from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from .contracts import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    Mode,
    ServerSpec,
)

CONTEXT_TOOLS = frozenset(
    {
        "get_active_task",
        "get_project_overview",
        "list_tasks",
        "get_task_handoff",
        "get_task_context",
        "get_attempt_summary",
        "get_gate_status",
        "validate_result_record",
        "get_cost_hotspots",
        "search_team_memory",
        "search_repository",
        "get_change_summary",
    }
)
LOCAL_DOCS_TOOLS = frozenset({"list_doc_sources", "search_docs", "read_doc"})


def context_server_spec(
    projects_root: str | Path,
    project: str,
    *,
    work_root: str | Path | None = None,
    repository_id: str | None = None,
    interpreter: str | Path = sys.executable,
    repository_root: str | Path | None = None,
    script: str | Path | None = None,
    args: Iterable[str] = (),
    mode: Mode = Mode.OPTIONAL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> ServerSpec:
    root = _repository_root(repository_root)
    server_script = Path(script) if script is not None else root / "scripts/team-context-mcp.py"
    command = (
        str(interpreter),
        str(server_script),
        "--projects-root",
        str(projects_root),
        *(str(value) for value in args),
    )
    if (work_root is None) != (repository_id is None):
        raise ValueError("work_root and repository_id must be supplied together")
    environment = [("CODEXTEAM_CONTEXT_PROJECT", project)]
    if work_root is not None and repository_id is not None:
        environment.extend(
            (
                ("CODEXTEAM_CONTEXT_WORK_ROOT", str(work_root)),
                ("CODEXTEAM_CONTEXT_REPOSITORY_ID", repository_id),
            )
        )
    return ServerSpec(
        command=command,
        expected_name="codexteam-context-pilot",
        expected_version="0.3.0",
        allowed_tools=CONTEXT_TOOLS,
        mode=mode,
        timeout_seconds=timeout_seconds,
        max_request_bytes=max_request_bytes,
        max_response_bytes=max_response_bytes,
        environment=tuple(environment),
        cwd=str(root),
    )


def local_docs_server_spec(
    manifest: str | Path,
    *,
    interpreter: str | Path = sys.executable,
    repository_root: str | Path | None = None,
    script: str | Path | None = None,
    args: Iterable[str] = (),
    mode: Mode = Mode.OPTIONAL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> ServerSpec:
    root = _repository_root(repository_root)
    server_script = Path(script) if script is not None else root / "scripts/local-docs-mcp.py"
    command = (
        str(interpreter),
        str(server_script),
        "--manifest",
        str(manifest),
        *(str(value) for value in args),
    )
    return ServerSpec(
        command=command,
        expected_name="local-docs",
        expected_version="0.1.0",
        allowed_tools=LOCAL_DOCS_TOOLS,
        mode=mode,
        timeout_seconds=timeout_seconds,
        max_request_bytes=max_request_bytes,
        max_response_bytes=max_response_bytes,
        cwd=str(root),
    )


def _repository_root(value: str | Path | None) -> Path:
    if value is not None:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[3]
