import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway
from openclaw_agents.communication.zulip_gateway_service import GatewayService
from openclaw_agents.communication.zulip_plugin.client import ZulipApiError
from openclaw_agents.communication.zulip_plugin.runtime import ZulipRuntimePlugin


class _FakeZulipClient:
    def __init__(self, email: str) -> None:
        self.email = email
        self.register_count = 0
        self.subscriptions: list[list[str]] = []
        self.sent_private: list[dict[str, object]] = []
        self.sent_stream: list[dict[str, object]] = []
        self._events: list[dict[str, object]] = []
        self.raise_bad_queue_once = False

    def queue_event(self, event: dict[str, object]) -> None:
        self._events.append(event)

    def get_me(self) -> dict[str, object]:
        return {"full_name": self.email.split("@", maxsplit=1)[0], "user_id": 10, "is_bot": True}

    def register_queue(self, *, event_types: list[str] | None = None) -> dict[str, object]:
        self.register_count += 1
        return {"queue_id": f"queue-{self.email}-{self.register_count}", "last_event_id": 0}

    def get_events(
        self,
        queue_id: str,
        last_event_id: int,
        *,
        timeout_seconds: int = 0,
        dont_block: bool = True,
    ) -> dict[str, object]:
        del last_event_id, timeout_seconds, dont_block
        if self.raise_bad_queue_once:
            self.raise_bad_queue_once = False
            raise ZulipApiError("bad event queue", error_code="BAD_EVENT_QUEUE_ID")
        batch = list(self._events)
        self._events.clear()
        last_seen = max((int(event["id"]) for event in batch), default=0)
        return {"queue_id": queue_id, "events": batch, "last_event_id": last_seen}

    def send_private_message(self, recipients: list[str], content: str) -> dict[str, object]:
        self.sent_private.append({"recipients": recipients, "content": content})
        return {"id": 1000 + len(self.sent_private)}

    def send_stream_message(self, stream_name: str, topic_name: str, content: str) -> dict[str, object]:
        self.sent_stream.append({"stream_name": stream_name, "topic_name": topic_name, "content": content})
        return {"id": 2000 + len(self.sent_stream)}

    def edit_message(self, message_id: int | str, content: str) -> dict[str, object]:
        return {"id": int(message_id), "content": content}

    def add_reaction(self, message_id: int | str, emoji_name: str) -> dict[str, object]:
        return {"message_id": int(message_id), "emoji_name": emoji_name}

    def remove_reaction(self, message_id: int | str, emoji_name: str) -> dict[str, object]:
        return {"message_id": int(message_id), "emoji_name": emoji_name}

    def ensure_subscriptions(self, stream_names: list[str]) -> dict[str, object]:
        self.subscriptions.append(list(stream_names))
        return {"subscriptions": stream_names}


class LiveRuntimeTest(unittest.TestCase):
    def _write_config(self, temp_dir: str) -> tuple[Path, Path]:
        root = Path(temp_dir)
        credentials_path = root / "zulip_credentials.txt"
        credentials_path.write_text(
            "\n".join(
                [
                    "[api]",
                    "email=neo-bot@bots.localdomain",
                    "key=neo-key",
                    "site=https://zulip.localnet:3838",
                    "[api]",
                    "email=agentsmith-bot@bots.localdomain",
                    "key=smith-key",
                    "site=https://zulip.localnet:3838",
                    "[api]",
                    "email=niaobe-bot@localhost.localdomain",
                    "key=niaobe-key",
                    "site=https://zulip.localnet:3838",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        config_path = root / "zulip_gateway_config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "version: 2",
                    "zulip_server_url: https://zulip.localnet:3838",
                    "verify_tls: false",
                    "enabled_agents:",
                    "  - neo",
                    "  - agent_smith",
                    "  - niaobe",
                    "bot_identities:",
                    "  neo: neo-bot@bots.localdomain",
                    "  agent_smith: agentsmith-bot@bots.localdomain",
                    "  niaobe: niaobe-bot@localhost.localdomain",
                    f"local_dev_credentials_file: {credentials_path}",
                    "required_subscriptions:",
                    "  neo: [projects]",
                    "  agent_smith: [projects]",
                    "  niaobe: [projects]",
                    "runtime:",
                    "  queue_timeout_seconds: 0",
                    "  batch_size: 20",
                    "  startup_subscriptions: true",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return config_path, credentials_path

    def test_live_runtime_normalizes_dm_and_routes_sender_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path, _credentials_path = self._write_config(temp_dir)
            clients = {
                "neo-bot@bots.localdomain": _FakeZulipClient("neo-bot@bots.localdomain"),
                "agentsmith-bot@bots.localdomain": _FakeZulipClient("agentsmith-bot@bots.localdomain"),
                "niaobe-bot@localhost.localdomain": _FakeZulipClient("niaobe-bot@localhost.localdomain"),
            }

            plugin = ZulipRuntimePlugin.from_config(
                config_path=config_path,
                client_factory=lambda credentials, verify_tls: clients[credentials.email],
            )
            clients["neo-bot@bots.localdomain"].queue_event(
                {
                    "id": 1,
                    "type": "message",
                    "message": {
                        "id": 42,
                        "type": "private",
                        "sender_id": 7,
                        "sender_email": "master@example.com",
                        "display_recipient": [
                            {"email": "master@example.com"},
                            {"email": "neo-bot@bots.localdomain"},
                        ],
                        "content": "<p>What active projects are open right now?</p>",
                    },
                }
            )

            plugin.initialize(ensure_subscriptions=True)
            events = plugin.poll_events()

            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event["recipient_agent"], "neo")
            self.assertEqual(event["conversation_surface"], "dm")
            self.assertEqual(event["event_id"], "zulip-message::42")
            self.assertEqual(event["raw_content"], "What active projects are open right now?")
            self.assertEqual(clients["neo-bot@bots.localdomain"].subscriptions, [["projects"]])

            plugin.send_dm(
                target_email="master@example.com",
                content_markdown="Reply from Neo",
                sender_agent="neo",
            )
            self.assertEqual(len(clients["neo-bot@bots.localdomain"].sent_private), 1)
            self.assertEqual(len(clients["agentsmith-bot@bots.localdomain"].sent_private), 0)

    def test_live_runtime_emits_queue_expiry_for_bad_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path, _credentials_path = self._write_config(temp_dir)
            clients = {
                "neo-bot@bots.localdomain": _FakeZulipClient("neo-bot@bots.localdomain"),
                "agentsmith-bot@bots.localdomain": _FakeZulipClient("agentsmith-bot@bots.localdomain"),
                "niaobe-bot@localhost.localdomain": _FakeZulipClient("niaobe-bot@localhost.localdomain"),
            }
            clients["neo-bot@bots.localdomain"].raise_bad_queue_once = True

            plugin = ZulipRuntimePlugin.from_config(
                config_path=config_path,
                client_factory=lambda credentials, verify_tls: clients[credentials.email],
            )
            plugin.initialize()
            events = plugin.poll_events()

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["source_type"], "queue_expired")
            self.assertEqual(events[0]["queue_owner_agent"], "neo")

            new_queue_id = plugin.recreate_queue(queue_owner_agent="neo")
            self.assertTrue(new_queue_id.startswith("queue-neo-bot@bots.localdomain-"))
            self.assertEqual(clients["neo-bot@bots.localdomain"].register_count, 2)

    def test_gateway_service_processes_live_dm_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path, _credentials_path = self._write_config(temp_dir)
            clients = {
                "neo-bot@bots.localdomain": _FakeZulipClient("neo-bot@bots.localdomain"),
                "agentsmith-bot@bots.localdomain": _FakeZulipClient("agentsmith-bot@bots.localdomain"),
                "niaobe-bot@localhost.localdomain": _FakeZulipClient("niaobe-bot@localhost.localdomain"),
            }
            clients["neo-bot@bots.localdomain"].queue_event(
                {
                    "id": 1,
                    "type": "message",
                    "message": {
                        "id": 55,
                        "type": "private",
                        "sender_id": 7,
                        "sender_email": "master@example.com",
                        "display_recipient": [
                            {"email": "master@example.com"},
                            {"email": "neo-bot@bots.localdomain"},
                        ],
                        "content": "<p>What active projects are open right now?</p>",
                    },
                }
            )

            plugin = ZulipRuntimePlugin.from_config(
                config_path=config_path,
                client_factory=lambda credentials, verify_tls: clients[credentials.email],
            )
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime", plugin=plugin)
            gateway.project_provisioning.create_project_surface(
                name="Atlas API",
                summary="API modernization project.",
                requested_by="master@example.com",
            )

            service = GatewayService(
                config_path=config_path,
                plugin=plugin,
                gateway=gateway,
                ensure_subscriptions_on_start=True,
            )
            result = service.process_once()

            self.assertEqual(result["events_polled"], 1)
            self.assertFalse(result["errors"])
            self.assertEqual(len(clients["neo-bot@bots.localdomain"].sent_private), 1)
            reply = clients["neo-bot@bots.localdomain"].sent_private[0]["content"]
            self.assertIn("Atlas API", str(reply))


if __name__ == "__main__":
    unittest.main()
