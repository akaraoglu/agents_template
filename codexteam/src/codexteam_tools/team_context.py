from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .paths import (
    PathValidationError,
    contained_path,
    ensure_existing_workspace,
    normalize_task_id,
    validate_identifier,
)
from .subagent_status import collect_subagent_status
from .tasks import TaskDocumentError, parse_task_document
from .test_gates import (
    GATES,
    GateConfigError,
    gate_record_path,
    load_gate_config,
    validate_current_gate_record,
)

PROJECT_MEMORY_FILES = ("DECISIONS.md", "OPEN_QUESTIONS.md")
MEMORY_SCOPES = ("project", "team", "all")
MAX_QUERY_LENGTH = 200
MAX_MEMORY_RESULTS = 10
MAX_MEMORY_BLOCK_CHARS = 600


class TeamContextError(ValueError):
    pass


class TeamContextReader:
    def __init__(
        self,
        projects_root: str | Path,
        *,
        team_memory_root: str | Path | None = None,
    ) -> None:
        self.projects_root = ensure_existing_workspace(projects_root)
        self.team_memory_root = (
            ensure_existing_workspace(team_memory_root)
            if team_memory_root is not None
            else None
        )

    def get_active_task(self, project: str) -> dict[str, Any]:
        root = self._project(project)
        current_path = self._required_file(root, "CURRENT_TASK.md")
        tasks_path = self._required_file(root, "TASKS.md")
        current = _parse_bullets(current_path.read_text(encoding="utf-8"))
        raw_task_id = current.get("task_id", "")
        if raw_task_id.casefold() == "none":
            return {
                "project": project,
                "current": current,
                "ledger": None,
                "ledger_warning": None,
                "attempts": [],
                "sources": [self._source(root, current_path)],
            }
        task_id = normalize_task_id(raw_task_id)
        row, ledger_warning = _read_task_row(
            tasks_path.read_text(encoding="utf-8"),
            task_id,
        )
        attempts = [
            _compact_attempt(record)
            for record in collect_subagent_status(root)
            if record["task"] == task_id
        ][:3]
        handoff = current.get("handoff")
        source_paths = [current_path, tasks_path]
        if handoff:
            handoff_path = self._optional_file(root, _strip_code(handoff))
            if handoff_path is not None:
                source_paths.append(handoff_path)
        return {
            "project": project,
            "current": current,
            "ledger": row,
            "ledger_warning": ledger_warning,
            "attempts": attempts,
            "sources": [self._source(root, path) for path in source_paths],
        }

    def get_task_handoff(self, project: str, task_id: str) -> dict[str, Any]:
        root = self._project(project)
        normalized = normalize_task_id(task_id)
        handoff_path = self._required_file(root, f"management/tasks/{normalized}.md")
        tasks_path = self._required_file(root, "TASKS.md")
        text = handoff_path.read_text(encoding="utf-8")
        title, sections = _parse_sections(text)
        row, ledger_warning = _read_task_row(
            tasks_path.read_text(encoding="utf-8"),
            normalized,
        )
        return {
            "project": project,
            "task_id": normalized,
            "title": title,
            "ledger": row,
            "ledger_warning": ledger_warning,
            "sections": sections,
            "sources": [
                self._source(root, handoff_path),
                self._source(root, tasks_path),
            ],
        }

    def get_gate_status(self, project: str) -> dict[str, Any]:
        root = self._project(project)
        config = load_gate_config(root)
        config_path = self._required_file(root, "management/TEST_GATES.toml")
        gates: list[dict[str, Any]] = []
        source_paths = [config_path]
        commands = {
            "development": config.development_commands,
            "integration": config.integration_commands,
        }
        timeouts = {
            "development": config.development_timeout,
            "integration": config.integration_timeout,
        }
        surfaces = {
            "development": config.development_surface,
            "integration": config.integration_surface,
        }
        for gate in GATES:
            record_path = gate_record_path(root, gate)
            record = self._read_record(root, record_path)
            current = False
            freshness_error: str | None = None
            if record is not None:
                try:
                    validate_current_gate_record(root, gate)
                    current = True
                except GateConfigError as exc:
                    freshness_error = str(exc)
                source_paths.append(record_path)
            gates.append(
                {
                    "gate": gate,
                    "configured_commands": [list(argv) for argv in commands[gate]],
                    "timeout_seconds": timeouts[gate],
                    "execution_surface": surfaces[gate],
                    "record": _compact_gate_record(record),
                    "current": current,
                    "freshness_error": freshness_error,
                }
            )
        return {
            "project": project,
            "verification_paths": list(config.verification_paths),
            "gates": gates,
            "sources": [self._source(root, path) for path in source_paths],
        }

    def search_team_memory(
        self,
        project: str,
        query: str,
        *,
        scope: str = "all",
        limit: int = 3,
    ) -> dict[str, Any]:
        root = self._project(project)
        clean_query = query.strip()
        if not clean_query or len(clean_query) > MAX_QUERY_LENGTH:
            raise TeamContextError(
                f"query must contain 1-{MAX_QUERY_LENGTH} characters"
            )
        if scope not in MEMORY_SCOPES:
            raise TeamContextError(
                f"scope must be one of: {', '.join(MEMORY_SCOPES)}"
            )
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_MEMORY_RESULTS:
            raise TeamContextError(f"limit must be between 1 and {MAX_MEMORY_RESULTS}")
        files: list[tuple[str, Path]] = []
        if scope in {"project", "all"}:
            for relative in PROJECT_MEMORY_FILES:
                path = self._optional_file(root, relative)
                if path is not None:
                    files.append(("project", path))
        if scope in {"team", "all"}:
            if self.team_memory_root is None:
                if scope == "team":
                    raise TeamContextError("team memory root is not configured")
            else:
                for path in sorted(self.team_memory_root.glob("*.md")):
                    if path.is_file() and not path.is_symlink():
                        files.append(("team", path))

        query_terms = _search_terms(clean_query)
        if not query_terms:
            raise TeamContextError("query must contain a searchable term")
        matches: list[dict[str, Any]] = []
        source_hashes: dict[str, str] = {}
        for source_scope, path in files:
            source_hash = _sha256(path)
            source_name = self._memory_source_name(root, source_scope, path)
            source_hashes[source_name] = source_hash
            for line, block in _memory_blocks(path.read_text(encoding="utf-8")):
                score, matched_terms = _memory_score(
                    block,
                    clean_query,
                    query_terms,
                )
                if score <= 0:
                    continue
                matches.append(
                    {
                        "scope": source_scope,
                        "source": source_name,
                        "line": line,
                        "_score": score,
                        "text": _memory_excerpt(
                            block,
                            matched_terms,
                            MAX_MEMORY_BLOCK_CHARS,
                        ),
                    }
                )
        matches.sort(
            key=lambda item: (
                -item["_score"],
                item["source"],
                item["line"],
            )
        )
        selected = matches[:limit]
        selected_sources = {match["source"] for match in selected}
        return {
            "project": project,
            "query": clean_query,
            "scope": scope,
            "matches": [
                {key: value for key, value in match.items() if key != "_score"}
                for match in selected
            ],
            "searched_sources": len(files),
            "sources": [
                {
                    "path": source,
                    "sha256": digest,
                    "bytes": next(
                        path.stat().st_size
                        for source_scope, path in files
                        if self._memory_source_name(root, source_scope, path) == source
                    ),
                }
                for source, digest in sorted(source_hashes.items())
                if source in selected_sources
            ],
        }

    def project_root(self, project: str) -> Path:
        return self._project(project)

    def required_file(self, root: Path, relative: str) -> Path:
        return self._required_file(root, relative)

    def optional_file(self, root: Path, relative: str) -> Path | None:
        return self._optional_file(root, relative)

    def source(self, root: Path, path: Path) -> dict[str, str | int]:
        return self._source(root, path)

    def _project(self, project: str) -> Path:
        try:
            name = validate_identifier(project, label="project")
        except PathValidationError as exc:
            raise TeamContextError(str(exc)) from exc
        candidate = contained_path(self.projects_root, name, label="project")
        if candidate.is_symlink() or not candidate.is_dir():
            raise TeamContextError(f"project does not exist or is unsafe: {name}")
        return ensure_existing_workspace(candidate)

    def _required_file(self, root: Path, relative: str) -> Path:
        path = contained_path(root, relative, label="context file")
        if path.is_symlink() or not path.is_file():
            raise TeamContextError(f"required context file is missing or unsafe: {relative}")
        return path

    def _optional_file(self, root: Path, relative: str) -> Path | None:
        try:
            path = contained_path(root, relative, label="context file")
        except PathValidationError:
            return None
        if path.is_symlink() or not path.is_file():
            return None
        return path

    def _read_record(self, root: Path, path: Path) -> dict[str, Any] | None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise TeamContextError("gate record escapes project root") from exc
        if path.is_symlink() or not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TeamContextError(f"invalid gate record JSON: {path.name}") from exc
        if not isinstance(value, dict):
            raise TeamContextError(f"gate record must contain an object: {path.name}")
        return value

    def _source(self, root: Path, path: Path) -> dict[str, str | int]:
        return {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }

    def _memory_source_name(
        self,
        project_root: Path,
        scope: str,
        path: Path,
    ) -> str:
        if scope == "project":
            return path.relative_to(project_root).as_posix()
        assert self.team_memory_root is not None
        return f"team-memory/{path.relative_to(self.team_memory_root).as_posix()}"


def _parse_bullets(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    active_key: str | None = None
    for line in text.splitlines():
        match = re.match(r"^- ([^:]+):\s*(.*)$", line)
        if match:
            active_key = _key(match.group(1))
            values[active_key] = match.group(2).strip()
        elif active_key and line.startswith((" ", "\t")) and line.strip():
            values[active_key] = f"{values[active_key]} {line.strip()}".strip()
        else:
            active_key = None
    if not values:
        raise TeamContextError("current task document has no key-value bullets")
    return values


def _parse_sections(text: str) -> tuple[str, list[dict[str, str]]]:
    title = ""
    sections: list[dict[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            if current_title is not None:
                sections.append(
                    {
                        "title": current_title,
                        "text": "\n".join(current_lines).strip(),
                    }
                )
            current_title = line[3:].strip()
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections.append(
            {
                "title": current_title,
                "text": "\n".join(current_lines).strip(),
            }
        )
    if not title or not sections:
        raise TeamContextError("handoff must contain a title and at least one section")
    return title, sections


def _read_task_row(
    text: str,
    task_id: str,
) -> tuple[dict[str, str], str | None]:
    try:
        row = parse_task_document(text).row(task_id)
    except TaskDocumentError as exc:
        warning = f"TASKS.md full validation failed: {exc}"
        for index, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("|") or not stripped.endswith("|"):
                continue
            cells = tuple(part.strip() for part in stripped[1:-1].split("|"))
            if len(cells) != 6 or cells[0].upper() != task_id:
                continue
            return (
                {
                    "task_id": task_id,
                    "description": cells[1],
                    "status": cells[2],
                    "owner": cells[3],
                    "verification": cells[4],
                    "evidence": cells[5],
                },
                f"{warning}; requested row read exactly from line {index}",
            )
        raise
    return (
        {
            "task_id": row.task_id,
            "description": row.description,
            "status": row.status,
            "owner": row.owner,
            "verification": row.verification,
            "evidence": row.evidence,
        },
        None,
    )


def _compact_attempt(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "team",
            "task",
            "attempt",
            "role",
            "profile",
            "phase",
            "turn",
            "status",
            "updated_at",
            "state_path",
        )
    }


def _compact_gate_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    failures = [
        {
            "gate": command.get("gate"),
            "argv": command.get("argv"),
            "exit_code": command.get("exit_code"),
            "stderr_tail": _truncate(str(command.get("stderr_tail") or ""), 500),
        }
        for command in record.get("commands", [])
        if isinstance(command, dict) and command.get("exit_code") != 0
    ]
    return {
        "status": record.get("status"),
        "completed_at": record.get("completed_at"),
        "duration_seconds": record.get("duration_seconds"),
        "configuration_digest": record.get("configuration_digest"),
        "workspace_digest": record.get("workspace_digest"),
        "execution_surface": record.get("execution_surface", "worker"),
        "failures": failures,
    }


def _memory_blocks(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    decision_indexes = [
        index for index, line in enumerate(lines) if re.match(r"^## D[0-9]+\b", line)
    ]
    if decision_indexes:
        return _heading_blocks(lines, decision_indexes)
    bullet_indexes = [
        index for index, line in enumerate(lines) if line.startswith("- ")
    ]
    if bullet_indexes:
        return _indexed_blocks(lines, bullet_indexes)
    heading_indexes = [
        index for index, line in enumerate(lines) if line.startswith("## ")
    ]
    return _heading_blocks(lines, heading_indexes)


def _heading_blocks(lines: list[str], indexes: list[int]) -> list[tuple[int, str]]:
    return _indexed_blocks(lines, indexes)


def _indexed_blocks(lines: list[str], indexes: list[int]) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    for position, start in enumerate(indexes):
        end = indexes[position + 1] if position + 1 < len(indexes) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        if block:
            blocks.append((start + 1, block))
    return blocks


def _memory_score(
    block: str,
    query: str,
    query_terms: tuple[str, ...],
) -> tuple[int, list[str]]:
    lowered = block.lower()
    matched = [term for term in query_terms if term in lowered]
    if not matched:
        return 0, []
    score = len(matched) * 3
    score += sum(min(lowered.count(term), 3) for term in matched)
    if len(matched) == len(query_terms):
        score += 5
    if query.lower() in lowered:
        score += 10
    return score, matched


def _search_terms(value: str) -> tuple[str, ...]:
    terms = re.findall(r"[a-z0-9][a-z0-9_.-]*", value.lower())
    return tuple(dict.fromkeys(term for term in terms if len(term) > 1))


def _strip_code(value: str) -> str:
    clean = value.strip()
    return clean[1:-1] if clean.startswith("`") and clean.endswith("`") else clean


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _memory_excerpt(
    block: str,
    matched_terms: list[str],
    limit: int,
) -> str:
    if len(block) <= limit:
        return block
    lowered = block.lower()
    positions = [lowered.find(term) for term in matched_terms if term in lowered]
    match_at = min(positions) if positions else 0
    start = max(0, match_at - limit // 3)
    end = min(len(block), start + limit)
    start = max(0, end - limit)
    excerpt = block[start:end].strip()
    if start:
        excerpt = "..." + excerpt
    if end < len(block):
        excerpt = excerpt.rstrip() + "..."
    return excerpt
