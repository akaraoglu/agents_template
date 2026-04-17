"""Controlled command execution inside the repository/workspace boundary."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .audit_log import AuditLogService


_BLOCKED_PATTERNS = (
    r"\brm\s+-rf\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-fd\b",
    r"\bsudo\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bkill\s+-9\b",
    r"\b:?\(\)\s*\{",
    r">\s*/dev/sd",
)


class CommandRunnerService:
    def __init__(self, allowed_root: Path, audit_log: AuditLogService | None = None) -> None:
        self.allowed_root = allowed_root.resolve()
        self.audit_log = audit_log

    def _resolve_cwd(
        self,
        cwd: str | Path | None = None,
        *,
        allowed_root: str | Path | None = None,
    ) -> Path:
        boundary = Path(allowed_root).resolve() if allowed_root is not None else self.allowed_root
        if cwd is None:
            target = boundary
        else:
            candidate = Path(cwd)
            target = candidate if candidate.is_absolute() else (boundary / candidate)
            target = target.resolve()
        if not str(target).startswith(str(boundary)):
            raise ValueError("Command cwd escapes the allowed runtime boundary.")
        if not target.exists():
            raise FileNotFoundError(f"Command cwd does not exist: {target}")
        return target

    def run(
        self,
        command: str,
        *,
        cwd: str | Path | None = None,
        timeout_seconds: int = 120,
        actor_agent: str = "neo",
        project_id: str | None = None,
        allowed_root: str | Path | None = None,
    ) -> dict[str, Any]:
        cleaned = command.strip()
        if not cleaned:
            raise ValueError("Command is required.")
        lowered = cleaned.lower()
        for pattern in _BLOCKED_PATTERNS:
            if re.search(pattern, lowered):
                if self.audit_log is not None:
                    self.audit_log.record(
                        action_type="workspace_command",
                        actor_agent=actor_agent,
                        outcome="blocked",
                        payload={"command": cleaned, "pattern": pattern},
                        project_id=project_id,
                    )
                raise ValueError("Command blocked by execution guardrails.")
        resolved_cwd = self._resolve_cwd(cwd, allowed_root=allowed_root)
        capped_timeout = max(1, min(int(timeout_seconds), 300))
        completed = subprocess.run(
            ["/bin/bash", "-lc", cleaned],
            cwd=resolved_cwd,
            text=True,
            capture_output=True,
            timeout=capped_timeout,
            check=False,
        )
        result = {
            "command": cleaned,
            "cwd": str(resolved_cwd),
            "returncode": completed.returncode,
            "stdout": completed.stdout[:12000],
            "stderr": completed.stderr[:12000],
        }
        if self.audit_log is not None:
            self.audit_log.record(
                action_type="workspace_command",
                actor_agent=actor_agent,
                outcome="ok" if completed.returncode == 0 else "error",
                payload={
                    "command": cleaned,
                    "cwd": str(resolved_cwd),
                    "returncode": completed.returncode,
                },
                project_id=project_id,
            )
        return result
