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
import signal
import ssl
import subprocess
import sys
import threading
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
        raise ValueError(f"Replace template placeholders in {path}: {', '.join(placeholder_fields)}")
    return {
        "site": section["site"].rstrip("/"),
        "email": section["email"],
        "key": section["key"],
    }


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "topic"


def topic_storage_dir(state_dir: pathlib.Path, scope_name: str, topic: str) -> pathlib.Path:
    topic_hash = hashlib.sha1(f"{scope_name}:{topic}".encode()).hexdigest()[:10]
    return state_dir / "topics" / f"{slugify(topic)}-{topic_hash}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )


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
        return self._request("POST", "/api/v1/register", form={"event_types": ["message"]})

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
            form={"type": "stream", "to": stream_name, "topic": topic, "content": content},
        )

    def send_private_message(self, emails: list[str], content: str) -> None:
        self._request(
            "POST",
            "/api/v1/messages",
            form={"type": "private", "to": emails, "content": content},
        )


class Bridge:
    def __init__(self, config_path: pathlib.Path) -> None:
        self.config_path = config_path.resolve()
        self.config_dir = self.config_path.parent
        raw_config = load_json(self.config_path)

        persona_registry_value = raw_config.get("persona_registry_path")
        if not persona_registry_value:
            raise RuntimeError("persona_registry_path is required.")
        self.persona_registry_path = resolve_path(self.config_dir, persona_registry_value)
        self.state_dir = resolve_path(self.config_dir, raw_config.get("state_dir", "./state"))
        self.verify_tls = bool(raw_config.get("verify_tls", False))
        self.poll_timeout_seconds = int(raw_config.get("poll_timeout_seconds", 15))
        self.history_entry_limit = int(raw_config.get("history_entry_limit", 20))
        self.send_acknowledgement = bool(raw_config.get("send_acknowledgement", True))
        self.send_status_updates = bool(raw_config.get("send_status_updates", True))

        ensure_dir(self.state_dir)
        self.personas = self._load_persona_registry()
        self.all_persona_emails = {persona["email"] for persona in self.personas.values()}
        self.active_runs: dict[str, dict[str, Any]] = {}
        self.active_runs_lock = threading.Lock()

    def _load_runtime_state(self, state_path: pathlib.Path) -> dict[str, Any]:
        if not state_path.exists():
            return {"processed_message_ids": [], "topics": {}}
        payload = load_json(state_path)
        payload.setdefault("processed_message_ids", [])
        payload.setdefault("topics", {})
        return payload

    def _save_runtime_state(self, persona: dict[str, Any]) -> None:
        with persona["state_lock"]:
            processed = persona["state"].get("processed_message_ids", [])
            persona["state"]["processed_message_ids"] = processed[-500:]
            save_json(persona["state_path"], persona["state"])

    def _load_persona_registry(self) -> dict[str, dict[str, Any]]:
        if contains_template_placeholder(str(self.persona_registry_path)):
            raise RuntimeError("Replace the persona_registry_path placeholder in the bridge config.")
        if not self.persona_registry_path.exists():
            raise RuntimeError(f"Persona registry does not exist: {self.persona_registry_path}")

        raw_registry = load_json(self.persona_registry_path)
        raw_personas = raw_registry.get("personas")
        if not isinstance(raw_personas, dict) or not raw_personas:
            raise RuntimeError("Persona registry must define a non-empty 'personas' mapping.")

        personas: dict[str, dict[str, Any]] = {}
        for slug, entry in raw_personas.items():
            if contains_template_placeholder(slug):
                raise RuntimeError(f"Replace template placeholders in persona slug: {slug}")
            if not isinstance(entry, dict):
                raise RuntimeError(f"Persona registry entry for {slug} must be an object.")

            display_name = entry.get("display_name") or slug
            zuliprc_value = entry.get("zuliprc_path")
            workspace_value = entry.get("workspace")
            run_command = entry.get("run_command")
            allowed_streams = entry.get("allowed_streams", [])
            reply_mode = entry.get("reply_mode", "dm_or_mention")

            if contains_template_placeholder(display_name):
                raise RuntimeError(f"Replace template placeholders in display_name for {slug}.")
            if not zuliprc_value:
                raise RuntimeError(f"Persona {slug} is missing zuliprc_path.")
            if not workspace_value:
                raise RuntimeError(f"Persona {slug} is missing workspace.")
            if not isinstance(run_command, list) or len(run_command) < 2:
                raise RuntimeError(f"Persona {slug} must define run_command with at least executable and script.")
            if not isinstance(allowed_streams, list):
                raise RuntimeError(f"Persona {slug} allowed_streams must be a list.")
            if reply_mode not in {"dm_only", "dm_or_mention", "mention_only", "always"}:
                raise RuntimeError(f"Persona {slug} has invalid reply_mode: {reply_mode}")

            zuliprc = load_zuliprc(resolve_path(self.persona_registry_path.parent, zuliprc_value))
            workspace = resolve_path(self.persona_registry_path.parent, workspace_value)
            state_dir = self.state_dir / slug
            ensure_dir(state_dir)
            ensure_dir(state_dir / "topics")
            state_path = state_dir / "bridge_state.json"
            mention_triggers = entry.get("mention_triggers") or []
            if not mention_triggers:
                mention_triggers = [slug, display_name, zuliprc["email"].split("@", 1)[0]]

            personas[slug] = {
                "slug": slug,
                "display_name": display_name,
                "description": entry.get("description", ""),
                "bridge_instructions": entry.get("bridge_instructions", ""),
                "workspace": workspace,
                "run_command": list(run_command),
                "allow_dm": bool(entry.get("allow_dm", True)),
                "allowed_streams": [str(stream) for stream in allowed_streams],
                "reply_mode": reply_mode,
                "mention_triggers": [str(trigger).strip().lower() for trigger in mention_triggers if str(trigger).strip()],
                "client": ZulipClient(
                    site=zuliprc["site"],
                    email=zuliprc["email"],
                    api_key=zuliprc["key"],
                    verify_tls=self.verify_tls,
                ),
                "email": zuliprc["email"],
                "state_dir": state_dir,
                "state_path": state_path,
                "state": self._load_runtime_state(state_path),
                "state_lock": threading.Lock(),
            }

        return personas

    def check(self) -> None:
        for slug, persona in sorted(self.personas.items()):
            if contains_template_placeholder(str(persona["workspace"])):
                raise RuntimeError(f"Replace template placeholders in workspace for persona {slug}.")
            if not persona["workspace"].exists():
                raise RuntimeError(f"Workspace does not exist for persona {slug}: {persona['workspace']}")
            run_script = persona["workspace"] / persona["run_command"][1]
            if not run_script.exists():
                raise RuntimeError(f"Missing run script for persona {slug}: {run_script}")
            for stream_name in persona["allowed_streams"]:
                if contains_template_placeholder(stream_name):
                    raise RuntimeError(f"Replace template placeholders in allowed_streams for persona {slug}.")
            print(
                f"OK: {slug} -> email={persona['email']} workspace={persona['workspace']} "
                f"reply_mode={persona['reply_mode']} streams={persona['allowed_streams']}"
            )
        print("Persona bridge config OK")
        print(f"- registry: {self.persona_registry_path}")
        print(f"- state dir: {self.state_dir}")
        print(f"- personas: {', '.join(sorted(self.personas))}")

    def _run_key(self, slug: str, scope_name: str, topic: str) -> str:
        return f"{slug}::{scope_name}::{topic}"

    def _start_active_run(self, run_key: str, *, persona_name: str, scope_name: str, topic: str) -> bool:
        with self.active_runs_lock:
            if run_key in self.active_runs:
                return False
            self.active_runs[run_key] = {
                "persona_name": persona_name,
                "scope": scope_name,
                "topic": topic,
                "phase": "queued",
                "started_at": now_iso(),
                "process": None,
                "stop_requested": False,
            }
            return True

    def _finish_active_run(self, run_key: str) -> None:
        with self.active_runs_lock:
            self.active_runs.pop(run_key, None)

    def _set_active_phase(self, run_key: str, phase: str) -> None:
        with self.active_runs_lock:
            run = self.active_runs.get(run_key)
            if run is not None:
                run["phase"] = phase

    def _set_active_process(self, run_key: str, process: subprocess.Popen[str] | None) -> None:
        with self.active_runs_lock:
            run = self.active_runs.get(run_key)
            if run is not None:
                run["process"] = process

    def _active_status(self, run_key: str) -> dict[str, Any] | None:
        with self.active_runs_lock:
            run = self.active_runs.get(run_key)
            if run is None:
                return None
            return dict(run)

    def _is_stop_requested(self, run_key: str) -> bool:
        status = self._active_status(run_key)
        return bool(status and status.get("stop_requested"))

    def _request_stop(self, run_key: str) -> bool:
        with self.active_runs_lock:
            run = self.active_runs.get(run_key)
            if run is None:
                return False
            run["stop_requested"] = True
            run["phase"] = "stop requested"
            process = run.get("process")
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.time() + 3.0
            while time.time() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return True

    def _conversation_state(
        self,
        persona: dict[str, Any],
        scope_name: str,
        topic: str,
    ) -> tuple[pathlib.Path, dict[str, Any]]:
        with persona["state_lock"]:
            topic_dir = topic_storage_dir(persona["state_dir"], scope_name, topic)
            ensure_dir(topic_dir)
            topic_key = str(topic_dir.relative_to(persona["state_dir"]))
            topics = persona["state"].setdefault("topics", {})
            topic_state = topics.setdefault(topic_key, {"scope": scope_name, "topic": topic, "history": []})
            topic_state["scope"] = scope_name
            topic_state["topic"] = topic
            topic_state["topic_dir"] = str(topic_dir)
            return topic_dir, topic_state

    def _append_history(
        self,
        persona: dict[str, Any],
        topic_state: dict[str, Any],
        *,
        role: str,
        sender: str,
        content: str,
        message_id: int | None = None,
    ) -> None:
        with persona["state_lock"]:
            entry = {"timestamp": now_iso(), "role": role, "sender": sender, "content": content}
            if message_id is not None:
                entry["message_id"] = message_id
            topic_state.setdefault("history", []).append(entry)
            topic_state["history"] = topic_state["history"][-200:]

    def _write_transcript(self, persona: dict[str, Any], topic_dir: pathlib.Path, topic_state: dict[str, Any]) -> None:
        with persona["state_lock"]:
            lines: list[str] = [f"# Transcript for {topic_state['scope']} / {topic_state['topic']}", ""]
            for entry in topic_state.get("history", []):
                lines.append(f"## {entry['role'].upper()} | {entry['sender']} | {entry['timestamp']}")
                if entry.get("message_id") is not None:
                    lines.append(f"message_id: {entry['message_id']}")
                lines.append("")
                lines.append(entry["content"].strip())
                lines.append("")
            (topic_dir / "transcript.md").write_text("\n".join(lines).strip() + "\n")
            save_json(topic_dir / "topic_state.json", topic_state)

    def _format_recent_history(self, persona: dict[str, Any], topic_state: dict[str, Any]) -> str:
        with persona["state_lock"]:
            entries = list(topic_state.get("history", [])[-self.history_entry_limit :])
        blocks: list[str] = []
        for entry in entries:
            header = f"{entry['role'].upper()} | {entry['sender']} | {entry['timestamp']}"
            blocks.append(f"{header}\n{entry['content'].strip()}")
        return "\n\n".join(blocks)

    def _build_prompt(
        self,
        persona: dict[str, Any],
        scope_name: str,
        topic: str,
        topic_state: dict[str, Any],
    ) -> str:
        transcript = self._format_recent_history(persona, topic_state)
        description_line = ""
        if persona["description"]:
            description_line = f"- Persona description: {persona['description']}\n"
        extra_line = ""
        if persona["bridge_instructions"]:
            extra_line = f"- Extra bridge instructions: {persona['bridge_instructions']}\n"
        return (
            "Handle the following Zulip persona conversation.\n\n"
            f"Persona slug: {persona['slug']}\n"
            f"Persona display name: {persona['display_name']}\n"
            f"Conversation scope: {scope_name}\n"
            f"Conversation topic: {topic}\n"
            f"Host workspace: {persona['workspace']}\n\n"
            "Instructions:\n"
            f"{description_line}"
            f"{extra_line}"
            "- The persona's underlying command and prompt define its soul and behavior.\n"
            "- Use the conversation transcript below as the current thread context.\n"
            "- Return one concise reply suitable for posting back into Zulip.\n\n"
            "THREAD_TRANSCRIPT:\n"
            f"{transcript}"
        )

    def _extract_private_recipients(self, persona: dict[str, Any], message: dict[str, Any]) -> list[str]:
        recipients: list[str] = []
        display = message.get("display_recipient")
        if isinstance(display, list):
            for entry in display:
                email = entry.get("email")
                if email and email != persona["email"]:
                    recipients.append(email)
        sender_email = message.get("sender_email")
        if sender_email and sender_email != persona["email"] and sender_email not in recipients:
            recipients.append(sender_email)
        return sorted(set(recipients))

    def _private_scope(self, persona: dict[str, Any], message: dict[str, Any]) -> tuple[str, str, list[str]]:
        recipients = self._extract_private_recipients(persona, message)
        display = message.get("display_recipient")
        names: list[str] = []
        if isinstance(display, list):
            for entry in display:
                email = entry.get("email")
                if email and email == persona["email"]:
                    continue
                names.append(entry.get("full_name") or email or "user")
        label = ", ".join(sorted(set(names))) or (message.get("sender_full_name") or "direct-message")
        return "dm", label, recipients

    def _stream_name_from_message(self, message: dict[str, Any]) -> str | None:
        recipient = message.get("display_recipient")
        if isinstance(recipient, str):
            return recipient
        return None

    def _matches_trigger(self, trigger: str, plain_lower: str) -> bool:
        escaped = re.escape(trigger)
        if re.fullmatch(r"[a-z0-9_-]+", trigger):
            return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", plain_lower) is not None
        return escaped.lower() in plain_lower

    def _is_persona_invoked(self, persona: dict[str, Any], content: str) -> bool:
        plain = strip_html(content).lower()
        summon_match = re.match(r"^\s*/(?:summon|ask)\s+([a-z0-9_-]+)\b", plain)
        if summon_match:
            target = summon_match.group(1)
            trigger_set = {persona["slug"].lower(), *persona["mention_triggers"]}
            if target in trigger_set:
                return True
        for trigger in persona["mention_triggers"]:
            if self._matches_trigger(trigger, plain):
                return True
        return False

    def _should_process_stream_message(
        self,
        persona: dict[str, Any],
        stream_name: str,
        topic: str,
        content: str,
    ) -> bool:
        if stream_name not in persona["allowed_streams"]:
            return False
        lowered = strip_html(content).lstrip().lower()
        run_key = self._run_key(persona["slug"], stream_name, topic)
        active_status = self._active_status(run_key)
        if lowered.startswith("/status") or lowered.startswith("/stop") or lowered.startswith("/help"):
            if active_status is not None:
                return True
        if persona["reply_mode"] == "always":
            return True
        if persona["reply_mode"] == "dm_only":
            return False
        return self._is_persona_invoked(persona, content)

    def _route_for_message(
        self,
        persona: dict[str, Any],
        message: dict[str, Any],
    ) -> tuple[str, str, list[str] | None] | None:
        message_type = message.get("type")
        if message_type == "private":
            if not persona["allow_dm"]:
                return None
            scope_name, topic, recipients = self._private_scope(persona, message)
            return scope_name, topic, recipients
        if message_type == "stream":
            stream_name = self._stream_name_from_message(message)
            if stream_name is None:
                return None
            topic = message.get("topic") or message.get("subject") or "discussion"
            if not self._should_process_stream_message(persona, stream_name, topic, message.get("content") or ""):
                return None
            return stream_name, topic, None
        return None

    def _reply(
        self,
        persona: dict[str, Any],
        message: dict[str, Any],
        scope_name: str,
        topic: str,
        private_recipients: list[str] | None,
        content: str,
    ) -> None:
        if message.get("type") == "private":
            assert private_recipients is not None
            persona["client"].send_private_message(private_recipients, content)
            return
        persona["client"].send_stream_message(scope_name, topic, content)

    def _post_status(
        self,
        persona: dict[str, Any],
        message: dict[str, Any],
        scope_name: str,
        topic: str,
        private_recipients: list[str] | None,
        topic_state: dict[str, Any],
        content: str,
        topic_dir: pathlib.Path,
    ) -> None:
        self._reply(persona, message, scope_name, topic, private_recipients, content)
        self._append_history(persona, topic_state, role="status", sender=persona["display_name"], content=content)
        self._write_transcript(persona, topic_dir, topic_state)

    def _run_command(self, persona: dict[str, Any], prompt: str, run_key: str) -> str:
        completed = subprocess.Popen(
            list(persona["run_command"]) + [prompt],
            cwd=persona["workspace"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
        )
        self._set_active_process(run_key, completed)
        stdout, stderr = completed.communicate()
        self._set_active_process(run_key, None)
        if self._is_stop_requested(run_key):
            raise InterruptedError("stopped by user")
        if completed.returncode != 0:
            error_text = stderr.strip() or stdout.strip() or "unknown failure"
            raise RuntimeError(f"{persona['display_name']} command failed: {error_text}")
        return stdout.strip()

    def _run_persona(
        self,
        persona: dict[str, Any],
        scope_name: str,
        topic: str,
        topic_state: dict[str, Any],
        run_key: str,
    ) -> str:
        prompt = self._build_prompt(persona, scope_name, topic, topic_state)
        return self._run_command(persona, prompt, run_key)

    def _reply_for_help(self, persona: dict[str, Any]) -> str:
        streams = ", ".join(persona["allowed_streams"]) if persona["allowed_streams"] else "none"
        return (
            f"{persona['display_name']} bridge commands:\n\n"
            "- `/help`\n"
            "- `/status`\n"
            "- `/stop`\n\n"
            f"Reply mode: `{persona['reply_mode']}`\n"
            f"DM enabled: `{str(persona['allow_dm']).lower()}`\n"
            f"Allowed streams: {streams}"
        )

    def _run_topic_work(
        self,
        persona: dict[str, Any],
        message: dict[str, Any],
        scope_name: str,
        topic: str,
        private_recipients: list[str] | None,
        topic_dir: pathlib.Path,
        topic_state: dict[str, Any],
        run_key: str,
    ) -> None:
        try:
            if self.send_status_updates:
                self._set_active_phase(run_key, "reading thread context")
                self._post_status(
                    persona,
                    message,
                    scope_name,
                    topic,
                    private_recipients,
                    topic_state,
                    f"{persona['display_name']} status: reading the current thread context.",
                    topic_dir,
                )
                self._set_active_phase(run_key, "running persona")
                self._post_status(
                    persona,
                    message,
                    scope_name,
                    topic,
                    private_recipients,
                    topic_state,
                    f"{persona['display_name']} status: running the persona analysis for this thread.",
                    topic_dir,
                )
                self._set_active_phase(run_key, "drafting reply")
                self._post_status(
                    persona,
                    message,
                    scope_name,
                    topic,
                    private_recipients,
                    topic_state,
                    f"{persona['display_name']} status: drafting the final reply for this thread.",
                    topic_dir,
                )
            result = self._run_persona(persona, scope_name, topic, topic_state, run_key)
        except InterruptedError:
            result = f"{persona['display_name']} stopped this run on request."
        except Exception as exc:
            if self._is_stop_requested(run_key):
                result = f"{persona['display_name']} stopped this run on request."
            else:
                result = f"{persona['display_name']} run failed.\n\n```text\n{exc}\n```"

        self._set_active_phase(run_key, "completed")
        self._append_history(persona, topic_state, role="persona", sender=persona["display_name"], content=result)
        self._write_transcript(persona, topic_dir, topic_state)
        self._reply(persona, message, scope_name, topic, private_recipients, result)
        self._finish_active_run(run_key)

    def _persona_listener(self, persona: dict[str, Any]) -> None:
        registration = persona["client"].register_message_queue()
        queue_id = registration["queue_id"]
        last_event_id = int(registration["last_event_id"])
        print(
            f"Listening for persona {persona['slug']} ({persona['display_name']}) "
            f"in DMs and streams {persona['allowed_streams']}..."
        )

        while True:
            response = persona["client"].get_events(queue_id, last_event_id, self.poll_timeout_seconds)
            for event in response.get("events", []):
                last_event_id = int(event["id"])
                if event.get("type") != "message":
                    continue
                self._handle_message(persona, event["message"])

    def _handle_message(self, persona: dict[str, Any], message: dict[str, Any]) -> None:
        if message.get("sender_email") in self.all_persona_emails:
            return

        route = self._route_for_message(persona, message)
        if route is None:
            return
        scope_name, topic, private_recipients = route

        message_id = int(message["id"])
        processed_ids = persona["state"].setdefault("processed_message_ids", [])
        if message_id in processed_ids:
            return

        sender = message.get("sender_full_name") or message.get("sender_email") or "human"
        content = strip_html(message.get("content") or "")
        if not content:
            processed_ids.append(message_id)
            self._save_runtime_state(persona)
            return

        topic_dir, topic_state = self._conversation_state(persona, scope_name, topic)
        self._append_history(persona, topic_state, role="human", sender=sender, content=content, message_id=message_id)
        self._write_transcript(persona, topic_dir, topic_state)
        run_key = self._run_key(persona["slug"], scope_name, topic)
        lowered = content.lstrip().lower()

        if lowered.startswith("/help"):
            response = self._reply_for_help(persona)
            self._append_history(persona, topic_state, role="persona", sender=persona["display_name"], content=response)
            self._write_transcript(persona, topic_dir, topic_state)
            self._reply(persona, message, scope_name, topic, private_recipients, response)
            processed_ids.append(message_id)
            self._save_runtime_state(persona)
            return

        if lowered.startswith("/status"):
            status = self._active_status(run_key)
            if status is None:
                response = f"{persona['display_name']} status: idle on this thread."
            else:
                phase = status.get("phase", "unknown")
                started_at = status.get("started_at", "unknown")
                stop_requested = bool(status.get("stop_requested"))
                stop_line = "\n\nStop requested: yes" if stop_requested else ""
                response = f"{persona['display_name']} status: `{phase}`\n\nStarted: {started_at}{stop_line}"
            self._append_history(persona, topic_state, role="persona", sender=persona["display_name"], content=response)
            self._write_transcript(persona, topic_dir, topic_state)
            self._reply(persona, message, scope_name, topic, private_recipients, response)
            processed_ids.append(message_id)
            self._save_runtime_state(persona)
            return

        if lowered.startswith("/stop"):
            stopped = self._request_stop(run_key)
            response = (
                f"{persona['display_name']} stop request accepted for this thread."
                if stopped
                else f"{persona['display_name']} has no active run to stop on this thread."
            )
            self._append_history(persona, topic_state, role="persona", sender=persona["display_name"], content=response)
            self._write_transcript(persona, topic_dir, topic_state)
            self._reply(persona, message, scope_name, topic, private_recipients, response)
            processed_ids.append(message_id)
            self._save_runtime_state(persona)
            return

        if not self._start_active_run(run_key, persona_name=persona["display_name"], scope_name=scope_name, topic=topic):
            response = (
                f"{persona['display_name']} is already working on this thread. "
                "Use `/status` to inspect progress or `/stop` to cancel the current run."
            )
            self._append_history(persona, topic_state, role="persona", sender=persona["display_name"], content=response)
            self._write_transcript(persona, topic_dir, topic_state)
            self._reply(persona, message, scope_name, topic, private_recipients, response)
            processed_ids.append(message_id)
            self._save_runtime_state(persona)
            return

        if self.send_acknowledgement:
            ack = f"{persona['display_name']} received this message and is starting a threaded run."
            self._reply(persona, message, scope_name, topic, private_recipients, ack)

        worker = threading.Thread(
            target=self._run_topic_work,
            args=(persona, message, scope_name, topic, private_recipients, topic_dir, topic_state, run_key),
            daemon=True,
        )
        worker.start()

        processed_ids.append(message_id)
        self._save_runtime_state(persona)

    def serve_forever(self) -> None:
        threads: list[threading.Thread] = []
        for persona in self.personas.values():
            worker = threading.Thread(target=self._persona_listener, args=(persona,), daemon=True)
            worker.start()
            threads.append(worker)
        while True:
            for worker in threads:
                if not worker.is_alive():
                    raise RuntimeError("A persona listener thread exited unexpectedly.")
            time.sleep(1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared Zulip multi-bot persona bridge")
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
