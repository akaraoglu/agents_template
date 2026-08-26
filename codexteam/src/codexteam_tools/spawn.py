from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from fnmatch import fnmatchcase
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    AGENT_ROLES,
    ResultValidationError,
    validate_artifact_report,
    validate_handoff,
    validate_result,
    validate_session,
)
from .delegation import (
    DELEGATION_FILENAME,
    build_delegation,
    delegation_digest,
    load_delegation,
    write_delegation,
)
from .context_pack import CONTEXT_PACK_FILENAME, build_context_pack, write_context_pack
from .backend_adapter import BackendEventSummary, adapter_for
from .contract_registry import (
    ARTIFACT_REPORT,
    DEFAULT_DRAFT_FORMAT,
    DRAFT_FORMATS,
)
from .execution_spec import (
    EXECUTION_SPEC_FILENAME,
    compile_execution_spec,
    execution_spec_reference,
    load_execution_spec,
    write_execution_spec,
)
from .agent_specs import (
    AgentSpec,
    AgentSpecError,
    effective_policy_digest,
    effective_role_policy,
    guidance_paths as agent_spec_guidance_paths,
    load_agent_spec_snapshot,
    resolve_agent_spec,
)
from .execution_registry import (
    ExecutionRegistryError,
    ResolvedExecutionProfile,
    host_availability,
    load_execution_registry,
    require_execution_backend_enabled,
)
from .local_mcp import LocalMcpClient, context_server_spec
from .files import atomic_write_json, atomic_write_text, create_json
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
from .repository_binding import load_repository_binding
from . import opencode_backend
from .run_guard import ExactFailedRepeatGuard
from .turn_metrics import (
    metrics_path,
    previous_summary,
    summarize_turn,
    write_summary,
)
from .test_gates import (
    GateConfigError,
    gate_record_path,
    load_gate_config,
    run_gate,
    validate_current_gate_record,
)
from .tasks import TaskDocumentError, parse_task_handoff_metadata

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
PHASES = ("draft", "feedback", "final")
REASONING_EFFORTS = ("provider_default", "low", "medium", "high", "xhigh")
SESSION_SCHEMA_VERSION = "1.0"
ROLE_POLICY_FILENAME = "role-policy.json"
GUIDANCE_MANIFEST_FILENAME = "guidance-manifest.json"
TURN_STATE_FILENAME = "turn-state.json"
WORKSPACE_BASELINE_FILENAME = "workspace-baseline.json"
DRAFT_FORMAT_FILENAME = "draft-format.json"
HANDOFF_CONTRACT_FILENAME = "handoff-contract.json"
AGENT_SPEC_FILENAME = "agent-spec.json"
WORKSPACE_SCAN_EXCLUDES = (".git", ".codexteam/runtime")
ACCEPTANCE_PATH_EXCLUDES = (".git", ".codexteam")
CHECK_RECORD_ROOT = "results/checks"
DIRECT_VERIFICATION_EXECUTABLES = {"env", "go", "node", "python", "python3", "sh", "true"}
CONTEXT_MCP_SERVER = "codexteam-context"
CONTEXT_PROJECT_ENV = "CODEXTEAM_CONTEXT_PROJECT"
CONTEXT_WORK_ROOT_ENV = "CODEXTEAM_CONTEXT_WORK_ROOT"
CONTEXT_REPOSITORY_ID_ENV = "CODEXTEAM_CONTEXT_REPOSITORY_ID"
PROGRESS_INTERVAL_SECONDS = 30.0
POST_EXIT_DRAIN_SECONDS = 0.5
DESCENDANT_TERM_GRACE_SECONDS = 0.25
SMALL_EXECUTION_ROLES = {"documenter", "git_steward"}
DEBUG_STREAM_MODES = ("off", "assistant", "activity")
DEBUG_PREVIEW_CHARS = 1_200
SAFE_PROGRESS_EVENT_TYPES = {
    "error", "item.completed", "item.started", "step_finish", "step_start",
    "text", "thread.started", "tool_use", "turn.completed", "turn.started",
}
SAFE_PROGRESS_TOOLS = {
    "apply_patch", "bash", "edit", "glob", "grep", "question", "read",
    "skill", "task", "todowrite", "webfetch", "write",
}


@dataclass(frozen=True)
class SpawnRequest:
    backend: str
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
    control_root: Path
    work_root: Path
    git_root: Path
    git_prefix: str
    repo_id: str | None
    prompt: str
    prompt_source_path: str | None
    prompt_content_digest: str
    timeout_seconds: int
    execution_class: str
    result_dir: Path
    result_path: Path
    artifact_report_path: Path
    session_dir: Path
    session_path: Path
    draft_format: str
    draft_format_pinned: bool
    draft_format_path: Path
    codex_home: Path
    source_codex_home: Path
    configured_mcp_servers: tuple[str, ...]
    effective_mcp_servers: tuple[str, ...]
    missing_mcp_servers: tuple[str, ...]
    effective_mcp_tools: tuple[tuple[str, tuple[str, ...]], ...]
    mcp_context_project: str | None
    add_dirs: tuple[Path, ...]
    trust_parent_sandbox: bool
    run_guard: bool
    debug_stream: str
    skill_files: tuple[Path, ...]
    guidance_digest: str
    profile_file: Path
    role_policy: RolePolicy
    effective_role_policy: RolePolicy
    role_policy_path: Path
    agent_spec: AgentSpec | None
    agent_spec_path: Path
    backend_version: str | None
    backend_config_path: Path | None
    backend_config_digest: str | None
    opencode_project_instructions: str | None
    gate_routing: dict[str, str] | None
    execution_spec_path: Path
    execution_spec: dict[str, Any] | None
    execution_profile: ResolvedExecutionProfile
    task_write_scope: tuple[str, ...] | None
    context_mode: str | None
    result_report: str | None
    direct_context: tuple[tuple[str, int, int], ...]
    verification_commands: tuple[tuple[str, ...], ...]
    result_status: str
    feedback_mode: str
    delegation: dict[str, Any] | None

    @property
    def backend_mcp_args(self) -> tuple[str, ...]:
        return tuple(_mcp_override_args(self))

    @property
    def execution_codex_home(self) -> Path:
        return _execution_codex_home(self)

    @property
    def split_root(self) -> bool:
        return self.repo_id is not None

    @property
    def worker_add_dirs(self) -> tuple[Path, ...]:
        if not self.split_root:
            return self.add_dirs
        return (self.artifact_report_path.parent,)

@dataclass(frozen=True)
class TurnContext:
    number: int
    lead_prompt_path: Path
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


def _default_execution_class(*, context_mode: str | None, role: str, prompt: str) -> str:
    if re.search(r"(?m)^PLANNED LANE\s*$", prompt):
        return "complex"
    return "small"


def _required_complex_checkpoint(request: SpawnRequest) -> str | None:
    if request.execution_class != "complex":
        return None
    session = request.session_path
    accepted: str | None = None
    if session.is_file() and not session.is_symlink():
        value = json.loads(session.read_text(encoding="utf-8"))
        candidate = value.get("complex_checkpoint")
        accepted = candidate if isinstance(candidate, str) else None
    if request.role == "developer":
        return "source_focused_tests"
    if request.role == "tester":
        return "integration_evidence"
    return "final_report"


def _complex_checkpoint_error(
    request: SpawnRequest, report: dict[str, Any]
) -> str | None:
    expected = _required_complex_checkpoint(request)
    if expected is None:
        return None
    actual = report.get("checkpoint")
    if actual != expected:
        return f"complex work requires checkpoint {expected!r}, got {actual!r}"
    return None


def prepare_request(args: argparse.Namespace) -> SpawnRequest:
    if os.environ.get("CODEXTEAM_LAUNCHED_WORKER") == "1":
        raise ValueError("nested CodexTeam worker launches are not enabled")
    phase = args.phase
    if phase not in PHASES:
        raise ValueError(f"unsupported conversation phase: {phase}")
    team_id = validate_identifier(args.team, label="team ID")
    task_id = normalize_task_id(args.task)
    attempt_id = validate_identifier(args.attempt, label="attempt ID")
    if args.role not in AGENT_ROLES:
        raise ValueError(f"unsupported agent role: {args.role}")
    if args.timeout is not None and args.timeout < 1:
        raise ValueError("timeout must be a positive integer")
    registry = load_execution_registry()
    backend_value = getattr(args, "backend", None)
    profile_value = getattr(args, "profile", None)
    reasoning_effort_value = getattr(args, "reasoning_effort", None)
    execution_spec_path = session_dir = None
    trust_parent_sandbox = bool(getattr(args, "trust_parent_sandbox", False))
    run_guard = bool(getattr(args, "run_guard", False))
    debug_stream_value = getattr(args, "debug_stream", None)
    requested_result_status = getattr(args, "result_status", None)
    result_status = requested_result_status or "completed"
    if phase != "final" and requested_result_status is not None:
        raise ValueError("--result-status is valid only for finalization")
    # Runtime selectors are explicit on draft and forbidden on continuation.
    if phase == "draft":
        if backend_value is None or profile_value is None or reasoning_effort_value is None:
            raise ValueError("draft requires explicit --backend, --profile, and --reasoning-effort")
        execution_profile = registry.resolve(backend_value, profile_value, reasoning_effort_value)
    else:
        if any(value is not None for value in (backend_value, profile_value, reasoning_effort_value)):
            raise ValueError("feedback/final load backend, profile, and reasoning from ExecutionSpec")
        execution_profile = None
    backend = execution_profile.backend_id if execution_profile is not None else ""
    if backend == "opencode":
        unsupported = []
        if trust_parent_sandbox:
            unsupported.append("--trust-parent-sandbox")
        if run_guard:
            unsupported.append("--run-guard")
        if unsupported:
            raise ValueError(
                "OpenCode backend does not support " + ", ".join(unsupported)
            )
    reasoning_effort_override = (
        _validate_reasoning_effort(reasoning_effort_value) if phase == "draft" else None
    )

    workspace_value = getattr(args, "workspace", None)
    split_values = (
        getattr(args, "control_root", None),
        getattr(args, "work_root", None),
        getattr(args, "repo_id", None),
    )
    if workspace_value is not None and any(value is not None for value in split_values):
        raise ValueError("--workspace cannot be mixed with split-root arguments")
    if workspace_value is None and not all(value is not None for value in split_values):
        raise ValueError(
            "supply either --workspace or all of --control-root, --work-root, and --repo-id"
        )
    if workspace_value is not None:
        workspace = control_root = work_root = git_root = ensure_existing_workspace(workspace_value)
        git_prefix = "."
        repo_id = None
    else:
        assert all(value is not None for value in split_values)
        binding = load_repository_binding(
            str(split_values[0]), str(split_values[1]), str(split_values[2])
        )
        control_root = binding.control_root
        workspace = work_root = binding.work_root
        git_root = binding.git_root
        git_prefix = binding.git_prefix
        repo_id = binding.repo_id
    safe_relative_path(args.result_dir, label="result directory")
    result_dir = contained_path(control_root, args.result_dir, label="result directory")
    result_path = contained_path(
        control_root,
        f"{args.result_dir}/{task_id}-{attempt_id}.json",
        label="result path",
    )
    artifact_report_path = contained_path(
        control_root,
        (
            f".codexteam/runtime/sessions/{team_id}/{task_id}/{attempt_id}/exchange/report.json"
            if repo_id is not None
            else f"results/reports/{task_id}-{attempt_id}.json"
        ),
        label="artifact report path",
    )
    session_dir = contained_path(
        control_root,
        f".codexteam/runtime/sessions/{team_id}/{task_id}/{attempt_id}",
        label="session directory",
    )
    session_path = session_dir / "session.json"
    execution_spec_path = session_dir / EXECUTION_SPEC_FILENAME
    spec: dict[str, Any] | None = None
    existing_session = (
        _load_session(session_path)
        if phase != "draft" and session_path.is_file()
        else None
    )
    if phase != "draft":
        if existing_session is None:
            raise ValueError("post-cutover continuation requires session.json")
        spec = load_execution_spec(execution_spec_path)
        profile_ref = spec.get("execution_profile")
        if not isinstance(profile_ref, dict):
            raise ValueError("execution specification lacks curated execution profile")
        backend = profile_ref["backend"]["id"]
        profile_leaf = profile_ref["profile"]["id"].split("/", 1)[1]
        reasoning = profile_ref["reasoning"]["requested"]
        execution_profile = registry.resolve(backend, profile_leaf, reasoning)
        current_profile_ref = execution_profile.reference(
            runtime_version=profile_ref["backend"]["runtime_version"],
            backend_material_digest=profile_ref["backend_material_digest"],
        )
        # Registry additions must not invalidate otherwise immutable attempts.
        current_profile_ref["registry_digest"] = profile_ref["registry_digest"]
        if current_profile_ref != profile_ref:
            raise ValueError("execution profile registry definition mismatch")
        permissions = spec["permissions"]
        if getattr(args, "add_dir", None) or trust_parent_sandbox:
            raise ValueError(
                "feedback/final load additional write roots and parent sandbox trust from ExecutionSpec"
            )
        trust_parent_sandbox = permissions["trust_parent_sandbox"]
    debug_stream = str(
        debug_stream_value
        if debug_stream_value is not None
        else ("activity" if backend == "opencode" else "off")
    )
    if debug_stream != "off" and backend != "opencode":
        raise ValueError("--debug-stream is supported only by the OpenCode backend")
    draft_format_path = session_dir / DRAFT_FORMAT_FILENAME
    if phase == "draft":
        draft_format = ARTIFACT_REPORT
        draft_format_pinned = True
    else:
        draft_format = _load_draft_format_pin(draft_format_path)
        draft_format_pinned = True
    assert execution_profile is not None
    role_policy_path = session_dir / ROLE_POLICY_FILENAME
    if phase == "draft":
        role_policy = load_role_policy(args.role)
    else:
        if not role_policy_path.is_file() or role_policy_path.is_symlink():
            raise FileNotFoundError("post-cutover RolePolicy snapshot is missing or unsafe")
        role_policy = load_role_policy_snapshot(role_policy_path, expected_role=args.role)
    requested_agent_spec = getattr(args, "agent_spec", None)
    agent_spec_path = session_dir / AGENT_SPEC_FILENAME
    if phase == "draft":
        agent_spec = resolve_agent_spec(args.role, requested_agent_spec)
    else:
        if requested_agent_spec is not None:
            raise ValueError("--agent-spec is valid only when creating a draft attempt")
        spec_agent_ref = spec.get("agent_spec") if spec is not None else None
        if spec_agent_ref is not None:
            if not agent_spec_path.is_file() or agent_spec_path.is_symlink():
                raise FileNotFoundError("post-cutover AgentSpec snapshot is missing or unsafe")
            agent_spec = load_agent_spec_snapshot(agent_spec_path, expected_role=args.role)
            if agent_spec.reference() != spec_agent_ref:
                raise ValueError("execution specification AgentSpec reference mismatch")
        else:
            agent_spec = None
    effective_policy = (
        effective_role_policy(role_policy, agent_spec)
        if agent_spec is not None
        else role_policy
    )
    profile = execution_profile.profile_id
    feedback_mode = getattr(args, "feedback_mode", None) or "revision"
    if phase != "feedback" and getattr(args, "feedback_mode", None) is not None:
        raise ValueError("--feedback-mode is valid only for feedback")
    if feedback_mode == "format-only" and backend != "opencode":
        raise ValueError("format-only feedback currently requires the OpenCode backend")

    prompt, prompt_source_path, prompt_content_digest = _read_prompt(
        args.prompt_file, args.prompt, control_root
    )
    contract: dict[str, Any] = {}
    if phase == "draft":
        task_metadata = _task_handoff_metadata(prompt, prompt_source_path, args.role)
        task_write_scope = task_metadata.task_write_scope
        context_mode = task_metadata.context_mode
        result_report = task_metadata.result_report
        direct_context = task_metadata.direct_context
        verification_commands = task_metadata.verification_commands
        execution_class = task_metadata.execution_class or _default_execution_class(
            context_mode=context_mode, role=args.role, prompt=prompt
        )
        if context_mode == "direct" and backend != "opencode":
            raise ValueError("Context Mode direct currently requires the OpenCode backend")
    else:
        task_write_scope = (
            tuple(spec["permissions"]["task_write_scope"])
            if spec is not None and spec["permissions"]["task_write_scope"] is not None
            else None
        )
        contract = _load_handoff_contract(session_dir)
        context_mode = contract.get("context_mode")
        result_report = contract.get("result_report")
        direct_context = tuple(
            (item["path"], item["start"], item["end"])
            for item in contract.get("direct_context", [])
        )
        verification_commands = tuple(
            tuple(item) for item in contract.get("verification_commands", [])
        )
        execution_class = contract.get("execution_class") or _default_execution_class(
            context_mode=context_mode, role=args.role, prompt=""
        )
    timeout_seconds = args.timeout
    if phase != "draft":
        pinned_timeout = contract.get("timeout_seconds")
        if not isinstance(pinned_timeout, int) or isinstance(pinned_timeout, bool):
            pinned_timeout = 600 if execution_class == "small" else 1200
        if timeout_seconds is not None and timeout_seconds != pinned_timeout:
            raise ValueError("continuation timeout must match the pinned draft timeout")
        timeout_seconds = pinned_timeout
    if timeout_seconds is None:
        timeout_seconds = 600 if execution_class == "small" else 1200
    if phase == "draft":
        add_dir_values = args.add_dir
    else:
        assert spec is not None
        add_dir_values = spec["permissions"]["additional_write_roots"]
    if repo_id is not None and add_dir_values:
        raise ValueError("split-root attempts allow only the private attempt exchange add-dir")
    add_dirs = tuple(ensure_existing_workspace(path) for path in add_dir_values)
    if phase != "draft" and args.skill_file:
        raise ValueError("skill guidance cannot be overridden after the draft turn")
    guidance_manifest_path = session_dir / GUIDANCE_MANIFEST_FILENAME
    if phase == "draft":
        skill_files = _skill_files(role_policy, args.skill_file)
        if agent_spec is not None:
            if args.skill_file and agent_spec.guidance_files:
                raise ValueError("--skill-file cannot replace selected AgentSpec guidance")
            skill_files = (*skill_files, *agent_spec_guidance_paths(agent_spec))
    else:
        if not guidance_manifest_path.is_file() or guidance_manifest_path.is_symlink():
            raise FileNotFoundError("post-cutover guidance manifest is missing or unsafe")
        skill_files = _load_pinned_skill_files(session_dir)
    guidance_digest = _guidance_bundle_digest(skill_files)
    gate_routing = _resolve_gate_routing(control_root, args.role)
    source_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve(
        strict=False
    )
    if backend == "opencode":
        if phase == "draft":
            availability = host_availability(registry, backend, profile)
            if not availability["host_available"]:
                raise ValueError(availability["reason_unavailable"])
        model = execution_profile.provider_locator
        model_provider = execution_profile.provider
        backend_config_path = opencode_backend.config_path(session_dir / "opencode-runtime")
        context_plugin = _opencode_context_plugin_config(session_dir, execution_profile)
        if existing_session is None:
            project_instructions = _workspace_agents_instructions(workspace)
            backend_config = opencode_backend.build_config(
                model=model,
                role_name=args.role,
                role_instructions=effective_policy.developer_instructions,
                project_instructions=project_instructions,
                add_dirs=(artifact_report_path.parent,) if repo_id is not None else add_dirs,
                display_name=execution_profile.model["display_name"],
                context_limit=execution_profile.model["context_limit"],
                output_limit=execution_profile.model["output_limit"],
                direct_mode=context_mode == "direct",
                editable_paths=task_write_scope or (),
                artifact_report_path=artifact_report_path.as_posix(),
                context_plugin=context_plugin,
            )
            backend_config_digest = opencode_backend.config_digest(backend_config)
        else:
            project_instructions = None
            backend_config_digest = existing_session.get("backend_config_digest")
            if not isinstance(backend_config_digest, str) or not backend_config_digest:
                raise ValueError("OpenCode session backend_config_digest must be a non-empty string")
        if phase == "draft":
            sidecar_tools = tuple(
                tool
                for tool in effective_policy.tools_for_server("codexteam-context")
                if tool == "get_task_context"
            )
            sidecar_enabled = bool(
                repo_id is None
                and context_mode != "direct"
                and
                prompt_source_path
                and re.fullmatch(r"management/tasks/T[0-9]{3,6}\.md", prompt_source_path)
                and sidecar_tools
            )
            effective_mcp_servers = (("codexteam-context",) if sidecar_enabled else ())
            missing_mcp_servers = ()
            effective_mcp_tools = (
                (("codexteam-context", sidecar_tools),) if sidecar_enabled else ()
            )
            mcp_context_project = workspace.name if sidecar_enabled else None
        else:
            assert spec is not None
            permissions = spec["permissions"]
            effective_mcp_servers = tuple(permissions["mcp_effective_servers"])
            missing_mcp_servers = tuple(permissions["mcp_missing_servers"])
            effective_mcp_tools = tuple(
                (server, tuple(tools))
                for server, tools in permissions["mcp_effective_tools"].items()
            )
            mcp_context_project = permissions["bound_mcp_project"]
            if phase == "feedback":
                effective_mcp_servers = ()
                effective_mcp_tools = ()
                mcp_context_project = None
        request = SpawnRequest(
            backend=backend,
            phase=phase,
            profile=profile,
            model=model,
            model_provider=model_provider,
            model_catalog_json=None,
            model_reasoning_effort=None,
            reasoning_effort_override=None,
            model_verbosity=None,
            team_id=team_id,
            task_id=task_id,
            role=args.role,
            attempt_id=attempt_id,
            workspace=workspace,
            control_root=control_root,
            work_root=work_root,
            git_root=git_root,
            git_prefix=git_prefix,
            repo_id=repo_id,
            prompt=prompt,
            prompt_source_path=prompt_source_path,
            prompt_content_digest=prompt_content_digest,
            timeout_seconds=timeout_seconds,
            execution_class=execution_class,
            result_dir=result_dir,
            result_path=result_path,
            artifact_report_path=artifact_report_path,
            session_dir=session_dir,
            session_path=session_path,
            draft_format=draft_format,
            draft_format_pinned=draft_format_pinned,
            draft_format_path=draft_format_path,
            codex_home=session_dir / "codex-home",
            source_codex_home=source_codex_home,
            configured_mcp_servers=effective_mcp_servers,
            effective_mcp_servers=effective_mcp_servers,
            missing_mcp_servers=missing_mcp_servers,
            effective_mcp_tools=effective_mcp_tools,
            mcp_context_project=mcp_context_project,
            add_dirs=add_dirs,
            trust_parent_sandbox=False,
            run_guard=False,
            debug_stream=debug_stream,
            skill_files=skill_files,
            guidance_digest=guidance_digest,
            profile_file=backend_config_path,
            role_policy=role_policy,
            effective_role_policy=effective_policy,
            role_policy_path=role_policy_path,
            agent_spec=agent_spec,
            agent_spec_path=agent_spec_path,
            backend_version=(
                existing_session.get("backend_version")
                if existing_session is not None
                else None
            ),
            backend_config_path=backend_config_path,
            backend_config_digest=backend_config_digest,
            opencode_project_instructions=project_instructions,
            gate_routing=gate_routing,
            execution_spec_path=execution_spec_path,
            execution_spec=None,
            execution_profile=execution_profile,
            task_write_scope=task_write_scope,
            context_mode=context_mode,
            result_report=result_report,
            direct_context=direct_context,
            verification_commands=verification_commands,
            result_status=result_status,
            feedback_mode=feedback_mode,
            delegation=(
                build_delegation(
                    team_id=team_id, task_id=task_id, attempt_id=attempt_id,
                    role=args.role, workspace=workspace,
                ) if phase == "draft" else None
            ),
        )
        return _with_execution_spec(request, existing_session)
    codex_config_path = (
        session_dir / "codex-home" / "config.toml"
        if phase != "draft"
        else source_codex_home / "config.toml"
    )
    configured_mcp_servers = _configured_mcp_servers(codex_config_path)
    if phase == "draft":
        effective_mcp_servers = tuple(
            server for server in effective_policy.mcp_servers if server in configured_mcp_servers
        )
        if context_mode == "direct":
            effective_mcp_servers = ()
        missing_mcp_servers = tuple(
            server for server in effective_policy.mcp_servers if server not in configured_mcp_servers
        )
        effective_mcp_tools = tuple(
            (server, tools)
            for server, tools in effective_policy.mcp_tools
            if server in effective_mcp_servers
        )
    elif phase == "feedback":
        effective_mcp_servers = ()
        missing_mcp_servers = tuple(
            server for server in effective_policy.mcp_servers if server not in configured_mcp_servers
        )
        effective_mcp_tools = ()
    else:
        assert spec is not None
        permissions = spec["permissions"]
        effective_mcp_servers = tuple(permissions["mcp_effective_servers"])
        missing_mcp_servers = tuple(permissions["mcp_missing_servers"])
        effective_mcp_tools = tuple(
            (server, tuple(tools))
            for server, tools in permissions["mcp_effective_tools"].items()
        )
    mcp_context_project = (
        _mcp_context_project(
            config_path=codex_config_path,
            control_root=control_root,
            workspace=workspace,
            repo_id=repo_id,
            role=args.role,
            phase=phase,
            effective_mcp_servers=effective_mcp_servers,
            existing_session=existing_session,
        )
        if phase == "draft"
        else None
        if phase == "feedback"
        else spec["permissions"]["bound_mcp_project"]
    )
    source_profile = execution_profile.profile.get("source_profile")
    profile_root = (
        session_dir / "codex-home"
        if phase != "draft"
        else source_codex_home
    )
    profile_file = profile_root / f"{source_profile}.config.toml"
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
    if model.strip() != execution_profile.provider_locator or model_provider.strip() != execution_profile.provider:
        raise ValueError("installed Codex profile material does not match curated execution registry")
    if model_catalog_json is not None and not isinstance(model_catalog_json, str):
        raise ValueError(f"Codex profile model_catalog_json must be a string: {profile_file}")
    if model_reasoning_effort is not None and not isinstance(model_reasoning_effort, str):
        raise ValueError(f"Codex profile model_reasoning_effort must be a string: {profile_file}")
    if model_verbosity is not None and not isinstance(model_verbosity, str):
        raise ValueError(f"Codex profile model_verbosity must be a string: {profile_file}")
    if trust_parent_sandbox and model_provider.strip() == "openai":
        raise ValueError(
            "--trust-parent-sandbox requires a local model profile because authenticated "
            "OpenAI workers reuse the source CODEX_HOME outside the parent writable root"
        )

    request = SpawnRequest(
        backend=backend,
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
        control_root=control_root,
        work_root=work_root,
        git_root=git_root,
        git_prefix=git_prefix,
        repo_id=repo_id,
        prompt=prompt,
        prompt_source_path=prompt_source_path,
        prompt_content_digest=prompt_content_digest,
        timeout_seconds=timeout_seconds,
        execution_class=execution_class,
        result_dir=result_dir,
        result_path=result_path,
        artifact_report_path=artifact_report_path,
        session_dir=session_dir,
        session_path=session_path,
        draft_format=draft_format,
        draft_format_pinned=draft_format_pinned,
        draft_format_path=draft_format_path,
        codex_home=session_dir / "codex-home",
        source_codex_home=source_codex_home,
        configured_mcp_servers=configured_mcp_servers,
        effective_mcp_servers=effective_mcp_servers,
        missing_mcp_servers=missing_mcp_servers,
        effective_mcp_tools=effective_mcp_tools,
        mcp_context_project=mcp_context_project,
        add_dirs=add_dirs,
        trust_parent_sandbox=trust_parent_sandbox,
        run_guard=run_guard,
        debug_stream=debug_stream,
        skill_files=skill_files,
        guidance_digest=guidance_digest,
        profile_file=profile_file,
        role_policy=role_policy,
        effective_role_policy=effective_policy,
        role_policy_path=role_policy_path,
        agent_spec=agent_spec,
        agent_spec_path=agent_spec_path,
        backend_version=None,
        backend_config_path=None,
        backend_config_digest=None,
        opencode_project_instructions=None,
        gate_routing=gate_routing,
        execution_spec_path=execution_spec_path,
        execution_spec=None,
        execution_profile=execution_profile,
        task_write_scope=task_write_scope,
        context_mode=context_mode,
        result_report=result_report,
        direct_context=direct_context,
        verification_commands=verification_commands,
        result_status=result_status,
        feedback_mode=feedback_mode,
        delegation=(
            build_delegation(
                team_id=team_id, task_id=task_id, attempt_id=attempt_id,
                role=args.role, workspace=workspace,
            ) if phase == "draft" else None
        ),
    )
    return _with_execution_spec(request, existing_session)


def _with_execution_spec(
    request: SpawnRequest,
    existing_session: dict[str, Any] | None,
) -> SpawnRequest:
    spec = _resolve_execution_spec(request, existing_session=existing_session)
    return replace(request, execution_spec=spec)


def _resolve_execution_spec(
    request: SpawnRequest,
    *,
    existing_session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if request.phase == "draft":
        return compile_execution_spec(
            team_id=request.team_id,
            task_id=request.task_id,
            attempt_id=request.attempt_id,
            role=request.role,
            workspace_root=str(request.workspace),
            control_root=(str(request.control_root) if request.split_root else None),
            work_root=(str(request.work_root) if request.split_root else None),
            git_root=(str(request.git_root) if request.split_root else None),
            git_prefix=(request.git_prefix if request.split_root else None),
            repo_id=request.repo_id,
            handoff_source_path=request.prompt_source_path,
            handoff_content_digest=request.prompt_content_digest,
            role_policy_name=request.role_policy.name,
            role_policy_version=request.role_policy.schema_version,
            role_policy_digest=request.role_policy.digest,
            agent_spec=(request.agent_spec.reference() if request.agent_spec is not None else None),
            effective_policy_digest=effective_policy_digest(request.effective_role_policy),
            guidance_files=[path.name for path in request.skill_files],
            guidance_digest=request.guidance_digest,
            execution_profile=request.execution_profile.reference(
                runtime_version=request.backend_version,
                backend_material_digest=_backend_material_digest(request),
            ),
            sandbox_mode=request.effective_role_policy.sandbox_mode,
            trust_parent_sandbox=request.trust_parent_sandbox,
            additional_write_roots=[str(path) for path in request.add_dirs],
            mcp_allowed_servers=list(request.effective_role_policy.mcp_servers),
            mcp_effective_servers=list(request.effective_mcp_servers),
            mcp_missing_servers=list(request.missing_mcp_servers),
            mcp_allowed_tools={server: list(tools) for server, tools in request.effective_role_policy.mcp_tools},
            mcp_effective_tools={server: list(tools) for server, tools in request.effective_mcp_tools},
            bound_mcp_project=request.mcp_context_project,
            task_write_scope=(
                list(request.task_write_scope)
                if request.task_write_scope is not None
                else None
            ),
            gate_routing=request.gate_routing,
        )

    session = existing_session
    if session is None and request.session_path.is_file():
        session = _load_session(request.session_path)
    reference = session.get("execution_spec") if session else None
    path_exists = request.execution_spec_path.exists() or request.execution_spec_path.is_symlink()
    if reference is None and not path_exists:
        return None
    if reference is None or not path_exists:
        raise ValueError("execution specification reference and sidecar must both exist")
    spec = load_execution_spec(request.execution_spec_path)
    if reference != execution_spec_reference(spec):
        raise ValueError("session execution specification reference mismatch")
    _validate_execution_spec_request(request, spec)
    return spec


def _validate_execution_spec_request(request: SpawnRequest, spec: dict[str, Any]) -> None:
    expected = {
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "role": request.role,
        "workspace_root": str(request.workspace),
    }
    if request.split_root:
        assert request.repo_id is not None
        expected.update({
            "control_root": str(request.control_root),
            "work_root": str(request.work_root),
            "git_root": str(request.git_root),
            "git_prefix": request.git_prefix,
            "repo_id": request.repo_id,
        })
    if spec["identity"] != expected:
        raise ValueError("execution specification identity mismatch")
    if spec["role_policy"] != {
        "name": request.role_policy.name,
        "version": request.role_policy.schema_version,
        "digest": request.role_policy.digest,
    }:
        raise ValueError("execution specification role policy mismatch")
    expected_agent_spec = request.agent_spec.reference() if request.agent_spec is not None else None
    if spec["agent_spec"] != expected_agent_spec:
        raise ValueError("execution specification AgentSpec mismatch")
    if spec["guidance"] != {
        "files": [path.name for path in request.skill_files],
        "bundle_digest": request.guidance_digest,
    }:
        raise ValueError("execution specification guidance mismatch")
    expected_profile = request.execution_profile.reference(
        runtime_version=request.backend_version,
        backend_material_digest=_backend_material_digest(request),
    )
    expected_profile["registry_digest"] = spec["execution_profile"]["registry_digest"]
    if spec["execution_profile"] != expected_profile:
        raise ValueError("execution specification profile mismatch")
    expected_effective_servers = (
        spec["permissions"]["mcp_effective_servers"]
        if request.phase == "feedback"
        else list(request.effective_mcp_servers)
    )
    expected_effective_tools = (
        spec["permissions"]["mcp_effective_tools"]
        if request.phase == "feedback"
        else {server: list(tools) for server, tools in request.effective_mcp_tools}
    )
    expected_bound_project = (
        spec["permissions"]["bound_mcp_project"]
        if request.phase == "feedback"
        else request.mcp_context_project
    )
    if spec["permissions"] != {
        "effective_policy_digest": effective_policy_digest(request.effective_role_policy),
        "sandbox_mode": request.effective_role_policy.sandbox_mode,
        "trust_parent_sandbox": request.trust_parent_sandbox,
        "additional_write_roots": [str(path) for path in request.add_dirs],
        "mcp_allowed_servers": list(request.effective_role_policy.mcp_servers),
        "mcp_effective_servers": expected_effective_servers,
        "mcp_missing_servers": list(request.missing_mcp_servers),
        "mcp_allowed_tools": {server: list(tools) for server, tools in request.effective_role_policy.mcp_tools},
        "mcp_effective_tools": expected_effective_tools,
        "bound_mcp_project": expected_bound_project,
        "task_write_scope": (
            list(request.task_write_scope)
            if request.task_write_scope is not None
            else None
        ),
    }:
        raise ValueError("execution specification permissions mismatch")
    if spec["gate_routing"] != request.gate_routing:
        raise ValueError("execution specification gate routing mismatch")
    initial_prompt = request.session_dir / "turns" / "001-draft.lead-prompt.md"
    if request.phase != "draft":
        if initial_prompt.is_symlink() or not initial_prompt.is_file():
            raise ValueError("execution specification handoff snapshot is missing or unsafe")
        actual_handoff_digest = hashlib.sha256(initial_prompt.read_bytes()).hexdigest()
        if actual_handoff_digest != spec["handoff"]["content_digest"]:
            raise ValueError("execution specification handoff content digest mismatch")


def _backend_material_digest(request: SpawnRequest) -> str:
    if request.backend == "opencode":
        if request.backend_config_digest is None:
            raise ValueError("OpenCode execution profile requires backend config digest")
        return request.backend_config_digest
    return hashlib.sha256(request.profile_file.read_bytes()).hexdigest()


def _opencode_context_plugin_config(
    session_dir: Path,
    profile: ResolvedExecutionProfile,
) -> dict[str, str] | None:
    if profile.backend_id != "opencode" or profile.profile_id != "qwen38-27b-context":
        return None
    effort = profile.effective_reasoning
    if effort not in {"low", "medium", "high"}:
        raise ValueError("OpenCode Qwen 3.8 requires explicit low, medium, or high reasoning")
    runtime_root = session_dir / "opencode-runtime"
    return {
        "path": str(opencode_backend.context_plugin_path(runtime_root)),
        "archive_root": str(opencode_backend.context_archive_path(session_dir)),
        "digest": opencode_backend.context_plugin_digest(),
        "reasoning_effort": effort,
    }


def _execution_reasoning(
    request: SpawnRequest,
    *,
    session: dict[str, Any] | None = None,
) -> tuple[str | None, str | None, str]:
    return (
        request.execution_profile.requested_reasoning,
        request.execution_profile.effective_reasoning,
        request.execution_profile.reasoning_support_status,
    )


def _verify_execution_spec_immutable(request: SpawnRequest) -> None:
    if request.execution_spec is None:
        return
    current = load_execution_spec(request.execution_spec_path)
    if current != request.execution_spec:
        raise ValueError("execution specification changed during worker execution")
    if request.agent_spec is not None:
        snapshot = load_agent_spec_snapshot(request.agent_spec_path, expected_role=request.role)
        if snapshot.reference() != request.agent_spec.reference():
            raise ValueError("AgentSpec snapshot changed during worker execution")


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
        lead_prompt_path=turns_dir / f"{stem}.lead-prompt.md",
        message_path=turns_dir / f"{stem}.txt",
        events_path=turns_dir / f"{stem}.jsonl",
        stderr_path=turns_dir / f"{stem}.stderr.txt",
        state_path=request.session_dir / TURN_STATE_FILENAME,
        session=session,
    )


def run_spawn(
    request: SpawnRequest,
    *,
    executable: str | None = None,
    _lock_held: bool = False,
) -> tuple[dict[str, Any], int]:
    if request.phase == "feedback" and not _lock_held:
        lock_path = _acquire_attempt_lock(request)
        try:
            return run_spawn(request, executable=executable, _lock_held=True)
        finally:
            lock_path.unlink(missing_ok=True)
    if request.phase == "final":
        return _seal_semantic_result(request)
    executable = executable or request.backend
    turn = prepare_turn(request)
    if turn.is_initial:
        request.session_dir.mkdir(parents=True, exist_ok=False)
        request.session_dir.chmod(0o700)
    _write_turn_state(request, turn, status="initializing", verify_spec=False)
    try:
        adapter = adapter_for(request.backend)
        backend_version = adapter.preflight(request, executable)
        if backend_version is not None:
            request = replace(request, backend_version=backend_version)
        if request.backend == "opencode" and request.phase == "draft":
            request = replace(
                request,
                execution_spec=_resolve_execution_spec(
                    replace(request, execution_spec=None),
                ),
            )
        if turn.session is not None:
            _validate_session_scope(request, turn.session)
        _prepare_session_storage(request, initial=turn.is_initial, session=turn.session)
    except Exception as exc:
        _write_turn_state(
            request, turn, status="turn_failed",
            errors=[f"worker setup failed: {exc}"], verify_spec=False,
        )
        raise
    delegation_path = request.session_dir / DELEGATION_FILENAME
    delegation_before = (
        hashlib.sha256(delegation_path.read_bytes()).hexdigest()
        if delegation_path.is_file() and not delegation_path.is_symlink()
        else None
    )
    trusted_baseline: dict[str, str] | None = None
    trusted_baseline_digest: str | None = None
    try:
        if request.backend == "opencode" or request.draft_format == ARTIFACT_REPORT:
            expected_baseline = (
                turn.session.get("workspace_baseline_sha256") if turn.session else None
            )
            trusted_baseline = _load_workspace_baseline(
                request,
                expected_digest=expected_baseline,
            )
            trusted_baseline_digest = _workspace_baseline_digest(trusted_baseline)
        turn.message_path.parent.mkdir(parents=True, exist_ok=True)
        turn.message_path.parent.chmod(0o700)
        before_workspace = _snapshot_request_workspace(request)
        prior_artifact_report_bytes = (
            request.artifact_report_path.read_bytes()
            if request.artifact_report_path.is_file() and not request.artifact_report_path.is_symlink()
            else None
        )
        before_additional = tuple(snapshot_workspace(path) for path in request.add_dirs)
        prior_turn_state_bytes = turn.state_path.read_bytes()
        command = build_command(request, turn, executable=executable)
        worker_prompt = build_prompt(request, turn)
        sidecar_provenance: dict[str, Any] | None = None
        if (
            request.phase == "draft"
            and request.backend == "opencode"
            and "codexteam-context" in request.effective_mcp_servers
        ):
            context, sidecar_provenance = _opencode_task_context(request)
            if context is not None:
                worker_prompt += (
                    "\n\n[BOUNDED LOCAL MCP CONTEXT]\n"
                    + json.dumps(context, sort_keys=True, separators=(",", ":"))
                    + "\n[/BOUNDED LOCAL MCP CONTEXT]\n"
                )
        atomic_write_text(turn.lead_prompt_path, request.prompt)
        turn.lead_prompt_path.chmod(0o600)
        environment = adapter.environment(request)
        _write_turn_state(request, turn, status="running")
        process = run_process(
            command,
            prompt=worker_prompt,
            timeout_seconds=request.timeout_seconds,
            env=environment,
            cwd=request.work_root,
            events_path=turn.events_path,
            stderr_path=turn.stderr_path,
            run_guard=request.run_guard,
            debug_stream=request.debug_stream,
        )
    except Exception as exc:
        _write_turn_state(
            request, turn, status="turn_failed",
            errors=[f"worker setup failed: {exc}"], verify_spec=False,
        )
        raise
    if delegation_before is not None:
        if delegation_path.is_symlink() or not delegation_path.is_file():
            raise ValueError("delegation attribution changed during worker execution")
        delegation_after = hashlib.sha256(delegation_path.read_bytes()).hexdigest()
        if delegation_after != delegation_before:
            raise ValueError("delegation attribution changed during worker execution")
    _verify_execution_spec_immutable(request)
    atomic_write_text(turn.events_path, process.stdout)
    atomic_write_text(turn.stderr_path, process.stderr)
    after_workspace = _snapshot_request_workspace(request)
    after_additional = tuple(snapshot_workspace(path) for path in request.add_dirs)
    changed_paths = changed_workspace_paths(before_workspace, after_workspace)
    change_actions = _workspace_change_actions(
        before_workspace,
        after_workspace,
        changed_paths,
    )
    boundary_errors = role_boundary_errors(
        request.effective_role_policy,
        changed_paths,
        task_write_scope=request.task_write_scope,
    )
    report_relative = _artifact_report_reference(request)
    if not request.split_root:
        boundary_errors = [
            error for error in boundary_errors
            if not error.endswith(f"changing {report_relative}")
        ]
    if request.feedback_mode == "format-only":
        boundary_errors.extend(
            f"format-only feedback does not allow changing {path}"
            for path in changed_paths
            if path != report_relative
        )
    for root, before, after in zip(
        request.add_dirs, before_additional, after_additional, strict=True
    ):
        external_changes = changed_workspace_paths(before, after)
        boundary_errors.extend(
            role_boundary_errors(
                request.effective_role_policy,
                external_changes,
                task_write_scope=request.task_write_scope,
            )
        )

    events = adapter.parse_events(process.stdout)
    summary = adapter.collect_telemetry(
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
        context_bytes=(
            _opencode_context_bytes(request, turn, worker_prompt)
            if request.backend == "opencode"
            else None
        ),
        requested_reasoning=request.execution_profile.requested_reasoning,
        effective_reasoning=request.execution_profile.effective_reasoning,
        exit_code=process.exit_code,
        timed_out=process.timed_out,
        guard_triggered=process.guard_triggered,
        prompt_bytes=len(worker_prompt.encode("utf-8")),
        events_sha256=hashlib.sha256(process.stdout.encode("utf-8")).hexdigest(),
        stderr_sha256=hashlib.sha256(process.stderr.encode("utf-8")).hexdigest(),
    )
    if sidecar_provenance is not None:
        _merge_sidecar_mcp_summary(summary["activity"]["mcp"], sidecar_provenance)
    write_summary(metrics_path(turn.events_path), summary)
    write_context_pack(
        request.session_dir / "turns" / f"{turn.number:03d}-{CONTEXT_PACK_FILENAME}",
        build_context_pack(request, turn.number, summary),
    )
    adapter.cleanup(request)
    stored_thread_id = turn.session.get("thread_id") if turn.session is not None else None
    event_thread_id = _single_thread_id(events.thread_ids)
    thread_id = stored_thread_id or event_thread_id
    thread_mismatch = bool(stored_thread_id and event_thread_id and stored_thread_id != event_thread_id)

    baseline_error = _post_run_baseline_error(request, trusted_baseline_digest)
    if baseline_error is not None:
        assert trusted_baseline is not None
        assert trusted_baseline_digest is not None
        _restore_workspace_baseline(request, trusted_baseline)
        persistent_thread_id = stored_thread_id or (
            event_thread_id if not thread_mismatch else None
        )
        if persistent_thread_id:
            session = _session_record(
                request,
                turn,
                thread_id=persistent_thread_id,
                status="correction_needed",
                process=process,
                change_actions=change_actions,
                workspace_snapshot=after_workspace,
                trusted_baseline=trusted_baseline,
                trusted_baseline_digest=trusted_baseline_digest,
            )
            _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="correction_needed",
            process=process,
            changed_paths=changed_paths,
            errors=[baseline_error],
            thread_id=persistent_thread_id,
        )
        return _turn_outcome(
            request,
            turn,
            status="correction_needed",
            thread_id=persistent_thread_id,
            errors=[baseline_error],
        ), 1

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
        backend=request.backend,
    )
    if failure_status is not None:
        persistent_thread_id = (
            stored_thread_id
            if request.backend == "opencode" and stored_thread_id
            else thread_id if not thread_mismatch else None
        )
        if persistent_thread_id:
            session = _session_record(
                request,
                turn,
                thread_id=persistent_thread_id,
                status=failure_status,
                process=process,
                change_actions=change_actions,
                workspace_snapshot=after_workspace,
                trusted_baseline=trusted_baseline,
                trusted_baseline_digest=trusted_baseline_digest,
            )
            _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status=failure_status,
            process=process,
            changed_paths=changed_paths,
            errors=failure_errors + boundary_errors,
            thread_id=thread_id,
        )
        return _turn_outcome(
            request,
            turn,
            status=failure_status,
            thread_id=thread_id,
            errors=failure_errors + boundary_errors,
        ), failure_code

    if (
        request.context_mode == "direct"
        and request.phase in {"draft", "feedback"}
        and not boundary_errors
    ):
        _, direct_errors = _run_direct_verification(request)
        if direct_errors:
            boundary_errors.extend(direct_errors)
        else:
            try:
                semantic = _direct_semantic_result(request)
                message = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
                atomic_write_text(turn.message_path, message + "\n")
                atomic_write_json(request.artifact_report_path, semantic)
            except (OSError, ValueError) as exc:
                boundary_errors.append(f"direct result report invalid: {exc}")

    if boundary_errors:
        if request.feedback_mode == "format-only":
            _restore_format_only_report(request, prior_artifact_report_bytes)
            for relative in changed_paths:
                if relative != report_relative and relative not in before_workspace:
                    path = contained_path(request.workspace, relative, label="format-only cleanup")
                    if path.is_file() or path.is_symlink():
                        path.unlink()
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="correction_needed",
            process=process,
            change_actions={},
            workspace_snapshot=before_workspace,
            trusted_baseline=trusted_baseline,
            trusted_baseline_digest=trusted_baseline_digest,
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="correction_needed",
            process=process,
            changed_paths=changed_paths,
            errors=boundary_errors,
            thread_id=thread_id,
        )
        return _turn_outcome(
            request,
            turn,
            status="correction_needed",
            thread_id=thread_id,
            errors=boundary_errors,
        ), 1

    if not message and request.phase not in {"draft", "feedback"}:
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="correction_needed",
            process=process,
            change_actions=change_actions,
            workspace_snapshot=after_workspace,
            trusted_baseline=trusted_baseline,
            trusted_baseline_digest=trusted_baseline_digest,
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="correction_needed",
            process=process,
            changed_paths=changed_paths,
            errors=[f"{_backend_name(request.backend)} returned no final agent message for this turn"],
            thread_id=thread_id,
        )
        return _turn_outcome(
            request,
            turn,
            status="correction_needed",
            thread_id=thread_id,
            errors=[f"{_backend_name(request.backend)} returned no final agent message for this turn"],
        ), 1

    if request.phase in {"draft", "feedback"}:
        draft, draft_errors = _artifact_report_from_file(request)
        if draft is None:
            if request.feedback_mode == "format-only":
                _restore_format_only_report(request, prior_artifact_report_bytes)
            session = _session_record(
                request,
                turn,
                thread_id=thread_id,
                status="correction_needed",
                process=process,
                change_actions=change_actions,
                workspace_snapshot=after_workspace,
                trusted_baseline=trusted_baseline,
                trusted_baseline_digest=trusted_baseline_digest,
            )
            _write_session(request.session_path, session)
            _write_turn_state(
                request,
                turn,
                status="correction_needed",
                process=process,
                changed_paths=changed_paths,
                errors=draft_errors,
                thread_id=thread_id,
            )
            return _turn_outcome(
                request,
                turn,
                status="correction_needed",
                thread_id=thread_id,
                errors=draft_errors,
            ), 1
        checkpoint_error = _complex_checkpoint_error(request, draft)
        if checkpoint_error is not None:
            session = _session_record(
                request, turn, thread_id=thread_id, status="correction_needed",
                process=process, change_actions=change_actions,
                workspace_snapshot=after_workspace, trusted_baseline=trusted_baseline,
                trusted_baseline_digest=trusted_baseline_digest,
            )
            _write_session(request.session_path, session)
            _write_turn_state(
                request, turn, status="correction_needed", process=process,
                changed_paths=changed_paths, errors=[checkpoint_error], thread_id=thread_id,
            )
            return _turn_outcome(
                request, turn, status="correction_needed", thread_id=thread_id,
                errors=[checkpoint_error],
            ), 1
        if request.context_mode != "direct":
            gate_error = _run_launcher_gate(request)
            if gate_error is not None:
                session = _session_record(
                    request, turn, thread_id=thread_id, status="correction_needed",
                    process=process, change_actions=change_actions,
                    workspace_snapshot=after_workspace, trusted_baseline=trusted_baseline,
                    trusted_baseline_digest=trusted_baseline_digest,
                )
                _write_session(request.session_path, session)
                _write_turn_state(
                    request, turn, status="correction_needed", process=process,
                    changed_paths=changed_paths, errors=[gate_error], thread_id=thread_id,
                )
                return _turn_outcome(
                    request, turn, status="correction_needed", thread_id=thread_id,
                    errors=[gate_error],
                ), 1
        _write_turn_state(
            request,
            turn,
            status="draft_ready",
            process=process,
            changed_paths=changed_paths,
            change_actions=(change_actions if request.backend == "opencode" else None),
            thread_id=thread_id,
        )
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="draft_ready",
            process=process,
            change_actions=change_actions,
            workspace_snapshot=after_workspace,
            trusted_baseline=trusted_baseline,
            trusted_baseline_digest=trusted_baseline_digest,
        )
        if request.execution_class == "complex":
            session["complex_checkpoint"] = draft["checkpoint"]
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
            process=process,
            change_actions=change_actions,
            workspace_snapshot=after_workspace,
            trusted_baseline=trusted_baseline,
            trusted_baseline_digest=trusted_baseline_digest,
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="correction_needed",
            process=process,
            changed_paths=changed_paths,
            errors=validation_errors,
            thread_id=thread_id,
        )
        return _turn_outcome(
            request,
            turn,
            status="correction_needed",
            thread_id=thread_id,
            errors=validation_errors,
        ), 1

    request.result_dir.mkdir(parents=True, exist_ok=True)
    prior_session_bytes = (
        request.session_path.read_bytes() if request.session_path.is_file() else None
    )
    _verify_execution_spec_immutable(request)
    try:
        atomic_write_json(request.result_path, result)
        _verify_execution_spec_immutable(request)
        session = _session_record(
            request,
            turn,
            thread_id=thread_id,
            status="finalized",
            process=process,
            change_actions=change_actions,
            workspace_snapshot=after_workspace,
            trusted_baseline=trusted_baseline,
            trusted_baseline_digest=trusted_baseline_digest,
            final_result_path=request.result_path.relative_to(request.control_root).as_posix(),
        )
        _write_session(request.session_path, session)
        _verify_execution_spec_immutable(request)
        _write_turn_state(
            request,
            turn,
            status="finalized",
            process=process,
            changed_paths=changed_paths,
            thread_id=thread_id,
        )
        _verify_execution_spec_immutable(request)
    except Exception:
        request.result_path.unlink(missing_ok=True)
        if prior_session_bytes is None:
            request.session_path.unlink(missing_ok=True)
        else:
            atomic_write_text(request.session_path, prior_session_bytes.decode("utf-8"))
            request.session_path.chmod(0o600)
        if prior_turn_state_bytes is None:
            turn.state_path.unlink(missing_ok=True)
        else:
            atomic_write_text(turn.state_path, prior_turn_state_bytes.decode("utf-8"))
            turn.state_path.chmod(0o600)
        raise
    return result, 0 if result["status"] in {"completed", "needs_review"} else 1


def _restore_format_only_report(
    request: SpawnRequest,
    prior: bytes | None,
) -> None:
    if prior is None:
        request.artifact_report_path.unlink(missing_ok=True)
    else:
        request.artifact_report_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(request.artifact_report_path, prior.decode("utf-8"))


def _seal_semantic_result(request: SpawnRequest) -> tuple[dict[str, Any], int]:
    lock_path = _acquire_attempt_lock(request)
    try:
        return _seal_semantic_result_locked(request)
    finally:
        lock_path.unlink(missing_ok=True)


def _acquire_attempt_lock(request: SpawnRequest) -> Path:
    lock_path = request.session_dir / "turn.lock"
    if lock_path.is_file() and not lock_path.is_symlink():
        try:
            owner = int(lock_path.read_text(encoding="ascii").strip())
            os.kill(owner, 0)
        except ProcessLookupError:
            lock_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
    except FileExistsError as exc:
        raise ValueError("another attempt turn is already in progress") from exc
    return lock_path


def _seal_semantic_result_locked(request: SpawnRequest) -> tuple[dict[str, Any], int]:
    turn = prepare_turn(request)
    _prepare_session_storage(request, initial=False, session=turn.session)
    _verify_execution_spec_immutable(request)
    _ensure_accepted_checkpoint(request, turn)
    assert turn.session is not None
    checkpoint = turn.session["accepted_checkpoint"]
    if request.execution_class == "complex":
        required = "source_focused_tests" if request.role == "developer" else "integration_evidence" if request.role == "tester" else "final_report"
        accepted_checkpoint = turn.session.get("complex_checkpoint")
        if accepted_checkpoint not in ({required, "development_gate"} if request.role == "developer" else {required}):
            raise ValueError(
                f"finalization requires accepted complex checkpoint {required!r}"
            )
    if request.gate_routing is not None:
        validate_current_gate_record(
            request.control_root,
            request.gate_routing["gate"],
            work_root=request.work_root if request.split_root else None,
            repo_id=request.repo_id,
        )
    baseline = _load_workspace_baseline(
        request,
        expected_digest=turn.session["workspace_baseline_sha256"],
    )
    current_snapshot = _snapshot_request_workspace(request)
    current_changed = changed_workspace_paths(baseline, current_snapshot)
    current_manifest = _accepted_product_paths(_merge_worker_change_manifest(
        baseline,
        {},
        _workspace_change_actions(baseline, current_snapshot, current_changed),
        current_snapshot,
    ))
    current_role_manifest = {
        path: item
        for path, item in current_manifest.items()
        if request.effective_role_policy.allows_change(path)
    }
    if (
        turn.session.get("last_status") != "draft_ready"
        or checkpoint.get("turn_number") != turn.session.get("turn_count")
        or _accepted_product_paths(turn.session.get("worker_change_manifest", {}))
        != checkpoint.get("accepted_paths")
        or current_role_manifest != checkpoint.get("accepted_paths")
    ):
        raise ValueError(
            "finalization requires the latest worker turn and change manifest to be accepted"
        )
    semantic, report_errors = _artifact_report_from_file(request, pin_evidence=False)
    if semantic is None:
        raise ValueError("accepted artifact report is invalid: " + "; ".join(report_errors))
    accepted_paths = checkpoint["accepted_paths"]
    file_changes = [
        {"path": path, "action": item["action"]}
        for path, item in sorted(accepted_paths.items())
    ]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = {
        "schema_version": "1.0",
        "result_id": f"res-{request.task_id.lower()}-{request.attempt_id}",
        "team_id": request.team_id,
        "task_id": request.task_id,
        "agent_role": request.role,
        "attempt_id": request.attempt_id,
        "status": request.result_status,
        "summary": semantic["summary"],
        "output": {
            "exit_code": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "duration_seconds": 0.0,
        },
        "file_changes": [] if request.role == "git_steward" else file_changes,
        "evidence": [
            {
                "type": "artifact",
                "artifact_ref": relative,
                "summary": "Worker-reported evidence artifact.",
            }
            for relative in semantic["evidence"]
        ] + ([{
            "type": "test_output",
            "artifact_ref": f"results/gates/{request.gate_routing['gate']}.json",
            "summary": f"Launcher-owned {request.gate_routing['gate']} gate record.",
        }] if (
            request.gate_routing is not None
            and f"results/gates/{request.gate_routing['gate']}.json" not in semantic["evidence"]
        ) else []),
        "requested_followups": [],
        "errors": [],
        "warnings": [],
        "limitations": semantic["limitations"],
        "produced_at": now,
    }
    validate_result(
        result,
        expected_task=request.task_id,
        expected_team=request.team_id,
        expected_attempt=request.attempt_id,
        expected_role=request.role,
        expected_status=request.result_status,
    )
    artifact_errors = _result_artifact_errors(request, result)
    policy_errors = _result_policy_errors(request, result)
    if artifact_errors or policy_errors:
        raise ValueError("deterministic final result validation failed: " + "; ".join(
            artifact_errors + policy_errors
        ))
    process = ProcessResult(0, "", "", 0.0)
    prior_session = request.session_path.read_bytes()
    prior_state = turn.state_path.read_bytes() if turn.state_path.is_file() else None
    created_result = False
    try:
        turn.message_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(turn.lead_prompt_path, request.prompt)
        atomic_write_json(turn.message_path, result)
        request.result_dir.mkdir(parents=True, exist_ok=True)
        create_json(request.result_path, result)
        created_result = True
        session = _session_record(
            request,
            turn,
            thread_id=turn.session["thread_id"],
            status="finalized",
            process=process,
            trusted_baseline=baseline,
            trusted_baseline_digest=turn.session["workspace_baseline_sha256"],
            workspace_snapshot=current_snapshot,
            final_result_path=request.result_path.relative_to(request.control_root).as_posix(),
        )
        _write_session(request.session_path, session)
        _write_turn_state(
            request,
            turn,
            status="finalized",
            process=process,
            changed_paths=(),
            thread_id=turn.session["thread_id"],
        )
    except Exception:
        if created_result:
            request.result_path.unlink(missing_ok=True)
        atomic_write_text(request.session_path, prior_session.decode("utf-8"))
        if prior_state is None:
            turn.state_path.unlink(missing_ok=True)
        else:
            atomic_write_text(turn.state_path, prior_state.decode("utf-8"))
        turn.message_path.unlink(missing_ok=True)
        turn.lead_prompt_path.unlink(missing_ok=True)
        raise
    return result, 0 if request.result_status in {"completed", "needs_review"} else 1


def build_command(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    executable: str | None = None,
) -> list[str]:
    if request.phase == "final":
        return []
    executable = executable or request.backend
    adapter = adapter_for(request.backend)
    if turn.is_initial:
        return adapter.start_draft(request, turn, executable)
    if request.phase == "final":
        return adapter.finalize(request, turn, executable)
    return adapter.resume_feedback(request, turn, executable)


def _configured_mcp_servers(config_path: Path) -> tuple[str, ...]:
    return tuple(sorted(_configured_mcp_server_table(config_path)))


def _configured_mcp_server_table(config_path: Path) -> dict[str, dict[str, Any]]:
    if not config_path.is_file():
        return {}
    try:
        value = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid Codex base configuration: {config_path}: {exc}") from exc
    servers = value.get("mcp_servers")
    if servers is None:
        return {}
    if not isinstance(servers, dict) or any(
        not isinstance(name, str) or not isinstance(config, dict)
        for name, config in servers.items()
    ):
        raise ValueError(f"Codex base mcp_servers must be a table: {config_path}")
    return servers


def _mcp_context_project(
    *,
    config_path: Path,
    control_root: Path,
    workspace: Path,
    repo_id: str | None,
    role: str,
    phase: str,
    effective_mcp_servers: tuple[str, ...],
    existing_session: dict[str, Any] | None,
) -> str | None:
    if CONTEXT_MCP_SERVER not in effective_mcp_servers or role == "leader":
        return None
    stored = None

    projects_root = _context_projects_root(config_path)
    if repo_id is None and workspace.parent != projects_root:
        raise ValueError(
            "codexteam-context worker workspace must be a direct child of its configured "
            f"projects root: workspace={workspace}, projects_root={projects_root}"
        )
    if repo_id is not None and control_root.parent != projects_root:
        raise ValueError(
            "codexteam-context control root must be a direct child of its configured "
            f"projects root: control_root={control_root}, projects_root={projects_root}"
        )
    project = validate_identifier(
        control_root.name if repo_id is not None else workspace.name,
        label="MCP context project",
    )
    project_entry = projects_root / project
    expected_root = control_root if repo_id is not None else workspace
    if (
        project_entry.is_symlink()
        or project_entry.resolve(strict=True) != expected_root
    ):
        raise ValueError(
            f"codexteam-context project is missing or unsafe: {project_entry}"
        )
    if stored is not None and stored != project:
        raise ValueError(
            "session MCP context project mismatch: "
            f"expected {project!r}, found {stored!r}"
        )
    return project


def _context_projects_root(config_path: Path) -> Path:
    servers = _configured_mcp_server_table(config_path)
    config = servers.get(CONTEXT_MCP_SERVER)
    if config is None:
        raise ValueError("codexteam-context is not configured")
    args = config.get("args")
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError(
            "codexteam-context configuration must expose --projects-root in its args"
        )
    roots: list[str] = []
    for index, argument in enumerate(args):
        if argument == "--projects-root" and index + 1 < len(args):
            roots.append(args[index + 1])
        elif argument.startswith("--projects-root="):
            roots.append(argument.split("=", 1)[1])
    if len(roots) != 1 or not roots[0]:
        raise ValueError(
            "codexteam-context configuration must contain exactly one --projects-root"
        )
    raw_root = Path(roots[0]).expanduser()
    if not raw_root.is_absolute():
        raise ValueError("codexteam-context --projects-root must be absolute")
    return ensure_existing_workspace(raw_root)


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
    for server, tools in request.effective_mcp_tools:
        arguments.extend(
            (
                "-c",
                (
                    f"mcp_servers.{server}.enabled_tools="
                    + json.dumps(list(tools), separators=(",", ":"))
                ),
            )
        )
    if request.mcp_context_project is not None:
        arguments.extend(
            (
                "-c",
                (
                    f"mcp_servers.{CONTEXT_MCP_SERVER}.env.{CONTEXT_PROJECT_ENV}="
                    + json.dumps(request.mcp_context_project)
                ),
            )
        )
    return arguments


def build_prompt(request: SpawnRequest, turn: TurnContext) -> str:
    if request.phase == "feedback":
        return (
            f"[CODEXTEAM FEEDBACK {request.feedback_mode}]\n"
            f"Task: {request.task_id}/{request.attempt_id}\n"
            f"Correction: {request.prompt.strip()}\n"
            "Preserve: accepted workspace changes.\n"
            f"Output: update {_artifact_report_reference(request)}.\n"
            + (
                "Use only edit or write on the artifact report; no other tools or file changes are allowed.\n"
                if request.feedback_mode == "format-only"
                else "Apply only the correction delta; do not rediscover context.\n"
            )
        )
    if request.phase == "final":
        return "Finalization is deterministic and does not invoke a provider.\n"

    skills = []
    prompt_skill_files = request.skill_files
    if (request.session_dir / GUIDANCE_MANIFEST_FILENAME).is_file():
        prompt_skill_files = _load_pinned_skill_files(request.session_dir)
    for path in prompt_skill_files:
        if request.backend == "opencode":
            skills.append(
                f"\n[PINNED GUIDANCE: {path}]\n"
                "Read the Purpose, Workflow, Validation, and Common Mistakes sections as needed.\n"
            )
        else:
            skills.append(f"\n[GUIDANCE: {path.name}]\n{path.read_text(encoding='utf-8').strip()}\n")
    handoff = build_handoff(request)
    context_binding = ""
    if request.mcp_context_project is not None:
        context_binding = (
            "The codexteam-context server is already bound to this workspace. "
            "Its tools omit the project argument; do not discover or supply one.\n"
        )
    gate_routing = _gate_routing(request)
    gate_note = ""
    if gate_routing is not None:
        gate_note = (
            f"The launcher owns the configured {gate_routing['gate']} gate on the "
            f"{gate_routing['execution_surface']} surface after validating this draft. "
            "Run only focused task checks; do not launch the configured gate.\n"
        )
    direct_context_note = _direct_context_instruction(request)
    return (
        "[CODEXTEAM HANDOFF]\n"
        f"{json.dumps(handoff, indent=2)}\n"
        f"Role policy: {request.role_policy.name} v{request.role_policy.schema_version} "
        f"({request.role_policy.digest[:12]}).\n"
        + context_binding
        + gate_note
        + direct_context_note
        + "You are the responsible AI for this task and logical attempt. Work only inside the assigned workspace "
        "and additional explicitly writable directories.\n"
        "Read relevant files before editing. Run task-relevant verification. Do not invent evidence.\n"
        + _draft_response_instruction(request, feedback=False)
        + "Do not emit result and do not close canonical project state; the Project Lead will review this draft.\n"
        + "".join(skills)
    )


def _artifact_report_reference(request: SpawnRequest) -> str:
    if request.split_root:
        return str(request.artifact_report_path)
    return request.artifact_report_path.relative_to(request.work_root).as_posix()


def _direct_context_instruction(request: SpawnRequest) -> str:
    if request.context_mode != "direct":
        return ""
    contract = _load_handoff_contract(request.session_dir)
    sections = [
        f"[DIRECT CONTEXT: {item['path']}:{item['start']}-{item['end']}]\n{item['content']}"
        for item in contract.get("direct_context", [])
    ]
    return (
        "Direct context is complete and authoritative. Discovery and shell tools are disabled. "
        "Edit only scoped paths, write the required report, and return a short completion sentence; "
        "the launcher owns verification and result construction.\n\n"
        + "\n".join(sections)
        + "\n"
    )


def build_handoff(request: SpawnRequest) -> dict[str, Any]:
    if request.execution_spec is None:
        raise ValueError("handoff requires an execution specification")
    handoff = {
        "schema_version": "1.0",
        "handoff_id": f"handoff-{request.task_id.lower()}-{request.attempt_id}",
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "execution_spec": execution_spec_reference(request.execution_spec),
        "role_policy": {
            "name": request.role_policy.name,
            "schema_version": request.role_policy.schema_version,
            "digest": request.role_policy.digest,
        },
        "workspace_root": str(request.workspace),
        "task_context": {
            "prompt": request.prompt,
            "guidance_files": [path.name for path in request.skill_files],
            "context_mode": request.context_mode,
            "execution_class": request.execution_class,
        },
        "instruction_bundle": {
            "digest": request.guidance_digest,
            "files": [path.name for path in request.skill_files],
        },
        "constraints": {
            "workspace_write": str(request.workspace),
            "additional_writable_directories": [str(path) for path in request.worker_add_dirs],
            "trust_parent_sandbox": request.trust_parent_sandbox,
            "timeout_seconds": request.timeout_seconds,
            "execution_class": request.execution_class,
            "gate_routing": _gate_routing(request),
            "draft_format": request.draft_format,
            "task_write_scope": (
                list(request.task_write_scope)
                if request.task_write_scope is not None
                else None
            ),
        },
        "completion_criteria": [
            "Run task-relevant verification.",
            "Return a draft for Project Lead review.",
            "Do not emit a final result or close project state in the draft turn.",
        ],
    }
    validate_handoff(handoff)
    return handoff


def _draft_response_instruction(request: SpawnRequest, *, feedback: bool) -> str:
    checkpoint = _required_complex_checkpoint(request)
    checkpoint_text = (
        f" For this complex stage set checkpoint={checkpoint!r}."
        if checkpoint is not None else ""
    )
    return (
        f"Write the artifact report at {_artifact_report_reference(request)} "
        "as one JSON object with version=1, non-empty summary, evidence path strings, and limitations strings. "
        "Unknown fields are allowed. Terminal output is diagnostic only."
        + checkpoint_text + "\n"
    )


def _gate_routing(request: SpawnRequest) -> dict[str, Any] | None:
    if request.gate_routing is None:
        return None
    return {
        **request.gate_routing,
        "worker_may_execute": False,
    }


def _resolve_gate_routing(workspace: Path, role: str) -> dict[str, str] | None:
    gate = "development" if role == "developer" else (
        "integration" if role == "tester" else None
    )
    if gate is None:
        return None
    try:
        config = load_gate_config(workspace)
    except (FileNotFoundError, GateConfigError, OSError, ValueError):
        return None
    surface = config.development_surface if gate == "development" else config.integration_surface
    return {"gate": gate, "execution_surface": surface}


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
        for name in tuple(directory_names):
            path = root / name
            if path.is_symlink():
                relative = path.relative_to(workspace).as_posix()
                snapshot[relative] = "symlink:" + os.readlink(path)
                directory_names.remove(name)
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


def _snapshot_request_workspace(request: SpawnRequest) -> dict[str, str]:
    if not request.split_root:
        return snapshot_workspace(request.workspace)
    completed = subprocess.run(
        [
            "git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
            "--", request.git_prefix,
        ],
        cwd=request.git_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"Git-visible workspace scan failed: {detail}")
    snapshot: dict[str, str] = {}
    prefix = "" if request.git_prefix == "." else request.git_prefix + "/"
    for git_relative in completed.stdout.split("\0"):
        if not git_relative:
            continue
        if prefix and not git_relative.startswith(prefix):
            continue
        relative = git_relative[len(prefix):]
        path = request.work_root / relative
        if path.is_dir():
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


def _workspace_change_actions(
    before: dict[str, str],
    after: dict[str, str],
    changed_paths: tuple[str, ...],
) -> dict[str, str]:
    return {
        path: (
            "created"
            if path not in before
            else "deleted"
            if path not in after
            else "modified"
        )
        for path in changed_paths
    }


def role_boundary_errors(
    policy: RolePolicy,
    changed_paths: tuple[str, ...],
    *,
    task_write_scope: tuple[str, ...] | None = None,
) -> list[str]:
    errors = [
        f"role policy {policy.name} does not allow changing {path}"
        for path in changed_paths
        if not policy.allows_change(path)
    ]
    if task_write_scope is not None:
        errors.extend(
            f"task write scope does not allow changing {path}"
            for path in changed_paths
            if not any(fnmatchcase(path, pattern) for pattern in task_write_scope)
        )
    return errors


def _run_launcher_gate(request: SpawnRequest) -> str | None:
    if request.gate_routing is None:
        return None
    gate = request.gate_routing["gate"]
    try:
        record = run_gate(
            request.control_root,
            gate,
            execution_surface=request.gate_routing["execution_surface"],
            work_root=request.work_root if request.split_root else None,
            repo_id=request.repo_id,
        )
    except (GateConfigError, OSError, ValueError) as exc:
        return f"launcher-owned {gate} gate failed to run: {exc}"
    if record.get("status") != "passed":
        return f"launcher-owned {gate} gate failed; see results/gates/{gate}.json"
    return None


def _run_direct_verification(request: SpawnRequest) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    environment = {
        key: value for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "WINDIR"}
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    gate_record: dict[str, Any] | None = None
    try:
        if not request.gate_routing or request.gate_routing["execution_surface"] != "worker":
            raise ValueError("direct verification requires a worker-surface gate")
        gate = request.gate_routing["gate"]
        prefix = tuple(_direct_verification_command(request.workspace, ()))
        gate_record = run_gate(
            request.control_root,
            gate,
            execution_surface="worker",
            command_prefix=prefix,
            environment=environment,
            work_root=(request.work_root if request.split_root else None),
            repo_id=request.repo_id,
        )
        records = list(gate_record["commands"])
        if gate_record.get("status") != "passed":
            errors.append(f"{gate} gate failed")
    except (OSError, GateConfigError, ValueError) as exc:
        errors.append(f"verification infrastructure failed: {exc}")
    check_path = contained_path(
        request.workspace,
        f"{CHECK_RECORD_ROOT}/{request.task_id}-{request.attempt_id}.json",
        label="direct verification record",
    )
    atomic_write_json(check_path, {
        "schema_version": "1.0",
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "status": "passed" if not errors else "failed",
        "commands": records,
        "gate": (
            {
                "name": request.gate_routing["gate"],
                "artifact_ref": gate_record_path(
                    request.control_root, request.gate_routing["gate"]
                ).relative_to(request.control_root).as_posix(),
                "status": gate_record.get("status") if gate_record else "not_run",
            }
            if request.gate_routing and request.gate_routing["execution_surface"] == "worker"
            else None
        ),
    })
    return records, errors


def _direct_semantic_result(request: SpawnRequest) -> dict[str, Any]:
    if request.result_report is None:
        raise ValueError("direct result report is missing")
    report = contained_path(request.workspace, request.result_report, label="result report")
    if report.is_symlink() or not report.is_file():
        raise ValueError(f"result report is missing or unsafe: {request.result_report}")
    content = report.read_bytes()
    if not content or len(content) > 64 * 1024:
        raise ValueError("result report must contain 1 to 65536 bytes")
    try:
        report_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("result report must be UTF-8") from exc
    dispositions = re.findall(
        r"^Disposition:\s*(ready_for_review|blocked)\s*$",
        report_text,
        re.MULTILINE,
    )
    if dispositions != ["ready_for_review"]:
        raise ValueError(
            "result report must contain exactly one 'Disposition: ready_for_review' line"
        )
    check_ref = f"{CHECK_RECORD_ROOT}/{request.task_id}-{request.attempt_id}.json"
    evidence = [{
        "type": "artifact",
        "artifact_ref": request.result_report,
        "summary": "Worker task report.",
    }, {
        "type": "test_output",
        "artifact_ref": check_ref,
        "summary": "Launcher-owned focused verification record.",
    }]
    if request.gate_routing and request.gate_routing["execution_surface"] == "worker":
        gate_ref = gate_record_path(
            request.control_root, request.gate_routing["gate"]
        ).relative_to(request.control_root).as_posix()
        evidence.append({
            "type": "test_output",
            "artifact_ref": gate_ref,
            "summary": f"Launcher-owned {request.gate_routing['gate']} gate record.",
        })
    semantic = {
        "version": 1,
        "summary": f"{request.role} completed {request.task_id}; see {request.result_report}.",
        "evidence": [item["artifact_ref"] for item in evidence],
        "limitations": ["See the task report for detailed limitations."],
    }
    atomic_write_json(request.artifact_report_path, semantic)
    return semantic


def _direct_verification_command(
    workspace: Path,
    command: tuple[str, ...],
) -> list[str]:
    executable = shutil.which("bwrap")
    if executable is None:
        raise ValueError("direct verification requires bubblewrap")
    return [
        executable,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--ro-bind", "/", "/",
        "--tmpfs", "/tmp",
        "--proc", "/proc",
        "--dev", "/dev",
        "--chdir", str(workspace),
        "--",
        *command,
    ]


def _workspace_scan_excluded(relative: str) -> bool:
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in WORKSPACE_SCAN_EXCLUDES
    )


def _acceptance_path_excluded(relative: str) -> bool:
    if re.fullmatch(r"results/reports/T[0-9]{3,6}-[A-Za-z0-9._-]+\.json", relative):
        return True
    if relative == CHECK_RECORD_ROOT or relative.startswith(CHECK_RECORD_ROOT + "/"):
        return True
    if relative == "results/gates" or relative.startswith("results/gates/"):
        return True
    if re.fullmatch(r"results/T[0-9]{3,6}-att-[0-9]{3}\.json", relative):
        return True
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in ACCEPTANCE_PATH_EXCLUDES
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
    debug_stream: str = "off",
) -> ProcessResult:
    return _run_streaming_process(
        command,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        env=env,
        cwd=cwd,
        events_path=events_path,
        stderr_path=stderr_path,
        run_guard=run_guard,
        debug_stream=debug_stream,
    )


def _run_streaming_process(
    command: list[str],
    *,
    prompt: str,
    timeout_seconds: int,
    env: dict[str, str],
    cwd: Path | None,
    events_path: Path | None,
    stderr_path: Path | None,
    run_guard: bool,
    debug_stream: str,
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

    guard = ExactFailedRepeatGuard() if run_guard else None
    guard_reason: str | None = None
    guard_deadline: float | None = None
    force_killed = False
    timed_out = False
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    completed_streams: set[str] = set()
    descendants: set[int] = set()
    process_exit_at: float | None = None
    descendants_killed = False
    event_count = 0
    model_step_count = 0
    last_tool: str | None = None
    last_progress_at = started
    event_handle = _open_live_stream(events_path)
    error_handle = _open_live_stream(stderr_path)
    try:
        while len(completed_streams) < 2:
            now = time.monotonic()
            descendants.update(_process_descendants(process.pid))
            if process.poll() is not None and process_exit_at is None:
                process_exit_at = now
                _signal_process_group(process, signal.SIGTERM)
                _signal_processes(descendants, signal.SIGTERM)
            if process_exit_at is not None:
                elapsed_after_exit = now - process_exit_at
                if (
                    not descendants_killed
                    and elapsed_after_exit >= DESCENDANT_TERM_GRACE_SECONDS
                ):
                    _signal_process_group(process, signal.SIGKILL)
                    _signal_processes(descendants, signal.SIGKILL)
                    descendants_killed = True
                if elapsed_after_exit >= POST_EXIT_DRAIN_SECONDS:
                    break
            if now - last_progress_at >= PROGRESS_INTERVAL_SECONDS:
                print(
                    "Worker progress: "
                    f"{event_count} events, {model_step_count} model steps, "
                    f"last tool {last_tool or '-'}, {int(now - started)}s elapsed",
                    file=sys.stderr,
                    flush=True,
                )
                last_progress_at = now
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
                event_type, tool = _safe_progress_event(chunk)
                if event_type is not None:
                    event_count += 1
                    model_step_count += int(event_type == "step_finish")
                if tool is not None:
                    last_tool = tool
                _print_debug_event(
                    chunk,
                    debug_stream,
                    workspace=cwd,
                    step_ordinal=model_step_count,
                )
                if guard is not None and guard_reason is None and not timed_out:
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
        _signal_processes(descendants, signal.SIGKILL)
        process.wait()
        for reader in readers:
            reader.join(timeout=1.0)

    exit_code = 124 if timed_out else process.returncode
    if debug_stream == "activity":
        process_status = (
            "timed_out" if timed_out else
            "interrupted" if guard_reason is not None else
            "completed" if exit_code == 0 else
            "failed"
        )
        print(
            f"[worker process] {process_status}\n"
            f"  exit: {exit_code}\n"
            f"  duration: {_debug_duration_ms((time.monotonic() - started) * 1000)}",
            file=sys.stderr,
            flush=True,
        )
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


def _safe_progress_event(line: str) -> tuple[str | None, str | None]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(event, dict):
        return None, None
    event_type = event.get("type")
    safe_event = event_type if event_type in SAFE_PROGRESS_EVENT_TYPES else "unknown"
    tool: str | None = None
    if event_type == "tool_use":
        part = event.get("part")
        raw_tool = part.get("tool") if isinstance(part, dict) else None
        tool = raw_tool if raw_tool in SAFE_PROGRESS_TOOLS else "unknown"
    return safe_event, tool


def _print_debug_event(
    line: str,
    mode: str,
    *,
    workspace: Path | None = None,
    step_ordinal: int = 0,
) -> None:
    if mode == "off":
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict):
        return
    event_type = event.get("type")
    part = event.get("part")
    if event_type == "text" and isinstance(part, dict):
        text = part.get("text")
        if isinstance(text, str) and text:
            print(
                f"[worker assistant]\n{_debug_terminal_text(text)}",
                file=sys.stderr,
                flush=True,
            )
        return
    if event_type == "error":
        print("[worker error] provider error reported; see private JSONL", file=sys.stderr, flush=True)
        return
    if mode != "activity" or not isinstance(part, dict):
        return
    if event_type == "tool_use":
        print(
            "\n".join(_activity_tool_lines(part, workspace)),
            file=sys.stderr,
            flush=True,
        )
    elif event_type == "step_finish":
        print(
            "\n".join(_activity_step_lines(part, step_ordinal)),
            file=sys.stderr,
            flush=True,
        )


def _activity_tool_lines(part: dict[str, Any], workspace: Path | None) -> list[str]:
    tool_name = _debug_label(part.get("tool"))
    state = part.get("state")
    state = state if isinstance(state, dict) else {}
    status_name = _debug_label(state.get("status"))
    inputs = state.get("input")
    inputs = inputs if isinstance(inputs, dict) else {}
    metadata = state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    lines = [f"[worker tool] {tool_name} {status_name}"]

    if tool_name == "read":
        _append_activity_path(lines, "target", inputs.get("filePath"), workspace)
        _append_optional(lines, "offset", inputs.get("offset"))
        _append_optional(lines, "limit", inputs.get("limit"))
    elif tool_name == "grep":
        _append_redacted(lines, "query", inputs.get("pattern"))
        _append_activity_path(lines, "path", inputs.get("path"), workspace)
        _append_redacted(lines, "include", inputs.get("include"))
    elif tool_name == "glob":
        _append_redacted(lines, "pattern", inputs.get("pattern"))
        _append_activity_path(lines, "path", inputs.get("path"), workspace)
    elif tool_name == "bash":
        command = inputs.get("command")
        if isinstance(command, str) and command:
            if workspace is not None:
                command = command.replace(str(workspace.resolve(strict=False)), ".")
            _append_redacted(lines, "command", command)
        _append_activity_path(lines, "workdir", inputs.get("workdir"), workspace)
    elif tool_name in {"write", "edit"}:
        path_value = inputs.get("filePath") or inputs.get("path")
        _append_activity_path(lines, "target", path_value, workspace)
        if tool_name == "write":
            _append_content_size(lines, "content", inputs.get("content"))
        else:
            _append_content_size(lines, "old text", inputs.get("oldString"))
            _append_content_size(lines, "new text", inputs.get("newString"))
    elif tool_name == "apply_patch":
        patch = inputs.get("patchText")
        patch = patch if isinstance(patch, str) else ""
        paths = re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch, re.MULTILINE)
        if paths:
            rendered = ", ".join(_activity_path(path, workspace) for path in paths[:8])
            lines.append(f"  targets: {rendered}")
        lines.append(f"  actions: {len(paths)}")
    elif tool_name == "webfetch":
        _append_redacted(lines, "url", inputs.get("url"))
        _append_redacted(lines, "format", inputs.get("format"))
    elif tool_name == "skill":
        _append_redacted(lines, "skill", inputs.get("name"))
    elif tool_name == "task":
        _append_redacted(lines, "agent", inputs.get("subagent_type"))
    elif tool_name == "question":
        questions = inputs.get("questions")
        lines.append(f"  questions: {len(questions) if isinstance(questions, list) else 0}")
    elif tool_name == "todowrite":
        todos = inputs.get("todos")
        lines.append(f"  items: {len(todos) if isinstance(todos, list) else 0}")
    else:
        safe_keys = sorted(
            str(key) for key in inputs
            if str(key).casefold() not in {
                "content", "output", "patch", "patchtext", "prompt", "text"
            }
        )
        if safe_keys:
            lines.append(f"  input fields: {', '.join(safe_keys[:12])}")

    duration = _activity_duration_ms(state.get("time"))
    if duration is not None:
        lines.append(f"  duration: {_debug_duration_ms(duration)}")
    exit_code = next(
        (
            metadata.get(key)
            for key in ("exit", "exit_code", "exitCode")
            if metadata.get(key) is not None
        ),
        None,
    )
    _append_optional(lines, "exit", exit_code)
    count = metadata.get("count")
    if isinstance(count, int) and not isinstance(count, bool):
        lines.append(f"  matches: {count}")
    output_bytes = _activity_output_bytes(state, metadata)
    result_parts = [f"{output_bytes} bytes"]
    if metadata.get("truncated") is True:
        result_parts.append("truncated")
    elif output_bytes:
        result_parts.append("complete")
    lines.append(f"  result: {', '.join(result_parts)}")
    if status_name in {"error", "failed"}:
        lines.append("  error: provider error reported; see private JSONL")
    return lines


def _activity_step_lines(part: dict[str, Any], ordinal: int) -> list[str]:
    lines = [f"[worker step] {ordinal} completed"]
    _append_redacted(lines, "reason", part.get("reason"))
    tokens = part.get("tokens")
    if isinstance(tokens, dict):
        cache = tokens.get("cache")
        cache = cache if isinstance(cache, dict) else {}
        input_tokens = sum(
            value for value in (
                _debug_nonnegative_int(tokens.get("input")),
                _debug_nonnegative_int(cache.get("read")),
                _debug_nonnegative_int(cache.get("write")),
            )
        )
        output_tokens = sum(
            value for value in (
                _debug_nonnegative_int(tokens.get("output")),
                _debug_nonnegative_int(tokens.get("reasoning")),
            )
        )
        lines.append(f"  input: {input_tokens:,} tokens")
        lines.append(f"  output: {output_tokens:,} tokens")
    return lines


def _append_activity_path(
    lines: list[str], label: str, value: Any, workspace: Path | None
) -> None:
    if isinstance(value, str) and value:
        lines.append(f"  {label}: {_activity_path(value, workspace)}")


def _activity_path(value: str, workspace: Path | None) -> str:
    safe = _debug_terminal_text(value)
    candidate = Path(safe).expanduser()
    if workspace is not None:
        root = workspace.resolve(strict=False)
        resolved = (
            candidate.resolve(strict=False)
            if candidate.is_absolute()
            else (root / candidate).resolve(strict=False)
        )
        try:
            return resolved.relative_to(root).as_posix() or "."
        except ValueError:
            return f"<outside-workspace>/{resolved.name or '?'}"
    return safe[:512]


def _append_redacted(lines: list[str], label: str, value: Any) -> None:
    if isinstance(value, str) and value:
        lines.append(f"  {label}: {_debug_preview(value)}")


def _append_optional(lines: list[str], label: str, value: Any) -> None:
    if value is not None and value != "":
        lines.append(f"  {label}: {_debug_label(str(value))}")


def _append_content_size(lines: list[str], label: str, value: Any) -> None:
    if isinstance(value, str):
        lines.append(f"  {label}: {len(value.encode('utf-8'))} bytes")


def _activity_duration_ms(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return max(0.0, float(end) - float(start))


def _debug_duration_ms(value: float) -> str:
    if value >= 1000:
        return f"{value / 1000:.3f}s"
    return f"{int(round(value))}ms"


def _debug_serialized_bytes(value: Any) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    try:
        return len(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            .encode("utf-8")
        )
    except (TypeError, ValueError):
        return 0


def _activity_output_bytes(state: dict[str, Any], metadata: dict[str, Any]) -> int:
    output = state.get("output")
    if isinstance(output, str):
        return len(output.encode("utf-8"))
    error = state.get("error")
    if isinstance(error, str):
        return len(error.encode("utf-8"))
    for key in ("output_bytes", "outputBytes"):
        value = metadata.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    metadata_output = metadata.get("output")
    if isinstance(metadata_output, str):
        return len(metadata_output.encode("utf-8"))
    return sum(
        len(metadata[key].encode("utf-8"))
        for key in ("stdout", "stderr")
        if isinstance(metadata.get(key), str)
    )


def _debug_nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _debug_error_text(event: dict[str, Any]) -> str:
    value = event.get("error") or event.get("message") or "OpenCode reported an error"
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            return data["message"]
        if isinstance(value.get("message"), str):
            return value["message"]
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _debug_preview(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    redacted = re.sub(r"(?i)Bearer\s+[^\s,;&'\"]+", "Bearer <redacted>", value)
    redacted = re.sub(
        r'(?i)("(?:token|secret|password|passwd|api[_-]?key|authorization|credential)"'
        r'\s*:\s*")([^"]*)(")',
        lambda match: f"{match.group(1)}<redacted>{match.group(3)}",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|credential)"
        r"(\s*[=:]\s*|\s+)(?:'[^']*'|\"[^\"]*\"|[^\s,;&]+)",
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        redacted,
    )
    safe = _debug_terminal_text(redacted)
    if len(safe) <= DEBUG_PREVIEW_CHARS:
        return safe
    return safe[:DEBUG_PREVIEW_CHARS] + "...[truncated]"


def _debug_label(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "unknown"
    return _debug_terminal_text(value)[:64] or "unknown"


def _debug_terminal_text(value: str) -> str:
    return "".join(
        character
        for character in value
        if character in {"\n", "\t"}
        or ord(character) >= 160
        or 32 <= ord(character) < 127
    )


def _signal_process_group(process: subprocess.Popen[str], target_signal: int) -> None:
    try:
        os.killpg(process.pid, target_signal)
    except ProcessLookupError:
        return


def _signal_processes(process_ids: set[int], target_signal: int) -> None:
    for process_id in process_ids:
        try:
            os.kill(process_id, target_signal)
        except ProcessLookupError:
            continue


def _process_descendants(process_id: int) -> set[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        return set()
    children: dict[int, set[int]] = {}
    for status_path in proc.glob("[0-9]*/status"):
        try:
            status = status_path.read_text(encoding="utf-8")
            child_id = int(status_path.parent.name)
            match = re.search(r"^PPid:\s+(\d+)$", status, re.MULTILINE)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if match is not None:
            children.setdefault(int(match.group(1)), set()).add(child_id)
    descendants: set[int] = set()
    pending = [process_id]
    while pending:
        for child_id in children.get(pending.pop(), set()):
            if child_id not in descendants:
                descendants.add(child_id)
                pending.append(child_id)
    return descendants


def parse_codex_events(text: str) -> BackendEventSummary:
    return adapter_for("codex").parse_events(text)


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
    parser.add_argument("--backend", choices=("codex", "opencode"))
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument(
        "--agent-spec",
        help="Select one technical specialization only when creating a new attempt",
    )
    parser.add_argument("--profile", help="Select a curated backend-scoped profile on draft")
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        help="Select a reasoning request supported by the curated profile",
    )
    parser.add_argument("--team", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--role", required=True, choices=tuple(sorted(AGENT_ROLES)))
    parser.add_argument("--workspace")
    parser.add_argument("--control-root")
    parser.add_argument("--work-root")
    parser.add_argument("--repo-id")
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
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Override the handoff-derived timeout (small=600s, complex=1200s)",
    )
    parser.add_argument(
        "--run-guard",
        action="store_true",
        help=(
            "Interrupt repeated failures, oversized command output, or broad discovery "
            "after bounded context, preserving the resumable thread"
        ),
    )
    parser.add_argument(
        "--debug-stream",
        choices=DEBUG_STREAM_MODES,
        default=None,
        help=(
            "Stream OpenCode assistant text, or assistant text plus bounded tool activity, "
            "to launcher stderr; defaults to activity for OpenCode and off for other backends; "
            "content may contain sensitive project data"
        ),
    )
    parser.add_argument("--result-dir", default="results")
    parser.add_argument(
        "--feedback-mode",
        choices=("revision", "format-only"),
        help="Select compact revision or tool-free artifact-format correction",
    )
    parser.add_argument(
        "--result-status",
        choices=("completed", "failed", "partial", "blocked", "needs_review"),
        default=None,
        help="Select the Lead-owned terminal result status on finalization",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _require_canonical_draft_handoff(args)
        request = prepare_request(args)
        if request.phase != "final":
            require_execution_backend_enabled(request.backend)
        turn = prepare_turn(request)
        if args.dry_run:
            details = {
                "phase": request.phase,
                "draft_format": request.draft_format,
                "draft_format_pinned": request.draft_format_pinned,
                "draft_format_path": str(request.draft_format_path),
                "execution_spec": request.execution_spec,
                "execution_spec_path": str(request.execution_spec_path),
                "command": build_command(request, turn),
                "profile_file": (
                    str(request.profile_file) if request.backend == "codex" else None
                ),
                "role_policy": request.role_policy.name,
                "role_policy_version": request.role_policy.schema_version,
                "role_policy_digest": request.role_policy.digest,
                "role_policy_source": str(request.role_policy.source_path),
                "sandbox_mode": request.effective_role_policy.sandbox_mode,
                "agent_spec": request.agent_spec.reference() if request.agent_spec is not None else None,
                "effective_policy_digest": effective_policy_digest(request.effective_role_policy),
                "mcp_allowed_servers": list(request.effective_role_policy.mcp_servers),
                "mcp_effective_servers": list(request.effective_mcp_servers),
                "mcp_missing_servers": list(request.missing_mcp_servers),
                "mcp_allowed_tools": {
                    server: list(tools)
                    for server, tools in request.effective_role_policy.mcp_tools
                },
                "mcp_effective_tools": {
                    server: list(tools)
                    for server, tools in request.effective_mcp_tools
                },
                "mcp_context_project": request.mcp_context_project,
                "reasoning_effort": _session_reasoning_effort(request, turn.session),
                "reasoning_effort_override": request.reasoning_effort_override,
                "workspace": str(request.workspace),
                "trust_parent_sandbox": request.trust_parent_sandbox,
                "run_guard": request.run_guard,
                "session_path": str(request.session_path),
                "lead_prompt_path": str(turn.lead_prompt_path),
                "turn_path": str(turn.message_path),
                "stderr_path": str(turn.stderr_path),
                "result_path": str(request.result_path),
                "result_status": request.result_status,
                "skills": [str(path) for path in request.skill_files],
            }
            if request.split_root:
                details.update({
                    "control_root": str(request.control_root),
                    "work_root": str(request.work_root),
                    "git_root": str(request.git_root),
                    "git_prefix": request.git_prefix,
                    "repo_id": request.repo_id,
                })
            if request.backend == "opencode":
                details.update(
                    {
                        "backend": request.backend,
                        "resolved_model": request.model,
                        "backend_config_path": str(request.backend_config_path),
                        "backend_config_digest": request.backend_config_digest,
                        "debug_stream": request.debug_stream,
                        "reasoning_effort": None,
                    }
                )
            print(
                json.dumps(
                    details,
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


def _require_canonical_draft_handoff(args: argparse.Namespace) -> None:
    if args.phase != "draft" or args.dry_run:
        return
    if args.prompt_file is None or args.prompt is not None:
        raise ValueError(
            "live drafts require the canonical management/tasks/<task>.md handoff"
        )
    root_value = args.workspace or args.control_root
    if root_value is None:
        raise ValueError("live drafts require a workspace or control root")
    workspace = ensure_existing_workspace(root_value)
    task_id = normalize_task_id(args.task)
    expected = contained_path(
        workspace,
        f"management/tasks/{task_id}.md",
        label="canonical task handoff",
    )
    supplied = Path(args.prompt_file).expanduser()
    if supplied.is_symlink():
        raise ValueError("canonical task handoff must not be a symlink")
    try:
        supplied = supplied.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"canonical task handoff is missing: {expected}") from exc
    if supplied != expected or not supplied.is_file():
        raise ValueError(
            f"live drafts require the exact canonical task handoff: {expected}"
        )


def _read_prompt(
    prompt_file: str | None,
    prompt: str | None,
    workspace: Path,
) -> tuple[str, str | None, str]:
    if prompt_file is not None:
        source = Path(prompt_file).expanduser().resolve(strict=True)
        content = source.read_text(encoding="utf-8")
        try:
            source_path = source.relative_to(workspace).as_posix()
        except ValueError:
            source_path = str(source)
    else:
        content = prompt or ""
        source_path = None
    if not content.strip():
        raise ValueError("prompt cannot be empty")
    return content, source_path, hashlib.sha256(content.encode("utf-8")).hexdigest()


def _task_handoff_metadata(
    prompt: str,
    source_path: str | None,
    role: str,
) -> Any:
    if source_path is None or not re.fullmatch(r"management/tasks/T[0-9]{3,6}\.md", source_path):
        return parse_task_handoff_metadata("")
    try:
        metadata = parse_task_handoff_metadata(prompt)
    except TaskDocumentError as exc:
        raise ValueError(str(exc)) from exc
    if not metadata.task_write_scope and role not in {"git_steward"}:
        raise ValueError("canonical task handoff requires a non-empty task write scope")
    if metadata.context_mode is None:
        metadata = replace(metadata, context_mode="bounded-mcp")
    return metadata


def _handoff_contract_path(session_dir: Path) -> Path:
    return session_dir / HANDOFF_CONTRACT_FILENAME


def _direct_context_pack(
    workspace: Path,
    targets: tuple[tuple[str, int, int], ...],
) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    sections: list[str] = []
    total_bytes = 0
    for relative, start, end in targets:
        path = contained_path(workspace, relative, label="direct context target")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"direct context target is missing or unsafe: {relative}")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError(f"direct context target is not UTF-8: {relative}") from exc
        if end > len(lines):
            raise ValueError(
                f"direct context range exceeds {relative}: requested {start}-{end}, file has {len(lines)} lines"
            )
        excerpt = "\n".join(lines[start - 1:end]) + "\n"
        total_bytes += len(excerpt.encode("utf-8"))
        if total_bytes > 64 * 1024:
            raise ValueError("direct context exceeds 65536 bytes")
        records.append({
            "path": relative,
            "start": start,
            "end": end,
            "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "content": excerpt,
        })
        sections.append(f"[DIRECT CONTEXT: {relative}:{start}-{end}]\n{excerpt}")
    return records, "\n".join(sections)


def _build_handoff_contract(request: SpawnRequest) -> dict[str, Any]:
    direct_records: list[dict[str, Any]] = []
    if request.context_mode == "direct":
        if request.result_report is None:
            raise ValueError("direct context requires a result report")
        report_path = contained_path(
            request.workspace, request.result_report, label="result report"
        )
        report_relative = report_path.relative_to(request.workspace).as_posix()
        if request.task_write_scope is None or not any(
            fnmatchcase(report_relative, pattern) for pattern in request.task_write_scope
        ):
            raise ValueError("Result Report is outside Task Write Scope")
        for pattern in request.task_write_scope:
            if any(character in pattern for character in "*?["):
                raise ValueError(
                    f"direct Task Write Scope entries must be literal files: {pattern}"
                )
            if not request.effective_role_policy.allows_change(pattern):
                raise ValueError(
                    f"direct Task Write Scope exceeds role policy: {pattern}"
                )
            if pattern.startswith(".codexteam/"):
                raise ValueError("direct Task Write Scope cannot include private runtime state")
        for system_relative in (
            f"{CHECK_RECORD_ROOT}/{request.task_id}-{request.attempt_id}.json",
            request.result_path.relative_to(request.workspace).as_posix(),
        ):
            if any(
                fnmatchcase(system_relative, pattern) for pattern in request.task_write_scope
            ):
                raise ValueError(
                    f"system-owned path must not be in Task Write Scope: {system_relative}"
                )
        direct_records, _ = _direct_context_pack(request.workspace, request.direct_context)
        for command in request.verification_commands:
            executable = Path(command[0]).name
            if executable not in DIRECT_VERIFICATION_EXECUTABLES:
                raise ValueError(
                    f"direct verification executable is not allowed: {command[0]}"
                )
        gate_config = load_gate_config(request.control_root)
        approved_commands = list(gate_config.development_commands)
        if request.role == "tester":
            approved_commands.extend(gate_config.integration_commands)
        if request.verification_commands != tuple(approved_commands):
            raise ValueError(
                "direct Verification Commands must exactly equal configured routed gate commands"
            )
        if request.gate_routing and request.gate_routing["execution_surface"] == "worker":
            gate = request.gate_routing["gate"]
            record_relative = gate_record_path(request.control_root, gate).relative_to(
                request.control_root
            ).as_posix()
            if request.task_write_scope and any(
                fnmatchcase(record_relative, pattern) for pattern in request.task_write_scope
            ):
                raise ValueError(
                    f"system-owned gate record must not be in Task Write Scope: {record_relative}"
                )
    return {
        "schema_version": "1.0",
        "context_mode": request.context_mode,
        "execution_class": request.execution_class,
        "timeout_seconds": request.timeout_seconds,
        "result_report": request.result_report,
        "direct_context": direct_records,
        "verification_commands": [list(item) for item in request.verification_commands],
    }


def _write_handoff_contract(request: SpawnRequest) -> None:
    path = _handoff_contract_path(request.session_dir)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"handoff contract already exists: {path}")
    atomic_write_json(path, _build_handoff_contract(request))
    path.chmod(0o600)


def _load_handoff_contract(session_dir: Path) -> dict[str, Any]:
    path = _handoff_contract_path(session_dir)
    if path.is_symlink() or not path.is_file():
        return {
            "schema_version": "1.0", "context_mode": None,
            "execution_class": None, "timeout_seconds": None,
            "result_report": None, "direct_context": [], "verification_commands": [],
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValueError("invalid pinned handoff contract")
    return value


def _validate_task_scope_pattern(pattern: str) -> None:
    if (
        not pattern
        or pattern.startswith("/")
        or "\\" in pattern
        or any(part == ".." for part in Path(pattern).parts)
    ):
        raise ValueError(f"unsafe task write scope pattern: {pattern!r}")


def _workspace_agents_instructions(workspace: Path) -> str | None:
    path = workspace / "AGENTS.md"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"workspace AGENTS.md is unsafe: {path}")
    content = path.read_text(encoding="utf-8")
    return content if content.strip() else None


def _opencode_task_context(
    request: SpawnRequest,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    spec = context_server_spec(
        request.workspace.parent,
        request.workspace.name,
        repository_root=CODEXTEAM_ROOT,
        timeout_seconds=min(5.0, float(request.timeout_seconds)),
        max_response_bytes=1_000_000,
    )
    with LocalMcpClient(spec) as client:
        result = client.call(
            "get_task_context",
            {"task_id": request.task_id, "role": request.role},
        )
    provenance = {
        "server": result.provenance.server_name,
        "tool": result.provenance.tool,
        "failed": not result.available,
        "server_duration_ms": result.provenance.duration_ms,
        "client_duration_ms": result.provenance.duration_ms,
        "returned_bytes": result.provenance.returned_bytes,
        "source_bytes": result.provenance.source_bytes or 0,
        "response_bytes": result.provenance.returned_bytes,
        "cache_hit": result.provenance.cache_hit is True,
        "source_digests": _source_digests(result.content),
    }
    return (result.content if result.available and isinstance(result.content, dict) else None), provenance


def _source_digests(value: Any) -> list[str]:
    serialized = json.dumps(value, sort_keys=True) if value is not None else ""
    return sorted(set(re.findall(r'"(?:sha256|source_sha256|index_sha256)":\s*"([a-f0-9]{64})"', serialized)))


def _merge_sidecar_mcp_summary(summary: dict[str, Any], item: dict[str, Any]) -> None:
    summary["calls"] += 1
    summary["failed_calls"] += int(item["failed"])
    for field in ("server_duration_ms", "client_duration_ms"):
        summary[field] = round(summary[field] + item[field], 3)
    for field in ("returned_bytes", "source_bytes", "response_bytes"):
        summary[field] += item[field]
    summary["cache_hits"] += int(item["cache_hit"])
    summary["max_returned_bytes"] = max(summary["max_returned_bytes"], item["returned_bytes"])
    summary["max_response_bytes"] = max(summary["max_response_bytes"], item["response_bytes"])
    summary["source_digests"] = sorted(set(summary["source_digests"]) | set(item["source_digests"]))
    summary["by_tool"].append({
        "server": item["server"], "tool": item["tool"], "calls": 1,
        "failed_calls": int(item["failed"]),
        "server_duration_ms": round(item["server_duration_ms"], 3),
        "client_duration_ms": round(item["client_duration_ms"], 3),
        "returned_bytes": item["returned_bytes"], "source_bytes": item["source_bytes"],
        "response_bytes": item["response_bytes"], "cache_hits": int(item["cache_hit"]),
        "source_digests": item["source_digests"],
    })
    summary["by_tool"].sort(key=lambda value: (value["server"], value["tool"]))


def _opencode_context_bytes(
    request: SpawnRequest,
    turn: TurnContext,
    worker_prompt: str,
) -> dict[str, int]:
    guidance = _load_pinned_skill_files(request.session_dir)
    assert request.backend_config_path is not None
    config = json.loads(request.backend_config_path.read_text(encoding="utf-8"))
    agent_name = (
        opencode_backend.FORMAT_AGENT
        if request.phase == "feedback" and request.feedback_mode == "format-only"
        else opencode_backend.AGENT
    )
    agent = config.get("agent", {}).get(agent_name, {})
    agent_prompt = agent.get("prompt") if isinstance(agent, dict) else None
    if not isinstance(agent_prompt, str):
        raise ValueError(f"pinned OpenCode config is missing {agent_name} prompt")
    values = {
        "worker_prompt_bytes": len(worker_prompt.encode("utf-8")),
        "agent_prompt_bytes": len(agent_prompt.encode("utf-8")),
        "lead_prompt_source_bytes": len(request.prompt.encode("utf-8")),
        "available_guidance_snapshot_bytes": sum(
            len(path.read_bytes()) for path in guidance
        ),
        "available_guidance_snapshot_count": len(guidance),
    }
    if request.phase == "final" and turn.session is not None:
        checkpoint = turn.session.get("accepted_checkpoint")
        if isinstance(checkpoint, dict):
            serialized = json.dumps(
                checkpoint,
                indent=2,
                sort_keys=True,
            )
            values["accepted_checkpoint_embedded_bytes"] = len(serialized.encode("utf-8"))
    return values


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


def _prepare_session_storage(
    request: SpawnRequest,
    *,
    initial: bool,
    session: dict[str, Any] | None,
) -> None:
    if initial:
        request.session_dir.mkdir(parents=True, exist_ok=True)
        request.session_dir.chmod(0o700)
        try:
            if request.split_root:
                request.artifact_report_path.parent.mkdir(mode=0o700)
            if request.delegation is None:
                raise ValueError("new attempts require delegation attribution")
            write_delegation(request.session_dir / DELEGATION_FILENAME, request.delegation)
            _write_draft_format_pin(request.draft_format_path, request.draft_format)
            _write_handoff_contract(request)
            if request.backend == "opencode" or request.draft_format == ARTIFACT_REPORT:
                _write_workspace_baseline(request)
            atomic_write_json(request.role_policy_path, request.role_policy.snapshot())
            request.role_policy_path.chmod(0o600)
            if request.agent_spec is not None:
                atomic_write_json(request.agent_spec_path, request.agent_spec.snapshot())
                request.agent_spec_path.chmod(0o600)
            _snapshot_skill_files(request)
            if request.execution_spec is None:
                raise ValueError("new attempts require an execution specification")
            write_execution_spec(request.execution_spec_path, request.execution_spec)
            if request.backend == "opencode":
                assert request.backend_config_path is not None
                context_plugin = _opencode_context_plugin_config(
                    request.session_dir,
                    request.execution_profile,
                )
                if context_plugin is not None:
                    plugin_path = Path(context_plugin["path"])
                    plugin_path.parent.mkdir(parents=True, exist_ok=True)
                    plugin_path.parent.chmod(0o700)
                    opencode_backend.write_context_plugin(plugin_path)
                config = opencode_backend.build_config(
                    model=request.model,
                    role_name=request.role,
                    role_instructions=request.effective_role_policy.developer_instructions,
                    project_instructions=request.opencode_project_instructions,
                    add_dirs=request.add_dirs,
                    display_name=request.execution_profile.model["display_name"],
                    context_limit=request.execution_profile.model["context_limit"],
                    output_limit=request.execution_profile.model["output_limit"],
                    direct_mode=request.context_mode == "direct",
                    editable_paths=request.task_write_scope or (),
                    artifact_report_path=request.artifact_report_path.as_posix(),
                    context_plugin=context_plugin,
                )
                opencode_backend.write_config(request.backend_config_path, config)
                return
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
        except Exception:
            raise
    delegation_path = request.session_dir / DELEGATION_FILENAME
    if delegation_path.exists() or delegation_path.is_symlink():
        load_delegation(
            delegation_path,
            expected_child={
                "team_id": request.team_id,
                "task_id": request.task_id,
                "attempt_id": request.attempt_id,
                "agent_role": request.role,
                "workspace_root": str(request.workspace),
            },
        )
    if request.backend == "opencode":
        assert request.backend_config_path is not None
        assert request.backend_config_digest is not None
        opencode_backend.ensure_config(
            request.backend_config_path,
            request.backend_config_digest,
        )
        context_plugin = _opencode_context_plugin_config(
            request.session_dir,
            request.execution_profile,
        )
        if context_plugin is not None:
            opencode_backend.ensure_context_plugin(
                Path(context_plugin["path"]),
                context_plugin["digest"],
            )
        expected_baseline = session.get("workspace_baseline_sha256") if session else None
        if not isinstance(expected_baseline, str) or not expected_baseline:
            raise ValueError("OpenCode session workspace_baseline_sha256 must be a non-empty string")
        _load_workspace_baseline(request, expected_digest=expected_baseline)
    elif not request.codex_home.is_dir():
        raise FileNotFoundError(f"persistent Codex home is missing: {request.codex_home}")
    if request.draft_format == ARTIFACT_REPORT and request.backend != "opencode":
        expected_baseline = session.get("workspace_baseline_sha256") if session else None
        if not isinstance(expected_baseline, str) or not expected_baseline:
            raise ValueError("semantic session workspace_baseline_sha256 must be a non-empty string")
        _load_workspace_baseline(request, expected_digest=expected_baseline)
    if not request.role_policy_path.is_file():
        atomic_write_json(request.role_policy_path, request.role_policy.snapshot())
        request.role_policy_path.chmod(0o600)
    if request.agent_spec is not None:
        loaded_agent_spec = load_agent_spec_snapshot(
            request.agent_spec_path, expected_role=request.role
        )
        if loaded_agent_spec.reference() != request.agent_spec.reference():
            raise ValueError("AgentSpec snapshot changed during continuation")
    if not (request.session_dir / GUIDANCE_MANIFEST_FILENAME).is_file():
        _snapshot_skill_files(request)
    if request.execution_spec is not None:
        loaded_spec = load_execution_spec(request.execution_spec_path)
        if loaded_spec != request.execution_spec:
            raise ValueError("execution specification changed during continuation")


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
    validate_session(data)
    return data


def _load_draft_format_pin(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"draft format pin is missing or unsafe: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid draft format pin: {path}: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"schema_version", "draft_format"}:
        raise ValueError("draft format pin must contain only schema_version and draft_format")
    if data.get("schema_version") != "1.0" or data.get("draft_format") not in DRAFT_FORMATS:
        raise ValueError("draft format pin contains an unsupported contract")
    return data["draft_format"]


def _write_draft_format_pin(path: Path, draft_format: str) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"draft format pin already exists: {path}")
    atomic_write_json(path, {"schema_version": "1.0", "draft_format": draft_format})
    path.chmod(0o600)


def _validate_session_scope(request: SpawnRequest, session: dict[str, Any]) -> None:
    if (
        request.backend == "opencode"
        and request.backend_version is not None
        and session.get("backend_version") != request.backend_version
    ):
        raise ValueError(
            "session backend version mismatch: "
            f"expected {request.backend_version!r}, found {session.get('backend_version')!r}"
        )
    expected = {
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "workspace_root": str(request.workspace),
        "handoff_contract_sha256": hashlib.sha256(
            _handoff_contract_path(request.session_dir).read_bytes()
        ).hexdigest(),
    }
    if request.split_root:
        assert request.repo_id is not None
        expected.update({
            "control_root": str(request.control_root),
            "work_root": str(request.work_root),
            "git_root": str(request.git_root),
            "git_prefix": request.git_prefix,
            "repo_id": request.repo_id,
        })
    mismatches = [
        f"{field}: expected {value!r}, found {session.get(field)!r}"
        for field, value in expected.items()
        if session.get(field) != value
    ]
    if mismatches:
        raise ValueError("session scope mismatch: " + "; ".join(mismatches))
    if request.execution_spec is None or session.get("execution_spec") != execution_spec_reference(request.execution_spec):
        raise ValueError("session execution specification reference mismatch")


def _session_record(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    thread_id: str | None,
    status: str,
    process: ProcessResult,
    change_actions: dict[str, str] | None = None,
    workspace_snapshot: dict[str, str] | None = None,
    trusted_baseline: dict[str, str] | None = None,
    trusted_baseline_digest: str | None = None,
    final_result_path: str | None = None,
) -> dict[str, Any]:
    if not thread_id:
        raise ValueError("cannot persist a resumable session without a thread ID")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    created_at = turn.session.get("created_at", now) if turn.session else now
    turns = list(turn.session.get("turns", [])) if turn.session else []
    turns.append({
        "number": turn.number,
        "phase": request.phase,
        "status": status,
        "duration_seconds": round(process.duration_seconds, 3),
    })
    record = dict(turn.session or {})
    record.update({
        "schema_version": "1.1" if request.split_root else SESSION_SCHEMA_VERSION,
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "workspace_root": str(request.workspace),
        **({
            "control_root": str(request.control_root),
            "work_root": str(request.work_root),
            "git_root": str(request.git_root),
            "git_prefix": request.git_prefix,
            "repo_id": request.repo_id,
        } if request.split_root else {}),
        "handoff_contract_sha256": hashlib.sha256(
            _handoff_contract_path(request.session_dir).read_bytes()
        ).hexdigest(),
        "thread_id": thread_id,
        "turn_count": turn.number,
        "last_phase": request.phase,
        "last_status": status,
        "last_turn_path": turn.message_path.relative_to(request.control_root).as_posix(),
        "created_at": created_at,
        "updated_at": now,
        "turns": turns,
    })
    if request.execution_spec is not None:
        record["execution_spec"] = execution_spec_reference(request.execution_spec)
    else:
        record.pop("execution_spec", None)
    if request.backend == "opencode" or request.draft_format == ARTIFACT_REPORT:
        if trusted_baseline is None or trusted_baseline_digest is None:
            raise ValueError("trusted workspace baseline is required")
        record["workspace_baseline_sha256"] = trusted_baseline_digest
        worker_changes = _merge_worker_change_manifest(
            trusted_baseline,
            turn.session.get("worker_change_manifest") if turn.session else None,
            change_actions or {},
            workspace_snapshot or {},
        )
        record["worker_change_manifest"] = worker_changes
        if request.phase in {"draft", "feedback"} and status == "draft_ready":
            record["accepted_checkpoint"] = _accepted_checkpoint(
                request,
                turn,
                thread_id=thread_id,
                accepted_paths=_accepted_product_paths(worker_changes),
            )
        elif turn.session and "accepted_checkpoint" in turn.session:
            record["accepted_checkpoint"] = turn.session["accepted_checkpoint"]
    if request.backend == "opencode":
        record["backend_version"] = request.backend_version
        record["backend_config_digest"] = request.backend_config_digest
        record["opencode_session_id"] = thread_id
    if final_result_path is not None:
        record["final_result_path"] = final_result_path
    return record


def _accepted_checkpoint(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    thread_id: str,
    accepted_paths: dict[str, dict[str, str | None]],
) -> dict[str, Any]:
    report_relative = _artifact_report_reference(request)
    report_bytes = request.artifact_report_path.read_bytes()
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    try:
        report = json.loads(report_bytes.decode("utf-8"))
        validate_artifact_report(report)
    except (UnicodeDecodeError, json.JSONDecodeError, ResultValidationError) as exc:
        raise ValueError(f"cannot checkpoint invalid artifact report: {exc}") from exc
    evidence_hashes = {
        relative: hashlib.sha256(
            contained_path(request.workspace, relative, label="checkpoint evidence").read_bytes()
        ).hexdigest()
        for relative in report["evidence"]
    }
    return {
        "turn_number": turn.number,
        "phase": request.phase,
        "artifact_report_path": report_relative,
        "artifact_report_sha256": report_hash,
        "evidence_sha256": evidence_hashes,
        "workspace_sha256": _accepted_paths_digest(accepted_paths),
        "changed_paths": sorted(accepted_paths),
        "accepted_paths": accepted_paths,
        "session_id": thread_id,
        "execution_spec": (
            execution_spec_reference(request.execution_spec)
            if request.execution_spec is not None
            else None
        ),
    }


def _ensure_accepted_checkpoint(request: SpawnRequest, turn: TurnContext) -> None:
    checkpoint = turn.session.get("accepted_checkpoint") if turn.session else None
    if not isinstance(checkpoint, dict):
        raise ValueError("finalization requires an accepted draft checkpoint")
    reference = checkpoint.get("artifact_report_path")
    expected_hash = checkpoint.get("artifact_report_sha256")
    if not isinstance(reference, str) or not isinstance(expected_hash, str):
        raise ValueError("accepted draft checkpoint is incomplete")
    if reference != _artifact_report_reference(request):
        raise ValueError("accepted artifact report path does not match this attempt")
    path = request.artifact_report_path
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"accepted artifact report is missing or unsafe: {path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError(f"accepted artifact report digest mismatch: {path}")
    evidence_hashes = checkpoint.get("evidence_sha256")
    if not isinstance(evidence_hashes, dict):
        raise ValueError("accepted checkpoint evidence digests are missing")
    for evidence_relative, evidence_hash in evidence_hashes.items():
        evidence_path = contained_path(
            request.workspace, evidence_relative, label="accepted evidence"
        )
        if evidence_path.is_symlink() or not evidence_path.is_file():
            raise ValueError(f"accepted evidence is missing or unsafe: {evidence_relative}")
        if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != evidence_hash:
            raise ValueError(f"accepted evidence digest mismatch: {evidence_relative}")
    accepted_paths = checkpoint.get("accepted_paths")
    if not isinstance(accepted_paths, dict):
        raise ValueError("OpenCode accepted draft checkpoint paths are incomplete")
    path_errors = _accepted_path_errors(request.workspace, accepted_paths)
    if path_errors:
        raise ValueError("accepted draft product path mismatch: " + "; ".join(path_errors))
    if checkpoint.get("workspace_sha256") != _accepted_paths_digest(accepted_paths):
        raise ValueError("accepted draft product manifest digest mismatch")
    if request.execution_spec is None:
        raise ValueError("post-cutover OpenCode checkpoint requires execution specification")
    expected_identity = {
        "session_id": turn.session.get("thread_id") if turn.session else None,
        "execution_spec": execution_spec_reference(request.execution_spec),
    }
    mismatches = [
        f"{field}: expected {value!r}, found {checkpoint.get(field)!r}"
        for field, value in expected_identity.items()
        if checkpoint.get(field) != value
    ]
    if mismatches:
        raise ValueError("accepted draft checkpoint mismatch: " + "; ".join(mismatches))


def _merge_worker_change_manifest(
    baseline: dict[str, str],
    previous: Any,
    change_actions: dict[str, str],
    snapshot: dict[str, str],
) -> dict[str, dict[str, str | None]]:
    touched = {
        path
        for path in (previous or {})
        if isinstance(path, str)
    }
    touched.update(
        path
        for path, action in change_actions.items()
        if isinstance(path, str) and action in {"created", "modified", "deleted"}
    )
    manifest: dict[str, dict[str, str | None]] = {}
    for path in sorted(touched):
        baseline_hash = baseline.get(path)
        current_hash = snapshot.get(path)
        if baseline_hash is None and current_hash is None:
            continue
        if baseline_hash == current_hash:
            continue
        action = (
            "created"
            if baseline_hash is None
            else "deleted"
            if current_hash is None
            else "modified"
        )
        manifest[path] = {"action": action, "sha256": current_hash}
    return manifest


def _accepted_product_paths(
    worker_changes: dict[str, dict[str, str | None]],
) -> dict[str, dict[str, str | None]]:
    return {
        path: dict(item)
        for path, item in worker_changes.items()
        if not _acceptance_path_excluded(path)
    }


def _accepted_path_errors(
    workspace: Path,
    accepted_paths: dict[str, Any],
) -> list[str]:
    snapshot = snapshot_workspace(workspace)
    errors: list[str] = []
    for path, item in sorted(accepted_paths.items()):
        if (
            not isinstance(path, str)
            or _acceptance_path_excluded(path)
            or not isinstance(item, dict)
            or item.get("action") not in {"created", "modified", "deleted"}
            or (item.get("sha256") is not None and not isinstance(item.get("sha256"), str))
        ):
            errors.append(f"invalid accepted path entry: {path!r}")
            continue
        if snapshot.get(path) != item.get("sha256"):
            errors.append(path)
    return errors


def _accepted_paths_digest(accepted_paths: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            accepted_paths,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _workspace_baseline_path(request: SpawnRequest) -> Path:
    return request.session_dir / WORKSPACE_BASELINE_FILENAME


def _write_workspace_baseline(request: SpawnRequest) -> None:
    path = _workspace_baseline_path(request)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"workspace baseline already exists: {path}")
    atomic_write_json(path, _snapshot_request_workspace(request))
    path.chmod(0o600)


def _load_workspace_baseline(
    request: SpawnRequest,
    *,
    expected_digest: Any = None,
) -> dict[str, str]:
    path = _workspace_baseline_path(request)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"workspace baseline is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid workspace baseline: {path}: {exc}") from exc
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(digest, str)
        for key, digest in value.items()
    ):
        raise ValueError(f"invalid workspace baseline manifest: {path}")
    digest = _workspace_baseline_digest(value)
    if expected_digest is not None and expected_digest != digest:
        raise ValueError(f"workspace baseline digest mismatch: {path}")
    return value


def _workspace_baseline_digest(baseline: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(baseline, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _post_run_baseline_error(
    request: SpawnRequest,
    trusted_digest: str | None,
) -> str | None:
    if request.backend != "opencode":
        return None
    if trusted_digest is None:
        return "trusted OpenCode workspace baseline digest is missing"
    try:
        current = _load_workspace_baseline(request)
    except (OSError, ValueError) as exc:
        return f"OpenCode worker changed the private workspace baseline: {exc}"
    if _workspace_baseline_digest(current) != trusted_digest:
        return "OpenCode worker changed the private workspace baseline digest"
    return None


def _restore_workspace_baseline(
    request: SpawnRequest,
    trusted_baseline: dict[str, str],
) -> None:
    path = _workspace_baseline_path(request)
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    atomic_write_json(path, trusted_baseline)
    path.chmod(0o600)


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
    return request.execution_profile.effective_reasoning


def _write_session(path: Path, session: dict[str, Any]) -> None:
    validate_session(session)
    reference = session.get("execution_spec")
    if isinstance(reference, dict):
        current = load_execution_spec(path.parent / reference["path"])
        if execution_spec_reference(current) != reference:
            raise ValueError("session execution specification reference mismatch")
    atomic_write_json(path, session)
    path.chmod(0o600)


def _write_turn_state(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    status: str,
    process: ProcessResult | None = None,
    changed_paths: tuple[str, ...] = (),
    change_actions: dict[str, str] | None = None,
    errors: list[str] | None = None,
    thread_id: str | None = None,
    verify_spec: bool = True,
) -> None:
    if verify_spec:
        _verify_execution_spec_immutable(request)
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
        "draft_format": request.draft_format,
        "draft_format_pinned": request.draft_format_pinned,
        "role_policy_name": request.role_policy.name,
        "role_policy_version": request.role_policy.schema_version,
        "role_policy_digest": request.role_policy.digest,
        "agent_spec": request.agent_spec.reference() if request.agent_spec is not None else None,
        "effective_policy_digest": effective_policy_digest(request.effective_role_policy),
        "instruction_bundle_digest": request.guidance_digest,
        "execution_spec": (
            execution_spec_reference(request.execution_spec)
            if request.execution_spec is not None
            else None
        ),
        "phase": request.phase,
        "turn_number": turn.number,
        "status": status,
        "started_at": existing.get("started_at", now) if same_turn else now,
        "updated_at": now,
        "timeout_seconds": request.timeout_seconds,
        "run_guard_enabled": request.run_guard,
        "mcp_allowed_servers": list(request.effective_role_policy.mcp_servers),
        "mcp_effective_servers": list(request.effective_mcp_servers),
        "mcp_missing_servers": list(request.missing_mcp_servers),
        "mcp_allowed_tools": {
            server: list(tools)
            for server, tools in request.effective_role_policy.mcp_tools
        },
        "mcp_effective_tools": {
            server: list(tools)
            for server, tools in request.effective_mcp_tools
        },
        "changed_paths": list(changed_paths),
        "errors": errors or [],
    }
    if change_actions is not None:
        state["change_actions"] = change_actions
    if request.backend == "opencode":
        state["execution_backend"] = request.backend
        state["resolved_model"] = request.model
        state["backend_version"] = request.backend_version
        state["backend_config_digest"] = request.backend_config_digest
    if request.mcp_context_project is not None:
        state["mcp_context_project"] = request.mcp_context_project
    if thread_id is not None:
        if request.backend == "opencode":
            state["thread_id"] = thread_id
            state["opencode_session_id"] = thread_id
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
    events: BackendEventSummary,
    *,
    thread_id: str | None,
    thread_mismatch: bool,
    backend: str = "codex",
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
        if backend == "codex":
            return "turn_failed", 1, ["Codex event stream did not contain turn.completed"]
        if events.terminal_reason:
            return "turn_failed", 1, [
                f"OpenCode turn ended with terminal reason {events.terminal_reason!r}"
            ]
        return "turn_failed", 1, ["OpenCode event stream did not contain step_finish"]
    return None, 0, []


def _backend_name(backend: str) -> str:
    return "OpenCode" if backend == "opencode" else "Codex"


def _turn_outcome(
    request: SpawnRequest,
    turn: TurnContext,
    *,
    status: str,
    thread_id: str | None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    outcome = {
        "phase": request.phase,
        "status": status,
        "team_id": request.team_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "agent_role": request.role,
        "draft_format": request.draft_format,
        "draft_format_pinned": request.draft_format_pinned,
        "role_policy_name": request.role_policy.name,
        "role_policy_version": request.role_policy.schema_version,
        "role_policy_digest": request.role_policy.digest,
        "agent_spec": request.agent_spec.reference() if request.agent_spec is not None else None,
        "effective_policy_digest": effective_policy_digest(request.effective_role_policy),
        "instruction_bundle_digest": request.guidance_digest,
        "execution_spec": (
            execution_spec_reference(request.execution_spec)
            if request.execution_spec is not None
            else None
        ),
        "mcp_context_project": request.mcp_context_project,
        "thread_id": thread_id,
        "turn_count": turn.number,
        "session_path": str(request.session_path),
        "turn_path": str(turn.message_path),
        "lead_prompt_path": str(turn.lead_prompt_path),
        "events_path": str(turn.events_path),
        "metrics_path": str(metrics_path(turn.events_path)),
        "stderr_path": str(turn.stderr_path),
        "result_path": str(request.result_path) if request.result_path.exists() else None,
        "errors": errors or [],
    }
    if request.backend == "opencode":
        outcome["execution_backend"] = request.backend
        outcome["resolved_model"] = request.model
    return outcome


def _result_from_message(
    request: SpawnRequest,
    process: ProcessResult,
    message: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    candidates = extract_json_objects(message)
    validation_errors: list[str] = []
    for candidate in reversed(candidates):
        candidate = dict(candidate)
        candidate.update(
            {
                "schema_version": "1.0",
                "team_id": request.team_id,
                "task_id": request.task_id,
                "agent_role": request.role,
                "attempt_id": request.attempt_id,
                "produced_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            }
        )
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
        if request.role == "git_steward":
            candidate["file_changes"] = []
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
        accepted_change_errors = _accepted_change_declaration_errors(request, candidate)
        if accepted_change_errors:
            validation_errors.extend(accepted_change_errors)
            continue
        policy_errors = _result_policy_errors(request, candidate)
        if policy_errors:
            validation_errors.extend(policy_errors)
            continue
        return candidate, []
    errors = ["final result validation failed"]
    errors.extend(list(dict.fromkeys(validation_errors))[:10])
    return None, errors


def _artifact_report_from_file(
    request: SpawnRequest,
    *,
    pin_evidence: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    path = request.artifact_report_path
    if path.is_symlink() or not path.is_file():
        return None, [f"artifact report is missing or unsafe: {_artifact_report_reference(request)}"]
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > 64 * 1024:
            return None, ["artifact report must contain 1 to 65536 bytes"]
        candidate = json.loads(raw.decode("utf-8"))
        validate_artifact_report(candidate)
    except UnicodeDecodeError:
        return None, ["artifact report must be UTF-8"]
    except json.JSONDecodeError as exc:
        return None, [f"artifact report must be valid JSON: {exc.msg}"]
    except ResultValidationError as exc:
        return None, list(exc.errors[:10])
    errors: list[str] = []
    for index, relative in enumerate(candidate["evidence"]):
        try:
            evidence_path = contained_path(
                request.workspace, relative, label=f"evidence[{index}]"
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if evidence_path.is_symlink() or not evidence_path.is_file():
            errors.append(f"evidence[{index}] does not name an existing regular file: {relative}")
    if errors:
        return None, errors
    return candidate, []


def _semantic_json_object(message: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    stripped = message.strip()
    value, end = decoder.raw_decode(stripped)
    trailing = stripped[end:].strip()
    if trailing and not re.fullmatch(r"(?:</atem:parameter>\s*)+", trailing):
        raise json.JSONDecodeError("Extra data", stripped, end)
    if not isinstance(value, dict):
        raise json.JSONDecodeError("payload must be an object", stripped, 0)
    return value




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
        root = (
            request.control_root
            if request.split_root and evidence["artifact_ref"].startswith("results/gates/")
            else request.workspace
        )
        path = contained_path(
            root,
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
        if not request.effective_role_policy.allows_change(item["path"])
    ]
    errors.extend(
        f"role policy {request.role_policy.name} does not allow evidence type: {item['type']}"
        for item in result["evidence"]
        if item["type"] not in request.effective_role_policy.allowed_evidence_types
    )
    return errors


def _accepted_change_declaration_errors(
    request: SpawnRequest,
    result: dict[str, Any],
) -> list[str]:
    if request.backend != "opencode" or request.role == "git_steward":
        return []
    session = _load_session(request.session_path)
    checkpoint = session.get("accepted_checkpoint")
    accepted = checkpoint.get("accepted_paths") if isinstance(checkpoint, dict) else None
    if not isinstance(accepted, dict):
        return ["OpenCode accepted product path manifest is missing"]
    declared: dict[str, str] = {}
    errors: list[str] = []
    for item in result["file_changes"]:
        path = item["path"]
        if path in declared:
            errors.append(f"file_changes contains duplicate path: {path}")
        else:
            declared[path] = item["action"]
    errors.extend(
        f"file_changes must declare accepted {item.get('action')} path: {path}"
        for path, item in sorted(accepted.items())
        if isinstance(item, dict) and declared.get(path) != item.get("action")
    )
    errors.extend(
        f"file_changes contains path outside accepted product manifest: {path}"
        for path in sorted(set(declared) - set(accepted))
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
