from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .files import atomic_write_text
from .paths import normalize_task_id

TASK_STATUSES = {
    "planned": "Planned",
    "ready": "Ready",
    "in progress": "In Progress",
    "blocked": "Blocked",
    "needs review": "Needs Review",
    "completed": "Completed",
}
EXPECTED_HEADER = ("Task ID", "Description", "Status", "Owner", "Verification", "Evidence")
CONTEXT_MODES = {"direct", "bounded-mcp"}
EXECUTION_CLASSES = {"small", "complex"}
MAX_DIRECT_CONTEXT_TARGETS = 5


class TaskDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class TaskRow:
    task_id: str
    description: str
    status: str
    owner: str
    verification: str
    evidence: str

    def cells(self) -> tuple[str, ...]:
        return (self.task_id, self.description, self.status, self.owner, self.verification, self.evidence)


@dataclass(frozen=True)
class TaskHandoffMetadata:
    task_write_scope: tuple[str, ...] | None
    context_mode: str | None
    result_report: str | None
    direct_context: tuple[tuple[str, int, int], ...]
    verification_commands: tuple[tuple[str, ...], ...]
    execution_class: str | None


def parse_task_handoff_metadata(text: str) -> TaskHandoffMetadata:
    lines = text.splitlines()
    scope_sections = _section_indexes(lines, "Task Write Scope")
    if len(scope_sections) > 1:
        raise TaskDocumentError("task handoff contains multiple Task Write Scope sections")
    scope: tuple[str, ...] | None = None
    if scope_sections:
        patterns: list[str] = []
        for line in _section_lines(lines, scope_sections[0]):
            match = re.fullmatch(r"\s*-\s+`([^`]+)`\s*", line)
            if match is None:
                raise TaskDocumentError("Task Write Scope entries must be backticked bullet patterns")
            pattern = match.group(1)
            if (
                not pattern
                or pattern.startswith("/")
                or "\\" in pattern
                or any(part == ".." for part in Path(pattern).parts)
            ):
                raise TaskDocumentError(f"unsafe task write scope pattern: {pattern!r}")
            patterns.append(pattern)
        scope = tuple(dict.fromkeys(patterns))

    context_sections = _section_indexes(lines, "Context Mode")
    if len(context_sections) > 1:
        raise TaskDocumentError("task handoff contains multiple Context Mode sections")
    context_mode: str | None = None
    if context_sections:
        values = _section_lines(lines, context_sections[0])
        if len(values) != 1:
            raise TaskDocumentError("Context Mode must contain exactly one value")
        match = re.fullmatch(r"\s*-\s+`([^`]+)`\s*", values[0])
        if match is None or match.group(1) not in CONTEXT_MODES:
            raise TaskDocumentError(
                "Context Mode must be one backticked bullet: direct or bounded-mcp"
            )
        context_mode = match.group(1)

    execution_sections = _section_indexes(lines, "Execution Class")
    if len(execution_sections) > 1:
        raise TaskDocumentError("task handoff contains multiple Execution Class sections")
    execution_class: str | None = None
    if execution_sections:
        values = _section_lines(lines, execution_sections[0])
        if len(values) != 1:
            raise TaskDocumentError("Execution Class must contain exactly one value")
        match = re.fullmatch(r"\s*-\s+`([^`]+)`\s*", values[0])
        if match is None or match.group(1) not in EXECUTION_CLASSES:
            raise TaskDocumentError(
                "Execution Class must be one backticked bullet: small or complex"
            )
        execution_class = match.group(1)
    result_sections = _section_indexes(lines, "Result Report")
    if len(result_sections) > 1:
        raise TaskDocumentError("task handoff contains multiple Result Report sections")
    result_report: str | None = None
    if result_sections:
        values = _section_lines(lines, result_sections[0])
        if len(values) != 1:
            raise TaskDocumentError("Result Report must contain exactly one path")
        match = re.fullmatch(r"\s*-\s+`([^`]+)`\s*", values[0])
        if match is None:
            raise TaskDocumentError("Result Report must be one backticked path bullet")
        result_report = _safe_handoff_path(match.group(1), "Result Report")

    direct_sections = _section_indexes(lines, "Direct Context")
    if len(direct_sections) > 1:
        raise TaskDocumentError("task handoff contains multiple Direct Context sections")
    direct_context: list[tuple[str, int, int]] = []
    if direct_sections:
        values = _section_lines(lines, direct_sections[0])
        if len(values) > MAX_DIRECT_CONTEXT_TARGETS:
            raise TaskDocumentError(
                f"Direct Context must contain at most {MAX_DIRECT_CONTEXT_TARGETS} targets"
            )
        for value in values:
            match = re.fullmatch(r"\s*-\s+`([^`]+):(\d+)-(\d+)`\s*", value)
            if match is None:
                raise TaskDocumentError(
                    "Direct Context entries must use `relative/path:start-end`"
                )
            path = _safe_handoff_path(match.group(1), "Direct Context")
            start, end = int(match.group(2)), int(match.group(3))
            if start < 1 or end < start or end - start + 1 > 400:
                raise TaskDocumentError(
                    "Direct Context ranges must be positive, ordered, and at most 400 lines"
                )
            direct_context.append((path, start, end))

    verification_sections = _section_indexes(lines, "Verification Commands")
    if len(verification_sections) > 1:
        raise TaskDocumentError("task handoff contains multiple Verification Commands sections")
    verification_commands: list[tuple[str, ...]] = []
    if verification_sections:
        for value in _section_lines(lines, verification_sections[0]):
            match = re.fullmatch(r"\s*-\s+`(.+)`\s*", value)
            if match is None:
                raise TaskDocumentError(
                    "Verification Commands entries must be backticked JSON argv arrays"
                )
            try:
                command = json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                raise TaskDocumentError(f"invalid Verification Commands JSON: {exc.msg}") from exc
            if (
                not isinstance(command, list)
                or not command
                or any(not isinstance(item, str) or not item or "\x00" in item for item in command)
            ):
                raise TaskDocumentError(
                    "Verification Commands entries must be non-empty string argv arrays"
                )
            verification_commands.append(tuple(command))

    if context_mode == "direct":
        if result_report is None:
            raise TaskDocumentError("direct context requires a Result Report")
        if not direct_context:
            raise TaskDocumentError("direct context requires at least one Direct Context target")
        if not verification_commands:
            raise TaskDocumentError("direct context requires at least one Verification Command")
    return TaskHandoffMetadata(
        scope,
        context_mode,
        result_report,
        tuple(direct_context),
        tuple(verification_commands),
        execution_class,
    )


def _safe_handoff_path(value: str, label: str) -> str:
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or any(part == ".." for part in Path(value).parts)
    ):
        raise TaskDocumentError(f"unsafe {label} path: {value!r}")
    return value


def _section_indexes(lines: list[str], heading: str) -> list[int]:
    expected = f"## {heading}"
    return [index for index, line in enumerate(lines) if line.strip() == expected]


def _section_lines(lines: list[str], start: int) -> list[str]:
    values: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.strip():
            values.append(line)
    return values


@dataclass(frozen=True)
class TaskDocument:
    lines: tuple[str, ...]
    row_indexes: tuple[int, ...]
    rows: tuple[TaskRow, ...]

    def row(self, task_id: str) -> TaskRow:
        normalized = normalize_task_id(task_id)
        for row in self.rows:
            if row.task_id == normalized:
                return row
        raise TaskDocumentError(f"task {normalized} not found in task table")


def parse_task_document(text: str) -> TaskDocument:
    lines = tuple(text.splitlines())
    header_index = _find_header(lines)
    if header_index + 1 >= len(lines) or not _is_separator(lines[header_index + 1]):
        raise TaskDocumentError("task table separator is missing or malformed")

    rows: list[TaskRow] = []
    indexes: list[int] = []
    seen: set[str] = set()
    for index in range(header_index + 2, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            break
        cells = _parse_cells(line, label=f"task row at line {index + 1}")
        task_id = normalize_task_id(cells[0])
        if task_id in seen:
            raise TaskDocumentError(f"duplicate task ID: {task_id}")
        seen.add(task_id)
        status = normalize_status(cells[2])
        row = TaskRow(task_id, cells[1], status, cells[3], cells[4], cells[5])
        rows.append(row)
        indexes.append(index)
    if not rows:
        raise TaskDocumentError("task table has no task rows")
    return TaskDocument(lines=lines, row_indexes=tuple(indexes), rows=tuple(rows))


def update_task_document(
    text: str,
    task_id: str,
    *,
    status: str | None = None,
    owner: str | None = None,
    verification: str | None = None,
    evidence: str | None = None,
    history: str | None = None,
) -> str:
    document = parse_task_document(text)
    current = document.row(task_id)
    updates = {
        "status": normalize_status(status) if status is not None else current.status,
        "owner": _safe_cell(owner, "owner") if owner is not None else current.owner,
        "verification": _safe_cell(verification, "verification") if verification is not None else current.verification,
        "evidence": _safe_cell(evidence, "evidence") if evidence is not None else current.evidence,
    }
    updated = replace(current, **updates)
    lines = list(document.lines)
    row_index = document.row_indexes[document.rows.index(current)]
    lines[row_index] = _render_row(updated.cells())

    if history is not None:
        clean_history = _safe_history(history)
        history_line = f"- {clean_history}"
        if history_line not in lines:
            history_header = _find_history_header(lines)
            if history_header is None:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.extend(("## Task History", "", history_line))
            else:
                insert_at = len(lines)
                for index in range(history_header + 1, len(lines)):
                    if lines[index].startswith("## "):
                        insert_at = index
                        break
                while insert_at > history_header + 1 and not lines[insert_at - 1].strip():
                    insert_at -= 1
                lines.insert(insert_at, history_line)
                if insert_at + 1 < len(lines) and lines[insert_at + 1].startswith("## "):
                    lines.insert(insert_at + 1, "")

    result = "\n".join(lines).rstrip() + "\n"
    parse_task_document(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update one validated TASKS.md row atomically.")
    parser.add_argument("file", type=Path, help="Path to TASKS.md")
    parser.add_argument("--task", required=True, help="Task ID, such as T002")
    parser.add_argument("--status", choices=tuple(TASK_STATUSES.values()))
    parser.add_argument("--owner")
    parser.add_argument("--verification")
    parser.add_argument("--evidence")
    parser.add_argument("--history")
    parser.add_argument("--dry-run", action="store_true", help="Print a unified diff without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not any((args.status, args.owner, args.verification, args.evidence, args.history)):
        print("ERROR: provide at least one update value")
        return 2
    try:
        original = args.file.read_text(encoding="utf-8")
        updated = update_task_document(
            original,
            args.task,
            status=args.status,
            owner=args.owner,
            verification=args.verification,
            evidence=args.evidence,
            history=args.history,
        )
    except (OSError, TaskDocumentError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    if args.dry_run:
        diff = difflib.unified_diff(
            original.splitlines(True),
            updated.splitlines(True),
            fromfile=str(args.file),
            tofile=str(args.file),
        )
        print("".join(diff))
        return 0
    if updated == original:
        print(f"No changes: {args.file}")
        return 0
    atomic_write_text(args.file, updated)
    print(f"Updated: {args.file}")
    return 0


def normalize_status(value: str) -> str:
    normalized = re.sub(r"[_-]+", " ", value.strip().lower())
    normalized = re.sub(r"\s+", " ", normalized)
    try:
        return TASK_STATUSES[normalized]
    except KeyError as exc:
        raise TaskDocumentError(f"invalid task status: {value!r}") from exc


def _find_header(lines: tuple[str, ...]) -> int:
    for index, line in enumerate(lines):
        try:
            cells = _parse_cells(line, label=f"line {index + 1}")
        except TaskDocumentError:
            continue
        if cells == EXPECTED_HEADER:
            return index
    raise TaskDocumentError("task table header not found")


def _find_history_header(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == "## Task History":
            return index
    return None


def _is_separator(line: str) -> bool:
    try:
        cells = _parse_cells(line, label="separator")
    except TaskDocumentError:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell) is not None for cell in cells)


def _parse_cells(line: str, *, label: str) -> tuple[str, ...]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise TaskDocumentError(f"{label} must start and end with '|'")
    parts = stripped[1:-1].split("|")
    if len(parts) != len(EXPECTED_HEADER):
        raise TaskDocumentError(f"{label} must contain exactly {len(EXPECTED_HEADER)} columns")
    return tuple(part.strip() for part in parts)


def _render_row(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(_safe_cell(cell, "task cell") for cell in cells) + " |"


def _safe_cell(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise TaskDocumentError(f"{label} cannot be empty")
    if "|" in clean or "\n" in clean or "\r" in clean:
        raise TaskDocumentError(f"{label} cannot contain table delimiters or newlines")
    return clean


def _safe_history(value: str) -> str:
    clean = value.strip()
    if not clean or "\n" in clean or "\r" in clean:
        raise TaskDocumentError("history must be one non-empty line")
    return clean


if __name__ == "__main__":
    raise SystemExit(main())
