import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class ConfirmationGateTest(unittest.TestCase):
    def test_project_mutation_is_blocked_until_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")

            gateway.process_raw_event(
                {
                    "event_id": "evt-gate-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Create project Edge Sync for near-real-time replication.",
                }
            )
            self.assertEqual(gateway.project_registry.list_projects(), [])

            gateway.process_raw_event(
                {
                    "event_id": "evt-gate-2",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "maybe later",
                }
            )
            self.assertEqual(gateway.project_registry.list_projects(), [])

            pending = gateway.state_store.list_pending_approvals(
                requester_email="master@example.com", owner_agent="agent_smith"
            )
            self.assertEqual(len(pending), 1)
            approval_id = pending[0]["approval_id"]

            gateway.process_raw_event(
                {
                    "event_id": "evt-gate-3",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": f"reject {approval_id}",
                }
            )

            self.assertEqual(gateway.project_registry.list_projects(), [])
            self.assertEqual(gateway.state_store.get_approval(approval_id)["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
