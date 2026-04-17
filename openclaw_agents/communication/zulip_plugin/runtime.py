"""Foundation Zulip runtime with in-memory and live transport modes."""

from __future__ import annotations

import html
import os
import re
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from openclaw_agents.runtime_paths import RuntimePaths

from .client import ZulipApiClient, ZulipApiError, ZulipCredentials, load_credentials_bundle


_TAG_RE = re.compile(r"<[^>]+>")
_CODE_BLOCK_RE = re.compile(
    r"<pre(?P<pre_attrs>[^>]*)>\s*<code(?P<code_attrs>[^>]*)>(?P<body>.*?)</code>\s*</pre>",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"<code(?P<attrs>[^>]*)>(?P<body>.*?)</code>", re.IGNORECASE | re.DOTALL)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _rendered_content_to_text(content: str) -> str:
    if "<" not in content or ">" not in content:
        return html.unescape(content).strip()

    placeholders: dict[str, str] = {}

    def replace_code_block(match: re.Match[str]) -> str:
        attrs = f"{match.group('pre_attrs')} {match.group('code_attrs')}"
        body = html.unescape(match.group("body")).strip("\n")
        lang_match = re.search(r'(?:language-|data-code-language=")([a-zA-Z0-9_+-]+)', attrs)
        lang = lang_match.group(1) if lang_match else ""
        fenced = f"```{lang}\n{body}\n```" if lang else f"```\n{body}\n```"
        key = f"__CODE_BLOCK_{len(placeholders)}__"
        placeholders[key] = fenced
        return f"\n{key}\n"

    text = _CODE_BLOCK_RE.sub(replace_code_block, content)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = _INLINE_CODE_RE.sub(lambda match: f"`{html.unescape(match.group('body'))}`", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    for key, value in placeholders.items():
        text = text.replace(key, value)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass(slots=True)
class PublishResult:
    message_id: int
    target_type: str
    sent_at: str


@dataclass(slots=True)
class _ManagedBot:
    agent_id: str
    email: str
    subscriptions: list[str]
    client: ZulipApiClient
    queue_id: str | None = None
    last_event_id: int = -1
    connected: bool = False
    last_error: str | None = None


class ZulipRuntimePlugin:
    """Shared Zulip transport/runtime used by the foundation gateway."""

    def __init__(
        self,
        *,
        bot_sessions: dict[str, _ManagedBot] | None = None,
        poll_timeout_seconds: int = 0,
        batch_size: int = 50,
        verify_tls: bool = True,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._queue: deque[dict[str, Any]] = deque()
        self._sent_messages: list[dict[str, Any]] = []
        self._reactions: dict[int, list[str]] = {}
        self._next_message_id = 1
        self._queue_counter = 1
        self.queue_id = f"queue-{self._queue_counter}"
        self._connected = True
        self._bot_sessions = bot_sessions or {}
        self._bot_emails = {session.email: agent_id for agent_id, session in self._bot_sessions.items()}
        self._live_mode = bool(self._bot_sessions)
        self.poll_timeout_seconds = poll_timeout_seconds
        self.batch_size = batch_size
        self.verify_tls = verify_tls
        self.config = config or {}

    @classmethod
    def from_config(
        cls,
        *,
        config_path: str | Path | None = None,
        credentials_file: str | Path | None = None,
        enabled_agents: list[str] | None = None,
        verify_tls: bool | None = None,
        client_factory: Callable[[ZulipCredentials, bool], ZulipApiClient] | None = None,
    ) -> ZulipRuntimePlugin:
        package_root = Path(__file__).resolve().parents[2]
        repo_root = package_root.parent
        runtime_paths = RuntimePaths.from_root()
        resolved_config_path = Path(config_path or (package_root / "communication" / "zulip_gateway_config.yaml"))
        raw_config = yaml.safe_load(resolved_config_path.read_text(encoding="utf-8")) or {}

        selected_agents = enabled_agents or raw_config.get("enabled_agents") or list(
            (raw_config.get("bot_identities") or {}).keys()
        )
        if not selected_agents:
            raise ValueError("zulip gateway config does not define any enabled agents")

        def resolve_path(value: str | Path) -> Path:
            candidate = Path(value)
            if candidate.is_absolute():
                return candidate
            for base in (runtime_paths.config_root, resolved_config_path.parent, package_root, repo_root):
                resolved = (base / candidate).resolve()
                if resolved.exists():
                    return resolved
            return (runtime_paths.config_root / candidate).resolve()

        credentials_path = None
        if credentials_file:
            credentials_path = resolve_path(credentials_file)
        else:
            configured = raw_config.get("local_dev_credentials_file")
            if configured:
                credentials_path = resolve_path(configured)

        bundled_credentials = load_credentials_bundle(credentials_path) if credentials_path and credentials_path.exists() else {}
        bot_identities = raw_config.get("bot_identities") or {}
        secret_refs = raw_config.get("bot_credentials_secret_refs") or {}
        server_url = str(raw_config.get("zulip_server_url", "")).rstrip("/")
        tls_enabled = raw_config.get("verify_tls", True) if verify_tls is None else verify_tls
        factory = client_factory or (lambda credentials, tls: ZulipApiClient(credentials, verify_tls=tls))

        sessions: dict[str, _ManagedBot] = {}
        for agent_id in selected_agents:
            email = bot_identities.get(agent_id)
            if not email:
                raise ValueError(f"missing bot identity for agent '{agent_id}'")

            credentials = bundled_credentials.get(email)
            secret_ref = str(secret_refs.get(agent_id, ""))
            api_key = None
            if secret_ref.startswith("env:"):
                env_key = secret_ref.split(":", maxsplit=1)[1]
                api_key = os.environ.get(env_key)
            if not api_key and credentials:
                api_key = credentials.api_key
            if not api_key:
                raise ValueError(f"missing Zulip API key for '{agent_id}'")

            site = credentials.site if credentials and credentials.site else server_url
            if not site:
                raise ValueError(f"missing Zulip site for '{agent_id}'")

            account = ZulipCredentials(site=site.rstrip("/"), email=email, api_key=api_key)
            subscriptions = list((raw_config.get("required_subscriptions") or {}).get(agent_id, []))
            sessions[agent_id] = _ManagedBot(
                agent_id=agent_id,
                email=email,
                subscriptions=subscriptions,
                client=factory(account, bool(tls_enabled)),
            )

        runtime_config = raw_config.get("runtime") or {}
        plugin = cls(
            bot_sessions=sessions,
            poll_timeout_seconds=int(runtime_config.get("queue_timeout_seconds", 0)),
            batch_size=int(runtime_config.get("batch_size", 50)),
            verify_tls=bool(tls_enabled),
            config=raw_config,
        )
        return plugin

    @property
    def sent_messages(self) -> list[dict[str, Any]]:
        return deepcopy(self._sent_messages)

    @property
    def live_mode(self) -> bool:
        return self._live_mode

    def initialize(self, *, ensure_subscriptions: bool = False) -> None:
        if not self._live_mode:
            return
        if ensure_subscriptions:
            self.ensure_subscriptions({})
        for agent_id in self._bot_sessions:
            if self._bot_sessions[agent_id].queue_id is None:
                self._register_queue(agent_id)

    def identify_bots(self) -> dict[str, dict[str, Any]]:
        if not self._live_mode:
            return {}
        identities: dict[str, dict[str, Any]] = {}
        for agent_id, session in self._bot_sessions.items():
            payload = session.client.get_me()
            identities[agent_id] = {
                "email": session.email,
                "full_name": payload.get("full_name"),
                "user_id": payload.get("user_id"),
                "is_bot": payload.get("is_bot"),
                "queue_id": session.queue_id,
            }
        return identities

    def normalize_inbound(self, raw_event: dict[str, Any]) -> dict[str, Any]:
        if self._live_mode and raw_event.get("type") == "message":
            normalized = self._normalize_live_event(
                raw_event,
                recipient_agent=str(raw_event.get("recipient_agent", "")),
                queue_id=raw_event.get("queue_id"),
            )
            if normalized:
                return normalized

        source_type = raw_event.get("source_type", "dm_message")
        conversation_surface = raw_event.get(
            "conversation_surface", "dm" if source_type == "dm_message" else "stream_topic"
        )
        message_id = raw_event.get("zulip_message_id") or f"raw-{raw_event.get('event_id', '0')}"
        return {
            "event_id": str(raw_event.get("event_id", message_id)),
            "source_type": source_type,
            "zulip_message_id": message_id,
            "sender_id": raw_event.get("sender_id", 0),
            "sender_email": raw_event.get("sender_email", ""),
            "recipient_agent": raw_event.get("recipient_agent", ""),
            "conversation_surface": conversation_surface,
            "stream_name": raw_event.get("stream_name"),
            "topic_name": raw_event.get("topic_name"),
            "dm_participants": raw_event.get("dm_participants", []),
            "received_at": raw_event.get("received_at", _utc_now()),
            "raw_content": raw_event.get("raw_content", ""),
            "attachments": raw_event.get("attachments", []),
            "queue_id": raw_event.get("queue_id", self.queue_id),
        }

    def enqueue_inbound(self, raw_event: dict[str, Any]) -> None:
        self._queue.append(self.normalize_inbound(raw_event))

    def poll_events(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._live_mode:
            events: list[dict[str, Any]] = []
            while self._queue and len(events) < limit:
                events.append(self._queue.popleft())
            return events

        self.initialize()
        events: list[dict[str, Any]] = []
        for agent_id, session in self._bot_sessions.items():
            if session.queue_id is None:
                self._register_queue(agent_id)
            try:
                payload = session.client.get_events(
                    session.queue_id or "",
                    session.last_event_id,
                    timeout_seconds=self.poll_timeout_seconds,
                    dont_block=True,
                )
                session.connected = True
                session.last_error = None
                self._connected = True
            except ZulipApiError as exc:
                session.connected = False
                session.last_error = str(exc)
                self._connected = False
                if exc.error_code == "BAD_EVENT_QUEUE_ID":
                    events.append(
                        {
                            "event_id": f"queue-expired::{agent_id}::{session.queue_id or 'none'}",
                            "source_type": "queue_expired",
                            "conversation_surface": "control",
                            "queue_id": session.queue_id,
                            "queue_owner_agent": agent_id,
                            "raw_content": str(exc),
                        }
                    )
                    if len(events) >= limit:
                        return events
                    continue
                raise

            session.last_event_id = int(payload.get("last_event_id", session.last_event_id))
            self.queue_id = session.queue_id or self.queue_id
            for raw_event in payload.get("events", []):
                normalized = self._normalize_live_event(
                    raw_event,
                    recipient_agent=agent_id,
                    queue_id=session.queue_id,
                )
                if not normalized:
                    continue
                events.append(normalized)
                if len(events) >= limit:
                    return events
        return events

    def _normalize_live_event(
        self,
        raw_event: dict[str, Any],
        *,
        recipient_agent: str,
        queue_id: str | None,
    ) -> dict[str, Any] | None:
        if raw_event.get("type") != "message":
            return None
        message = raw_event.get("message") or {}
        message_id = message.get("id")
        if message_id is None:
            return None

        sender_email = str(message.get("sender_email", ""))
        if sender_email in self._bot_emails:
            return None

        message_type = message.get("type")
        if message_type == "private":
            conversation_surface = "dm"
            source_type = "dm_message"
            stream_name = None
            topic_name = None
            dm_participants = self._dm_participants(message, recipient_agent)
        else:
            conversation_surface = "stream_topic"
            source_type = "stream_message"
            stream_name = message.get("display_recipient")
            topic_name = message.get("topic") or message.get("subject")
            dm_participants = []

        return {
            "event_id": f"zulip-message::{message_id}",
            "source_type": source_type,
            "zulip_message_id": message_id,
            "sender_id": message.get("sender_id", 0),
            "sender_email": sender_email,
            "recipient_agent": recipient_agent,
            "conversation_surface": conversation_surface,
            "stream_name": stream_name,
            "topic_name": topic_name,
            "dm_participants": dm_participants,
            "received_at": _utc_now(),
            "raw_content": _rendered_content_to_text(str(message.get("content", ""))),
            "attachments": [],
            "queue_id": queue_id,
        }

    def _dm_participants(self, message: dict[str, Any], recipient_agent: str) -> list[str]:
        participants: list[str] = []
        display_recipient = message.get("display_recipient")
        recipient_email = self._bot_sessions.get(recipient_agent).email if recipient_agent in self._bot_sessions else ""
        if isinstance(display_recipient, list):
            for row in display_recipient:
                email = row.get("email")
                if email and email != recipient_email:
                    participants.append(email)
        sender_email = message.get("sender_email")
        if sender_email and sender_email not in participants and sender_email != recipient_email:
            participants.append(sender_email)
        return participants

    def _publish(self, payload: dict[str, Any]) -> PublishResult:
        message_id = self._next_message_id
        self._next_message_id += 1
        row = {"id": message_id, "sent_at": _utc_now(), **payload}
        self._sent_messages.append(row)
        return PublishResult(message_id=message_id, target_type=payload["target_type"], sent_at=row["sent_at"])

    def _record_live_publish(self, payload: dict[str, Any], result_payload: dict[str, Any]) -> PublishResult:
        message_id = int(result_payload.get("id", 0))
        if message_id <= 0:
            raise ZulipApiError("Zulip send succeeded without a message id", payload=result_payload)
        row = {"id": message_id, "sent_at": _utc_now(), **payload}
        self._sent_messages.append(row)
        return PublishResult(message_id=message_id, target_type=payload["target_type"], sent_at=row["sent_at"])

    def _resolve_sender_agent(self, sender_agent: str | None) -> str:
        if sender_agent and sender_agent in self._bot_sessions:
            return sender_agent
        if self._bot_sessions:
            return next(iter(self._bot_sessions))
        return sender_agent or "gateway"

    def send_dm(
        self,
        target_email: str,
        content_markdown: str,
        project_id: str | None = None,
        task_id: str | None = None,
        message_kind: str = "consultation_reply",
        sender_agent: str | None = None,
    ) -> PublishResult:
        payload = {
            "target_type": "dm",
            "target_email": target_email,
            "content_markdown": content_markdown,
            "project_id": project_id,
            "task_id": task_id,
            "message_kind": message_kind,
            "sender_agent": sender_agent,
        }
        if not self._live_mode:
            return self._publish(payload)

        resolved_sender = self._resolve_sender_agent(sender_agent)
        result = self._bot_sessions[resolved_sender].client.send_private_message([target_email], content_markdown)
        payload["sender_agent"] = resolved_sender
        return self._record_live_publish(payload, result)

    def send_stream_message(
        self,
        stream_name: str,
        topic_name: str,
        content_markdown: str,
        project_id: str | None = None,
        task_id: str | None = None,
        message_kind: str = "projection_event",
        sender_agent: str | None = None,
    ) -> PublishResult:
        payload = {
            "target_type": "stream",
            "stream_name": stream_name,
            "topic_name": topic_name,
            "content_markdown": content_markdown,
            "project_id": project_id,
            "task_id": task_id,
            "message_kind": message_kind,
            "sender_agent": sender_agent,
        }
        if not self._live_mode:
            return self._publish(payload)

        resolved_sender = self._resolve_sender_agent(sender_agent)
        result = self._bot_sessions[resolved_sender].client.send_stream_message(
            stream_name, topic_name, content_markdown
        )
        payload["sender_agent"] = resolved_sender
        return self._record_live_publish(payload, result)

    def reply_in_topic(
        self,
        stream_name: str,
        topic_name: str,
        content_markdown: str,
        project_id: str | None = None,
        task_id: str | None = None,
        message_kind: str = "status_update",
        sender_agent: str | None = None,
    ) -> PublishResult:
        return self.send_stream_message(
            stream_name=stream_name,
            topic_name=topic_name,
            content_markdown=content_markdown,
            project_id=project_id,
            task_id=task_id,
            message_kind=message_kind,
            sender_agent=sender_agent,
        )

    def edit_message(self, message_id: int, new_content_markdown: str, sender_agent: str | None = None) -> bool:
        if not self._live_mode:
            for row in self._sent_messages:
                if row["id"] == message_id:
                    row["content_markdown"] = new_content_markdown
                    row["edited_at"] = _utc_now()
                    return True
            return False

        resolved_sender = self._resolve_sender_agent(sender_agent)
        self._bot_sessions[resolved_sender].client.edit_message(message_id, new_content_markdown)
        for row in self._sent_messages:
            if row["id"] == message_id:
                row["content_markdown"] = new_content_markdown
                row["edited_at"] = _utc_now()
        return True

    def upload_file(self, local_path: str) -> dict[str, str]:
        return {"local_path": local_path, "url": f"zulip://upload/{Path(local_path).name}"}

    def add_reaction(self, message_id: int, emoji_name: str, sender_agent: str | None = None) -> None:
        if not self._live_mode:
            self._reactions.setdefault(message_id, []).append(emoji_name)
            return
        resolved_sender = self._resolve_sender_agent(sender_agent)
        self._bot_sessions[resolved_sender].client.add_reaction(message_id, emoji_name)

    def remove_reaction(self, message_id: int, emoji_name: str, sender_agent: str | None = None) -> None:
        if not self._live_mode:
            if message_id not in self._reactions:
                return
            self._reactions[message_id] = [value for value in self._reactions[message_id] if value != emoji_name]
            return
        resolved_sender = self._resolve_sender_agent(sender_agent)
        self._bot_sessions[resolved_sender].client.remove_reaction(message_id, emoji_name)

    def ensure_subscriptions(self, plan: dict[str, list[str]] | None = None) -> dict[str, Any]:
        requested = plan or {
            agent_id: list(session.subscriptions) for agent_id, session in self._bot_sessions.items()
        }
        if not self._live_mode:
            return {"queue_id": self.queue_id, "subscriptions": requested, "applied": True}

        applied: dict[str, list[str]] = {}
        for agent_id, streams in requested.items():
            if agent_id not in self._bot_sessions or not streams:
                continue
            self._bot_sessions[agent_id].client.ensure_subscriptions(streams)
            applied[agent_id] = list(streams)
        return {"queue_id": self.queue_id, "subscriptions": applied, "applied": True}

    def expire_queue(self, queue_owner_agent: str | None = None) -> dict[str, Any]:
        if self._live_mode and queue_owner_agent in self._bot_sessions:
            session = self._bot_sessions[queue_owner_agent]
            session.connected = False
            return {
                "event_id": f"queue-expired::{queue_owner_agent}::{session.queue_id or 'none'}",
                "source_type": "queue_expired",
                "conversation_surface": "control",
                "queue_id": session.queue_id,
                "queue_owner_agent": queue_owner_agent,
                "raw_content": "Queue expired",
            }

        self._connected = False
        return {
            "event_id": f"{self.queue_id}-expired",
            "source_type": "queue_expired",
            "conversation_surface": "control",
            "queue_id": self.queue_id,
            "raw_content": "Queue expired",
        }

    def recreate_queue(self, queue_owner_agent: str | None = None) -> str:
        if self._live_mode:
            agent_id = queue_owner_agent or next(iter(self._bot_sessions))
            self._register_queue(agent_id)
            return self._bot_sessions[agent_id].queue_id or ""

        self._queue_counter += 1
        self.queue_id = f"queue-{self._queue_counter}"
        self._connected = True
        return self.queue_id

    def _register_queue(self, agent_id: str) -> None:
        session = self._bot_sessions[agent_id]
        payload = session.client.register_queue(event_types=["message"])
        session.queue_id = str(payload["queue_id"])
        session.last_event_id = int(payload["last_event_id"])
        session.connected = True
        session.last_error = None
        self.queue_id = session.queue_id
        self._connected = True

    def health(self) -> dict[str, Any]:
        if not self._live_mode:
            return {
                "mode": "memory",
                "queue_id": self.queue_id,
                "connected": self._connected,
                "pending_events": len(self._queue),
                "sent_messages": len(self._sent_messages),
            }

        return {
            "mode": "live",
            "connected": any(session.connected for session in self._bot_sessions.values()),
            "queue_id": self.queue_id,
            "pending_events": None,
            "sent_messages": len(self._sent_messages),
            "bots": {
                agent_id: {
                    "email": session.email,
                    "queue_id": session.queue_id,
                    "last_event_id": session.last_event_id,
                    "connected": session.connected,
                    "subscriptions": list(session.subscriptions),
                    "last_error": session.last_error,
                }
                for agent_id, session in self._bot_sessions.items()
            },
        }
