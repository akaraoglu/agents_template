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


def _seed_pending_handoff(gateway: ZulipGateway) -> tuple[dict[str, object], dict[str, object]]:
    project = gateway.project_provisioning.create_project_surface(
        name="Atlas Runtime",
        summary="Execution runtime rollout.",
        requested_by="master@example.com",
    )
    handoff = gateway.artifact_ref_service.persist_execution_handoff(
        gateway.artifact_ref_service.build_execution_handoff(
            project=project,
            approved_summary="Approved execution handoff for Atlas Runtime.",
        )
    )
    return project, handoff


class NiaobeExecutionRuntimeTest(unittest.TestCase):
    def test_pending_handoff_is_consumed_into_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = _build_gateway(
                temp_dir,
                [
                    {
                        "reply": "Execution intake started. I will begin with workspace validation and first-step verification.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "execution_start"},
                    },
                    {
                        "reply": "Morpheus accepted the internal loop.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "morpheus"},
                    }
                ],
            )
            project, handoff = _seed_pending_handoff(gateway)

            results = gateway.process_pending_runtime_work()

            self.assertEqual(len(results), 1)
            stored_handoff = gateway.state_store.get_handoff(handoff["handoff_id"])
            self.assertEqual(stored_handoff["status"], "IN_PROGRESS")
            execution_state = gateway.execution_state.get_state(handoff_id=handoff["handoff_id"])
            self.assertIsNotNone(execution_state)
            self.assertEqual(execution_state["status"], "IN_PROGRESS")

            stream_posts = [row for row in gateway.plugin.sent_messages if row["target_type"] == "stream"]
            self.assertTrue(any("Execution intake started" in row["content_markdown"] for row in stream_posts))
            self.assertTrue(any(project["id"] == row["project_id"] for row in stream_posts))

    def test_blocker_reports_escalate_to_agent_smith_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = _build_gateway(
                temp_dir,
                [
                    {
                        "reply": "",
                        "tool_calls": [{"tool_name": "report_execution_blocker", "arguments": {"blocker": "Missing staging credentials", "next_step": "Need AgentSmith to unblock credentials."}}],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "blocker"},
                    },
                    {
                        "reply": "Execution is blocked on missing staging credentials.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "blocker"},
                    },
                    {
                        "reply": "Morpheus accepted the internal loop.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "morpheus"},
                    },
                ],
            )
            project, handoff = _seed_pending_handoff(gateway)

            gateway.process_pending_runtime_work()

            stored_handoff = gateway.state_store.get_handoff(handoff["handoff_id"])
            self.assertEqual(stored_handoff["status"], "BLOCKED")
            execution_state = gateway.execution_state.get_state(handoff_id=handoff["handoff_id"])
            self.assertIsNotNone(execution_state)
            self.assertEqual(execution_state["status"], "BLOCKED")
            self.assertEqual(gateway.state_store.get_project(project["id"])["status"], "BLOCKED")

            dm_posts = [row for row in gateway.plugin.sent_messages if row["target_type"] == "dm"]
            self.assertTrue(any(row["target_email"] == "agentsmith-bot@bots.localdomain" for row in dm_posts))

            events = gateway.projection_event_service.list_events(project["id"])
            self.assertIn("execution_blocked", {row["event_type"] for row in events})

    def test_restart_recovers_pending_handoff_from_authoritative_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir) / "runtime"
            gateway = _build_gateway(
                temp_dir,
                [
                    {
                        "reply": "Execution intake started after restart.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "restart"},
                    },
                    {
                        "reply": "Morpheus accepted the internal loop.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "morpheus"},
                    }
                ],
            )
            project, handoff = _seed_pending_handoff(gateway)
            del gateway

            recovered = _build_gateway(
                temp_dir,
                [
                    {
                        "reply": "Execution intake started after restart.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "restart"},
                    },
                    {
                        "reply": "Morpheus accepted the internal loop.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "morpheus"},
                    }
                ],
            )
            recovered.base_dir = base_dir

            results = recovered.process_pending_runtime_work()

            self.assertEqual(len(results), 1)
            self.assertEqual(recovered.state_store.get_handoff(handoff["handoff_id"])["status"], "IN_PROGRESS")
            self.assertEqual(recovered.execution_state.get_state(handoff_id=handoff["handoff_id"])["status"], "IN_PROGRESS")
            self.assertTrue(any(row["project_id"] == project["id"] for row in recovered.plugin.sent_messages if row["target_type"] == "stream"))
