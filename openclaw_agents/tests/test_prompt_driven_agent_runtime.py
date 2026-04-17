import tempfile
import unittest
from pathlib import Path

from openclaw_agents.agents import AgentEnvironment, AgentRuntimeManager
from openclaw_agents.communication.zulip_gateway import ZulipGateway


class _FakeModelClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate_json(self, *, target, system_prompt: str, user_prompt: str) -> dict[str, object]:
        self.calls.append(
            {
                "target_model": target.model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )
        if not self.responses:
            raise AssertionError("fake model client exhausted scripted responses")
        return dict(self.responses.pop(0))


class _FakeWebResearchService:
    def search(self, query: str, *, limit: int = 5) -> dict[str, object]:
        return {
            "query": query,
            "results": [
                {"title": "OpenAI weather API example", "url": "https://example.com/weather-api"},
                {"title": "NOAA overview", "url": "https://example.com/noaa"},
            ][:limit],
        }

    def fetch_url(self, url: str, *, max_chars: int = 4000) -> dict[str, object]:
        return {"url": url, "final_url": url, "content_type": "text/html", "content": "Example content"[:max_chars]}

    def research(
        self,
        query: str,
        *,
        search_limit: int = 5,
        fetch_limit: int = 3,
        max_chars: int = 1600,
    ) -> dict[str, object]:
        del search_limit, fetch_limit, max_chars
        return {
            "query": query,
            "results": [
                {"rank": 1, "title": "Weather API comparison", "url": "https://example.com/weather", "domain": "example.com", "search_snippet": "Comparison article."},
                {"rank": 2, "title": "NOAA docs", "url": "https://example.com/noaa", "domain": "example.com", "search_snippet": "Official public data docs."},
            ],
            "sources": [
                {
                    "citation_index": 1,
                    "title": "Weather API comparison",
                    "url": "https://example.com/weather",
                    "domain": "example.com",
                    "search_snippet": "Comparison article.",
                    "content_excerpt": "This article compares several weather APIs for developer use.",
                    "content_type": "text/html",
                },
                {
                    "citation_index": 2,
                    "title": "NOAA docs",
                    "url": "https://example.com/noaa",
                    "domain": "example.com",
                    "search_snippet": "Official public data docs.",
                    "content_excerpt": "NOAA provides official weather and forecast data feeds.",
                    "content_type": "text/html",
                },
            ],
            "citations": [
                "[1] Weather API comparison (example.com) - https://example.com/weather",
                "[2] NOAA docs (example.com) - https://example.com/noaa",
            ],
        }


def _build_runtime_gateway(
    temp_dir: str,
    fake_model: _FakeModelClient,
    *,
    web_research=None,
) -> ZulipGateway:
    gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
    if web_research is not None:
        gateway.web_research = web_research
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
        model_client=fake_model,
    )
    return gateway


class PromptDrivenAgentRuntimeTest(unittest.TestCase):
    def test_neo_handles_general_dm_without_project_specific_stub_logic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "REST is simpler for broad ecosystem compatibility; gRPC is stronger for typed internal APIs and streaming.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "api_tradeoffs"},
                    }
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model)

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "neo",
                    "sender_email": "master@example.com",
                    "raw_content": "Compare REST and gRPC for an internal control plane.",
                }
            )

            sent = gateway.plugin.sent_messages[-1]
            self.assertIn("REST", sent["content_markdown"])
            self.assertIn("gRPC", sent["content_markdown"])
            self.assertEqual(fake_model.calls[0]["target_model"], "gemma4:31b")
            self.assertTrue(str(fake_model.calls[0]["system_prompt"]).startswith("<|think|>"))

    def test_neo_can_use_project_tools_inside_model_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "",
                        "tool_calls": [{"tool_name": "list_open_projects", "arguments": {}}],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "project_inventory"},
                    },
                    {
                        "reply": "Open projects right now are Atlas API and Beacon UI.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "project_inventory"},
                    },
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model)
            gateway.project_provisioning.create_project_surface(
                name="Atlas API",
                summary="API modernization project.",
                requested_by="master@example.com",
            )
            gateway.project_provisioning.create_project_surface(
                name="Beacon UI",
                summary="UI refresh project.",
                requested_by="master@example.com",
            )

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-2",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "neo",
                    "sender_email": "master@example.com",
                    "raw_content": "What active projects are open right now?",
                }
            )

            sent = gateway.plugin.sent_messages[-1]
            self.assertIn("Atlas API", sent["content_markdown"])
            self.assertIn("Beacon UI", sent["content_markdown"])
            self.assertEqual(len(fake_model.calls), 2)
            self.assertIn("list_open_projects", fake_model.calls[1]["user_prompt"])

    def test_agent_smith_can_use_project_management_surface_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "",
                        "tool_calls": [{"tool_name": "get_project_management_surface", "arguments": {"project_ref": "Atlas Platform"}}],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "project_surface_review"},
                    },
                    {
                        "reply": "Atlas Platform is ACTIVE, the top milestone is Beta readiness, and the backlog still includes API parity and release automation.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "project_surface_review"},
                    },
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model)
            project = gateway.project_provisioning.create_project_surface(
                name="Atlas Platform",
                summary="Unify service APIs and rollout planning.",
                requested_by="master@example.com",
            )
            gateway.project_provisioning.update_project_surface(
                project_id=project["id"],
                updates={
                    "milestones": ["Beta readiness", "Public rollout"],
                    "backlog_items": ["Finish API parity", "Automate release checks"],
                    "blockers": ["Missing staging credentials"],
                    "decisions": ["Ship beta after parity freeze."],
                },
                requested_by="master@example.com",
            )

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-smith-surface-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Give me the current management view for Atlas Platform.",
                }
            )

            sent = gateway.plugin.sent_messages[-1]
            self.assertIn("Atlas Platform", sent["content_markdown"])
            self.assertIn("backlog", sent["content_markdown"].lower())
            self.assertEqual(len(fake_model.calls), 2)
            self.assertIn("get_project_management_surface", fake_model.calls[1]["user_prompt"])

    def test_neo_can_use_web_research_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "",
                        "tool_calls": [{"tool_name": "web_search", "arguments": {"query": "best weather api", "limit": 2}}],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "weather_api_research"},
                    },
                    {
                        "reply": "Two reasonable weather data options are OpenAI weather API example coverage and NOAA references for public data feeds.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "weather_api_research"},
                    },
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model, web_research=_FakeWebResearchService())

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-web-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "neo",
                    "sender_email": "master@example.com",
                    "raw_content": "Find me a good weather API to evaluate.",
                }
            )

            sent = gateway.plugin.sent_messages[-1]
            self.assertIn("weather", sent["content_markdown"].lower())
            self.assertEqual(len(fake_model.calls), 2)
            self.assertIn("web_search", fake_model.calls[1]["user_prompt"])

    def test_neo_can_use_multi_source_research_tool_with_citations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "",
                        "tool_calls": [{"tool_name": "research_brief", "arguments": {"query": "best public weather api", "search_limit": 4, "fetch_limit": 2}}],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "weather_api_brief"},
                    },
                    {
                        "reply": "OpenWeather-style developer APIs are easy to evaluate, while NOAA-style public feeds are stronger when official public data matters [1][2].",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "weather_api_brief"},
                    },
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model, web_research=_FakeWebResearchService())

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-research-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "neo",
                    "sender_email": "master@example.com",
                    "raw_content": "Research public weather APIs and cite the strongest sources.",
                }
            )

            sent = gateway.plugin.sent_messages[-1]
            self.assertIn("[1]", sent["content_markdown"])
            self.assertIn("[2]", sent["content_markdown"])
            self.assertEqual(len(fake_model.calls), 2)
            self.assertIn("research_brief", fake_model.calls[1]["user_prompt"])

    def test_neo_can_run_workspace_command_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "",
                        "tool_calls": [{"tool_name": "run_workspace_command", "arguments": {"command": "printf executive"}}],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "command_execution"},
                    },
                    {
                        "reply": "The command completed successfully and printed executive.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "command_execution"},
                    },
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model)

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-exec-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "neo",
                    "sender_email": "master@example.com",
                    "raw_content": "Run a quick command and tell me the output.",
                }
            )

            sent = gateway.plugin.sent_messages[-1]
            self.assertIn("executive", sent["content_markdown"])
            self.assertIn("run_workspace_command", fake_model.calls[1]["user_prompt"])

    def test_neo_can_directly_mutate_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "",
                        "tool_calls": [{"tool_name": "create_project_surface", "arguments": {"name": "Orbit Control", "summary": "Executive-created project."}}],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "direct_project_create"},
                    },
                    {
                        "reply": "I created Orbit Control and opened the canonical project thread.",
                        "tool_calls": [],
                        "action_intent": {"kind": "none", "payload": {}},
                        "working_memory": {"focus": "direct_project_create"},
                    },
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model)

            result = gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-mutate-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "neo",
                    "sender_email": "master@example.com",
                    "raw_content": "Create a new project called Orbit Control.",
                }
            )

            projects = gateway.project_registry.list_projects(include_done=True)
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["name"], "Orbit Control")
            self.assertGreaterEqual(len(result["message_ids"]), 2)
            self.assertEqual(gateway.projection_event_service.list_events(project_id=projects[0]["id"])[0]["event_type"], "project_kickoff")

    def test_agent_smith_routes_mutation_intent_into_confirmation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "I can set that up once you confirm the project creation.",
                        "tool_calls": [],
                        "action_intent": {
                            "kind": "project_mutation_request",
                            "summary": "Create a new project surface for Edge Sync.",
                            "payload": {
                                "action": "create_project",
                                "name": "Edge Sync",
                                "summary": "Near-real-time replication service.",
                            },
                        },
                        "working_memory": {"focus": "project_creation"},
                    }
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model)

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-3",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Create project Edge Sync for near-real-time replication.",
                }
            )

            self.assertEqual(gateway.project_registry.list_projects(), [])
            pending = gateway.state_store.list_pending_approvals(
                requester_email="master@example.com", owner_agent="agent_smith"
            )
            self.assertEqual(len(pending), 1)
            sent = gateway.plugin.sent_messages[-1]
            self.assertIn("Approval ID", sent["content_markdown"])
            self.assertIn("Edge Sync", sent["content_markdown"])

    def test_agent_smith_structured_project_update_persists_tasks_and_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_model = _FakeModelClient(
                [
                    {
                        "reply": "I’ve prepared the backlog and blocker update. Confirm it and I’ll persist it.",
                        "tool_calls": [],
                        "action_intent": {
                            "kind": "project_mutation_request",
                            "summary": "Update Atlas Platform backlog and blockers.",
                            "payload": {
                                "action": "update_project",
                                "project_ref": "Atlas Platform",
                                "backlog_items": ["Finish API parity", "Automate release checks"],
                                "blockers": ["Missing staging credentials"],
                                "next_actions": ["Escalate credential request", "Prepare beta checklist"],
                            },
                        },
                        "working_memory": {"focus": "backlog_refresh"},
                    }
                ]
            )
            gateway = _build_runtime_gateway(temp_dir, fake_model)
            project = gateway.project_provisioning.create_project_surface(
                name="Atlas Platform",
                summary="Unify service APIs and rollout planning.",
                requested_by="master@example.com",
            )

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-smith-update-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Update Atlas Platform backlog and blockers for the beta push.",
                }
            )

            pending = gateway.state_store.list_pending_approvals(
                requester_email="master@example.com",
                owner_agent="agent_smith",
            )
            self.assertEqual(len(pending), 1)
            approval_id = pending[0]["approval_id"]
            self.assertIn("backlog_items", pending[0]["change"])
            self.assertIn("blockers", pending[0]["change"])

            gateway.process_raw_event(
                {
                    "event_id": "evt-runtime-smith-update-2",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": f"confirm {approval_id}",
                }
            )

            updated = gateway.state_store.get_project(project["id"])
            assert updated is not None
            self.assertEqual(updated["backlog_items"], ["Finish API parity", "Automate release checks"])
            self.assertEqual(updated["blockers"], ["Missing staging credentials"])
            self.assertEqual(updated["next_actions"], ["Escalate credential request", "Prepare beta checklist"])

            backlog_file = gateway.workspace_service.read_project_file(project["id"], "management/BACKLOG.md")
            status_file = gateway.workspace_service.read_project_file(project["id"], "management/STATUS.md")
            self.assertIn("Finish API parity", backlog_file)
            self.assertIn("Missing staging credentials", status_file)

            events = gateway.projection_event_service.list_events(project["id"])
            event_types = {row["event_type"] for row in events}
            self.assertIn("tasks_updated", event_types)
            self.assertIn("project_change_confirmed", event_types)
            self.assertIn("execution_handoff_created", event_types)


if __name__ == "__main__":
    unittest.main()
