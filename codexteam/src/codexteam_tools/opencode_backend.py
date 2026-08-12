from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .files import atomic_write_json


PROFILES = {
    "ornith35b": "ollama/ornith:35b",
    "qwen36-27b": "ollama/qwen3.6-27b:latest",
    "muse-glimmer": "ollama/muse-glimmer:30b",
}
OLLAMA_MODELS = {
    "ornith:35b": "Ornith 35B",
    "qwen3.6-27b:latest": "Qwen3.6 27B",
    "muse-glimmer:30b": "Muse Glimmer 30B",
}
AGENT = "codexteam"
FINAL_AGENT = "codexteam-final"
CONFIG_FILENAME = "opencode.json"


@dataclass(frozen=True)
class OpenCodeEventSummary:
    thread_ids: tuple[str, ...]
    last_agent_message: str
    completed: bool
    failures: tuple[str, ...]
    parse_errors: tuple[str, ...]


def resolve_profile(profile: str) -> tuple[str, str]:
    model = PROFILES.get(profile)
    if model is None:
        raise ValueError(
            "OpenCode profile must be one of " + ", ".join(sorted(PROFILES))
        )
    return model, "ollama"


def config_path(runtime_root: Path) -> Path:
    return runtime_root / "xdg-config" / "opencode" / CONFIG_FILENAME


def build_config(
    *,
    model: str,
    role_name: str,
    role_instructions: str,
    project_instructions: str | None = None,
    add_dirs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    provider, separator, model_id = model.partition("/")
    if provider != "ollama" or not separator or model_id not in OLLAMA_MODELS:
        raise ValueError(f"unsupported OpenCode model: {model!r}")
    prompt = (
        f"Act as the CodexTeam {role_name} for one bounded task attempt. "
        "Follow the handoff, pinned guidance paths, role boundaries, and evidence rules. "
        + role_instructions.strip()
    )
    if project_instructions:
        prompt += "\n\nPinned workspace AGENTS.md instructions:\n" + project_instructions.strip()
    external_directories = {"*": "deny"}
    external_directories.update({f"{path}/**": "allow" for path in add_dirs})
    common_permissions = {
        "*": "allow",
        "task": "deny",
        "skill": "deny",
        "lsp": "deny",
        "external_directory": external_directories,
        "question": "deny",
        "webfetch": "deny",
        "websearch": "deny",
    }
    final_permissions = {
        "*": "deny",
        "read": "allow",
        "glob": "allow",
        "grep": "allow",
        "list": "allow",
        "edit": "deny",
        "bash": "deny",
        "webfetch": "deny",
        "websearch": "deny",
    }
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "small_model": model,
        "enabled_providers": ["ollama"],
        "provider": {
            "ollama": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "http://localhost:11434/v1"},
                "models": {
                    model_id: {"name": OLLAMA_MODELS[model_id]},
                },
            }
        },
        "autoupdate": False,
        "share": "disabled",
        "snapshot": False,
        "plugin": [],
        "mcp": {},
        "lsp": False,
        "formatter": False,
        "instructions": [],
        "skills": {"paths": [], "urls": []},
        "subagent_depth": 0,
        "default_agent": AGENT,
        "agent": {
            AGENT: {
                "description": f"CodexTeam {role_name} task worker",
                "mode": "primary",
                "model": model,
                "prompt": prompt,
                "permission": common_permissions,
            },
            FINAL_AGENT: {
                "description": f"Read-only CodexTeam {role_name} finalizer",
                "mode": "primary",
                "model": model,
                "prompt": prompt + " Finalization is read-only; report only accepted evidence.",
                "permission": final_permissions,
            },
        },
    }


def config_digest(config: dict[str, Any]) -> str:
    content = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def write_config(path: Path, config: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"OpenCode config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    atomic_write_json(path, config)
    path.chmod(0o600)


def ensure_config(path: Path, expected_digest: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"attempt-private OpenCode config is missing or unsafe: {path}")
    actual = hashlib.sha256(
        json.dumps(
            json.loads(path.read_text(encoding="utf-8")),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if actual != expected_digest:
        raise ValueError(f"OpenCode config digest mismatch: {path}")


def build_command(
    *,
    executable: str,
    workspace: Path,
    model: str,
    phase: str,
    session_id: str | None,
    title: str,
) -> list[str]:
    command = [
        executable,
        "run",
        "--pure",
        "--format",
        "json",
        "--model",
        model,
        "--agent",
        FINAL_AGENT if phase == "final" else AGENT,
        "--dir",
        str(workspace),
    ]
    if session_id is None:
        command.extend(("--title", title))
    else:
        command.extend(("--session", session_id))
    return command


def environment(runtime_root: Path, path: Path) -> dict[str, str]:
    home = runtime_root / "home"
    data = runtime_root / "xdg-data"
    state = runtime_root / "xdg-state"
    cache = runtime_root / "xdg-cache"
    for directory in (home, data, state, cache):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(path.parents[1]),
        "XDG_DATA_HOME": str(data),
        "XDG_STATE_HOME": str(state),
        "XDG_CACHE_HOME": str(cache),
        "OPENCODE_CONFIG": str(path),
        "OPENCODE_CONFIG_DIR": str(path.parent),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
    }


def version(executable: str) -> str:
    try:
        process = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot determine OpenCode version from {executable!r}: {exc}") from exc
    value = process.stdout.strip()
    if process.returncode != 0 or not value:
        raise ValueError(f"cannot determine OpenCode version from {executable!r}")
    return value.splitlines()[-1].strip()


def parse_events(text: str) -> OpenCodeEventSummary:
    session_ids: list[str] = []
    messages: list[str] = []
    failures: list[str] = []
    parse_errors: list[str] = []
    terminal_steps = 0
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
        session_id = event.get("sessionID")
        if not isinstance(session_id, str) or not session_id.strip():
            parse_errors.append(f"line {line_number}: OpenCode event is missing sessionID")
        else:
            session_ids.append(session_id.strip())
        event_type = event.get("type")
        part = event.get("part")
        if event_type == "text" and isinstance(part, dict):
            message = part.get("text")
            if isinstance(message, str) and message.strip():
                messages.append(message)
        elif event_type == "step_finish" and isinstance(part, dict):
            reason = part.get("reason")
            if reason == "stop":
                terminal_steps += 1
        elif event_type == "error":
            failures.append(_error_text(event))
        elif event_type not in {"step_start", "text", "tool_use", "step_finish", "reasoning"}:
            parse_errors.append(f"line {line_number}: unsupported OpenCode event type: {event_type!r}")
    unique_ids = tuple(dict.fromkeys(session_ids))
    if len(unique_ids) > 1:
        parse_errors.append("OpenCode event stream reported inconsistent sessionID values")
    return OpenCodeEventSummary(
        thread_ids=unique_ids,
        last_agent_message=messages[-1] if messages else "",
        completed=terminal_steps > 0 and bool(messages) and not failures,
        failures=tuple(failures),
        parse_errors=tuple(parse_errors),
    )


def _error_text(event: dict[str, Any]) -> str:
    value = event.get("error") or event.get("message") or "OpenCode reported an error"
    if isinstance(value, dict):
        data = value.get("data")
        value = (
            data.get("message")
            if isinstance(data, dict) and isinstance(data.get("message"), str)
            else value.get("message") or value.get("name") or json.dumps(value, sort_keys=True)
        )
    return str(value)[:500]
