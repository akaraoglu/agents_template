import tempfile
import unittest
from pathlib import Path

from openclaw_agents.agents import AgentEnvironment, AgentRuntimeManager
from openclaw_agents.communication.zulip_gateway import ZulipGateway


class _FakeModelClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)

    def generate_json(self, *, target, system_prompt: str, user_prompt: str) -> dict[str, object]:
        del target, system_prompt, user_prompt
        if not self.responses:
            raise AssertionError("fake model client exhausted scripted responses")
        return dict(self.responses.pop(0))


def _build_gateway(temp_dir: str, responses: list[dict[str, object]]) -> ZulipGateway:
    gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
    gateway.agent_runtime = AgentRuntimeManager(
        env=AgentEnvironment(
            state_store=gateway.state_store,
            project_registry=gateway.project_registry,
            project_provisioning=gateway.project_provisioning,
            workspace_service=gateway.workspace_service,
            artifact_ref_service=gateway.artifact_ref_service,
            policy_service=gateway.policy_service,
            mutation_service=gateway.mutation_service,
            projection_event_service=gateway.projection_event_service,
            conversation_memory=gateway.conversation_memory,
            working_memory=gateway.working_memory,
            command_runner=gateway.command_runner,
            web_research=gateway.web_research,
            dm_context_resolver=gateway.dm_context_resolver,
            topic_router=gateway.topic_router,
            registry=gateway.agent_registry,
            audit_log=gateway.audit_log,
            execution_state=gateway.execution_state,
            internal_loop=gateway.internal_loop,
        ),
        model_client=_FakeModelClient(responses),
    )
    return gateway


def _seed_handoff(gateway: ZulipGateway) -> tuple[dict[str, object], dict[str, object]]:
    project = gateway.project_provisioning.create_project_surface(
        name="Loop Runtime",
        summary="Internal loop execution project.",
        requested_by="master@example.com",
    )
    handoff = gateway.artifact_ref_service.persist_execution_handoff(
        gateway.artifact_ref_service.build_execution_handoff(
            project=project,
            approved_summary="Approved execution for the internal loop runtime.",
        )
    )
    return project, handoff


class InternalSoftwareLoopTest(unittest.TestCase):
    def test_internal_loop_progresses_to_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = _build_gateway(
                temp_dir,
                [
                    {"reply": "Niaobe started the execution loop and handed control to Morpheus.", "tool_calls": [], "action_intent": {"kind": "none"}, "working_memory": {"focus": "niaobe"}},
                    {"reply": "Execution objective is runtime stabilization with a planner-first loop.", "tool_calls": [], "action_intent": {"kind": "none"}, "working_memory": {"focus": "morpheus"}},
                    {"reply": "Plan: validate workspace, update the internal plan, then hand the execution package to Implementer.", "tool_calls": [], "action_intent": {"kind": "none"}, "working_memory": {"focus": "planner"}},
                    {"reply": "Implementation package: update runtime notes and prepare the verification handoff.", "tool_calls": [], "action_intent": {"kind": "none"}, "working_memory": {"focus": "implementer"}},
                    {
                        "reply": "Verification is ready.",
                        "tool_calls": [],
                        "action_intent": {
                            "kind": "verification_report",
                            "summary": "Verification completed.",
                            "payload": {
                                "report_summary": "Verification completed.",
                                "report_body": "Smoke validation passed for the internal runtime loop.",
                            },
                        },
                        "working_memory": {"focus": "tester"},
                    },
                ],
            )
            project, handoff = _seed_handoff(gateway)

            for _ in range(4):
                gateway.process_pending_runtime_work()

            run = gateway.internal_loop.get_run_for_handoff(handoff["handoff_id"])
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run["status"], "COMPLETED")
            self.assertEqual(set(run["stage_results"].keys()), {"morpheus", "planner", "implementer", "tester"})

            self.assertIn("validate workspace", gateway.workspace_service.read_project_file(project["id"], "management/PLAN.md").lower())
            self.assertIn("implementation package", gateway.workspace_service.read_project_file(project["id"], "artifacts/reports/IMPLEMENTATION_NOTES.md").lower())
            self.assertIn("Smoke validation passed", gateway.workspace_service.read_project_file(project["id"], "management/TEST_REPORT.md"))

            execution_state = gateway.execution_state.get_state(handoff_id=handoff["handoff_id"])
            self.assertIsNotNone(execution_state)
            assert execution_state is not None
            self.assertEqual(execution_state["status"], "VERIFICATION_REPORTED")

            event_types = {row["event_type"] for row in gateway.projection_event_service.list_events(project["id"])}
            self.assertIn("plan_updated", event_types)
            self.assertIn("tasks_updated", event_types)
            self.assertIn("verification_reported", event_types)

    def test_internal_loop_blocker_escalates_via_niaobe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = _build_gateway(
                temp_dir,
                [
                    {"reply": "Niaobe started the execution loop and handed control to Morpheus.", "tool_calls": [], "action_intent": {"kind": "none"}, "working_memory": {"focus": "niaobe"}},
                    {"reply": "Morpheus handoff accepted.", "tool_calls": [], "action_intent": {"kind": "none"}, "working_memory": {"focus": "morpheus"}},
                    {"reply": "Plan is ready.", "tool_calls": [], "action_intent": {"kind": "none"}, "working_memory": {"focus": "planner"}},
                    {
                        "reply": "Execution is blocked on missing staging credentials.",
                        "tool_calls": [],
                        "action_intent": {
                            "kind": "execution_blocker",
                            "summary": "Missing staging credentials.",
                            "payload": {
                                "blocker": "Missing staging credentials",
                                "next_step": "AgentSmith needs to unblock credential access.",
                            },
                        },
                        "working_memory": {"focus": "implementer"},
                    },
                ],
            )
            project, handoff = _seed_handoff(gateway)

            for _ in range(3):
                gateway.process_pending_runtime_work()

            run = gateway.internal_loop.get_run_for_handoff(handoff["handoff_id"])
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run["status"], "BLOCKED")
            self.assertEqual(run["blocked_stage"], "implementer")

            execution_state = gateway.execution_state.get_state(handoff_id=handoff["handoff_id"])
            self.assertIsNotNone(execution_state)
            assert execution_state is not None
            self.assertEqual(execution_state["status"], "BLOCKED")

            dm_posts = [row for row in gateway.plugin.sent_messages if row["target_type"] == "dm"]
            self.assertTrue(any(row["target_email"] == "agentsmith-bot@bots.localdomain" for row in dm_posts))
            self.assertEqual(gateway.state_store.get_project(project["id"])["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
