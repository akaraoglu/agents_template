from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import AGENT_ROLES, ResultValidationError, validate_handoff, validate_result
from .files import atomic_write_json, atomic_write_text
from .paths import (
    contained_path,
    ensure_existing_workspace,
    normalize_task_id,
    safe_relative_path,
    validate_identifier,
    validate_profile,
)
from .roles import (
    RolePolicy,
    RolePolicyError,
    load_role_policy,
    load_role_policy_snapshot,
)
from .run_guard import ExactFailedRepeatGuard
from .turn_metrics import (
    metrics_path,
    previous_summary,
    summarize_turn,
    write_summary,
)

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA_PATH = CODEXTEAM_ROOT / "schemas" / "result-v1-openai.json"
PHASES = ("draft", "feedback", "final")
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
SESSION_SCHEMA_VERSION = "1.0"
ROLE_POLICY_FILENAME = "role-policy.json"
GUIDANCE_MANIFEST_FILENAME = "guidance-manifest.json"
TURN_STATE_FILENAME = "turn-state.json"
WORKSPACE_SCAN_EXCLUDES = (".git", ".codexteam/runtime")


@dataclass(frozen=True)
class SpawnRequest:
    phase: str
    profile: str
    model: str
    model_provider: str
    model_catalog_json: str | None
    model_reasoning_effort: str | None
    reasoning_effort_override: str | None
    model_verbosity: str | None
    team_id: str
    task_id: str
    role: str
    attempt_id: str
    workspace: Path
    prompt: str
    timeout_seconds: int
    result_dir: Path
    result_path: Path
    session_dir: Path
    session_path: Path
    codex_home: Path
    source_codex_home: Path
    configured_mcp_servers: tuple[str, ...]
    effective_mcp_servers: tuple[str, ...]
    missing_mcp_servers: tuple[str, ...]
    add_dirs: tuple[Path, ...]
    trust_parent_sandbox: bool
    run_guard: bool
    skill_files: tuple[Path, ...]
    guidance_digest: str
    profile_file: Path
    role_policy: RolePolicy
    role_policy_path: Path


@dataclass(frozen=True)
class TurnContext:
    number: int
    message_path: Path
    events_path: Path
    stderr_path: Path
    state_path: Path
    session: dict[str, Any] | None

    @property
    def is_initial(self) -> bool:
        return self.session is None


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    guard_triggered: bool = False
    guard_reason: str | None = None


@dataclass(frozen=True)
class EventSummary:
    thread_ids: tuple[str, ...]
    last_agent_message: str
    completed: bool
    failures: tuple[str, ...]
    parse_errors: tuple[str, ...]


def prepare_request(args: argparse.Namespace) -> SpawnRequest:
    phase = args.phase
    if phase not in PHASES:
        raise ValueError(f"unsupported conversation phase: {phase}")
    team_id = validate_identifier(args.team, label="team ID")
    task_id = normalize_task_id(args.task)
    attempt_id = validate_identifier(args.attempt, label="attempt ID")
    if args.role not in AGENT_ROLES:
        raise ValueError(f"unsupported agent role: {args.role}")
    if args.timeout < 1:
        raise ValueError("timeout must be a positive integer")
    reasoning_effort_override = _validate_reasoning_effort(
        getattr(args, "reasoning_effort", None)
    )

    workspace = ensure_existing_workspace(args.workspace)
    safe_relative_path(args.result_dir, label="result directory")
    result_dir = contained_path(workspace, args.result_dir, label="result directory")
    result_path = contained_path(
        workspace,
        f"{args.result_dir}/{task_id}-{attempt_id}.json",
        label="result path",
    )
    session_dir = contained_path(
        workspace,
        f".codexteam/runtime/sessions/{team_id}/{task_id}/{attempt_id}",
        label="session directory",
    )
    session_path = session_dir / "session.json"
    role_policy_path = session_dir / ROLE_POLICY_FILENAME
    if phase != "draft" and role_policy_path.is_file():
        role_policy = load_role_policy_snapshot(role_policy_path, expected_role=args.role)
    else:
        role_policy = load_role_policy(args.role)
    profile_value = args.profile
    if profile_value is None and phase != "draft" and session_path.is_file():
        profile_value = _load_session(session_path).get("model_profile")
    profile = validate_profile(profile_value or role_policy.default_profile)

    prompt = _read_prompt(args.prompt_file, args.prompt)
    add_dirs = tuple(ensure_existing_workspace(path) for path in args.add_dir)
    if phase != "draft" and args.skill_file:
        raise ValueError("skill guidance cannot be overridden after the draft turn")
    guidance_manifest_path = session_dir / GUIDANCE_MANIFEST_FILENAME
    if phase != "draft" and guidance_manifest_path.is_file():
        skill_files = _load_pinned_skill_files(session_dir)
    else:
        skill_files = _skill_files(role_policy, args.skill_file)
    guidance_digest = _guidance_bundle_digest(skill_files)
    source_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve(
        strict=False
    )
    configured_mcp_servers = _configured_mcp_servers(source_codex_home / "config.toml")
    effective_mcp_servers = tuple(
        server for server in role_policy.mcp_servers if server in configured_mcp_servers
    )
    missing_mcp_servers = tuple(
        server for server in role_policy.mcp_servers if server not in configured_mcp_servers
    )
    profile_file = source_codex_home / f"{profile}.config.toml"
    if not profile_file.is_file():
        raise FileNotFoundError(f"Codex profile not found: {profile_file}")
    profile_config = tomllib.loads(profile_file.read_text(encoding="utf-8"))
    model = profile_config.get("model")
    model_provider = profile_config.get("model_provider")
    model_catalog_json = profile_config.get("model_catalog_json")
    model_reasoning_effort = profile_config.get("model_reasoning_effort")
    model_verbosity = profile_config.get("model_verbosity")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"Codex profile does not define a model: {profile_file}")
    if not isinstance(model_provider, str) or not model_provider.strip():
        raise ValueError(f"Codex profile does not define a model_provider: {profile_file}")
    if model_catalog_json is not None and not isinstance(model_catalog_json, str):
        raise ValueError(f"Codex profile model_catalog_json must be a string: {profile_file}")
    if model_reasoning_effort is not None and not isinstance(model_reasoning_effort, str):
        raise ValueError(f"Codex profile model_reasoning_effort must be a string: {profile_file}")
    if model_verbosity is not None and not isinstance(model_verbosity, str):
        raise ValueError(f"Codex profile model_verbosity must be a string: {profile_file}")
    trust_parent_sandbox = bool(getattr(args, "trust_parent_sandbox", False))
    run_guard = bool(getattr(args, "run_guard", False))
    if trust_parent_sandbox and model_provider.strip() == "openai":
        raise ValueError(
            "--trust-parent-sandbox requires a local model profile because authenticated "
            "OpenAI workers reuse the source CODEX_HOME outside the parent writable root"
        )

    return SpawnRequest(
        phase=phase,
        profile=profile,
        model=model.strip(),
        model_provider=model_provider.strip(),
        model_catalog_json=model_catalog_json,
        model_reasoning_effort=model_reasoning_effort,
        reasoning_effort_override=reasoning_effort_override,
        model_verbosity=model_verbosity,
        team_id=team_id,
        task_id=task_id,
        role=args.role,
        attempt_id=attempt_id,
        workspace=workspace,
        prompt=prompt,
        timeout_seconds=args.timeout,
        result_dir=result_dir,
        result_path=result_path,
        session_dir=session_dir,
        session_path=session_path,
        codex_home=session_dir / "codex-home",
        source_codex_home=source_codex_home,
        configured_mcp_servers=configured_mcp_servers,
        effective_mcp_servers=effective_mcp_servers,
        missing_mcp_servers=missing_mcp_servers,
        add_dirs=add_dirs,
        trust_parent_sandbox=trust_parent_sandbox,
        run_guard=run_guard,
        skill_files=skill_files,
        guidance_digest=guidance_digest,
        profile_file=profile_file,
        role_policy=role_policy,
        role_policy_path=role_policy_path,
    )


def prepare_turn(request: SpawnRequest) -> TurnContext:
    if request.phase == "draft":
        if request.session_path.exists():
            raise ValueError(
                f"session already exists for {request.task_id}/{request.attempt_id}; resume it with feedback or final"
            )
        if request.session_dir.exists() and any(request.session_dir.iterdir()):
            raise ValueError(
                f"non-resumable session data already exists for {request.task_id}/{request.attempt_id}; use a new attempt"
            )
        if request.result_path.exists():
            raise ValueError(f"result already exists for {request.task_id}/{request.attempt_id}")
        session = None
        turn_number = 1
    else:
        session = _load_session(request.session_path)
        _validate_session_scope(request, session)
        if session.get("final_result_path"):
            raise ValueError(f"session is already finalized for {request.task_id}/{request.attempt_id}")
        if request.phase == "final" and request.result_path.exists():
            raise ValueError(
                f"reserved result path already exists for {request.task_id}/{request.attempt_id}; "
                "resume with feedback so the responsible AI can move or remove the draft artifact"
            )
        turn_count = session.get("turn_count")
        if not isinstance(turn_count, int) or turn_count < 1:
            raise ValueError("session turn_count must be a positive integer")
        turn_number = turn_count + 1

    turns_dir = request.session_dir / "turns"
    stem = f"{turn_number:03d}-{request.phase}"
    return TurnContext(
        number=turn_number,
        message_path=turns_dir / f"{stem}.txt",
        events_path=turns_dir / f"{stem}.jsonl",
        stderr_path=turns_dir / f"{stem}.stderr.txt",
        state_path=request.session_dir / TURN_STATE_FILENAME,
        session=session,
    )


def run_spawn(request: SpawnRequest, *, executable: str = "codex") -> tuple[dict[str, Any], int]:
    turn = prepare_turn(request)
    _prepare_session_storage(request, initial=turn.is_initial)
    turn.message_path.parent.mkdir(parents=True, exist_ok=True)
    turn.message_path.parent.chmod(0o700)
    before_workspace = snapshot_workspace(request.workspace)
    _write_turn_state(request, turn, status="running")

    command = build_command(request, turn, executable=executable)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["CODEX_HOME"] = str(_execution_codex_home(request))
    environment["CODEX_SQLITE_HOME"] = str(request.codex_home)
    process = run_process(
        command,
        prompt=build_prompt(request, turn),
        timeout_seconds=request.timeout_seconds,
        env=environment,
        cwd=request.workspace,
        events_path=turn.events_path,
        stderr_path=turn.stderr_path,
        run_guard=request.run_guard,
    )
    atomic_write_text(turn.events_path, process.stdout)
    atomic_write_text(turn.stderr_path, process.stderr)
    changed_paths = changed_workspace_paths(
        before_workspace,
        snapshot_workspace(request.workspace),
    )
    boundary_errors = role_boundary_errors(request.role_policy, changed_paths)

    events = parse_codex_events(process.stdout)
    summary = summarize_turn(
        process.stdout,
        task_id=request.task_id,
        attempt_id=request.attempt_id,
        role=request.role,
        profile=request.profile,
        turn_number=turn.number,
        phase=request.phase,
        duration_seconds=process.duration_seconds,
        source_event_file=turn.events_path.name,
        previous_summary=previous_summary(turn.events_path.parent, turn.number),
    )
    write_summary(metrics_path(turn.events_path), summary)
    stored_thread_id = turn.session.get("thread_id") if turn.session is not None else None
    event_thread_id = _single_thread_id(events.thread_ids)
    thread_id = stored_thread_id or event_thread_id
    thread_mismatch = bool(stored_thread_id and event_thread_id and stored_thread_id != event_thread_id)

    message = ""
    if turn.message_path.is_file():
        message = turn.message_path.read_text(encoding="utf-8").strip()
    elif events.last_agent_message:
        message = events.last_agent_message.strip()
        atomic_write_text(turn.message_path, message + "\n")

    failure_status, failure_code, failure_errors = _turn_failure(
        process,
        events,
        thread_id=thread_id,
        thread_mismatch=thread_mismatch,
    )
    if failure_status is not None:
        if thread_id and not thread_mismatch:
            session = _session_record(
                request,
                turn,
                thread_id=thread_id,
                status=failure_status,
                process=process,
            )
            _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status=failure_status,
            process=process,
            changed_paths=changed_paths,
            errors=failure_errors + boundary_errors,
        )
        return _turn_outcome(
            request,
            turn,
            status=failure_status,
            thread_id=thread_id,
            errors=failure_errors + boundary_errors,
        ), failure_code

    if boundary_errors:
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="correction_needed",
            process=process,
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="correction_needed",
            process=process,
            changed_paths=changed_paths,
            errors=boundary_errors,
        )
        return _turn_outcome(
            request,
            turn,
            status="correction_needed",
            thread_id=thread_id,
            errors=boundary_errors,
        ), 1

    if not message:
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="correction_needed",
            process=process,
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="correction_needed",
            process=process,
            changed_paths=changed_paths,
            errors=["Codex returned no final agent message for this turn"],
        )
        return _turn_outcome(
            request,
            turn,
            status="correction_needed",
            thread_id=thread_id,
            errors=["Codex returned no final agent message for this turn"],
        ), 1

    if request.phase in {"draft", "feedback"}:
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="draft_ready",
            process=process,
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="draft_ready",
            process=process,
            changed_paths=changed_paths,
        )
        return _turn_outcome(
            request,
            turn,
            status="draft_ready",
            thread_id=thread_id,
        ), 0

    result, validation_errors = _result_from_message(request, process, message)
    if result is None:
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="correction_needed",
            process=process,
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="correction_needed",
            process=process,
            changed_paths=changed_paths,
            errors=validation_errors,
        )
        return _turn_outcome(
            request,
            turn,
            status="correction_needed",
            thread_id=thread_id,
            errors=validation_errors,
        ), 1

    request.result_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(request.result_path, result)
    session = _session_record(
        request,
        turn,
        thread_id=thread_id,
        status="finalized",
        process=process,
        final_result_path=request.result_path.relative_to(request.workspace).as_posix(),
    )
    _write_session(request.session_path, session)
    _write_turn_state(
        request,
        turn,
        status="finalized",
        process=process,
        changed_paths=changed_paths,
    )
    return result, 0 if result["status"] in {"completed", "needs_review"} else 1


def build_command(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    executable: str = "codex",
) -> list[str]:
    prefix = [executable]
    if request.trust_parent_sandbox:
        prefix.extend(("-s", "danger-full-access"))
    if turn.is_initial:
        command = prefix + [
            "exec",
            "--profile",
            request.profile,
            "-c",
            "developer_instructions="
            f"{json.dumps(request.role_policy.developer_instructions)}",
            *_mcp_override_args(request),
            "-C",
            str(request.workspace),
            "--skip-git-repo-check",
            "--json",
            "-o",
            str(turn.message_path),
        ]
        if not request.trust_parent_sandbox:
            command.extend(("-s", request.role_policy.sandbox_mode))
        reasoning_effort = _session_reasoning_effort(request, None)
        if reasoning_effort is not None:
            command.extend(
                (
                    "-c",
                    "model_reasoning_effort="
                    f"{json.dumps(reasoning_effort)}",
                )
            )
        for directory in request.add_dirs:
            command.extend(("--add-dir", str(directory)))
        command.append("-")
        return command

    thread_id = turn.session["thread_id"]
    reasoning_effort = _session_reasoning_effort(request, turn.session)
    return prefix + [
        "exec",
        "resume",
        "-m",
        request.model,
        "-c",
        f"model_provider={json.dumps(request.model_provider)}",
        "-c",
        "developer_instructions="
        f"{json.dumps(request.role_policy.developer_instructions)}",
        *_mcp_override_args(request),
        *(
            ["-c", f"model_catalog_json={json.dumps(request.model_catalog_json)}"]
            if request.model_catalog_json
            else []
        ),
        *(
            ["-c", f"model_reasoning_effort={json.dumps(reasoning_effort)}"]
            if reasoning_effort
            else []
        ),
        *(
            ["-c", f"model_verbosity={json.dumps(request.model_verbosity)}"]
            if request.model_verbosity
            else []
        ),
        "--skip-git-repo-check",
        "--json",
        *(
            ["--output-schema", str(RESULT_SCHEMA_PATH)]
            if request.phase == "final" and request.model_provider == "openai"
            else []
        ),
        "-o",
        str(turn.message_path),
        thread_id,
        "-",
    ]


def _configured_mcp_servers(config_path: Path) -> tuple[str, ...]:
    if not config_path.is_file():
        return ()
    try:
        value = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid Codex base configuration: {config_path}: {exc}") from exc
    servers = value.get("mcp_servers")
    if servers is None:
        return ()
    if not isinstance(servers, dict) or any(
        not isinstance(name, str) or not isinstance(config, dict)
        for name, config in servers.items()
    ):
        raise ValueError(f"Codex base mcp_servers must be a table: {config_path}")
    return tuple(sorted(servers))


def _mcp_override_args(request: SpawnRequest) -> list[str]:
    allowed = set(request.effective_mcp_servers)
    arguments: list[str] = []
    for server in request.configured_mcp_servers:
        enabled = "true" if server in allowed else "false"
        arguments.extend(
            (
                "-c",
                f"mcp_servers.{server}.enabled={enabled}",
            )
        )
    return arguments


def build_prompt(request: SpawnRequest, turn: TurnContext) -> str:
    if request.phase == "feedback":
        return (
            "[CODEXTEAM FEEDBACK TURN]\n"
            f"Continue the existing {request.task_id}/{request.attempt_id} assignment as the same responsible AI.\n"
            "Apply the Project Lead's feedback while preserving accepted work. Run relevant verification.\n"
            "Return a revised conversational draft with Outcome, Evidence, Uncertainties or conflicts, "
            "and Proposed disposition. State how the feedback was addressed.\n"
            "Do not emit result-v1 and do not close canonical project state.\n\n"
            f"[PROJECT LEAD FEEDBACK]\n{request.prompt.strip()}\n"
        )
    if request.phase == "final":
        return (
            "[CODEXTEAM FINALIZATION TURN]\n"
            f"The Project Lead accepted the draft for {request.task_id}/{request.attempt_id}.\n"
            "Return one JSON object matching the result-v1 contract, with no prose.\n"
            "Use the complete attempt and real evidence without inventing evidence or expanding scope.\n"
            "Set these identity fields exactly:\n"
            "schema_version: 1.0\n"
            f"team_id: {request.team_id}\n"
            f"task_id: {request.task_id}\n"
            f"agent_role: {request.role}\n"
            f"attempt_id: {request.attempt_id}\n"
            "Include every required top-level key: schema_version, result_id, team_id, task_id, "
            "agent_role, attempt_id, status, summary, output, file_changes, evidence, "
            "requested_followups, errors, warnings, limitations, and produced_at.\n"
            "Every created or modified file and every evidence artifact_ref must be an actual existing "
            "project-relative path. Summarize relevant commands in evidence summary, never artifact_ref. Use empty arrays "
            "when there are no entries.\n\n"
            f"[PROJECT LEAD DECISION]\n{request.prompt.strip()}\n"
        )

    skills = []
    for path in request.skill_files:
        skills.append(f"\n[GUIDANCE: {path.name}]\n{path.read_text(encoding='utf-8').strip()}\n")
    handoff = build_handoff(request)
    return (
        "[CODEXTEAM HANDOFF V1]\n"
        f"{json.dumps(handoff, indent=2)}\n"
        f"Role policy: {request.role_policy.name} v{request.role_policy.schema_version} "
        f"({request.role_policy.digest[:12]}).\n"
        "You are the responsible AI for this task and logical attempt. Work only inside the assigned workspace "
        "and additional explicitly writable directories.\n"
        "Read relevant files before editing. Run task-relevant verification. Do not invent evidence.\n"
        f"Return a conversational draft headed 'DRAFT {request.task_id}/{request.attempt_id}' with sections "
        "Outcome, Evidence, Uncertainties or conflicts, and Proposed disposition.\n"
        "Do not emit result-v1 and do not close canonical project state; the Project Lead will review this draft.\n"
        + "".join(skills)
        + f"\n[TASK DETAILS]\n{request.prompt.strip()}\n"
    )


def build_handoff(request: SpawnRequest) -> dict[str, Any]:
    handoff = {
        "schema_version": "1.0",
        "handoff_id": f"handoff-{request.task_id.lower()}-{request.attempt_id}",
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "model_profile": request.profile,
        "role_policy": {
            "name": request.role_policy.name,
            "schema_version": request.role_policy.schema_version,
            "digest": request.role_policy.digest,
        },
        "workspace_root": str(request.workspace),
        "task_context": {
            "prompt": request.prompt,
            "guidance_files": [path.name for path in request.skill_files],
        },
        "instruction_bundle": {
            "digest": request.guidance_digest,
            "files": [path.name for path in request.skill_files],
        },
        "constraints": {
            "workspace_write": str(request.workspace),
            "additional_writable_directories": [str(path) for path in request.add_dirs],
            "trust_parent_sandbox": request.trust_parent_sandbox,
            "timeout_seconds": request.timeout_seconds,
        },
        "completion_criteria": [
            "Run task-relevant verification.",
            "Return a draft for Project Lead review.",
            "Do not emit a final result or close project state in the draft turn.",
        ],
    }
    validate_handoff(handoff)
    return handoff


def snapshot_workspace(workspace: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for current_root, directory_names, file_names in os.walk(workspace, topdown=True):
        root = Path(current_root)
        relative_root = root.relative_to(workspace).as_posix()
        directory_names[:] = [
            name
            for name in directory_names
            if not _workspace_scan_excluded(
                name if relative_root == "." else f"{relative_root}/{name}"
            )
        ]
        for name in file_names:
            path = root / name
            relative = path.relative_to(workspace).as_posix()
            if _workspace_scan_excluded(relative):
                continue
            if path.is_symlink():
                snapshot[relative] = "symlink:" + os.readlink(path)
                continue
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except FileNotFoundError:
                continue
            snapshot[relative] = digest.hexdigest()
    return snapshot


def changed_workspace_paths(
    before: dict[str, str],
    after: dict[str, str],
) -> tuple[str, ...]:
    return tuple(
        path
        for path in sorted(set(before) | set(after))
        if before.get(path) != after.get(path)
    )


def role_boundary_errors(
    policy: RolePolicy,
    changed_paths: tuple[str, ...],
) -> list[str]:
    return [
        f"role policy {policy.name} does not allow changing {path}"
        for path in changed_paths
        if not policy.allows_change(path)
    ]


def _workspace_scan_excluded(relative: str) -> bool:
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in WORKSPACE_SCAN_EXCLUDES
    )


def run_process(
    command: list[str],
    *,
    prompt: str,
    timeout_seconds: int,
    env: dict[str, str],
    cwd: Path | None = None,
    events_path: Path | None = None,
    stderr_path: Path | None = None,
    run_guard: bool = False,
) -> ProcessResult:
    if run_guard:
        return _run_guarded_process(
            command,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            env=env,
            cwd=cwd,
            events_path=events_path,
            stderr_path=stderr_path,
        )

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
        cwd=cwd,
    )
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout_seconds)
        return ProcessResult(process.returncode, stdout, stderr, time.monotonic() - started)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        return ProcessResult(124, stdout, stderr, time.monotonic() - started, timed_out=True)


def _run_guarded_process(
    command: list[str],
    *,
    prompt: str,
    timeout_seconds: int,
    env: dict[str, str],
    cwd: Path | None,
    events_path: Path | None,
    stderr_path: Path | None,
) -> ProcessResult:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
        env=env,
        cwd=cwd,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    chunks: queue.Queue[tuple[str, str | None]] = queue.Queue()
    readers = (
        threading.Thread(
            target=_read_process_stream,
            args=("stdout", process.stdout, chunks),
            daemon=True,
        ),
        threading.Thread(
            target=_read_process_stream,
            args=("stderr", process.stderr, chunks),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()
    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except BrokenPipeError:
        process.stdin.close()

    guard = ExactFailedRepeatGuard()
    guard_reason: str | None = None
    guard_deadline: float | None = None
    force_killed = False
    timed_out = False
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    completed_streams: set[str] = set()
    event_handle = _open_live_stream(events_path)
    error_handle = _open_live_stream(stderr_path)
    try:
        while len(completed_streams) < 2:
            now = time.monotonic()
            if guard_reason is None and not timed_out and now - started >= timeout_seconds:
                timed_out = True
                _signal_process_group(process, signal.SIGKILL)
                force_killed = True
            elif (
                guard_deadline is not None
                and not force_killed
                and now >= guard_deadline
                and process.poll() is None
            ):
                _signal_process_group(process, signal.SIGKILL)
                force_killed = True

            try:
                stream_name, chunk = chunks.get(timeout=0.05)
            except queue.Empty:
                continue
            if chunk is None:
                completed_streams.add(stream_name)
                continue
            if stream_name == "stdout":
                stdout_chunks.append(chunk)
                _write_live_chunk(event_handle, chunk)
                if guard_reason is None and not timed_out:
                    decision = guard.observe_line(chunk)
                    if decision is not None:
                        guard_reason = decision.reason
                        _signal_process_group(process, signal.SIGINT)
                        guard_deadline = time.monotonic() + 2.0
            else:
                stderr_chunks.append(chunk)
                _write_live_chunk(error_handle, chunk)
    finally:
        if event_handle is not None:
            event_handle.close()
        if error_handle is not None:
            error_handle.close()
        if process.poll() is None:
            _signal_process_group(process, signal.SIGKILL)
        process.wait()
        for reader in readers:
            reader.join(timeout=1.0)

    exit_code = 124 if timed_out else process.returncode
    return ProcessResult(
        exit_code,
        "".join(stdout_chunks),
        "".join(stderr_chunks),
        time.monotonic() - started,
        timed_out=timed_out,
        guard_triggered=guard_reason is not None,
        guard_reason=guard_reason,
    )


def _read_process_stream(
    stream_name: str,
    stream: Any,
    chunks: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        for line in iter(stream.readline, ""):
            chunks.put((stream_name, line))
    finally:
        stream.close()
        chunks.put((stream_name, None))


def _open_live_stream(path: Path | None) -> Any:
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8", newline="")
    path.chmod(0o600)
    return handle


def _write_live_chunk(handle: Any, chunk: str) -> None:
    if handle is None:
        return
    handle.write(chunk)
    handle.flush()


def _signal_process_group(process: subprocess.Popen[str], target_signal: int) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, target_signal)
    except ProcessLookupError:
        return


def parse_codex_events(text: str) -> EventSummary:
    thread_ids: list[str] = []
    messages: list[str] = []
    failures: list[str] = []
    parse_errors: list[str] = []
    completed = False
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
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id.strip():
                thread_ids.append(thread_id.strip())
            else:
                parse_errors.append(f"line {line_number}: thread.started is missing thread_id")
        elif event_type == "turn.completed":
            completed = True
        elif event_type in {"turn.failed", "error"}:
            failures.append(_event_failure_text(event))
        elif event_type == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                message = item.get("text")
                if isinstance(message, str) and message.strip():
                    messages.append(message)
    return EventSummary(
        thread_ids=tuple(dict.fromkeys(thread_ids)),
        last_agent_message=messages[-1] if messages else "",
        completed=completed,
        failures=tuple(failures),
        parse_errors=tuple(parse_errors),
    )


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    position = 0
    while True:
        start = text.find("{", position)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            position = start + 1
            continue
        if isinstance(value, dict):
            objects.append(value)
        position = start + max(end, 1)
    return objects


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one turn of a persistent CodexTeam worker conversation."
    )
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--profile", help="Override the selected role policy's default profile")
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        help="Override the profile reasoning effort for this persistent task attempt",
    )
    parser.add_argument("--team", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--role", required=True, choices=tuple(sorted(AGENT_ROLES)))
    parser.add_argument("--workspace", required=True)
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt-file")
    prompt_group.add_argument("--prompt")
    parser.add_argument("--skill-file", action="append", default=[], help="Override default role guidance; repeatable")
    parser.add_argument("--add-dir", action="append", default=[], help="Additional writable directory; repeatable")
    parser.add_argument(
        "--trust-parent-sandbox",
        action="store_true",
        help=(
            "Skip the redundant worker sandbox only when the launcher already runs inside "
            "a Codex workspace sandbox; local model profiles only"
        ),
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--run-guard",
        action="store_true",
        help="Interrupt three consecutive identical failed commands and preserve the resumable thread",
    )
    parser.add_argument("--result-dir", default="results")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        request = prepare_request(args)
        turn = prepare_turn(request)
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "phase": request.phase,
                        "command": build_command(request, turn),
                        "profile_file": str(request.profile_file),
                        "role_policy": request.role_policy.name,
                        "role_policy_version": request.role_policy.schema_version,
                        "role_policy_digest": request.role_policy.digest,
                        "role_policy_source": str(request.role_policy.source_path),
                        "default_profile": request.role_policy.default_profile,
                        "sandbox_mode": request.role_policy.sandbox_mode,
                        "mcp_allowed_servers": list(request.role_policy.mcp_servers),
                        "mcp_effective_servers": list(request.effective_mcp_servers),
                        "mcp_missing_servers": list(request.missing_mcp_servers),
                        "reasoning_effort": _session_reasoning_effort(request, turn.session),
                        "reasoning_effort_override": request.reasoning_effort_override,
                        "workspace": str(request.workspace),
                        "trust_parent_sandbox": request.trust_parent_sandbox,
                        "run_guard": request.run_guard,
                        "session_path": str(request.session_path),
                        "turn_path": str(turn.message_path),
                        "stderr_path": str(turn.stderr_path),
                        "result_path": str(request.result_path),
                        "skills": [str(path) for path in request.skill_files],
                    },
                    indent=2,
                )
            )
            return 0
        outcome, code = run_spawn(request)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        RolePolicyError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}")
        return 2

    print(f"Session: {request.session_path}")
    if request.phase == "final" and outcome.get("schema_version") == "1.0":
        print(f"Result: {request.result_path}")
        print(f"Status: {outcome['status']}")
    else:
        print(f"Turn: {outcome.get('turn_path', turn.message_path)}")
        print(f"Status: {outcome.get('status', 'unknown')}")
        errors = outcome.get("errors", [])
        for error in errors:
            print(f"ERROR: {error}")
        if errors:
            print(f"Diagnostics: {outcome.get('stderr_path', turn.stderr_path)}")
    return code


def _read_prompt(prompt_file: str | None, prompt: str | None) -> str:
    if prompt_file is not None:
        content = Path(prompt_file).expanduser().read_text(encoding="utf-8")
    else:
        content = prompt or ""
    if not content.strip():
        raise ValueError("prompt cannot be empty")
    return content


def _skill_files(policy: RolePolicy, overrides: list[str]) -> tuple[Path, ...]:
    if overrides:
        paths = tuple(Path(value).expanduser().resolve(strict=True) for value in overrides)
    else:
        names = policy.skill_files
        paths = tuple(
            (
                CODEXTEAM_ROOT
                / ".agents"
                / ("capabilities" if name == "coding-standards.md" else "skills")
                / name
            ).resolve(strict=True)
            for name in names
        )
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"skill file not found: {path}")
    return paths


def _guidance_bundle_digest(paths: tuple[Path, ...]) -> str:
    entries = []
    for index, path in enumerate(paths, start=1):
        content = path.read_bytes()
        entries.append(
            {
                "index": index,
                "name": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _snapshot_skill_files(request: SpawnRequest) -> None:
    guidance_root = request.session_dir / "guidance"
    entries = []
    for index, source in enumerate(request.skill_files, start=1):
        relative = f"guidance/{index:03d}/{source.name}"
        target = contained_path(request.session_dir, relative, label="guidance snapshot")
        content = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"guidance snapshot already exists: {target}")
        target.write_bytes(content)
        target.chmod(0o600)
        entries.append(
            {
                "name": source.name,
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "digest": request.guidance_digest,
        "files": entries,
    }
    atomic_write_json(request.session_dir / GUIDANCE_MANIFEST_FILENAME, manifest)
    (request.session_dir / GUIDANCE_MANIFEST_FILENAME).chmod(0o600)


def _load_pinned_skill_files(session_dir: Path) -> tuple[Path, ...]:
    manifest_path = session_dir / GUIDANCE_MANIFEST_FILENAME
    if manifest_path.is_symlink():
        raise ValueError(f"guidance manifest must not be a symlink: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid guidance manifest: {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise ValueError("guidance manifest schema_version must be '1.0'")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("guidance manifest files must be a non-empty list")
    paths: list[Path] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"guidance manifest files[{index}] must be an object")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise ValueError(f"guidance manifest files[{index}] is incomplete")
        path = contained_path(session_dir, relative, label="guidance snapshot")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"guidance snapshot is missing or unsafe: {path}")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"guidance snapshot digest mismatch: {path}")
        paths.append(path)
    pinned = tuple(paths)
    actual_digest = _guidance_bundle_digest(pinned)
    if actual_digest != manifest.get("digest"):
        raise ValueError("guidance bundle digest mismatch")
    return pinned


def _prepare_session_storage(request: SpawnRequest, *, initial: bool) -> None:
    if initial:
        request.session_dir.mkdir(parents=True, exist_ok=False)
        request.session_dir.chmod(0o700)
        request.codex_home.mkdir()
        request.codex_home.chmod(0o700)
        atomic_write_json(request.role_policy_path, request.role_policy.snapshot())
        request.role_policy_path.chmod(0o600)
        _snapshot_skill_files(request)
        source = request.profile_file.parent
        base_config = source / "config.toml"
        if base_config.is_file():
            shutil.copy2(base_config, request.codex_home / base_config.name)
        for profile in source.glob("*.config.toml"):
            shutil.copy2(profile, request.codex_home / profile.name)
        catalogs = source / "model_catalogs"
        if catalogs.is_dir():
            shutil.copytree(catalogs, request.codex_home / "model_catalogs")
        return
    if not request.codex_home.is_dir():
        raise FileNotFoundError(f"persistent Codex home is missing: {request.codex_home}")
    if not request.role_policy_path.is_file():
        atomic_write_json(request.role_policy_path, request.role_policy.snapshot())
        request.role_policy_path.chmod(0o600)
    if not (request.session_dir / GUIDANCE_MANIFEST_FILENAME).is_file():
        _snapshot_skill_files(request)


def _execution_codex_home(request: SpawnRequest) -> Path:
    """Use the authenticated source home for OpenAI without copying credentials.

    Thread state remains isolated through CODEX_SQLITE_HOME and the exact thread ID
    recorded in the project-local session metadata. Local providers continue using
    the fully private Codex home seeded for the logical attempt.
    """
    if request.model_provider == "openai" and (request.source_codex_home / "auth.json").is_file():
        return request.source_codex_home
    return request.codex_home


def _load_session(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"persistent session is missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("session record must be a JSON object")
    if data.get("schema_version") != SESSION_SCHEMA_VERSION:
        raise ValueError(f"session schema_version must be {SESSION_SCHEMA_VERSION!r}")
    thread_id = data.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("session thread_id must be a non-empty string")
    return data


def _validate_session_scope(request: SpawnRequest, session: dict[str, Any]) -> None:
    expected = {
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "model_profile": request.profile,
        "workspace_root": str(request.workspace),
    }
    mismatches = [
        f"{field}: expected {value!r}, found {session.get(field)!r}"
        for field, value in expected.items()
        if session.get(field) != value
    ]
    if mismatches:
        raise ValueError("session scope mismatch: " + "; ".join(mismatches))
    stored_parent_trust = session.get("trust_parent_sandbox", False)
    if stored_parent_trust is not request.trust_parent_sandbox:
        raise ValueError(
            "session scope mismatch: trust_parent_sandbox: "
            f"expected {request.trust_parent_sandbox!r}, found {stored_parent_trust!r}"
        )
    optional_expected = {
        "model": request.model,
        "model_provider": request.model_provider,
        "model_catalog_json": request.model_catalog_json,
        "model_verbosity": request.model_verbosity,
    }
    optional_mismatches = [
        f"{field}: expected {value!r}, found {session.get(field)!r}"
        for field, value in optional_expected.items()
        if field in session and session.get(field) != value
    ]
    if optional_mismatches:
        raise ValueError("session model mismatch: " + "; ".join(optional_mismatches))
    policy_expected = {
        "role_policy_name": request.role_policy.name,
        "role_policy_version": request.role_policy.schema_version,
        "role_policy_digest": request.role_policy.digest,
    }
    policy_mismatches = [
        f"{field}: expected {value!r}, found {session.get(field)!r}"
        for field, value in policy_expected.items()
        if field in session and session.get(field) != value
    ]
    if policy_mismatches:
        raise ValueError("session role policy mismatch: " + "; ".join(policy_mismatches))
    if (
        "instruction_bundle_digest" in session
        and session.get("instruction_bundle_digest") != request.guidance_digest
    ):
        raise ValueError(
            "session instruction bundle mismatch: expected "
            f"{request.guidance_digest!r}, found {session.get('instruction_bundle_digest')!r}"
        )
    if (
        request.reasoning_effort_override is not None
        and session.get("model_reasoning_effort") != request.reasoning_effort_override
    ):
        raise ValueError(
            "session model mismatch: model_reasoning_effort: "
            f"expected {request.reasoning_effort_override!r}, "
            f"found {session.get('model_reasoning_effort')!r}"
        )


def _session_record(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    thread_id: str | None,
    status: str,
    process: ProcessResult,
    final_result_path: str | None = None,
) -> dict[str, Any]:
    if not thread_id:
        raise ValueError("cannot persist a resumable session without a thread ID")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    created_at = turn.session.get("created_at", now) if turn.session else now
    reasoning_effort = _session_reasoning_effort(request, turn.session)
    reasoning_effort_override = (
        turn.session.get("reasoning_effort_override")
        if turn.session is not None
        else request.reasoning_effort_override
    )
    turns = list(turn.session.get("turns", [])) if turn.session else []
    turns.append({
        "number": turn.number,
        "phase": request.phase,
        "status": status,
        "duration_seconds": round(process.duration_seconds, 3),
    })
    record = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "model_profile": request.profile,
        "role_policy_name": request.role_policy.name,
        "role_policy_version": request.role_policy.schema_version,
        "role_policy_digest": request.role_policy.digest,
        "instruction_bundle_digest": request.guidance_digest,
        "model": request.model,
        "model_provider": request.model_provider,
        "model_catalog_json": request.model_catalog_json,
        "model_reasoning_effort": reasoning_effort,
        "reasoning_effort_override": reasoning_effort_override,
        "model_verbosity": request.model_verbosity,
        "mcp_allowed_servers": list(request.role_policy.mcp_servers),
        "mcp_effective_servers": list(request.effective_mcp_servers),
        "mcp_missing_servers": list(request.missing_mcp_servers),
        "workspace_root": str(request.workspace),
        "trust_parent_sandbox": request.trust_parent_sandbox,
        "thread_id": thread_id,
        "turn_count": turn.number,
        "last_phase": request.phase,
        "last_status": status,
        "last_turn_path": turn.message_path.relative_to(request.workspace).as_posix(),
        "created_at": created_at,
        "updated_at": now,
        "turns": turns,
    }
    if final_result_path is not None:
        record["final_result_path"] = final_result_path
    return record


def _validate_reasoning_effort(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("reasoning effort override must be a string")
    normalized = value.strip().lower()
    if normalized not in REASONING_EFFORTS:
        raise ValueError(
            "reasoning effort override must be one of "
            + ", ".join(REASONING_EFFORTS)
        )
    return normalized


def _session_reasoning_effort(
    request: SpawnRequest,
    session: dict[str, Any] | None,
) -> str | None:
    if session is not None and "model_reasoning_effort" in session:
        value = session.get("model_reasoning_effort")
        return value if isinstance(value, str) and value else None
    return (
        request.reasoning_effort_override
        or request.role_policy.default_reasoning_effort
        or request.model_reasoning_effort
    )


def _write_session(path: Path, session: dict[str, Any]) -> None:
    atomic_write_json(path, session)
    path.chmod(0o600)


def _write_turn_state(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    status: str,
    process: ProcessResult | None = None,
    changed_paths: tuple[str, ...] = (),
    errors: list[str] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    existing: dict[str, Any] = {}
    if turn.state_path.is_file():
        try:
            loaded = json.loads(turn.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            existing = loaded
    same_turn = (
        existing.get("turn_number") == turn.number
        and existing.get("phase") == request.phase
    )
    state = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "model_profile": request.profile,
        "role_policy_name": request.role_policy.name,
        "role_policy_version": request.role_policy.schema_version,
        "role_policy_digest": request.role_policy.digest,
        "instruction_bundle_digest": request.guidance_digest,
        "phase": request.phase,
        "turn_number": turn.number,
        "status": status,
        "started_at": existing.get("started_at", now) if same_turn else now,
        "updated_at": now,
        "timeout_seconds": request.timeout_seconds,
        "run_guard_enabled": request.run_guard,
        "mcp_allowed_servers": list(request.role_policy.mcp_servers),
        "mcp_effective_servers": list(request.effective_mcp_servers),
        "mcp_missing_servers": list(request.missing_mcp_servers),
        "changed_paths": list(changed_paths),
        "errors": errors or [],
    }
    if process is not None:
        state["duration_seconds"] = round(process.duration_seconds, 3)
        state["exit_code"] = process.exit_code
        state["timed_out"] = process.timed_out
        state["run_guard_triggered"] = process.guard_triggered
        if process.guard_reason is not None:
            state["run_guard_reason"] = process.guard_reason
    atomic_write_json(turn.state_path, state)
    turn.state_path.chmod(0o600)


def _single_thread_id(thread_ids: tuple[str, ...]) -> str | None:
    if not thread_ids:
        return None
    if len(thread_ids) > 1:
        return None
    return thread_ids[0]


def _turn_failure(
    process: ProcessResult,
    events: EventSummary,
    *,
    thread_id: str | None,
    thread_mismatch: bool,
) -> tuple[str | None, int, list[str]]:
    if thread_mismatch:
        return "session_mismatch", 1, ["resumed turn reported a different thread ID"]
    if len(events.thread_ids) > 1:
        return "session_mismatch", 1, ["turn reported multiple thread IDs"]
    if process.guard_triggered:
        return "interrupted", 3, [process.guard_reason or "run guard interrupted the turn"]
    if process.timed_out:
        return "interrupted", 3, [f"subagent timed out after {round(process.duration_seconds, 3)} seconds"]
    if process.exit_code != 0:
        return "turn_failed", 1, [f"subagent exited with code {process.exit_code}"]
    if events.parse_errors:
        return "turn_failed", 1, list(events.parse_errors)
    if not thread_id:
        return "turn_failed", 1, ["initial turn did not report a persistent thread ID"]
    if not events.completed:
        if events.failures:
            return "turn_failed", 1, list(events.failures)
        return "turn_failed", 1, ["Codex event stream did not contain turn.completed"]
    return None, 0, []


def _turn_outcome(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    status: str,
    thread_id: str | None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "phase": request.phase,
        "status": status,
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "role_policy_name": request.role_policy.name,
        "role_policy_version": request.role_policy.schema_version,
        "role_policy_digest": request.role_policy.digest,
        "instruction_bundle_digest": request.guidance_digest,
        "thread_id": thread_id,
        "turn_count": turn.number,
        "session_path": str(request.session_path),
        "turn_path": str(turn.message_path),
        "events_path": str(turn.events_path),
        "metrics_path": str(metrics_path(turn.events_path)),
        "stderr_path": str(turn.stderr_path),
        "result_path": str(request.result_path) if request.result_path.exists() else None,
        "errors": errors or [],
    }


def _result_from_message(
    request: SpawnRequest,
    process: ProcessResult,
    message: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    candidates = extract_json_objects(message)
    validation_errors: list[str] = []
    for candidate in reversed(candidates):
        candidate = dict(candidate)
        if not isinstance(candidate.get("result_id"), str) or not candidate["result_id"].strip():
            candidate["result_id"] = f"res-{request.task_id.lower()}-{request.attempt_id}"
        if candidate.get("status") == "completed":
            candidate.setdefault("requested_followups", [])
        for field in ("errors", "warnings", "limitations"):
            value = candidate.get(field)
            if isinstance(value, list):
                candidate[field] = [
                    item["message"]
                    if isinstance(item, dict) and isinstance(item.get("message"), str)
                    else item
                    for item in value
                ]
        candidate["output"] = {
            "exit_code": process.exit_code,
            "stdout_tail": process.stdout[-2_000:],
            "stderr_tail": process.stderr[-2_000:],
            "duration_seconds": round(process.duration_seconds, 3),
        }
        try:
            validate_result(
                candidate,
                expected_task=request.task_id,
                expected_team=request.team_id,
                expected_attempt=request.attempt_id,
                expected_role=request.role,
            )
        except ResultValidationError as exc:
            validation_errors.extend(exc.errors)
            continue
        artifact_errors = _result_artifact_errors(request, candidate)
        if artifact_errors:
            validation_errors.extend(artifact_errors)
            continue
        policy_errors = _result_policy_errors(request, candidate)
        if policy_errors:
            validation_errors.extend(policy_errors)
            continue
        return candidate, []
    errors = ["final result-v1 validation failed"]
    errors.extend(list(dict.fromkeys(validation_errors))[:10])
    return None, errors


def _result_artifact_errors(request: SpawnRequest, result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, change in enumerate(result["file_changes"]):
        path = contained_path(
            request.workspace,
            change["path"],
            label=f"file_changes[{index}].path",
        )
        action = change["action"]
        if action in {"created", "modified"} and not path.exists():
            errors.append(
                f"file_changes[{index}].path does not exist for {action}: {change['path']}"
            )
        elif action == "deleted" and path.exists():
            errors.append(
                f"file_changes[{index}].path still exists for deleted: {change['path']}"
            )

    for index, evidence in enumerate(result["evidence"]):
        path = contained_path(
            request.workspace,
            evidence["artifact_ref"],
            label=f"evidence[{index}].artifact_ref",
        )
        if not path.exists():
            errors.append(
                "evidence["
                f"{index}].artifact_ref does not exist: {evidence['artifact_ref']}"
            )
    return errors


def _result_policy_errors(request: SpawnRequest, result: dict[str, Any]) -> list[str]:
    errors = [
        f"role policy {request.role_policy.name} does not allow declared change: {item['path']}"
        for item in result["file_changes"]
        if not request.role_policy.allows_change(item["path"])
    ]
    errors.extend(
        f"role policy {request.role_policy.name} does not allow evidence type: {item['type']}"
        for item in result["evidence"]
        if item["type"] not in request.role_policy.allowed_evidence_types
    )
    return errors


def _event_failure_text(event: dict[str, Any]) -> str:
    for field in ("message", "error"):
        value = event.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            message = value.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    return f"Codex reported {event.get('type', 'an error')}"


if __name__ == "__main__":
    raise SystemExit(main())
