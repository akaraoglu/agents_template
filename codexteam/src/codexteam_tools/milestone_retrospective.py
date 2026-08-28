from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .contracts import ResultValidationError, validate_result
from .delegation import load_delegation
from .execution_registry import ExecutionRegistryError, load_execution_registry
from .execution_spec import ExecutionSpecError, load_execution_spec
from .files import atomic_write_text, create_json
from .paths import normalize_task_id, safe_relative_path, validate_identifier
from .repository_binding import RepositoryBinding, RepositoryBindingError, load_repository_binding
from .tasks import TaskDocumentError, parse_task_document
from .test_gates import GateConfigError, validate_gate_record
from .turn_metrics import load_summary


SCHEMA_VERSION = "1.0"
DEFAULT_PROFILE = "qwen38-27b"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
DISPOSITIONS = ("NO_CHANGE", "PROPOSALS_RECORDED")
DECISIONS = {"approve": "Approved", "reject": "Rejected", "defer": "Deferred"}
CANDIDATE_TYPES = ("instruction", "skill", "template", "contract", "tool", "system")
MAX_TASKS = 50
MAX_ATTEMPTS = 20
MAX_TURNS = 50
MAX_SIGNALS = 999
MAX_JSON_BYTES = 1_000_000
MAX_TEXT_BYTES = 2_000_000
MAX_COMMIT_PATHS = 1_000
MAX_COMMIT_BYTES = 50_000_000
MAX_GATE_MANIFEST_PATHS = 10_000
MAX_GATE_MANIFEST_BYTES = 100_000_000
MAX_MODEL_PROMPT_CHARS = 128_000
MAX_MODEL_RESPONSE_BYTES = 64 * 1024
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024
HEX64 = re.compile(r"^[a-f0-9]{64}$")
HEX_OBJECT = re.compile(r"^[a-f0-9]{40,64}$")
METRIC_NAME = re.compile(r"^(\d+)-(draft|feedback|final)\.metrics\.json$")
PROPOSAL_ID = re.compile(
    r"^IMP-[A-Z0-9]+(?:-[A-Z0-9]+)*-[A-F0-9]{16}-[0-9]{3}$"
)
RFC3339_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
HARD_FINDING_MARKERS = {
    "[unsupported-acceptance]": ("unsupported-acceptance", "contract"),
    "[evidence-integrity]": ("evidence-integrity", "contract"),
    "[scope-violation]": ("scope-violation", "system"),
}


class RetrospectiveError(ValueError):
    pass


class _RoundError(RetrospectiveError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def analyze_milestone(
    control_root: str | Path,
    *,
    boundary_id: str,
    task_ids: tuple[str, ...] | list[str],
    commit_record: str | None = None,
    work_root: str | Path | None = None,
    repo_id: str | None = None,
    commit: str | None = None,
    profile: str = DEFAULT_PROFILE,
    without_model: bool = False,
    apply: bool = False,
    model_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze one milestone. Invalid round evidence is returned as BLOCKED."""
    root = _exact_safe_root(control_root, "control root")
    boundary = validate_identifier(boundary_id, label="boundary ID")
    tasks = tuple(normalize_task_id(item) for item in task_ids)
    if not tasks or len(tasks) > MAX_TASKS or len(tasks) != len(set(tasks)):
        raise RetrospectiveError(f"tasks must contain 1-{MAX_TASKS} unique task IDs")
    split = (work_root, repo_id, commit)
    if any(value is not None for value in split) and not all(value is not None for value in split):
        raise RetrospectiveError(
            "split-root analysis requires --work-root, --repo-id, and --commit together"
        )
    if all(value is not None for value in split) and commit_record is not None:
        raise RetrospectiveError("--commit-record is supported only in same-root mode")

    try:
        if apply:
            with _project_lock(root):
                return _analyze_round(
                    root, boundary, tasks, commit_record, work_root, repo_id, commit,
                    profile, without_model, apply, model_runner,
                )
        return _analyze_round(
            root, boundary, tasks, commit_record, work_root, repo_id, commit,
            profile, without_model, apply, model_runner,
        )
    except Exception as exc:
        code = exc.code if isinstance(exc, _RoundError) else _failure_code(exc)
        message = (
            str(exc)
            if isinstance(exc, RetrospectiveError)
            else f"{exc.__class__.__name__} interrupted retrospective analysis"
        )
        return _blocked(
            boundary,
            tasks,
            code,
            message,
            artifact_root=(
                str(_artifact_root(root, boundary))
                if code == "backlog_publication_pending"
                else None
            ),
        )


def _analyze_round(
    root: Path,
    boundary: str,
    tasks: tuple[str, ...],
    commit_record: str | None,
    work_root: str | Path | None,
    repo_id: str | None,
    commit: str | None,
    profile: str,
    without_model: bool,
    apply: bool,
    model_runner: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    binding: RepositoryBinding | None = None
    if work_root is not None:
        try:
            _exact_safe_root(work_root, "work root")
            binding = load_repository_binding(root, work_root, str(repo_id))
            _exact_safe_root(binding.git_root, "Git root")
        except RetrospectiveError as exc:
            raise _RoundError("repository_identity", str(exc)) from exc
        except (OSError, RepositoryBindingError, ValueError) as exc:
            raise _RoundError("repository_identity", "repository binding validation failed") from exc
    work = binding.work_root if binding else _exact_git_root(root)
    git_root = binding.git_root if binding else work

    task_evidence, sources = _collect_tasks(root, work, binding, tasks)
    commit_evidence, commit_sources = _collect_commit(
        root, work, git_root, binding, boundary, tasks, commit_record, commit,
        _terminal_gate_digest(task_evidence),
    )
    sources.extend(commit_sources)
    lead_usage = _collect_lead_metrics(root, tasks, sources)
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "project": {"id": root.name},
        "repository": {
            "id": binding.repo_id if binding else "control-root",
            "mode": "split-root" if binding else "same-root",
            **({"git_prefix": binding.git_prefix} if binding else {}),
        },
        "boundary_id": boundary,
        "task_ids": list(tasks),
        "tasks": task_evidence,
        "commit": commit_evidence,
        "lead_usage": lead_usage,
        "source_digests": sorted(sources, key=lambda item: item["ref"]),
    }
    signals = qualify_signals(evidence)
    proposals = _build_proposals(boundary, signals)
    disposition = "PROPOSALS_RECORDED" if proposals else "NO_CHANGE"
    destination = _artifact_root(root, boundary)

    _update_backlog(root, proposals, write=False)
    existing = _existing_retrospective(root, destination, evidence, signals, proposals)
    if existing is not None:
        backlog_changed = False
        if apply:
            backlog_changed = _update_backlog(root, proposals, write=True)
        return _analysis_response(
            existing,
            destination,
            apply,
            idempotent=not backlog_changed,
            mutated=backlog_changed,
        )

    advisory = None
    if not without_model:
        try:
            advisory = run_advisory_analysis(
                evidence, signals, profile=profile, runner=model_runner
            )
        except Exception as exc:
            raise _RoundError("model_failure", "local advisory analysis failed") from exc
    analysis = {
        "schema_version": SCHEMA_VERSION,
        "boundary_id": boundary,
        "evidence_digest": _digest(evidence),
        "disposition": disposition,
        "signals": signals,
        "proposals": proposals,
        "advisory_model": advisory,
    }
    validate_retrospective(analysis)
    report = _render_report(analysis)
    if apply:
        _publish_artifacts(root, destination, evidence, analysis, report)
        try:
            _update_backlog(root, proposals, write=True)
        except Exception as exc:
            raise _RoundError(
                "backlog_publication_pending",
                "retrospective artifacts were published; rerun the same boundary to finish backlog insertion",
            ) from exc
    return _analysis_response(analysis, destination, apply, idempotent=False)


def decide_proposal(
    control_root: str | Path,
    *,
    boundary_id: str,
    proposal_id: str,
    decision: str,
    approver: str,
    reason: str,
    human_approved: bool,
    apply: bool = False,
) -> dict[str, Any]:
    root = _exact_safe_root(control_root, "control root")
    boundary = validate_identifier(boundary_id, label="boundary ID")
    if not PROPOSAL_ID.fullmatch(proposal_id):
        raise RetrospectiveError(f"invalid proposal ID: {proposal_id!r}")
    if decision not in DECISIONS:
        raise RetrospectiveError("decision must be approve, reject, or defer")
    clean_approver = _human_text(approver, "approver", 200)
    clean_reason = _human_text(reason, "reason", 2_000)
    if apply and human_approved is not True:
        raise RetrospectiveError("disposition apply requires explicit human_approved=True")

    try:
        if apply:
            with _project_lock(root):
                return _decide_round(
                    root, boundary, proposal_id, decision, clean_approver,
                    clean_reason, True,
                )
        return _decide_round(
            root, boundary, proposal_id, decision, clean_approver,
            clean_reason, False,
        )
    except RetrospectiveError:
        raise
    except Exception as exc:
        raise RetrospectiveError(str(exc)) from exc


def _decide_round(
    root: Path,
    boundary: str,
    proposal_id: str,
    decision: str,
    approver: str,
    reason: str,
    apply: bool,
) -> dict[str, Any]:
    destination = _artifact_root(root, boundary)
    if destination.is_symlink() or not destination.is_dir():
        raise RetrospectiveError("retrospective boundary is missing or unsafe")
    analysis = _read_json_file(
        _safe_existing_file(root, destination / "analysis.json", "analysis", MAX_JSON_BYTES),
        "analysis",
    )
    validate_retrospective(analysis)
    if analysis["boundary_id"] != boundary:
        raise RetrospectiveError("retrospective boundary identity mismatch")
    evidence = _read_json_file(
        _safe_existing_file(root, destination / "evidence.json", "evidence", MAX_JSON_BYTES),
        "evidence",
    )
    if _digest(evidence) != analysis["evidence_digest"]:
        raise RetrospectiveError("retrospective evidence digest mismatch")
    reconstructed_signals = qualify_signals(evidence)
    reconstructed_proposals = _build_proposals(boundary, reconstructed_signals)
    if (
        reconstructed_signals != analysis["signals"]
        or reconstructed_proposals != analysis["proposals"]
    ):
        raise RetrospectiveError("retrospective analysis does not match deterministic evidence")
    proposal = next(
        (item for item in analysis["proposals"] if item["proposal_id"] == proposal_id),
        None,
    )
    if proposal is None:
        raise RetrospectiveError(f"proposal {proposal_id} does not belong to {boundary}")

    backlog_path, backlog = _load_backlog(root)
    expected_block = _proposal_block(proposal)
    current_block = _extract_proposal_block(backlog, proposal_id)
    if current_block is None or not _proposal_block_matches(
        root, current_block, expected_block, boundary, proposal_id
    ):
        raise RetrospectiveError(f"backlog proposal {proposal_id} is missing or conflicting")

    disposition_path = destination / "dispositions" / f"{proposal_id}.json"
    if disposition_path.parent.is_symlink() or not disposition_path.parent.is_dir():
        raise RetrospectiveError("dispositions directory is missing or unsafe")
    base = {
        "schema_version": SCHEMA_VERSION,
        "boundary_id": boundary,
        "proposal_id": proposal_id,
        "proposal_sha256": _digest(proposal),
        "decision": decision,
        "status": DECISIONS[decision],
        "approver": approver,
        "reason": reason,
        "approval_scope": "planning-only" if decision == "approve" else "not-approved",
        "creates_task": False,
        "grants_implementation_authority": False,
    }
    existing_record = None
    if disposition_path.exists() or disposition_path.is_symlink():
        safe = _safe_existing_file(root, disposition_path, "disposition", MAX_JSON_BYTES)
        existing_record = _read_json_file(safe, "disposition")
        validate_disposition(existing_record)
        if any(existing_record.get(key) != value for key, value in base.items()):
            raise RetrospectiveError(f"proposal {proposal_id} already has a conflicting disposition")

    if not apply:
        if existing_record is not None:
            raise RetrospectiveError(f"proposal {proposal_id} already has a disposition")
        return {**base, "applied": False, "mutates": False}

    if existing_record is None:
        record = {**base, "decided_at": _utc_now()}
        validate_disposition(record)
        try:
            create_json(disposition_path, record)
        except FileExistsError:
            raced = _read_json_file(
                _safe_existing_file(root, disposition_path, "disposition", MAX_JSON_BYTES),
                "disposition",
            )
            validate_disposition(raced)
            if any(raced.get(key) != value for key, value in base.items()):
                raise RetrospectiveError("concurrent conflicting disposition")
            record = raced
    else:
        record = existing_record

    record_ref = disposition_path.relative_to(root).as_posix()
    updated_block = _set_disposition(expected_block, record["status"], record_ref)
    latest = backlog_path.read_text(encoding="utf-8")
    latest_block = _extract_proposal_block(latest, proposal_id)
    if latest_block == updated_block:
        return {**record, "applied": True, "idempotent": True, "record_ref": record_ref}
    if latest_block != expected_block:
        raise RetrospectiveError("backlog changed before disposition update")
    assert latest_block is not None
    atomic_write_text(backlog_path, latest.replace(latest_block, updated_block, 1))
    return {**record, "applied": True, "idempotent": existing_record is not None, "record_ref": record_ref}


def validate_retrospective(value: Any) -> dict[str, Any]:
    required = {
        "schema_version", "boundary_id", "evidence_digest", "disposition",
        "signals", "proposals", "advisory_model",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise RetrospectiveError("retrospective fields do not match the strict contract")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise RetrospectiveError("retrospective schema_version must be '1.0'")
    boundary = validate_identifier(value.get("boundary_id", ""), label="boundary ID")
    if value.get("boundary_id") != boundary:
        raise RetrospectiveError("retrospective boundary_id must be canonical")
    if not isinstance(value.get("evidence_digest"), str) or not HEX64.fullmatch(value["evidence_digest"]):
        raise RetrospectiveError("retrospective evidence_digest is invalid")
    if value.get("disposition") not in DISPOSITIONS:
        raise RetrospectiveError("retrospective disposition is invalid")
    signals = value.get("signals")
    proposals = value.get("proposals")
    if not isinstance(signals, list) or len(signals) > MAX_SIGNALS:
        raise RetrospectiveError("retrospective signals are invalid")
    if not isinstance(proposals, list) or len(proposals) > MAX_SIGNALS:
        raise RetrospectiveError("retrospective proposals are invalid")
    keys = set()
    for signal in signals:
        _validate_signal(signal)
        if signal["recurrence_key"] in keys:
            raise RetrospectiveError("retrospective contains duplicate signal keys")
        keys.add(signal["recurrence_key"])
    ids = set()
    for proposal in proposals:
        validate_proposal(proposal)
        if proposal["proposal_id"] in ids or proposal["recurrence_key"] not in keys:
            raise RetrospectiveError("retrospective proposals are duplicate or unqualified")
        if proposal["boundary_id"] != value["boundary_id"]:
            raise RetrospectiveError("proposal boundary does not match retrospective")
        ids.add(proposal["proposal_id"])
    if (value["disposition"] == "NO_CHANGE") != (not proposals):
        raise RetrospectiveError("retrospective disposition does not match proposals")
    proposal_keys = [proposal["recurrence_key"] for proposal in proposals]
    if len(signals) != len(proposals) or set(proposal_keys) != keys:
        raise RetrospectiveError("every qualified signal requires exactly one proposal")
    advisory = value.get("advisory_model")
    if advisory is not None:
        _validate_advisory(advisory, keys)
    return value


def validate_proposal(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "proposal_id", "boundary_id", "recurrence_key",
        "category", "scope", "impact", "confidence", "evidence", "trigger",
        "expected_gain", "validation", "rollback", "status", "human_disposition",
        "creates_task", "grants_implementation_authority",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise RetrospectiveError("proposal fields do not match the strict contract")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise RetrospectiveError("proposal schema_version must be '1.0'")
    if not isinstance(value.get("proposal_id"), str) or not PROPOSAL_ID.fullmatch(value["proposal_id"]):
        raise RetrospectiveError("proposal_id is invalid")
    boundary = validate_identifier(value.get("boundary_id", ""), label="boundary ID")
    if value.get("boundary_id") != boundary:
        raise RetrospectiveError("proposal boundary_id must be canonical")
    if not _short_text(value.get("recurrence_key"), 300):
        raise RetrospectiveError("proposal recurrence_key is invalid")
    if value.get("category") not in CANDIDATE_TYPES:
        raise RetrospectiveError("proposal category is invalid")
    if value.get("impact") not in {"medium", "high"}:
        raise RetrospectiveError("proposal impact is invalid")
    if value.get("confidence") not in {"medium", "high"}:
        raise RetrospectiveError("proposal confidence is invalid")
    for field, limit in (
        ("scope", 300), ("trigger", 1_000), ("expected_gain", 1_000),
        ("validation", 1_000), ("rollback", 1_000),
    ):
        if not _short_text(value.get(field), limit):
            raise RetrospectiveError(f"proposal {field} is invalid")
    _validate_refs(value.get("evidence"), "proposal evidence")
    if value.get("status") != "Proposed" or value.get("human_disposition") != "None":
        raise RetrospectiveError("proposal must remain Proposed with no human disposition")
    if value.get("creates_task") is not False or value.get("grants_implementation_authority") is not False:
        raise RetrospectiveError("proposal cannot create a task or implementation authority")
    return value


def validate_disposition(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "boundary_id", "proposal_id", "proposal_sha256",
        "decision", "status", "approver", "reason", "decided_at",
        "approval_scope", "creates_task", "grants_implementation_authority",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise RetrospectiveError("disposition fields do not match the strict contract")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise RetrospectiveError("disposition schema_version must be '1.0'")
    boundary = validate_identifier(value.get("boundary_id", ""), label="boundary ID")
    if value.get("boundary_id") != boundary:
        raise RetrospectiveError("disposition boundary_id must be canonical")
    if not isinstance(value.get("proposal_id"), str) or not PROPOSAL_ID.fullmatch(value["proposal_id"]):
        raise RetrospectiveError("disposition proposal_id is invalid")
    if not isinstance(value.get("proposal_sha256"), str) or not HEX64.fullmatch(value["proposal_sha256"]):
        raise RetrospectiveError("disposition proposal_sha256 is invalid")
    decision = value.get("decision")
    if decision not in DECISIONS or value.get("status") != DECISIONS.get(decision):
        raise RetrospectiveError("disposition decision and status do not match")
    if not _short_text(value.get("approver"), 200) or not _short_text(value.get("reason"), 2_000):
        raise RetrospectiveError("disposition approver or reason is invalid")
    if not _timestamp(value.get("decided_at")):
        raise RetrospectiveError("disposition decided_at is invalid")
    expected_scope = "planning-only" if decision == "approve" else "not-approved"
    if value.get("approval_scope") != expected_scope:
        raise RetrospectiveError("disposition approval_scope is invalid")
    if value.get("creates_task") is not False or value.get("grants_implementation_authority") is not False:
        raise RetrospectiveError("disposition cannot create a task or implementation authority")
    return value


def qualify_signals(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    observations: dict[str, list[tuple[str, str, str, str, bool]]] = defaultdict(list)
    failed_turns: list[tuple[str, str]] = []
    mcp_fallbacks: list[tuple[str, str]] = []
    command_counts: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    warning_tasks: dict[str, set[str]] = defaultdict(set)
    warning_refs: dict[str, list[str]] = defaultdict(list)

    for task in evidence.get("tasks", []):
        task_id = task["task_id"]
        attempts = task["attempts"]
        if len(attempts) > 1:
            observations["correction:replacement-attempt"].append(
                (task_id, task["result"]["ref"], "correction", "instruction", False)
            )
        for finding in task["result"]["findings"]:
            key = finding["recurrence_key"]
            warning_tasks[key].add(task_id)
            warning_refs[key].append(task["result"]["ref"])
            if finding["hard"]:
                observations[key].append(
                    (task_id, task["result"]["ref"], finding["category"], finding["response_class"], True)
                )
        for attempt in attempts:
            ref = attempt["ref"]
            for field, key in (
                ("execution_spec_status", "identity:invalid-execution-spec"),
                ("delegation_status", "identity:invalid-delegation"),
            ):
                if attempt[field] in {"missing", "invalid", "orphan"}:
                    observations[key].append((task_id, ref, "identity", "system", True))
            if attempt["feedback_count"] >= 2:
                observations["correction:feedback-loop"].append(
                    (task_id, ref, "correction", "instruction", False)
                )
            if attempt["status"] in {"unauthorized", "scope_violation"}:
                observations[f"authority:{attempt['status']}"].append(
                    (task_id, ref, "authority", "system", True)
                )
            for turn in attempt["turns"]:
                turn_ref = turn["ref"]
                if turn["timed_out"]:
                    observations["runtime:timeout"].append(
                        (task_id, turn_ref, "runtime", "system", False)
                    )
                if turn["guard_triggered"]:
                    observations["runtime:run-guard"].append(
                        (task_id, turn_ref, "runtime", "system", False)
                    )
                if turn["failed_activity"]:
                    failed_turns.append((task_id, turn_ref))
                if turn["mcp_failed"] and turn["fallback_commands"]:
                    mcp_fallbacks.append((task_id, turn_ref))
                for fingerprint, count in turn["command_fingerprints"].items():
                    command_counts[fingerprint].append((task_id, turn_ref, count))

    if len(failed_turns) >= 2:
        observations["activity:repeated-failure"].extend(
            (task, ref, "tool-failure", "skill", False) for task, ref in failed_turns
        )
    if len(mcp_fallbacks) >= 2:
        observations["activity:mcp-fallback-loop"].extend(
            (task, ref, "tool-failure", "tool", False) for task, ref in mcp_fallbacks
        )
    for fingerprint, items in command_counts.items():
        if sum(item[2] for item in items) >= 3:
            observations[f"tool-loop:{fingerprint}"].extend(
                (task, ref, "tool-loop", "tool", False) for task, ref, _ in items
            )
    for key, task_set in warning_tasks.items():
        if len(task_set) >= 2 and key not in observations:
            for task, ref in zip(sorted(task_set), sorted(set(warning_refs[key]))):
                observations[key].append((task, ref, "structured-warning", "skill", False))

    if len(observations) > MAX_SIGNALS:
        raise RetrospectiveError("qualified signal count exceeds the bounded limit")
    result = []
    for key in sorted(observations):
        items = observations[key]
        hard = any(item[4] for item in items)
        tasks = sorted({item[0] for item in items})
        response = items[0][3]
        result.append({
            "recurrence_key": key,
            "category": items[0][2],
            "impact": "high" if hard or response == "system" else "medium",
            "count": len(items),
            "distinct_task_count": len(tasks),
            "task_ids": tasks,
            "evidence_refs": sorted({item[1] for item in items})[:50],
            "recommended_response_class": response,
            "qualification": "hard" if hard else "threshold",
        })
    return result


def build_model_request(
    evidence: dict[str, Any], signals: list[dict[str, Any]], *, profile: str
) -> tuple[dict[str, Any], str]:
    named_profile = profile.split("/", 1)[1] if profile.startswith("codex/") else profile
    try:
        resolved = load_execution_registry().resolve("codex", named_profile, "medium")
    except ExecutionRegistryError as exc:
        raise RetrospectiveError(str(exc)) from exc
    if resolved.provider != "ollama_local":
        raise RetrospectiveError("advisory analysis requires a curated local Ollama profile")
    keys = [signal["recurrence_key"] for signal in signals]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "summary", "recommendations"],
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "summary": {"type": "string", "maxLength": 2_000},
            "recommendations": {
                "type": "array", "maxItems": len(keys),
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["recurrence_keys", "candidate_type", "rationale"],
                    "properties": {
                        "recurrence_keys": {
                            "type": "array", "minItems": 1, "uniqueItems": True,
                            "items": {"type": "string", "enum": keys},
                        },
                        "candidate_type": {"type": "string", "enum": list(CANDIDATE_TYPES)},
                        "rationale": {"type": "string", "maxLength": 500},
                    },
                },
            },
        },
    }
    prompt = (
        "Classify only the supplied deterministic milestone signals. Do not qualify or suppress "
        "signals, request tools, or propose execution. Return only schema-valid JSON.\n\n"
        + json.dumps({"evidence": evidence, "signals": signals}, sort_keys=True, separators=(",", ":"))
    )
    if len(prompt) > MAX_MODEL_PROMPT_CHARS:
        raise RetrospectiveError("bounded advisory prompt is too large")
    return ({
        "model": resolved.provider_locator,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": schema,
        "options": {"temperature": 0},
    }, resolved.canonical_profile)


def run_advisory_analysis(
    evidence: dict[str, Any],
    signals: list[dict[str, Any]],
    *,
    profile: str,
    runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    request, canonical = build_model_request(evidence, signals, profile=profile)
    provider = (runner or _post_ollama)(request, timeout_seconds=300)
    response, usage = _parse_model_response(provider, {item["recurrence_key"] for item in signals})
    advisory = {
        "provider": "ollama_local", "profile": canonical,
        "usage": usage, "response": response,
    }
    _validate_advisory(advisory, {item["recurrence_key"] for item in signals})
    return advisory


def _collect_tasks(
    root: Path,
    work: Path,
    binding: RepositoryBinding | None,
    task_ids: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    tasks_path = _safe_existing_file(root, root / "TASKS.md", "task ledger", MAX_TEXT_BYTES)
    try:
        document = parse_task_document(tasks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TaskDocumentError, ValueError) as exc:
        raise _RoundError("task_ledger", f"invalid task ledger: {exc}") from exc
    sources = [_source_digest(root, tasks_path)]
    collected = []
    for task_id in task_ids:
        try:
            row = document.row(task_id)
        except TaskDocumentError as exc:
            raise _RoundError("task_identity", str(exc)) from exc
        if row.status != "Completed":
            raise _RoundError("task_incomplete", f"task {task_id} is not Completed")
        result_ref = _result_ref(row.evidence, task_id)
        result_path = _safe_existing_file(
            root, root.joinpath(*safe_relative_path(result_ref).parts),
            f"result for {task_id}", MAX_JSON_BYTES,
        )
        result = _read_json_file(result_path, f"result for {task_id}")
        try:
            validate_result(result, expected_task=task_id, expected_status="completed")
        except ResultValidationError as exc:
            raise _RoundError("result_identity", str(exc)) from exc
        sources.append(_source_digest(root, result_path))
        attempts = _collect_attempts(root, work, binding, task_id, sources)
        selected = [
            item for item in attempts
            if item["attempt_id"] == result["attempt_id"] and item["team_id"] == result["team_id"]
        ]
        if len(selected) != 1:
            raise _RoundError("attempt_identity", f"result attempt for {task_id} is not unique")
        if selected[0]["role"] != result["agent_role"]:
            raise _RoundError("attempt_identity", f"result role does not match runtime attempt for {task_id}")
        gate = _accepted_gate(root, work, binding, task_id, result["attempt_id"], sources)
        findings = [
            _structured_finding(text)
            for text in (*result.get("warnings", []), *result.get("errors", []))
        ][:50]
        collected.append({
            "task_id": task_id,
            "ledger_status": row.status,
            "result": {
                "ref": result_ref,
                "digest": _file_digest(result_path),
                "result_id": result["result_id"],
                "team_id": result["team_id"],
                "attempt_id": result["attempt_id"],
                "role": result["agent_role"],
                "status": result["status"],
                "warning_count": len(result.get("warnings", [])),
                "error_count": len(result.get("errors", [])),
                "findings": findings,
            },
            "attempt_count": len(attempts),
            "attempts": attempts,
            "accepted_gate": gate,
        })
    return collected, sources


def _terminal_gate_digest(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        raise _RoundError("task_identity", "milestone has no terminal task")
    gate = tasks[-1].get("accepted_gate")
    digest = gate.get("workspace_digest") if isinstance(gate, dict) else None
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        raise _RoundError("accepted_gate_identity", "terminal task gate digest is invalid")
    return digest


def _collect_attempts(
    root: Path,
    work: Path,
    binding: RepositoryBinding | None,
    task_id: str,
    sources: list[dict[str, str]],
) -> list[dict[str, Any]]:
    sessions = root / ".codexteam" / "runtime" / "sessions"
    if sessions.is_symlink():
        raise _RoundError("runtime_identity", "sessions root must not be a symlink")
    candidates: list[tuple[str, Path]] = []
    if sessions.is_dir():
        for team in sorted(sessions.iterdir(), key=lambda item: item.name):
            task_dir = team / task_id
            if team.is_symlink() or task_dir.is_symlink() or not task_dir.is_dir():
                continue
            for attempt in sorted(task_dir.iterdir(), key=lambda item: item.name):
                if attempt.is_symlink() or not attempt.is_dir():
                    raise _RoundError("runtime_identity", "attempt path is unsafe")
                candidates.append((team.name, attempt))
    if len(candidates) > MAX_ATTEMPTS:
        raise _RoundError("evidence_bound", f"task {task_id} exceeds attempt limit")
    attempts = []
    for team_name, attempt_dir in candidates:
        team_id = validate_identifier(team_name, label="team ID")
        attempt_id = validate_identifier(attempt_dir.name, label="attempt ID")
        session_path = _safe_existing_file(
            root, attempt_dir / "session.json", "session", MAX_JSON_BYTES
        )
        session = _read_json_file(session_path, "session")
        sources.append(_source_digest(root, session_path))
        state: dict[str, Any] = {}
        state_path = attempt_dir / "turn-state.json"
        if state_path.exists() or state_path.is_symlink():
            safe_state = _safe_existing_file(root, state_path, "turn state", MAX_JSON_BYTES)
            state = _read_json_file(safe_state, "turn state")
            sources.append(_source_digest(root, safe_state))
        core_identity = {
            "team_id": team_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
        }
        if binding and any(key not in session for key in core_identity):
            raise _RoundError(
                "attempt_identity", f"split-root session core identity is missing for {task_id}"
            )
        if any(session.get(key, expected) != expected for key, expected in core_identity.items()):
            raise _RoundError("attempt_identity", f"session identity mismatch for {task_id}")
        role = _bounded_token(session.get("agent_role") or "unknown", "attempt role")
        if session.get("workspace_root", str(work)) != str(work):
            raise _RoundError("attempt_identity", f"session workspace mismatch for {task_id}")
        recorded_binding: dict[str, Any] = {}
        expected_binding: dict[str, str] = {}
        if binding:
            expected_binding = {
                "control_root": str(binding.control_root),
                "work_root": str(binding.work_root),
                "git_root": str(binding.git_root),
                "git_prefix": binding.git_prefix,
                "repo_id": binding.repo_id,
            }
            recorded_binding = {
                key: session.get(key)
                for key in expected_binding
                if key in session
            }
            if recorded_binding and recorded_binding != expected_binding:
                raise _RoundError(
                    "attempt_identity", f"session repository binding mismatch for {task_id}"
                )
        modern = (
            session.get("schema_version") in {"1.0", "1.1"}
            or isinstance(session.get("execution_spec"), dict)
            or (attempt_dir / "execution-spec.json").exists()
            or bool(state)
        )
        spec_status = "legacy"
        profile = _bounded_token(session.get("model_profile") or "unknown", "model profile")
        spec_path = attempt_dir / "execution-spec.json"
        if modern:
            if not spec_path.exists() or spec_path.is_symlink():
                spec_status = "missing"
            else:
                try:
                    safe_spec = _safe_existing_file(root, spec_path, "execution specification", MAX_JSON_BYTES)
                    spec = load_execution_spec(safe_spec)
                    sources.append(_source_digest(root, safe_spec))
                    identity = spec["identity"]
                    expected = {
                        "team_id": team_id, "task_id": task_id, "attempt_id": attempt_id,
                        "role": role, "workspace_root": str(work),
                    }
                    if any(identity.get(key) != value for key, value in expected.items()):
                        raise ExecutionSpecError("execution identity mismatch")
                    if binding and any(identity.get(key) != value for key, value in {
                        "control_root": str(binding.control_root), "work_root": str(binding.work_root),
                        "git_root": str(binding.git_root), "git_prefix": binding.git_prefix,
                        "repo_id": binding.repo_id,
                    }.items()):
                        raise ExecutionSpecError("execution binding mismatch")
                    reference = session.get("execution_spec")
                    if isinstance(reference, dict):
                        if reference.get("path") != "execution-spec.json" or reference.get("digest") != spec["execution_spec_digest"]:
                            raise ExecutionSpecError("session execution reference mismatch")
                    profile = _bounded_token(spec["execution_profile"]["profile"]["id"], "model profile")
                    spec_status = "valid"
                except (OSError, RetrospectiveError, ExecutionSpecError, ValueError):
                    spec_status = "invalid"
        if binding and recorded_binding != expected_binding and spec_status != "valid":
            raise _RoundError(
                "attempt_identity",
                f"split-root runtime provenance is missing for {task_id}/{attempt_id}",
            )

        delegation_path = attempt_dir / "delegation.json"
        if not modern and not delegation_path.exists() and not delegation_path.is_symlink():
            delegation_status = "legacy"
        elif not delegation_path.exists() or delegation_path.is_symlink():
            delegation_status = "missing"
        else:
            try:
                safe_delegation = _safe_existing_file(root, delegation_path, "delegation", MAX_JSON_BYTES)
                delegation = load_delegation(safe_delegation, expected_child={
                    "team_id": team_id, "task_id": task_id, "attempt_id": attempt_id,
                    "agent_role": role, "workspace_root": str(work),
                })
                sources.append(_source_digest(root, safe_delegation))
                delegation_status = delegation["attribution"]
            except (OSError, RetrospectiveError, ValueError):
                delegation_status = "invalid"
        turns = _collect_turns(root, attempt_dir, task_id, attempt_id, sources)
        attempts.append({
            "ref": attempt_dir.relative_to(root).as_posix(),
            "team_id": team_id, "task_id": task_id, "attempt_id": attempt_id,
            "role": role, "profile": profile,
            "status": _terminal_status(state.get("status") or session.get("last_status")),
            "execution_spec_status": spec_status,
            "delegation_status": delegation_status,
            "turn_count": len(turns),
            "feedback_count": sum(turn["phase"] == "feedback" for turn in turns),
            "turns": turns,
            "usage": _aggregate_usage(turns),
            "activity": _aggregate_activity(turns),
        })
    return attempts


def _collect_turns(
    root: Path,
    attempt_dir: Path,
    task_id: str,
    attempt_id: str,
    sources: list[dict[str, str]],
) -> list[dict[str, Any]]:
    turns_dir = attempt_dir / "turns"
    if turns_dir.is_symlink():
        raise _RoundError("runtime_identity", "turn metrics directory is unsafe")
    if not turns_dir.is_dir():
        return []
    paths = [path for path in sorted(turns_dir.iterdir()) if METRIC_NAME.fullmatch(path.name)]
    if len(paths) > MAX_TURNS:
        raise _RoundError("evidence_bound", f"attempt {attempt_id} exceeds turn limit")
    turns = []
    for path in paths:
        safe = _safe_existing_file(root, path, "turn metrics", MAX_JSON_BYTES)
        metrics = load_summary(safe)
        if metrics is None:
            raise _RoundError("metrics_invalid", f"invalid turn metrics: {path.name}")
        if metrics.get("task_id") != task_id or metrics.get("attempt_id") != attempt_id:
            raise _RoundError("attempt_identity", "turn metrics identity mismatch")
        match = METRIC_NAME.fullmatch(path.name)
        assert match is not None
        activity = metrics["activity"]
        raw_process = metrics.get("process")
        process: dict[str, Any] = raw_process if isinstance(raw_process, dict) else {}
        mcp = activity.get("mcp") if isinstance(activity.get("mcp"), dict) else {}
        fingerprints: Counter[str] = Counter()
        repeated_seen: set[str] = set()
        for item in activity.get("repeated_commands", [])[:10]:
            fingerprint = item.get("fingerprint") if isinstance(item, dict) else None
            count = _integer(item.get("count")) if isinstance(item, dict) else None
            if isinstance(fingerprint, str) and re.fullmatch(r"[a-f0-9]{8,64}", fingerprint) and count:
                fingerprints[fingerprint] = max(fingerprints[fingerprint], count)
                repeated_seen.add(fingerprint)
        # largest_commands contains bounded, sanitized fingerprints but no command text is copied.
        for item in activity.get("largest_commands", [])[:3]:
            fingerprint = item.get("fingerprint") if isinstance(item, dict) else None
            if isinstance(fingerprint, str) and re.fullmatch(r"[a-f0-9]{8,64}", fingerprint) and fingerprint not in repeated_seen:
                fingerprints[fingerprint] += 1
        usage = metrics["usage"].get("delta")
        sources.append(_source_digest(root, safe))
        turns.append({
            "ref": safe.relative_to(root).as_posix(), "digest": _file_digest(safe),
            "number": int(match.group(1)), "phase": match.group(2),
            "duration_seconds": _number(metrics["turn"].get("duration_seconds")),
            "terminal_reason": _terminal_status(metrics["turn"].get("terminal_reason")),
            "timed_out": process.get("timed_out") is True,
            "guard_triggered": process.get("guard_triggered") is True,
            "tool_calls": _integer(activity.get("tool_calls")) or 0,
            "failed_activity": _integer(activity.get("failed_tool_calls")) or 0,
            "failed_commands": _integer(activity.get("failed_command_calls")) or 0,
            "mcp_failed": _integer(mcp.get("failed_calls")) or 0,
            "fallback_commands": _integer(mcp.get("command_calls_after_failure")) or 0,
            "command_fingerprints": dict(sorted(fingerprints.items())),
            "usage": _safe_usage(usage),
        })
    return turns


def _accepted_gate(
    root: Path,
    work: Path,
    binding: RepositoryBinding | None,
    task_id: str,
    attempt_id: str,
    sources: list[dict[str, str]],
) -> dict[str, Any]:
    accepted = root / "results" / "gates" / "accepted"
    if accepted.is_symlink() or not accepted.is_dir():
        raise _RoundError("accepted_gate_missing", f"accepted gate directory missing for {task_id}")
    matches = sorted(accepted.glob(f"{task_id}-{attempt_id}-integration-*.json"))
    if len(matches) != 1:
        raise _RoundError(
            "accepted_gate_identity",
            f"task {task_id} requires exactly one accepted Integration Gate snapshot for {attempt_id}",
        )
    path = _safe_existing_file(root, matches[0], "accepted gate snapshot", MAX_JSON_BYTES)
    snapshot = _read_json_file(path, "accepted gate snapshot")
    record = snapshot.get("record")
    digest = snapshot.get("record_sha256")
    if not isinstance(record, dict) or not isinstance(digest, str) or not HEX64.fullmatch(digest):
        raise _RoundError("accepted_gate_identity", "accepted gate snapshot shape is invalid")
    if _digest(record) != digest or path.name != f"{task_id}-{attempt_id}-integration-{digest[:16]}.json":
        raise _RoundError("accepted_gate_identity", "accepted gate snapshot digest or name mismatch")
    expected = {
        "schema_version": SCHEMA_VERSION, "kind": "accepted_gate_snapshot",
        "task_id": task_id, "attempt_id": attempt_id, "gate": "integration",
    }
    if any(snapshot.get(key) != value for key, value in expected.items()):
        raise _RoundError("accepted_gate_identity", "accepted gate snapshot identity mismatch")
    _validate_integration_gate(record, root, work, binding)
    sources.append(_source_digest(root, path))
    return {
        "ref": path.relative_to(root).as_posix(), "digest": _file_digest(path),
        "record_digest": digest, "status": "passed",
        "duration_seconds": _number(record.get("duration_seconds")),
        "command_count": len(record["commands"]),
        "workspace_digest": record["workspace_digest"],
    }


def _validate_integration_gate(
    record: dict[str, Any], root: Path, work: Path, binding: RepositoryBinding | None
) -> None:
    try:
        validate_gate_record(record)
    except GateConfigError as exc:
        raise _RoundError("integration_gate_invalid", str(exc)) from exc
    if record.get("gate") != "integration" or record.get("status") != "passed":
        raise _RoundError("integration_gate_invalid", "Integration Gate is not passing")
    if record.get("project_root") != str(work):
        raise _RoundError("integration_gate_identity", "Integration Gate project root mismatch")
    expected_binding = ({
        "control_root": str(binding.control_root), "work_root": str(binding.work_root),
        "git_root": str(binding.git_root), "git_prefix": binding.git_prefix,
        "repo_id": binding.repo_id,
    } if binding else {})
    observed = {
        key: record[key]
        for key in ("control_root", "work_root", "git_root", "git_prefix", "repo_id")
        if key in record
    }
    if observed != expected_binding:
        raise _RoundError("integration_gate_identity", "Integration Gate repository binding mismatch")


def _collect_commit(
    root: Path,
    work: Path,
    git_root: Path,
    binding: RepositoryBinding | None,
    boundary: str,
    tasks: tuple[str, ...],
    commit_record_path: str | None,
    supplied_commit: str | None,
    terminal_workspace_digest: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    sources: list[dict[str, str]] = []
    record: dict[str, Any] | None = None
    if binding is None:
        relative = commit_record_path or f".codexteam/runtime/git-steward/{boundary}/commit-record.json"
        safe = safe_relative_path(relative, label="commit record")
        path = _safe_existing_file(root, root.joinpath(*safe.parts), "commit record", MAX_JSON_BYTES)
        record = _read_json_file(path, "commit record")
        sources.append(_source_digest(root, path))
        _validate_commit_record_shape(record, root, boundary)
        supplied_commit = record["head_after"]
    if not isinstance(supplied_commit, str) or not HEX_OBJECT.fullmatch(supplied_commit):
        raise _RoundError("commit_identity", "milestone commit must be a full lowercase object ID")
    commit = _git(git_root, "rev-parse", f"{supplied_commit}^{{commit}}")
    if commit != supplied_commit:
        raise _RoundError("commit_identity", "milestone commit does not resolve exactly")
    message = _git(git_root, "show", "-s", "--format=%B", commit)
    verification_values = _trailers(message, "CodexTeam-Verification")
    if (
        _trailers(message, "CodexTeam-Boundary") != [boundary]
        or _trailers(message, "CodexTeam-Tasks") != [",".join(tasks)]
        or len(verification_values) != 1
    ):
        raise _RoundError("commit_trailers", "commit trailers do not exactly match milestone identity")
    verification_ref = verification_values[0]
    safe_verification = safe_relative_path(verification_ref, label="verification artifact").as_posix()
    verification_path = _safe_existing_file(
        root, root.joinpath(*safe_relative_path(safe_verification).parts),
        "verification artifact", MAX_JSON_BYTES,
    )
    verification_record = _read_json_file(verification_path, "verification artifact")
    _validate_integration_gate(verification_record, root, work, binding)
    workspace_digest = verification_record["workspace_digest"]
    if workspace_digest != terminal_workspace_digest:
        raise _RoundError(
            "milestone_gate_identity",
            "milestone verification digest does not match the terminal task's accepted Integration Gate",
        )
    sources.append(_source_digest(root, verification_path))

    tree = _git(git_root, "rev-parse", f"{commit}^{{tree}}")
    committed_gate_digest = _commit_gate_manifest_digest(
        git_root,
        commit,
        verification_record["verification_paths"],
        binding.git_prefix if binding else ".",
    )
    if committed_gate_digest != workspace_digest:
        raise _RoundError(
            "milestone_gate_identity",
            "milestone commit tree does not match its Integration Gate workspace digest",
        )
    paths = sorted(filter(None, _git(
        git_root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit
    ).splitlines()))
    if len(paths) > MAX_COMMIT_PATHS:
        raise _RoundError("evidence_bound", "milestone commit contains too many paths")
    if binding and binding.git_prefix != ".":
        prefix = binding.git_prefix.rstrip("/") + "/"
        if any(not item.startswith(prefix) for item in paths):
            raise _RoundError("commit_scope", "commit contains paths outside registered source binding")
    if record is not None:
        verification = record["verification"]
        parents = _git(git_root, "rev-list", "--parents", "-n", "1", commit).split()
        expected_parent = parents[1] if len(parents) == 2 else None
        if len(parents) > 2:
            raise _RoundError("commit_record_identity", "Git Steward milestone commit cannot be a merge commit")
        if (
            record["head_before"] != expected_parent
            or record["tree"] != tree
            or record["committed_paths"] != paths
            or verification["artifact_ref"] != safe_verification
            or verification["workspace_digest"] != workspace_digest
            or safe_verification not in paths
            or record["commit_subject"] != message.splitlines()[0]
        ):
            raise _RoundError("commit_record_identity", "commit record does not match Git or verification evidence")
        committed_verification = _git_bytes_optional(git_root, "show", f"{commit}:{safe_verification}")
        if committed_verification is None or hashlib.sha256(committed_verification).hexdigest() != _file_digest(verification_path):
            raise _RoundError("commit_record_identity", "committed verification artifact differs from control evidence")

    source_files = _commit_source_manifest(
        git_root, commit, paths, binding.repo_id if binding else "control-root"
    )
    return ({
        "repository_id": binding.repo_id if binding else "control-root",
        "object_id": commit, "tree": tree, "committed_path_count": len(paths),
        "verification_ref": safe_verification,
        "verification_workspace_digest": workspace_digest,
        "source_files": source_files,
    }, sources)


def _validate_commit_record_shape(record: dict[str, Any], root: Path, boundary: str) -> None:
    fields = {
        "schema_version", "boundary_id", "status", "project_root", "branch",
        "head_before", "head_after", "tree", "committed_paths", "verification",
        "commit_subject", "committed_at",
    }
    if set(record) != fields:
        raise _RoundError("commit_record_identity", "commit record fields do not match the Git Steward contract")
    if (
        record.get("schema_version") != SCHEMA_VERSION
        or record.get("boundary_id") != boundary
        or record.get("status") != "committed"
        or record.get("project_root") != str(root)
        or not _short_text(record.get("branch"), 255)
        or not isinstance(record.get("head_after"), str)
        or not HEX_OBJECT.fullmatch(record["head_after"])
        or not isinstance(record.get("tree"), str)
        or not HEX_OBJECT.fullmatch(record["tree"])
        or not _short_text(record.get("commit_subject"), 72)
        or "\n" in record["commit_subject"]
        or not _timestamp(record.get("committed_at"))
    ):
        raise _RoundError("commit_record_identity", "commit record identity fields are invalid")
    if _git_optional(root, "check-ref-format", "--branch", record["branch"]) is None:
        raise _RoundError("commit_record_identity", "commit record branch is invalid")
    head_before = record.get("head_before")
    if head_before is not None and (not isinstance(head_before, str) or not HEX_OBJECT.fullmatch(head_before)):
        raise _RoundError("commit_record_identity", "commit record head_before is invalid")
    paths = record.get("committed_paths")
    if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
        raise _RoundError("commit_record_identity", "commit record paths are invalid")
    for item in paths:
        safe_relative_path(item, label="committed path")
    verification = record.get("verification")
    if not isinstance(verification, dict) or set(verification) != {"kind", "artifact_ref", "workspace_digest"}:
        raise _RoundError("commit_record_identity", "commit record verification is invalid")
    if verification.get("kind") != "integration":
        raise _RoundError("commit_record_identity", "milestone commit verification must be integration")
    artifact_ref = verification.get("artifact_ref")
    if not isinstance(artifact_ref, str):
        raise _RoundError("commit_record_identity", "commit verification artifact is invalid")
    safe_relative_path(artifact_ref, label="verification artifact")
    if not isinstance(verification.get("workspace_digest"), str) or not HEX64.fullmatch(verification["workspace_digest"]):
        raise _RoundError("commit_record_identity", "commit verification digest is invalid")


def _commit_source_manifest(
    git_root: Path, commit: str, paths: list[str], repository_id: str
) -> list[dict[str, str]]:
    total = 0
    result = []
    for relative in paths:
        content = _git_bytes_optional(git_root, "show", f"{commit}:{relative}")
        version = "committed"
        if content is None:
            content = _git_bytes_optional(git_root, "show", f"{commit}^:{relative}")
            version = "deleted-preimage"
        if content is None:
            raise _RoundError("commit_identity", f"cannot read committed path {relative}")
        total += len(content)
        if total > MAX_COMMIT_BYTES:
            raise _RoundError("evidence_bound", "committed source exceeds bounded size")
        result.append({
            "ref": f"repo:{repository_id}@{commit}:{relative}",
            "sha256": hashlib.sha256(content).hexdigest(), "version": version,
        })
    return result


def _commit_gate_manifest_digest(
    git_root: Path,
    commit: str,
    patterns: list[str],
    git_prefix: str,
) -> str:
    prefix = "" if git_prefix == "." else git_prefix.rstrip("/") + "/"
    raw = _git_bytes_optional(git_root, "ls-tree", "-rz", "--full-tree", commit)
    if raw is None:
        raise _RoundError("commit_identity", "cannot enumerate milestone commit tree")
    manifest: dict[str, str] = {}
    total_bytes = 0
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            git_path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise _RoundError("commit_identity", "Git returned an invalid tree entry") from exc
        if object_type != "blob" or (prefix and not git_path.startswith(prefix)):
            continue
        relative = git_path[len(prefix):]
        if _gate_path_excluded(relative) or not any(
            fnmatch.fnmatchcase(relative, pattern) for pattern in patterns
        ):
            continue
        content = _git_bytes_optional(git_root, "cat-file", "blob", object_id)
        if content is None:
            raise _RoundError("commit_identity", f"cannot read committed gate path {relative}")
        total_bytes += len(content)
        if len(manifest) >= MAX_GATE_MANIFEST_PATHS or total_bytes > MAX_GATE_MANIFEST_BYTES:
            raise _RoundError("evidence_bound", "committed gate manifest exceeds bounded limits")
        if mode == "120000":
            try:
                manifest[relative] = "symlink:" + content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _RoundError("commit_identity", "committed symlink target is not UTF-8") from exc
        else:
            manifest[relative] = hashlib.sha256(content).hexdigest()
    if not manifest:
        raise _RoundError("milestone_gate_identity", "commit verification paths match no files")
    return _digest(dict(sorted(manifest.items())))


def _gate_path_excluded(relative: str) -> bool:
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in (".git", ".codexteam/runtime", "results/gates")
    )


def _collect_lead_metrics(
    root: Path, tasks: tuple[str, ...], sources: list[dict[str, str]]
) -> dict[str, Any]:
    path = root / ".codexteam" / "runtime" / "lead-metrics.json"
    if not path.exists() and not path.is_symlink():
        return {"available": False, "tasks": {}}
    safe = _safe_existing_file(root, path, "Lead metrics", MAX_JSON_BYTES)
    data = _read_json_file(safe, "Lead metrics")
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("tasks"), dict):
        raise _RoundError("lead_metrics_invalid", "Lead metrics contract is invalid")
    selected = {}
    for task_id in tasks:
        item = data["tasks"].get(task_id)
        if isinstance(item, dict):
            selected[task_id] = {
                "profile": _bounded_token(item.get("profile") or "unknown", "Lead profile"),
                "provider": _bounded_token(item.get("provider") or "unknown", "Lead provider"),
                "duration_seconds": _number(item.get("duration_seconds")),
                "input_tokens": _integer(item.get("input_tokens")),
                "cached_input_tokens": _integer(item.get("cached_input_tokens")),
                "output_tokens": _integer(item.get("output_tokens")),
            }
    sources.append(_source_digest(root, safe))
    return {"available": True, "tasks": selected}


def _build_proposals(boundary: str, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prefix = re.sub(r"[^A-Z0-9]+", "-", boundary.upper()).strip("-")
    boundary_tag = hashlib.sha256(boundary.encode("utf-8")).hexdigest()[:16].upper()
    proposals = []
    for ordinal, signal in enumerate(signals, 1):
        category = signal["recommended_response_class"]
        proposal = {
            "schema_version": SCHEMA_VERSION,
            "proposal_id": f"IMP-{prefix}-{boundary_tag}-{ordinal:03d}",
            "boundary_id": boundary,
            "recurrence_key": signal["recurrence_key"],
            "category": category,
            "scope": _scope(category),
            "impact": signal["impact"],
            "confidence": "high" if signal["qualification"] == "hard" else "medium",
            "evidence": signal["evidence_refs"],
            "trigger": _trigger(signal["recurrence_key"]),
            "expected_gain": _gain(category),
            "validation": f"At a later comparable milestone, verify that `{signal['recurrence_key']}` does not recur.",
            "rollback": "Revert the accepted planning change if validation does not reduce recurrence.",
            "status": "Proposed", "human_disposition": "None",
            "creates_task": False, "grants_implementation_authority": False,
        }
        validate_proposal(proposal)
        proposals.append(proposal)
    return proposals


def _scope(category: str) -> str:
    return {
        "instruction": "existing project or role guidance",
        "skill": "reusable CodexTeam workflow guidance",
        "template": "project handoff template",
        "contract": "structured evidence contract",
        "tool": "deterministic local tooling",
        "system": "authority, isolation, gate, or runtime system",
    }[category]


def _trigger(key: str) -> str:
    known = {
        "correction:replacement-attempt": "More than one attempt was required for an included task.",
        "correction:feedback-loop": "At least two feedback turns were required for one attempt.",
        "runtime:timeout": "An included worker turn timed out.",
        "runtime:run-guard": "The Run Guard interrupted an included worker turn.",
        "activity:repeated-failure": "Failed tool or command activity recurred in at least two turns.",
        "activity:mcp-fallback-loop": "MCP failure was followed by fallback commands in at least two turns.",
        "identity:invalid-execution-spec": "Modern attempt execution identity was missing or invalid.",
        "identity:invalid-delegation": "Modern attempt delegation identity was missing, orphaned, or invalid.",
    }
    return known.get(key, "Deterministic milestone evidence met this recurrence threshold.")


def _gain(category: str) -> str:
    return {
        "instruction": "Reduce avoidable correction while preserving authority boundaries.",
        "skill": "Make reusable judgment and trigger handling more consistent.",
        "template": "Capture required handoff facts before execution.",
        "contract": "Represent and validate required evidence explicitly.",
        "tool": "Replace repeated error-prone manual activity with bounded tooling.",
        "system": "Prevent recurrence at the authority, isolation, gate, or runtime boundary.",
    }[category]


def _proposal_block(proposal: dict[str, Any]) -> str:
    evidence = ", ".join(f"`{item}`" for item in proposal["evidence"])
    proposal_id = proposal["proposal_id"]
    return "\n".join((
        f"<!-- codexteam-improvement:{proposal_id} -->",
        f"### {proposal_id}",
        f"- Category: {proposal['category']}", f"- Scope: {proposal['scope']}",
        f"- Impact: {proposal['impact']}", f"- Confidence: {proposal['confidence']}",
        f"- Evidence: {evidence}", f"- Trigger: {proposal['trigger']}",
        f"- Expected gain: {proposal['expected_gain']}",
        f"- Validation: {proposal['validation']}", f"- Rollback: {proposal['rollback']}",
        "- Status: Proposed", "- Human disposition: None", "- Creates task: No",
        "- Implementation authority: Not granted",
        f"<!-- /codexteam-improvement:{proposal_id} -->",
    ))


def _update_backlog(root: Path, proposals: list[dict[str, Any]], *, write: bool) -> bool:
    if not proposals:
        return False
    path, text = _load_backlog(root)
    updated = text
    for proposal in proposals:
        expected = _proposal_block(proposal)
        existing = _extract_proposal_block(updated, proposal["proposal_id"])
        if existing is not None:
            if not _proposal_block_matches(
                root, existing, expected, proposal["boundary_id"], proposal["proposal_id"]
            ):
                raise _RoundError("backlog_conflict", f"conflicting backlog proposal {proposal['proposal_id']}")
            continue
        if proposal["proposal_id"] in updated:
            raise _RoundError("backlog_conflict", f"unmarked backlog proposal conflict {proposal['proposal_id']}")
        updated = updated.rstrip() + "\n\n" + expected + "\n"
    if write and updated != text:
        atomic_write_text(path, updated)
    return write and updated != text


def _proposal_block_matches(
    root: Path, current: str, expected: str, boundary: str, proposal_id: str
) -> bool:
    if current == expected:
        return True
    status = re.search(r"^- Status: (Approved|Rejected|Deferred)$", current, re.MULTILINE)
    disposition = re.search(r"^- Human disposition: `([^`]+)`$", current, re.MULTILINE)
    if status is None or disposition is None:
        return False
    try:
        path = _safe_control_relative_file(root, disposition.group(1), "disposition", MAX_JSON_BYTES)
        record = _read_json_file(path, "disposition")
        validate_disposition(record)
        analysis = _read_json_file(
            _safe_existing_file(
                root,
                root / "results" / "retrospectives" / boundary / "analysis.json",
                "analysis",
                MAX_JSON_BYTES,
            ),
            "analysis",
        )
        proposal = next(
            (
                item
                for item in analysis.get("proposals", [])
                if isinstance(item, dict) and item.get("proposal_id") == proposal_id
            ),
            None,
        )
    except (OSError, RetrospectiveError, ValueError):
        return False
    if (
        proposal is None
        or record["boundary_id"] != boundary
        or record["proposal_id"] != proposal_id
        or record["proposal_sha256"] != _digest(proposal)
        or record["status"] != status.group(1)
    ):
        return False
    normalized = re.sub(r"^- Status: .+$", "- Status: Proposed", current, flags=re.MULTILINE)
    normalized = re.sub(
        r"^- Human disposition: .+$", "- Human disposition: None", normalized,
        flags=re.MULTILINE,
    )
    return normalized == expected


def _extract_proposal_block(text: str, proposal_id: str) -> str | None:
    start = f"<!-- codexteam-improvement:{proposal_id} -->"
    end = f"<!-- /codexteam-improvement:{proposal_id} -->"
    if text.count(start) > 1 or text.count(end) > 1:
        raise RetrospectiveError("duplicate proposal markers")
    if start not in text and end not in text:
        return None
    if start not in text or end not in text:
        raise RetrospectiveError("incomplete proposal markers")
    return start + text.split(start, 1)[1].split(end, 1)[0] + end


def _set_disposition(block: str, status: str, record_ref: str) -> str:
    return block.replace("- Status: Proposed", f"- Status: {status}", 1).replace(
        "- Human disposition: None", f"- Human disposition: `{record_ref}`", 1
    )


def _existing_retrospective(
    root: Path,
    destination: Path,
    evidence: dict[str, Any],
    signals: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not destination.exists() and not destination.is_symlink():
        return None
    if destination.is_symlink() or not destination.is_dir():
        raise _RoundError("artifact_conflict", "retrospective destination is unsafe")
    existing_evidence = _read_json_file(
        _safe_existing_file(root, destination / "evidence.json", "evidence", MAX_JSON_BYTES),
        "evidence",
    )
    if existing_evidence != evidence:
        raise _RoundError("artifact_conflict", "evidence changed under an existing boundary")
    analysis = _read_json_file(
        _safe_existing_file(root, destination / "analysis.json", "analysis", MAX_JSON_BYTES),
        "analysis",
    )
    validate_retrospective(analysis)
    expected = {
        "boundary_id": evidence["boundary_id"], "evidence_digest": _digest(evidence),
        "disposition": "PROPOSALS_RECORDED" if proposals else "NO_CHANGE",
        "signals": signals, "proposals": proposals,
    }
    if any(analysis.get(key) != value for key, value in expected.items()):
        raise _RoundError("artifact_conflict", "existing analysis conflicts with deterministic evidence")
    report_path = _safe_existing_file(root, destination / "RETROSPECTIVE.md", "report", MAX_TEXT_BYTES)
    if report_path.read_text(encoding="utf-8") != _render_report(analysis):
        raise _RoundError("artifact_conflict", "existing retrospective report conflicts")
    dispositions = destination / "dispositions"
    if dispositions.is_symlink() or not dispositions.is_dir():
        raise _RoundError("artifact_conflict", "dispositions directory is unsafe")
    return analysis


def _publish_artifacts(
    root: Path,
    destination: Path,
    evidence: dict[str, Any],
    analysis: dict[str, Any],
    report: str,
) -> None:
    results = root / "results"
    parent = destination.parent
    for path in (results, parent):
        if path.is_symlink():
            raise _RoundError("artifact_path", f"artifact path is a symlink: {path}")
        path.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=parent))
    try:
        (temporary / "dispositions").mkdir()
        (temporary / "evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (temporary / "analysis.json").write_text(
            json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (temporary / "RETROSPECTIVE.md").write_text(report, encoding="utf-8")
        if destination.exists() or destination.is_symlink():
            raise _RoundError("artifact_conflict", "retrospective destination appeared concurrently")
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _render_report(analysis: dict[str, Any]) -> str:
    lines = [
        f"# Milestone Retrospective: {analysis['boundary_id']}", "",
        f"- Disposition: `{analysis['disposition']}`",
        f"- Evidence digest: `{analysis['evidence_digest']}`",
        f"- Qualified signals: {len(analysis['signals'])}",
        f"- Proposed improvements: {len(analysis['proposals'])}", "",
        "## Deterministic Findings", "",
    ]
    if analysis["signals"]:
        for signal in analysis["signals"]:
            lines.append(
                f"- `{signal['recurrence_key']}`: {signal['count']} observation(s), "
                f"{signal['distinct_task_count']} task(s), `{signal['recommended_response_class']}` response."
            )
    else:
        lines.append("No signal met deterministic qualification rules.")
    lines.extend(["", "## Proposals", ""])
    if analysis["proposals"]:
        for proposal in analysis["proposals"]:
            lines.append(
                f"- `{proposal['proposal_id']}`: {proposal['trigger']} Status `Proposed`; "
                "no task or implementation authority is created."
            )
    else:
        lines.append("No backlog proposal was created.")
    advisory = analysis.get("advisory_model")
    if advisory is not None:
        lines.extend(["", "## Local Advisory", "", advisory["response"]["summary"] or "No advisory summary."])
    return "\n".join(lines).rstrip() + "\n"


def _post_ollama(payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            if response.geturl() != OLLAMA_CHAT_URL:
                raise RetrospectiveError("Ollama redirected away from fixed loopback endpoint")
            body = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise RetrospectiveError(f"local Ollama advisory failed: {exc}") from exc
    if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
        raise RetrospectiveError("Ollama provider response is too large")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetrospectiveError("Ollama response is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RetrospectiveError("Ollama response must be an object")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _parse_model_response(
    provider: dict[str, Any], signal_keys: set[str]
) -> tuple[dict[str, Any], dict[str, int]]:
    message = provider.get("message")
    if not isinstance(message, dict):
        raise RetrospectiveError("Ollama response lacks assistant message")
    if message.get("tool_calls") not in (None, []):
        raise RetrospectiveError("tool-free advisory returned tool calls")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RetrospectiveError("Ollama response lacks advisory JSON")
    if len(content.encode("utf-8")) > MAX_MODEL_RESPONSE_BYTES:
        raise RetrospectiveError("advisory response is too large")
    try:
        response = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RetrospectiveError("advisory response is not JSON") from exc
    _validate_advisory_response(response, signal_keys)
    usage = {}
    for field in ("prompt_eval_count", "eval_count"):
        count = _integer(provider.get(field))
        if count is not None:
            usage[field] = count
    return response, usage


def _validate_advisory(advisory: Any, signal_keys: set[str]) -> None:
    if not isinstance(advisory, dict) or set(advisory) != {"provider", "profile", "usage", "response"}:
        raise RetrospectiveError("advisory fields are invalid")
    if advisory.get("provider") != "ollama_local" or not _short_text(advisory.get("profile"), 200):
        raise RetrospectiveError("advisory provider or profile is invalid")
    usage = advisory.get("usage")
    if not isinstance(usage, dict) or set(usage) - {"prompt_eval_count", "eval_count"}:
        raise RetrospectiveError("advisory usage is invalid")
    if any(_integer(value) is None for value in usage.values()):
        raise RetrospectiveError("advisory usage counts are invalid")
    _validate_advisory_response(advisory.get("response"), signal_keys)


def _validate_advisory_response(value: Any, signal_keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"schema_version", "summary", "recommendations"}:
        raise RetrospectiveError("advisory response fields are invalid")
    if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("summary"), str) or len(value["summary"]) > 2_000:
        raise RetrospectiveError("advisory response metadata is invalid")
    recommendations = value.get("recommendations")
    if not isinstance(recommendations, list) or len(recommendations) > len(signal_keys):
        raise RetrospectiveError("advisory recommendations are invalid")
    for item in recommendations:
        if not isinstance(item, dict) or set(item) != {"recurrence_keys", "candidate_type", "rationale"}:
            raise RetrospectiveError("advisory recommendation fields are invalid")
        keys = item["recurrence_keys"]
        if not isinstance(keys, list) or not keys or len(keys) != len(set(keys)) or any(key not in signal_keys for key in keys):
            raise RetrospectiveError("advisory references an unqualified signal")
        if item["candidate_type"] not in CANDIDATE_TYPES or not isinstance(item["rationale"], str) or len(item["rationale"]) > 500:
            raise RetrospectiveError("advisory recommendation is invalid")


def _validate_signal(value: Any) -> None:
    fields = {
        "recurrence_key", "category", "impact", "count", "distinct_task_count",
        "task_ids", "evidence_refs", "recommended_response_class", "qualification",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise RetrospectiveError("signal fields are invalid")
    if not _short_text(value.get("recurrence_key"), 300) or not _short_text(value.get("category"), 100):
        raise RetrospectiveError("signal identity is invalid")
    if value.get("impact") not in {"medium", "high"} or value.get("qualification") not in {"hard", "threshold"}:
        raise RetrospectiveError("signal qualification is invalid")
    if value.get("recommended_response_class") not in CANDIDATE_TYPES:
        raise RetrospectiveError("signal response class is invalid")
    if isinstance(value.get("count"), bool) or not isinstance(value.get("count"), int) or value["count"] < 1:
        raise RetrospectiveError("signal count is invalid")
    tasks = value.get("task_ids")
    if (
        not isinstance(tasks, list)
        or not tasks
        or len(tasks) > MAX_TASKS
        or len(tasks) != len(set(tasks))
    ):
        raise RetrospectiveError("signal task IDs are invalid")
    for task in tasks:
        if normalize_task_id(task) != task:
            raise RetrospectiveError("signal task IDs must be canonical")
    distinct_count = value.get("distinct_task_count")
    if (
        isinstance(distinct_count, bool)
        or not isinstance(distinct_count, int)
        or distinct_count != len(tasks)
    ):
        raise RetrospectiveError("signal distinct task count is invalid")
    _validate_refs(value.get("evidence_refs"), "signal evidence")


def _structured_finding(text: str) -> dict[str, Any]:
    lowered = text.lower()
    matched = next(
        (
            (category, response)
            for marker, (category, response) in HARD_FINDING_MARKERS.items()
            if marker in lowered
        ),
        None,
    )
    if matched is None:
        category, hard, response = "structured-warning", False, "skill"
    else:
        category, response = matched
        hard = True
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "category": category, "digest": digest,
        "recurrence_key": f"finding:{category}:{digest[:16]}",
        "hard": hard, "response_class": response,
    }


def _aggregate_usage(turns: list[dict[str, Any]]) -> dict[str, int]:
    totals = Counter()
    for turn in turns:
        for key, value in turn["usage"].items():
            if value is not None:
                totals[key] += value
    return dict(sorted(totals.items()))


def _aggregate_activity(turns: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "timeouts": sum(turn["timed_out"] for turn in turns),
        "guard_interruptions": sum(turn["guard_triggered"] for turn in turns),
        "tool_calls": sum(turn["tool_calls"] for turn in turns),
        "failed_tool_or_command_calls": sum(turn["failed_activity"] for turn in turns),
        "failed_command_calls": sum(turn["failed_commands"] for turn in turns),
        "mcp_failures": sum(turn["mcp_failed"] for turn in turns),
        "fallback_commands_after_mcp_failure": sum(turn["fallback_commands"] for turn in turns),
    }


def _safe_usage(value: Any) -> dict[str, int | None]:
    data = value if isinstance(value, dict) else {}
    return {
        key: _integer(data.get(key))
        for key in (
            "input_tokens", "cached_input_tokens", "uncached_input_tokens",
            "output_tokens", "reasoning_output_tokens",
        )
    }


def _result_ref(evidence: str, task_id: str) -> str:
    matches = sorted(set(re.findall(rf"results/{re.escape(task_id)}-[A-Za-z0-9._-]+\.json", evidence)))
    if len(matches) != 1:
        raise _RoundError("result_identity", f"task {task_id} must reference exactly one result JSON")
    return matches[0]


def _terminal_status(value: Any) -> str:
    status = str(value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    if "unauthor" in status:
        return "unauthorized"
    if "scope" in status and "violation" in status:
        return "scope_violation"
    if "timeout" in status:
        return "timeout"
    if "guard" in status:
        return "guard_interrupted"
    allowed = {
        "completed", "finalized", "failed", "partial", "blocked", "needs_review",
        "running", "unknown", "process_exit", "success", "draft_ready",
    }
    return status if status in allowed else "other"


def _blocked(
    boundary: str,
    tasks: tuple[str, ...],
    code: str,
    message: str,
    *,
    artifact_root: str | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION, "boundary_id": boundary,
        "task_ids": list(tasks), "disposition": "BLOCKED_INSUFFICIENT_EVIDENCE",
        "blocking_reasons": [{"code": code[:100], "message": message[:500]}],
        "applied": artifact_root is not None,
        "mutates": artifact_root is not None,
    }
    if artifact_root is not None:
        result["artifact_root"] = artifact_root
    return result


def _failure_code(exc: Exception) -> str:
    name = exc.__class__.__name__.removesuffix("Error")
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return normalized or "analysis_failure"


def _analysis_response(
    analysis: dict[str, Any],
    destination: Path,
    apply: bool,
    *,
    idempotent: bool,
    mutated: bool | None = None,
) -> dict[str, Any]:
    return {
        **analysis,
        "applied": apply,
        "mutates": (apply and not idempotent) if mutated is None else mutated,
        "idempotent": idempotent, "artifact_root": str(destination),
    }


def _artifact_root(root: Path, boundary: str) -> Path:
    return root / "results" / "retrospectives" / boundary


def _load_backlog(root: Path) -> tuple[Path, str]:
    path = _safe_existing_file(root, root / "management" / "BACKLOG.md", "backlog", MAX_TEXT_BYTES)
    return path, path.read_text(encoding="utf-8")


def _safe_control_relative_file(root: Path, relative: str, label: str, limit: int) -> Path:
    safe = safe_relative_path(relative, label=label)
    return _safe_existing_file(root, root.joinpath(*safe.parts), label, limit)


def _safe_existing_file(root: Path, path: Path, label: str, limit: int) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RetrospectiveError(f"{label} escapes control root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RetrospectiveError(f"{label} contains a symlink")
    if not path.is_file():
        raise _RoundError("evidence_missing", f"{label} is missing")
    if path.stat().st_size > limit:
        raise _RoundError("evidence_bound", f"{label} exceeds size limit")
    return path


def _read_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _RoundError("malformed_evidence", f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise _RoundError("malformed_evidence", f"{label} must be a JSON object")
    return value


def _exact_safe_root(value: str | Path, label: str) -> Path:
    raw = Path(os.path.abspath(Path(value).expanduser()))
    if not raw.is_dir():
        raise RetrospectiveError(f"{label} is not an existing directory: {raw}")
    resolved = raw.resolve(strict=True)
    if raw != resolved:
        raise RetrospectiveError(f"{label} must not contain symlink components")
    return resolved


def _exact_git_root(root: Path) -> Path:
    try:
        reported = Path(_git(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
    except (OSError, RetrospectiveError) as exc:
        raise _RoundError("repository_identity", str(exc)) from exc
    if reported != root:
        raise _RoundError("repository_identity", "same-root project must be the exact Git root")
    return root


@contextmanager
def _project_lock(root: Path) -> Iterator[None]:
    runtime = root / ".codexteam" / "runtime"
    for path in (root / ".codexteam", runtime):
        if path.is_symlink():
            raise RetrospectiveError("project lock path is a symlink")
        path.mkdir(exist_ok=True)
    lock_path = runtime / "milestone-retrospective.lock"
    if lock_path.is_symlink():
        raise RetrospectiveError("project lock must not be a symlink")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RetrospectiveError("another retrospective mutation holds the project lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _git(root: Path, *arguments: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RetrospectiveError("git executable is required")
    completed = subprocess.run(
        [executable, "-C", str(root), *arguments], text=True, capture_output=True,
        timeout=30, check=False,
    )
    if completed.returncode != 0:
        raise _RoundError("commit_identity", f"Git failed to validate {arguments[0]}")
    return completed.stdout.strip()


def _git_bytes_optional(root: Path, *arguments: str) -> bytes | None:
    executable = shutil.which("git")
    if executable is None:
        raise RetrospectiveError("git executable is required")
    completed = subprocess.run(
        [executable, "-C", str(root), *arguments], capture_output=True,
        timeout=30, check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def _git_optional(root: Path, *arguments: str) -> str | None:
    executable = shutil.which("git")
    if executable is None:
        raise RetrospectiveError("git executable is required")
    completed = subprocess.run(
        [executable, "-C", str(root), *arguments], text=True, capture_output=True,
        timeout=30, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _trailers(message: str, name: str) -> list[str]:
    return re.findall(rf"^{re.escape(name)}:\s*(.*?)\s*$", message, re.MULTILINE)


def _source_digest(root: Path, path: Path) -> dict[str, str]:
    return {"ref": path.relative_to(root).as_posix(), "sha256": _file_digest(path)}


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _bounded_token(value: Any, label: str) -> str:
    text = str(value).strip()
    if not _short_text(text, 200):
        raise RetrospectiveError(f"{label} is invalid")
    return text


def _human_text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not _short_text(value.strip(), limit):
        raise RetrospectiveError(f"{label} must be non-empty and at most {limit} characters")
    return value.strip()


def _short_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and "\x00" not in value


def _validate_refs(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value or len(value) > 50 or len(value) != len(set(value)):
        raise RetrospectiveError(f"{label} must be a bounded unique list")
    for item in value:
        if not _short_text(item, 500) or item.startswith("/") or ".." in item.split("/"):
            raise RetrospectiveError(f"{label} contains an unsafe reference")


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    rounded = round(float(value), 3)
    return int(rounded) if rounded.is_integer() else rounded


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str) or RFC3339_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview or publish a bounded milestone retrospective.")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze_parser = commands.add_parser("analyze")
    analyze_parser.add_argument("control_root")
    analyze_parser.add_argument("--boundary", required=True)
    analyze_parser.add_argument("--tasks", required=True)
    analyze_parser.add_argument("--commit-record")
    analyze_parser.add_argument("--work-root")
    analyze_parser.add_argument("--repo-id")
    analyze_parser.add_argument("--commit")
    analyze_parser.add_argument("--profile", default=DEFAULT_PROFILE)
    analyze_parser.add_argument("--without-model", action="store_true")
    analyze_parser.add_argument("--apply", action="store_true")
    analyze_parser.add_argument("--json", action="store_true")
    decide_parser = commands.add_parser("decide")
    decide_parser.add_argument("control_root")
    decide_parser.add_argument("--boundary", required=True)
    decide_parser.add_argument("--proposal", required=True)
    decide_parser.add_argument("--decision", required=True, choices=tuple(DECISIONS))
    decide_parser.add_argument("--approver", required=True)
    decide_parser.add_argument("--reason", required=True)
    decide_parser.add_argument("--human-approved", action="store_true")
    decide_parser.add_argument("--apply", action="store_true")
    decide_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            payload = analyze_milestone(
                args.control_root, boundary_id=args.boundary,
                task_ids=tuple(item.strip() for item in args.tasks.split(",") if item.strip()),
                commit_record=args.commit_record, work_root=args.work_root,
                repo_id=args.repo_id, commit=args.commit, profile=args.profile,
                without_model=args.without_model, apply=args.apply,
            )
        else:
            payload = decide_proposal(
                args.control_root, boundary_id=args.boundary, proposal_id=args.proposal,
                decision=args.decision, approver=args.approver, reason=args.reason,
                human_approved=args.human_approved, apply=args.apply,
            )
    except (OSError, RetrospectiveError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Boundary: {payload['boundary_id']}")
        print(f"Disposition: {payload.get('disposition', payload.get('status'))}")
        print(f"Applied: {'yes' if payload.get('applied') else 'no'}")
    return 1 if payload.get("disposition") == "BLOCKED_INSUFFICIENT_EVIDENCE" else 0


analyze = analyze_milestone
decide = decide_proposal


if __name__ == "__main__":
    raise SystemExit(main())
