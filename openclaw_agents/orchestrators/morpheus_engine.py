"""Rule-driven Morpheus software loop execution."""

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

TERMINAL_CHILD_FAILURES = {"NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "CANCELLED"}
SOFTWARE_STEP_CONFIG = {
    "PLAN_SOFTWARE_TASK": {
        "agent_id": "planner",
        "artifact_type": "software_task_plan",
        "phase": "software_planning",
    },
    "IMPLEMENT_SOFTWARE_TASK": {
        "agent_id": "implementer",
        "artifact_type": "code_change",
        "phase": "software_implementation",
    },
    "TEST_SOFTWARE_TASK": {
        "agent_id": "tester",
        "artifact_type": "test_execution_report",
        "phase": "software_validation",
    },
}


@dataclass(slots=True)
class ChildDispatch:
    task: dict[str, Any]
    receipt: "DispatchReceipt"


class MorpheusLoopEngine:
    """Advance the Morpheus planner -> implementer -> tester loop."""

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
            (base / "orchestrators" / "morpheus_state_machine.yaml" if state_machine_path is None else Path(state_machine_path)).read_text()
        )
        self.max_retry_cycles = int(
            (((self.routing_rules.get("stop_conditions") or {}).get("morpheus") or {}).get("max_retry_cycles_per_software_task"))
            or 5
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

    def _response(
        self,
        packet: dict[str, Any],
        *,
        status: str,
        summary: str,
        artifacts_out: list[dict[str, Any]] | None = None,
        findings: list[Any] | None = None,
        risks: list[str] | None = None,
        next_action_type: str,
        next_action_reason: str,
        target_agent: str | None = None,
    ) -> dict[str, Any]:
        next_action: dict[str, Any] = {
            "type": next_action_type,
            "reason": next_action_reason,
        }
        if target_agent:
            next_action["target_agent"] = target_agent
        return {
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent": packet["to_agent"],
            "status": status,
            "summary": summary,
            "artifacts_out": artifacts_out or [],
            "findings": findings or [],
            "next_action": next_action,
            "risks": risks or [],
            "trace": {
                "run_id": packet["metadata"]["run_id"],
                "engine": "morpheus_rule_loop",
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
        spec = SOFTWARE_STEP_CONFIG[task_type]
        parent_task = self.store.get_task(packet["task_id"])
        if not parent_task:
            raise ValueError(f"unknown morpheus task {packet['task_id']}")
        child_task = self.store.record_task(
            project_id=packet["project_id"],
            parent_task_id=packet["task_id"],
            from_agent="morpheus",
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
        reply_stream, reply_topic = self.dispatcher.reply_address_for_task(
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
            {
                "current_phase": spec["phase"],
            },
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
            "owner_agent": "morpheus",
            "reason": reason,
            "blocking_facts": blocking_facts,
            "options_considered": [
                "retry current software stage",
                "return to Niaobe with evidence",
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
    ) -> dict[str, Any]:
        escalation = self._build_escalation_payload(
            packet,
            reason=summary,
            blocking_facts=blocking_facts,
        )
        target_agent = self.store.get_task(packet["task_id"])["from_agent"]
        return self._response(
            packet,
            status="BLOCKED",
            summary=summary,
            artifacts_out=[
                {
                    "artifact_type": "escalation_packet",
                    "ref": f"inline://morpheus-escalation-{packet['task_id']}",
                    "payload": escalation,
                    "metadata": {"engine": "morpheus_rule_loop"},
                }
            ],
            findings=blocking_facts,
            risks=blocking_facts,
            next_action_type="RETURN_TO_REQUESTER",
            next_action_reason=summary,
            target_agent=target_agent,
        )

    def _delivery_payload(
        self,
        packet: dict[str, Any],
        *,
        parent_context: dict[str, Any],
        plan_payload: dict[str, Any],
        code_payload: dict[str, Any],
        test_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "project_id": packet["project_id"],
            "task_id": packet["task_id"],
            "summary": f"Software loop completed for {packet['project_id']}.",
            "milestone_id": parent_context.get("milestone_id"),
            "milestone_title": parent_context.get("milestone_title"),
            "work_item_id": parent_context.get("work_item_id"),
            "work_item_title": parent_context.get("work_item_title"),
            "implemented_changes": code_payload.get("changed_files") or [],
            "test_changes": test_payload.get("test_changes") or [],
            "test_execution_report": test_payload,
            "known_limitations": code_payload.get("known_limitations") or [],
            "recommended_next_step": "return_to_requester",
            "plan_summary": {
                "task_breakdown": plan_payload.get("task_breakdown") or [],
                "implementation_steps": plan_payload.get("implementation_steps") or [],
                "test_obligations": plan_payload.get("test_obligations") or [],
            },
        }

    def _retry_stage_for_test_result(self, test_payload: dict[str, Any]) -> str | None:
        failure_cause = test_payload.get("failure_cause")
        if failure_cause == "BAD_PLAN":
            return "PLAN_SOFTWARE_TASK"
        if failure_cause == "TEST_GAP":
            return "TEST_SOFTWARE_TASK"
        if failure_cause == "IMPLEMENTATION_DEFECT":
            return "IMPLEMENT_SOFTWARE_TASK"
        return None

    def execute(self, packet: dict[str, Any]) -> dict[str, Any]:
        if packet["task_type"] != "ORCHESTRATE_SOFTWARE" or packet["to_agent"] != "morpheus":
            raise ValueError("Morpheus loop engine only accepts ORCHESTRATE_SOFTWARE tasks for morpheus")

        project = self.store.get_project(packet["project_id"])
        parent_task = self.store.get_task(packet["task_id"])
        if not project or not parent_task:
            raise ValueError(f"unknown project or task for packet {packet['task_id']}")
        parent_context = parent_task.get("context_json") or {}

        active_child = self._active_child(packet["task_id"])
        if active_child:
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Morpheus is waiting for {active_child['to_agent']} to finish {active_child['task_type']}.",
                findings=[f"active_child_task={active_child['task_id']}"],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason=f"Waiting on {active_child['task_type']}.",
                target_agent=active_child["to_agent"],
            )

        planner_task = self._latest_child(packet["task_id"], "PLAN_SOFTWARE_TASK")
        if planner_task is None:
            dispatch = self._dispatch_child(
                packet,
                task_type="PLAN_SOFTWARE_TASK",
                goal=packet["goal"],
                context={
                    "software_goal": packet["goal"],
                    "project_goal": project["goal"],
                    "parent_task_id": packet["task_id"],
                    "milestone_id": parent_context.get("milestone_id"),
                    "milestone_title": parent_context.get("milestone_title"),
                    "work_item_id": parent_context.get("work_item_id"),
                    "work_item_title": parent_context.get("work_item_title"),
                    "sequence_index": parent_context.get("sequence_index"),
                    "artifacts_in": packet.get("artifacts_in") or [],
                    "requirements": parent_context.get("requirements") or [],
                    "acceptance_criteria": parent_context.get("acceptance_criteria") or [],
                },
                expected_output={"artifact_type": "software_task_plan"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Morpheus queued planner task {dispatch.task['task_id']}.",
                findings=[dispatch.task["task_id"]],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Planner has the software task.",
                target_agent=dispatch.task["to_agent"],
            )
        if planner_task["status"] in TERMINAL_CHILD_FAILURES:
            return self._blocked_response(
                packet,
                summary=f"Planner did not produce an acceptable software plan for {packet['project_id']}.",
                blocking_facts=[f"planner_status={planner_task['status']}"],
            )
        plan_record, plan_payload = self._latest_artifact_payload(
            packet["project_id"],
            task_id=planner_task["task_id"],
            artifact_type="software_task_plan",
        )
        if plan_record is None or not isinstance(plan_payload, dict):
            return self._blocked_response(
                packet,
                summary=f"Planner completed but no software_task_plan artifact was persisted for {packet['project_id']}.",
                blocking_facts=[f"planner_task={planner_task['task_id']}"],
            )
        if not project.get("workspace_ref"):
            return self._blocked_response(
                packet,
                summary=f"Morpheus cannot execute software work for {packet['project_id']} without a workspace_ref.",
                blocking_facts=["missing_workspace_ref"],
            )

        implementer_task = self._latest_child(packet["task_id"], "IMPLEMENT_SOFTWARE_TASK")
        if self._is_stale(implementer_task, planner_task):
            implementer_task = None
        if implementer_task is None:
            dispatch = self._dispatch_child(
                packet,
                task_type="IMPLEMENT_SOFTWARE_TASK",
                goal=packet["goal"],
                context={
                    "software_goal": packet["goal"],
                    "project_goal": project["goal"],
                    "parent_task_id": packet["task_id"],
                    "milestone_id": parent_context.get("milestone_id"),
                    "milestone_title": parent_context.get("milestone_title"),
                    "work_item_id": parent_context.get("work_item_id"),
                    "work_item_title": parent_context.get("work_item_title"),
                    "sequence_index": parent_context.get("sequence_index"),
                    "plan_task_id": planner_task["task_id"],
                    "plan_artifact_ref": plan_record["ref"],
                    "plan_summary": plan_payload,
                    "suggested_files": parent_context.get("suggested_files") or [],
                    "acceptance_criteria": parent_context.get("acceptance_criteria") or [],
                },
                expected_output={"artifact_type": "code_change"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Morpheus queued implementer task {dispatch.task['task_id']}.",
                findings=[dispatch.task["task_id"]],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Implementer is executing the approved software plan.",
                target_agent=dispatch.task["to_agent"],
            )
        if implementer_task["status"] in TERMINAL_CHILD_FAILURES:
            return self._blocked_response(
                packet,
                summary=f"Implementer could not complete the software task for {packet['project_id']}.",
                blocking_facts=[f"implementer_status={implementer_task['status']}"],
            )
        code_record, code_payload = self._latest_artifact_payload(
            packet["project_id"],
            task_id=implementer_task["task_id"],
            artifact_type="code_change",
        )
        if code_record is None or not isinstance(code_payload, dict):
            return self._blocked_response(
                packet,
                summary=f"Implementer completed but no code_change artifact was persisted for {packet['project_id']}.",
                blocking_facts=[f"implementer_task={implementer_task['task_id']}"],
            )

        tester_task = self._latest_child(packet["task_id"], "TEST_SOFTWARE_TASK")
        if self._is_stale(tester_task, implementer_task):
            tester_task = None
        if tester_task is None:
            dispatch = self._dispatch_child(
                packet,
                task_type="TEST_SOFTWARE_TASK",
                goal=f"Validate implementation for {packet['goal']}",
                context={
                    "software_goal": packet["goal"],
                    "parent_task_id": packet["task_id"],
                    "milestone_id": parent_context.get("milestone_id"),
                    "milestone_title": parent_context.get("milestone_title"),
                    "work_item_id": parent_context.get("work_item_id"),
                    "work_item_title": parent_context.get("work_item_title"),
                    "sequence_index": parent_context.get("sequence_index"),
                    "plan_task_id": planner_task["task_id"],
                    "implementer_task_id": implementer_task["task_id"],
                    "plan_artifact_ref": plan_record["ref"],
                    "code_change_ref": code_record["ref"],
                    "plan_summary": plan_payload,
                    "code_summary": code_payload,
                    "acceptance_criteria": parent_context.get("acceptance_criteria") or [],
                    "force_test_result": parent_context.get("force_test_result"),
                    "failure_cause": parent_context.get("failure_cause"),
                },
                expected_output={"artifact_type": "test_execution_report"},
            )
            return self._response(
                packet,
                status="RUNNING",
                summary=f"Morpheus queued tester task {dispatch.task['task_id']}.",
                findings=[dispatch.task["task_id"]],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Tester is validating the software change.",
                target_agent=dispatch.task["to_agent"],
            )
        if tester_task["status"] in TERMINAL_CHILD_FAILURES:
            return self._blocked_response(
                packet,
                summary=f"Tester could not complete validation for {packet['project_id']}.",
                blocking_facts=[f"tester_status={tester_task['status']}"],
            )
        test_record, test_payload = self._latest_artifact_payload(
            packet["project_id"],
            task_id=tester_task["task_id"],
            artifact_type="test_execution_report",
        )
        if test_record is None or not isinstance(test_payload, dict):
            return self._blocked_response(
                packet,
                summary=f"Tester completed but no test_execution_report artifact was persisted for {packet['project_id']}.",
                blocking_facts=[f"tester_task={tester_task['task_id']}"],
            )
        if test_payload.get("result") != "PASS":
            retry_task_type = self._retry_stage_for_test_result(test_payload)
            if retry_task_type and self._child_task_count(packet["task_id"], retry_task_type) < self.max_retry_cycles:
                dispatch = self._dispatch_child(
                    packet,
                    task_type=retry_task_type,
                    goal=packet["goal"],
                    context={
                        "software_goal": packet["goal"],
                        "project_goal": project["goal"],
                        "parent_task_id": packet["task_id"],
                        "retry_reason": test_payload.get("failure_cause") or "UNKNOWN",
                        "latest_test_report": test_payload,
                        "plan_task_id": planner_task["task_id"],
                        "implementer_task_id": implementer_task["task_id"],
                        "plan_artifact_ref": plan_record["ref"],
                        "code_change_ref": code_record["ref"],
                        "force_test_result": parent_context.get("force_test_result"),
                        "failure_cause": parent_context.get("failure_cause"),
                        "suggested_files": parent_context.get("suggested_files") or [],
                    },
                    expected_output={"artifact_type": SOFTWARE_STEP_CONFIG[retry_task_type]["artifact_type"]},
                )
                return self._response(
                    packet,
                    status="RUNNING",
                    summary=(
                        f"Morpheus queued {dispatch.task['to_agent']} retry task {dispatch.task['task_id']} "
                        f"after test result {test_payload.get('result')}."
                    ),
                    findings=[test_payload.get("failure_cause") or "UNKNOWN"],
                    risks=test_payload.get("failures") or [],
                    next_action_type="WAIT_FOR_EXTERNAL",
                    next_action_reason=f"Retrying {retry_task_type} based on test evidence.",
                    target_agent=dispatch.task["to_agent"],
                )
            return self._blocked_response(
                packet,
                summary=f"Morpheus cannot recover the current software task for {packet['project_id']} after test failures.",
                blocking_facts=test_payload.get("failures") or [test_payload.get("failure_cause") or "UNKNOWN"],
            )

        delivery_package = self._delivery_payload(
            packet,
            parent_context=parent_context,
            plan_payload=plan_payload,
            code_payload=code_payload,
            test_payload=test_payload,
        )
        return self._response(
            packet,
            status="SUCCESS",
            summary=f"Morpheus completed the software loop for {packet['project_id']}.",
            artifacts_out=[
                {
                    "artifact_type": "software_delivery_package",
                    "ref": f"inline://morpheus-delivery-{packet['task_id']}",
                    "payload": delivery_package,
                    "metadata": {"engine": "morpheus_rule_loop"},
                }
            ],
            findings=[
                {
                    "plan_task_id": planner_task["task_id"],
                    "implementer_task_id": implementer_task["task_id"],
                    "tester_task_id": tester_task["task_id"],
                }
            ],
            risks=code_payload.get("known_limitations") or [],
            next_action_type="RETURN_TO_REQUESTER",
            next_action_reason="Software delivery package is ready for the requesting agent.",
            target_agent=parent_task["from_agent"],
        )

    def handle_child_completion(self, task_id: str) -> "DispatchReceipt" | None:
        child_task = self.store.get_task(task_id)
        if not child_task or not child_task.get("parent_task_id"):
            return None
        parent_task = self.store.get_task(child_task["parent_task_id"])
        if not parent_task:
            return None
        if parent_task["to_agent"] != "morpheus" or parent_task["task_type"] != "ORCHESTRATE_SOFTWARE":
            return None
        if parent_task["status"] in {"SUCCESS", "FAILED", "BLOCKED", "CANCELLED", "NEEDS_CLARIFICATION"}:
            return None
        if self.store.get_active_task_attempt(parent_task["task_id"]):
            return None
        reply_stream, reply_topic = self.dispatcher.reply_address_for_task(
            parent_task["project_id"],
            parent_task["task_id"],
            parent_task["task_type"],
        )
        self.store.update(
            "projects",
            {
                "current_phase": "software_orchestration",
            },
            where_clause="project_id = ?",
            where_params=[parent_task["project_id"]],
        )
        return self.dispatcher.dispatch_plan(
            DispatchPlan(
                project_id=parent_task["project_id"],
                task_id=parent_task["task_id"],
                target_agent="morpheus",
                task_type=parent_task["task_type"],
                reply_stream=reply_stream,
                reply_topic=reply_topic,
                reason=parent_task["goal"],
            )
        )
