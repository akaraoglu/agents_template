"""Runtime dispatch adapter and response recorder for task execution."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from openclaw_agents.communication.topic_router import TopicRouter
from openclaw_agents.database.store import ControlPlaneStore, parse_timestamp, utc_now
from openclaw_agents.runtime.artifact_serializers import ArtifactSerializer
from openclaw_agents.scheduler.snapshot_store import SnapshotStore


TERMINAL_TASK_STATUSES = {"SUCCESS", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "CANCELLED"}
SANDBOX_PROFILE_BY_TASK_TYPE = {
    "IMPLEMENT_SOFTWARE_TASK": "coding_task",
    "TEST_SOFTWARE_TASK": "test_task",
}


@dataclass(slots=True)
class DispatchReceipt:
    task_id: str
    project_id: str
    agent_id: str
    attempt_id: str
    attempt_number: int
    run_id: str
    packet_ref: str
    runtime_backend: str
    model_profile: str
    sandbox_profile: str


@dataclass(slots=True)
class ResponseRecord:
    task_id: str
    project_id: str
    agent_id: str
    status: str
    run_id: str
    attempt_id: str
    artifact_refs: list[str]
    artifact_ids: list[str]
    snapshot_id: str | None


class ContractValidator:
    """Small schema validator with jsonschema fallback when available."""

    def __init__(self, schema_dir: str | Path) -> None:
        self.schema_dir = Path(schema_dir)
        self.schemas = {
            "task_envelope": json.loads((self.schema_dir / "task_envelope.schema.json").read_text()),
            "response_envelope": json.loads((self.schema_dir / "response_envelope.schema.json").read_text()),
        }
        try:
            import jsonschema  # type: ignore
        except Exception:  # pragma: no cover - optional dependency
            self._jsonschema = None
        else:
            self._jsonschema = jsonschema

    def validate(self, schema_name: str, payload: dict[str, Any]) -> None:
        schema = self.schemas[schema_name]
        if self._jsonschema is not None:
            self._jsonschema.validate(payload, schema)
            return
        self._validate_minimal(payload, schema, path="$")

    def _validate_minimal(self, payload: Any, schema: dict[str, Any], *, path: str) -> None:
        expected_type = schema.get("type")
        if expected_type == "object":
            if not isinstance(payload, dict):
                raise ValueError(f"{path} must be an object")
            for key in schema.get("required", []):
                if key not in payload:
                    raise ValueError(f"{path}.{key} is required")
            if schema.get("additionalProperties") is False:
                allowed = set(schema.get("properties", {}).keys())
                for key in payload:
                    if key not in allowed:
                        raise ValueError(f"{path}.{key} is not allowed")
            for key, subschema in schema.get("properties", {}).items():
                if key in payload:
                    self._validate_minimal(payload[key], subschema, path=f"{path}.{key}")
            return
        if expected_type == "array":
            if not isinstance(payload, list):
                raise ValueError(f"{path} must be an array")
            items_schema = schema.get("items")
            if items_schema:
                for index, item in enumerate(payload):
                    self._validate_minimal(item, items_schema, path=f"{path}[{index}]")
            return
        if isinstance(expected_type, list):
            errors = []
            for one_type in expected_type:
                try:
                    self._validate_minimal(payload, {**schema, "type": one_type}, path=path)
                    return
                except ValueError as exc:
                    errors.append(str(exc))
            raise ValueError("; ".join(errors))
        if "oneOf" in schema:
            for option in schema["oneOf"]:
                try:
                    self._validate_minimal(payload, option, path=path)
                    return
                except ValueError:
                    continue
            raise ValueError(f"{path} does not match any allowed schema variant")
        if expected_type == "string" and not isinstance(payload, str):
            raise ValueError(f"{path} must be a string")
        if expected_type == "integer" and not isinstance(payload, int):
            raise ValueError(f"{path} must be an integer")
        if expected_type == "boolean" and not isinstance(payload, bool):
            raise ValueError(f"{path} must be a boolean")
        if "enum" in schema and payload not in schema["enum"]:
            raise ValueError(f"{path} must be one of {schema['enum']}")
        if "minLength" in schema and isinstance(payload, str) and len(payload) < schema["minLength"]:
            raise ValueError(f"{path} is shorter than {schema['minLength']}")


class RuntimeDispatcher:
    """Create task execution packets and persist runtime lifecycle state."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        model_map_path: str | Path | None = None,
        routing_rules_path: str | Path | None = None,
        state_dir: str | Path | None = None,
        snapshot_store: SnapshotStore | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        base = Path(__file__).resolve().parents[1]
        self.model_map = yaml.safe_load(Path(model_map_path or base / "config" / "model_map.yaml").read_text())
        self.routing_rules = yaml.safe_load(Path(routing_rules_path or base / "config" / "routing_rules.yaml").read_text())
        self.router = TopicRouter(
            yaml.safe_load((base / "communication" / "zulip_gateway_config.yaml").read_text())
        )
        self.state_dir = Path(state_dir or "/tmp/openclaw_runtime_dispatch")
        self.validator = ContractValidator(base / "schemas")
        self.artifact_serializer = ArtifactSerializer(self.store)
        self.snapshot_store = snapshot_store or SnapshotStore(self.store)

    def _model_profile_for_task(self, agent_id: str, task_type: str) -> str:
        overrides = ((self.model_map.get("overrides") or {}).get("by_task_type") or {}).get(task_type) or {}
        if overrides.get("preferred_profile"):
            return overrides["preferred_profile"]
        return ((self.model_map.get("assignments") or {}).get(agent_id) or {}).get("profile", "ollama_default")

    def _sandbox_profile_for_task(self, task_type: str) -> str:
        return SANDBOX_PROFILE_BY_TASK_TYPE.get(task_type, "structured_reasoning")

    def _resolve_return_target(self, task: dict[str, Any]) -> str:
        return task["from_agent"] if task["return_to"] == "requesting_agent" else task["return_to"]

    def _packet_root(self, project_id: str, workspace_ref: str | None) -> Path:
        if workspace_ref:
            root = Path(workspace_ref) / "artifacts" / "incoming"
        else:
            root = self.state_dir / project_id / "incoming"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _build_task_envelope(
        self,
        *,
        task: dict[str, Any],
        project: dict[str, Any],
        plan_reason: str,
        reply_stream: str,
        reply_topic: str,
        attempt_id: str,
        run_id: str,
        model_profile: str,
        sandbox_profile: str,
        packet_ref: str,
    ) -> dict[str, Any]:
        envelope = {
            "task_id": task["task_id"],
            "project_id": task["project_id"],
            "from_agent": task["from_agent"],
            "to_agent": task["to_agent"],
            "task_type": task["task_type"],
            "title": task["title"],
            "goal": task["goal"],
            "priority": task["priority"],
            "context": task.get("context_json") or {},
            "expected_output": task.get("expected_output_json") or {},
            "decision_bounds": task.get("decision_bounds_json") or {},
            "return_to": task["return_to"],
            "artifacts_in": self.store.list_recent_artifact_refs(task["project_id"]),
            "metadata": {
                "attempt_id": attempt_id,
                "run_id": run_id,
                "workspace_ref": project.get("workspace_ref"),
                "reply_stream": reply_stream,
                "reply_topic": reply_topic,
                "model_profile": model_profile,
                "sandbox_profile": sandbox_profile,
                "packet_ref": packet_ref,
                "dispatch_reason": plan_reason,
                "queued_at": utc_now(),
            },
        }
        if task.get("parent_task_id"):
            envelope["parent_task_id"] = task["parent_task_id"]
        self.validator.validate("task_envelope", envelope)
        return envelope

    def dispatch_plan(self, plan: Any) -> DispatchReceipt:
        task = self.store.get_task(plan.task_id)
        if not task:
            raise ValueError(f"unknown task {plan.task_id}")
        project = self.store.get_project(plan.project_id)
        if not project:
            raise ValueError(f"unknown project {plan.project_id}")

        attempt_number = self.store.next_attempt_number(plan.task_id)
        attempt_id = self.store.new_id("attempt")
        run_id = self.store.new_id("run")
        model_profile = self._model_profile_for_task(plan.target_agent, plan.task_type)
        sandbox_profile = self._sandbox_profile_for_task(plan.task_type)
        packet_root = self._packet_root(plan.project_id, project.get("workspace_ref"))
        packet_path = packet_root / f"{plan.task_id}_{attempt_id}.yaml"

        envelope = self._build_task_envelope(
            task=task,
            project=project,
            plan_reason=plan.reason,
            reply_stream=plan.reply_stream,
            reply_topic=plan.reply_topic,
            attempt_id=attempt_id,
            run_id=run_id,
            model_profile=model_profile,
            sandbox_profile=sandbox_profile,
            packet_ref=str(packet_path),
        )
        packet_path.write_text(yaml.safe_dump(envelope, sort_keys=False))

        self.store.record_task_attempt(
            task_id=plan.task_id,
            project_id=plan.project_id,
            agent_id=plan.target_agent,
            attempt_number=attempt_number,
            status="PENDING",
            workspace_ref=project.get("workspace_ref"),
            input_artifact_refs=envelope["artifacts_in"],
            summary=f"queued runtime packet at {packet_path}",
            attempt_id=attempt_id,
        )
        self.store.record_agent_run(
            run_id=run_id,
            task_id=plan.task_id,
            project_id=plan.project_id,
            agent_id=plan.target_agent,
            model_profile=model_profile,
            model_used=None,
            runtime_backend="workspace_queue",
            sandbox_id=sandbox_profile,
            session_id=attempt_id,
            result_status="PENDING",
            raw_transcript_ref=None,
            log_ref=str(packet_path),
        )
        self.store.update(
            "tasks",
            {"status": "RUNNING", "updated_at": utc_now()},
            where_clause="task_id = ?",
            where_params=[plan.task_id],
        )
        self.store.update(
            "projects",
            {
                "current_owner_agent": plan.target_agent,
                "last_activity_at": utc_now(),
                "updated_at": utc_now(),
                "next_action_json": {
                    "type": plan.task_type,
                    "target_agent": plan.target_agent,
                    "task_id": plan.task_id,
                    "run_id": run_id,
                    "packet_ref": str(packet_path),
                },
            },
            where_clause="project_id = ?",
            where_params=[plan.project_id],
        )
        return DispatchReceipt(
            task_id=plan.task_id,
            project_id=plan.project_id,
            agent_id=plan.target_agent,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            run_id=run_id,
            packet_ref=str(packet_path),
            runtime_backend="workspace_queue",
            model_profile=model_profile,
            sandbox_profile=sandbox_profile,
        )

    def _artifact_backend_for_ref(self, ref: str) -> str:
        if ref.startswith("inline://"):
            return "inline_json"
        if Path(ref).exists():
            return "workspace"
        return "external_ref"

    def _persist_output_artifacts(
        self,
        *,
        project_id: str,
        task_id: str,
        agent_id: str,
        workspace_ref: str | None,
        artifacts_out: list[Any],
    ) -> tuple[list[str], list[str]]:
        artifact_refs: list[str] = []
        artifact_ids: list[str] = []
        for item in artifacts_out:
            if isinstance(item, str):
                artifact_refs.append(item)
                continue
            artifact_type = item["artifact_type"]
            metadata = item.get("metadata") or {}
            if "payload" in item:
                record = self.artifact_serializer.serialize(
                    project_id=project_id,
                    artifact_type=artifact_type,
                    payload=item["payload"],
                    task_id=task_id,
                    produced_by_agent=agent_id,
                    workspace_ref=item.get("workspace_ref", workspace_ref),
                    filename=item.get("filename"),
                    metadata=metadata,
                )
            else:
                ref = item["ref"]
                record = {
                    "artifact_id": self.store.new_id("artifact"),
                    "project_id": project_id,
                    "task_id": task_id,
                    "produced_by_agent": agent_id,
                    "artifact_type": artifact_type,
                    "store_backend": self._artifact_backend_for_ref(ref),
                    "ref": ref,
                    "content_hash": None,
                    "metadata_json": metadata,
                    "created_at": utc_now(),
                }
                self.store.upsert("artifacts", record, conflict_columns=["artifact_id"])
            artifact_refs.append(record["ref"])
            artifact_ids.append(record["artifact_id"])
        return artifact_refs, artifact_ids

    def _safe_boundary_for_response(self, artifact_types: set[str]) -> str:
        if "verification_report" in artifact_types:
            return "ORACLE_REPORT_PERSISTED"
        if "software_delivery_package" in artifact_types:
            return "MORPHEUS_DELIVERY_PERSISTED"
        if "project_status_report" in artifact_types or "project_closure_report" in artifact_types:
            return "PROJECT_STATUS_SNAPSHOT_PERSISTED"
        if "escalation_packet" in artifact_types:
            return "ESCALATION_PERSISTED"
        return "TASK_RESULT_PERSISTED"

    def record_response(self, response: dict[str, Any]) -> ResponseRecord:
        self.validator.validate("response_envelope", response)
        task = self.store.get_task(response["task_id"])
        if not task:
            raise ValueError(f"unknown task {response['task_id']}")
        project = self.store.get_project(response["project_id"])
        if not project:
            raise ValueError(f"unknown project {response['project_id']}")
        run = self.store.get_agent_run(response["trace"]["run_id"])
        if not run:
            raise ValueError(f"unknown run {response['trace']['run_id']}")
        attempt = self.store.get_active_task_attempt(response["task_id"]) or self.store.get_latest_task_attempt(response["task_id"])
        if not attempt:
            raise ValueError(f"no task attempt found for {response['task_id']}")

        artifact_refs, artifact_ids = self._persist_output_artifacts(
            project_id=response["project_id"],
            task_id=response["task_id"],
            agent_id=response["agent"],
            workspace_ref=project.get("workspace_ref"),
            artifacts_out=response["artifacts_out"],
        )

        now = utc_now()
        run_started = parse_timestamp(run.get("started_at"))
        run_finished = parse_timestamp(now)
        duration_ms = None
        if run_started and run_finished:
            duration_ms = max(int((run_finished - run_started).total_seconds() * 1000), 0)

        self.store.update(
            "task_attempts",
            {
                "status": response["status"],
                "output_artifact_refs_json": artifact_refs,
                "summary": response["summary"],
                "finished_at": now,
            },
            where_clause="attempt_id = ?",
            where_params=[attempt["attempt_id"]],
        )
        self.store.update(
            "agent_runs",
            {
                "result_status": response["status"],
                "ended_at": now,
                "duration_ms": duration_ms,
            },
            where_clause="run_id = ?",
            where_params=[run["run_id"]],
        )
        task_updates = {
            "status": response["status"],
            "updated_at": now,
        }
        if response["status"] in TERMINAL_TASK_STATUSES:
            task_updates["closed_at"] = now
        self.store.update("tasks", task_updates, where_clause="task_id = ?", where_params=[response["task_id"]])

        next_owner = self._resolve_return_target(task)
        next_action = dict(response["next_action"])
        next_action.setdefault("from_task_id", response["task_id"])
        if next_action.get("target_agent"):
            next_owner = next_action["target_agent"]
        elif response["status"] in {"PENDING", "RUNNING"}:
            next_owner = response["agent"]
        project_updates = {
            "current_owner_agent": next_owner,
            "last_activity_at": now,
            "updated_at": now,
            "next_action_json": next_action,
            "runtime_status": "WAITING_EXTERNAL" if next_action["type"] == "WAIT_FOR_EXTERNAL" else "ACTIVE",
        }
        self.store.update(
            "projects",
            project_updates,
            where_clause="project_id = ?",
            where_params=[response["project_id"]],
        )

        artifact_types = {item["artifact_type"] for item in response["artifacts_out"] if isinstance(item, dict) and "artifact_type" in item}
        boundary = self._safe_boundary_for_response(artifact_types)
        snapshot = None
        if project.get("workspace_ref"):
            snapshot = self.snapshot_store.capture_project_snapshot(
                response["project_id"],
                captured_by=response["agent"],
                latest_human_summary=response["summary"],
                safe_boundary_type=boundary,
                created_from_run_id=run["run_id"],
            )

        return ResponseRecord(
            task_id=response["task_id"],
            project_id=response["project_id"],
            agent_id=response["agent"],
            status=response["status"],
            run_id=run["run_id"],
            attempt_id=attempt["attempt_id"],
            artifact_refs=artifact_refs,
            artifact_ids=artifact_ids,
            snapshot_id=snapshot["snapshot_id"] if snapshot else None,
        )


def _load_response_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text()
    if path.suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not decode to an object")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runtime dispatch adapter for OpenClaw agents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dispatch_parser = subparsers.add_parser("dispatch-task", help="Queue a persisted task for runtime execution")
    dispatch_parser.add_argument("--task-id", required=True)

    response_parser = subparsers.add_parser("record-response", help="Persist a response envelope into the state store")
    response_parser.add_argument("--file", required=True, help="Path to a YAML or JSON response envelope")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dispatcher = RuntimeDispatcher()
    if args.command == "dispatch-task":
        task = dispatcher.store.get_task(args.task_id)
        if not task:
            raise SystemExit(f"unknown task {args.task_id}")
        reply_stream, reply_topic = dispatcher.router.reply_address_for_task(
            task["project_id"],
            task["task_id"],
            task["task_type"],
        )
        plan = SimpleNamespace(
            project_id=task["project_id"],
            task_id=task["task_id"],
            target_agent=task["to_agent"],
            task_type=task["task_type"],
            reply_stream=reply_stream,
            reply_topic=reply_topic,
            reason=task["goal"],
        )
        receipt = dispatcher.dispatch_plan(plan)
        print(json.dumps(asdict(receipt), indent=2, sort_keys=True))
        return 0
    if args.command == "record-response":
        payload = _load_response_file(args.file)
        record = dispatcher.record_response(payload)
        from openclaw_agents.runtime.role_executor import BuiltinRoleExecutor

        BuiltinRoleExecutor(dispatcher=dispatcher).handle_recorded_response(payload, record)
        print(json.dumps(asdict(record), indent=2, sort_keys=True))
        return 0
    raise SystemExit(f"unsupported command {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
