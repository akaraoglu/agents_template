"""Rule-driven Niobe project loop execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

from openclaw_agents.communication.zulip_gateway import DispatchPlan
from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.runtime.artifact_parsers import ArtifactParser

if TYPE_CHECKING:
    from openclaw_agents.runtime.dispatcher import DispatchReceipt, RuntimeDispatcher


TERMINAL_CHILD_FAILURES = {"BLOCKED", "FAILED", "CANCELLED"}
PROJECT_STEP_CONFIG = {
    "DESIGN_ARCHITECTURE": {
        "agent_id": "architect",
        "artifact_type": "architecture_spec",
        "phase": "project_design",
    },
    "ORCHESTRATE_SOFTWARE": {
        "agent_id": "morpheus",
        "artifact_type": "software_delivery_package",
        "phase": "project_implementation",
    },
    "VERIFY_PROJECT": {
        "agent_id": "oracle",
        "artifact_type": "verification_report",
        "phase": "project_verification",
    },
}


@dataclass(slots=True)
class ChildDispatch:
    task: dict[str, Any]
    receipt: "DispatchReceipt"


class NiobeLoopEngine:
    """Advance the Niobe architect -> morpheus -> oracle project loop."""

    def __init__(
        self,
        *,
        store: ControlPlaneStore | None = None,
        dispatcher: "RuntimeDispatcher",
        artifact_parser: ArtifactParser | None = None,
        routing_rules_path: str | None = None,
        state_machine_path: str | None = None,
    ) -> None:
        self.store = store or dispatcher.store
        self.dispatcher = dispatcher
        self.artifact_parser = artifact_parser or ArtifactParser(self.store)
        base = Path(__file__).resolve().parents[1]
        self.routing_rules = yaml.safe_load(
            (base / "config" / "routing_rules.yaml" if routing_rules_path is None else Path(routing_rules_path)).read_text()
        )
        self.state_machine = yaml.safe_load(
            (base / "orchestrators" / "niobe_state_machine.yaml" if state_machine_path is None else Path(state_machine_path)).read_text()
        )
        self.max_transitions = int(
            (((self.routing_rules.get("stop_conditions") or {}).get("niobe") or {}).get("max_project_transitions_before_escalation"))
            or 20
        )

    def _latest_child(self, parent_task_id: str, task_type: str) -> dict[str, Any] | None:
        return self.store.get_latest_child_task(parent_task_id, task_type=task_type)

    def _active_child(self, parent_task_id: str) -> dict[str, Any] | None:
        children = self.store.list_child_tasks(parent_task_id, include_terminal=False)
        return children[-1] if children else None

    def _child_task_count(self, parent_task_id: str, task_type: str) -> int:
        return len(self.store.list_child_tasks(parent_task_id, task_type=task_type))

    @staticmethod
    def _is_stale(child_task: dict[str, Any] | None, dependency_task: dict[str, Any] | None) -> bool:
        if not child_task or not dependency_task:
            return False
        return str(child_task.get("opened_at") or "") < str(dependency_task.get("opened_at") or "")

    def _latest_artifact_payload(
        self,
        project_id: str,
        *,
        task_id: str | None = None,
        artifact_type: str,
    ) -> tuple[dict[str, Any] | None, Any]:
        records = self.artifact_parser.list_project_artifacts(project_id, artifact_type=artifact_type, task_id=task_id)
        if not records:
            return None, None
        record = records[-1]
        return record, self.artifact_parser.parse_record(record)

    def _status_report_payload(
        self,
        packet: dict[str, Any],
        *,
        state: str,
        summary: str,
        evidence: list[str],
        next_action: dict[str, Any],
        safe_to_pause: bool,
    ) -> dict[str, Any]:
        return {
            "project_id": packet["project_id"],
            "task_id": packet["task_id"],
            "state": state,
            "summary": summary,
            "evidence_received": evidence,
            "next_action": next_action,
            "safe_to_pause_or_switch": safe_to_pause,
        }

    def _response(
        self,
        packet: dict[str, Any],
        *,
        status: str,
        summary: str,
        phase: str,
        state: str,
        artifacts_out: list[dict[str, Any]] | None = None,
        findings: list[Any] | None = None,
        risks: list[str] | None = None,
        next_action_type: str,
        next_action_reason: str,
        target_agent: str | None = None,
        safe_to_pause: bool = True,
    ) -> dict[str, Any]:
        next_action: dict[str, Any] = {
            "type": next_action_type,
            "reason": next_action_reason,
        }
        if target_agent:
            next_action["target_agent"] = target_agent
        status_artifact = {
            "artifact_type": "project_status_report",
            "ref": f"inline://niobe-status-{packet['task_id']}",
            "payload": self._status_report_payload(
                packet,
                state=state,
                summary=summary,
                evidence=[str(item) for item in findings or []],
                next_action=next_action,
                safe_to_pause=safe_to_pause,
            ),
            "metadata": {"engine": "niobe_rule_loop", "phase": phase},
        }
        return {
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent": packet["to_agent"],
            "status": status,
            "summary": summary,
            "artifacts_out": [status_artifact, *(artifacts_out or [])],
            "findings": findings or [],
            "next_action": next_action,
            "risks": risks or [],
            "trace": {
                "run_id": packet["metadata"]["run_id"],
                "engine": "niobe_rule_loop",
            },
        }

    def _dispatch_child(
        self,
        packet: dict[str, Any],
        *,
        task_type: str,
        goal: str,
        context: dict[str, Any],
        expected_output: dict[str, Any],
    ) -> ChildDispatch:
        spec = PROJECT_STEP_CONFIG[task_type]
        parent_task = self.store.get_task(packet["task_id"])
        if not parent_task:
            raise ValueError(f"unknown niobe task {packet['task_id']}")
        child_task = self.store.record_task(
            project_id=packet["project_id"],
            parent_task_id=packet["task_id"],
            from_agent="niobe",
            to_agent=spec["agent_id"],
            task_type=task_type,
            title=f"{task_type} for {packet['project_id']}",
            goal=goal,
            priority=parent_task["priority"],
            context=context,
            expected_output=expected_output,
            decision_bounds=parent_task.get("decision_bounds_json") or {},
            return_to="requesting_agent",
        )
        reply_stream, reply_topic = self.dispatcher.router.reply_address_for_task(
            packet["project_id"],
            child_task["task_id"],
            task_type,
        )
        receipt = self.dispatcher.dispatch_plan(
            DispatchPlan(
                project_id=packet["project_id"],
                task_id=child_task["task_id"],
                target_agent=spec["agent_id"],
                task_type=task_type,
                reply_stream=reply_stream,
                reply_topic=reply_topic,
                reason=goal,
            )
        )
        self.store.update(
            "projects",
            {"current_phase": spec["phase"]},
            where_clause="project_id = ?",
            where_params=[packet["project_id"]],
        )
        return ChildDispatch(task=child_task, receipt=receipt)

    def _build_escalation_payload(
        self,
        packet: dict[str, Any],
        *,
        reason: str,
        blocking_facts: list[str],
        recommended_action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "project_id": packet["project_id"],
            "task_id": packet["task_id"],
            "owner_agent": "niobe",
            "reason": reason,
            "blocking_facts": blocking_facts,
            "options_considered": [
                "continue current project loop",
                "return to request owner with explicit escalation",
            ],
            "recommended_action": recommended_action or {
                "type": "RETURN_TO_REQUESTER",
                "reason": reason,
            },
        }

    def _blocked_response(
        self,
        packet: dict[str, Any],
        *,
        summary: str,
        blocking_facts: list[str],
        target_agent: str | None = None,
    ) -> dict[str, Any]:
        escalation = self._build_escalation_payload(
            packet,
            reason=summary,
            blocking_facts=blocking_facts,
        )
        requester = target_agent or self.store.get_task(packet["task_id"])["from_agent"]
        return self._response(
            packet,
            status="BLOCKED",
            summary=summary,
            phase="blocked",
            state="ESCALATE",
            artifacts_out=[
                {
                    "artifact_type": "escalation_packet",
                    "ref": f"inline://niobe-escalation-{packet['task_id']}",
                    "payload": escalation,
                    "metadata": {"engine": "niobe_rule_loop"},
                }
            ],
            findings=blocking_facts,
            risks=blocking_facts,
            next_action_type="RETURN_TO_REQUESTER",
            next_action_reason=summary,
            target_agent=requester,
            safe_to_pause=True,
        )

    def _clarification_response(
        self,
        packet: dict[str, Any],
        *,
        summary: str,
        open_questions: list[str],
        target_agent: str | None = None,
    ) -> dict[str, Any]:
        clarification = {
            "project_id": packet["project_id"],
            "task_id": packet["task_id"],
            "summary": summary,
            "open_questions": open_questions,
            "requested_from": target_agent or self.store.get_task(packet["task_id"])["from_agent"],
        }
        requester = target_agent or self.store.get_task(packet["task_id"])["from_agent"]
        return self._response(
            packet,
            status="NEEDS_CLARIFICATION",
            summary=summary,
            phase="clarify",
            state="CLARIFY",
            artifacts_out=[
                {
                    "artifact_type": "clarification_brief",
                    "ref": f"inline://niobe-clarify-{packet['task_id']}",
                    "payload": clarification,
                    "metadata": {"engine": "niobe_rule_loop"},
                }
            ],
            findings=open_questions,
            risks=[],
            next_action_type="WAIT_FOR_EXTERNAL",
            next_action_reason=summary,
            target_agent=requester,
            safe_to_pause=True,
        )

    def _closure_payload(
        self,
        packet: dict[str, Any],
        *,
        charter_payload: dict[str, Any],
        architecture_payload: dict[str, Any],
        delivery_payload: dict[str, Any],
        verification_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "project_id": packet["project_id"],
            "task_id": packet["task_id"],
            "summary": f"Project {packet['project_id']} completed with Oracle verification evidence.",
            "charter_goal": charter_payload.get("problem_statement") or charter_payload.get("goal") or packet["goal"],
            "accepted_scope": charter_payload.get("goals") or [],
            "architecture_summary": architecture_payload.get("system_shape") or architecture_payload.get("summary"),
            "software_delivery_summary": delivery_payload.get("summary"),
            "verification_result": verification_payload.get("result"),
            "evidence": verification_payload.get("evidence") or [],
            "residual_risks": delivery_payload.get("known_limitations") or [],
        }

    def _verification_route(
        self,
        packet: dict[str, Any],
        *,
        verification_task: dict[str, Any],
        verification_payload: dict[str, Any],
        architecture_task: dict[str, Any],
        software_task: dict[str, Any],
        charter_record: dict[str, Any],
        charter_payload: dict[str, Any],
        architecture_record: dict[str, Any],
        architecture_payload: dict[str, Any],
        delivery_record: dict[str, Any],
        delivery_payload: dict[str, Any],
        parent_context: dict[str, Any],
    ) -> dict[str, Any]:
        result = verification_payload.get("result")
        defect_category = verification_payload.get("defect_category")
        if result == "PASS":
            closure = self._closure_payload(
                packet,
                charter_payload=charter_payload,
                architecture_payload=architecture_payload,
                delivery_payload=delivery_payload,
                verification_payload=verification_payload,
            )
            return self._response(
                packet,
                status="SUCCESS",
                summary=f"Niobe closed project {packet['project_id']} after Oracle verification passed.",
                phase="project_closed",
                state="DONE",
                artifacts_out=[
                    {
                        "artifact_type": "project_closure_report",
                        "ref": f"inline://niobe-closure-{packet['task_id']}",
                        "payload": closure,
                        "metadata": {"engine": "niobe_rule_loop"},
                    }
                ],
                findings=verification_payload.get("evidence") or ["verification_report:PASS"],
                risks=delivery_payload.get("known_limitations") or [],
                next_action_type="CLOSE_PROJECT",
                next_action_reason="Project is complete and verified.",
                target_agent=self.store.get_task(packet["task_id"])["from_agent"],
                safe_to_pause=True,
            )
        if defect_category == "requirements":
            return self._blocked_response(
                packet,
                summary=f"Oracle reported a requirements defect for {packet['project_id']}.",
                blocking_facts=verification_payload.get("findings") or ["requirements_defect"],
            )
        if defect_category == "design":
            if self._child_task_count(packet["task_id"], "DESIGN_ARCHITECTURE") >= self.max_transitions:
                return self._blocked_response(
                    packet,
                    summary=f"Niobe reached the architecture retry limit for {packet['project_id']}.",
                    blocking_facts=["design_retries_exhausted"],
                )
            dispatch = self._dispatch_child(
                packet,
                task_type="DESIGN_ARCHITECTURE",
                goal=packet["goal"],
                context={
                    "project_goal": packet["goal"],
                    "parent_task_id": packet["task_id"],
                    "charter_artifact_ref": charter_record["ref"],
                    "latest_verification_report": verification_payload,
                    "requirements": charter_payload.get("acceptance_criteria") or [],
                },
                expected_output={"artifact_type": "architecture_spec"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Niobe routed project {packet['project_id']} back to Architect after a design verification failure.",
                phase="project_design",
                state="WAITING_RESULT",
                findings=verification_payload.get("findings") or ["design_verification_failure"],
                risks=verification_payload.get("findings") or [],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Architect is revising the design after Oracle feedback.",
                target_agent=dispatch.task["to_agent"],
                safe_to_pause=True,
            )
        if defect_category == "implementation":
            if self._child_task_count(packet["task_id"], "ORCHESTRATE_SOFTWARE") >= self.max_transitions:
                return self._blocked_response(
                    packet,
                    summary=f"Niobe reached the implementation retry limit for {packet['project_id']}.",
                    blocking_facts=["implementation_retries_exhausted"],
                )
            dispatch = self._dispatch_child(
                packet,
                task_type="ORCHESTRATE_SOFTWARE",
                goal=packet["goal"],
                context={
                    "project_goal": packet["goal"],
                    "parent_task_id": packet["task_id"],
                    "charter_artifact_ref": charter_record["ref"],
                    "architecture_artifact_ref": architecture_record["ref"],
                    "architecture_summary": architecture_payload,
                    "requirements": charter_payload.get("acceptance_criteria") or [],
                    "verification_feedback": verification_payload,
                    "force_test_result": parent_context.get("force_test_result"),
                    "failure_cause": parent_context.get("failure_cause"),
                    "suggested_files": parent_context.get("suggested_files") or [],
                },
                expected_output={"artifact_type": "software_delivery_package"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Niobe routed project {packet['project_id']} back to Morpheus after an implementation verification failure.",
                phase="project_implementation",
                state="WAITING_RESULT",
                findings=verification_payload.get("findings") or ["implementation_verification_failure"],
                risks=verification_payload.get("findings") or [],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Morpheus is addressing Oracle implementation findings.",
                target_agent=dispatch.task["to_agent"],
                safe_to_pause=True,
            )
        return self._clarification_response(
            packet,
            summary=f"Oracle returned an inconclusive verification result for {packet['project_id']}.",
            open_questions=verification_payload.get("findings") or ["verification_result_inconclusive"],
        )

    def execute(self, packet: dict[str, Any]) -> dict[str, Any]:
        if packet["task_type"] != "ORCHESTRATE_PROJECT" or packet["to_agent"] != "niobe":
            raise ValueError("Niobe loop engine only accepts ORCHESTRATE_PROJECT tasks for niobe")

        project = self.store.get_project(packet["project_id"])
        parent_task = self.store.get_task(packet["task_id"])
        if not project or not parent_task:
            raise ValueError(f"unknown project or task for packet {packet['task_id']}")
        parent_context = parent_task.get("context_json") or {}

        active_child = self._active_child(packet["task_id"])
        if active_child:
            waiting_phase = {
                "architect": "project_design",
                "morpheus": "project_implementation",
                "oracle": "project_verification",
            }.get(active_child["to_agent"], "project_orchestration")
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Niobe is waiting for {active_child['to_agent']} to finish {active_child['task_type']} for {packet['project_id']}.",
                phase=waiting_phase,
                state="WAITING_RESULT",
                findings=[f"active_child_task={active_child['task_id']}"],
                risks=[],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason=f"Waiting on {active_child['task_type']}.",
                target_agent=active_child["to_agent"],
                safe_to_pause=True,
            )

        charter_record, charter_payload = self._latest_artifact_payload(packet["project_id"], artifact_type="project_charter")
        if charter_record is None or not isinstance(charter_payload, dict):
            return self._clarification_response(
                packet,
                summary=f"Niobe cannot start project {packet['project_id']} without a persisted project charter.",
                open_questions=["missing_project_charter"],
                target_agent="agent_smith",
            )
        acceptance = charter_payload.get("acceptance_criteria") or []
        if not acceptance:
            return self._clarification_response(
                packet,
                summary=f"Project charter for {packet['project_id']} is missing acceptance criteria.",
                open_questions=["acceptance_criteria_required"],
                target_agent="agent_smith",
            )

        architecture_task = self._latest_child(packet["task_id"], "DESIGN_ARCHITECTURE")
        if architecture_task is None:
            dispatch = self._dispatch_child(
                packet,
                task_type="DESIGN_ARCHITECTURE",
                goal=packet["goal"],
                context={
                    "project_goal": packet["goal"],
                    "parent_task_id": packet["task_id"],
                    "charter_artifact_ref": charter_record["ref"],
                    "charter_summary": charter_payload,
                    "requirements": acceptance,
                },
                expected_output={"artifact_type": "architecture_spec"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Niobe queued Architect for project {packet['project_id']}.",
                phase="project_design",
                state="WAITING_RESULT",
                findings=[dispatch.task["task_id"]],
                risks=[],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Architect is producing the architecture specification.",
                target_agent=dispatch.task["to_agent"],
                safe_to_pause=True,
            )
        if architecture_task["status"] == "NEEDS_CLARIFICATION":
            return self._clarification_response(
                packet,
                summary=f"Architect needs clarification before continuing project {packet['project_id']}.",
                open_questions=[f"architect_task={architecture_task['task_id']}"],
            )
        if architecture_task["status"] in TERMINAL_CHILD_FAILURES:
            return self._blocked_response(
                packet,
                summary=f"Architect could not complete the design for project {packet['project_id']}.",
                blocking_facts=[f"architect_status={architecture_task['status']}"],
            )
        architecture_record, architecture_payload = self._latest_artifact_payload(
            packet["project_id"],
            task_id=architecture_task["task_id"],
            artifact_type="architecture_spec",
        )
        if architecture_record is None or not isinstance(architecture_payload, dict):
            return self._blocked_response(
                packet,
                summary=f"Architect completed but no architecture_spec artifact was persisted for {packet['project_id']}.",
                blocking_facts=[f"architect_task={architecture_task['task_id']}"],
            )

        software_task = self._latest_child(packet["task_id"], "ORCHESTRATE_SOFTWARE")
        if self._is_stale(software_task, architecture_task):
            software_task = None
        if software_task is None:
            dispatch = self._dispatch_child(
                packet,
                task_type="ORCHESTRATE_SOFTWARE",
                goal=packet["goal"],
                context={
                    "project_goal": packet["goal"],
                    "parent_task_id": packet["task_id"],
                    "charter_artifact_ref": charter_record["ref"],
                    "architecture_artifact_ref": architecture_record["ref"],
                    "architecture_summary": architecture_payload,
                    "requirements": acceptance,
                    "suggested_files": parent_context.get("suggested_files") or [],
                    "force_test_result": parent_context.get("force_test_result"),
                    "failure_cause": parent_context.get("failure_cause"),
                },
                expected_output={"artifact_type": "software_delivery_package"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Niobe queued Morpheus for project {packet['project_id']}.",
                phase="project_implementation",
                state="WAITING_RESULT",
                findings=[dispatch.task["task_id"]],
                risks=[],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Morpheus is delivering the software package.",
                target_agent=dispatch.task["to_agent"],
                safe_to_pause=True,
            )
        if software_task["status"] == "NEEDS_CLARIFICATION":
            return self._clarification_response(
                packet,
                summary=f"Morpheus needs clarification before continuing project {packet['project_id']}.",
                open_questions=[f"morpheus_task={software_task['task_id']}"],
            )
        if software_task["status"] in TERMINAL_CHILD_FAILURES:
            return self._blocked_response(
                packet,
                summary=f"Morpheus could not deliver the software package for project {packet['project_id']}.",
                blocking_facts=[f"morpheus_status={software_task['status']}"],
            )
        delivery_record, delivery_payload = self._latest_artifact_payload(
            packet["project_id"],
            task_id=software_task["task_id"],
            artifact_type="software_delivery_package",
        )
        if delivery_record is None or not isinstance(delivery_payload, dict):
            return self._blocked_response(
                packet,
                summary=f"Morpheus completed but no software_delivery_package artifact was persisted for {packet['project_id']}.",
                blocking_facts=[f"morpheus_task={software_task['task_id']}"],
            )

        verification_task = self._latest_child(packet["task_id"], "VERIFY_PROJECT")
        if self._is_stale(verification_task, software_task):
            verification_task = None
        if verification_task is None:
            dispatch = self._dispatch_child(
                packet,
                task_type="VERIFY_PROJECT",
                goal=f"Verify project {packet['project_id']} against the charter",
                context={
                    "project_goal": packet["goal"],
                    "parent_task_id": packet["task_id"],
                    "charter_artifact_ref": charter_record["ref"],
                    "architecture_artifact_ref": architecture_record["ref"],
                    "software_delivery_ref": delivery_record["ref"],
                    "acceptance_criteria": acceptance,
                    "force_verification_result": parent_context.get("force_verification_result"),
                    "verification_defect_category": parent_context.get("verification_defect_category"),
                },
                expected_output={"artifact_type": "verification_report"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Niobe queued Oracle for project {packet['project_id']}.",
                phase="project_verification",
                state="WAITING_RESULT",
                findings=[dispatch.task["task_id"]],
                risks=[],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Oracle is verifying the project package.",
                target_agent=dispatch.task["to_agent"],
                safe_to_pause=True,
            )
        if verification_task["status"] == "NEEDS_CLARIFICATION":
            return self._clarification_response(
                packet,
                summary=f"Oracle needs clarification before completing verification for {packet['project_id']}.",
                open_questions=[f"oracle_task={verification_task['task_id']}"],
            )
        if verification_task["status"] in TERMINAL_CHILD_FAILURES:
            return self._blocked_response(
                packet,
                summary=f"Oracle could not complete verification for project {packet['project_id']}.",
                blocking_facts=[f"oracle_status={verification_task['status']}"],
            )
        verification_record, verification_payload = self._latest_artifact_payload(
            packet["project_id"],
            task_id=verification_task["task_id"],
            artifact_type="verification_report",
        )
        if verification_record is None or not isinstance(verification_payload, dict):
            return self._blocked_response(
                packet,
                summary=f"Oracle completed but no verification_report artifact was persisted for {packet['project_id']}.",
                blocking_facts=[f"oracle_task={verification_task['task_id']}"],
            )

        return self._verification_route(
            packet,
            verification_task=verification_task,
            verification_payload=verification_payload,
            architecture_task=architecture_task,
            software_task=software_task,
            charter_record=charter_record,
            charter_payload=charter_payload,
            architecture_record=architecture_record,
            architecture_payload=architecture_payload,
            delivery_record=delivery_record,
            delivery_payload=delivery_payload,
            parent_context=parent_context,
        )

    def handle_child_completion(self, task_id: str) -> "DispatchReceipt" | None:
        child_task = self.store.get_task(task_id)
        if not child_task or not child_task.get("parent_task_id"):
            return None
        parent_task = self.store.get_task(child_task["parent_task_id"])
        if not parent_task:
            return None
        if parent_task["to_agent"] != "niobe" or parent_task["task_type"] != "ORCHESTRATE_PROJECT":
            return None
        if parent_task["status"] in {"SUCCESS", "FAILED", "BLOCKED", "CANCELLED", "NEEDS_CLARIFICATION"}:
            return None
        if self.store.get_active_task_attempt(parent_task["task_id"]):
            return None
        reply_stream, reply_topic = self.dispatcher.router.reply_address_for_task(
            parent_task["project_id"],
            parent_task["task_id"],
            parent_task["task_type"],
        )
        self.store.update(
            "projects",
            {"current_phase": "project_orchestration"},
            where_clause="project_id = ?",
            where_params=[parent_task["project_id"]],
        )
        return self.dispatcher.dispatch_plan(
            DispatchPlan(
                project_id=parent_task["project_id"],
                task_id=parent_task["task_id"],
                target_agent="niobe",
                task_type=parent_task["task_type"],
                reply_stream=reply_stream,
                reply_topic=reply_topic,
                reason=parent_task["goal"],
            )
        )
