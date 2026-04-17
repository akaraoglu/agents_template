import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class ProjectContextResolutionTest(unittest.TestCase):
    def test_ambiguous_project_context_triggers_follow_up_question(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
            gateway.project_provisioning.create_project_surface(
                name="Alpha API", summary="First alpha project.", requested_by="master@example.com"
            )
            gateway.project_provisioning.create_project_surface(
                name="Alpha Mobile", summary="Second alpha project.", requested_by="master@example.com"
            )

            result = gateway.process_raw_event(
                {
                    "event_id": "evt-context-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Update project Alpha with revised milestones.",
                }
            )

            self.assertEqual(result["status"], "dm_replied")
            sent = gateway.plugin.sent_messages[-1]["content_markdown"].lower()
            self.assertIn("multiple matching projects", sent)
            self.assertIn("alpha api", sent)
            self.assertIn("alpha mobile", sent)


if __name__ == "__main__":
    unittest.main()
