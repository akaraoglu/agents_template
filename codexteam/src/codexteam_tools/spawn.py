from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
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

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
PHASES = ("draft", "feedback", "final")
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
SESSION_SCHEMA_VERSION = "1.0"
DEFAULT_SKILLS = {
    "developer": ("implementation.md", "testing.md"),
    "tester": ("testing.md", "verification.md"),
    "reviewer": ("verification.md", "coding-standards.md"),
    "documenter": ("document-editing.md",),
    "leader": ("project-lead.md", "subagent-orchestration.md", "task-breakdown.md"),
}


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
    add_dirs: tuple[Path, ...]
    trust_parent_sandbox: bool
    skill_files: tuple[Path, ...]
    profile_file: Path


@dataclass(frozen=True)
class TurnContext:
    number: int
    message_path: Path
    events_path: Path
    stderr_path: Path
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
    profile = validate_profile(args.profile)
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

    prompt = _read_prompt(args.prompt_file, args.prompt)
    add_dirs = tuple(ensure_existing_workspace(path) for path in args.add_dir)
    skill_files = _skill_files(args.role, args.skill_file)
    source_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve(
        strict=False
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
        session_path=session_dir / "session.json",
        codex_home=session_dir / "codex-home",
        source_codex_home=source_codex_home,
        add_dirs=add_dirs,
        trust_parent_sandbox=trust_parent_sandbox,
        skill_files=skill_files,
        profile_file=profile_file,
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
        session=session,
    )


def run_spawn(request: SpawnRequest, *, executable: str = "codex") -> tuple[dict[str, Any], int]:
    turn = prepare_turn(request)
    _prepare_session_storage(request, initial=turn.is_initial)
    turn.message_path.parent.mkdir(parents=True, exist_ok=True)
    turn.message_path.parent.chmod(0o700)

    command = build_command(request, turn, executable=executable)
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(_execution_codex_home(request))
    environment["CODEX_SQLITE_HOME"] = str(request.codex_home)
    process = run_process(
        command,
        prompt=build_prompt(request, turn),
        timeout_seconds=request.timeout_seconds,
        env=environment,
        cwd=request.workspace,
    )
    atomic_write_text(turn.events_path, process.stdout)
    atomic_write_text(turn.stderr_path, process.stderr)

    events = parse_codex_events(process.stdout)
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
            )
            _write_session(request.session_path, session)
        return _turn_outcome(
            request,
            turn,
            status=failure_status,
            thread_id=thread_id,
            errors=failure_errors,
        ), failure_code

    if not message:
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="correction_needed",
        )
        _write_session(request.session_path, session)
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
        )
        _write_session(request.session_path, session)
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
        )
        _write_session(request.session_path, session)
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
        final_result_path=request.result_path.relative_to(request.workspace).as_posix(),
    )
    _write_session(request.session_path, session)
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
            "-C",
            str(request.workspace),
            "--skip-git-repo-check",
            "--json",
            "-o",
            str(turn.message_path),
        ]
        if not request.trust_parent_sandbox:
            command.extend(("-s", "workspace-write"))
        if request.reasoning_effort_override is not None:
            command.extend(
                (
                    "-c",
                    "model_reasoning_effort="
                    f"{json.dumps(request.reasoning_effort_override)}",
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
        "-o",
        str(turn.message_path),
        thread_id,
        "-",
    ]


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
            f"The Project Lead has reviewed the draft for {request.task_id}/{request.attempt_id}.\n"
            "Use the complete work and real evidence from this entire attempt. Do not invent evidence or expand scope.\n"
            "Every created or modified file path and every evidence artifact_ref must name an actual existing "
            "project-relative artifact. Put commands in evidence metadata, never in artifact_ref.\n"
            "The JSON below is a shape example, not result content. Replace every angle-bracket placeholder "
            "with observed task data. Remove the example file-change object when no file changed; never copy "
            "a placeholder into the result.\n"
            "Return exactly one final result-v1 JSON object with no Markdown fence or additional prose.\n"
            f"{json.dumps(_schema_example(request), indent=2)}\n\n"
            f"[PROJECT LEAD DECISION]\n{request.prompt.strip()}\n"
        )

    skills = []
    for path in request.skill_files:
        skills.append(f"\n[GUIDANCE: {path.name}]\n{path.read_text(encoding='utf-8').strip()}\n")
    handoff = build_handoff(request)
    return (
        "[CODEXTEAM HANDOFF V1]\n"
        f"{json.dumps(handoff, indent=2)}\n"
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
        "workspace_root": str(request.workspace),
        "task_context": {
            "prompt": request.prompt,
            "guidance_files": [str(path) for path in request.skill_files],
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


def run_process(
    command: list[str],
    *,
    prompt: str,
    timeout_seconds: int,
    env: dict[str, str],
    cwd: Path | None = None,
) -> ProcessResult:
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
    parser.add_argument("--profile", required=True)
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
                        "reasoning_effort": _session_reasoning_effort(request, turn.session),
                        "reasoning_effort_override": request.reasoning_effort_override,
                        "workspace": str(request.workspace),
                        "trust_parent_sandbox": request.trust_parent_sandbox,
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
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
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


def _skill_files(role: str, overrides: list[str]) -> tuple[Path, ...]:
    if overrides:
        paths = tuple(Path(value).expanduser().resolve(strict=True) for value in overrides)
    else:
        names = DEFAULT_SKILLS[role]
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


def _prepare_session_storage(request: SpawnRequest, *, initial: bool) -> None:
    if initial:
        request.session_dir.mkdir(parents=True, exist_ok=False)
        request.session_dir.chmod(0o700)
        request.codex_home.mkdir()
        request.codex_home.chmod(0o700)
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
    record = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "model_profile": request.profile,
        "model": request.model,
        "model_provider": request.model_provider,
        "model_catalog_json": request.model_catalog_json,
        "model_reasoning_effort": reasoning_effort,
        "reasoning_effort_override": reasoning_effort_override,
        "model_verbosity": request.model_verbosity,
        "workspace_root": str(request.workspace),
        "trust_parent_sandbox": request.trust_parent_sandbox,
        "thread_id": thread_id,
        "turn_count": turn.number,
        "last_phase": request.phase,
        "last_status": status,
        "last_turn_path": turn.message_path.relative_to(request.workspace).as_posix(),
        "created_at": created_at,
        "updated_at": now,
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
    return request.reasoning_effort_override or request.model_reasoning_effort


def _write_session(path: Path, session: dict[str, Any]) -> None:
    atomic_write_json(path, session)
    path.chmod(0o600)


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
        "thread_id": thread_id,
        "turn_count": turn.number,
        "session_path": str(request.session_path),
        "turn_path": str(turn.message_path),
        "events_path": str(turn.events_path),
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


def _schema_example(request: SpawnRequest) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "result_id": f"res-{request.task_id.lower()}-{request.attempt_id}",
        "team_id": request.team_id,
        "task_id": request.task_id,
        "agent_role": request.role,
        "attempt_id": request.attempt_id,
        "status": "completed",
        "summary": "<actual completed outcome and addressed feedback>",
        "output": {"exit_code": 0, "stdout_tail": "", "stderr_tail": "", "duration_seconds": 0},
        "file_changes": [
            {
                "path": "<actual project-relative changed file; remove object if none>",
                "action": "modified",
            }
        ],
        "evidence": [
            {
                "type": "artifact",
                "artifact_ref": "<actual existing project-relative evidence artifact>",
                "summary": "<what the artifact proves>",
                "metadata": {},
            }
        ],
        "requested_followups": [],
        "errors": [],
        "warnings": [],
        "limitations": [],
        "produced_at": "<actual current UTC timestamp ending in Z>",
    }


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
