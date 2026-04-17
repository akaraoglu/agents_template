import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class ProjectionAndOpsTest(unittest.TestCase):
    def test_projection_rendering_is_event_specific(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
            project = gateway.project_provisioning.create_project_surface(
                name="Beacon QA",
                summary="Verification-heavy project.",
                requested_by="master@example.com",
            )
            event = gateway.projection_event_service.record_event(
                event_type="verification_reported",
                project_id=project["id"],
                summary="Niaobe reported verification results for Beacon QA.",
                payload={"report_summary": "Smoke tests passed."},
                actor_agent="niaobe",
            )

            gateway.projection_helpers.post_projection_event(event, sender_agent="niaobe")

            message = gateway.plugin.sent_messages[-1]["content_markdown"]
            self.assertIn("**Verification reported**", message)
            self.assertIn("Smoke tests passed.", message)

    def test_ops_snapshot_includes_memory_execution_and_audit_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
            project = gateway.project_provisioning.create_project_surface(
                name="Ops Atlas",
                summary="Diagnostics project.",
                requested_by="master@example.com",
            )
            gateway.conversation_memory.append_message(
                "dm::neo::master@example.com",
                role="human",
                sender="master@example.com",
                content="hello",
            )
            gateway.working_memory.put_state("neo", "dm::neo::master@example.com", {"draft": "x"})
            gateway.command_runner.run("echo ops", actor_agent="neo", project_id=project["id"])

            snapshot = gateway.ops_diagnostics.diagnostics_snapshot()

            self.assertIn("conversation_memory", snapshot)
            self.assertIn("working_memory", snapshot)
            self.assertIn("internal_runs", snapshot)
            self.assertIn("audit_tail", snapshot)
            self.assertGreaterEqual(snapshot["conversation_memory"]["messages"], 1)
            self.assertGreaterEqual(snapshot["working_memory"]["scopes"], 1)
            self.assertGreaterEqual(snapshot["audit_entries"], 1)
