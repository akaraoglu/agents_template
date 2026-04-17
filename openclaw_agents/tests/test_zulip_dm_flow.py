import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class ZulipDMFlowTest(unittest.TestCase):
    def test_neo_answers_open_project_question_from_dm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
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

            result = gateway.process_raw_event(
                {
                    "event_id": "evt-neo-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "neo",
                    "sender_email": "master@example.com",
                    "raw_content": "What active projects are open right now?",
                }
            )

            self.assertEqual(result["status"], "dm_replied")
            sent = gateway.plugin.sent_messages[-1]
            self.assertEqual(sent["target_type"], "dm")
            self.assertIn("Atlas API", sent["content_markdown"])
            self.assertIn("Beacon UI", sent["content_markdown"])


if __name__ == "__main__":
    unittest.main()
