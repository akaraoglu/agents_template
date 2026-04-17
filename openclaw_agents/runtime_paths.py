"""Runtime-root path helpers for Option A deployment layout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_DEFAULT_RUNTIME_ROOT = "~/workspace/clawspace"


def resolve_runtime_root(root: str | Path | None = None) -> Path:
    raw = root if root is not None else os.environ.get("OPENCLAW_ROOT", _DEFAULT_RUNTIME_ROOT)
    return Path(raw).expanduser().resolve()


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path
    system_root: Path
    config_root: Path
    state_root: Path
    logs_root: Path
    runtime_root: Path
    artifacts_root: Path
    projects_root: Path

    @classmethod
    def from_root(cls, root: str | Path | None = None) -> RuntimePaths:
        resolved_root = resolve_runtime_root(root)
        system_root = resolved_root / "system"
        return cls(
            root=resolved_root,
            system_root=system_root,
            config_root=system_root / "config",
            state_root=system_root / "state",
            logs_root=system_root / "logs",
            runtime_root=system_root / "runtime",
            artifacts_root=system_root / "artifacts",
            projects_root=resolved_root / "projects",
        )

    def ensure(self) -> RuntimePaths:
        for path in (
            self.root,
            self.system_root,
            self.config_root,
            self.state_root,
            self.logs_root,
            self.runtime_root,
            self.artifacts_root,
            self.projects_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def project_root(self, project_id: str) -> Path:
        return self.projects_root / project_id
