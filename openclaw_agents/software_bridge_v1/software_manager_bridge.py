#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import configparser
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def save_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def ensure_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_path(base_dir: pathlib.Path, value: str) -> pathlib.Path:
    candidate = pathlib.Path(value)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def contains_template_placeholder(value: str) -> bool:
    return "YOUR_" in value


def load_zuliprc(path: pathlib.Path) -> dict[str, str]:
    parser = configparser.ConfigParser()
    with path.open() as handle:
        parser.read_file(handle)
    if "api" not in parser:
        raise ValueError(f"Missing [api] section in {path}")
    section = parser["api"]
    required = ["site", "email", "key"]
    missing = [key for key in required if not section.get(key)]
    if missing:
        raise ValueError(f"Missing fields in {path}: {', '.join(missing)}")
    placeholder_fields = [key for key in required if contains_template_placeholder(section[key])]
    if placeholder_fields:
        raise ValueError(
            f"Replace template placeholders in {path}: {', '.join(placeholder_fields)}"
        )
    return {
        "site": section["site"].rstrip("/"),
        "email": section["email"],
        "key": section["key"],
    }


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "topic"


def topic_storage_dir(state_dir: pathlib.Path, stream_name: str, topic: str) -> pathlib.Path:
    topic_hash = hashlib.sha1(f"{stream_name}:{topic}".encode()).hexdigest()[:10]
    return state_dir / "topics" / f"{slugify(topic)}-{topic_hash}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class ZulipClient:
    def __init__(self, site: str, email: str, api_key: str, verify_tls: bool) -> None:
        self.site = site.rstrip("/")
        token = base64.b64encode(f"{email}:{api_key}".encode()).decode()
        self.auth_header = f"Basic {token}"
        self.ssl_context = ssl.create_default_context()
        if not verify_tls:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.site}{path}"
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"

        data: bytes | None = None
        headers = {"Authorization": self.auth_header}
        if form is not None:
            encoded_form: dict[str, Any] = {}
            for key, value in form.items():
                if isinstance(value, (dict, list)):
                    encoded_form[key] = json.dumps(value)
                else:
                    encoded_form[key] = value
            data = urllib.parse.urlencode(encoded_form, doseq=True).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self.ssl_context) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise RuntimeError(f"Zulip API error {exc.code} for {path}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to reach Zulip at {url}: {exc}") from exc

        if payload.get("result") != "success":
            msg = payload.get("msg", "unknown Zulip API failure")
            raise RuntimeError(f"Zulip API failure for {path}: {msg}")
        return payload

    def register_message_queue(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/register",
            form={"event_types": ["message"]},
        )

    def get_events(self, queue_id: str, last_event_id: int, timeout_seconds: int) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/events",
            params={
                "queue_id": queue_id,
                "last_event_id": last_event_id,
                "dont_block": "false",
                "timeout": str(timeout_seconds),
            },
        )

    def send_stream_message(self, stream_name: str, topic: str, content: str) -> None:
        self._request(
            "POST",
            "/api/v1/messages",
            form={
                "type": "stream",
                "to": stream_name,
                "topic": topic,
                "content": content,
            },
        )


class Bridge:
    def __init__(self, config_path: pathlib.Path) -> None:
        self.config_path = config_path.resolve()
        self.config_dir = self.config_path.parent
        raw_config = load_json(self.config_path)

        zuliprc_path = resolve_path(self.config_dir, raw_config["zuliprc_path"])
        zuliprc = load_zuliprc(zuliprc_path)

        self.stream_name = raw_config["stream_name"]
        self.software_workspace = resolve_path(self.config_dir, raw_config["software_workspace"])
        self.software_run_command = raw_config.get("software_run_command", ["bash", ".agents/run_team.sh"])
        self.state_dir = resolve_path(self.config_dir, raw_config.get("state_dir", "./state"))
        self.verify_tls = bool(raw_config.get("verify_tls", False))
        self.poll_timeout_seconds = int(raw_config.get("poll_timeout_seconds", 30))
        self.history_entry_limit = int(raw_config.get("history_entry_limit", 20))
        self.send_acknowledgement = bool(raw_config.get("send_acknowledgement", True))

        ensure_dir(self.state_dir)
        ensure_dir(self.state_dir / "topics")

        self.state_path = self.state_dir / "bridge_state.json"
        self.state = self._load_state()

        self.client = ZulipClient(
            site=zuliprc["site"],
            email=zuliprc["email"],
            api_key=zuliprc["key"],
            verify_tls=self.verify_tls,
        )
        self.bot_email = zuliprc["email"]

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"processed_message_ids": [], "topics": {}}
        payload = load_json(self.state_path)
        payload.setdefault("processed_message_ids", [])
        payload.setdefault("topics", {})
        return payload

    def _save_state(self) -> None:
        processed = self.state.get("processed_message_ids", [])
        self.state["processed_message_ids"] = processed[-500:]
        save_json(self.state_path, self.state)

    def check(self) -> None:
        run_script = self.software_workspace / self.software_run_command[1]
        if contains_template_placeholder(self.stream_name):
            raise RuntimeError("Replace the stream_name placeholder in the bridge config.")
        if contains_template_placeholder(str(self.software_workspace)):
            raise RuntimeError("Replace the software_workspace placeholder in the bridge config.")
        if not self.software_workspace.exists():
            raise RuntimeError(f"Software workspace does not exist: {self.software_workspace}")
        if not (self.software_workspace / "PROJECT.md").exists():
            raise RuntimeError(f"Missing PROJECT.md in software workspace: {self.software_workspace / 'PROJECT.md'}")
        if len(self.software_run_command) < 2:
            raise RuntimeError("software_run_command must include the executable and script path")
        if not run_script.exists():
            raise RuntimeError(f"Missing software team run script: {run_script}")
        print("Bridge config OK")
        print(f"- stream: {self.stream_name}")
        print(f"- software workspace: {self.software_workspace}")
        print(f"- state dir: {self.state_dir}")
        print(f"- zulip site: {self.client.site}")

    def _topic_state(self, stream_name: str, topic: str) -> tuple[pathlib.Path, dict[str, Any]]:
        topic_dir = topic_storage_dir(self.state_dir, stream_name, topic)
        ensure_dir(topic_dir)
        topic_key = str(topic_dir.relative_to(self.state_dir))
        topics = self.state.setdefault("topics", {})
        topic_state = topics.setdefault(topic_key, {"stream": stream_name, "topic": topic, "history": []})
        topic_state["stream"] = stream_name
        topic_state["topic"] = topic
        topic_state["topic_dir"] = str(topic_dir)
        return topic_dir, topic_state

    def _append_history(
        self,
        topic_state: dict[str, Any],
        *,
        role: str,
        sender: str,
        content: str,
        message_id: int | None = None,
    ) -> None:
        entry = {
            "timestamp": now_iso(),
            "role": role,
            "sender": sender,
            "content": content,
        }
        if message_id is not None:
            entry["message_id"] = message_id
        topic_state.setdefault("history", []).append(entry)
        topic_state["history"] = topic_state["history"][-200:]

    def _write_transcript(self, topic_dir: pathlib.Path, topic_state: dict[str, Any]) -> None:
        lines: list[str] = [
            f"# Transcript for {topic_state['stream']} / {topic_state['topic']}",
            "",
        ]
        for entry in topic_state.get("history", []):
            lines.append(f"## {entry['role'].upper()} | {entry['sender']} | {entry['timestamp']}")
            if entry.get("message_id") is not None:
                lines.append(f"message_id: {entry['message_id']}")
            lines.append("")
            lines.append(entry["content"].strip())
            lines.append("")
        (topic_dir / "transcript.md").write_text("\n".join(lines).strip() + "\n")
        save_json(topic_dir / "topic_state.json", topic_state)

    def _format_recent_history(self, topic_state: dict[str, Any]) -> str:
        entries = topic_state.get("history", [])[-self.history_entry_limit :]
        blocks: list[str] = []
        for entry in entries:
            header = f"{entry['role'].upper()} | {entry['sender']} | {entry['timestamp']}"
            blocks.append(f"{header}\n{entry['content'].strip()}")
        return "\n\n".join(blocks)

    def _build_prompt(self, stream_name: str, topic: str, topic_state: dict[str, Any]) -> str:
        transcript = self._format_recent_history(topic_state)
        return (
            "Handle the following Zulip software task thread.\n\n"
            f"Stream: {stream_name}\n"
            f"Topic: {topic}\n"
            "Sandbox workspace path: /workspace\n\n"
            "Instructions:\n"
            "- Use PROJECT.md in the project workspace as the current source of truth.\n"
            "- Inside the OpenClaw sandbox, the repository root is /workspace.\n"
            "- Use repo-root-relative paths or /workspace/... paths only in assignments and summaries.\n"
            "- Treat the transcript below as the current task thread.\n"
            "- Continue the software work for this Zulip topic.\n"
            "- Return a concise manager summary suitable for posting back into Zulip.\n\n"
            "THREAD_TRANSCRIPT:\n"
            f"{transcript}"
        )

    def _run_software_team(self, stream_name: str, topic: str, topic_state: dict[str, Any]) -> str:
        prompt = self._build_prompt(stream_name, topic, topic_state)
        command = list(self.software_run_command) + [prompt]
        completed = subprocess.run(
            command,
            cwd=self.software_workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown failure"
            raise RuntimeError(f"Software team command failed: {stderr}")
        return completed.stdout.strip()

    def _stream_name_from_message(self, message: dict[str, Any]) -> str | None:
        recipient = message.get("display_recipient")
        if isinstance(recipient, str):
            return recipient
        return None

    def _handle_message(self, message: dict[str, Any]) -> None:
        if message.get("type") != "stream":
            return
        if message.get("sender_email") == self.bot_email:
            return

        stream_name = self._stream_name_from_message(message)
        if stream_name != self.stream_name:
            return

        message_id = int(message["id"])
        processed_ids = self.state.setdefault("processed_message_ids", [])
        if message_id in processed_ids:
            return

        topic = message.get("topic") or message.get("subject") or "task"
        sender = message.get("sender_full_name") or message.get("sender_email") or "human"
        content = (message.get("content") or "").strip()
        if not content:
            processed_ids.append(message_id)
            self._save_state()
            return

        topic_dir, topic_state = self._topic_state(stream_name, topic)
        self._append_history(
            topic_state,
            role="human",
            sender=sender,
            content=content,
            message_id=message_id,
        )
        self._write_transcript(topic_dir, topic_state)

        if self.send_acknowledgement:
            ack = "Software manager received this task and is starting a run."
            self.client.send_stream_message(stream_name, topic, ack)

        try:
            result = self._run_software_team(stream_name, topic, topic_state)
        except Exception as exc:
            error_text = f"Software manager run failed.\n\n```text\n{exc}\n```"
            self._append_history(
                topic_state,
                role="manager",
                sender=self.bot_email,
                content=error_text,
            )
            self._write_transcript(topic_dir, topic_state)
            self.client.send_stream_message(stream_name, topic, error_text)
            processed_ids.append(message_id)
            self._save_state()
            return

        self._append_history(
            topic_state,
            role="manager",
            sender=self.bot_email,
            content=result,
        )
        self._write_transcript(topic_dir, topic_state)
        self.client.send_stream_message(stream_name, topic, result)

        processed_ids.append(message_id)
        self._save_state()

    def serve_forever(self) -> None:
        registration = self.client.register_message_queue()
        queue_id = registration["queue_id"]
        last_event_id = int(registration["last_event_id"])
        print(f"Listening for Zulip messages in stream '{self.stream_name}'...")

        while True:
            response = self.client.get_events(queue_id, last_event_id, self.poll_timeout_seconds)
            for event in response.get("events", []):
                last_event_id = int(event["id"])
                if event.get("type") != "message":
                    continue
                self._handle_message(event["message"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Zulip V1 software manager bridge")
    parser.add_argument("--config", required=True, help="Path to bridge config JSON")
    parser.add_argument("--check", action="store_true", help="Validate config and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bridge = Bridge(pathlib.Path(args.config))
    if args.check:
        bridge.check()
        return 0
    bridge.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
