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
    return slug or "thread"


def thread_storage_dir(state_dir: pathlib.Path, scope_name: str, topic: str) -> pathlib.Path:
    thread_hash = hashlib.sha1(f"{scope_name}:{topic}".encode()).hexdigest()[:10]
    return state_dir / "threads" / f"{slugify(topic)}-{thread_hash}"


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


def normalize_agent_token(value: str) -> str:
    cleaned = strip_html(value or "")
    cleaned = re.sub(r"[@*`_]", "", cleaned).strip().lower()
    cleaned = cleaned.replace(" ", "-")
    cleaned = re.sub(r"[^a-z0-9_-]+", "", cleaned)
    return cleaned


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


class Gateway:
    def __init__(self, config_path: pathlib.Path) -> None:
        self.config_path = config_path.resolve()
        self.config_dir = self.config_path.parent
        raw_config = load_json(self.config_path)

        registry_value = raw_config.get("agent_registry_path")
        if not registry_value:
            raise RuntimeError("agent_registry_path is required.")

        self.agent_registry_path = resolve_path(self.config_dir, registry_value)
        self.state_dir = resolve_path(self.config_dir, raw_config.get("state_dir", "./state"))
        self.verify_tls = bool(raw_config.get("verify_tls", False))
        self.poll_timeout_seconds = int(raw_config.get("poll_timeout_seconds", 15))
        self.history_entry_limit = int(raw_config.get("history_entry_limit", 20))
        self.send_acknowledgement = bool(raw_config.get("send_acknowledgement", True))
        self.send_status_updates = bool(raw_config.get("send_status_updates", True))

        ensure_dir(self.state_dir)
        ensure_dir(self.state_dir / "threads")
        ensure_dir(self.state_dir / "agents")

        self.agents = self._load_agent_registry()
        self.agent_email_to_slug = {agent["email"]: slug for slug, agent in self.agents.items()}
        self.agent_lookup = self._build_agent_lookup()
        self.active_runs: dict[str, dict[str, Any]] = {}
        self.active_runs_lock = threading.Lock()
        self.thread_lock = threading.Lock()

    def _load_runtime_state(self, state_path: pathlib.Path) -> dict[str, Any]:
        if not state_path.exists():
            return {"processed_message_ids": []}
        payload = load_json(state_path)
        payload.setdefault("processed_message_ids", [])
        return payload

    def _save_runtime_state(self, agent: dict[str, Any]) -> None:
        with agent["state_lock"]:
            processed = agent["state"].get("processed_message_ids", [])
            agent["state"]["processed_message_ids"] = processed[-1000:]
            save_json(agent["state_path"], agent["state"])

    def _build_agent_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for slug, agent in self.agents.items():
            lookup[normalize_agent_token(slug)] = slug
            lookup[normalize_agent_token(agent["display_name"])] = slug
            lookup[normalize_agent_token(agent["email"].split("@", 1)[0])] = slug
            for trigger in agent["mention_triggers"]:
                lookup[normalize_agent_token(trigger)] = slug
        return lookup

    def _load_agent_registry(self) -> dict[str, dict[str, Any]]:
        if contains_template_placeholder(str(self.agent_registry_path)):
            raise RuntimeError("Replace the agent_registry_path placeholder in the gateway config.")
        if not self.agent_registry_path.exists():
            raise RuntimeError(f"Agent registry does not exist: {self.agent_registry_path}")

        raw_registry = load_json(self.agent_registry_path)
        raw_agents = raw_registry.get("agents")
        if not isinstance(raw_agents, dict) or not raw_agents:
            raise RuntimeError("Agent registry must define a non-empty 'agents' mapping.")

        agents: dict[str, dict[str, Any]] = {}
        for slug, entry in raw_agents.items():
            if contains_template_placeholder(slug):
                raise RuntimeError(f"Replace template placeholders in agent slug: {slug}")
            if not isinstance(entry, dict):
                raise RuntimeError(f"Agent registry entry for {slug} must be an object.")

            display_name = entry.get("display_name") or slug
            zuliprc_value = entry.get("zuliprc_path")
            workspace_value = entry.get("workspace")
            run_command = entry.get("run_command")
            allowed_streams = entry.get("allowed_streams", [])
            reply_mode = entry.get("reply_mode", "dm_or_mention")
            loops = entry.get("loops", [])
            skills = entry.get("skills", [])
            can_handoff_to = entry.get("can_handoff_to", [])

            if contains_template_placeholder(display_name):
                raise RuntimeError(f"Replace template placeholders in display_name for {slug}.")
            if not zuliprc_value:
                raise RuntimeError(f"Agent {slug} is missing zuliprc_path.")
            if not workspace_value:
                raise RuntimeError(f"Agent {slug} is missing workspace.")
            if not isinstance(run_command, list) or len(run_command) < 2:
                raise RuntimeError(f"Agent {slug} must define run_command with at least executable and script.")
            if not isinstance(allowed_streams, list):
                raise RuntimeError(f"Agent {slug} allowed_streams must be a list.")
            if reply_mode not in {"dm_only", "dm_or_mention", "mention_only", "always"}:
                raise RuntimeError(f"Agent {slug} has invalid reply_mode: {reply_mode}")
            if not isinstance(loops, list) or not all(isinstance(item, str) for item in loops):
                raise RuntimeError(f"Agent {slug} loops must be a list of strings.")
            if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
                raise RuntimeError(f"Agent {slug} skills must be a list of strings.")
            if not isinstance(can_handoff_to, list) or not all(isinstance(item, str) for item in can_handoff_to):
                raise RuntimeError(f"Agent {slug} can_handoff_to must be a list of strings.")

            zuliprc = load_zuliprc(resolve_path(self.agent_registry_path.parent, zuliprc_value))
            workspace = resolve_path(self.agent_registry_path.parent, workspace_value)
            state_dir = self.state_dir / "agents" / slug
            ensure_dir(state_dir)
            state_path = state_dir / "agent_state.json"

            mention_triggers = entry.get("mention_triggers") or []
            if not mention_triggers:
                mention_triggers = [slug, display_name, zuliprc["email"].split("@", 1)[0]]

            agents[slug] = {
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
                "loops": list(loops),
                "skills": list(skills),
                "can_handoff_to": [str(item).strip().lower() for item in can_handoff_to if str(item).strip()],
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

        return agents

    def check(self) -> None:
        for slug, agent in sorted(self.agents.items()):
            if contains_template_placeholder(str(agent["workspace"])):
                raise RuntimeError(f"Replace template placeholders in workspace for agent {slug}.")
            if not agent["workspace"].exists():
                raise RuntimeError(f"Workspace does not exist for agent {slug}: {agent['workspace']}")
            run_script = agent["workspace"] / agent["run_command"][1]
            if not run_script.exists():
                raise RuntimeError(f"Missing run script for agent {slug}: {run_script}")
            print(
                f"OK: {slug} -> email={agent['email']} workspace={agent['workspace']} "
                f"reply_mode={agent['reply_mode']} loops={agent['loops']} "
                f"handoffs={agent['can_handoff_to']}"
            )
        print("V3 gateway config OK")
        print(f"- registry: {self.agent_registry_path}")
        print(f"- state dir: {self.state_dir}")
        print(f"- agents: {', '.join(sorted(self.agents))}")

    def _run_key(self, slug: str, scope_name: str, topic: str) -> str:
        return f"{slug}::{scope_name}::{topic}"

    def _start_active_run(self, run_key: str, *, agent_name: str, scope_name: str, topic: str) -> bool:
        with self.active_runs_lock:
            if run_key in self.active_runs:
                return False
            self.active_runs[run_key] = {
                "agent_name": agent_name,
                "scope": scope_name,
                "topic": topic,
                "phase": "queued",
                "started_at": now_iso(),
                "process": None,
                "stop_requested": False,
                "last_status_text": f"{agent_name} status: queued for this thread.",
                "last_status_at": now_iso(),
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

    def _record_active_status(
        self,
        run_key: str,
        *,
        phase: str | None = None,
        status_text: str | None = None,
    ) -> None:
        with self.active_runs_lock:
            run = self.active_runs.get(run_key)
            if run is None:
                return
            if phase is not None:
                run["phase"] = phase
            if status_text is not None:
                run["last_status_text"] = status_text
                run["last_status_at"] = now_iso()

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
            run["last_status_text"] = "Stop has been requested for this thread."
            run["last_status_at"] = now_iso()
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
        scope_name: str,
        topic: str,
        *,
        delivery_type: str,
        private_recipients: list[str] | None,
    ) -> tuple[pathlib.Path, dict[str, Any]]:
        with self.thread_lock:
            thread_dir = thread_storage_dir(self.state_dir, scope_name, topic)
            ensure_dir(thread_dir)
            state_path = thread_dir / "thread_state.json"
            if state_path.exists():
                thread_state = load_json(state_path)
            else:
                thread_state = {
                    "scope": scope_name,
                    "topic": topic,
                    "mode": delivery_type,
                    "participants": [],
                    "current_speaker": None,
                    "awaiting_from": None,
                    "active_run_id": None,
                    "private_recipients": [],
                    "history": [],
                }
            thread_state["scope"] = scope_name
            thread_state["topic"] = topic
            thread_state["mode"] = delivery_type
            thread_state["private_recipients"] = list(private_recipients or [])
            thread_state.setdefault("participants", [])
            thread_state.setdefault("history", [])
            thread_state.setdefault("current_speaker", None)
            thread_state.setdefault("awaiting_from", None)
            thread_state.setdefault("active_run_id", None)
            thread_state.setdefault("last_handoff", None)
            return thread_dir, thread_state

    def _save_thread_state(self, thread_dir: pathlib.Path, thread_state: dict[str, Any]) -> None:
        with self.thread_lock:
            save_json(thread_dir / "thread_state.json", thread_state)
            lines: list[str] = [f"# Transcript for {thread_state['scope']} / {thread_state['topic']}", ""]
            for entry in thread_state.get("history", []):
                entry_type = entry.get("entry_type", "message").upper()
                header = f"{entry_type} | {entry['sender']} | {entry['timestamp']}"
                lines.append(f"## {header}")
                if entry.get("message_id") is not None:
                    lines.append(f"message_id: {entry['message_id']}")
                if entry.get("sender_slug"):
                    lines.append(f"sender_slug: {entry['sender_slug']}")
                lines.append("")
                lines.append(entry["content"].strip())
                lines.append("")
            (thread_dir / "transcript.md").write_text("\n".join(lines).strip() + "\n")

    def _add_participant(self, thread_state: dict[str, Any], participant: str) -> None:
        cleaned = participant.strip()
        if cleaned and cleaned not in thread_state["participants"]:
            thread_state["participants"].append(cleaned)

    def _has_recent_duplicate(
        self,
        thread_state: dict[str, Any],
        *,
        sender: str,
        content: str,
    ) -> bool:
        normalized = content.strip()
        for entry in reversed(thread_state.get("history", [])[-8:]):
            if entry.get("sender") == sender and entry.get("content", "").strip() == normalized:
                return True
        return False

    def _history_key(self, entry: dict[str, Any]) -> tuple[Any, ...]:
        return (
            entry.get("entry_type"),
            entry.get("sender"),
            entry.get("sender_slug"),
            entry.get("message_id"),
            entry.get("content"),
        )

    def _append_history(
        self,
        thread_state: dict[str, Any],
        *,
        entry_type: str,
        sender: str,
        content: str,
        sender_slug: str | None = None,
        message_id: int | None = None,
    ) -> None:
        entry = {
            "timestamp": now_iso(),
            "entry_type": entry_type,
            "sender": sender,
            "content": content,
        }
        if sender_slug:
            entry["sender_slug"] = sender_slug
        if message_id is not None:
            entry["message_id"] = message_id
        thread_state.setdefault("history", []).append(entry)
        thread_state["history"] = thread_state["history"][-300:]

    def _merge_thread_context(self, target_thread_state: dict[str, Any], source_thread_state: dict[str, Any]) -> None:
        seen = {self._history_key(entry) for entry in target_thread_state.get("history", [])}
        for entry in source_thread_state.get("history", []):
            key = self._history_key(entry)
            if key in seen:
                continue
            target_thread_state.setdefault("history", []).append(dict(entry))
            seen.add(key)
        target_thread_state["history"] = target_thread_state["history"][-300:]
        for participant in source_thread_state.get("participants", []):
            self._add_participant(target_thread_state, participant)

    def _format_recent_history(self, thread_state: dict[str, Any]) -> str:
        entries = list(thread_state.get("history", [])[-self.history_entry_limit :])
        blocks: list[str] = []
        for entry in entries:
            sender_slug = f" [{entry['sender_slug']}]" if entry.get("sender_slug") else ""
            header = f"{entry['entry_type'].upper()} | {entry['sender']}{sender_slug} | {entry['timestamp']}"
            blocks.append(f"{header}\n{entry['content'].strip()}")
        return "\n\n".join(blocks)

    def _build_prompt(
        self,
        agent: dict[str, Any],
        thread_state: dict[str, Any],
    ) -> str:
        transcript = self._format_recent_history(thread_state)
        can_handoff_to = ", ".join(agent["can_handoff_to"]) or "none"
        skills = ", ".join(agent["skills"]) or "none"
        loops = ", ".join(agent["loops"]) or "none"
        participants = ", ".join(thread_state.get("participants", [])) or "unknown"
        latest_handoff = thread_state.get("last_handoff") or {}
        latest_handoff_block = ""
        if latest_handoff:
            latest_handoff_block = (
                "LATEST_HANDOFF:\n"
                f"- from: {latest_handoff.get('from', 'unknown')}\n"
                f"- to: {latest_handoff.get('to', 'unknown')}\n"
                f"- project: {latest_handoff.get('project', 'n/a')}\n"
                f"- summary: {latest_handoff.get('summary', '')}\n"
                f"- next: {latest_handoff.get('next', '')}\n\n"
            )
        description_line = ""
        if agent["description"]:
            description_line = f"- Description: {agent['description']}\n"
        extra_line = ""
        if agent["bridge_instructions"]:
            extra_line = f"- Extra bridge instructions: {agent['bridge_instructions']}\n"
        return (
            "Handle the following Zulip conversation as the named visible agent.\n\n"
            f"Agent slug: {agent['slug']}\n"
            f"Agent display name: {agent['display_name']}\n"
            f"Host workspace: {agent['workspace']}\n"
            f"Conversation mode: {thread_state['mode']}\n"
            f"Conversation scope: {thread_state['scope']}\n"
            f"Conversation topic: {thread_state['topic']}\n"
            f"Participants: {participants}\n"
            f"Current speaker: {thread_state.get('current_speaker') or 'none'}\n"
            f"Awaiting from: {thread_state.get('awaiting_from') or 'none'}\n"
            f"Skills: {skills}\n"
            f"Loops: {loops}\n"
            f"Allowed handoffs: {can_handoff_to}\n\n"
            "Instructions:\n"
            f"{description_line}"
            f"{extra_line}"
            "- Reply in the visible voice of this agent.\n"
            "- Use the transcript below as the current shared thread context.\n"
            "- If another visible role should take over, include a visible handoff block using this exact format:\n"
            "  TYPE: HANDOFF\n"
            f"  FROM: {agent['display_name']}\n"
            "  TO: <agent slug or display name>\n"
            "  PROJECT: <project slug or n/a>\n"
            "  SUMMARY: <one concise summary>\n"
            "  NEXT: <what the next agent should do>\n"
            "- Only emit a handoff if another agent should continue the thread now.\n"
            "- Otherwise, reply normally.\n\n"
            f"{latest_handoff_block}"
            "THREAD_TRANSCRIPT:\n"
            f"{transcript}"
        )

    def _extract_private_recipients(self, agent: dict[str, Any], message: dict[str, Any]) -> list[str]:
        recipients: list[str] = []
        display = message.get("display_recipient")
        if isinstance(display, list):
            for entry in display:
                email = entry.get("email")
                if email and email != agent["email"]:
                    recipients.append(email)
        sender_email = message.get("sender_email")
        if sender_email and sender_email != agent["email"] and sender_email not in recipients:
            recipients.append(sender_email)
        return sorted(set(recipients))

    def _private_scope(self, agent: dict[str, Any], message: dict[str, Any]) -> tuple[str, str, list[str]]:
        recipients = self._extract_private_recipients(agent, message)
        display = message.get("display_recipient")
        names: list[str] = []
        if isinstance(display, list):
            for entry in display:
                email = entry.get("email")
                if email and email == agent["email"]:
                    continue
                names.append(entry.get("full_name") or email or "user")
        label = ", ".join(sorted(set(names))) or (message.get("sender_full_name") or "direct-message")
        return f"dm:{agent['slug']}", label, recipients

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

    def _is_agent_invoked(self, agent: dict[str, Any], content: str) -> bool:
        explicit_mentions = re.findall(r"@\*\*([^*]+)\*\*", content)
        if explicit_mentions:
            primary_slug = self._resolve_agent_slug(explicit_mentions[0])
            if primary_slug is not None:
                return agent["slug"] == primary_slug

        plain = strip_html(content).lower()
        summon_match = re.match(r"^\s*/(?:summon|ask)\s+([a-z0-9_-]+)\b", plain)
        if summon_match:
            target = summon_match.group(1)
            trigger_set = {agent["slug"].lower(), *agent["mention_triggers"]}
            if target in trigger_set:
                return True
        for trigger in agent["mention_triggers"]:
            if self._matches_trigger(trigger, plain):
                return True
        return False

    def _extract_handoff(self, content: str) -> dict[str, str] | None:
        lines = content.splitlines()
        capture = False
        block: dict[str, str] = {}
        current_key: str | None = None
        for line in lines:
            stripped = line.strip()
            if not capture:
                if re.match(r"^TYPE:\s*HANDOFF\s*$", stripped, flags=re.IGNORECASE):
                    capture = True
                    block["TYPE"] = "HANDOFF"
                    current_key = "TYPE"
                continue

            if not stripped:
                if "TO" in block:
                    break
                continue

            match = re.match(r"^([A-Z_]+):\s*(.*)$", stripped)
            if match:
                current_key = match.group(1).upper()
                block[current_key] = match.group(2).strip()
                continue

            if current_key in {"SUMMARY", "NEXT"}:
                existing = block.get(current_key, "")
                block[current_key] = f"{existing} {stripped}".strip()
                continue

            break

        if not capture or "TO" not in block:
            return None
        return {
            "type": "HANDOFF",
            "from": block.get("FROM", ""),
            "to": block.get("TO", ""),
            "project": block.get("PROJECT", "n/a"),
            "summary": block.get("SUMMARY", ""),
            "next": block.get("NEXT", ""),
        }

    def _truncate_after_handoff(self, content: str) -> str:
        lines = content.splitlines()
        capture = False
        block: dict[str, str] = {}
        current_key: str | None = None
        last_idx: int | None = None

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not capture:
                if re.match(r"^TYPE:\s*HANDOFF\s*$", stripped, flags=re.IGNORECASE):
                    capture = True
                    block["TYPE"] = "HANDOFF"
                    current_key = "TYPE"
                    last_idx = idx
                continue

            if not stripped:
                if "TO" in block and last_idx is not None:
                    return "\n".join(lines[: last_idx + 1]).strip()
                continue

            match = re.match(r"^([A-Z_]+):\s*(.*)$", stripped)
            if match:
                current_key = match.group(1).upper()
                block[current_key] = match.group(2).strip()
                last_idx = idx
                continue

            if current_key in {"SUMMARY", "NEXT"}:
                existing = block.get(current_key, "")
                block[current_key] = f"{existing} {stripped}".strip()
                last_idx = idx
                continue

            if last_idx is not None:
                return "\n".join(lines[: last_idx + 1]).strip()
            break

        if capture and last_idx is not None:
            return "\n".join(lines[: last_idx + 1]).strip()
        return content.strip()

    def _resolve_agent_slug(self, value: str) -> str | None:
        token = normalize_agent_token(value)
        if not token:
            return None
        return self.agent_lookup.get(token)

    def _should_process_stream_message(
        self,
        agent: dict[str, Any],
        thread_state: dict[str, Any],
        content: str,
        sender_is_agent: bool,
    ) -> bool:
        lowered = strip_html(content).lstrip().lower()
        run_key = self._run_key(agent["slug"], thread_state["scope"], thread_state["topic"])
        active_status = self._active_status(run_key)
        if lowered.startswith("/status") or lowered.startswith("/stop") or lowered.startswith("/help"):
            if active_status is not None or thread_state.get("awaiting_from") == agent["slug"]:
                return True
        if sender_is_agent:
            return False
        if thread_state.get("awaiting_from") == agent["slug"]:
            return True
        if agent["reply_mode"] == "always":
            return True
        if agent["reply_mode"] == "dm_only":
            return False
        return self._is_agent_invoked(agent, content)

    def _route_for_message(
        self,
        agent: dict[str, Any],
        message: dict[str, Any],
    ) -> tuple[pathlib.Path, dict[str, Any]] | None:
        sender_email = message.get("sender_email") or ""
        sender_is_agent = sender_email in self.agent_email_to_slug
        message_type = message.get("type")
        if message_type == "private":
            if not agent["allow_dm"]:
                return None
            scope_name, topic, recipients = self._private_scope(agent, message)
            return self._conversation_state(scope_name, topic, delivery_type="dm", private_recipients=recipients)
        if message_type == "stream":
            stream_name = self._stream_name_from_message(message)
            if stream_name is None or stream_name not in agent["allowed_streams"]:
                return None
            topic = message.get("topic") or message.get("subject") or "discussion"
            thread_dir, thread_state = self._conversation_state(
                stream_name,
                topic,
                delivery_type="stream",
                private_recipients=None,
            )
            content = message.get("content") or ""
            if not self._should_process_stream_message(agent, thread_state, content, sender_is_agent):
                return None
            return thread_dir, thread_state
        return None

    def _reply(self, agent: dict[str, Any], thread_state: dict[str, Any], content: str) -> None:
        if thread_state.get("mode") == "dm":
            recipients = list(thread_state.get("private_recipients") or [])
            agent["client"].send_private_message(recipients, content)
            return
        agent["client"].send_stream_message(thread_state["scope"], thread_state["topic"], content)

    def _post_agent_message(
        self,
        agent: dict[str, Any],
        thread_dir: pathlib.Path,
        thread_state: dict[str, Any],
        content: str,
        *,
        entry_type: str = "agent",
        update_active_run: str | None = None,
    ) -> None:
        if update_active_run is not None:
            self._record_active_status(update_active_run, status_text=content)
        self._reply(agent, thread_state, content)
        if not self._has_recent_duplicate(thread_state, sender=agent["display_name"], content=content):
            self._append_history(
                thread_state,
                entry_type=entry_type,
                sender=agent["display_name"],
                sender_slug=agent["slug"],
                content=content,
            )
        self._add_participant(thread_state, agent["display_name"])
        self._save_thread_state(thread_dir, thread_state)

    def _run_command(self, agent: dict[str, Any], prompt: str, run_key: str) -> str:
        session_seed = f"{agent['slug']}::{run_key}"
        session_hash = hashlib.sha1(session_seed.encode()).hexdigest()[:24]
        session_id = f"zulip-v3-{agent['slug']}-{session_hash}"
        env = os.environ.copy()
        env["OPENCLAW_SESSION_ID"] = session_id
        process = subprocess.Popen(
            list(agent["run_command"]) + [prompt],
            cwd=agent["workspace"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
            env=env,
        )
        self._set_active_process(run_key, process)
        stdout, stderr = process.communicate()
        self._set_active_process(run_key, None)
        if self._is_stop_requested(run_key):
            raise InterruptedError("stopped by user")
        if process.returncode != 0:
            error_text = stderr.strip() or stdout.strip() or "unknown failure"
            raise RuntimeError(f"{agent['display_name']} command failed: {error_text}")
        return stdout.strip()

    def _run_agent(self, agent: dict[str, Any], thread_state: dict[str, Any], run_key: str) -> str:
        prompt = self._build_prompt(agent, thread_state)
        return self._run_command(agent, prompt, run_key)

    def _reply_for_help(self, agent: dict[str, Any]) -> str:
        streams = ", ".join(agent["allowed_streams"]) if agent["allowed_streams"] else "none"
        loops = ", ".join(agent["loops"]) if agent["loops"] else "none"
        skills = ", ".join(agent["skills"]) if agent["skills"] else "none"
        can_handoff = ", ".join(agent["can_handoff_to"]) if agent["can_handoff_to"] else "none"
        return (
            f"{agent['display_name']} V3 gateway commands:\n\n"
            "- `/help`\n"
            "- `/status`\n"
            "- `/stop`\n\n"
            f"Reply mode: `{agent['reply_mode']}`\n"
            f"DM enabled: `{str(agent['allow_dm']).lower()}`\n"
            f"Allowed streams: {streams}\n"
            f"Loops: {loops}\n"
            f"Skills: {skills}\n"
            f"Can handoff to: {can_handoff}\n\n"
            "Visible handoff format:\n"
            "```text\n"
            "TYPE: HANDOFF\n"
            f"FROM: {agent['display_name']}\n"
            "TO: <agent>\n"
            "PROJECT: <slug or n/a>\n"
            "SUMMARY: <summary>\n"
            "NEXT: <next step>\n"
            "```"
        )

    def _handoff_summary_text(self, source_agent: dict[str, Any], target_agent: dict[str, Any], handoff: dict[str, str]) -> str:
        del handoff
        return (
            f"{target_agent['display_name']} received the handoff from "
            f"{source_agent['display_name']} and is thinking."
        )

    def _thinking_ack_text(self, agent: dict[str, Any]) -> str:
        return f"{agent['display_name']} received your message and is thinking."

    def _launch_handoff(
        self,
        source_agent: dict[str, Any],
        thread_dir: pathlib.Path,
        thread_state: dict[str, Any],
        handoff: dict[str, str],
    ) -> str | None:
        target_slug = self._resolve_agent_slug(handoff.get("to", ""))
        if target_slug is None:
            return f"Gateway rejected the handoff: unknown target `{handoff.get('to', '').strip() or 'unknown'}`."
        if target_slug not in source_agent["can_handoff_to"]:
            return (
                f"Gateway rejected the handoff from {source_agent['display_name']}: "
                f"`{target_slug}` is not in the allowed handoff list."
            )

        target_agent = self.agents[target_slug]
        target_thread_dir = thread_dir
        target_thread_state = thread_state
        if thread_state.get("mode") == "dm" and target_slug != source_agent["slug"]:
            target_scope = f"dm:{target_slug}"
            target_thread_dir, target_thread_state = self._conversation_state(
                target_scope,
                thread_state["topic"],
                delivery_type="dm",
                private_recipients=list(thread_state.get("private_recipients") or []),
            )
            self._merge_thread_context(target_thread_state, thread_state)

        run_key = self._run_key(target_slug, target_thread_state["scope"], target_thread_state["topic"])
        if not self._start_active_run(
            run_key,
            agent_name=target_agent["display_name"],
            scope_name=target_thread_state["scope"],
            topic=target_thread_state["topic"],
        ):
            return (
                f"Gateway skipped the handoff to {target_agent['display_name']}: "
                "that agent is already working on this thread."
            )

        handoff_record = {
            "from": source_agent["slug"],
            "to": target_slug,
            "project": handoff.get("project", "n/a"),
            "summary": handoff.get("summary", ""),
            "next": handoff.get("next", ""),
            "timestamp": now_iso(),
        }
        thread_state["last_handoff"] = dict(handoff_record)
        self._save_thread_state(thread_dir, thread_state)
        target_thread_state["last_handoff"] = dict(handoff_record)
        target_thread_state["awaiting_from"] = target_slug
        target_thread_state["current_speaker"] = target_slug
        target_thread_state["active_run_id"] = run_key
        self._save_thread_state(target_thread_dir, target_thread_state)

        if self.send_acknowledgement:
            self._post_agent_message(
                target_agent,
                target_thread_dir,
                target_thread_state,
                self._handoff_summary_text(source_agent, target_agent, handoff),
                entry_type="status",
                update_active_run=run_key,
            )

        worker = threading.Thread(
            target=self._run_thread_work,
            args=(target_agent, target_thread_dir, run_key),
            daemon=True,
        )
        worker.start()
        return None

    def _run_thread_work(
        self,
        agent: dict[str, Any],
        thread_dir: pathlib.Path,
        run_key: str,
    ) -> None:
        thread_state = load_json(thread_dir / "thread_state.json")
        thread_state["current_speaker"] = agent["slug"]
        thread_state["awaiting_from"] = agent["slug"]
        thread_state["active_run_id"] = run_key
        self._save_thread_state(thread_dir, thread_state)

        try:
            if self.send_status_updates:
                self._set_active_phase(run_key, "thinking")

            result = self._run_agent(agent, thread_state, run_key)
        except InterruptedError:
            result = f"{agent['display_name']} stopped this run on request."
        except Exception as exc:
            if self._is_stop_requested(run_key):
                result = f"{agent['display_name']} stopped this run on request."
            else:
                result = f"{agent['display_name']} run failed.\n\n```text\n{exc}\n```"

        result = self._truncate_after_handoff(result)
        thread_state = load_json(thread_dir / "thread_state.json")
        self._set_active_phase(run_key, "completed")
        thread_state["active_run_id"] = None
        thread_state["current_speaker"] = agent["slug"]
        thread_state["awaiting_from"] = None
        self._post_agent_message(agent, thread_dir, thread_state, result, update_active_run=run_key)
        self._finish_active_run(run_key)

        handoff = self._extract_handoff(result)
        if handoff is None:
            self._save_thread_state(thread_dir, thread_state)
            return

        handoff_error = self._launch_handoff(agent, thread_dir, thread_state, handoff)
        if handoff_error:
            thread_state = load_json(thread_dir / "thread_state.json")
            self._post_agent_message(agent, thread_dir, thread_state, handoff_error, entry_type="status")

    def _elapsed_text(self, started_at: str | None) -> str:
        if not started_at:
            return "unknown"
        try:
            started = dt.datetime.fromisoformat(started_at)
        except ValueError:
            return "unknown"
        seconds = max(0, int((dt.datetime.now(dt.timezone.utc) - started).total_seconds()))
        if seconds < 60:
            return f"~{seconds}s"
        minutes, remaining = divmod(seconds, 60)
        return f"~{minutes}m {remaining}s"

    def _agent_listener(self, agent: dict[str, Any]) -> None:
        registration = agent["client"].register_message_queue()
        queue_id = registration["queue_id"]
        last_event_id = int(registration["last_event_id"])
        print(
            f"Listening for V3 gateway agent {agent['slug']} ({agent['display_name']}) "
            f"in DMs and streams {agent['allowed_streams']}..."
        )
        while True:
            response = agent["client"].get_events(queue_id, last_event_id, self.poll_timeout_seconds)
            for event in response.get("events", []):
                last_event_id = int(event["id"])
                if event.get("type") != "message":
                    continue
                self._handle_message(agent, event["message"])

    def _handle_message(self, agent: dict[str, Any], message: dict[str, Any]) -> None:
        sender_email = message.get("sender_email") or ""
        if sender_email == agent["email"]:
            return

        route = self._route_for_message(agent, message)
        if route is None:
            return
        thread_dir, thread_state = route

        message_id = int(message["id"])
        processed_ids = agent["state"].setdefault("processed_message_ids", [])
        if message_id in processed_ids:
            return

        sender_slug = self.agent_email_to_slug.get(sender_email)
        sender = message.get("sender_full_name") or sender_email or "participant"
        content = strip_html(message.get("content") or "")
        if not content:
            processed_ids.append(message_id)
            self._save_runtime_state(agent)
            return

        if not self._has_recent_duplicate(thread_state, sender=sender, content=content):
            entry_type = "agent" if sender_slug else "human"
            self._append_history(
                thread_state,
                entry_type=entry_type,
                sender=sender,
                sender_slug=sender_slug,
                content=content,
                message_id=message_id,
            )
        self._add_participant(thread_state, sender)
        self._save_thread_state(thread_dir, thread_state)

        run_key = self._run_key(agent["slug"], thread_state["scope"], thread_state["topic"])
        lowered = content.lstrip().lower()

        if lowered.startswith("/help"):
            response = self._reply_for_help(agent)
            self._post_agent_message(agent, thread_dir, thread_state, response)
            processed_ids.append(message_id)
            self._save_runtime_state(agent)
            return

        if lowered.startswith("/status"):
            status = self._active_status(run_key)
            if status is None:
                awaiting = thread_state.get("awaiting_from") or "none"
                current = thread_state.get("current_speaker") or "none"
                response = (
                    f"{agent['display_name']} status: idle on this thread.\n\n"
                    f"Current speaker: `{current}`\n"
                    f"Awaiting from: `{awaiting}`"
                )
            else:
                phase = status.get("phase", "unknown")
                started_at = status.get("started_at", "unknown")
                elapsed = self._elapsed_text(started_at)
                latest_update = status.get("last_status_text")
                stop_requested = bool(status.get("stop_requested"))
                stop_line = "\n\nStop requested: yes" if stop_requested else ""
                latest_line = f"\n\nLatest update:\n{latest_update}" if latest_update else ""
                response = (
                    f"{agent['display_name']} status: `{phase}`\n\nStarted: {started_at}\n"
                    f"Elapsed: {elapsed}{latest_line}{stop_line}"
                )
            self._post_agent_message(agent, thread_dir, thread_state, response)
            processed_ids.append(message_id)
            self._save_runtime_state(agent)
            return

        if lowered.startswith("/stop"):
            stopped = self._request_stop(run_key)
            response = (
                f"{agent['display_name']} stop request accepted for this thread."
                if stopped
                else f"{agent['display_name']} has no active run to stop on this thread."
            )
            self._post_agent_message(agent, thread_dir, thread_state, response)
            processed_ids.append(message_id)
            self._save_runtime_state(agent)
            return

        if not self._start_active_run(
            run_key,
            agent_name=agent["display_name"],
            scope_name=thread_state["scope"],
            topic=thread_state["topic"],
        ):
            status = self._active_status(run_key)
            latest_update = status.get("last_status_text") if status else None
            latest_line = f"\n\nLatest update:\n{latest_update}" if latest_update else ""
            response = (
                f"{agent['display_name']} is already working on this thread. "
                "Use `/status` to inspect progress or `/stop` to cancel the current run."
                f"{latest_line}"
            )
            self._post_agent_message(agent, thread_dir, thread_state, response)
            processed_ids.append(message_id)
            self._save_runtime_state(agent)
            return

        thread_state["current_speaker"] = agent["slug"]
        thread_state["awaiting_from"] = agent["slug"]
        thread_state["active_run_id"] = run_key
        self._save_thread_state(thread_dir, thread_state)

        if self.send_acknowledgement:
            self._post_agent_message(
                agent,
                thread_dir,
                thread_state,
                self._thinking_ack_text(agent),
                entry_type="status",
                update_active_run=run_key,
            )

        worker = threading.Thread(
            target=self._run_thread_work,
            args=(agent, thread_dir, run_key),
            daemon=True,
        )
        worker.start()

        processed_ids.append(message_id)
        self._save_runtime_state(agent)

    def serve_forever(self) -> None:
        threads: list[threading.Thread] = []
        for agent in self.agents.values():
            worker = threading.Thread(target=self._agent_listener, args=(agent,), daemon=True)
            worker.start()
            threads.append(worker)
        while True:
            for worker in threads:
                if not worker.is_alive():
                    raise RuntimeError("A V3 gateway listener thread exited unexpectedly.")
            time.sleep(1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shared Zulip multi-bot V3 gateway")
    parser.add_argument("--config", required=True, help="Path to gateway config JSON")
    parser.add_argument("--check", action="store_true", help="Validate config and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gateway = Gateway(pathlib.Path(args.config))
    if args.check:
        gateway.check()
        return 0
    gateway.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
