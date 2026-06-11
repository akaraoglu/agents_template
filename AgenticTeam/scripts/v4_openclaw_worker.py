from __future__ import annotations

import fnmatch
import hashlib
import json
import posixpath
import subprocess
from pathlib import Path
from typing import Any

from AgenticTeam.scripts.v4_contracts import EventV4, LeaseV4, TaskPackV4, WorkResultV4
from AgenticTeam.scripts.v4_events import append_event_v4
from AgenticTeam.scripts.v4_tools import V4ToolError, V4Tools


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RESULT_BEGIN = "WORK_RESULT_JSON_BEGIN"
RESULT_END = "WORK_RESULT_JSON_END"
IGNORED_CHANGE_PATTERNS = (
    ".pytest_cache/**",
    "**/.pytest_cache/**",
    "**/__pycache__/**",
    "**/*.pyc",
)


class V4OpenClawWorkerRunner:
    """Runs a V4 worker task through the configured OpenClaw agent platform."""

    def __init__(self, task_pack: TaskPackV4, lease: LeaseV4, actor: str = "morpheus", timeout_seconds: int = 600):
        self.task_pack = task_pack
        self.lease = lease
        self.actor = actor
        self.timeout_seconds = timeout_seconds
        self.workspace_root = Path(task_pack.workspace_root).resolve()
        self.tools = V4Tools(str(self.workspace_root))

    def run(self) -> str:
        before = snapshot_project_files(self.workspace_root)
        command = self._agent_command()
        try:
            result = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds + 60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            reason = f"OpenClaw worker agent timed out after {self.timeout_seconds + 60}s"
            self._record_agent_failure("agent_timeout", reason, stdout=exc.stdout, stderr=exc.stderr)
            return reason

        if result.returncode != 0:
            reason = f"OpenClaw worker agent exited with code {result.returncode}"
            self._record_agent_failure("agent_exit_nonzero", reason, stdout=result.stdout, stderr=result.stderr)
            return reason

        payload = result.stdout if result.stdout else ""
        if result.stderr:
            payload = f"{payload}\n{result.stderr}"
        try:
            work_payload = extract_marked_json(payload, RESULT_BEGIN, RESULT_END)
        except ValueError as exc:
            reason = str(exc)
            self._record_agent_failure("missing_work_result", reason, stdout=result.stdout, stderr=result.stderr)
            return reason

        status = str(work_payload.get("status", "DONE")).upper()
        summary = str(work_payload.get("summary", ""))
        if status in {"BLOCKED", "FAILED"}:
            reason = summary or str(work_payload.get("reason", "Worker reported blocked."))
            return self.tools.work_block(
                self.task_pack.task_id,
                self.lease.metadata.get("attempt_id", "none"),
                reason,
                self.lease.lease_id,
                self.actor,
            )

        if status != "DONE":
            reason = f"Unsupported worker status: {status}"
            self._record_agent_failure("invalid_work_result_status", reason, stdout=result.stdout, stderr=result.stderr)
            return reason

        after = snapshot_project_files(self.workspace_root)
        changed_paths = changed_project_paths(before, after)
        try:
            self._ensure_changes_allowed(changed_paths)
            self._ensure_expected_artifacts_exist()
        except V4ToolError as exc:
            self._record_agent_failure(exc.error_code, exc.message, stdout=result.stdout, stderr=result.stderr)
            return f"Tool Error [{exc.error_code}]: {exc.message}"

        output = work_payload.get("output")
        if not isinstance(output, dict):
            output = {}
        output.setdefault("artifacts", self._expected_artifacts())
        evidence = work_payload.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        evidence.setdefault("openclaw_agent", self.actor)
        evidence.setdefault("changed_paths", changed_paths)

        wr = WorkResultV4(
            task_id=self.task_pack.task_id,
            attempt_id=self.lease.metadata.get("attempt_id", "none"),
            status="DONE",
            summary=summary,
            output=output,
            evidence=evidence,
        )
        return self.tools.work_submit(wr, self.lease.lease_id, self.actor)

    def _agent_command(self) -> list[str]:
        session_key = (
            f"agent:{self.actor}:v4:{self.task_pack.project_id}:"
            f"{self.task_pack.task_id}:{self.lease.metadata.get('attempt_id', 'none')}"
        )
        return [
            "openclaw",
            "agent",
            "--agent",
            self.actor,
            "--session-key",
            session_key,
            "--message",
            self._message(),
            "--timeout",
            str(self.timeout_seconds),
            "--thinking",
            "off",
        ]

    def _message(self) -> str:
        task_file = f"management/tasks/{self.task_pack.task_id}.md"
        optional_test = self.workspace_root / "tests" / "test_main.py"
        return f"""You are executing a V4 worker task as the real OpenClaw `{self.actor}` agent.

Project ID: {self.task_pack.project_id}
Task ID: {self.task_pack.task_id}
Workspace Root: {self.workspace_root}
Task File: {task_file}
Expected Artifacts: {json.dumps(self._expected_artifacts())}
Writable Paths: {json.dumps(self._writable_paths())}
Protected Paths: {json.dumps(self._protected_paths())}

Required workflow:
1. Read `{self.workspace_root / "PROJECT.md"}` and `{self.workspace_root / task_file}`.
2. Inspect existing relevant files by reading known paths directly. Start with `{self.workspace_root / "src" / "main.py"}` and `{self.workspace_root / "README.md"}`. Read `{optional_test}` only if it exists or the task asks for tests.
3. Edit only files under Workspace Root that match Writable Paths and do not match Protected Paths.
4. Do not edit `.openclaw`, PROJECT.md, PROJECT_STATE.md, CURRENT_TASK.md, BRIEF.md, RESULT.md, DONE_REPORT.md, BLOCKED_REPORT.md, or management task/plan/backlog files.
5. Do not list directories and do not use shell commands for discovery. If a known optional file is missing, continue with the files you can read.
6. Implement the task and add or update tests when appropriate.
7. The `exec` tool is intentionally unavailable in this worker lane. Do not attempt shell validation and do not block only because `exec` is unavailable. Use `evidence.validation` to state what you inspected or why runtime/host validation remains.
8. If any tool is unavailable or fails, you must still finish with the marker envelope below. Never end with plain text such as "I cannot use exec".
9. If you cannot complete the implementation with read/write, return BLOCKED with an exact reason in the marker envelope.
10. Your final response must include exactly one JSON object between these markers:

{RESULT_BEGIN}
{{
  "status": "DONE | BLOCKED | FAILED",
  "summary": "brief task result or block reason",
  "output": {{
    "artifacts": ["project-relative files you created or changed"]
  }},
  "evidence": {{
    "validation": "what you ran or inspected"
  }}
}}
{RESULT_END}

The V4 runtime will validate expected artifacts and write boundaries after your OpenClaw turn returns.
"""

    def _record_agent_failure(self, reason_code: str, reason: str, *, stdout: Any = "", stderr: Any = "") -> None:
        append_event_v4(
            EventV4(
                event_type="worker_agent_failed",
                payload={
                    "task_id": self.task_pack.task_id,
                    "attempt_id": self.lease.metadata.get("attempt_id", "none"),
                    "lease_id": self.lease.lease_id,
                    "actor": self.actor,
                    "reason_code": reason_code,
                    "reason": reason,
                    "stdout_tail": tail_text(stdout),
                    "stderr_tail": tail_text(stderr),
                },
                actor="v4_runtime",
            )
        )

    def _normalized_relative_path(self, relative_path: str) -> str:
        normalized = posixpath.normpath(str(relative_path).replace("\\", "/")).strip("/")
        if normalized in ("", ".") or normalized.startswith("../") or normalized == "..":
            raise V4ToolError("path_outside_workspace", f"Invalid project-relative path: {relative_path}")
        return normalized

    def _expected_artifacts(self) -> list[str]:
        return [
            self._normalized_relative_path(path)
            for path in self.task_pack.effective_expected_artifacts()
        ]

    def _writable_paths(self) -> list[str]:
        return [self._normalized_relative_path(path) for path in self.task_pack.writable_paths]

    def _protected_paths(self) -> list[str]:
        return [self._normalized_relative_path(path) for path in self.task_pack.protected_paths]

    def _ensure_expected_artifacts_exist(self) -> None:
        missing = [
            path
            for path in self._expected_artifacts()
            if not (self.workspace_root / path).is_file()
        ]
        if missing:
            raise V4ToolError(
                "missing_expected_artifacts",
                f"Cannot submit DONE; missing expected artifacts: {missing}",
            )

    def _ensure_changes_allowed(self, changed_paths: list[str]) -> None:
        writable = self._writable_paths()
        protected = self._protected_paths()
        violations: list[str] = []
        for path in changed_paths:
            if any(matches_path_rule(path, rule) for rule in protected):
                violations.append(f"{path} matches protected path")
                continue
            if writable and not any(matches_path_rule(path, rule) for rule in writable):
                violations.append(f"{path} is outside writable paths")
        if violations:
            raise V4ToolError(
                "write_boundary_violation",
                "; ".join(violations),
            )


def extract_marked_json(text: str, begin: str, end: str) -> dict[str, Any]:
    start = text.rfind(begin)
    finish = text.rfind(end)
    if start == -1 or finish == -1 or finish <= start:
        raise ValueError(f"OpenClaw worker response did not include {begin}/{end} WorkResult markers")
    raw = text[start + len(begin) : finish].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenClaw worker WorkResult JSON was invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("OpenClaw worker WorkResult JSON must be an object")
    return data


def snapshot_project_files(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.exists():
        return snapshot
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return snapshot


def changed_project_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = sorted(set(before) | set(after))
    changed = [path for path in paths if before.get(path) != after.get(path)]
    return [path for path in changed if not ignored_change_path(path)]


def ignored_change_path(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in IGNORED_CHANGE_PATTERNS)


def matches_path_rule(normalized: str, rule: str) -> bool:
    if rule.endswith("/**"):
        prefix = rule[:-3].rstrip("/")
        return normalized == prefix or normalized.startswith(prefix + "/")
    return normalized == rule


def tail_text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    return text[-limit:]
