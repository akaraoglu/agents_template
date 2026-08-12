from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..canonical import canonical_sha256
from ..models import (
    ActorRef,
    ContextPack,
    MailboxMessage,
    PermissionOperation,
    PermissionResource,
    RoleInstance,
    project_path_pattern_matches,
)
from .base import (
    DefectPacket,
    DraftTurn,
    ProbeResult,
    PreflightReceipt,
    RenderedContext,
    RuntimeBackendError,
    RuntimeOutputError,
    RuntimeSessionError,
    StageSemantic,
    SemanticResponse,
)


class FakeRuntimeAdapter:
    """Deterministic in-process adapter. It never invokes a shell or network client."""

    def __init__(self, scenario: str | Path | Mapping[str, Any], *, workspace: str | Path) -> None:
        if isinstance(scenario, Mapping):
            data = dict(scenario)
        else:
            path = Path(scenario)
            data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("stages", {}), dict):
            raise ValueError("fake scenario must be an object with a stages object")
        self.scenario = data
        self.workspace = Path(workspace).resolve(strict=True)
        supplied_workspace = data.get("workspace")
        if supplied_workspace is not None and Path(str(supplied_workspace)).resolve() != self.workspace:
            raise ValueError("fake scenario workspace does not match the canonical workspace")
        self.calls: list[dict[str, Any]] = []
        self._sessions: dict[str, RoleInstance] = {}
        self._candidate_indexes: dict[str, int] = {}
        self._feedback_indexes: dict[str, int] = {}

    def _stage(self, role: RoleInstance) -> dict[str, Any]:
        value = self.scenario.get("stages", {}).get(role.stage_id, {})
        if not isinstance(value, dict):
            raise RuntimeBackendError(f"invalid fake stage scenario for {role.stage_id}")
        return value

    @staticmethod
    def _inspect_context(context: RenderedContext) -> None:
        for item in context.items:
            if hashlib.sha256(item.content.encode("utf-8")).hexdigest() != item.content_digest:
                raise RuntimeOutputError("fake received context with a bad content digest")
        if context.rendered_digest != canonical_sha256({
            "context_pack_digest": context.context_pack_digest,
            "items": context.items,
        }):
            raise RuntimeOutputError("fake received context with a bad rendered digest")

    @staticmethod
    def _inject(stage: Mapping[str, Any], turn: str) -> None:
        injection = stage.get("inject")
        if injection == f"timeout:{turn}":
            raise TimeoutError(f"injected fake {turn} timeout")
        if injection == f"failure:{turn}":
            raise RuntimeBackendError(f"injected fake {turn} failure")

    @staticmethod
    def _safe_write(workspace: Path, relative: str, content: str, role: RoleInstance) -> None:
        if relative.startswith("/") or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise RuntimeBackendError(f"unsafe fake write path: {relative!r}")
        if relative in {".git", ".codexteam"} or relative.startswith((".git/", ".codexteam/")):
            raise RuntimeBackendError("fake scenarios cannot write repository or runtime metadata")
        if not any(project_path_pattern_matches(pattern, relative) for pattern in role.assignment_scope):
            # The write is still performed inside the fixture so EvidenceManager proves it is forbidden.
            pass
        target = workspace.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def preflight(self, role_instance: RoleInstance, context_pack: ContextPack, workspace: Path) -> PreflightReceipt:
        stage = self._stage(role_instance)
        self.calls.append({"turn": "preflight", "stage": role_instance.stage_id, "role_instance_id": role_instance.role_instance_id})
        self._inject(stage, "preflight")
        backend_id = role_instance.backend.definition_id
        if stage.get("backend_mismatch"):
            backend_id = "mismatched-backend"
        observed_operations = list(role_instance.backend_supported_operations)
        missing_operation = stage.get("missing_operation")
        if missing_operation is not None:
            observed_operations = [item for item in observed_operations if item != PermissionOperation(missing_operation)]
        probes = []
        if missing_operation is not None:
            resource = {
                "read": PermissionResource.PROJECT_PATH,
                "write": PermissionResource.PROJECT_PATH,
                "execute": PermissionResource.PROCESS,
                "send": PermissionResource.MAILBOX,
            }.get(str(missing_operation), PermissionResource.PROJECT_PATH)
            probes.append(ProbeResult(
                operation=PermissionOperation(missing_operation),
                resource=resource,
                status="failed",
                evidence_summary=f"Injected missing {missing_operation} backend support.",
            ))
        if PermissionOperation.SEND in observed_operations and PermissionResource.MAILBOX in role_instance.backend_supported_resources:
            sender = ActorRef(
                actor_id="fake-preflight-agent",
                kind="agent",
                role_instance_id=role_instance.role_instance_id,
            )
            MailboxMessage(
                schema_version="2.0",
                kind="mailbox_message",
                message_id=f"preflight-{role_instance.role_instance_id}",
                sender=sender,
                recipient=ActorRef(actor_id="fake-preflight-orchestrator", kind="orchestrator"),
                correlation_id=f"preflight-{role_instance.role_instance_id}",
                idempotency_key=f"preflight-{role_instance.role_instance_id}",
                created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
                body={"kind": "question", "question": "Validate the bound mailbox route."},
            )
            probes.append(ProbeResult(
                operation=PermissionOperation.SEND,
                resource=PermissionResource.MAILBOX,
                status="failed" if stage.get("failed_probe") == "send:mailbox" else "passed",
                evidence_summary="Constructed and validated a typed agent-to-orchestrator mailbox message for the bound role.",
            ))
        if stage.get("missing_probe"):
            operation, resource = str(stage["missing_probe"]).split(":", 1)
            probes = [item for item in probes if (item.operation, item.resource) != (operation, resource)]
        return PreflightReceipt(
            role_instance_digest=role_instance.resolved_digest,
            context_pack_digest=context_pack.digest,
            catalog_digest=str(self.scenario.get("catalog_digest", "")),
            workspace=str(self.workspace),
            backend_id=backend_id,
            observed_capabilities=tuple(item.definition_id for item in role_instance.capabilities),
            probes=tuple(probes),
            enforcement_limitations=("fake adapter attests configured surfaces; no OS sandbox proof",),
        )

    def draft(self, role_instance: RoleInstance, context: RenderedContext, workspace: Path) -> DraftTurn:
        if workspace.resolve() != self.workspace:
            raise RuntimeBackendError("fake draft workspace differs from preflight workspace")
        stage = self._stage(role_instance)
        self.calls.append({"turn": "draft", "stage": role_instance.stage_id, "role_instance_id": role_instance.role_instance_id})
        self._inject(stage, "draft")
        self._inspect_context(context)
        expected_context = stage.get("expected_context")
        if expected_context is not None and not any(str(expected_context) in item.content for item in context.items):
            raise RuntimeOutputError("fake did not receive expected context content")
        self.calls[-1]["rendered_digest"] = context.rendered_digest
        self.calls[-1]["context_content"] = tuple(item.content for item in context.items)
        session_id = str(stage.get("session_id", f"fake-{role_instance.stage_id}-session"))
        existing = self._sessions.get(session_id)
        if existing is not None and existing != role_instance:
            raise RuntimeSessionError("fake session is already bound to a different RoleInstance")
        self._sessions[session_id] = role_instance
        for write in stage.get("draft_writes", ()):
            self._safe_write(self.workspace, str(write["path"]), str(write["content"]), role_instance)
        if stage.get("inject") == "failure_after_write:draft":
            raise RuntimeBackendError("injected fake draft failure after write")
        if stage.get("inject") == "malformed:draft":
            return {"session_id": session_id, "response": {"summary": 3}}  # type: ignore[return-value]
        return DraftTurn(
            session_id=session_id,
            response=SemanticResponse(summary=str(stage.get("draft_summary", f"Drafted {role_instance.stage_id}"))),
            consumed_context_digest=("0" * 64 if stage.get("context_mismatch") else context.rendered_digest),
        )

    def resume(
        self,
        session_id: str,
        role_instance: RoleInstance,
        context: RenderedContext,
        workspace: Path,
        *,
        candidate_sequence: int,
    ) -> DraftTurn:
        if workspace.resolve() != self.workspace:
            raise RuntimeBackendError("fake resume workspace differs from preflight workspace")
        self._inspect_context(context)
        existing = self._sessions.get(session_id)
        if existing is not None and existing != role_instance:
            raise RuntimeSessionError("fake session is already bound to a different RoleInstance")
        self._sessions[session_id] = role_instance
        self._candidate_indexes[session_id] = candidate_sequence
        self.calls.append({
            "turn": "resume",
            "stage": role_instance.stage_id,
            "session_id": session_id,
            "rendered_digest": context.rendered_digest,
            "context_content": tuple(item.content for item in context.items),
        })
        return DraftTurn(
            session_id=session_id,
            response=SemanticResponse(summary=f"Resumed {role_instance.stage_id}"),
            consumed_context_digest=context.rendered_digest,
        )

    def feedback(self, session_id: str, defect_packet: DefectPacket) -> SemanticResponse:
        role = self._sessions.get(session_id)
        if role is None:
            raise RuntimeSessionError("feedback used an unknown fake session")
        stage = self._stage(role)
        self.calls.append({"turn": "feedback", "stage": role.stage_id, "session_id": session_id, "role_instance_id": role.role_instance_id})
        self._inject(stage, "feedback")
        if stage.get("session_mismatch"):
            raise RuntimeSessionError("injected fake feedback session mismatch")
        index = self._feedback_indexes.get(session_id, 0)
        self._feedback_indexes[session_id] = index + 1
        writes = stage.get("feedback_writes", ())
        selected = writes[index] if writes and isinstance(writes[0], list) else writes
        for write in selected:
            self._safe_write(self.workspace, str(write["path"]), str(write["content"]), role)
        if stage.get("inject") == "failure_after_write:feedback":
            raise RuntimeBackendError("injected fake feedback failure after write")
        return SemanticResponse(summary=f"Corrected: {defect_packet.summary}")

    def candidate(self, session_id: str, *, read_only: bool) -> StageSemantic:
        role = self._sessions.get(session_id)
        if role is None:
            raise RuntimeSessionError("candidate used an unknown fake session")
        stage = self._stage(role)
        self.calls.append({"turn": "candidate", "stage": role.stage_id, "session_id": session_id, "role_instance_id": role.role_instance_id, "read_only": read_only})
        self._inject(stage, "candidate")
        if not read_only:
            raise RuntimeOutputError("fake candidate requires an explicit read-only turn")
        if stage.get("session_mismatch"):
            raise RuntimeSessionError("injected fake candidate session mismatch")
        for write in stage.get("candidate_writes", ()):
            self._safe_write(self.workspace, str(write["path"]), str(write["content"]), role)
        defaults: dict[str, Any] = {
            "discovery": {
                "stage": "discovery", "outcome": "succeeded",
                "requested_optional_stages": ("architecture", "ux"),
                "rationale": "Architecture and UX are needed for the CLI contract.",
            },
            "assurance": {
                "stage": "assurance", "outcome": "succeeded",
                "dispositions": ({"domain": "security_privacy", "disposition": "pass"},),
            },
            "review": {
                "stage": "review", "outcome": "succeeded", "decision": "ACCEPT",
                "rationale": "Independent evidence satisfies acceptance.",
            },
        }
        default = defaults.get(role.stage_id, {"stage": role.stage_id, "outcome": "succeeded"})
        evidence_type = {
            "discovery": "analysis",
            "architecture": "artifact",
            "ux": "artifact",
            "implementation": "artifact",
            "verification": "test_output",
            "assurance": "review",
            "review": "review",
        }[role.stage_id]
        default = {**default, "evidence": [{"evidence_type": evidence_type, "content": f"{role.stage_id} output\n"}]}
        values = stage.get("candidates") or (default,)
        index = self._candidate_indexes.get(session_id, 0)
        self._candidate_indexes[session_id] = index + 1
        value = values[min(index, len(values) - 1)]
        if stage.get("inject") == "malformed:candidate":
            return {"outcome": "succeeded", "authoritative_stage_id": role.stage_id}  # type: ignore[return-value]
        if not isinstance(value, Mapping):
            raise RuntimeOutputError("fake candidate must be an object")
        value = {**default, **value}
        from .base import STAGE_SEMANTIC_ADAPTER

        try:
            return STAGE_SEMANTIC_ADAPTER.validate_json(json.dumps(value), strict=True)
        except ValueError as exc:
            raise RuntimeOutputError(f"malformed runtime stage semantic: {exc}") from exc

    @property
    def sessions(self) -> dict[str, str]:
        return {role.stage_id: session for session, role in sorted(self._sessions.items())}


def scenario_digest(scenario: Mapping[str, Any]) -> str:
    return canonical_sha256(scenario)


__all__ = ["FakeRuntimeAdapter", "scenario_digest"]
