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


def validate_project_workspace(path: pathlib.Path) -> None:
    if contains_template_placeholder(str(path)):
        raise RuntimeError(f"Replace template placeholders in project workspace path: {path}")
    if not path.exists():
        raise RuntimeError(f"Project workspace does not exist: {path}")
    if not (path / "PROJECT.md").exists():
        raise RuntimeError(f"Missing PROJECT.md in project workspace: {path / 'PROJECT.md'}")


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
        software_workspace_value = raw_config.get("software_workspace")
        self.software_workspace = (
            resolve_path(self.config_dir, software_workspace_value)
            if software_workspace_value
            else None
        )
        project_registry_value = raw_config.get("project_registry_path")
        self.project_registry_path = (
            resolve_path(self.config_dir, project_registry_value)
            if project_registry_value
            else None
        )
        self.default_project_slug = raw_config.get("default_project_slug")
        self.software_run_command = raw_config.get("software_run_command", ["bash", ".agents/run_team.sh"])
        self.state_dir = resolve_path(self.config_dir, raw_config.get("state_dir", "./state"))
        self.verify_tls = bool(raw_config.get("verify_tls", False))
        self.poll_timeout_seconds = int(raw_config.get("poll_timeout_seconds", 30))
        self.history_entry_limit = int(raw_config.get("history_entry_limit", 20))
        self.send_acknowledgement = bool(raw_config.get("send_acknowledgement", True))
        self.project_registry = self._load_project_registry()

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

    def _load_project_registry(self) -> dict[str, Any] | None:
        if self.project_registry_path is None:
            return None
        if contains_template_placeholder(str(self.project_registry_path)):
            raise RuntimeError(
                "Replace the project_registry_path placeholder in the bridge config."
            )
        if not self.project_registry_path.exists():
            raise RuntimeError(f"Project registry does not exist: {self.project_registry_path}")

        raw_registry = load_json(self.project_registry_path)
        raw_projects = raw_registry.get("projects")
        if not isinstance(raw_projects, dict) or not raw_projects:
            raise RuntimeError("Project registry must define a non-empty 'projects' mapping.")

        projects: dict[str, dict[str, Any]] = {}
        for slug, entry in raw_projects.items():
            if contains_template_placeholder(slug):
                raise RuntimeError(f"Replace template placeholders in project slug: {slug}")
            if not isinstance(entry, dict):
                raise RuntimeError(f"Project registry entry for {slug} must be an object.")
            workspace_value = entry.get("workspace")
            if not workspace_value:
                raise RuntimeError(f"Project registry entry for {slug} is missing 'workspace'.")
            workspace = resolve_path(self.project_registry_path.parent, workspace_value)
            projects[slug] = {
                "slug": slug,
                "display_name": entry.get("display_name") or slug,
                "description": entry.get("description", ""),
                "workspace": workspace,
            }

        default_slug = self.default_project_slug or raw_registry.get("default_project")
        if default_slug is not None and default_slug not in projects:
            raise RuntimeError(f"Default project '{default_slug}' is not present in the registry.")

        return {
            "default_project": default_slug,
            "projects": projects,
        }

    def check(self) -> None:
        if contains_template_placeholder(self.stream_name):
            raise RuntimeError("Replace the stream_name placeholder in the bridge config.")
        if self.software_workspace is not None and self.project_registry is not None:
            raise RuntimeError(
                "Configure either software_workspace or project_registry_path, not both."
            )
        if self.software_workspace is None and self.project_registry is None:
            raise RuntimeError(
                "Configure software_workspace for single-project mode or project_registry_path for multi-project mode."
            )
        if len(self.software_run_command) < 2:
            raise RuntimeError("software_run_command must include the executable and script path")
        if self.software_workspace is not None:
            validate_project_workspace(self.software_workspace)
            run_script = self.software_workspace / self.software_run_command[1]
            if not run_script.exists():
                raise RuntimeError(f"Missing software team run script: {run_script}")
        if self.project_registry is not None:
            for slug, entry in self.project_registry["projects"].items():
                validate_project_workspace(entry["workspace"])
                run_script = entry["workspace"] / self.software_run_command[1]
                if not run_script.exists():
                    raise RuntimeError(f"Missing software team run script for {slug}: {run_script}")
        print("Bridge config OK")
        print(f"- stream: {self.stream_name}")
        if self.software_workspace is not None:
            print(f"- software workspace: {self.software_workspace}")
        if self.project_registry is not None:
            print(f"- project registry: {self.project_registry_path}")
            print(f"- default project: {self.project_registry['default_project']}")
            print(f"- registered projects: {', '.join(sorted(self.project_registry['projects'].keys()))}")
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

    def _parse_project_command(self, content: str) -> tuple[str, str | None] | None:
        stripped = content.strip()
        if not stripped.lower().startswith("/project"):
            return None
        parts = stripped.split()
        if len(parts) == 1:
            return "status", None
        action = parts[1].lower()
        argument = " ".join(parts[2:]).strip() or None
        return action, argument

    def _project_command_response(self, topic_state: dict[str, Any], action: str, argument: str | None) -> str:
        if self.project_registry is None:
            if action == "status":
                assert self.software_workspace is not None
                return (
                    "Bridge project mode: single project\n\n"
                    f"Workspace: `{self.software_workspace}`\n"
                    "Project selection commands are unavailable because no multi-project registry is configured."
                )
            return "Project selection commands are unavailable because no multi-project registry is configured."

        projects = self.project_registry["projects"]
        default_slug = self.project_registry["default_project"]

        if action == "list":
            lines = ["Registered projects:"]
            for slug in sorted(projects):
                entry = projects[slug]
                suffix = " (default)" if slug == default_slug else ""
                description = entry.get("description", "")
                detail = f" - {description}" if description else ""
                lines.append(f"- `{slug}` -> `{entry['workspace']}`{suffix}{detail}")
            lines.append("")
            lines.append("Commands: `/project use <slug>`, `/project status`, `/project clear`")
            return "\n".join(lines)

        if action == "use":
            if not argument:
                return "Usage: `/project use <slug>`"
            entry = projects.get(argument)
            if entry is None:
                return f"Unknown project slug `{argument}`. Use `/project list`."
            topic_state["selected_project_slug"] = argument
            return (
                f"Selected project `{argument}` for this topic.\n\n"
                f"Workspace: `{entry['workspace']}`"
            )

        if action == "status":
            selected_slug = topic_state.get("selected_project_slug")
            if selected_slug:
                entry = projects.get(selected_slug)
                if entry is None:
                    return (
                        f"This topic still references unknown project `{selected_slug}`.\n\n"
                        "Use `/project list` and `/project use <slug>` to repair it."
                    )
                return (
                    f"Current topic project: `{selected_slug}`\n\n"
                    f"Workspace: `{entry['workspace']}`\n"
                    f"Default project: `{default_slug}`"
                )
            if default_slug:
                entry = projects[default_slug]
                return (
                    "No topic-specific project is selected.\n\n"
                    f"Default project: `{default_slug}`\n"
                    f"Workspace: `{entry['workspace']}`"
                )
            return "No project is selected for this topic. Use `/project list` and `/project use <slug>`."

        if action == "clear":
            cleared = topic_state.pop("selected_project_slug", None)
            if cleared:
                return f"Cleared topic-specific project selection `{cleared}`."
            return "This topic did not have a topic-specific project selection."

        return "Unknown project command. Use `/project list`, `/project use <slug>`, `/project status`, or `/project clear`."

    def _resolve_project_context(self, topic_state: dict[str, Any]) -> tuple[str | None, pathlib.Path]:
        if self.project_registry is None:
            assert self.software_workspace is not None
            validate_project_workspace(self.software_workspace)
            return None, self.software_workspace

        selected_slug = topic_state.get("selected_project_slug") or self.project_registry["default_project"]
        if not selected_slug:
            raise RuntimeError(
                "No project is selected for this topic. Use `/project list` and `/project use <slug>` before requesting software work."
            )

        entry = self.project_registry["projects"].get(selected_slug)
        if entry is None:
            raise RuntimeError(
                f"Selected project `{selected_slug}` is not present in the registry. Use `/project list` and `/project use <slug>`."
            )
        validate_project_workspace(entry["workspace"])
        return selected_slug, entry["workspace"]

    def _build_prompt(
        self,
        stream_name: str,
        topic: str,
        topic_state: dict[str, Any],
        project_slug: str | None,
        project_workspace: pathlib.Path,
    ) -> str:
        transcript = self._format_recent_history(topic_state)
        project_line = (
            f"Selected project slug: {project_slug}\n" if project_slug is not None else ""
        )
        return (
            "Handle the following Zulip software task thread.\n\n"
            f"Stream: {stream_name}\n"
            f"Topic: {topic}\n"
            f"{project_line}"
            f"Host project workspace: {project_workspace}\n"
            "Sandbox workspace path: /workspace\n\n"
            "Instructions:\n"
            "- Use PROJECT.md and management/ in the selected project workspace as the current source of truth.\n"
            "- Inside the OpenClaw sandbox, the repository root is /workspace.\n"
            "- Use repo-root-relative paths or /workspace/... paths only in assignments and summaries.\n"
            "- Treat the transcript below as the current task thread.\n"
            "- Continue the software work for this Zulip topic.\n"
            "- Return a concise manager summary suitable for posting back into Zulip.\n\n"
            "THREAD_TRANSCRIPT:\n"
            f"{transcript}"
        )

    def _run_software_team(
        self,
        stream_name: str,
        topic: str,
        topic_state: dict[str, Any],
        project_slug: str | None,
        project_workspace: pathlib.Path,
    ) -> str:
        prompt = self._build_prompt(stream_name, topic, topic_state, project_slug, project_workspace)
        command = list(self.software_run_command) + [prompt]
        completed = subprocess.run(
            command,
            cwd=project_workspace,
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

        project_command = self._parse_project_command(content)
        if project_command is not None:
            action, argument = project_command
            response = self._project_command_response(topic_state, action, argument)
            self._append_history(
                topic_state,
                role="manager",
                sender=self.bot_email,
                content=response,
            )
            self._write_transcript(topic_dir, topic_state)
            self.client.send_stream_message(stream_name, topic, response)
            processed_ids.append(message_id)
            self._save_state()
            return

        try:
            project_slug, project_workspace = self._resolve_project_context(topic_state)
        except Exception as exc:
            error_text = f"Software manager cannot start this topic.\n\n```text\n{exc}\n```"
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

        if self.send_acknowledgement:
            if project_slug is None:
                ack = "Software manager received this task and is starting a run in the configured single project workspace."
            else:
                ack = f"Software manager received this task and is starting a run for project `{project_slug}`."
            self.client.send_stream_message(stream_name, topic, ack)

        try:
            result = self._run_software_team(
                stream_name,
                topic,
                topic_state,
                project_slug,
                project_workspace,
            )
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
