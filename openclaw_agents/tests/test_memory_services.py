import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openclaw_agents.services.conversation_memory import ConversationMemoryService
from openclaw_agents.services.working_memory import WorkingMemoryService


class MemoryServicesTest(unittest.TestCase):
    def test_conversation_memory_is_session_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConversationMemoryService(path=Path(temp_dir) / "conversation.json")
            service.append_message("dm::neo::master@example.com", role="human", sender="master", content="hello")
            service.append_message("dm::neo::master@example.com", role="agent", sender="neo", content="hi")
            service.append_message("dm::smith::master@example.com", role="human", sender="master", content="create")

            neo_session = service.recent_messages("dm::neo::master@example.com")
            smith_session = service.recent_messages("dm::smith::master@example.com")

            self.assertEqual(len(neo_session), 2)
            self.assertEqual(len(smith_session), 1)
            self.assertEqual(neo_session[0]["content"], "hello")

    def test_working_memory_is_agent_and_scope_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WorkingMemoryService(path=Path(temp_dir) / "working.json")
            service.put_state("neo", "dm::neo::master@example.com", {"draft": "alpha"})
            service.put_state("agent_smith", "dm::agent_smith::master@example.com", {"draft": "beta"})

            self.assertEqual(service.get_state("neo", "dm::neo::master@example.com")["draft"], "alpha")
            self.assertEqual(
                service.get_state("agent_smith", "dm::agent_smith::master@example.com")["draft"], "beta"
            )
            self.assertEqual(service.get_state("niaobe", "dm::niaobe::master@example.com"), {})

    def test_conversation_memory_prunes_expired_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConversationMemoryService(
                path=Path(temp_dir) / "conversation.json",
                retention_seconds=60,
            )
            old_ts = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
            service.append_message(
                "topic::projects::project/atlas",
                role="human",
                sender="master",
                content="stale",
                created_at=old_ts,
            )
            service.append_message(
                "topic::projects::project/atlas",
                role="agent",
                sender="neo",
                content="fresh",
            )

            service.prune()
            messages = service.recent_messages("topic::projects::project/atlas", limit=10)

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["content"], "fresh")

    def test_working_memory_prunes_expired_scope_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WorkingMemoryService(
                path=Path(temp_dir) / "working.json",
                retention_seconds=60,
            )
            old_ts = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
            service.put_state("neo", "dm::neo::old", {"draft": "old"}, updated_at=old_ts)
            service.put_state("neo", "dm::neo::fresh", {"draft": "fresh"})

            service.prune()

            self.assertEqual(service.get_state("neo", "dm::neo::old"), {})
            self.assertEqual(service.get_state("neo", "dm::neo::fresh")["draft"], "fresh")


if __name__ == "__main__":
    unittest.main()
