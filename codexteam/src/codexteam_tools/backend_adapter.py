from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import opencode_backend
from .turn_metrics import summarize_turn


@dataclass(frozen=True)
class BackendEventSummary:
    thread_ids: tuple[str, ...]
    last_agent_message: str
    completed: bool
    terminal_reason: str | None
    failures: tuple[str, ...]
    parse_errors: tuple[str, ...]


class BackendAdapter(Protocol):
    backend_id: str

    def preflight(self, request: Any, executable: str) -> str | None: ...

    def start_draft(self, request: Any, turn: Any, executable: str) -> list[str]: ...

    def resume_feedback(self, request: Any, turn: Any, executable: str) -> list[str]: ...

    def finalize(self, request: Any, turn: Any, executable: str) -> list[str]: ...

    def environment(self, request: Any) -> dict[str, str]: ...

    def parse_events(self, text: str) -> BackendEventSummary: ...

    def collect_telemetry(self, event_text: str, **inputs: Any) -> dict[str, Any]: ...

    def cleanup(self, request: Any) -> None: ...


class CodexBackendAdapter:
    backend_id = "codex"

    def preflight(self, request: Any, executable: str) -> str | None:
        return None

    def start_draft(self, request: Any, turn: Any, executable: str) -> list[str]:
        prefix = self._prefix(request, executable)
        command = prefix + [
            "exec",
            "--profile",
            request.profile,
            "-c",
            "developer_instructions="
            f"{json.dumps(request.effective_role_policy.developer_instructions)}",
            *request.backend_mcp_args,
            "-C",
            str(request.work_root),
            "--skip-git-repo-check",
            "--json",
            "-o",
            str(turn.message_path),
        ]
        if not request.trust_parent_sandbox:
            command.extend(("-s", request.effective_role_policy.sandbox_mode))
        if request.execution_profile.effective_reasoning is not None:
            command.extend((
                "-c",
                "model_reasoning_effort="
                f"{json.dumps(request.execution_profile.effective_reasoning)}",
            ))
        for directory in request.worker_add_dirs:
            command.extend(("--add-dir", str(directory)))
        command.append("-")
        return command

    def resume_feedback(self, request: Any, turn: Any, executable: str) -> list[str]:
        return self._resume(request, turn, executable)

    def finalize(self, request: Any, turn: Any, executable: str) -> list[str]:
        return self._resume(request, turn, executable)

    def environment(self, request: Any) -> dict[str, str]:
        allowed = {
            "PATH", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
            "SYSTEMROOT", "WINDIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
        }
        environment = {
            name: value for name, value in os.environ.items() if name in allowed
        }
        environment.update({
            "HOME": str(request.codex_home),
            "CODEXTEAM_LAUNCHED_WORKER": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "CODEX_HOME": str(request.execution_codex_home),
            "CODEX_SQLITE_HOME": str(request.codex_home),
        })
        return environment

    def parse_events(self, text: str) -> BackendEventSummary:
        thread_ids: list[str] = []
        messages: list[str] = []
        failures: list[str] = []
        parse_errors: list[str] = []
        completed = False
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"line {line_number}: invalid JSONL event: {exc.msg}")
                continue
            if not isinstance(event, dict):
                parse_errors.append(f"line {line_number}: JSONL event must be an object")
                continue
            event_type = event.get("type")
            if event_type == "thread.started":
                thread_id = event.get("thread_id")
                if isinstance(thread_id, str) and thread_id.strip():
                    thread_ids.append(thread_id.strip())
                else:
                    parse_errors.append(
                        f"line {line_number}: thread.started is missing thread_id"
                    )
            elif event_type == "turn.completed":
                completed = True
            elif event_type in {"turn.failed", "error"}:
                failures.append(_event_failure_text(event))
            elif event_type == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    message = item.get("text")
                    if isinstance(message, str) and message.strip():
                        messages.append(message)
        return BackendEventSummary(
            thread_ids=tuple(dict.fromkeys(thread_ids)),
            last_agent_message=messages[-1] if messages else "",
            completed=completed,
            terminal_reason="completed" if completed else None,
            failures=tuple(failures),
            parse_errors=tuple(parse_errors),
        )

    def collect_telemetry(self, event_text: str, **inputs: Any) -> dict[str, Any]:
        return summarize_turn(event_text, backend=self.backend_id, **inputs)

    def cleanup(self, request: Any) -> None:
        return None

    @staticmethod
    def _prefix(request: Any, executable: str) -> list[str]:
        prefix = [executable]
        if request.trust_parent_sandbox:
            prefix.extend(("-s", "danger-full-access"))
        return prefix

    def _resume(self, request: Any, turn: Any, executable: str) -> list[str]:
        reasoning = request.execution_profile.effective_reasoning
        command = self._prefix(request, executable) + [
            "exec",
            "resume",
            "-m",
            request.model,
            "-c",
            f"model_provider={json.dumps(request.model_provider)}",
            "-c",
            "developer_instructions="
            f"{json.dumps(request.effective_role_policy.developer_instructions)}",
            *request.backend_mcp_args,
            *(
                ["-c", f"model_catalog_json={json.dumps(request.model_catalog_json)}"]
                if request.model_catalog_json
                else []
            ),
            *(
                ["-c", f"model_reasoning_effort={json.dumps(reasoning)}"]
                if reasoning
                else []
            ),
            *(
                ["-c", f"model_verbosity={json.dumps(request.model_verbosity)}"]
                if request.model_verbosity
                else []
            ),
            *(
                [
                    "-c",
                    "sandbox_workspace_write.writable_roots="
                    + json.dumps([str(path) for path in request.worker_add_dirs]),
                ]
                if request.worker_add_dirs
                else []
            ),
            "--skip-git-repo-check",
            "--json",
            "-o",
            str(turn.message_path),
            turn.session["thread_id"],
            "-",
        ]
        return command


class OpenCodeBackendAdapter:
    backend_id = "opencode"

    def preflight(self, request: Any, executable: str) -> str | None:
        return opencode_backend.version(executable)

    def start_draft(self, request: Any, turn: Any, executable: str) -> list[str]:
        return self._command(request, None, executable)

    def resume_feedback(self, request: Any, turn: Any, executable: str) -> list[str]:
        return self._command(request, turn.session["thread_id"], executable)

    def finalize(self, request: Any, turn: Any, executable: str) -> list[str]:
        return self._command(request, turn.session["thread_id"], executable)

    def environment(self, request: Any) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("CODEX_THREAD_ID", None)
        environment["CODEXTEAM_LAUNCHED_WORKER"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for name in tuple(environment):
            if name.startswith("OPENCODE_"):
                environment.pop(name)
        environment.update(
            opencode_backend.environment(
                request.session_dir / "opencode-runtime",
                request.backend_config_path,
            )
        )
        return environment

    def parse_events(self, text: str) -> BackendEventSummary:
        value = opencode_backend.parse_events(text)
        return BackendEventSummary(
            thread_ids=value.thread_ids,
            last_agent_message=value.last_agent_message,
            completed=value.completed,
            terminal_reason=value.terminal_reason,
            failures=value.failures,
            parse_errors=value.parse_errors,
        )

    def collect_telemetry(self, event_text: str, **inputs: Any) -> dict[str, Any]:
        return summarize_turn(event_text, backend=self.backend_id, **inputs)

    def cleanup(self, request: Any) -> None:
        return None

    @staticmethod
    def _command(request: Any, session_id: str | None, executable: str) -> list[str]:
        return opencode_backend.build_command(
            executable=executable,
            workspace=request.work_root,
            model=request.model,
            phase=request.phase,
            feedback_mode=request.feedback_mode,
            session_id=session_id,
            title=f"CodexTeam {request.task_id}/{request.attempt_id}",
            pure=request.execution_profile.profile_id != "qwen38-27b-context",
        )


def adapter_for(backend: str) -> BackendAdapter:
    if backend == "codex":
        return CodexBackendAdapter()
    if backend == "opencode":
        return OpenCodeBackendAdapter()
    raise ValueError(f"unsupported execution backend: {backend}")


def _event_failure_text(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = event.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return str(event.get("type") or "backend failure")
