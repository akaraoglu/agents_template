from __future__ import annotations

import unittest
from types import SimpleNamespace

from openclaw_agents.communication.zulip_gateway import GatewayEvent, ZulipGateway
from openclaw_agents.communication.zulip_gateway_service import GatewayService
from openclaw_agents.database.store import utc_now
from openclaw_agents.scheduler.workspace_provisioner import ProjectWorkspaceProvisioner

from tests.helpers import ControlPlaneHarness


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_gateway_human_request_creates_frame_project_dispatch(self) -> None:
        provisioner = ProjectWorkspaceProvisioner(
            self.harness.store,
            workspace_root=self.harness.tmp_path / "workspaces",
        )
        gateway = ZulipGateway(store=self.harness.store, workspace_provisioner=provisioner)
        event = GatewayEvent(
            message_id="gateway-human-1",
            sender_name="MASTER",
            sender_type="human",
            stream_name="projects",
            topic_name="project/P_gateway_human",
            content="Please frame and start this project.",
        )

        result = gateway.handle_inbound_event(event)

        self.assertEqual(result.status, "dispatch_planned")
        self.assertEqual(result.project_id, "P_gateway_human")
        self.assertIsNotNone(result.task_id)
        self.assertIsNotNone(result.dispatch_plan)
        assert result.dispatch_plan is not None
        self.assertEqual(result.dispatch_plan.target_agent, "agent_smith")
        self.assertEqual(result.dispatch_plan.task_type, "FRAME_PROJECT")

        task = self.harness.store.get_task(result.task_id)
        assert task is not None
        self.assertEqual(task["task_type"], "FRAME_PROJECT")
        self.assertEqual(task["to_agent"], "agent_smith")

        project = self.harness.store.get_project("P_gateway_human")
        scheduling = self.harness.store.get_scheduling_record("P_gateway_human")
        assert project is not None
        assert scheduling is not None
        self.assertEqual(scheduling["eligible_for_scheduling"], 1)
        self.assertIsNone(scheduling["waiting_reason"])
        self.assertIsNotNone(project["workspace_ref"])
        workspace_ref = project["workspace_ref"]
        assert isinstance(workspace_ref, str)
        self.assertTrue((self.harness.tmp_path / "workspaces" / "P_gateway_human").exists())
        self.assertIsNotNone(self.harness.store.get_workspace_state(workspace_ref))
        self.assertIn("task_assignment", result.outbound_message or "")

    def test_gateway_service_treats_real_user_named_master_as_human(self) -> None:
        gateway = ZulipGateway(store=self.harness.store)
        service = GatewayService(gateway=gateway)
        service.bot_emails = {"assistant-bot@localhost.localdomain": "agent_smith"}

        sender_type = service._sender_type("user8@localhost.localdomain", "master")

        self.assertEqual(sender_type, "human")

    def test_gateway_custom_topic_becomes_canonical_feedback_thread(self) -> None:
        provisioner = ProjectWorkspaceProvisioner(
            self.harness.store,
            workspace_root=self.harness.tmp_path / "workspaces",
        )
        gateway = ZulipGateway(store=self.harness.store, workspace_provisioner=provisioner)
        event = GatewayEvent(
            message_id="gateway-human-custom-topic",
            sender_name="operator",
            sender_type="human",
            stream_name="projects",
            topic_name="fibonacci_test",
            content="Build a fibonacci demo in this thread.",
        )

        result = gateway.handle_inbound_event(event)

        self.assertEqual(result.status, "dispatch_planned")
        assert result.project_id is not None
        assert result.dispatch_plan is not None
        self.assertEqual(result.dispatch_plan.reply_stream, "projects")
        self.assertEqual(result.dispatch_plan.reply_topic, "fibonacci_test")
        self.assertEqual(self.harness.store.get_project_feedback_thread(result.project_id), ("projects", "fibonacci_test"))
        self.assertIn("Step Started:", result.outbound_message or "")

    def test_gateway_service_mirrors_visible_dispatch_and_result_to_canonical_thread(self) -> None:
        provisioner = ProjectWorkspaceProvisioner(
            self.harness.store,
            workspace_root=self.harness.tmp_path / "workspaces",
        )
        gateway = ZulipGateway(store=self.harness.store, workspace_provisioner=provisioner)
        event = GatewayEvent(
            message_id="gateway-human-canonical-thread",
            sender_name="operator",
            sender_type="human",
            stream_name="projects",
            topic_name="single-thread-demo",
            content="Start a project and keep feedback here.",
        )
        result = gateway.handle_inbound_event(event)
        assert result.project_id is not None
        assert result.task_id is not None

        service = GatewayService(gateway=gateway)
        service.bots = {
            "agent_smith": SimpleNamespace(),
            "niobe": SimpleNamespace(),
            "architect": SimpleNamespace(),
            "morpheus": SimpleNamespace(),
            "oracle": SimpleNamespace(),
        }
        sent: list[tuple[str, str, str, str]] = []

        def fake_send(sender_agent: str, stream_name: str, topic_name: str, content: str) -> str:
            sent.append((sender_agent, stream_name, topic_name, content))
            return f"msg-{len(sent)}"

        service._send_stream_message = fake_send  # type: ignore[method-assign]

        dispatch_ids = service._mirror_visible_dispatches()
        self.assertEqual(len(dispatch_ids), 1)
        self.assertEqual(sent[0][1], "projects")
        self.assertEqual(sent[0][2], "single-thread-demo")
        self.assertIn("Step Started:", sent[0][3])

        self.harness.store.record_task_attempt(
            task_id=result.task_id,
            project_id=result.project_id,
            agent_id="agent_smith",
            attempt_number=1,
            status="SUCCESS",
            summary="Framed the request into a project charter.",
        )
        self.harness.store.update(
            "tasks",
            {"status": "SUCCESS"},
            where_clause="task_id = ?",
            where_params=[result.task_id],
        )
        self.harness.store.update(
            "projects",
            {
                "next_action_json": {
                    "type": "RETURN_TO_REQUESTER",
                    "target_agent": "niobe",
                }
            },
            where_clause="project_id = ?",
            where_params=[result.project_id],
        )

        result_ids = service._mirror_completed_results()
        self.assertEqual(len(result_ids), 1)
        self.assertEqual(sent[1][1], "projects")
        self.assertEqual(sent[1][2], "single-thread-demo")
        self.assertIn("Step Update:", sent[1][3])
        self.assertIn("Next:", sent[1][3])

    def test_gateway_service_mirrors_morpheus_progress_updates_to_canonical_thread(self) -> None:
        provisioner = ProjectWorkspaceProvisioner(
            self.harness.store,
            workspace_root=self.harness.tmp_path / "workspaces",
        )
        gateway = ZulipGateway(store=self.harness.store, workspace_provisioner=provisioner)
        event = GatewayEvent(
            message_id="gateway-human-morpheus-progress",
            sender_name="operator",
            sender_type="human",
            stream_name="projects",
            topic_name="morpheus-progress-demo",
            content="Start a software project and keep progress here.",
        )
        result = gateway.handle_inbound_event(event)
        assert result.project_id is not None

        now = utc_now()
        parent_task_id = "T_morpheus_parent"
        self.harness.store.upsert(
            "tasks",
            {
                "task_id": parent_task_id,
                "project_id": result.project_id,
                "parent_task_id": None,
                "from_agent": "niobe",
                "to_agent": "morpheus",
                "current_owner_agent": "morpheus",
                "return_to": "niobe",
                "task_type": "ORCHESTRATE_SOFTWARE",
                "title": "Deliver software",
                "goal": "Implement the requested software change.",
                "priority": "MEDIUM",
                "status": "PENDING",
                "context_json": {},
                "expected_output_json": {},
                "decision_bounds_json": {},
                "opened_at": now,
                "updated_at": now,
                "closed_at": None,
            },
            conflict_columns=["task_id"],
        )
        for task_id, to_agent, task_type in (
            ("T_morpheus_plan", "planner", "PLAN_SOFTWARE_TASK"),
            ("T_morpheus_implement", "implementer", "IMPLEMENT_SOFTWARE_TASK"),
            ("T_morpheus_test", "tester", "TEST_SOFTWARE_TASK"),
        ):
            self.harness.store.upsert(
                "tasks",
                {
                    "task_id": task_id,
                    "project_id": result.project_id,
                    "parent_task_id": parent_task_id,
                    "from_agent": "morpheus",
                    "to_agent": to_agent,
                    "current_owner_agent": to_agent,
                    "return_to": "morpheus",
                    "task_type": task_type,
                    "title": task_type,
                    "goal": "Run the next software phase.",
                    "priority": "MEDIUM",
                    "status": "PENDING",
                    "context_json": {},
                    "expected_output_json": {},
                    "decision_bounds_json": {},
                    "opened_at": now,
                    "updated_at": now,
                    "closed_at": None,
                },
                conflict_columns=["task_id"],
            )

        service = GatewayService(gateway=gateway)
        service.bots = {
            "agent_smith": SimpleNamespace(),
            "niobe": SimpleNamespace(),
            "architect": SimpleNamespace(),
            "morpheus": SimpleNamespace(),
            "oracle": SimpleNamespace(),
        }
        sent: list[tuple[str, str, str, str]] = []

        def fake_send(sender_agent: str, stream_name: str, topic_name: str, content: str) -> str:
            sent.append((sender_agent, stream_name, topic_name, content))
            return f"msg-{len(sent)}"

        service._send_stream_message = fake_send  # type: ignore[method-assign]

        message_ids = service._mirror_morpheus_progress_updates()

        self.assertEqual(len(message_ids), 3)
        self.assertEqual([entry[0] for entry in sent], ["morpheus", "morpheus", "morpheus"])
        self.assertEqual([entry[1] for entry in sent], ["projects", "projects", "projects"])
        self.assertEqual([entry[2] for entry in sent], ["morpheus-progress-demo"] * 3)
        self.assertIn("Step Update: [3/5] Software Planning", sent[0][3])
        self.assertIn("Owner: Morpheus", sent[0][3])
        self.assertIn("Morpheus started software planning.", sent[0][3])
        self.assertIn("Step Update: [3/5] Implementation", sent[1][3])
        self.assertIn("Morpheus started implementation.", sent[1][3])
        self.assertIn("Step Update: [3/5] Software Testing", sent[2][3])
        self.assertIn("Morpheus started testing.", sent[2][3])

        second_pass_ids = service._mirror_morpheus_progress_updates()

        self.assertEqual(second_pass_ids, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
