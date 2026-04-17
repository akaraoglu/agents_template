import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class ProjectionEventModelTest(unittest.TestCase):
    def test_confirmed_project_change_persists_projection_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")

            gateway.process_raw_event(
                {
                    "event_id": "evt-proj-1",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": "Create project Atlas Platform to unify service APIs.",
                }
            )
            approval = gateway.state_store.list_pending_approvals(
                requester_email="master@example.com",
                owner_agent="agent_smith",
            )[0]
            gateway.process_raw_event(
                {
                    "event_id": "evt-proj-2",
                    "source_type": "dm_message",
                    "conversation_surface": "dm",
                    "recipient_agent": "agent_smith",
                    "sender_email": "master@example.com",
                    "raw_content": f"confirm {approval['approval_id']}",
                }
            )

            project = gateway.project_registry.list_projects()[0]
            events = gateway.projection_event_service.list_events(project["id"])
            event_types = {row["event_type"] for row in events}

            self.assertIn("project_kickoff", event_types)
            self.assertIn("execution_handoff_created", event_types)

            stream_posts = [row for row in gateway.plugin.sent_messages if row["target_type"] == "stream"]
            self.assertTrue(any(row["message_kind"] == "projection_event" for row in stream_posts))
            self.assertTrue(any(row["message_kind"] == "execution_handoff" for row in stream_posts))

    def test_projection_rendering_varies_by_event_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
            project = gateway.project_provisioning.create_project_surface(
                name="Atlas Runtime",
                summary="Projection rendering.",
                requested_by="master@example.com",
            )
            blocked = gateway.projection_event_service.record_event(
                event_type="execution_blocked",
                project_id=project["id"],
                summary="Niaobe hit a deployment blocker.",
                payload={"blocker": "Missing deployment key", "escalation_target": "agent_smith"},
                actor_agent="niaobe",
            )
            verified = gateway.projection_event_service.record_event(
                event_type="verification_reported",
                project_id=project["id"],
                summary="Verification completed in staging.",
                payload={"verification_report": "Smoke tests passed in staging."},
                actor_agent="niaobe",
            )

            gateway.projection_helpers.post_projection_event(blocked, sender_agent="niaobe")
            gateway.projection_helpers.post_projection_event(verified, sender_agent="niaobe")

            content = "\n\n".join(row["content_markdown"] for row in gateway.plugin.sent_messages)
            self.assertIn("## Execution Blocked", content)
            self.assertIn("Missing deployment key", content)
            self.assertIn("## Verification Reported", content)
            self.assertIn("Smoke tests passed in staging.", content)


if __name__ == "__main__":
    unittest.main()
