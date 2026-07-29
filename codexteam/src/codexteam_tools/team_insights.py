from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .contracts import AGENT_ROLES, ResultValidationError, validate_result
from .paths import (
    PathValidationError,
    contained_path,
    normalize_task_id,
    validate_identifier,
)
from .repository_context import RepositoryContextReader
from .roles import RolePolicyError, load_role_policy
from .subagent_status import collect_subagent_status
from .tasks import TaskDocumentError, parse_task_document
from .team_context import TeamContextError, TeamContextReader, _parse_bullets, _parse_sections
from .test_gates import (
    GateConfigError,
    load_gate_config,
    validate_current_gate_record,
)

MAX_TASK_RESULTS = 50
MAX_ATTEMPT_TURNS = 20
MAX_COST_RESULTS = 20
COST_PHASES = ("all", "draft", "feedback", "final")
ATTENTION_ATTEMPT_STATUSES = {
    "blocked",
    "correction_needed",
    "failed",
    "interrupted",
    "stale",
    "timed_out",
}
COMPLETED_TASK_STATUSES = {"completed", "delivered", "done"}
_ROLE_LABELS = (
    ("feature planner", "feature_planner"),
    ("git steward", "git_steward"),
    ("test engineer", "tester"),
    ("ux designer", "ux_designer"),
    ("architect", "architect"),
    ("developer", "developer"),
    ("documenter", "documenter"),
    ("reviewer", "reviewer"),
    ("tester", "tester"),
    ("leader", "leader"),
    ("lead", "leader"),
)


class TeamInsightsReader:
    def __init__(
        self,
        context: TeamContextReader,
        repository: RepositoryContextReader,
    ) -> None:
        self.context = context
        self.repository = repository

    def get_project_overview(self, project: str) -> dict[str, Any]:
        root = self.context.project_root(project)
        tasks_path = self.context.required_file(root, "TASKS.md")
        rows, ledger_warning = _read_all_task_rows(
            tasks_path.read_text(encoding="utf-8")
        )
        state_path = self.context.optional_file(root, "PROJECT_STATE.md")
        current_path = self.context.optional_file(root, "CURRENT_TASK.md")
        state = (
            _parse_bullets(state_path.read_text(encoding="utf-8"))
            if state_path is not None
            else {}
        )
        current = (
            _parse_bullets(current_path.read_text(encoding="utf-8"))
            if current_path is not None
            else {}
        )
        attempts = collect_subagent_status(root)
        latest_by_task: dict[str, dict[str, Any]] = {}
        for attempt in attempts:
            latest_by_task.setdefault(attempt["task"], attempt)
        task_counts = Counter(row["status"] for row in rows)
        attempt_counts = Counter(str(attempt["status"]) for attempt in attempts)
        attention = [
            _attention_task(row, latest_by_task.get(row["task_id"]))
            for row in rows
            if _task_needs_attention(row, latest_by_task.get(row["task_id"]))
        ]
        active_task = current.get("task_id") or state.get("active_task")
        attention.sort(
            key=lambda item: (
                item["task_id"] != active_task,
                -_task_number(item["task_id"]),
            )
        )
        attention = attention[:10]
        running = [
            _compact_attempt(attempt)
            for attempt in attempts
            if attempt["status"] in {"running", "stale"}
        ][:10]

        gate_status = self.context.get_gate_status(project)
        gates = [
            {
                "gate": gate["gate"],
                "status": (gate["record"] or {}).get("status"),
                "current": gate["current"],
                "freshness_error": gate["freshness_error"],
                "completed_at": (gate["record"] or {}).get("completed_at"),
            }
            for gate in gate_status["gates"]
        ]
        source_paths = [tasks_path]
        if state_path is not None:
            source_paths.append(state_path)
        if current_path is not None:
            source_paths.append(current_path)
        sources = _merge_sources(
            [self.context.source(root, path) for path in source_paths],
            gate_status["sources"],
        )
        return {
            "project": project,
            "state": state,
            "active_task": active_task,
            "current": current,
            "task_counts": dict(sorted(task_counts.items())),
            "task_total": len(rows),
            "attempt_counts": dict(sorted(attempt_counts.items())),
            "running_or_stale_attempts": running,
            "attention": attention,
            "attention_total": sum(
                _task_needs_attention(row, latest_by_task.get(row["task_id"]))
                for row in rows
            ),
            "gates": gates,
            "git": self.repository.project_git_state(project),
            "ledger_warning": ledger_warning,
            "sources": sources,
        }

    def list_tasks(
        self,
        project: str,
        *,
        status: str | None = None,
        owner: str | None = None,
        milestone: str | None = None,
        attention_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_TASK_RESULTS
        ):
            raise TeamContextError(f"limit must be between 1 and {MAX_TASK_RESULTS}")
        root = self.context.project_root(project)
        tasks_path = self.context.required_file(root, "TASKS.md")
        rows, ledger_warning = _read_all_task_rows(
            tasks_path.read_text(encoding="utf-8")
        )
        attempts = collect_subagent_status(root)
        latest_by_task: dict[str, dict[str, Any]] = {}
        for attempt in attempts:
            latest_by_task.setdefault(attempt["task"], attempt)
        status_filter = status.casefold().strip() if status else None
        owner_filter = owner.casefold().strip() if owner else None
        milestone_filter = milestone.casefold().strip() if milestone else None
        selected: list[dict[str, Any]] = []
        for row in rows:
            latest = latest_by_task.get(row["task_id"])
            row_milestone = _milestone(row["description"])
            attention = _task_needs_attention(row, latest)
            if status_filter and row["status"].casefold() != status_filter:
                continue
            if owner_filter and owner_filter not in row["owner"].casefold():
                continue
            if milestone_filter and (row_milestone or "").casefold() != milestone_filter:
                continue
            if attention_only and not attention:
                continue
            selected.append(
                {
                    "task_id": row["task_id"],
                    "description": row["description"],
                    "milestone": row_milestone,
                    "status": row["status"],
                    "owner": row["owner"],
                    "verification": row["verification"],
                    "evidence": _truncate(row["evidence"], 240),
                    "attention": attention,
                    "latest_attempt": _compact_attempt(latest) if latest else None,
                }
            )
        return {
            "project": project,
            "filters": {
                "status": status,
                "owner": owner,
                "milestone": milestone,
                "attention_only": attention_only,
            },
            "matched": len(selected),
            "tasks": selected[:limit],
            "truncated": len(selected) > limit,
            "ledger_warning": ledger_warning,
            "sources": [self.context.source(root, tasks_path)],
        }

    def get_task_context(
        self,
        project: str,
        task_id: str,
        *,
        role: str | None = None,
    ) -> dict[str, Any]:
        root = self.context.project_root(project)
        normalized = normalize_task_id(task_id)
        handoff = self.context.get_task_handoff(project, normalized)
        section_map = {
            section["title"].casefold(): section["text"]
            for section in handoff["sections"]
        }
        task_rows, ledger_warning = _read_all_task_rows(
            self.context.required_file(root, "TASKS.md").read_text(encoding="utf-8")
        )
        rows_by_id = {row["task_id"]: row for row in task_rows}
        dependency_text = "\n".join(
            text
            for title, text in section_map.items()
            if "dependenc" in title or "prerequisite" in title
        )
        dependency_ids = [
            dependency
            for dependency in dict.fromkeys(
                re.findall(r"\bT[0-9]{3,6}\b", dependency_text, re.IGNORECASE)
            )
            if dependency.upper() != normalized
        ]
        dependencies = []
        for dependency in dependency_ids:
            dependency_id = dependency.upper()
            row = rows_by_id.get(dependency_id)
            dependencies.append(
                {
                    "task_id": dependency_id,
                    "status": row["status"] if row else "Missing",
                    "description": row["description"] if row else None,
                    "blocking": row is None
                    or row["status"].casefold() not in COMPLETED_TASK_STATUSES,
                }
            )
        allowed_paths = _extract_allowed_paths(handoff["sections"])
        attempts = collect_subagent_status(root)
        selected_role = role or _infer_role(handoff, attempts, normalized)
        policy, policy_source, policy_warning = _role_policy(selected_role)

        concurrent: list[dict[str, Any]] = []
        stale_attempts = [
            _compact_attempt(attempt)
            for attempt in attempts
            if attempt["task"] != normalized and attempt["status"] == "stale"
        ][:5]
        for attempt in attempts:
            if attempt["task"] == normalized or attempt["status"] != "running":
                continue
            conflicts = self._attempt_path_conflicts(
                root,
                allowed_paths,
                attempt["task"],
            )
            concurrent.append(
                {
                    **_compact_attempt(attempt),
                    "possible_path_conflicts": conflicts,
                }
            )
            if len(concurrent) >= 10:
                break

        gate_config = load_gate_config(root)
        gate_config_path = self.context.required_file(
            root,
            "management/TEST_GATES.toml",
        )
        architecture_sources = self._architecture_sources(root, handoff["sections"])
        sources = _merge_sources(
            handoff["sources"],
            [self.context.source(root, gate_config_path)],
            architecture_sources,
            [policy_source] if policy_source else [],
        )
        warnings = [
            warning
            for warning in (ledger_warning, policy_warning)
            if warning is not None
        ]
        return {
            "project": project,
            "task_id": normalized,
            "title": handoff["title"],
            "ledger": handoff["ledger"],
            "sections": handoff["sections"],
            "allowed_paths": allowed_paths,
            "dependencies": dependencies,
            "blocking_dependencies": [
                item for item in dependencies if item["blocking"]
            ],
            "role": selected_role,
            "role_policy": policy,
            "concurrent_attempts": concurrent,
            "stale_attempts": stale_attempts,
            "architecture_references": [
                source["path"] for source in architecture_sources
            ],
            "gates": {
                "verification_paths": list(gate_config.verification_paths),
                "development": [
                    list(command)
                    for command in gate_config.development_commands
                ],
                "integration": [
                    list(command)
                    for command in gate_config.integration_commands
                ],
            },
            "warnings": warnings,
            "sources": sources,
        }

    def get_attempt_summary(
        self,
        project: str,
        task_id: str,
        attempt_id: str,
        *,
        max_turns: int = 5,
    ) -> dict[str, Any]:
        if (
            not isinstance(max_turns, int)
            or isinstance(max_turns, bool)
            or not 1 <= max_turns <= MAX_ATTEMPT_TURNS
        ):
            raise TeamContextError(
                f"max_turns must be between 1 and {MAX_ATTEMPT_TURNS}"
            )
        root = self.context.project_root(project)
        task = normalize_task_id(task_id)
        attempt = validate_identifier(attempt_id, label="attempt ID")
        attempt_dir = _find_attempt_dir(root, task, attempt)
        if attempt_dir is None:
            raise TeamContextError(f"attempt not found: {task}/{attempt}")
        session_path = attempt_dir / "session.json"
        turn_state_path = attempt_dir / "turn-state.json"
        session = _read_json_object(session_path)
        turn_state = _read_json_object(turn_state_path)
        status_record = next(
            (
                item
                for item in collect_subagent_status(root)
                if item["task"] == task and item["attempt"] == attempt
            ),
            None,
        )
        metric_paths = sorted((attempt_dir / "turns").glob("*.metrics.json"))
        metrics = [
            (path, _read_json_object(path))
            for path in metric_paths
            if path.is_file() and not path.is_symlink()
        ]
        metrics = [(path, value) for path, value in metrics if value]
        selected_metrics = metrics[-max_turns:]
        turns = [_compact_turn_metric(value) for _, value in selected_metrics]
        totals = _usage_totals(value for _, value in metrics)

        result_path = _attempt_result_path(root, task, attempt, session)
        result = _read_json_object(result_path) if result_path is not None else {}
        source_paths = [
            path
            for path in (session_path, turn_state_path, result_path)
            if path is not None and path.is_file() and not path.is_symlink()
        ]
        source_paths.extend(path for path, _ in selected_metrics)
        return {
            "project": project,
            "task_id": task,
            "attempt_id": attempt,
            "status": _compact_attempt(status_record) if status_record else None,
            "session": {
                key: session.get(key)
                for key in (
                    "team_id",
                    "agent_role",
                    "model_profile",
                    "model_provider",
                    "model_reasoning_effort",
                    "last_phase",
                    "last_status",
                    "turn_count",
                    "created_at",
                    "updated_at",
                    "final_result_path",
                )
            },
            "turns": turns,
            "turns_total": len(metrics),
            "turns_truncated": len(metrics) > len(selected_metrics),
            "usage_delta_totals": totals,
            "result": _compact_result(result) if result else None,
            "sources": [
                self.context.source(root, path)
                for path in dict.fromkeys(source_paths)
            ],
        }

    def validate_result_record(
        self,
        project: str,
        task_id: str,
        attempt_id: str,
        *,
        role: str | None = None,
    ) -> dict[str, Any]:
        root = self.context.project_root(project)
        task = normalize_task_id(task_id)
        attempt = validate_identifier(attempt_id, label="attempt ID")
        if role is not None and role not in AGENT_ROLES:
            raise TeamContextError(f"unsupported role: {role}")
        attempt_dir = _find_attempt_dir(root, task, attempt)
        session_path = attempt_dir / "session.json" if attempt_dir else None
        session = _read_json_object(session_path) if session_path else {}
        result_path = _attempt_result_path(root, task, attempt, session)
        if result_path is None or not result_path.is_file() or result_path.is_symlink():
            return {
                "project": project,
                "task_id": task,
                "attempt_id": attempt,
                "valid": False,
                "errors": ["result record is missing"],
                "result": None,
                "evidence": [],
                "sources": [],
            }
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "project": project,
                "task_id": task,
                "attempt_id": attempt,
                "valid": False,
                "errors": [f"invalid result JSON: {exc}"],
                "result": None,
                "evidence": [],
                "sources": [self.context.source(root, result_path)],
            }
        expected_role = role or session.get("agent_role")
        expected_team = session.get("team_id")
        errors: list[str] = []
        try:
            validate_result(
                raw,
                expected_task=task,
                expected_team=expected_team,
                expected_attempt=attempt,
                expected_role=expected_role,
            )
        except ResultValidationError as exc:
            errors.extend(exc.errors)

        evidence, evidence_sources, evidence_errors = self._evidence_status(root, raw)
        errors.extend(evidence_errors)
        sources = [self.context.source(root, result_path)]
        if session_path is not None and session_path.is_file() and not session_path.is_symlink():
            sources.append(self.context.source(root, session_path))
        sources.extend(evidence_sources)
        return {
            "project": project,
            "task_id": task,
            "attempt_id": attempt,
            "valid": not errors,
            "errors": errors,
            "expected": {
                "team_id": expected_team,
                "agent_role": expected_role,
            },
            "result": _compact_result(raw) if isinstance(raw, dict) else None,
            "evidence": evidence,
            "sources": _merge_sources(sources),
        }

    def get_cost_hotspots(
        self,
        project: str,
        *,
        task_id: str | None = None,
        phase: str = "all",
        limit: int = 10,
    ) -> dict[str, Any]:
        if task_id is not None:
            task_id = normalize_task_id(task_id)
        if phase not in COST_PHASES:
            raise TeamContextError(
                f"phase must be one of: {', '.join(COST_PHASES)}"
            )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_COST_RESULTS
        ):
            raise TeamContextError(f"limit must be between 1 and {MAX_COST_RESULTS}")
        root = self.context.project_root(project)
        metrics_root = root / ".codexteam" / "runtime" / "sessions"
        records: list[tuple[Path, dict[str, Any]]] = []
        files_scanned = 0
        bytes_scanned = 0
        if metrics_root.is_dir() and not metrics_root.is_symlink():
            for path in metrics_root.glob("*/*/*/turns/*.metrics.json"):
                if path.is_symlink() or not path.is_file():
                    continue
                files_scanned += 1
                bytes_scanned += path.stat().st_size
                value = _read_json_object(path)
                if not value:
                    continue
                if task_id is not None and value.get("task_id") != task_id:
                    continue
                turn = value.get("turn") if isinstance(value.get("turn"), dict) else {}
                if phase != "all" and turn.get("phase") != phase:
                    continue
                records.append((path, value))
        records.sort(
            key=lambda item: (
                -_integer(_usage_delta(item[1]).get("input_tokens")),
                -_integer(_usage_delta(item[1]).get("uncached_input_tokens")),
                str(item[1].get("task_id") or ""),
                str(item[1].get("attempt_id") or ""),
                _integer((item[1].get("turn") or {}).get("number")),
            )
        )
        selected = records[:limit]
        return {
            "project": project,
            "filters": {"task_id": task_id, "phase": phase},
            "metrics_files_scanned": files_scanned,
            "metrics_bytes_scanned": bytes_scanned,
            "matched_turns": len(records),
            "hotspots": [_compact_hotspot(value) for _, value in selected],
            "largest_commands": _largest_commands(records),
            "repeated_commands": _repeated_commands(records),
            "truncated": len(records) > limit,
            "sources": [
                self.context.source(root, path)
                for path, _ in selected
            ],
        }

    def _attempt_path_conflicts(
        self,
        root: Path,
        allowed_paths: list[str],
        task_id: str,
    ) -> list[dict[str, str]]:
        if not allowed_paths:
            return []
        try:
            handoff_path = self.context.required_file(
                root,
                f"management/tasks/{normalize_task_id(task_id)}.md",
            )
        except (PathValidationError, TeamContextError):
            return []
        _, sections = _parse_sections(handoff_path.read_text(encoding="utf-8"))
        other_paths = _extract_allowed_paths(sections)
        conflicts: list[dict[str, str]] = []
        for own in allowed_paths:
            for other in other_paths:
                if _patterns_overlap(own, other):
                    conflicts.append({"requested": own, "active": other})
                    if len(conflicts) >= 10:
                        return conflicts
        return conflicts

    def _architecture_sources(
        self,
        root: Path,
        sections: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        candidates = ["ARCHITECTURE.md", "DECISIONS.md"]
        text = "\n".join(section["text"] for section in sections)
        candidates.extend(
            match
            for match in re.findall(r"`([^`]+\.(?:md|toml|json))`", text)
            if match.startswith(("docs/architecture/", "docs/decisions/"))
        )
        sources = []
        for relative in dict.fromkeys(candidates):
            path = self.context.optional_file(root, relative)
            if path is not None:
                sources.append(self.context.source(root, path))
            if len(sources) >= 8:
                break
        return sources

    def _evidence_status(
        self,
        root: Path,
        result: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        if not isinstance(result, dict) or not isinstance(result.get("evidence"), list):
            return [], [], []
        evidence: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, item in enumerate(result["evidence"][:20]):
            if not isinstance(item, dict):
                continue
            artifact = item.get("artifact_ref")
            record = {
                "type": item.get("type"),
                "artifact_ref": artifact,
                "summary": _truncate(str(item.get("summary") or ""), 400),
                "exists": False,
            }
            if isinstance(artifact, str):
                try:
                    path = contained_path(root, artifact, label="evidence artifact")
                except PathValidationError as exc:
                    errors.append(f"evidence[{index}] is unsafe: {exc}")
                else:
                    if path.is_file() and not path.is_symlink():
                        record["exists"] = True
                        record["sha256"] = _sha256(path)
                        sources.append(self.context.source(root, path))
                        gate_match = re.fullmatch(
                            r"results/gates/(development|integration)\.json",
                            artifact,
                        )
                        if gate_match:
                            try:
                                validate_current_gate_record(root, gate_match.group(1))
                            except GateConfigError as exc:
                                record["current"] = False
                                record["freshness_error"] = str(exc)
                                errors.append(
                                    f"evidence[{index}] gate record is stale: {exc}"
                                )
                            else:
                                record["current"] = True
                    else:
                        errors.append(
                            f"evidence[{index}] artifact is missing or unsafe: {artifact}"
                        )
            evidence.append(record)
        return evidence, sources, errors


def _read_all_task_rows(text: str) -> tuple[list[dict[str, str]], str | None]:
    try:
        document = parse_task_document(text)
    except TaskDocumentError as exc:
        rows: list[dict[str, str]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|") or not stripped.endswith("|"):
                continue
            cells = tuple(part.strip() for part in stripped[1:-1].split("|"))
            if len(cells) != 6 or re.fullmatch(r"T[0-9]{3,6}", cells[0], re.IGNORECASE) is None:
                continue
            rows.append(
                {
                    "task_id": cells[0].upper(),
                    "description": cells[1],
                    "status": cells[2],
                    "owner": cells[3],
                    "verification": cells[4],
                    "evidence": cells[5],
                }
            )
        if not rows:
            raise
        return rows, f"TASKS.md full validation failed: {exc}; rows read exactly"
    return [
        {
            "task_id": row.task_id,
            "description": row.description,
            "status": row.status,
            "owner": row.owner,
            "verification": row.verification,
            "evidence": row.evidence,
        }
        for row in document.rows
    ], None


def _task_needs_attention(
    row: dict[str, str],
    latest_attempt: dict[str, Any] | None,
) -> bool:
    if row["status"].casefold() == "blocked":
        return True
    if row["status"].casefold() in COMPLETED_TASK_STATUSES:
        return False
    return (
        latest_attempt is not None
        and str(latest_attempt.get("status") or "").casefold()
        in ATTENTION_ATTEMPT_STATUSES
    )


def _attention_task(
    row: dict[str, str],
    latest_attempt: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "description": row["description"],
        "status": row["status"],
        "latest_attempt": _compact_attempt(latest_attempt) if latest_attempt else None,
    }


def _compact_attempt(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
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
            "result",
            "state_path",
        )
    }


def _milestone(description: str) -> str | None:
    match = re.search(r"\bM[0-9]+\b", description, re.IGNORECASE)
    return match.group(0).upper() if match else None


def _task_number(task_id: str) -> int:
    match = re.fullmatch(r"T([0-9]{3,6})", task_id)
    return int(match.group(1)) if match else 0


def _extract_allowed_paths(sections: list[dict[str, str]]) -> list[str]:
    text = "\n".join(
        section["text"]
        for section in sections
        if "allowed path" in section["title"].casefold()
    )
    paths = []
    for value in re.findall(r"`([^`]+)`", text):
        clean = value.strip()
        if clean and not clean.startswith(("/", "\\")) and ".." not in clean.split("/"):
            paths.append(clean)
    return list(dict.fromkeys(paths))[:30]


def _infer_role(
    handoff: dict[str, Any],
    attempts: list[dict[str, Any]],
    task_id: str,
) -> str | None:
    matching = [attempt for attempt in attempts if attempt["task"] == task_id]
    if matching and matching[0].get("role") in AGENT_ROLES:
        return str(matching[0]["role"])
    text = " ".join(
        [
            str(handoff.get("ledger", {}).get("owner") or ""),
            *[
                section["text"]
                for section in handoff["sections"]
                if "responsible" in section["title"].casefold()
            ],
        ]
    ).casefold()
    for label, role in _ROLE_LABELS:
        if label in text:
            return role
    return None


def _role_policy(
    role: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if role is None:
        return None, None, "role could not be inferred; pass role explicitly"
    if role not in AGENT_ROLES:
        return None, None, f"unsupported inferred role: {role}"
    try:
        policy = load_role_policy(role)
    except (OSError, RolePolicyError) as exc:
        return None, None, f"role policy unavailable: {exc}"
    source = {
        "path": f"role-policy/{policy.source_path.name}",
        "sha256": _sha256(policy.source_path),
        "bytes": policy.source_path.stat().st_size,
    }
    return (
        {
            "role": policy.role,
            "name": policy.name,
            "description": policy.description,
            "default_profile": policy.default_profile,
            "default_reasoning_effort": policy.default_reasoning_effort,
            "sandbox_mode": policy.sandbox_mode,
            "skill_files": list(policy.skill_files),
            "allowed_change_patterns": list(policy.allowed_change_patterns),
            "denied_change_patterns": list(policy.denied_change_patterns),
            "allowed_evidence_types": list(policy.allowed_evidence_types),
            "digest": policy.digest,
        },
        source,
        None,
    )


def _patterns_overlap(left: str, right: str) -> bool:
    if left == right or left in {"*", "**"} or right in {"*", "**"}:
        return True
    if not _has_glob(left) and fnmatch.fnmatchcase(left, right):
        return True
    if not _has_glob(right) and fnmatch.fnmatchcase(right, left):
        return True
    left_prefix = re.split(r"[*?\[]", left, maxsplit=1)[0]
    right_prefix = re.split(r"[*?\[]", right, maxsplit=1)[0]
    return bool(left_prefix and right_prefix) and (
        left_prefix.startswith(right_prefix) or right_prefix.startswith(left_prefix)
    )


def _has_glob(value: str) -> bool:
    return any(character in value for character in "*?[")


def _find_attempt_dir(root: Path, task_id: str, attempt_id: str) -> Path | None:
    sessions = root / ".codexteam" / "runtime" / "sessions"
    if not sessions.is_dir() or sessions.is_symlink():
        return None
    matches = [
        path
        for path in sessions.glob(f"*/{task_id}/{attempt_id}")
        if path.is_dir() and not path.is_symlink()
    ]
    if len(matches) > 1:
        raise TeamContextError(
            f"multiple runtime attempts match {task_id}/{attempt_id}"
        )
    return matches[0] if matches else None


def _read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or path.is_symlink() or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _attempt_result_path(
    root: Path,
    task_id: str,
    attempt_id: str,
    session: dict[str, Any],
) -> Path | None:
    value = session.get("final_result_path")
    relative = value if isinstance(value, str) and value else f"results/{task_id}-{attempt_id}.json"
    try:
        path = contained_path(root, relative, label="result record")
    except PathValidationError:
        return None
    return path


def _compact_turn_metric(value: dict[str, Any]) -> dict[str, Any]:
    turn = value.get("turn") if isinstance(value.get("turn"), dict) else {}
    activity = value.get("activity") if isinstance(value.get("activity"), dict) else {}
    events = value.get("events") if isinstance(value.get("events"), dict) else {}
    return {
        "number": turn.get("number"),
        "phase": turn.get("phase"),
        "completed": turn.get("completed"),
        "duration_seconds": turn.get("duration_seconds"),
        "usage_delta": _usage_delta(value),
        "activity": {
            key: activity.get(key)
            for key in (
                "tool_calls",
                "failed_tool_calls",
                "command_calls",
                "failed_command_calls",
                "edit_events",
                "command_output_bytes",
                "max_command_output_bytes",
            )
        },
        "last_error": events.get("last_error"),
    }


def _usage_delta(value: dict[str, Any]) -> dict[str, Any]:
    usage = value.get("usage")
    if not isinstance(usage, dict):
        return {}
    delta = usage.get("delta")
    return delta if isinstance(delta, dict) else {}


def _usage_totals(values: Any) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for value in values:
        for key, amount in _usage_delta(value).items():
            if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
                totals[key] += amount
    return dict(sorted(totals.items()))


def _compact_result(value: dict[str, Any]) -> dict[str, Any]:
    output = value.get("output") if isinstance(value.get("output"), dict) else {}
    return {
        "status": value.get("status"),
        "summary": _truncate(str(value.get("summary") or ""), 1_000),
        "agent_role": value.get("agent_role"),
        "team_id": value.get("team_id"),
        "produced_at": value.get("produced_at"),
        "exit_code": output.get("exit_code"),
        "duration_seconds": output.get("duration_seconds"),
        "file_changes": [
            {
                "action": item.get("action"),
                "path": item.get("path"),
            }
            for item in value.get("file_changes", [])[:30]
            if isinstance(item, dict)
        ],
        "errors": [_truncate(str(item), 500) for item in value.get("errors", [])[:10]],
        "warnings": [_truncate(str(item), 500) for item in value.get("warnings", [])[:10]],
        "limitations": [
            _truncate(str(item), 500) for item in value.get("limitations", [])[:10]
        ],
        "requested_followups": value.get("requested_followups", [])[:10],
    }


def _compact_hotspot(value: dict[str, Any]) -> dict[str, Any]:
    turn = value.get("turn") if isinstance(value.get("turn"), dict) else {}
    activity = value.get("activity") if isinstance(value.get("activity"), dict) else {}
    events = value.get("events") if isinstance(value.get("events"), dict) else {}
    return {
        "task_id": value.get("task_id"),
        "attempt_id": value.get("attempt_id"),
        "role": value.get("agent_role"),
        "profile": value.get("model_profile"),
        "turn": turn.get("number"),
        "phase": turn.get("phase"),
        "duration_seconds": turn.get("duration_seconds"),
        "usage_delta": _usage_delta(value),
        "tool_calls": activity.get("tool_calls"),
        "failed_tool_calls": activity.get("failed_tool_calls"),
        "command_calls": activity.get("command_calls"),
        "command_output_bytes": activity.get("command_output_bytes"),
        "last_error": events.get("last_error"),
    }


def _largest_commands(
    records: list[tuple[Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for _, value in records:
        activity = value.get("activity")
        turn = value.get("turn")
        if not isinstance(activity, dict) or not isinstance(turn, dict):
            continue
        for command in activity.get("largest_commands", []):
            if not isinstance(command, dict):
                continue
            commands.append(
                {
                    "task_id": value.get("task_id"),
                    "attempt_id": value.get("attempt_id"),
                    "turn": turn.get("number"),
                    "phase": turn.get("phase"),
                    "fingerprint": command.get("fingerprint"),
                    "preview": command.get("preview"),
                    "output_bytes": command.get("output_bytes"),
                    "exit_code": command.get("exit_code"),
                    "failed": command.get("failed"),
                }
            )
    commands.sort(
        key=lambda item: (
            -_integer(item.get("output_bytes")),
            str(item.get("fingerprint") or ""),
        )
    )
    return commands[:3]


def _repeated_commands(
    records: list[tuple[Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for _, value in records:
        activity = value.get("activity")
        if not isinstance(activity, dict):
            continue
        for command in activity.get("repeated_commands", []):
            if not isinstance(command, dict):
                continue
            fingerprint = command.get("fingerprint")
            count = command.get("count")
            if not isinstance(fingerprint, str) or not isinstance(count, int):
                continue
            current = grouped.setdefault(
                fingerprint,
                {
                    "fingerprint": fingerprint,
                    "preview": command.get("preview"),
                    "repeat_count": 0,
                    "turn_occurrences": 0,
                },
            )
            current["repeat_count"] += count
            current["turn_occurrences"] += 1
    values = list(grouped.values())
    values.sort(
        key=lambda item: (
            -item["repeat_count"],
            -item["turn_occurrences"],
            item["fingerprint"],
        )
    )
    return values[:10]


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _merge_sources(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for source in group:
            path = source.get("path")
            if isinstance(path, str):
                merged[path] = source
    return [merged[path] for path in sorted(merged)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
