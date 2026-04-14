"""Active-project lease management for singleton orchestrators."""

from __future__ import annotations

from dataclasses import dataclass

from openclaw_agents.database.store import ControlPlaneStore, parse_timestamp, utc_now


class LeaseConflictError(RuntimeError):
    """Raised when another active lease prevents acquisition."""


@dataclass(slots=True)
class LeaseDecision:
    orchestrator_id: str
    project_id: str | None
    lease_status: str
    lease_expires_at: str | None
    renewed: bool = False


class LeaseManager:
    """Manage singleton orchestrator leases backed by the control-plane store."""

    DEFAULT_TTLS = {"niobe": 30, "morpheus": 60}

    def __init__(self, store: ControlPlaneStore | None = None) -> None:
        self.store = store or ControlPlaneStore()
        self.store.ensure_orchestrator_leases()

    def _ensure_run_record(self, *, run_id: str, project_id: str, orchestrator_id: str, now: str) -> None:
        with self.store.transaction() as conn:
            existing = self.store.fetchone("SELECT run_id FROM agent_runs WHERE run_id = ?", (run_id,), conn=conn)
            if existing:
                return
            self.store.upsert(
                "agent_runs",
                {
                    "run_id": run_id,
                    "task_id": None,
                    "project_id": project_id,
                    "agent_id": orchestrator_id,
                    "model_profile": "scheduler_control_plane",
                    "model_used": None,
                    "runtime_backend": "control_plane",
                    "sandbox_id": None,
                    "session_id": None,
                    "result_status": "RUNNING",
                    "raw_transcript_ref": None,
                    "log_ref": None,
                    "started_at": now,
                    "ended_at": None,
                    "duration_ms": None,
                },
                conflict_columns=["run_id"],
                conn=conn,
            )

    def get_lease(self, orchestrator_id: str) -> dict | None:
        return self.store.get_lease(orchestrator_id)

    def lease_is_expired(self, lease: dict | None, *, now: str | None = None) -> bool:
        if not lease or lease.get("lease_status") != "HELD":
            return False
        expires_at = parse_timestamp(lease.get("lease_expires_at"))
        if expires_at is None:
            return False
        compare_at = parse_timestamp(now) if now else parse_timestamp(utc_now())
        return bool(compare_at and expires_at <= compare_at)

    def acquire(
        self,
        orchestrator_id: str,
        project_id: str,
        *,
        run_id: str,
        ttl_minutes: int | None = None,
        now: str | None = None,
    ) -> LeaseDecision:
        now = now or utc_now()
        ttl_minutes = ttl_minutes or self.DEFAULT_TTLS[orchestrator_id]
        lease = self.get_lease(orchestrator_id)
        self._ensure_run_record(run_id=run_id, project_id=project_id, orchestrator_id=orchestrator_id, now=now)

        if lease and lease.get("lease_status") == "HELD":
            if self.lease_is_expired(lease, now=now):
                self.release(orchestrator_id, release_reason="expired-before-acquire")
            elif lease.get("active_project_id") != project_id:
                raise LeaseConflictError(
                    f"{orchestrator_id} already holds project {lease.get('active_project_id')}"
                )
            else:
                return self.renew(orchestrator_id, run_id=run_id, ttl_minutes=ttl_minutes, now=now)

        expires_at = parse_timestamp(now)
        assert expires_at is not None
        expires_at = expires_at.replace(microsecond=0)
        lease_expires_at = expires_at.timestamp() + ttl_minutes * 60
        lease_expires_at_str = parse_timestamp(now).fromtimestamp(lease_expires_at, tz=expires_at.tzinfo)
        lease_expires_at_str = lease_expires_at_str.isoformat().replace("+00:00", "Z")

        self.store.upsert(
            "orchestrator_leases",
            {
                "orchestrator_id": orchestrator_id,
                "lease_status": "HELD",
                "active_project_id": project_id,
                "lease_owner_run_id": run_id,
                "lease_acquired_at": now,
                "lease_expires_at": lease_expires_at_str,
                "released_at": None,
                "release_reason": None,
            },
            conflict_columns=["orchestrator_id"],
        )
        return LeaseDecision(orchestrator_id, project_id, "HELD", lease_expires_at_str)

    def renew(
        self,
        orchestrator_id: str,
        *,
        run_id: str,
        ttl_minutes: int | None = None,
        now: str | None = None,
    ) -> LeaseDecision:
        now = now or utc_now()
        ttl_minutes = ttl_minutes or self.DEFAULT_TTLS[orchestrator_id]
        lease = self.get_lease(orchestrator_id)
        if not lease or lease.get("lease_status") != "HELD":
            raise LeaseConflictError(f"{orchestrator_id} does not currently hold a lease")
        if lease.get("lease_owner_run_id") not in {None, run_id}:
            raise LeaseConflictError(
                f"{orchestrator_id} lease is owned by {lease.get('lease_owner_run_id')}, not {run_id}"
            )

        expires_at = parse_timestamp(now)
        assert expires_at is not None
        lease_expires_at = expires_at.timestamp() + ttl_minutes * 60
        lease_expires_at_str = parse_timestamp(now).fromtimestamp(lease_expires_at, tz=expires_at.tzinfo)
        lease_expires_at_str = lease_expires_at_str.isoformat().replace("+00:00", "Z")

        renew_count = int(lease.get("renew_count") or 0) + 1
        self.store.update(
            "orchestrator_leases",
            {
                "lease_status": "HELD",
                "lease_owner_run_id": run_id,
                "lease_expires_at": lease_expires_at_str,
                "renew_count": renew_count,
            },
            where_clause="orchestrator_id = ?",
            where_params=[orchestrator_id],
        )
        return LeaseDecision(
            orchestrator_id,
            lease.get("active_project_id"),
            "HELD",
            lease_expires_at_str,
            renewed=True,
        )

    def release(
        self,
        orchestrator_id: str,
        *,
        release_reason: str,
        expected_project_id: str | None = None,
        expected_run_id: str | None = None,
    ) -> LeaseDecision:
        lease = self.get_lease(orchestrator_id)
        if not lease:
            return LeaseDecision(orchestrator_id, None, "FREE", None)
        if expected_project_id and lease.get("active_project_id") != expected_project_id:
            raise LeaseConflictError(
                f"{orchestrator_id} lease points at {lease.get('active_project_id')}, not {expected_project_id}"
            )
        if expected_run_id and lease.get("lease_owner_run_id") not in {None, expected_run_id}:
            raise LeaseConflictError(
                f"{orchestrator_id} lease is owned by {lease.get('lease_owner_run_id')}, not {expected_run_id}"
            )

        released_at = utc_now()
        self.store.update(
            "orchestrator_leases",
            {
                "lease_status": "FREE",
                "active_project_id": None,
                "lease_owner_run_id": None,
                "lease_acquired_at": None,
                "lease_expires_at": None,
                "released_at": released_at,
                "release_reason": release_reason,
            },
            where_clause="orchestrator_id = ?",
            where_params=[orchestrator_id],
        )
        return LeaseDecision(orchestrator_id, None, "FREE", None)

    def release_project_leases(self, project_id: str, *, release_reason: str) -> None:
        for orchestrator_id in ("niobe", "morpheus"):
            lease = self.get_lease(orchestrator_id)
            if lease and lease.get("active_project_id") == project_id:
                self.release(orchestrator_id, release_reason=release_reason, expected_project_id=project_id)

    def expire_stale_leases(self, *, now: str | None = None) -> list[dict]:
        now = now or utc_now()
        expired: list[dict] = []
        for orchestrator_id in ("niobe", "morpheus"):
            lease = self.get_lease(orchestrator_id)
            if self.lease_is_expired(lease, now=now):
                expired.append(lease or {})
                self.store.update(
                    "orchestrator_leases",
                    {
                        "lease_status": "EXPIRED",
                        "released_at": now,
                        "release_reason": "lease-expired",
                    },
                    where_clause="orchestrator_id = ?",
                    where_params=[orchestrator_id],
                )
        return expired
