from __future__ import annotations

import unittest

from openclaw_agents.communication.zulip_gateway import GatewayEvent, ZulipGateway
from openclaw_agents.communication.zulip_gateway_service import GatewayService
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
