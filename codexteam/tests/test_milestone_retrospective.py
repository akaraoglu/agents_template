from __future__ import annotations

import hashlib
import fcntl
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import codexteam_tools.milestone_retrospective as retrospective
from codexteam_tools.milestone_retrospective import (
    FIXED_REMEDIATION_RECIPES,
    RetrospectiveError,
    _build_proposals,
    _preparation_boundary_digest,
    _prepared_analysis_digest,
    accept_evaluation,
    analyze_milestone,
    build_evaluation_request,
    build_model_request,
    decide_proposal,
    evaluate_milestone,
    prepare_milestone,
    qualify_signals,
    _structured_finding,
    _terminal_gate_digest,
    validate_disposition,
    validate_evaluation_report,
    validate_preparation,
    validate_proposal,
    validate_retrospective,
    validate_v2_analysis,
    validate_v2_proposal,
    _NoRedirect,
    _post_ollama,
)
from codexteam_tools.contract_registry import EVALUATION_CHECKS
from codexteam_tools.agent_specs import load_agent_spec


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "milestone-retrospective.py"
BOUNDARY = "M12"
TASK = "T001"
TEAM = "team-demo"
ATTEMPT = "att-001"
PROPOSAL = "IMP-M12-CF233112E9F1FE8C-001"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _result(*, role: str = "reviewer", secret: str = "") -> dict:
    return {
        "schema_version": "1.0",
        "result_id": "res-t001-att-001",
        "team_id": TEAM,
        "task_id": TASK,
        "agent_role": role,
        "attempt_id": ATTEMPT,
        "status": "completed",
        "summary": f"Reviewed and accepted the milestone. {secret}",
        "output": {
            "exit_code": 0,
            "stdout_tail": f"PRIVATE_PROCESS_OUTPUT {secret}",
            "stderr_tail": "PRIVATE_STDERR",
            "duration_seconds": 1,
        },
        "file_changes": [{"path": "src/main.py", "action": "modified", "size_bytes": 10}],
        "evidence": [{
            "type": "code_review",
            "artifact_ref": "results/review.md",
            "summary": "Review passed.",
            "metadata": {},
        }],
        "requested_followups": [],
        "errors": [],
        "warnings": [],
        "limitations": [],
        "produced_at": "2026-08-28T10:00:00Z",
    }


def _gate(control: Path, work: Path, *, split: bool) -> dict:
    source_digest = hashlib.sha256(b"VALUE = 1\n").hexdigest()
    workspace_digest = hashlib.sha256(
        json.dumps(
            {"src/main.py": source_digest},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    value = {
        "schema_version": "1.0",
        "gate": "integration",
        "status": "passed",
        "project_root": str(work),
        "execution_surface": "worker",
        "started_at": "2026-08-28T10:00:00Z",
        "completed_at": "2026-08-28T10:00:02Z",
        "duration_seconds": 2,
        "verification_paths": ["src/**"],
        "configuration_digest": "1" * 64,
        "workspace_digest": workspace_digest,
        "commands": [{
            "gate": "integration",
            "argv": ["python", "-m", "pytest"],
            "exit_code": 0,
            "duration_seconds": 2,
            "stdout_tail": "PRIVATE_GATE_OUTPUT",
            "stderr_tail": "",
        }],
    }
    if split:
        value.update({
            "control_root": str(control),
            "work_root": str(work),
            "git_root": str(work),
            "git_prefix": ".",
            "repo_id": "product",
        })
    return value


def _write_attempt(
    control: Path,
    work: Path,
    attempt_id: str,
    *,
    role: str = "reviewer",
    modern_missing_pins: bool = False,
    metrics: list[dict] | None = None,
) -> None:
    attempt = control / ".codexteam/runtime/sessions" / TEAM / TASK / attempt_id
    turns = attempt / "turns"
    turns.mkdir(parents=True)
    session: dict[str, object] = {
        "team_id": TEAM,
        "task_id": TASK,
        "attempt_id": attempt_id,
        "agent_role": role,
        "workspace_root": str(work),
        "model_profile": "codex/qwen38-27b",
        "last_status": "finalized",
    }
    if control != work:
        session.update(
            {
                "control_root": str(control),
                "work_root": str(work),
                "git_root": str(work),
                "git_prefix": ".",
                "repo_id": "product",
            }
        )
    if modern_missing_pins:
        session["execution_spec"] = {
            "contract": "execution-spec",
            "path": "execution-spec.json",
            "digest": "a" * 64,
        }
    (attempt / "session.json").write_text(json.dumps(session))
    for number, activity in enumerate(metrics or [], 1):
        phase = activity.pop("phase", "draft")
        metric = {
            "schema_version": "1.0",
            "metric_scope": "worker_turn",
            "task_id": TASK,
            "attempt_id": attempt_id,
            "agent_role": role,
            "model_profile": "qwen38-27b",
            "source_event_file": f"{number:03d}-{phase}.jsonl",
            "turn": {
                "number": number,
                "phase": phase,
                "completed": True,
                "duration_seconds": 1,
                "terminal_reason": "completed",
            },
            "reasoning": {"requested": "medium", "effective": "medium"},
            "process": {
                "exit_code": 0,
                "timed_out": activity.pop("timed_out", False),
                "guard_triggered": activity.pop("guard_triggered", False),
                "classification": "success",
            },
            "prompt_bytes": 100,
            "usage": {
                "cumulative": {},
                "delta": {},
                "delta_mode": "initial",
            },
            "activity": {
                "tool_calls": 1,
                "failed_tool_calls": 0,
                "command_calls": 1,
                "failed_command_calls": 0,
                "edit_events": 0,
                "agent_messages": 1,
                "command_output_bytes": 10,
                "max_command_output_bytes": 10,
                "item_type_counts": {},
                "repeated_commands": [],
                "largest_commands": [],
                "mcp": {"calls": 0, "failed_calls": 0, "command_calls_after_failure": 0},
                **activity,
            },
            "events": {"parse_error_count": 0, "last_error": None, "diagnostics": {}},
            "generated_at": "2026-08-28T10:00:00Z",
        }
        (turns / f"{number:03d}-{phase}.metrics.json").write_text(json.dumps(metric))


def _project(
    tmp_path: Path,
    *,
    split: bool = False,
    second_attempt: bool = False,
    modern_missing_pins: bool = False,
    result_role: str = "reviewer",
    attempt_role: str = "reviewer",
    secret: str = "",
    metrics: list[dict] | None = None,
) -> tuple[Path, Path, str]:
    control = tmp_path / "control"
    control.mkdir(parents=True)
    work = tmp_path / "source" if split else control
    if split:
        work.mkdir()
    git(work, "init", "--initial-branch", "main")
    git(work, "config", "user.name", "CodexTeam Test")
    git(work, "config", "user.email", "codexteam@example.invalid")

    (control / "management").mkdir()
    (control / "management/BACKLOG.md").write_text(
        "# Backlog\n\n## Improvement Proposals\n"
    )
    (control / "results/gates/accepted").mkdir(parents=True)
    (control / "results/review.md").write_text("reviewed\n")
    (control / "results/T001-att-001.json").write_text(
        json.dumps(_result(role=result_role, secret=secret))
    )
    (control / "TASKS.md").write_text(
        "# Tasks\n\n| Task ID | Description | Status | Owner | Verification | Evidence |\n"
        "|---|---|---|---|---|---|\n"
        "| T001 | Review | Completed | reviewer | Passed | `results/T001-att-001.json`, `results/T001-verification.txt` |\n"
    )
    _write_attempt(
        control, work, ATTEMPT, role=attempt_role,
        modern_missing_pins=modern_missing_pins, metrics=metrics,
    )
    if second_attempt:
        _write_attempt(control, work, "att-002", role=attempt_role)

    gate = _gate(control, work, split=split)
    (control / "results/gates/integration.json").write_text(json.dumps(gate))
    gate_digest = hashlib.sha256(
        json.dumps(gate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot = {
        "schema_version": "1.0",
        "kind": "accepted_gate_snapshot",
        "task_id": TASK,
        "attempt_id": ATTEMPT,
        "gate": "integration",
        "record_sha256": gate_digest,
        "record": gate,
    }
    (control / f"results/gates/accepted/T001-att-001-integration-{gate_digest[:16]}.json").write_text(
        json.dumps(snapshot)
    )
    (work / "src").mkdir()
    (work / "src/main.py").write_text("VALUE = 1\n")

    if split:
        git(work, "add", "src/main.py")
    else:
        git(work, "add", ".")
    git(
        work,
        "commit",
        "-m",
        "feat: verified milestone",
        "-m",
        "CodexTeam-Boundary: M12\nCodexTeam-Tasks: T001\n"
        "CodexTeam-Verification: results/gates/integration.json",
    )
    commit = git(work, "rev-parse", "HEAD")
    parents = git(work, "rev-list", "--parents", "-n", "1", commit).split()
    if split:
        (control / "REPOSITORIES.json").write_text(json.dumps({
            "schema_version": "1.0",
            "repositories": [{
                "id": "product",
                "work_root": str(work),
                "git_root": str(work),
                "git_prefix": ".",
                "remote_url": None,
                "write_policy": "task-owned",
            }],
        }))
    else:
        paths = sorted(git(
            work, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit
        ).splitlines())
        record_path = control / ".codexteam/runtime/git-steward/M12/commit-record.json"
        record_path.parent.mkdir(parents=True)
        record_path.write_text(json.dumps({
            "schema_version": "1.0",
            "boundary_id": BOUNDARY,
            "status": "committed",
            "project_root": str(control),
            "branch": "main",
            "head_before": parents[1] if len(parents) == 2 else None,
            "head_after": commit,
            "tree": git(work, "rev-parse", f"{commit}^{{tree}}"),
            "committed_paths": paths,
            "verification": {
                "kind": "integration",
                "artifact_ref": "results/gates/integration.json",
                "workspace_digest": gate["workspace_digest"],
            },
            "commit_subject": "feat: verified milestone",
            "committed_at": "2026-08-28T10:00:03Z",
        }))
    return control, work, commit


def _analyze(control: Path, **kwargs):
    return analyze_milestone(
        control,
        boundary_id=BOUNDARY,
        task_ids=(TASK,),
        without_model=True,
        **kwargs,
    )


def _prepare(control: Path, **kwargs):
    return prepare_milestone(
        control,
        boundary_id=BOUNDARY,
        task_ids=(TASK,),
        **kwargs,
    )


def _write_evaluation_report(
    control: Path,
    preparation: dict,
    *,
    action: str,
    evidence_refs: list[str] | None = None,
    target: str | None = None,
    mechanism: str | None = None,
    injected_text: str | None = None,
) -> tuple[str, str]:
    report_ref = (
        f"results/retrospectives/{BOUNDARY}/evaluations/"
        f"{preparation['preparation_digest']}.json"
    )
    observations = preparation["preparation"]["observations"]
    proposals = []
    investigations = []
    if action == "PROPOSE":
        recipe = FIXED_REMEDIATION_RECIPES.get(
            observations[0]["recurrence_key"],
            {
                "target": "unsupported evaluator target",
                "mechanism": "Unsupported evaluator mechanism.",
            },
        )
        proposals = [{
            "proposal_id": "EVAL-PROP-001",
            "observation_ids": [observations[0]["observation_id"]],
            "target": target or recipe["target"],
            "mechanism": mechanism or recipe["mechanism"],
            "alternatives": ["Retain post-run detection only."],
            "validation_cases": [
                "A missing execution specification is rejected before worker execution.",
                "A valid pinned execution specification remains accepted.",
            ],
            "rollback": injected_text or "Remove the pre-execution rejection and restore post-run detection.",
            "evidence_refs": (
                evidence_refs
                if evidence_refs is not None
                else observations[0]["evidence_refs"]
            ),
            "creates_task": False,
            "grants_implementation_authority": False,
        }]
    elif action == "INVESTIGATE":
        investigations = [{
            "investigation_id": "INV-001",
            "observation_ids": [observations[0]["observation_id"]],
            "question": "Which natural complexity or avoidable mechanism caused this recurrence?",
            "discriminator": "Inspect one bounded reason event that distinguishes the alternatives.",
            "evidence_needed": ["A structured reason code for the observed event."],
            "evidence_refs": (
                evidence_refs
                if evidence_refs is not None
                else observations[0]["evidence_refs"]
            ),
        }]
    assessments = []
    for index, observation in enumerate(observations):
        selected_action = action if index == 0 else "NO_CHANGE"
        assessments.append({
            "observation_id": observation["observation_id"],
            "evidence_ceiling": observation["action_ceiling"],
            "classification": (
                "AVOIDABLE_FRICTION" if selected_action == "PROPOSE"
                else "INSUFFICIENT_EVIDENCE"
            ),
            "facts": [observation["statement"]],
            "hypotheses": ["The observation may indicate avoidable friction."],
            "alternatives": ["The observation may reflect natural complexity."],
            "discriminator": "Inspect evidence that distinguishes the competing explanations.",
            "action": selected_action,
            "rationale": injected_text or "The prepared evidence supports this bounded action.",
            "evidence_refs": (
                evidence_refs if index == 0 and evidence_refs is not None
                else observation["evidence_refs"]
            ),
        })
    checks = {
        name: {"status": "PASS", "detail": f"{name} passed."}
        for name in EVALUATION_CHECKS
    }
    packet = preparation["preparation"]
    spec = load_agent_spec("agent-evaluator", expected_role="reviewer")
    request, _ = build_evaluation_request(packet, profile="qwen38-27b")
    report = {
        "schema_version": "1.0",
        "boundary_id": BOUNDARY,
        "preparation_digest": preparation["preparation_digest"],
        "evidence_digest": preparation["evidence_digest"],
        "boundary_digest": _preparation_boundary_digest(packet),
        "prepared_analysis_digest": _prepared_analysis_digest(packet),
        "agent_spec_id": spec.agent_spec_id,
        "agent_spec_version": spec.version,
        "agent_spec_digest": request["format"]["properties"]["agent_spec_digest"]["const"],
        "profile": "codex/qwen38-27b",
        "verdict": "ACCEPT",
        "checks": checks,
        "observation_assessments": assessments,
        "investigations": investigations,
        "proposals": proposals,
        "creates_task": False,
        "grants_implementation_authority": False,
    }
    report_path = control / report_ref
    report_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(content)
    return hashlib.sha256(content.encode()).hexdigest(), report_ref


def test_no_change_preview_and_atomic_apply(tmp_path: Path):
    control, _, _ = _project(tmp_path)

    preview = _analyze(control)
    assert preview["disposition"] == "NO_CHANGE"
    assert not (control / "results/retrospectives").exists()

    applied = _analyze(control, apply=True)
    destination = control / "results/retrospectives/M12"
    assert applied["disposition"] == "NO_CHANGE"
    assert {path.name for path in destination.iterdir()} == {
        "evidence.json", "analysis.json", "RETROSPECTIVE.md", "dispositions",
    }
    validate_retrospective(json.loads((destination / "analysis.json").read_text()))
    assert not list(destination.parent.glob(".M12.*"))


def test_reviewer_result_uses_its_exact_accepted_integration_snapshot(tmp_path: Path):
    control, _, _ = _project(tmp_path)
    accepted = control / "results/gates/accepted"
    original = next(accepted.iterdir())
    duplicate = accepted / original.name.replace(".json", "-duplicate.json")
    duplicate.write_bytes(original.read_bytes())

    blocked = _analyze(control)

    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "accepted_gate_identity"


def test_result_role_mismatch_blocks_and_modern_missing_pins_are_hard_signals(tmp_path: Path):
    mismatch, _, _ = _project(tmp_path / "mismatch", result_role="reviewer", attempt_role="developer")
    blocked = _analyze(mismatch)
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "attempt_identity"

    modern, _, _ = _project(tmp_path / "modern", modern_missing_pins=True)
    preview = _analyze(modern)
    keys = {item["recurrence_key"]: item for item in preview["signals"]}
    assert preview["disposition"] == "PROPOSALS_RECORDED"
    assert keys["identity:invalid-execution-spec"]["qualification"] == "hard"
    assert keys["identity:invalid-delegation"]["qualification"] == "hard"


def test_proposal_apply_and_idempotent_recovery(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)

    first = _analyze(control, apply=True)
    second = _analyze(control, apply=True)
    backlog = (control / "management/BACKLOG.md").read_text()

    assert first["disposition"] == "PROPOSALS_RECORDED"
    proposal = first["proposals"][0]
    validate_proposal(proposal)
    assert proposal["status"] == "Proposed"
    assert backlog.count(f"<!-- codexteam-improvement:{PROPOSAL} -->") == 1
    assert "- Creates task: No" in backlog
    assert "- Implementation authority: Not granted" in backlog
    assert second["idempotent"] is True


def test_malformed_evidence_model_failure_and_backlog_conflict_return_blocked(tmp_path: Path):
    malformed, _, _ = _project(tmp_path / "malformed")
    (malformed / "results/T001-att-001.json").write_text("not json")
    assert _analyze(malformed)["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"

    model, _, _ = _project(tmp_path / "model")
    def unavailable(request, **kwargs):
        raise OSError("model unavailable")
    failed_model = analyze_milestone(
        model,
        boundary_id=BOUNDARY,
        task_ids=(TASK,),
        model_runner=unavailable,
        apply=True,
    )
    assert failed_model["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert not (model / "results/retrospectives").exists()

    conflict, _, _ = _project(tmp_path / "conflict", second_attempt=True)
    (conflict / "management/BACKLOG.md").write_text(
        f"# Backlog\n\n{PROPOSAL} conflicting content\n"
    )
    blocked = _analyze(conflict, apply=True)
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert not (conflict / "results/retrospectives").exists()


def test_commit_record_and_verification_are_strongly_bound(tmp_path: Path):
    control, _, _ = _project(tmp_path)
    record_path = control / ".codexteam/runtime/git-steward/M12/commit-record.json"
    record = json.loads(record_path.read_text())
    record["verification"]["kind"] = "architecture"
    record_path.write_text(json.dumps(record))
    blocked = _analyze(control)
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "commit_record_identity"

    control2, _, _ = _project(tmp_path / "digest")
    gate_path = control2 / "results/gates/integration.json"
    gate = json.loads(gate_path.read_text())
    gate["workspace_digest"] = "f" * 64
    gate_path.write_text(json.dumps(gate))
    blocked = _analyze(control2)
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "milestone_gate_identity"


def test_multitask_commit_must_match_terminal_task_gate_digest(tmp_path: Path):
    tasks = [
        {"task_id": "T001", "accepted_gate": {"workspace_digest": "a" * 64}},
        {"task_id": "T002", "accepted_gate": {"workspace_digest": "b" * 64}},
    ]
    assert _terminal_gate_digest(tasks) == "b" * 64


def test_split_root_identity_isolation_and_exact_verification_trailer(tmp_path: Path):
    control, work, commit = _project(tmp_path, split=True)
    preview = _analyze(control, work_root=work, repo_id="product", commit=commit)
    assert preview["disposition"] == "NO_CHANGE"

    other = tmp_path / "other"
    other.mkdir()
    blocked = _analyze(control, work_root=other, repo_id="product", commit=commit)
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "repository_identity"

    (work / "src/main.py").write_text("VALUE = 2\n")
    git(work, "add", "src/main.py")
    git(
        work,
        "commit",
        "-m",
        "feat: wrong verification",
        "-m",
        "CodexTeam-Boundary: M12\nCodexTeam-Tasks: T001",
    )
    wrong_commit = git(work, "rev-parse", "HEAD")
    wrong = _analyze(control, work_root=work, repo_id="product", commit=wrong_commit)
    assert wrong["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert wrong["blocking_reasons"][0]["code"] == "commit_trailers"

    gate_mismatch, mismatch_work, _ = _project(tmp_path / "tree-mismatch", split=True)
    (mismatch_work / "src/main.py").write_text("VALUE = 9\n")
    git(mismatch_work, "add", "src/main.py")
    git(
        mismatch_work,
        "commit",
        "-m",
        "feat: mismatched tree",
        "-m",
        "CodexTeam-Boundary: M12\nCodexTeam-Tasks: T001\n"
        "CodexTeam-Verification: results/gates/integration.json",
    )
    mismatch_commit = git(mismatch_work, "rev-parse", "HEAD")
    mismatch = _analyze(
        gate_mismatch,
        work_root=mismatch_work,
        repo_id="product",
        commit=mismatch_commit,
    )
    assert mismatch["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert mismatch["blocking_reasons"][0]["code"] == "milestone_gate_identity"


def test_safe_fingerprints_qualify_across_turns_without_command_text():
    evidence = {
        "tasks": [{
            "task_id": TASK,
            "result": {"ref": "results/T001-att-001.json", "findings": []},
            "attempts": [{
                "ref": "runtime/attempt",
                "execution_spec_status": "legacy",
                "delegation_status": "legacy",
                "feedback_count": 0,
                "status": "finalized",
                "turns": [
                    {
                        "ref": "runtime/turn-1", "timed_out": False,
                        "guard_triggered": False, "failed_activity": 0,
                        "mcp_failed": 0, "fallback_commands": 0,
                        "command_fingerprints": {"abcdef1234567890": 1},
                    },
                    {
                        "ref": "runtime/turn-2", "timed_out": False,
                        "guard_triggered": False, "failed_activity": 0,
                        "mcp_failed": 0, "fallback_commands": 0,
                        "command_fingerprints": {"abcdef1234567890": 2},
                    },
                ],
            }],
        }],
    }
    signals = qualify_signals(evidence)
    assert [item["recurrence_key"] for item in signals] == [
        "tool-loop:abcdef1234567890"
    ]


def test_benign_scope_wording_does_not_create_a_hard_signal():
    control_warning = "Test scope was limited to the approved component."
    explicit_marker = "[scope-violation] Worker changed a denied path."
    assert _structured_finding(control_warning)["hard"] is False
    finding = _structured_finding(explicit_marker)
    assert finding["hard"] is True
    assert finding["category"] == "scope-violation"


def test_private_outputs_never_reach_artifacts_or_tool_free_model(tmp_path: Path):
    secret = "SECRET_TRANSCRIPT_7f04"
    control, _, _ = _project(tmp_path, second_attempt=True, secret=secret)
    calls = []

    def runner(request, **kwargs):
        calls.append((request, kwargs))
        return {
            "message": {"content": json.dumps({
                "schema_version": "1.0",
                "summary": "Use deterministic proposal.",
                "recommendations": [{
                    "recurrence_keys": ["correction:replacement-attempt"],
                    "candidate_type": "instruction",
                    "rationale": "Reduce replacement attempts.",
                }],
            })},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

    preview = analyze_milestone(
        control,
        boundary_id=BOUNDARY,
        task_ids=(TASK,),
        model_runner=runner,
    )
    serialized = json.dumps(preview)
    request_text = json.dumps(calls[0][0])
    assert preview["disposition"] == "PROPOSALS_RECORDED"
    assert secret not in serialized and secret not in request_text
    assert "PRIVATE_PROCESS_OUTPUT" not in serialized and "PRIVATE_GATE_OUTPUT" not in serialized
    assert "PRIVATE_PROCESS_OUTPUT" not in request_text and "PRIVATE_GATE_OUTPUT" not in request_text
    assert "tools" not in calls[0][0]
    assert calls[0][1] == {"timeout_seconds": 300}

    blocked = analyze_milestone(
        control,
        boundary_id=BOUNDARY,
        task_ids=(TASK,),
        profile="gpt54-mini",
    )
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    with pytest.raises(RetrospectiveError, match="local Ollama"):
        build_model_request({}, [], profile="gpt54-mini")

    def tool_runner(request, **kwargs):
        return {
            "message": {
                "content": json.dumps({
                    "schema_version": "1.0", "summary": "", "recommendations": [],
                }),
                "tool_calls": [{"function": {"name": "shell"}}],
            }
        }

    tool_blocked = analyze_milestone(
        control,
        boundary_id=BOUNDARY,
        task_ids=(TASK,),
        model_runner=tool_runner,
        apply=True,
    )
    assert tool_blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert not (control / "results/retrospectives").exists()


@pytest.mark.parametrize(("decision", "status"), [
    ("approve", "Approved"), ("reject", "Rejected"), ("defer", "Deferred"),
])
def test_disposition_requires_explicit_human_approval_and_is_planning_only(
    tmp_path: Path, decision: str, status: str,
):
    control, _, _ = _project(tmp_path, second_attempt=True)
    _analyze(control, apply=True)

    preview = decide_proposal(
        control,
        boundary_id=BOUNDARY,
        proposal_id=PROPOSAL,
        decision=decision,
        approver="A. Human",
        reason="Reviewed evidence.",
        human_approved=False,
    )
    assert preview["applied"] is False
    with pytest.raises(RetrospectiveError, match="human_approved"):
        decide_proposal(
            control,
            boundary_id=BOUNDARY,
            proposal_id=PROPOSAL,
            decision=decision,
            approver="A. Human",
            reason="Reviewed evidence.",
            human_approved=False,
            apply=True,
        )

    applied = decide_proposal(
        control,
        boundary_id=BOUNDARY,
        proposal_id=PROPOSAL,
        decision=decision,
        approver="A. Human",
        reason="Reviewed evidence.",
        human_approved=True,
        apply=True,
    )
    record = json.loads((control / applied["record_ref"]).read_text())
    validate_disposition(record)
    assert record["status"] == status
    assert len(record["proposal_sha256"]) == 64
    assert record["approval_scope"] == ("planning-only" if decision == "approve" else "not-approved")
    assert record["creates_task"] is False
    assert record["grants_implementation_authority"] is False


def test_disposition_recovers_matching_record_without_backlog_update(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    _analyze(control, apply=True)
    path = control / f"results/retrospectives/M12/dispositions/{PROPOSAL}.json"
    record = {
        "schema_version": "1.0",
        "boundary_id": BOUNDARY,
        "proposal_id": PROPOSAL,
        "proposal_sha256": hashlib.sha256(
            json.dumps(
                json.loads(
                    (control / "results/retrospectives/M12/analysis.json").read_text()
                )["proposals"][0],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "decision": "approve",
        "status": "Approved",
        "approver": "A. Human",
        "reason": "Reviewed evidence.",
        "decided_at": "2026-08-28T11:00:00Z",
        "approval_scope": "planning-only",
        "creates_task": False,
        "grants_implementation_authority": False,
    }
    path.write_text(json.dumps(record))

    recovered = decide_proposal(
        control,
        boundary_id=BOUNDARY,
        proposal_id=PROPOSAL,
        decision="approve",
        approver="A. Human",
        reason="Reviewed evidence.",
        human_approved=True,
        apply=True,
    )

    assert recovered["idempotent"] is True
    assert "- Status: Approved" in (control / "management/BACKLOG.md").read_text()
    assert path.read_text() == json.dumps(record)


def test_disposition_rejects_tampered_analysis_and_proposal_digest(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    _analyze(control, apply=True)
    analysis_path = control / "results/retrospectives/M12/analysis.json"
    analysis = json.loads(analysis_path.read_text())
    analysis["proposals"][0]["trigger"] = "Tampered proposal"
    analysis_path.write_text(json.dumps(analysis))

    with pytest.raises(RetrospectiveError, match="deterministic evidence"):
        decide_proposal(
            control,
            boundary_id=BOUNDARY,
            proposal_id=PROPOSAL,
            decision="approve",
            approver="A. Human",
            reason="Reviewed evidence.",
            human_approved=True,
            apply=True,
        )


def test_disposition_rejects_matching_record_with_wrong_proposal_digest(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    _analyze(control, apply=True)
    path = control / f"results/retrospectives/M12/dispositions/{PROPOSAL}.json"
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "boundary_id": BOUNDARY,
        "proposal_id": PROPOSAL,
        "proposal_sha256": "0" * 64,
        "decision": "approve",
        "status": "Approved",
        "approver": "A. Human",
        "reason": "Reviewed evidence.",
        "decided_at": "2026-08-28T11:00:00Z",
        "approval_scope": "planning-only",
        "creates_task": False,
        "grants_implementation_authority": False,
    }))

    with pytest.raises(RetrospectiveError, match="conflicting disposition"):
        decide_proposal(
            control,
            boundary_id=BOUNDARY,
            proposal_id=PROPOSAL,
            decision="approve",
            approver="A. Human",
            reason="Reviewed evidence.",
            human_approved=True,
            apply=True,
        )


def test_boundary_variants_have_distinct_proposal_ids():
    signal = {
        "recurrence_key": "correction:replacement-attempt",
        "category": "correction",
        "impact": "medium",
        "count": 1,
        "distinct_task_count": 1,
        "task_ids": [TASK],
        "evidence_refs": ["results/T001-att-001.json"],
        "recommended_response_class": "instruction",
        "qualification": "threshold",
    }
    ids = {
        _build_proposals(boundary, [signal])[0]["proposal_id"]
        for boundary in ("M.12", "M-12", "m-12")
    }
    assert len(ids) == 3


@pytest.mark.parametrize(
    ("validator", "value"),
    (
        (validate_retrospective, {"schema_version": "1.0"}),
        (validate_proposal, {"schema_version": "1.0"}),
        (validate_disposition, {"schema_version": "1.0"}),
    ),
)
def test_strict_contract_validators_reject_missing_fields(validator, value):
    with pytest.raises(RetrospectiveError, match="strict contract"):
        validator(value)


def test_split_root_requires_explicit_session_core_identity(tmp_path: Path):
    control, work, commit = _project(tmp_path, split=True)
    session_path = control / f".codexteam/runtime/sessions/{TEAM}/{TASK}/{ATTEMPT}/session.json"
    session = json.loads(session_path.read_text())
    session.pop("task_id")
    session_path.write_text(json.dumps(session))

    blocked = _analyze(control, work_root=work, repo_id="product", commit=commit)

    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "attempt_identity"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(boundary_id=" M12"),
        lambda value: value["signals"][0].update(count=True),
        lambda value: value.update(proposals=[]),
    ),
)
def test_retrospective_validator_rejects_semantic_contract_drift(mutation):
    signal = {
        "recurrence_key": "correction:replacement-attempt",
        "category": "correction",
        "impact": "medium",
        "count": 1,
        "distinct_task_count": 1,
        "task_ids": [TASK],
        "evidence_refs": ["results/T001-att-001.json"],
        "recommended_response_class": "instruction",
        "qualification": "threshold",
    }
    proposal = {
        "schema_version": "1.0",
        "proposal_id": PROPOSAL,
        "boundary_id": BOUNDARY,
        "recurrence_key": signal["recurrence_key"],
        "category": "instruction",
        "scope": "existing project or role guidance",
        "impact": "medium",
        "confidence": "medium",
        "evidence": signal["evidence_refs"],
        "trigger": "Replacement attempt.",
        "expected_gain": "Reduce correction.",
        "validation": "Verify recurrence is absent.",
        "rollback": "Revert the planning change.",
        "status": "Proposed",
        "human_disposition": "None",
        "creates_task": False,
        "grants_implementation_authority": False,
    }
    value = {
        "schema_version": "1.0",
        "boundary_id": BOUNDARY,
        "evidence_digest": "a" * 64,
        "disposition": "PROPOSALS_RECORDED",
        "signals": [signal],
        "proposals": [proposal],
        "advisory_model": None,
    }
    mutation(value)

    with pytest.raises((RetrospectiveError, ValueError)):
        validate_retrospective(value)


def test_cli_does_not_expose_historical_v1_analysis(tmp_path: Path):
    control, _, _ = _project(tmp_path)
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "analyze", str(control),
            "--boundary", BOUNDARY, "--tasks", TASK, "--without-model", "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr
    assert not (control / "results/retrospectives").exists()


def test_advisory_project_lock_ignores_stale_file_and_blocks_active_holder(tmp_path: Path):
    control, _, _ = _project(tmp_path)
    lock = control / ".codexteam/runtime/milestone-retrospective.lock"
    lock.write_text("stale metadata\n")
    assert _analyze(control, apply=True)["disposition"] == "NO_CHANGE"

    other, _, _ = _project(tmp_path / "held")
    held_lock = other / ".codexteam/runtime/milestone-retrospective.lock"
    held_lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(held_lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        blocked = _analyze(other, apply=True)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert "project lock" in blocked["blocking_reasons"][0]["message"]


def test_v2_prepare_is_conservative_content_addressed_and_backlog_free(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    backlog_before = (control / "management/BACKLOG.md").read_text()

    preview = _prepare(control)
    assert preview["disposition"] == "PREPARED"
    assert preview["preparation"]["observations"][0]["evidence_strength"] == "E1"
    assert preview["preparation"]["assessments"][0]["default_action"] == "NO_CHANGE"
    assert preview["preparation"]["assessments"][0]["fixed_recipe"] is None
    assert not (control / "results/retrospectives").exists()

    applied = _prepare(control, apply=True)
    packet_path = Path(applied["artifact_root"]) / "preparation.json"
    validate_preparation(json.loads(packet_path.read_text()))
    assert packet_path.is_file()
    assert Path(applied["artifact_root"]).name == applied["preparation_digest"]
    assert (control / "management/BACKLOG.md").read_text() == backlog_before
    assert _prepare(control, apply=True)["idempotent"] is True


def test_v2_rejects_historical_v1_boundary_backfill(tmp_path: Path):
    control, _, _ = _project(tmp_path)
    _analyze(control, apply=True)

    blocked = _prepare(control, apply=True)

    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "historical_v1_boundary"
    assert not (control / f"results/retrospectives/{BOUNDARY}/preparations").exists()


def test_v2_prepare_uses_exact_fixed_recipe_only_for_hard_identity_evidence(tmp_path: Path):
    control, _, _ = _project(tmp_path, modern_missing_pins=True)

    prepared = _prepare(control)
    observations = {
        item["recurrence_key"]: item for item in prepared["preparation"]["observations"]
    }
    assessments = {
        item["observation_id"]: item for item in prepared["preparation"]["assessments"]
    }

    for key in ("identity:invalid-execution-spec", "identity:invalid-delegation"):
        observation = observations[key]
        assert observation["evidence_strength"] == "E3"
        assert assessments[observation["observation_id"]]["fixed_recipe"] is not None
        assert assessments[observation["observation_id"]]["default_action"] == "NO_CHANGE"


def test_v2_evaluate_is_tool_free_local_and_exclusively_writes_report(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    packet = prepared["preparation"]
    request, profile = build_evaluation_request(packet, profile="qwen38-27b")
    assert profile == "codex/qwen38-27b"
    assert "tools" not in request
    assert "MCP" in request["messages"][0]["content"]
    with pytest.raises(RetrospectiveError, match="local Ollama"):
        build_evaluation_request(packet, profile="gpt54-mini")

    _, report_ref = _write_evaluation_report(control, prepared, action="NO_CHANGE")
    response = json.loads((control / report_ref).read_text())
    (control / report_ref).unlink()
    before = {path.relative_to(control).as_posix() for path in control.rglob("*")}
    calls = []

    def runner(payload, **kwargs):
        calls.append((payload, kwargs))
        return {"message": {"content": json.dumps(response)}}

    preview = evaluate_milestone(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        model_runner=runner,
    )
    assert preview["applied"] is False
    assert {path.relative_to(control).as_posix() for path in control.rglob("*")} == before
    applied = evaluate_milestone(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        model_runner=runner, apply=True,
    )
    assert applied["evaluation_path"] == report_ref
    assert (control / report_ref).is_file()
    assert "tools" not in calls[0][0]
    assert calls[0][1] == {"timeout_seconds": 300}


def test_v2_evaluate_rejects_tool_calls_and_sanitizes_model_text(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    _, report_ref = _write_evaluation_report(
        control, prepared, action="NO_CHANGE",
        injected_text="safe\n<!-- codexteam-improvement:EVIL --> text\x00",
    )
    response = json.loads((control / report_ref).read_text())
    (control / report_ref).unlink()

    tool = evaluate_milestone(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        model_runner=lambda *_args, **_kwargs: {
            "message": {"content": json.dumps(response), "tool_calls": [{}]}
        },
    )
    assert tool["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"

    applied = evaluate_milestone(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        model_runner=lambda *_args, **_kwargs: {
            "message": {"content": json.dumps(response)}
        }, apply=True,
    )
    text = (control / applied["evaluation_path"]).read_text()
    assert "\x00" not in text and "<!--" not in text and "\nEVIL" not in text


def test_ollama_transport_disables_proxies_and_redirects(monkeypatch):
    captured = {}

    class Opener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            raise urllib.error.URLError("blocked")

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    with pytest.raises(RetrospectiveError, match="local Ollama"):
        _post_ollama({}, timeout_seconds=7)
    proxy, redirect = captured["handlers"]
    assert isinstance(proxy, urllib.request.ProxyHandler)
    assert vars(proxy).get("proxies") == {}
    assert isinstance(redirect, _NoRedirect)
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 7


def test_v2_accept_rejects_cross_observation_evidence(tmp_path: Path):
    control, _, _ = _project(
        tmp_path, modern_missing_pins=True, metrics=[{"timed_out": True}]
    )
    prepared = _prepare(control, apply=True)
    observations = prepared["preparation"]["observations"]
    assert len(observations) >= 2
    digest, path = _write_evaluation_report(control, prepared, action="PROPOSE")
    report_path = control / path
    report = json.loads(report_path.read_text())
    other = next(
        item for item in observations
        if item["evidence_refs"] != observations[0]["evidence_refs"]
    )
    report["observation_assessments"][0]["evidence_refs"] = other["evidence_refs"]
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(content)
    blocked = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=hashlib.sha256(content.encode()).hexdigest(),
        evaluation_path=path,
    )
    assert "exactly match" in blocked["blocking_reasons"][0]["message"]


def test_v2_accept_rejects_noncanonical_evaluation_path(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    digest, _ = _write_evaluation_report(control, prepared, action="NO_CHANGE")
    blocked = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest,
        evaluation_path=f"results/retrospectives/{BOUNDARY}/evaluations/other.json",
    )
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert "not canonical" in blocked["blocking_reasons"][0]["message"]


def test_v2_accept_no_change_binds_evaluator_and_preserves_private_data(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="NO_CHANGE")

    accepted = accept_evaluation(
        control,
        boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest,
        evaluation_path=path,
        apply=True,
    )

    persisted = json.loads((control / "results/retrospectives/M12/analysis-v2.json").read_text())
    validate_v2_analysis(persisted)
    assert accepted["disposition"] == "NO_CHANGE"
    assert accepted["proposals"] == []
    assert accepted["evaluator"]["agent_spec_id"] == "agent-evaluator"
    assert "No candidate recommended this round" in (
        control / "results/retrospectives/M12/RETROSPECTIVE-v2.md"
    ).read_text()
    assert "PRIVATE" not in json.dumps(persisted)


@pytest.mark.parametrize("missing", ("analysis-v2.json", "RETROSPECTIVE-v2.md"))
def test_v2_accept_recovers_one_missing_publication_file(tmp_path: Path, missing: str):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="NO_CHANGE")
    accepted = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )
    destination = Path(accepted["artifact_root"])
    (destination / missing).unlink()

    recovered = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )

    assert recovered["disposition"] == "NO_CHANGE"
    assert (destination / "analysis-v2.json").is_file()
    assert (destination / "RETROSPECTIVE-v2.md").is_file()


def test_v2_accept_retains_investigation_under_no_change(tmp_path: Path):
    control, _, _ = _project(tmp_path)
    result_path = control / "results/T001-att-001.json"
    result = json.loads(result_path.read_text())
    result["warnings"] = ["[evidence-integrity] Accepted evidence needs investigation."]
    result_path.write_text(json.dumps(result))
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="INVESTIGATE")
    accepted = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )
    assert accepted["disposition"] == "NO_CHANGE"
    assert accepted["investigations"]
    assert accepted["proposals"] == []


def test_v2_accept_enforces_ceiling_references_and_concrete_proposal(tmp_path: Path):
    e1, _, _ = _project(tmp_path / "e1", second_attempt=True)
    prepared_e1 = _prepare(e1, apply=True)
    digest, path = _write_evaluation_report(e1, prepared_e1, action="PROPOSE")
    blocked = accept_evaluation(
        e1,
        boundary_id=BOUNDARY,
        preparation_digest=prepared_e1["preparation_digest"],
        evaluation_digest=digest,
        evaluation_path=path,
    )
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert "ceiling" in blocked["blocking_reasons"][0]["message"]

    invented, _, _ = _project(tmp_path / "invented", modern_missing_pins=True)
    prepared_invented = _prepare(invented, apply=True)
    digest, path = _write_evaluation_report(
        invented, prepared_invented, action="PROPOSE", evidence_refs=["private/unknown.json"]
    )
    blocked = accept_evaluation(
        invented,
        boundary_id=BOUNDARY,
        preparation_digest=prepared_invented["preparation_digest"],
        evaluation_digest=digest,
        evaluation_path=path,
    )
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert "exactly match" in blocked["blocking_reasons"][0]["message"]

    recipe, _, _ = _project(tmp_path / "recipe", modern_missing_pins=True)
    prepared_recipe = _prepare(recipe, apply=True)
    digest, path = _write_evaluation_report(
        recipe, prepared_recipe, action="PROPOSE", mechanism="Model-selected mechanism."
    )
    blocked = accept_evaluation(
        recipe, boundary_id=BOUNDARY,
        preparation_digest=prepared_recipe["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path,
    )
    assert "fixed E3 recipe" in blocked["blocking_reasons"][0]["message"]


def test_v2_accept_rejects_tampered_report_and_agentspec_metadata(tmp_path: Path):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="NO_CHANGE")
    report_path = control / path
    report = json.loads(report_path.read_text())
    report["agent_spec_digest"] = "0" * 64
    report_path.write_text(json.dumps(report))

    blocked = accept_evaluation(
        control,
        boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest,
        evaluation_path=path,
    )

    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert blocked["blocking_reasons"][0]["code"] == "evaluation_digest"

    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(content)
    blocked = accept_evaluation(
        control,
        boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=hashlib.sha256(content.encode()).hexdigest(),
        evaluation_path=path,
    )
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert "evaluator identity" in blocked["blocking_reasons"][0]["message"]


def test_v2_accept_rejects_changed_evaluator_guidance(
    tmp_path: Path, monkeypatch,
):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="NO_CHANGE")
    changed = tmp_path / "changed-evaluator.md"
    original = retrospective.guidance_paths(
        load_agent_spec("agent-evaluator", expected_role="reviewer")
    )[0].read_text()
    changed.write_text(original + "\nChanged after evaluation.\n")
    monkeypatch.setattr(retrospective, "guidance_paths", lambda _spec: (changed,))

    blocked = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path,
    )

    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert "evaluator identity" in blocked["blocking_reasons"][0]["message"]


def test_v2_accept_adds_only_valid_e3_proposal_as_proposed(tmp_path: Path):
    control, _, _ = _project(tmp_path, modern_missing_pins=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="PROPOSE")

    accepted = accept_evaluation(
        control,
        boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest,
        evaluation_path=path,
        apply=True,
    )

    proposal = accepted["proposals"][0]
    validate_v2_proposal(proposal)
    assert accepted["disposition"] == "PROPOSALS_RECORDED"
    assert proposal["status"] == "Proposed"
    assert proposal["category"] == "system"
    assert proposal["impact"] == "high"
    assert proposal["action_band"] == "Candidate"
    assert proposal["change_risk"] == "medium"
    assert proposal["change_amount"] == "medium"
    assert proposal["reversibility"] == "managed"
    assert proposal["creates_task"] is False
    backlog = (control / "management/BACKLOG.md").read_text()
    assert backlog.count(f"<!-- codexteam-improvement:{proposal['proposal_id']} -->") == 1
    assert "- Creates task: No" in backlog
    assert not (control / "management/tasks").exists()

    decided = decide_proposal(
        control,
        boundary_id=BOUNDARY,
        proposal_id=proposal["proposal_id"],
        decision="approve",
        approver="A. Human",
        reason="Approved for planning only.",
        human_approved=True,
        apply=True,
    )
    assert decided["approval_scope"] == "planning-only"
    assert decided["creates_task"] is False
    assert decided["grants_implementation_authority"] is False
    assert "- Status: Approved" in (control / "management/BACKLOG.md").read_text()


def test_v2_accepted_proposal_remains_decidable_after_guidance_change(
    tmp_path: Path, monkeypatch,
):
    control, _, _ = _project(tmp_path, modern_missing_pins=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="PROPOSE")
    accepted = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )
    changed = tmp_path / "later-evaluator.md"
    changed.write_text("Legitimate guidance published after retrospective acceptance.\n")
    monkeypatch.setattr(retrospective, "guidance_paths", lambda _spec: (changed,))

    decided = decide_proposal(
        control, boundary_id=BOUNDARY,
        proposal_id=accepted["proposals"][0]["proposal_id"],
        decision="defer", approver="A. Human", reason="Review later.",
        human_approved=True, apply=True,
    )

    assert decided["status"] == "Deferred"


def test_v2_acceptance_recovers_backlog_after_guidance_change(
    tmp_path: Path, monkeypatch,
):
    control, _, _ = _project(tmp_path, modern_missing_pins=True)
    backlog_before = (control / "management/BACKLOG.md").read_text()
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="PROPOSE")
    accepted = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )
    (control / "management/BACKLOG.md").write_text(backlog_before)
    changed = tmp_path / "later-evaluator.md"
    changed.write_text("Legitimate guidance published after retrospective acceptance.\n")
    monkeypatch.setattr(retrospective, "guidance_paths", lambda _spec: (changed,))

    recovered = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )

    marker = f"<!-- codexteam-improvement:{accepted['proposals'][0]['proposal_id']} -->"
    assert recovered["disposition"] == "PROPOSALS_RECORDED"
    assert marker in (control / "management/BACKLOG.md").read_text()


def test_v2_public_analysis_without_acceptance_receipt_cannot_bypass_provenance(
    tmp_path: Path, monkeypatch,
):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="NO_CHANGE")
    accepted = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )
    receipt = (
        control / ".codexteam/runtime/milestone-retrospectives"
        / BOUNDARY / "acceptance.json"
    )
    receipt.unlink()
    changed = tmp_path / "untrusted-evaluator.md"
    changed.write_text("Guidance differs from the evaluation provenance.\n")
    monkeypatch.setattr(retrospective, "guidance_paths", lambda _spec: (changed,))

    blocked = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )

    assert accepted["disposition"] == "NO_CHANGE"
    assert blocked["disposition"] == "BLOCKED_INSUFFICIENT_EVIDENCE"
    assert "evaluator identity" in blocked["blocking_reasons"][0]["message"]


def test_v2_decision_requires_acceptance_receipt(tmp_path: Path):
    control, _, _ = _project(tmp_path, modern_missing_pins=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="PROPOSE")
    accepted = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )
    receipt = (
        control / ".codexteam/runtime/milestone-retrospectives"
        / BOUNDARY / "acceptance.json"
    )
    receipt.unlink()

    with pytest.raises(RetrospectiveError, match="acceptance receipt"):
        decide_proposal(
            control, boundary_id=BOUNDARY,
            proposal_id=accepted["proposals"][0]["proposal_id"],
            decision="defer", approver="A. Human", reason="Review later.",
            human_approved=True, apply=True,
        )


def test_v2_acceptance_receipt_recovers_interrupted_publication_after_guidance_change(
    tmp_path: Path, monkeypatch,
):
    control, _, _ = _project(tmp_path, second_attempt=True)
    prepared = _prepare(control, apply=True)
    digest, path = _write_evaluation_report(control, prepared, action="NO_CHANGE")
    publish = retrospective._publish_v2_analysis
    monkeypatch.setattr(
        retrospective,
        "_publish_v2_analysis",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("interrupted")),
    )
    interrupted = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )
    monkeypatch.setattr(retrospective, "_publish_v2_analysis", publish)
    changed = tmp_path / "later-evaluator.md"
    changed.write_text("Legitimate guidance published after interrupted acceptance.\n")
    monkeypatch.setattr(retrospective, "guidance_paths", lambda _spec: (changed,))

    recovered = accept_evaluation(
        control, boundary_id=BOUNDARY,
        preparation_digest=prepared["preparation_digest"],
        evaluation_digest=digest, evaluation_path=path, apply=True,
    )

    assert interrupted["blocking_reasons"][0]["code"] == "acceptance_publication_pending"
    assert interrupted["applied"] is True
    assert recovered["disposition"] == "NO_CHANGE"


def test_v2_strict_validators_reject_extra_fields_and_authority():
    preparation = {
        "schema_version": "2.0", "boundary_id": BOUNDARY, "task_ids": [TASK],
        "evidence_digest": "a" * 64, "evidence": {}, "observations": [],
        "assessments": [], "investigations": [], "private": "no",
    }
    with pytest.raises(RetrospectiveError, match="strict v2"):
        validate_preparation(preparation)

    base = {
        "schema_version": "2.0", "boundary_id": BOUNDARY, "task_ids": [TASK],
        "evidence_digest": hashlib.sha256(b"{}").hexdigest(), "evidence": {},
        "observations": [], "assessments": [], "investigations": [],
    }
    report = {
        "schema_version": "1.0",
        "boundary_id": BOUNDARY,
        "boundary_digest": _preparation_boundary_digest(base),
        "preparation_digest": hashlib.sha256(
            json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "evidence_digest": base["evidence_digest"],
        "prepared_analysis_digest": _prepared_analysis_digest(base),
        "agent_spec_id": "agent-evaluator",
        "agent_spec_version": "1.0",
        "agent_spec_digest": load_agent_spec(
            "agent-evaluator", expected_role="reviewer"
        ).digest,
        "profile": "codex/qwen38-27b",
        "verdict": "ACCEPT",
        "checks": {
            name: {"status": "PASS", "detail": f"{name} passed."}
            for name in EVALUATION_CHECKS
        },
        "observation_assessments": [],
        "investigations": [],
        "proposals": [],
        "creates_task": True,
        "grants_implementation_authority": False,
    }
    with pytest.raises(RetrospectiveError, match="authority"):
        validate_evaluation_report(report, base)
