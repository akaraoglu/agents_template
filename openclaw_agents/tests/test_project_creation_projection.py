import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class ProjectCreationProjectionTest(unittest.TestCase):
    def test_agentsmith_creates_project_surface_and_projects_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")

            gateway.process_raw_event(
                {
                    "event_id": "evt-create-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Create project Atlas Platform to unify service APIs.",
                }
            )
            pending = gateway.state_store.list_pending_approvals(
                requester_email="master@example.com", owner_agent="agent_smith"
            )
            self.assertEqual(len(pending), 1)
            approval_id = pending[0]["approval_id"]

            gateway.process_raw_event(
                {
                    "event_id": "evt-create-2",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": f"confirm {approval_id}",
                }
            )

            projects = gateway.project_registry.list_projects()
            self.assertEqual(len(projects), 1)
            project = projects[0]
            self.assertEqual(project["name"], "Atlas Platform")
            self.assertEqual(project["canonical_topic"], f"project/{project['id']}")

            workspace = Path(project["workspace_path"])
            self.assertTrue((workspace / "PROJECT.md").exists())
            self.assertTrue((workspace / "management" / "STATUS.md").exists())

            stream_posts = [row for row in gateway.plugin.sent_messages if row["target_type"] == "stream"]
            self.assertTrue(any(row["message_kind"] == "projection_event" for row in stream_posts))
            self.assertTrue(any(row["topic_name"] == project["canonical_topic"] for row in stream_posts))


if __name__ == "__main__":
    unittest.main()
