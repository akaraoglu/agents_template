import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class ExecutionHandoffCreationTest(unittest.TestCase):
    def test_execution_handoff_packet_is_persisted_outside_zulip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")

            gateway.process_raw_event(
                {
                    "event_id": "evt-handoff-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Create project Pulse API for request orchestration.",
                }
            )
            approval_id = gateway.state_store.list_pending_approvals(
                requester_email="master@example.com", owner_agent="agent_smith"
            )[0]["approval_id"]
            gateway.process_raw_event(
                {
                    "event_id": "evt-handoff-2",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": f"confirm {approval_id}",
                }
            )

            project = gateway.project_registry.list_projects()[0]
            handoffs = gateway.state_store.list_handoffs(project_id=project["id"])
            self.assertEqual(len(handoffs), 1)
            handoff = handoffs[0]
            self.assertEqual(handoff["to_agent"], "niaobe")
            self.assertEqual(handoff["project_id"], project["id"])
            self.assertTrue(Path(handoff["artifact_ref"]["path"]).exists())
            self.assertEqual(project["handoff_status"], "PENDING")

            stream_posts = [row for row in gateway.plugin.sent_messages if row["target_type"] == "stream"]
            self.assertTrue(any(row["message_kind"] == "execution_handoff" for row in stream_posts))

    def test_project_handoff_status_tracks_authoritative_handoff_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")

            gateway.process_raw_event(
                {
                    "event_id": "evt-handoff-sync-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Create project Sync Check for handoff status validation.",
                }
            )
            approval_id = gateway.state_store.list_pending_approvals(
                requester_email="master@example.com", owner_agent="agent_smith"
            )[0]["approval_id"]
            gateway.process_raw_event(
                {
                    "event_id": "evt-handoff-sync-2",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": f"confirm {approval_id}",
                }
            )

            project = gateway.project_registry.list_projects()[0]
            handoff = gateway.state_store.list_handoffs(project_id=project["id"])[0]
            gateway.execution_state.start_execution(handoff["handoff_id"], actor_agent="niaobe")

            updated = gateway.state_store.get_project(project["id"])
            assert updated is not None
            self.assertEqual(updated["handoff_status"], "IN_PROGRESS")


if __name__ == "__main__":
    unittest.main()
