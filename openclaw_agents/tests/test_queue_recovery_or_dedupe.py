import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class QueueRecoveryOrDedupeTest(unittest.TestCase):
    def test_duplicate_events_dropped_and_queue_recovery_works(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")

            event = {
                "event_id": "evt-dup-1",
                "source_type": "dm_message",
                "conversation_surface": "dm",
                "recipient_agent": "neo",
                "sender_email": "master@example.com",
                "raw_content": "Any active projects?",
            }

            first = gateway.process_raw_event(event)
            second = gateway.process_raw_event(event)

            self.assertEqual(first["status"], "dm_replied")
            self.assertEqual(second["status"], "duplicate_dropped")
            self.assertEqual(len(gateway.plugin.sent_messages), 1)

            expired = gateway.plugin.expire_queue()
            recovery = gateway.process_raw_event(
                {
                    **expired,
                    "event_id": "evt-queue-expired",
                    "recipient_agent": "agent_smith",
                    "sender_email": "ops@example.com",
                }
            )
            self.assertEqual(recovery["status"], "queue_recovered")
            checkpoint = gateway.dedupe_store.get_checkpoint()
            self.assertEqual(checkpoint["queue_id"], recovery["new_queue_id"])
            self.assertIsNone(checkpoint["last_event_id"])


if __name__ == "__main__":
    unittest.main()
