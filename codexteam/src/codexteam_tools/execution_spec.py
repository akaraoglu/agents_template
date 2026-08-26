from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import AGENT_ROLES


EXECUTION_SPEC_CONTRACT = "execution-spec"
EXECUTION_SPEC_FILENAME = "execution-spec.json"
EXECUTION_SPEC_FIELDS = {
    "schema_version", "execution_spec_id", "identity", "handoff", "role_policy",
    "agent_spec", "guidance", "execution_profile", "permissions", "gate_routing",
    "execution_spec_digest",
}


class ExecutionSpecError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def compile_execution_spec(
    *,
    team_id: str,
    task_id: str,
    attempt_id: str,
    role: str,
    workspace_root: str,
    control_root: str | None = None,
    work_root: str | None = None,
    git_root: str | None = None,
    git_prefix: str | None = None,
    repo_id: str | None = None,
    handoff_source_path: str | None,
    handoff_content_digest: str,
    role_policy_name: str,
    role_policy_version: str,
    role_policy_digest: str,
    agent_spec: dict[str, str] | None,
    effective_policy_digest: str,
    guidance_files: list[str],
    guidance_digest: str,
    execution_profile: dict[str, Any],
    sandbox_mode: str,
    trust_parent_sandbox: bool,
    additional_write_roots: list[str],
    mcp_allowed_servers: list[str],
    mcp_effective_servers: list[str],
    mcp_missing_servers: list[str],
    mcp_allowed_tools: dict[str, list[str]],
    mcp_effective_tools: dict[str, list[str]],
    bound_mcp_project: str | None,
    gate_routing: dict[str, str] | None,
    task_write_scope: list[str] | None = None,
) -> dict[str, Any]:
    identity = {
        "team_id": team_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "role": role,
        "workspace_root": workspace_root,
    }
    split_values = (control_root, work_root, git_root, git_prefix, repo_id)
    if any(value is not None for value in split_values):
        if not all(isinstance(value, str) and value for value in split_values):
            raise ExecutionSpecError(
                "split-root identity requires control_root, work_root, git_root, git_prefix, and repo_id"
            )
        assert all(isinstance(value, str) for value in split_values)
        identity.update({
            "control_root": str(control_root),
            "work_root": str(work_root),
            "git_root": str(git_root),
            "git_prefix": str(git_prefix),
            "repo_id": str(repo_id),
        })
    value = {
        "schema_version": "1.1" if control_root is not None else "1.0",
        "execution_spec_id": f"exec-{canonical_sha256(identity)[:32]}",
        "identity": identity,
        "handoff": {
            "source_path": handoff_source_path,
            "content_digest": handoff_content_digest,
        },
        "role_policy": {
            "name": role_policy_name,
            "version": role_policy_version,
            "digest": role_policy_digest,
        },
        "agent_spec": agent_spec,
        "guidance": {
            "files": guidance_files,
            "bundle_digest": guidance_digest,
        },
        "execution_profile": execution_profile,
        "permissions": {
            "effective_policy_digest": effective_policy_digest,
            "sandbox_mode": sandbox_mode,
            "trust_parent_sandbox": trust_parent_sandbox,
            "additional_write_roots": additional_write_roots,
            "mcp_allowed_servers": mcp_allowed_servers,
            "mcp_effective_servers": mcp_effective_servers,
            "mcp_missing_servers": mcp_missing_servers,
            "mcp_allowed_tools": mcp_allowed_tools,
            "mcp_effective_tools": mcp_effective_tools,
            "bound_mcp_project": bound_mcp_project,
            "task_write_scope": task_write_scope,
        },
        "gate_routing": gate_routing,
    }
    value["execution_spec_digest"] = canonical_sha256(value)
    return validate_execution_spec(value)


def validate_execution_spec(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ExecutionSpecError("execution specification must be a JSON object")
    errors: list[str] = []
    if set(data) != EXECUTION_SPEC_FIELDS:
        errors.append("execution specification fields do not match execution-spec")
    if data.get("schema_version") not in {"1.0", "1.1"}:
        errors.append("schema_version must be '1.0' or '1.1'")
    _nonempty(data.get("execution_spec_id"), "execution_spec_id", errors)

    identity_fields = {"team_id", "task_id", "attempt_id", "role", "workspace_root"}
    if data.get("schema_version") == "1.1":
        identity_fields |= {"control_root", "work_root", "git_root", "git_prefix", "repo_id"}
    identity = _strict_object(
        data.get("identity"),
        "identity",
        identity_fields,
        errors,
    )
    for field in ("team_id", "task_id", "attempt_id"):
        _nonempty(identity.get(field), f"identity.{field}", errors)
    if identity.get("role") not in AGENT_ROLES:
        errors.append("identity.role is not a protocol role")
    workspace = identity.get("workspace_root")
    if not isinstance(workspace, str) or not PurePosixPath(workspace).is_absolute():
        errors.append("identity.workspace_root must be absolute")
    if data.get("schema_version") == "1.1":
        for field in ("control_root", "work_root", "git_root"):
            value = identity.get(field)
            if not isinstance(value, str) or not PurePosixPath(value).is_absolute():
                errors.append(f"identity.{field} must be absolute")
        _nonempty(identity.get("git_prefix"), "identity.git_prefix", errors)
        _nonempty(identity.get("repo_id"), "identity.repo_id", errors)
        if identity.get("workspace_root") != identity.get("work_root"):
            errors.append("identity.workspace_root must equal identity.work_root")

    handoff = _strict_object(data.get("handoff"), "handoff", {"source_path", "content_digest"}, errors)
    if handoff.get("source_path") is not None and not isinstance(handoff.get("source_path"), str):
        errors.append("handoff.source_path must be a string or null")
    _digest(handoff.get("content_digest"), "handoff.content_digest", errors)

    policy = _strict_object(data.get("role_policy"), "role_policy", {"name", "version", "digest"}, errors)
    _nonempty(policy.get("name"), "role_policy.name", errors)
    if policy.get("version") != "1.0":
        errors.append("role_policy.version must be '1.0'")
    _digest(policy.get("digest"), "role_policy.digest", errors)
    agent_spec = data.get("agent_spec")
    if agent_spec is not None:
        agent_spec = _strict_object(agent_spec, "agent_spec", {"id", "version", "digest"}, errors)
        _nonempty(agent_spec.get("id"), "agent_spec.id", errors)
        if agent_spec.get("version") != "1.0":
            errors.append("agent_spec.version must be '1.0'")
        _digest(agent_spec.get("digest"), "agent_spec.digest", errors)

    guidance = _strict_object(data.get("guidance"), "guidance", {"files", "bundle_digest"}, errors)
    _string_list(guidance.get("files"), "guidance.files", errors)
    _digest(guidance.get("bundle_digest"), "guidance.bundle_digest", errors)

    profile = _strict_object(
        data.get("execution_profile"), "execution_profile",
        {"registry_digest", "backend", "model", "profile", "reasoning", "backend_material_digest", "verbosity_supported", "qualification_references"},
        errors,
    )
    _digest(profile.get("registry_digest"), "execution_profile.registry_digest", errors)
    _nonempty(profile.get("backend_material_digest"), "execution_profile.backend_material_digest", errors)
    backend = _strict_object(profile.get("backend"), "execution_profile.backend", {"id", "definition_digest", "runtime_version"}, errors)
    if backend.get("id") not in {"codex", "opencode"}:
        errors.append("execution_profile.backend.id is invalid")
    _digest(backend.get("definition_digest"), "execution_profile.backend.definition_digest", errors)
    model = _strict_object(profile.get("model"), "execution_profile.model", {"id", "definition_digest", "provider", "provider_locator"}, errors)
    for field in ("id", "provider", "provider_locator"):
        _nonempty(model.get(field), f"execution_profile.model.{field}", errors)
    _digest(model.get("definition_digest"), "execution_profile.model.definition_digest", errors)
    profile_ref = _strict_object(profile.get("profile"), "execution_profile.profile", {"id", "definition_digest"}, errors)
    _nonempty(profile_ref.get("id"), "execution_profile.profile.id", errors)
    _digest(profile_ref.get("definition_digest"), "execution_profile.profile.definition_digest", errors)
    if isinstance(profile_ref.get("id"), str) and isinstance(backend.get("id"), str) and not profile_ref["id"].startswith(backend["id"] + "/"):
        errors.append("execution_profile.profile.id backend prefix mismatch")
    reasoning = _strict_object(profile.get("reasoning"), "execution_profile.reasoning", {"requested", "effective", "support_status", "runtime_options"}, errors)
    _nonempty(reasoning.get("requested"), "execution_profile.reasoning.requested", errors)
    if reasoning.get("effective") is not None and not isinstance(reasoning.get("effective"), str):
        errors.append("execution_profile.reasoning.effective must be a string or null")
    if reasoning.get("support_status") not in {"applied", "provider_default"}:
        errors.append("execution_profile.reasoning.support_status is invalid")
    if reasoning.get("support_status") == "provider_default" and reasoning.get("effective") is not None:
        errors.append("provider_default reasoning cannot claim an effective effort")
    if reasoning.get("support_status") == "applied" and not isinstance(reasoning.get("effective"), str):
        errors.append("applied reasoning requires an effective effort")
    if not isinstance(reasoning.get("runtime_options"), dict):
        errors.append("execution_profile.reasoning.runtime_options must be an object")
    qualifications = profile.get("qualification_references")
    if (
        not isinstance(qualifications, list)
        or not qualifications
        or any(not isinstance(item, str) or not item for item in qualifications)
        or len(set(qualifications)) != len(qualifications)
    ):
        errors.append("execution_profile qualification_references must be non-empty")

    permissions = _strict_object(
        data.get("permissions"), "permissions",
        {"effective_policy_digest", "sandbox_mode", "trust_parent_sandbox", "additional_write_roots", "mcp_allowed_servers", "mcp_effective_servers", "mcp_missing_servers", "mcp_allowed_tools", "mcp_effective_tools", "bound_mcp_project", "task_write_scope"},
        errors,
    )
    if permissions.get("sandbox_mode") not in {"read-only", "workspace-write"}:
        errors.append("permissions.sandbox_mode is invalid")
    if not isinstance(permissions.get("trust_parent_sandbox"), bool):
        errors.append("permissions.trust_parent_sandbox must be a boolean")
    _digest(permissions.get("effective_policy_digest"), "permissions.effective_policy_digest", errors)
    for field in ("additional_write_roots", "mcp_allowed_servers", "mcp_effective_servers", "mcp_missing_servers"):
        _string_list(permissions.get(field), f"permissions.{field}", errors)
    for field in ("mcp_allowed_tools", "mcp_effective_tools"):
        _tool_mapping(permissions.get(field), f"permissions.{field}", errors)
    if permissions.get("bound_mcp_project") is not None and not isinstance(permissions.get("bound_mcp_project"), str):
        errors.append("permissions.bound_mcp_project must be a string or null")
    if permissions.get("task_write_scope") is not None:
        _string_list(permissions.get("task_write_scope"), "permissions.task_write_scope", errors)

    route = data.get("gate_routing")
    if route is not None:
        route = _strict_object(route, "gate_routing", {"gate", "execution_surface"}, errors)
        if route.get("gate") not in {"development", "integration"}:
            errors.append("gate_routing.gate is invalid")
        if route.get("execution_surface") not in {"worker", "lead_host"}:
            errors.append("gate_routing.execution_surface is invalid")

    expected_digest = data.get("execution_spec_digest")
    _digest(expected_digest, "execution_spec_digest", errors)
    unsigned = {key: value for key, value in data.items() if key != "execution_spec_digest"}
    if isinstance(expected_digest, str) and not hmac.compare_digest(canonical_sha256(unsigned), expected_digest):
        errors.append("execution specification digest mismatch")
    if errors:
        raise ExecutionSpecError("; ".join(errors))
    return data


def load_execution_spec(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ExecutionSpecError(f"execution specification is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExecutionSpecError(f"invalid execution specification JSON: {exc}") from exc
    return validate_execution_spec(value)


def write_execution_spec(path: Path, value: dict[str, Any]) -> None:
    validate_execution_spec(value)
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ExecutionSpecError(f"execution specification already exists: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def execution_spec_reference(value: dict[str, Any]) -> dict[str, str]:
    validate_execution_spec(value)
    return {
        "contract": EXECUTION_SPEC_CONTRACT,
        "path": EXECUTION_SPEC_FILENAME,
        "digest": value["execution_spec_digest"],
    }


def _strict_object(value: Any, field: str, expected: set[str], errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return {}
    if set(value) != expected:
        errors.append(f"{field} fields do not match execution-spec")
    return value


def _nonempty(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")


def _digest(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        errors.append(f"{field} must be a lowercase SHA-256 digest")


def _string_list(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{field} must be a string list")


def _tool_mapping(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return
    for server, tools in value.items():
        if not isinstance(server, str) or not server:
            errors.append(f"{field} server names must be non-empty strings")
        _string_list(tools, f"{field}.{server}", errors)
