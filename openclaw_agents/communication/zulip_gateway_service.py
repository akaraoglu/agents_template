"""Long-running Zulip gateway service built on the control-plane gateway."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from openclaw_agents.communication.zulip_client import (
    ZulipApiClient,
    ZulipApiError,
    ZulipCredentials,
    load_zuliprc,
)
from openclaw_agents.communication.zulip_gateway import DispatchPlan, GatewayEvent, GatewayResult, ZulipGateway
from openclaw_agents.runtime.dispatcher import RuntimeDispatcher


_TAG_RE = re.compile(r"<[^>]+>")
_CODE_BLOCK_RE = re.compile(
    r"<pre(?P<pre_attrs>[^>]*)>\s*<code(?P<code_attrs>[^>]*)>(?P<body>.*?)</code>\s*</pre>",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"<code(?P<attrs>[^>]*)>(?P<body>.*?)</code>", re.IGNORECASE | re.DOTALL)


@dataclass(slots=True)
class ManagedBot:
    agent_id: str
    display_name: str
    email: str
    subscriptions: list[str]
    client: ZulipApiClient
    queue_id: str | None = None
    last_event_id: int = -1


class GatewayService:
    """Poll Zulip, normalize events, persist state, and mirror authoritative results."""

    def __init__(
        self,
        *,
        gateway_config_path: str | Path | None = None,
        routing_rules_path: str | Path | None = None,
        agent_registry_path: str | Path | None = None,
        zuliprc_dir: str | Path | None = None,
        state_dir: str | Path | None = None,
        poll_interval_seconds: float | None = None,
        queue_timeout_seconds: int | None = None,
        ensure_subscriptions: bool | None = None,
        verify_tls: bool = True,
        gateway: ZulipGateway | None = None,
        client_factory: Callable[[ZulipCredentials, bool], ZulipApiClient] | None = None,
    ) -> None:
        self.gateway = gateway or ZulipGateway(
            gateway_config_path=gateway_config_path,
            routing_rules_path=routing_rules_path,
            agent_registry_path=agent_registry_path,
        )
        self.gateway_config = self.gateway.gateway_config
        self.runtime_config = self.gateway_config.get("runtime", {})
        self.store = self.gateway.store

        zuliprc_env = self.runtime_config.get("zuliprc_dir_env", "OPENCLAW_ZULIPRC_DIR")
        state_env = self.runtime_config.get("state_dir_env", "OPENCLAW_ZULIP_GATEWAY_STATE_DIR")
        self.zuliprc_dir = Path(
            zuliprc_dir or os.environ.get(zuliprc_env, "")
        ).expanduser()
        self.state_dir = Path(
            state_dir or os.environ.get(state_env, "/tmp/openclaw_zulip_gateway")
        ).expanduser()
        self.poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else float(self.runtime_config.get("poll_interval_seconds", 1.0))
        )
        self.queue_timeout_seconds = (
            queue_timeout_seconds
            if queue_timeout_seconds is not None
            else int(self.runtime_config.get("queue_timeout_seconds", 0))
        )
        self.ensure_subscriptions_on_start = (
            ensure_subscriptions
            if ensure_subscriptions is not None
            else bool(self.runtime_config.get("ensure_subscriptions", True))
        )
        self.processed_message_cache_size = int(self.runtime_config.get("processed_message_cache_size", 5000))
        self.expected_site = os.environ.get(self.gateway_config.get("zulip", {}).get("server_url_env", ""))
        self.verify_tls = verify_tls
        self.client_factory = client_factory or (lambda credentials, tls: ZulipApiClient(credentials, verify_tls=tls))
        self.runtime_state_path = self.state_dir / "gateway_state.json"
        self.runtime_state = self._load_runtime_state()
        self.bots: dict[str, ManagedBot] = {}
        self.bot_emails: dict[str, str] = {}
        self._stop_requested = False
        self.runtime_dispatcher = RuntimeDispatcher(self.store, state_dir=self.state_dir / "dispatch_queue")

    @staticmethod
    def rendered_content_to_text(content: str) -> str:
        """Convert rendered Zulip HTML back to gateway-friendly markdown-ish text."""
        if "<" not in content or ">" not in content:
            return html.unescape(content).strip()

        placeholders: dict[str, str] = {}

        def replace_code_block(match: re.Match[str]) -> str:
            attrs = f"{match.group('pre_attrs')} {match.group('code_attrs')}"
            body = html.unescape(match.group("body")).strip("\n")
            lang_match = re.search(r'(?:language-|data-code-language=")([a-zA-Z0-9_+-]+)', attrs)
            lang = lang_match.group(1) if lang_match else ""
            fence = f"```{lang}\n{body}\n```" if lang else f"```\n{body}\n```"
            key = f"__CODE_BLOCK_{len(placeholders)}__"
            placeholders[key] = fence
            return f"\n{key}\n"

        text = _CODE_BLOCK_RE.sub(replace_code_block, content)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
        text = _INLINE_CODE_RE.sub(lambda m: f"`{html.unescape(m.group('body'))}`", text)
        text = _TAG_RE.sub("", text)
        text = html.unescape(text).replace("\xa0", " ")
        for key, value in placeholders.items():
            text = text.replace(key, value)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _load_runtime_state(self) -> dict[str, Any]:
        if not self.runtime_state_path.exists():
            return {"processed_message_ids": []}
        payload = json.loads(self.runtime_state_path.read_text())
        payload.setdefault("processed_message_ids", [])
        return payload

    def _save_runtime_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_state["processed_message_ids"] = self.runtime_state.get("processed_message_ids", [])[
            -self.processed_message_cache_size :
        ]
        self.runtime_state_path.write_text(json.dumps(self.runtime_state, indent=2, sort_keys=True) + "\n")

    def _mark_processed(self, message_id: str) -> None:
        processed = self.runtime_state.setdefault("processed_message_ids", [])
        if message_id not in processed:
            processed.append(message_id)
            self._save_runtime_state()

    def _is_processed(self, message_id: str) -> bool:
        return message_id in self.runtime_state.get("processed_message_ids", [])

    def _resolve_zuliprc_path(self, agent_id: str) -> Path:
        env_key = f"OPENCLAW_ZULIPRC_{agent_id.upper()}"
        direct = os.environ.get(env_key)
        if direct:
            return Path(direct).expanduser()
        if not str(self.zuliprc_dir):
            raise ValueError(
                "zuliprc directory is not configured; set OPENCLAW_ZULIPRC_DIR or pass --zuliprc-dir"
            )
        direct_path = (self.zuliprc_dir / f"{agent_id}.zuliprc").resolve()
        return direct_path

    def _load_bots(self) -> None:
        subscriptions = self.gateway_config.get("zulip", {}).get("subscriptions", {})
        registry = self.gateway.agent_registry.get("agents", {})
        bots: dict[str, ManagedBot] = {}
        bot_emails: dict[str, str] = {}
        for agent_id, streams in subscriptions.items():
            if not streams:
                continue
            credentials = load_zuliprc(self._resolve_zuliprc_path(agent_id))
            if self.expected_site and credentials.site.rstrip("/") != self.expected_site.rstrip("/"):
                raise ValueError(
                    f"{agent_id} zuliprc site {credentials.site} does not match {self.expected_site}"
                )
            client = self.client_factory(credentials, self.verify_tls)
            display_name = registry.get(agent_id, {}).get("display_name", agent_id)
            bots[agent_id] = ManagedBot(
                agent_id=agent_id,
                display_name=display_name,
                email=credentials.email,
                subscriptions=list(streams),
                client=client,
            )
            bot_emails[credentials.email] = agent_id
        if not bots:
            raise ValueError("no visible Zulip bots are configured")
        self.bots = bots
        self.bot_emails = bot_emails

    def initialize(self) -> None:
        if not self.bots:
            self._load_bots()
        if self.ensure_subscriptions_on_start:
            for bot in self.bots.values():
                bot.client.add_subscriptions(bot.subscriptions)
        for agent_id in self.bots:
            self.register_queue(agent_id)

    def register_queue(self, agent_id: str) -> None:
        bot = self.bots[agent_id]
        payload = bot.client.register_message_queue()
        bot.queue_id = payload["queue_id"]
        bot.last_event_id = int(payload["last_event_id"])

    def check(self) -> str:
        self.initialize()
        lines = [
            "gateway service configuration OK",
            f"- zuliprc dir: {self.zuliprc_dir}",
            f"- state dir: {self.state_dir}",
            f"- managed bots: {', '.join(sorted(self.bots))}",
        ]
        return "\n".join(lines)

    def _sender_type(self, sender_email: str | None, sender_name: str) -> str:
        if sender_email and sender_email in self.bot_emails:
            return "bot"
        if sender_email:
            return "human"
        canonical = self.gateway.canonicalize_agent(sender_name)
        return "bot" if canonical in self.gateway.agent_registry.get("agents", {}) else "human"

    def _convert_message_event(self, consumer_agent_id: str, event: dict[str, Any]) -> GatewayEvent | None:
        if event.get("type") != "message":
            return None
        message = event.get("message") or {}
        message_id = str(message.get("id"))
        if not message_id or self._is_processed(message_id):
            return None

        sender_name = message.get("sender_full_name") or message.get("sender_email") or "participant"
        sender_email = message.get("sender_email")
        sender_type = self._sender_type(sender_email, sender_name)

        if message.get("type") == "stream":
            stream_name = message.get("display_recipient") or ""
            topic_name = message.get("subject") or message.get("topic") or ""
        else:
            stream_name = self.gateway_config.get("streams", {}).get("executive", "exec")
            sender_slug = re.sub(r"[^a-z0-9]+", "-", sender_name.lower()).strip("-") or "dm"
            topic_name = f"dm/{consumer_agent_id}/{sender_slug}"

        content = self.rendered_content_to_text(message.get("content", ""))
        return GatewayEvent(
            message_id=message_id,
            sender_name=sender_name,
            sender_type=sender_type,
            stream_name=stream_name,
            topic_name=topic_name,
            content=content,
            sender_id=str(message["sender_id"]) if message.get("sender_id") is not None else None,
        )

    def _default_sender_agent(self) -> str:
        for preferred in ("agent_smith", "niaobe", "morpheus"):
            if preferred in self.bots:
                return preferred
        return next(iter(self.bots))

    def _is_visible_bot(self, agent_id: str | None) -> bool:
        return bool(agent_id and agent_id in self.bots)

    def _dispatch_sender_agent(self, result: GatewayResult) -> str:
        payload = (result.envelope.payload if result.envelope else None) or {}
        from_agent = payload.get("from_agent")
        if isinstance(from_agent, str):
            candidate = self.gateway.canonicalize_agent(from_agent)
            if candidate in self.bots:
                return candidate
        if result.dispatch_plan and result.dispatch_plan.target_agent in self.bots:
            return result.dispatch_plan.target_agent
        return self._default_sender_agent()

    def _assignment_sender_agent(self, candidate: dict[str, Any]) -> str:
        from_agent = candidate.get("from_agent")
        if self._is_visible_bot(from_agent):
            return from_agent
        to_agent = candidate.get("to_agent")
        if self._is_visible_bot(to_agent):
            return to_agent
        return self._default_sender_agent()

    def _control_sender_agent(self, result: GatewayResult) -> str:
        payload = (result.envelope.payload if result.envelope else None) or {}
        for raw_candidate in (payload.get("orchestrator_id"), payload.get("requested_by")):
            if isinstance(raw_candidate, str):
                candidate = self.gateway.canonicalize_agent(raw_candidate)
                if candidate in self.bots:
                    return candidate
        if result.project_id:
            project = self.store.get_project(result.project_id) or {}
            for candidate in (
                project.get("current_owner_agent"),
                project.get("assigned_project_orchestrator"),
                project.get("assigned_software_orchestrator"),
            ):
                if candidate in self.bots:
                    return candidate
        return self._default_sender_agent()

    def _result_sender_agent(self, candidate: dict[str, Any]) -> str:
        attempt_agent = candidate.get("attempt_agent_id")
        if self._is_visible_bot(attempt_agent):
            return attempt_agent
        from_agent = candidate.get("from_agent")
        if self._is_visible_bot(from_agent):
            return from_agent
        return_to = candidate.get("return_to")
        if return_to == "requesting_agent":
            return_to = from_agent
        if self._is_visible_bot(return_to):
            return return_to
        for fallback in (
            candidate.get("current_owner_agent"),
            candidate.get("assigned_software_orchestrator"),
            candidate.get("assigned_project_orchestrator"),
        ):
            if self._is_visible_bot(fallback):
                return fallback
        return self._default_sender_agent()

    def _send_stream_message(self, sender_agent: str, stream_name: str, topic_name: str, content: str) -> str:
        payload = self.bots[sender_agent].client.send_stream_message(stream_name, topic_name, content)
        message_id = payload.get("id")
        if message_id is None:
            raise ZulipApiError("Zulip message post succeeded without a message id", payload=payload)
        return str(message_id)

    def _post_dispatch_message(self, source_event: GatewayEvent, result: GatewayResult) -> str | None:
        if not result.dispatch_plan or not result.outbound_message:
            return None
        # Avoid re-posting an authoritative assignment that already landed in its final destination.
        if (
            result.envelope
            and result.envelope.schema_name == "task_assignment"
            and source_event.stream_name == result.dispatch_plan.reply_stream
            and source_event.topic_name == result.dispatch_plan.reply_topic
        ):
            return None
        sender_agent = self._dispatch_sender_agent(result)
        message_id = self._send_stream_message(
            sender_agent,
            result.dispatch_plan.reply_stream,
            result.dispatch_plan.reply_topic,
            result.outbound_message,
        )
        self.gateway.mapping_store.link_message(
            project_id=result.dispatch_plan.project_id,
            zulip_message_id=message_id,
            stream_name=result.dispatch_plan.reply_stream,
            topic_name=result.dispatch_plan.reply_topic,
            direction="outbound",
            message_kind="task_assignment",
            linked_entity_type="task",
            linked_entity_id=result.dispatch_plan.task_id,
            task_id=result.dispatch_plan.task_id,
        )
        self._mark_processed(message_id)
        return message_id

    def _post_control_event_message(self, result: GatewayResult) -> None:
        if not result.outbound_message or not result.project_id or not result.control_event_id:
            return
        sender_agent = self._control_sender_agent(result)
        stream_name, topic_name = self.gateway.control_event_address(result.project_id)
        message_id = self._send_stream_message(sender_agent, stream_name, topic_name, result.outbound_message)
        self.store.update(
            "control_events",
            {"mirrored_to_zulip": True, "mirrored_message_id": message_id},
            where_clause="event_id = ?",
            where_params=[result.control_event_id],
        )
        self.gateway.mapping_store.link_message(
            project_id=result.project_id,
            zulip_message_id=message_id,
            stream_name=stream_name,
            topic_name=topic_name,
            direction="outbound",
            message_kind="control_event",
            linked_entity_type="control_event",
            linked_entity_id=result.control_event_id,
            control_event_id=result.control_event_id,
        )
        self._mark_processed(message_id)

    def _handle_gateway_result(self, source_event: GatewayEvent, result: GatewayResult) -> GatewayResult:
        dispatch_message_id: str | None = None
        if result.dispatch_plan and result.outbound_message:
            dispatch_message_id = self._post_dispatch_message(source_event, result)
        elif result.control_event_id and result.outbound_message:
            self._post_control_event_message(result)
        if result.dispatch_plan:
            receipt = self.runtime_dispatcher.dispatch_plan(result.dispatch_plan)
            if dispatch_message_id:
                print(
                    f"queued task {receipt.task_id} for {receipt.agent_id} via {receipt.runtime_backend} "
                    f"packet={receipt.packet_ref} message_id={dispatch_message_id}"
        )
        return result

    def _mirror_visible_dispatches(self) -> list[str]:
        mirrored: list[str] = []
        for candidate in self.store.list_dispatch_mirror_candidates():
            sender_agent = self._assignment_sender_agent(candidate)
            stream_name, topic_name = self.gateway.reply_address_for_task(
                candidate["project_id"],
                candidate["task_id"],
                candidate["task_type"],
            )
            message = self.gateway.build_task_assignment_message(
                DispatchPlan(
                    project_id=candidate["project_id"],
                    task_id=candidate["task_id"],
                    target_agent=candidate["to_agent"],
                    task_type=candidate["task_type"],
                    reply_stream=stream_name,
                    reply_topic=topic_name,
                    reason=candidate["goal"],
                )
            )
            message_id = self._send_stream_message(sender_agent, stream_name, topic_name, message)
            self.gateway.mapping_store.link_message(
                project_id=candidate["project_id"],
                zulip_message_id=message_id,
                stream_name=stream_name,
                topic_name=topic_name,
                direction="outbound",
                message_kind="task_assignment",
                linked_entity_type="task",
                linked_entity_id=candidate["task_id"],
                task_id=candidate["task_id"],
            )
            self._mark_processed(message_id)
            mirrored.append(message_id)
        return mirrored

    def _mirror_morpheus_progress_updates(self) -> list[str]:
        mirrored: list[str] = []
        summaries = {
            "PLAN_SOFTWARE_TASK": "Morpheus started software planning.",
            "IMPLEMENT_SOFTWARE_TASK": "Morpheus started implementation.",
            "TEST_SOFTWARE_TASK": "Morpheus started testing.",
        }
        sender_agent = "morpheus" if "morpheus" in self.bots else self._default_sender_agent()
        for candidate in self.store.list_morpheus_progress_update_candidates():
            stream_name, topic_name = self.gateway.reply_address_for_task(
                candidate["project_id"],
                candidate["parent_task_id"],
                candidate.get("parent_task_type") or "ORCHESTRATE_SOFTWARE",
            )
            message = self.gateway.build_task_result_message(
                project_id=candidate["project_id"],
                task_id=candidate["task_id"],
                task_type=candidate["task_type"],
                agent="morpheus",
                status="RUNNING",
                summary=summaries.get(candidate["task_type"], "Morpheus started the next software phase."),
                artifacts_out=[],
                next_action={"type": "WAIT_FOR_EXTERNAL", "target_agent": "morpheus"},
                kind="status_update",
            )
            message_id = self._send_stream_message(sender_agent, stream_name, topic_name, message)
            self.gateway.mapping_store.link_message(
                project_id=candidate["project_id"],
                zulip_message_id=message_id,
                stream_name=stream_name,
                topic_name=topic_name,
                direction="outbound",
                message_kind="status_update",
                linked_entity_type="task",
                linked_entity_id=candidate["task_id"],
                task_id=candidate["task_id"],
            )
            self._mark_processed(message_id)
            mirrored.append(message_id)
        return mirrored

    def _mirror_completed_results(self) -> list[str]:
        mirrored: list[str] = []
        for candidate in self.store.list_result_mirror_candidates():
            sender_agent = self._result_sender_agent(candidate)
            stream_name, topic_name = self.gateway.reply_address_for_task(
                candidate["project_id"],
                candidate["task_id"],
                candidate["task_type"],
            )
            message = self.gateway.build_task_result_message(
                project_id=candidate["project_id"],
                task_id=candidate["task_id"],
                task_type=candidate["task_type"],
                agent=candidate["attempt_agent_id"],
                status=candidate["status"],
                summary=candidate.get("attempt_summary") or f"{candidate['task_type']} finished with {candidate['status']}",
                artifacts_out=candidate.get("output_artifact_refs_json") or [],
                next_action=candidate.get("next_action_json") or {},
            )
            message_id = self._send_stream_message(sender_agent, stream_name, topic_name, message)
            self.gateway.mapping_store.link_message(
                project_id=candidate["project_id"],
                zulip_message_id=message_id,
                stream_name=stream_name,
                topic_name=topic_name,
                direction="outbound",
                message_kind="task_result",
                linked_entity_type="task",
                linked_entity_id=candidate["task_id"],
                task_id=candidate["task_id"],
            )
            self._mark_processed(message_id)
            mirrored.append(message_id)
        return mirrored

    def process_pending_events(self) -> list[GatewayResult]:
        results: list[GatewayResult] = []
        for agent_id, bot in self.bots.items():
            if bot.queue_id is None:
                self.register_queue(agent_id)
            try:
                payload = bot.client.get_events(
                    bot.queue_id or "",
                    bot.last_event_id,
                    timeout_seconds=self.queue_timeout_seconds,
                    dont_block=True,
                )
            except ZulipApiError as exc:
                if exc.error_code == "BAD_EVENT_QUEUE_ID" or "queue" in str(exc).lower():
                    self.register_queue(agent_id)
                    continue
                raise
            bot.last_event_id = int(payload.get("last_event_id", bot.last_event_id))
            for raw_event in payload.get("events", []):
                bot.last_event_id = max(bot.last_event_id, int(raw_event.get("id", bot.last_event_id)))
                gateway_event = self._convert_message_event(agent_id, raw_event)
                if gateway_event is None:
                    continue
                try:
                    result = self.gateway.handle_inbound_event(gateway_event)
                    self._handle_gateway_result(gateway_event, result)
                    self._mark_processed(gateway_event.message_id)
                    results.append(result)
                except Exception as exc:  # pragma: no cover - runtime protection path
                    print(f"gateway event handling failed for message {gateway_event.message_id}: {exc}", file=sys.stderr)
        self._mirror_visible_dispatches()
        self._mirror_morpheus_progress_updates()
        self._mirror_completed_results()
        return results

    def request_stop(self, *_args: Any) -> None:
        self._stop_requested = True

    def serve_forever(self) -> None:
        self.initialize()
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)
        while not self._stop_requested:
            self.process_pending_events()
            time.sleep(self.poll_interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the shared OpenClaw Zulip gateway service")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("zulip_gateway_config.yaml")),
        help="Path to zulip_gateway_config.yaml",
    )
    parser.add_argument("--routing-rules", help="Optional path to routing_rules.yaml")
    parser.add_argument("--agent-registry", help="Optional path to agent_registry.yaml")
    parser.add_argument("--zuliprc-dir", help="Directory containing <agent_id>.zuliprc files")
    parser.add_argument("--state-dir", help="Directory for gateway runtime state")
    parser.add_argument("--poll-interval", type=float, help="Non-blocking poll interval in seconds")
    parser.add_argument("--queue-timeout", type=int, help="Queue poll timeout in seconds")
    parser.add_argument("--skip-subscriptions", action="store_true", help="Skip startup subscription sync")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for Zulip API calls")
    parser.add_argument("--once", action="store_true", help="Process one non-blocking poll cycle and exit")
    parser.add_argument("--check", action="store_true", help="Validate configuration and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = GatewayService(
        gateway_config_path=args.config,
        routing_rules_path=args.routing_rules,
        agent_registry_path=args.agent_registry,
        zuliprc_dir=args.zuliprc_dir,
        state_dir=args.state_dir,
        poll_interval_seconds=args.poll_interval,
        queue_timeout_seconds=args.queue_timeout,
        ensure_subscriptions=not args.skip_subscriptions,
        verify_tls=not args.insecure,
    )
    if args.check:
        print(service.check())
        return 0
    if args.once:
        service.initialize()
        results = service.process_pending_events()
        print(f"processed {len(results)} gateway result(s)")
        return 0
    service.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
