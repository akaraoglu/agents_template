"""Built-in deterministic role executors for local control-plane flows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.communication.zulip_gateway import DispatchPlan
from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.orchestrators.morpheus_engine import MorpheusLoopEngine
from openclaw_agents.orchestrators.niaobe_engine import NiaobeLoopEngine
from openclaw_agents.runtime.artifact_parsers import ArtifactParser


class BuiltinRoleExecutor:
    """Execute a small built-in subset of roles without external runtime dependencies."""

    def __init__(
        self,
        *,
        store: ControlPlaneStore | None = None,
        dispatcher: Any,
        artifact_parser: ArtifactParser | None = None,
        agent_registry_path: str | Path | None = None,
    ) -> None:
        self.store = store or dispatcher.store
        self.dispatcher = dispatcher
        self.artifact_parser = artifact_parser or ArtifactParser(self.store)
        base = Path(__file__).resolve().parents[1]
        self.agent_registry = yaml.safe_load(
            Path(agent_registry_path or base / "config" / "agent_registry.yaml").read_text()
        )
        self.morpheus_engine = MorpheusLoopEngine(
            store=self.store,
            dispatcher=self.dispatcher,
            artifact_parser=self.artifact_parser,
        )
        self.niaobe_engine = NiaobeLoopEngine(
            store=self.store,
            dispatcher=self.dispatcher,
            artifact_parser=self.artifact_parser,
        )

    def _prompt_path(self, agent_id: str) -> str | None:
        return ((self.agent_registry.get("agents") or {}).get(agent_id) or {}).get("prompt_path")

    def _response(
        self,
        packet: dict[str, Any],
        *,
        status: str,
        summary: str,
        artifacts_out: list[dict[str, Any]] | None = None,
        findings: list[Any] | None = None,
        risks: list[str] | None = None,
        next_action_type: str = "RETURN_TO_REQUESTER",
        next_action_reason: str,
        target_agent: str | None = None,
    ) -> dict[str, Any]:
        next_action: dict[str, Any] = {"type": next_action_type, "reason": next_action_reason}
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
                "executor": "builtin",
                "prompt_path": self._prompt_path(packet["to_agent"]),
            },
        }

    def _latest_payload(
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

    def _planner_response(self, packet: dict[str, Any]) -> dict[str, Any]:
        context = packet.get("context") or {}
        software_goal = context.get("software_goal") or packet["goal"]
        requirements = list(context.get("requirements") or [])
        if not requirements:
            requirements = [software_goal]
        if context.get("project_goal") and context.get("project_goal") != software_goal:
            requirements.append(context["project_goal"])
        plan = {
            "summary": f"Plan for {software_goal}",
            "milestone_id": context.get("milestone_id"),
            "milestone_title": context.get("milestone_title"),
            "work_item_id": context.get("work_item_id"),
            "work_item_title": context.get("work_item_title"),
            "task_breakdown": [software_goal],
            "implementation_steps": [
                "Inspect the current project workspace and relevant files.",
                f"Implement the behavior needed for: {software_goal}",
                "Update tests and supporting notes for the changed behavior.",
            ],
            "test_obligations": [
                f"Cover the primary success path for: {software_goal}",
                "Cover one regression or edge-case path affected by the change.",
            ],
            "risks": [],
            "open_questions": [],
            "requirements": requirements,
        }
        return self._response(
            packet,
            status="SUCCESS",
            summary=f"Planner produced a software task plan for {packet['project_id']}.",
            artifacts_out=[
                {
                    "artifact_type": "software_task_plan",
                    "ref": f"inline://planner-plan-{packet['task_id']}",
                    "payload": plan,
                    "metadata": {"executor": "builtin"},
                }
            ],
            findings=plan["implementation_steps"],
            next_action_reason="Planner completed the requested software plan.",
            target_agent=packet["from_agent"],
        )

    @staticmethod
    def _delivery_plan_seed(context: dict[str, Any], goal: str, acceptance_criteria: list[str]) -> list[dict[str, Any]]:
        milestones = list(context.get("milestones") or [])
        if not milestones:
            return [
                {
                    "milestone_id": "M1",
                    "title": "Software Delivery",
                    "goal": goal,
                    "requirements": list(context.get("requirements") or [goal]),
                    "acceptance_criteria": acceptance_criteria,
                }
            ]
        normalized: list[dict[str, Any]] = []
        for index, milestone in enumerate(milestones, start=1):
            if not isinstance(milestone, dict):
                continue
            title = str(milestone.get("title") or milestone.get("goal") or f"Milestone {index}").strip()
            normalized.append(
                {
                    "milestone_id": str(milestone.get("milestone_id") or f"M{index}"),
                    "title": title,
                    "goal": str(milestone.get("goal") or title),
                    "requirements": list(milestone.get("requirements") or milestone.get("notes") or [title]),
                    "acceptance_criteria": list(milestone.get("acceptance_criteria") or acceptance_criteria),
                    "constraints": list(milestone.get("constraints") or []),
                    "dependencies": list(milestone.get("dependencies") or []),
                }
            )
        return normalized or [
            {
                "milestone_id": "M1",
                "title": "Software Delivery",
                "goal": goal,
                "requirements": list(context.get("requirements") or [goal]),
                "acceptance_criteria": acceptance_criteria,
            }
        ]

    def _agent_smith_response(self, packet: dict[str, Any]) -> dict[str, Any]:
        context = packet.get("context") or {}
        goal = packet["goal"].strip()
        acceptance_criteria = list(context.get("acceptance_criteria") or [])
        if not acceptance_criteria:
            acceptance_criteria = [
                f"Provide a clear design and implementation path for: {goal}",
                "Produce verification evidence that the delivered result satisfies the framed scope.",
            ]
        delivery_plan_seed = self._delivery_plan_seed(context, goal, acceptance_criteria)
        charter = {
            "project_title": context.get("project_title"),
            "problem_statement": goal,
            "goals": [goal],
            "non_goals": list(context.get("non_goals") or []),
            "constraints": list(context.get("constraints") or []) + list(context.get("project_constraints") or []),
            "acceptance_criteria": acceptance_criteria,
            "initial_priority": packet["priority"],
            "dependencies": list(context.get("dependencies") or []),
            "open_questions": list(context.get("open_questions") or []),
            "delivery_shape": "multi_milestone" if len(delivery_plan_seed) > 1 else "single_delivery",
            "delivery_plan_seed": delivery_plan_seed,
            "recommended_next_handoff": {
                "task_type": "ORCHESTRATE_PROJECT",
                "target_agent": "niaobe",
            },
        }
        return self._response(
            packet,
            status="SUCCESS",
            summary=f"AgentSmith framed project {packet['project_id']} and prepared the project charter.",
            artifacts_out=[
                {
                    "artifact_type": "project_charter",
                    "ref": f"inline://agent-smith-charter-{packet['task_id']}",
                    "payload": charter,
                    "metadata": {"executor": "builtin"},
                }
            ],
            findings=charter["acceptance_criteria"],
            next_action_reason="Project charter is ready for Niaobe orchestration.",
            target_agent="niaobe",
        )

    def _architect_response(self, packet: dict[str, Any]) -> dict[str, Any]:
        context = packet.get("context") or {}
        _charter_record, charter_payload = self._latest_payload(
            packet["project_id"],
            artifact_type="project_charter",
        )
        if not isinstance(charter_payload, dict):
            return self._response(
                packet,
                status="NEEDS_CLARIFICATION",
                summary=f"Architect could not find the project charter for {packet['project_id']}.",
                findings=["missing project_charter artifact"],
                risks=["architecture cannot proceed without the charter"],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Architect needs the charter before continuing.",
                target_agent=packet["from_agent"],
            )
        goals = charter_payload.get("goals") or [packet["goal"]]
        requirements = context.get("requirements") or charter_payload.get("acceptance_criteria") or []
        architecture = {
            "summary": f"Reference architecture for {packet['project_id']}",
            "system_shape": "Niaobe-managed delivery with a bounded implementation loop and explicit verification.",
            "responsibilities": {
                "agent_smith": "frames the project charter",
                "niaobe": "routes project stages",
                "morpheus": "delivers the software package",
                "oracle": "verifies the delivered result",
            },
            "interfaces": [
                {"name": "project_charter", "role": "project framing input"},
                {"name": "software_delivery_package", "role": "implementation output"},
                {"name": "verification_report", "role": "acceptance decision"},
            ],
            "data_flow": [
                "Project charter enters through AgentSmith.",
                "Architecture constraints guide Morpheus implementation.",
                "Oracle verifies the final package against the charter.",
            ],
            "constraints": charter_payload.get("constraints") or [],
            "risks": [],
            "validation_implications": requirements,
            "unresolved_questions": charter_payload.get("open_questions") or [],
            "goals": goals,
        }
        return self._response(
            packet,
            status="SUCCESS",
            summary=f"Architect produced an architecture specification for {packet['project_id']}.",
            artifacts_out=[
                {
                    "artifact_type": "architecture_spec",
                    "ref": f"inline://architect-spec-{packet['task_id']}",
                    "payload": architecture,
                    "metadata": {"executor": "builtin"},
                }
            ],
            findings=requirements,
            next_action_reason="Architecture is ready for project orchestration.",
            target_agent=packet["from_agent"],
        )

    def _implementer_response(self, packet: dict[str, Any]) -> dict[str, Any]:
        context = packet.get("context") or {}
        _plan_record, plan_payload = self._latest_payload(
            packet["project_id"],
            task_id=context.get("plan_task_id"),
            artifact_type="software_task_plan",
        )
        if not isinstance(plan_payload, dict):
            return self._response(
                packet,
                status="BLOCKED",
                summary=f"Implementer could not find the software plan for {packet['project_id']}.",
                findings=["missing software_task_plan artifact"],
                risks=["implementation cannot proceed without a plan artifact"],
                next_action_reason="Implementer is blocked by missing planning evidence.",
                target_agent=packet["from_agent"],
            )
        changed_files = list(context.get("suggested_files") or [])
        if not changed_files:
            changed_files = ["src/implementation_placeholder.py", "tests/test_placeholder.py"]
        code_change = {
            "summary": f"Prepared implementation package for {packet['goal']}.",
            "milestone_id": context.get("milestone_id"),
            "milestone_title": context.get("milestone_title"),
            "work_item_id": context.get("work_item_id"),
            "work_item_title": context.get("work_item_title"),
            "changed_files": changed_files,
            "build_notes": "Builtin executor prepared the code-change handoff without mutating a real project repo.",
            "known_limitations": ["No real repository mutation was performed by the builtin executor."],
            "handoff_notes_for_tester": plan_payload.get("test_obligations") or [],
            "implementation_steps_used": plan_payload.get("implementation_steps") or [],
        }
        return self._response(
            packet,
            status="SUCCESS",
            summary=f"Implementer produced a code-change package for {packet['project_id']}.",
            artifacts_out=[
                {
                    "artifact_type": "code_change",
                    "ref": f"inline://implementer-change-{packet['task_id']}",
                    "payload": code_change,
                    "metadata": {"executor": "builtin"},
                }
            ],
            findings=changed_files,
            risks=code_change["known_limitations"],
            next_action_reason="Implementer finished the current software step.",
            target_agent=packet["from_agent"],
        )

    def _tester_response(self, packet: dict[str, Any]) -> dict[str, Any]:
        context = packet.get("context") or {}
        _code_record, code_payload = self._latest_payload(
            packet["project_id"],
            task_id=context.get("implementer_task_id"),
            artifact_type="code_change",
        )
        if not isinstance(code_payload, dict):
            return self._response(
                packet,
                status="BLOCKED",
                summary=f"Tester could not find the code-change artifact for {packet['project_id']}.",
                findings=["missing code_change artifact"],
                risks=["test execution requires an implementation artifact"],
                next_action_reason="Tester is blocked by missing implementation evidence.",
                target_agent=packet["from_agent"],
            )
        forced_result = context.get("force_test_result")
        result = forced_result or "PASS"
        report = {
            "summary": f"Builtin validation report for {packet['goal']}.",
            "milestone_id": context.get("milestone_id"),
            "milestone_title": context.get("milestone_title"),
            "work_item_id": context.get("work_item_id"),
            "work_item_title": context.get("work_item_title"),
            "test_changes": ["No repo mutation; validation based on handoff artifact consistency."],
            "commands_run": ["builtin:validate_software_package"],
            "result": result,
            "failures": [],
            "failure_cause": None,
            "coverage_notes": code_payload.get("handoff_notes_for_tester") or [],
        }
        if result != "PASS":
            report["failures"] = [f"Forced test result {result} requested in task context."]
            report["failure_cause"] = context.get("failure_cause") or "IMPLEMENTATION_DEFECT"
        return self._response(
            packet,
            status="SUCCESS",
            summary=f"Tester produced a validation report for {packet['project_id']} with result {report['result']}.",
            artifacts_out=[
                {
                    "artifact_type": "test_execution_report",
                    "ref": f"inline://tester-report-{packet['task_id']}",
                    "payload": report,
                    "metadata": {"executor": "builtin"},
                }
            ],
            findings=report["commands_run"],
            risks=report["failures"],
            next_action_reason="Tester finished the current software validation step.",
            target_agent=packet["from_agent"],
        )

    def _oracle_response(self, packet: dict[str, Any]) -> dict[str, Any]:
        context = packet.get("context") or {}
        _charter_record, charter_payload = self._latest_payload(packet["project_id"], artifact_type="project_charter")
        _architecture_record, architecture_payload = self._latest_payload(packet["project_id"], artifact_type="architecture_spec")
        _delivery_record, delivery_payload = self._latest_payload(packet["project_id"], artifact_type="software_delivery_package")
        if not isinstance(charter_payload, dict) or not isinstance(architecture_payload, dict) or not isinstance(delivery_payload, dict):
            return self._response(
                packet,
                status="NEEDS_CLARIFICATION",
                summary=f"Oracle is missing required evidence to verify project {packet['project_id']}.",
                findings=["project_charter, architecture_spec, and software_delivery_package are all required"],
                risks=["verification cannot proceed with incomplete evidence"],
                next_action_type="WAIT_FOR_EXTERNAL",
                next_action_reason="Oracle needs the full project evidence set.",
                target_agent=packet["from_agent"],
            )
        verification_result = context.get("force_verification_result") or "PASS"
        defect_category = None
        findings: list[str] = []
        if verification_result != "PASS":
            defect_category = context.get("verification_defect_category") or "implementation"
            findings.append(f"verification failed with defect category {defect_category}")
        verification_scope = context.get("verification_scope") or "project"
        acceptance_criteria = list(context.get("acceptance_criteria") or charter_payload.get("acceptance_criteria") or [])
        report = {
            "summary": f"Verification report for project {packet['project_id']}",
            "scope": verification_scope,
            "milestone_id": context.get("milestone_id"),
            "milestone_title": context.get("milestone_title"),
            "work_item_id": context.get("work_item_id"),
            "work_item_title": context.get("work_item_title"),
            "result": verification_result,
            "evidence": [
                "project_charter",
                "architecture_spec",
                "software_delivery_package",
            ],
            "acceptance_criteria_coverage": acceptance_criteria,
            "defect_category": defect_category,
            "findings": findings,
            "recommended_next_action": "return_to_requester",
        }
        return self._response(
            packet,
            status="SUCCESS",
            summary=f"Oracle completed project verification for {packet['project_id']} with result {verification_result}.",
            artifacts_out=[
                {
                    "artifact_type": "verification_report",
                    "ref": f"inline://oracle-report-{packet['task_id']}",
                    "payload": report,
                    "metadata": {"executor": "builtin"},
                }
            ],
            findings=report["evidence"],
            risks=report["findings"],
            next_action_reason="Oracle completed verification and returned the report to Niaobe.",
            target_agent=packet["from_agent"],
        )

    def _dispatch_from_task(
        self,
        *,
        task: dict[str, Any],
        target_agent: str | None = None,
        task_type: str | None = None,
        reason: str | None = None,
    ) -> Any:
        reply_stream, reply_topic = self.dispatcher.reply_address_for_task(
            task["project_id"],
            task["task_id"],
            task_type or task["task_type"],
        )
        return self.dispatcher.dispatch_plan(
            DispatchPlan(
                project_id=task["project_id"],
                task_id=task["task_id"],
                target_agent=target_agent or task["to_agent"],
                task_type=task_type or task["task_type"],
                reply_stream=reply_stream,
                reply_topic=reply_topic,
                reason=reason or task["goal"],
            )
        )

    def _queue_niaobe_task_from_frame(self, task: dict[str, Any]) -> None:
        existing = self.store.get_latest_child_task(task["task_id"], task_type="ORCHESTRATE_PROJECT")
        if existing:
            return
        niaobe_task = self.store.record_task(
            project_id=task["project_id"],
            parent_task_id=task["task_id"],
            from_agent="agent_smith",
            to_agent="niaobe",
            task_type="ORCHESTRATE_PROJECT",
            title=f"ORCHESTRATE_PROJECT for {task['project_id']}",
            goal=task["goal"],
            priority=task["priority"],
            context=task.get("context_json") or {},
            expected_output={"artifact_type": "project_status_report"},
            decision_bounds=task.get("decision_bounds_json") or {},
            return_to="requesting_agent",
        )
        self.store.update(
            "projects",
            {
                "current_phase": "project_orchestration",
                "project_status": "ACTIVE",
                "runtime_status": "READY",
                "current_owner_agent": "niaobe",
                "updated_at": niaobe_task["updated_at"],
            },
            where_clause="project_id = ?",
            where_params=[task["project_id"]],
        )
        self._dispatch_from_task(task=niaobe_task, target_agent="niaobe", task_type="ORCHESTRATE_PROJECT")

    def _handle_terminal_project_state(self, task: dict[str, Any], response: dict[str, Any]) -> None:
        artifact_types = {
            item.get("artifact_type")
            for item in response.get("artifacts_out", [])
            if isinstance(item, dict) and item.get("artifact_type")
        }
        if task["to_agent"] == "niaobe" and "project_closure_report" in artifact_types and response["status"] == "SUCCESS":
            self.store.update(
                "projects",
                {
                    "project_status": "DONE",
                    "runtime_status": "DONE",
                    "current_phase": "project_closed",
                },
                where_clause="project_id = ?",
                where_params=[task["project_id"]],
            )
            return
        if task["to_agent"] == "niaobe" and response["status"] == "BLOCKED":
            self.store.update(
                "projects",
                {
                    "project_status": "BLOCKED",
                    "runtime_status": "BLOCKED",
                    "current_phase": "blocked",
                },
                where_clause="project_id = ?",
                where_params=[task["project_id"]],
            )
            return
        if task["to_agent"] == "niaobe" and response["status"] == "NEEDS_CLARIFICATION":
            self.store.update(
                "projects",
                {
                    "runtime_status": "WAITING_EXTERNAL",
                    "current_phase": "clarify",
                },
                where_clause="project_id = ?",
                where_params=[task["project_id"]],
            )

    def execute(self, packet: dict[str, Any]) -> dict[str, Any]:
        agent_id = packet["to_agent"]
        if agent_id == "agent_smith":
            return self._agent_smith_response(packet)
        if agent_id == "niaobe":
            return self.niaobe_engine.execute(packet)
        if agent_id == "architect":
            return self._architect_response(packet)
        if agent_id == "morpheus":
            return self.morpheus_engine.execute(packet)
        if agent_id == "oracle":
            return self._oracle_response(packet)
        if agent_id == "planner":
            return self._planner_response(packet)
        if agent_id == "implementer":
            return self._implementer_response(packet)
        if agent_id == "tester":
            return self._tester_response(packet)
        raise RuntimeError(f"builtin executor does not support agent {agent_id}")

    def handle_recorded_response(self, response: dict[str, Any], _record: Any) -> None:
        if response["status"] in {"PENDING", "RUNNING"}:
            return
        task = self.store.get_task(response["task_id"])
        if not task:
            return
        self._handle_terminal_project_state(task, response)
        if task["to_agent"] == "agent_smith" and task["task_type"] == "FRAME_PROJECT" and response["status"] == "SUCCESS":
            self._queue_niaobe_task_from_frame(task)
            return
        if not task.get("parent_task_id"):
            return
        if task["to_agent"] in {"planner", "implementer", "tester"}:
            self.morpheus_engine.handle_child_completion(task["task_id"])
            return
        if task["to_agent"] in {"architect", "morpheus", "oracle"}:
            self.niaobe_engine.handle_child_completion(task["task_id"])
