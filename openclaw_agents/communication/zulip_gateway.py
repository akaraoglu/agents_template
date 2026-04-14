"""Zulip gateway normalization, validation, and dispatch planning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.communication.message_mapping_store import MessageMappingStore
from openclaw_agents.communication.topic_router import RouteContext, TopicRouter
from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.scheduler.control_commands import ControlCommandResult, ControlCommandService
from openclaw_agents.scheduler.project_scheduler import ProjectScheduler
from openclaw_agents.scheduler.workspace_provisioner import ProjectWorkspaceProvisioner


def load_gateway_config(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text())


@dataclass(slots=True)
class GatewayEvent:
    message_id: str
    sender_name: str
    sender_type: str
    stream_name: str
    topic_name: str
    content: str
    sender_id: str | None = None


@dataclass(slots=True)
class InboundEnvelope:
    summary: str
    payload: dict[str, Any] | None
    route: RouteContext
    authoritative: bool
    schema_name: str | None
    kind: str


@dataclass(slots=True)
class DispatchPlan:
    project_id: str
    task_id: str
    target_agent: str
    task_type: str
    reply_stream: str
    reply_topic: str
    reason: str


@dataclass(slots=True)
class GatewayResult:
    status: str
    summary: str
    project_id: str | None = None
    task_id: str | None = None
    control_event_id: str | None = None
    dispatch_plan: DispatchPlan | None = None
    outbound_message: str | None = None
    envelope: InboundEnvelope | None = None


class SchemaValidationError(ValueError):
    """Raised when a schema block does not match the expected contract."""


class SchemaValidator:
    """Validate gateway YAML blocks against the committed schema files."""

    def __init__(self, schema_dir: str | Path) -> None:
        self.schema_dir = Path(schema_dir)
        self.schemas = {
            "task_assignment": json.loads((self.schema_dir / "zulip_task_message.schema.json").read_text()),
            "task_result": json.loads((self.schema_dir / "zulip_result_message.schema.json").read_text()),
            "control_event": json.loads((self.schema_dir / "control_event.schema.json").read_text()),
        }
        try:
            import jsonschema  # type: ignore
        except Exception:  # pragma: no cover - fallback path
            self._jsonschema = None
        else:
            self._jsonschema = jsonschema

    def validate(self, schema_name: str, payload: dict[str, Any]) -> None:
        schema = self.schemas[schema_name]
        if self._jsonschema is not None:
            try:
                self._jsonschema.validate(payload, schema)
            except Exception as exc:  # pragma: no cover - depends on jsonschema internals
                raise SchemaValidationError(str(exc)) from exc
            return
        self._validate_minimal(payload, schema, path="$")

    def _validate_minimal(self, payload: Any, schema: dict[str, Any], *, path: str) -> None:
        expected_type = schema.get("type")
        if expected_type == "object":
            if not isinstance(payload, dict):
                raise SchemaValidationError(f"{path} must be an object")
            for key in schema.get("required", []):
                if key not in payload:
                    raise SchemaValidationError(f"{path}.{key} is required")
            if schema.get("additionalProperties") is False:
                allowed = set(schema.get("properties", {}).keys())
                for key in payload:
                    if key not in allowed:
                        raise SchemaValidationError(f"{path}.{key} is not allowed")
            for key, subschema in schema.get("properties", {}).items():
                if key in payload:
                    self._validate_minimal(payload[key], subschema, path=f"{path}.{key}")
            return
        if expected_type == "array":
            if not isinstance(payload, list):
                raise SchemaValidationError(f"{path} must be an array")
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
                    break
                except SchemaValidationError as exc:
                    errors.append(str(exc))
            else:
                raise SchemaValidationError("; ".join(errors))
            return
        if "oneOf" in schema:
            for option in schema["oneOf"]:
                try:
                    self._validate_minimal(payload, option, path=path)
                    return
                except SchemaValidationError:
                    continue
            raise SchemaValidationError(f"{path} does not match any allowed schema variant")
        if expected_type == "string" and not isinstance(payload, str):
            raise SchemaValidationError(f"{path} must be a string")
        if expected_type == "integer" and not isinstance(payload, int):
            raise SchemaValidationError(f"{path} must be an integer")
        if expected_type == "boolean" and not isinstance(payload, bool):
            raise SchemaValidationError(f"{path} must be a boolean")
        if "minLength" in schema and isinstance(payload, str) and len(payload) < schema["minLength"]:
            raise SchemaValidationError(f"{path} is shorter than {schema['minLength']}")
        if "minimum" in schema and isinstance(payload, int) and payload < schema["minimum"]:
            raise SchemaValidationError(f"{path} is less than {schema['minimum']}")
        if "const" in schema and payload != schema["const"]:
            raise SchemaValidationError(f"{path} must equal {schema['const']}")
        if "enum" in schema and payload not in schema["enum"]:
            raise SchemaValidationError(f"{path} must be one of {schema['enum']}")


class ZulipGateway:
    """Normalize inbound Zulip messages and produce control-plane actions."""

    _YAML_BLOCK_RE = re.compile(r"```yaml\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    _MILESTONE_RE = re.compile(r"^Milestone\s+(\d+)\s*:\s*(.+?)\s*$", re.IGNORECASE)
    _PROJECT_NAME_RE = re.compile(r"^(?:Start|Initiate)\s+(?:a\s+)?(?:new\s+)?(?:sample\s+)?software project:\s*(.+?)\.?\s*$", re.IGNORECASE)
    _SECTION_MAP = {
        "project goal": "project_goal",
        "requirements": "requirements",
        "acceptance criteria": "acceptance_criteria",
        "execution requirements": "execution_requirements",
        "project-wide constraints": "project_constraints",
        "project management requirements": "management_requirements",
        "constraints": "constraints",
        "dependencies": "dependencies",
        "open questions": "open_questions",
        "non-goals": "non_goals",
        "non goals": "non_goals",
    }
    _STEP_LABELS = {
        "FRAME_PROJECT": (1, 5, "Intake Framing"),
        "CLARIFY_GOAL": (1, 5, "Clarification"),
        "ORCHESTRATE_PROJECT": (2, 5, "Project Orchestration"),
        "DESIGN_ARCHITECTURE": (2, 5, "Architecture"),
        "REQUEST_ARCHITECTURE_CLARIFICATION": (2, 5, "Architecture Clarification"),
        "ORCHESTRATE_SOFTWARE": (3, 5, "Software Delivery"),
        "PLAN_SOFTWARE_TASK": (3, 5, "Software Planning"),
        "IMPLEMENT_SOFTWARE_TASK": (3, 5, "Implementation"),
        "TEST_SOFTWARE_TASK": (3, 5, "Software Testing"),
        "VERIFY_PROJECT": (4, 5, "Verification"),
        "RESOLVE_ESCALATION": (4, 5, "Escalation Resolution"),
        "APPROVE_PRIORITY": (4, 5, "Priority Approval"),
        "CLOSE_PROJECT": (5, 5, "Closure"),
    }

    def __init__(
        self,
        *,
        gateway_config_path: str | Path | None = None,
        routing_rules_path: str | Path | None = None,
        agent_registry_path: str | Path | None = None,
        store: ControlPlaneStore | None = None,
        scheduler: ProjectScheduler | None = None,
        control_commands: ControlCommandService | None = None,
        mapping_store: MessageMappingStore | None = None,
        workspace_provisioner: ProjectWorkspaceProvisioner | None = None,
    ) -> None:
        base = Path(__file__).resolve().parents[1]
        self.gateway_config = load_gateway_config(
            gateway_config_path or base / "communication" / "zulip_gateway_config.yaml"
        )
        self.routing_rules = yaml.safe_load(
            Path(routing_rules_path or base / "config" / "routing_rules.yaml").read_text()
        )
        self.agent_registry = yaml.safe_load(
            Path(agent_registry_path or base / "config" / "agent_registry.yaml").read_text()
        )
        self.store = store or ControlPlaneStore()
        self.scheduler = scheduler or ProjectScheduler(self.store)
        self.control_commands = control_commands or ControlCommandService(self.store)
        self.mapping_store = mapping_store or MessageMappingStore(self.store)
        self.workspace_provisioner = workspace_provisioner or ProjectWorkspaceProvisioner(self.store)
        self.router = TopicRouter(self.gateway_config)
        self.schema_validator = SchemaValidator(base / "schemas")
        self.alias_to_agent = self._build_agent_aliases()

    def _build_agent_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for agent_id, config in self.agent_registry.get("agents", {}).items():
            for candidate in [agent_id, config.get("display_name"), *(config.get("aliases") or [])]:
                if candidate:
                    aliases[self._slugify(candidate)] = agent_id
        return aliases

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
        return slug.strip("_")

    def canonicalize_agent(self, value: str) -> str:
        key = self._slugify(value)
        return self.alias_to_agent.get(key, key)

    def agent_display_name(self, agent_id: str) -> str:
        config = (self.agent_registry.get("agents") or {}).get(agent_id) or {}
        return str(config.get("display_name") or agent_id)

    def project_feedback_address(self, project_id: str) -> tuple[str, str] | None:
        return self.store.get_project_feedback_thread(project_id)

    def reply_address_for_task(self, project_id: str, task_id: str, task_type: str) -> tuple[str, str]:
        feedback_address = self.project_feedback_address(project_id)
        if feedback_address:
            return feedback_address
        return self.router.reply_address_for_task(project_id, task_id, task_type)

    def control_event_address(self, project_id: str) -> tuple[str, str]:
        feedback_address = self.project_feedback_address(project_id)
        if feedback_address:
            return feedback_address
        return self.router.control_event_topic(project_id)

    def _step_label(self, task_type: str) -> str:
        index, total, label = self._STEP_LABELS.get(task_type, (0, 0, task_type))
        return f"[{index}/{total}] {label}" if index and total else label

    def _assignment_next_text(self, task_type: str, target_agent: str) -> str:
        if task_type == "ORCHESTRATE_SOFTWARE":
            return "Morpheus will drive plan -> implement -> test inside the software loop."
        if task_type == "VERIFY_PROJECT":
            return "Oracle will verify the delivered package and return a pass, fail, or clarification result."
        if task_type == "DESIGN_ARCHITECTURE":
            return "Architect will produce an implementable architecture and hand it back to Niaobe."
        if task_type == "FRAME_PROJECT":
            return "AgentSmith will frame the request into a project charter for Niaobe."
        if task_type == "CLOSE_PROJECT":
            return "Niaobe will finalize the project and return the closure report."
        return f"{self.agent_display_name(target_agent)} will continue this step and report back."

    def _next_step_text(self, next_action: dict[str, Any]) -> str:
        action_type = str(next_action.get("type") or "").upper()
        target_agent = str(next_action.get("target_agent") or "").strip()
        if action_type == "WAIT_FOR_EXTERNAL":
            owner = self.agent_display_name(target_agent) if target_agent else "the assigned agent"
            return f"Waiting for {owner} to finish the active step."
        if action_type == "RETURN_TO_REQUESTER":
            owner = self.agent_display_name(target_agent) if target_agent else "the requesting agent"
            return f"Return to {owner}."
        if action_type == "CLOSE_PROJECT":
            return "Niaobe will finalize project closure."
        if target_agent:
            return f"Next owner: {self.agent_display_name(target_agent)}."
        if action_type:
            return f"Next action: {action_type}."
        return "No next step recorded."

    def extract_yaml_payload(self, content: str) -> tuple[str, dict[str, Any] | None]:
        match = self._YAML_BLOCK_RE.search(content)
        if not match:
            return content.strip(), None
        summary = content[: match.start()].strip()
        payload = yaml.safe_load(match.group(1)) or {}
        if not isinstance(payload, dict):
            raise SchemaValidationError("YAML block must decode to an object")
        return summary, payload

    def _schema_name_for_payload(self, payload: dict[str, Any]) -> str | None:
        if "command" in payload:
            return "control_event"
        kind = payload.get("kind")
        if kind == "task_assignment":
            return "task_assignment"
        if kind in {"task_result", "status_update"}:
            return "task_result"
        return None

    def _normalize_control_payload(self, event: GatewayEvent, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        normalized.setdefault("event_id", self.store.new_id("ctrl"))
        normalized.setdefault("project_id", payload.get("project_id"))
        normalized.setdefault("requested_by", event.sender_name)
        normalized.setdefault("requested_at", utc_now())
        normalized.setdefault("status", "REQUESTED")
        normalized.setdefault("args", {})
        return normalized

    def normalize_inbound_event(self, event: GatewayEvent) -> InboundEnvelope:
        route = self.router.resolve(event.stream_name, event.topic_name)
        summary, payload = self.extract_yaml_payload(event.content)
        if payload is None:
            return InboundEnvelope(
                summary=summary,
                payload=None,
                route=route,
                authoritative=False,
                schema_name=None,
                kind="human_note" if event.sender_type == "human" else "non_authoritative",
            )

        schema_name = self._schema_name_for_payload(payload)
        if schema_name == "control_event":
            payload = self._normalize_control_payload(event, payload)
        if schema_name is None:
            return InboundEnvelope(
                summary=summary,
                payload=payload,
                route=route,
                authoritative=False,
                schema_name=None,
                kind="malformed",
            )
        self.schema_validator.validate(schema_name, payload)
        return InboundEnvelope(
            summary=summary,
            payload=payload,
            route=route,
            authoritative=True,
            schema_name=schema_name,
            kind=payload.get("kind", "control_event" if schema_name == "control_event" else "unknown"),
        )

    @staticmethod
    def _normalize_request_text(value: str) -> str:
        return " ".join(str(value or "").split()).strip()

    def _parse_project_request(self, content: str) -> dict[str, Any]:
        parsed: dict[str, Any] = {
            "project_title": None,
            "project_goal": None,
            "requirements": [],
            "acceptance_criteria": [],
            "execution_requirements": [],
            "project_constraints": [],
            "management_requirements": [],
            "constraints": [],
            "dependencies": [],
            "open_questions": [],
            "non_goals": [],
            "milestones": [],
        }
        top_level_notes: list[str] = []
        current_section: str | None = None
        current_milestone: dict[str, Any] | None = None

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            project_match = self._PROJECT_NAME_RE.match(line)
            if project_match and not parsed["project_title"]:
                parsed["project_title"] = self._normalize_request_text(project_match.group(1))
                continue
            milestone_match = self._MILESTONE_RE.match(line)
            if milestone_match:
                current_milestone = {
                    "milestone_id": f"M{int(milestone_match.group(1))}",
                    "title": self._normalize_request_text(milestone_match.group(2)),
                    "goal": self._normalize_request_text(milestone_match.group(2)),
                    "requirements": [],
                    "acceptance_criteria": [],
                    "constraints": [],
                    "dependencies": [],
                    "notes": [],
                }
                parsed["milestones"].append(current_milestone)
                current_section = None
                continue
            if line.endswith(":"):
                section_key = self._SECTION_MAP.get(line[:-1].strip().lower())
                if section_key:
                    current_section = section_key
                    if current_section == "project_goal":
                        current_milestone = None
                    continue
            item = line[2:].strip() if line.startswith(("- ", "* ")) else line
            item = self._normalize_request_text(item)
            if not item:
                continue
            if current_section:
                if current_milestone is not None and current_section in {"requirements", "acceptance_criteria", "constraints", "dependencies"}:
                    current_milestone[current_section].append(item)
                elif current_section == "project_goal":
                    parsed["project_goal"] = item if not parsed["project_goal"] else f"{parsed['project_goal']} {item}"
                else:
                    parsed[current_section].append(item)
                continue
            if current_milestone is not None:
                current_milestone["notes"].append(item)
                continue
            top_level_notes.append(item)

        if not parsed["project_goal"]:
            for candidate in top_level_notes:
                if candidate.lower().startswith(("start a new software project", "initiate a sample software project", "initiate a new software project")):
                    continue
                parsed["project_goal"] = candidate
                break
        if not parsed["project_goal"]:
            parsed["project_goal"] = self._normalize_request_text(content.splitlines()[0] if content.splitlines() else content)
        return parsed

    def _ensure_project(self, project_id: str, *, goal: str, owner_agent: str, phase: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if project:
            if not project.get("workspace_ref"):
                self.workspace_provisioner.ensure_for_project(
                    project_id=project_id,
                    goal=project.get("goal") or goal,
                    priority=project.get("priority") or "MEDIUM",
                )
                project = self.store.get_project(project_id)
            return project
        now = utc_now()
        self.store.upsert(
            "projects",
            {
                "project_id": project_id,
                "goal": goal,
                "project_status": "ACTIVE",
                "runtime_status": "NEW",
                "priority": "MEDIUM",
                "current_phase": phase,
                "current_owner_agent": owner_agent,
                "assigned_project_orchestrator": self.routing_rules["routing"]["default_project_orchestrator"],
                "assigned_software_orchestrator": self.routing_rules["routing"]["default_software_orchestrator"],
                "next_action_json": {"type": "FRAME_PROJECT", "target_agent": owner_agent},
                "workspace_ref": None,
                "last_snapshot_id": None,
                "last_activity_at": now,
                "created_at": now,
                "updated_at": now,
            },
            conflict_columns=["project_id"],
        )
        self.store.upsert(
            "scheduling_records",
            {
                "project_id": project_id,
                "queue_state": "normal_ready",
                "eligible_for_scheduling": False,
                "pause_requested": False,
                "resume_requested": False,
                "preemption_allowed": False,
                "waiting_reason": "awaiting_intake_or_workspace",
                "last_scheduled_at": None,
                "times_scheduled": 0,
            },
            conflict_columns=["project_id"],
        )
        self.workspace_provisioner.ensure_for_project(
            project_id=project_id,
            goal=goal,
            priority="MEDIUM",
        )
        return self.store.get_project(project_id) or {}

    def _persist_task(
        self,
        *,
        project_id: str,
        task_id: str,
        from_agent: str,
        to_agent: str,
        task_type: str,
        title: str,
        goal: str,
        priority: str,
        context: dict[str, Any],
        expected_output: dict[str, Any],
        decision_bounds: dict[str, Any],
        return_to: str,
    ) -> dict[str, Any]:
        now = utc_now()
        self.store.upsert(
            "tasks",
            {
                "task_id": task_id,
                "project_id": project_id,
                "parent_task_id": None,
                "from_agent": from_agent,
                "to_agent": to_agent,
                "current_owner_agent": to_agent,
                "return_to": return_to,
                "task_type": task_type,
                "title": title,
                "goal": goal,
                "priority": priority,
                "status": "PENDING",
                "context_json": context,
                "expected_output_json": expected_output,
                "decision_bounds_json": decision_bounds,
                "opened_at": now,
                "updated_at": now,
                "closed_at": None,
            },
            conflict_columns=["task_id"],
        )
        self.store.update(
            "projects",
            {
                "current_owner_agent": to_agent,
                "last_activity_at": now,
                "updated_at": now,
                "next_action_json": {"type": task_type, "target_agent": to_agent, "task_id": task_id},
            },
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        return self.store.get_task(task_id) or {}

    def build_authoritative_message(self, summary: str, payload: dict[str, Any]) -> str:
        rendered = yaml.safe_dump(payload, sort_keys=False).strip()
        return f"{summary.strip()}\n\n```yaml\n{rendered}\n```"

    def build_task_assignment_message(self, plan: DispatchPlan) -> str:
        payload = {
            "kind": "task_assignment",
            "project_id": plan.project_id,
            "task_id": plan.task_id,
            "from_agent": "gateway",
            "to_agent": plan.target_agent,
            "task_type": plan.task_type,
            "goal": plan.reason,
            "return_to": "requesting_agent",
            "reply_stream": plan.reply_stream,
            "reply_topic": plan.reply_topic,
        }
        summary = "\n".join(
            [
                f"Step Started: {self._step_label(plan.task_type)}",
                f"Owner: {self.agent_display_name(plan.target_agent)}",
                f"Project: {plan.project_id}",
                "Status: ACTIVE",
                f"Goal: {plan.reason}",
                f"Next: {self._assignment_next_text(plan.task_type, plan.target_agent)}",
            ]
        )
        return self.build_authoritative_message(summary, payload)

    def build_task_result_message(
        self,
        *,
        project_id: str,
        task_id: str,
        task_type: str,
        agent: str,
        status: str,
        summary: str,
        artifacts_out: list[str],
        next_action: dict[str, Any],
        kind: str = "task_result",
    ) -> str:
        payload = {
            "kind": kind,
            "project_id": project_id,
            "task_id": task_id,
            "agent": agent,
            "status": status,
            "summary": summary,
            "artifacts_out": artifacts_out,
            "next_action": next_action,
        }
        self.schema_validator.validate("task_result", payload)
        human_summary = "\n".join(
            [
                f"Step Update: {self._step_label(task_type)}",
                f"Owner: {self.agent_display_name(agent)}",
                f"Project: {project_id}",
                f"Outcome: {status}",
                f"Summary: {summary}",
                f"Next: {self._next_step_text(next_action)}",
            ]
        )
        return self.build_authoritative_message(human_summary, payload)

    def mirror_control_event(self, result: ControlCommandResult) -> str:
        payload = {
            "event_id": result.event_id,
            "project_id": result.project_id,
            "command": result.command,
            "requested_by": "gateway",
            "requested_at": utc_now(),
            "status": result.status,
            "args": {},
            "result_summary": result.summary,
        }
        summary = "\n".join(
            [
                "Project Control Update",
                f"Project: {result.project_id}",
                f"Command: {result.command}",
                f"Outcome: {result.status}",
                f"Next: {result.summary}",
            ]
        )
        return self.build_authoritative_message(summary, payload)

    def _handle_freeform_human_request(self, event: GatewayEvent, envelope: InboundEnvelope) -> GatewayResult:
        project_id = envelope.route.project_id or self.store.new_id("P")
        entry_agent = self.routing_rules["routing"]["default_entry_agent"]
        task_id = self.store.new_id("T")
        parsed_request = self._parse_project_request(envelope.summary)
        project_goal = str(parsed_request.get("project_goal") or envelope.summary).strip()
        self._ensure_project(project_id, goal=project_goal, owner_agent=entry_agent, phase="intake")
        self._persist_task(
            project_id=project_id,
            task_id=task_id,
            from_agent="human",
            to_agent=entry_agent,
            task_type="FRAME_PROJECT",
            title="Human intake request",
            goal=project_goal,
            priority="MEDIUM",
            context={
                "source": "zulip_human_message",
                "stream_name": event.stream_name,
                "topic_name": event.topic_name,
                "sender_name": event.sender_name,
                "request_summary": envelope.summary,
                "project_title": parsed_request.get("project_title"),
                "project_goal": project_goal,
                "requirements": parsed_request.get("requirements") or [],
                "acceptance_criteria": parsed_request.get("acceptance_criteria") or [],
                "execution_requirements": parsed_request.get("execution_requirements") or [],
                "project_constraints": parsed_request.get("project_constraints") or [],
                "management_requirements": parsed_request.get("management_requirements") or [],
                "constraints": parsed_request.get("constraints") or [],
                "dependencies": parsed_request.get("dependencies") or [],
                "open_questions": parsed_request.get("open_questions") or [],
                "non_goals": parsed_request.get("non_goals") or [],
                "milestones": parsed_request.get("milestones") or [],
            },
            expected_output={"artifact_type": "project_charter"},
            decision_bounds={},
            return_to="requesting_agent",
        )
        self.mapping_store.link_message(
            project_id=project_id,
            zulip_message_id=event.message_id,
            stream_name=event.stream_name,
            topic_name=event.topic_name,
            direction="inbound",
            message_kind="human_note",
            linked_entity_type="task",
            linked_entity_id=task_id,
            task_id=task_id,
        )
        reply_stream, reply_topic = self.reply_address_for_task(project_id, task_id, "FRAME_PROJECT")
        plan = DispatchPlan(
            project_id=project_id,
            task_id=task_id,
            target_agent=entry_agent,
            task_type="FRAME_PROJECT",
            reply_stream=reply_stream,
            reply_topic=reply_topic,
            reason=project_goal,
        )
        return GatewayResult(
            status="dispatch_planned",
            summary="human intake normalized into AgentSmith frame-project task",
            project_id=project_id,
            task_id=task_id,
            dispatch_plan=plan,
            outbound_message=self.build_task_assignment_message(plan),
            envelope=envelope,
        )

    def _handle_task_assignment(self, event: GatewayEvent, envelope: InboundEnvelope) -> GatewayResult:
        assert envelope.payload is not None
        payload = envelope.payload
        project_id = payload["project_id"]
        task_id = payload["task_id"]
        target_agent = self.canonicalize_agent(payload["to_agent"])
        task_type = payload["task_type"]
        self._ensure_project(project_id, goal=payload["goal"], owner_agent=target_agent, phase="routed")
        self._persist_task(
            project_id=project_id,
            task_id=task_id,
            from_agent=self.canonicalize_agent(payload["from_agent"]),
            to_agent=target_agent,
            task_type=task_type,
            title=f"{task_type} for {project_id}",
            goal=payload["goal"],
            priority="MEDIUM",
            context={"zulip_payload": payload},
            expected_output={},
            decision_bounds={},
            return_to=self.canonicalize_agent(payload["return_to"]) if payload["return_to"] != "requesting_agent" else "requesting_agent",
        )
        self.mapping_store.link_message(
            project_id=project_id,
            zulip_message_id=event.message_id,
            stream_name=event.stream_name,
            topic_name=event.topic_name,
            direction="inbound",
            message_kind="task_assignment",
            linked_entity_type="task",
            linked_entity_id=task_id,
            task_id=task_id,
        )
        reply_stream, reply_topic = self.reply_address_for_task(project_id, task_id, task_type)
        plan = DispatchPlan(
            project_id=project_id,
            task_id=task_id,
            target_agent=target_agent,
            task_type=task_type,
            reply_stream=reply_stream,
            reply_topic=reply_topic,
            reason=payload["goal"],
        )
        return GatewayResult(
            status="dispatch_planned",
            summary="authoritative task assignment accepted",
            project_id=project_id,
            task_id=task_id,
            dispatch_plan=plan,
            outbound_message=self.build_task_assignment_message(plan),
            envelope=envelope,
        )

    def _handle_task_result(self, event: GatewayEvent, envelope: InboundEnvelope) -> GatewayResult:
        assert envelope.payload is not None
        payload = envelope.payload
        task_id = payload["task_id"]
        project_id = payload["project_id"]
        now = utc_now()
        self.store.update(
            "tasks",
            {"status": payload["status"], "updated_at": now},
            where_clause="task_id = ?",
            where_params=[task_id],
        )
        self.store.update(
            "projects",
            {"last_activity_at": now, "updated_at": now},
            where_clause="project_id = ?",
            where_params=[project_id],
        )
        self.mapping_store.link_message(
            project_id=project_id,
            zulip_message_id=event.message_id,
            stream_name=event.stream_name,
            topic_name=event.topic_name,
            direction="inbound",
            message_kind=payload["kind"],
            linked_entity_type="task",
            linked_entity_id=task_id,
            task_id=task_id,
        )
        return GatewayResult(
            status="result_recorded",
            summary="task result persisted",
            project_id=project_id,
            task_id=task_id,
            envelope=envelope,
        )

    def _handle_control_event(self, event: GatewayEvent, envelope: InboundEnvelope) -> GatewayResult:
        assert envelope.payload is not None
        payload = envelope.payload
        command = payload["command"]
        project_id = payload["project_id"]
        args = payload.get("args") or {}
        requested_by = payload.get("requested_by", event.sender_name)
        if command == "PAUSE_PROJECT":
            result = self.control_commands.pause_project(
                project_id,
                requested_by=requested_by,
                latest_human_summary=envelope.summary or "pause requested from Zulip",
                orchestrator_id=payload.get("orchestrator_id"),
                reason=payload.get("reason"),
            )
        elif command == "RESUME_PROJECT":
            result = self.control_commands.resume_project(
                project_id,
                requested_by=requested_by,
                orchestrator_id=payload.get("orchestrator_id"),
            )
        elif command == "CANCEL_PROJECT":
            result = self.control_commands.cancel_project(
                project_id,
                requested_by=requested_by,
                reason=payload.get("reason") or args.get("reason", "cancel requested from Zulip"),
            )
        elif command == "REPRIORITIZE_PROJECT":
            result = self.control_commands.reprioritize_project(
                project_id,
                requested_by=requested_by,
                priority=args["priority"],
            )
        elif command == "STATUS_SNAPSHOT":
            result = self.control_commands.create_status_snapshot(
                project_id,
                requested_by=requested_by,
                latest_human_summary=envelope.summary or "status snapshot requested from Zulip",
            )
        elif command == "FORCE_INTERRUPT":
            result = self.control_commands.force_interrupt(
                project_id,
                requested_by=requested_by,
                orchestrator_id=payload["orchestrator_id"],
                reason=payload.get("reason") or args.get("reason", "forced interrupt from Zulip"),
            )
        elif command == "SWITCH_PROJECT":
            result = self.control_commands.switch_project(
                from_project_id=args["from_project_id"],
                to_project_id=args["to_project_id"],
                orchestrator_id=args["orchestrator_id"],
                requested_by=requested_by,
                reason=payload.get("reason"),
                force=bool(args.get("force", False)),
            )
        else:
            raise ValueError(f"unsupported control command {command}")

        self.mapping_store.link_message(
            project_id=project_id,
            zulip_message_id=event.message_id,
            stream_name=event.stream_name,
            topic_name=event.topic_name,
            direction="inbound",
            message_kind="control_event",
            linked_entity_type="control_event",
            linked_entity_id=result.event_id,
            control_event_id=result.event_id,
        )
        return GatewayResult(
            status=result.status.lower(),
            summary=result.summary,
            project_id=result.project_id,
            control_event_id=result.event_id,
            outbound_message=self.mirror_control_event(result),
            envelope=envelope,
        )

    def handle_inbound_event(self, event: GatewayEvent) -> GatewayResult:
        existing = self.mapping_store.get_by_message_id(event.message_id)
        if existing:
            return GatewayResult(
                status="duplicate",
                summary=f"message {event.message_id} was already processed",
                project_id=existing.get("project_id"),
                task_id=existing.get("task_id"),
            )

        envelope = self.normalize_inbound_event(event)
        if event.sender_type == "human" and not envelope.authoritative:
            return self._handle_freeform_human_request(event, envelope)
        if not envelope.authoritative:
            return GatewayResult(status="ignored", summary="non-authoritative Zulip message ignored", envelope=envelope)
        if envelope.schema_name == "task_assignment":
            return self._handle_task_assignment(event, envelope)
        if envelope.schema_name == "task_result":
            return self._handle_task_result(event, envelope)
        if envelope.schema_name == "control_event":
            return self._handle_control_event(event, envelope)
        return GatewayResult(status="ignored", summary="unsupported authoritative payload", envelope=envelope)
