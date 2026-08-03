from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .contracts import AGENT_ROLES, EVIDENCE_TYPES
from .paths import PathValidationError, validate_profile

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROLES_ROOT = CODEXTEAM_ROOT / "roles"
ROLE_POLICY_SCHEMA_VERSION = "1.0"
REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}
SANDBOX_MODES = {"read-only", "workspace-write"}
ROLE_NAME_PATTERN = re.compile(r"codexteam_[a-z][a-z0-9_]{1,63}")
MCP_SERVER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
MCP_TOOL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")
LOCAL_MCP_TOOL_CATALOG = {
    "codexteam-context": frozenset(
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
    ),
    "local-docs": frozenset(
        {
            "list_doc_sources",
            "search_docs",
            "read_doc",
        }
    ),
}
REQUIRED_POLICY_FIELDS = {
    "schema_version",
    "role",
    "name",
    "description",
    "developer_instructions",
    "default_profile",
    "default_reasoning_effort",
    "sandbox_mode",
    "skill_files",
    "allowed_change_patterns",
    "denied_change_patterns",
    "allowed_evidence_types",
}
OPTIONAL_POLICY_FIELDS = {"mcp_servers", "mcp_tools"}
POLICY_FIELDS = REQUIRED_POLICY_FIELDS | OPTIONAL_POLICY_FIELDS


class RolePolicyError(ValueError):
    pass


@dataclass(frozen=True)
class RolePolicy:
    schema_version: str
    role: str
    name: str
    description: str
    developer_instructions: str
    default_profile: str
    default_reasoning_effort: str
    sandbox_mode: str
    skill_files: tuple[str, ...]
    allowed_change_patterns: tuple[str, ...]
    denied_change_patterns: tuple[str, ...]
    allowed_evidence_types: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    mcp_servers_declared: bool
    mcp_tools: tuple[tuple[str, tuple[str, ...]], ...]
    mcp_tools_declared: bool
    digest: str
    source_path: Path

    def allows_change(self, relative_path: str) -> bool:
        normalized = _normalize_relative_file(relative_path)
        if any(fnmatchcase(normalized, pattern) for pattern in self.denied_change_patterns):
            return False
        return any(fnmatchcase(normalized, pattern) for pattern in self.allowed_change_patterns)

    def tools_for_server(self, server: str) -> tuple[str, ...]:
        return dict(self.mcp_tools).get(server, ())

    def snapshot(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "role": self.role,
            "name": self.name,
            "description": self.description,
            "developer_instructions": self.developer_instructions,
            "default_profile": self.default_profile,
            "default_reasoning_effort": self.default_reasoning_effort,
            "sandbox_mode": self.sandbox_mode,
            "skill_files": list(self.skill_files),
            "allowed_change_patterns": list(self.allowed_change_patterns),
            "denied_change_patterns": list(self.denied_change_patterns),
            "allowed_evidence_types": list(self.allowed_evidence_types),
            "digest": self.digest,
        }
        if self.mcp_servers_declared:
            value["mcp_servers"] = list(self.mcp_servers)
        if self.mcp_tools_declared:
            value["mcp_tools"] = {
                server: list(tools)
                for server, tools in self.mcp_tools
            }
        return value


def load_role_policy(
    role: str,
    *,
    roles_root: str | Path = DEFAULT_ROLES_ROOT,
) -> RolePolicy:
    if role not in AGENT_ROLES:
        raise RolePolicyError(f"unsupported role policy: {role}")
    root = Path(roles_root).expanduser().resolve(strict=True)
    candidate = root / f"{role}.toml"
    if candidate.is_symlink():
        raise RolePolicyError(f"role policy must not be a symlink: {candidate}")
    path = candidate.resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RolePolicyError(f"role policy escapes policy root: {path}") from exc
    if not path.is_file():
        raise RolePolicyError(f"role policy must be a regular file: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RolePolicyError(f"invalid role policy TOML: {path}: {exc}") from exc
    return role_policy_from_mapping(data, source_path=path, expected_role=role)


def load_role_policy_snapshot(path: str | Path, *, expected_role: str) -> RolePolicy:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise RolePolicyError(f"role policy snapshot must not be a symlink: {candidate}")
    snapshot_path = candidate.resolve(strict=True)
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RolePolicyError(f"invalid role policy snapshot: {snapshot_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RolePolicyError("role policy snapshot must be a JSON object")
    stored_digest = data.pop("digest", None)
    policy = role_policy_from_mapping(
        data,
        source_path=snapshot_path,
        expected_role=expected_role,
    )
    if stored_digest != policy.digest:
        raise RolePolicyError(
            f"role policy snapshot digest mismatch: expected {policy.digest}, found {stored_digest}"
        )
    return replace(policy, digest=stored_digest)


def role_policy_from_mapping(
    data: dict[str, Any],
    *,
    source_path: Path,
    expected_role: str | None = None,
) -> RolePolicy:
    unknown = sorted(set(data) - POLICY_FIELDS)
    missing = sorted(REQUIRED_POLICY_FIELDS - set(data))
    errors: list[str] = []
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    if missing:
        errors.append("missing fields: " + ", ".join(missing))

    schema_version = data.get("schema_version")
    if schema_version != ROLE_POLICY_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ROLE_POLICY_SCHEMA_VERSION!r}")
    role = data.get("role")
    if role not in AGENT_ROLES:
        errors.append(f"role must be one of {sorted(AGENT_ROLES)}")
    elif expected_role is not None and role != expected_role:
        errors.append(f"role mismatch: expected {expected_role}, found {role}")
    name = _bounded_string(data.get("name"), "name", 128, errors)
    if name and not ROLE_NAME_PATTERN.fullmatch(name):
        errors.append("name must use the codexteam_<role> form")
    description = _bounded_string(data.get("description"), "description", 500, errors)
    developer_instructions = _bounded_string(
        data.get("developer_instructions"),
        "developer_instructions",
        8_000,
        errors,
    )
    default_profile = data.get("default_profile")
    if not isinstance(default_profile, str):
        errors.append("default_profile must be a string")
        default_profile = ""
    else:
        try:
            validate_profile(default_profile)
        except PathValidationError as exc:
            errors.append(str(exc))
    default_reasoning_effort = data.get("default_reasoning_effort")
    if default_reasoning_effort not in REASONING_EFFORTS:
        errors.append(
            "default_reasoning_effort must be one of "
            + ", ".join(sorted(REASONING_EFFORTS))
        )
    sandbox_mode = data.get("sandbox_mode")
    if sandbox_mode not in SANDBOX_MODES:
        errors.append("sandbox_mode must be read-only or workspace-write")

    skill_files = _string_tuple(data.get("skill_files"), "skill_files", errors, required=True)
    allowed_patterns = _pattern_tuple(
        data.get("allowed_change_patterns"),
        "allowed_change_patterns",
        errors,
        required=True,
    )
    denied_patterns = _pattern_tuple(
        data.get("denied_change_patterns"),
        "denied_change_patterns",
        errors,
        required=False,
    )
    evidence_types = _string_tuple(
        data.get("allowed_evidence_types"),
        "allowed_evidence_types",
        errors,
        required=True,
    )
    unsupported_evidence = sorted(set(evidence_types) - EVIDENCE_TYPES)
    if unsupported_evidence:
        errors.append("unsupported evidence types: " + ", ".join(unsupported_evidence))
    mcp_servers_declared = "mcp_servers" in data
    mcp_servers = (
        _string_tuple(
            data.get("mcp_servers"),
            "mcp_servers",
            errors,
            required=False,
        )
        if mcp_servers_declared
        else ()
    )
    invalid_mcp_servers = sorted(
        server for server in mcp_servers if not MCP_SERVER_PATTERN.fullmatch(server)
    )
    if invalid_mcp_servers:
        errors.append(
            "mcp_servers must use names containing only letters, digits, hyphens, "
            "or underscores: " + ", ".join(invalid_mcp_servers)
        )
    mcp_tools_declared = "mcp_tools" in data
    mcp_tools = (
        _mcp_tool_mapping(data.get("mcp_tools"), errors)
        if mcp_tools_declared
        else ()
    )
    unlisted_tool_servers = sorted(
        server for server, _tools in mcp_tools if server not in mcp_servers
    )
    if unlisted_tool_servers:
        errors.append(
            "mcp_tools servers must also appear in mcp_servers: "
            + ", ".join(unlisted_tool_servers)
        )
    for server, tools in mcp_tools:
        catalog = LOCAL_MCP_TOOL_CATALOG.get(server)
        if catalog is None:
            continue
        unknown_tools = sorted(set(tools) - catalog)
        if unknown_tools:
            errors.append(
                f"mcp_tools for {server} contain unknown locally owned tools: "
                + ", ".join(unknown_tools)
            )

    if errors:
        raise RolePolicyError(f"invalid role policy {source_path}: " + "; ".join(errors))

    canonical = {
        "schema_version": schema_version,
        "role": role,
        "name": name,
        "description": description,
        "developer_instructions": developer_instructions,
        "default_profile": default_profile,
        "default_reasoning_effort": default_reasoning_effort,
        "sandbox_mode": sandbox_mode,
        "skill_files": list(skill_files),
        "allowed_change_patterns": list(allowed_patterns),
        "denied_change_patterns": list(denied_patterns),
        "allowed_evidence_types": list(evidence_types),
    }
    if mcp_servers_declared:
        canonical["mcp_servers"] = list(mcp_servers)
    if mcp_tools_declared:
        canonical["mcp_tools"] = {
            server: list(tools)
            for server, tools in mcp_tools
        }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RolePolicy(
        schema_version=schema_version,
        role=role,
        name=name,
        description=description,
        developer_instructions=developer_instructions,
        default_profile=default_profile,
        default_reasoning_effort=default_reasoning_effort,
        sandbox_mode=sandbox_mode,
        skill_files=skill_files,
        allowed_change_patterns=allowed_patterns,
        denied_change_patterns=denied_patterns,
        allowed_evidence_types=evidence_types,
        mcp_servers=mcp_servers,
        mcp_servers_declared=mcp_servers_declared,
        mcp_tools=mcp_tools,
        mcp_tools_declared=mcp_tools_declared,
        digest=digest,
        source_path=source_path,
    )


def load_all_role_policies(
    *,
    roles_root: str | Path = DEFAULT_ROLES_ROOT,
) -> tuple[RolePolicy, ...]:
    policies = tuple(
        load_role_policy(role, roles_root=roles_root)
        for role in sorted(AGENT_ROLES)
    )
    names = [policy.name for policy in policies]
    if len(names) != len(set(names)):
        raise RolePolicyError("role policy names must be unique")
    return policies


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect validated CodexTeam role policies.")
    parser.add_argument("--role", choices=tuple(sorted(AGENT_ROLES)))
    parser.add_argument("--roles-root", default=str(DEFAULT_ROLES_ROOT))
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policies = (
            (load_role_policy(args.role, roles_root=args.roles_root),)
            if args.role
            else load_all_role_policies(roles_root=args.roles_root)
        )
    except (FileNotFoundError, OSError, RolePolicyError) as exc:
        print(f"ERROR: {exc}")
        return 2
    payload = [policy.snapshot() for policy in policies]
    if args.json:
        print(json.dumps(payload[0] if args.role else payload, indent=2, sort_keys=True))
        return 0
    for policy in policies:
        print(
            f"{policy.role}: {policy.name}; profile={policy.default_profile}; "
            f"reasoning={policy.default_reasoning_effort}; policy={policy.digest[:12]}"
        )
    return 0


def _bounded_string(value: Any, field: str, maximum: int, errors: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")
        return ""
    clean = value.strip()
    if len(clean) > maximum:
        errors.append(f"{field} must be at most {maximum} characters")
    return clean


def _string_tuple(
    value: Any,
    field: str,
    errors: list[str],
    *,
    required: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in value
    ):
        errors.append(f"{field} must be a list of non-empty strings")
        return ()
    clean = tuple(item.strip() for item in value)
    if required and not clean:
        errors.append(f"{field} cannot be empty")
    if len(clean) != len(set(clean)):
        errors.append(f"{field} cannot contain duplicates")
    return clean


def _pattern_tuple(
    value: Any,
    field: str,
    errors: list[str],
    *,
    required: bool,
) -> tuple[str, ...]:
    patterns = _string_tuple(value, field, errors, required=required)
    for pattern in patterns:
        if pattern.startswith("/") or "\\" in pattern or ".." in pattern.split("/"):
            errors.append(f"unsafe {field} pattern: {pattern!r}")
    return patterns


def _mcp_tool_mapping(
    value: Any,
    errors: list[str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, dict):
        errors.append("mcp_tools must be an object mapping servers to tool lists")
        return ()
    if not value:
        errors.append("mcp_tools cannot be empty")
        return ()
    entries: list[tuple[str, tuple[str, ...]]] = []
    for server in sorted(value):
        if not isinstance(server, str) or not MCP_SERVER_PATTERN.fullmatch(server):
            errors.append(f"invalid mcp_tools server name: {server!r}")
            continue
        tools = _string_tuple(
            value[server],
            f"mcp_tools.{server}",
            errors,
            required=True,
        )
        invalid_tools = sorted(
            tool for tool in tools if not MCP_TOOL_PATTERN.fullmatch(tool)
        )
        if invalid_tools:
            errors.append(
                f"mcp_tools.{server} contains invalid tool names: "
                + ", ".join(invalid_tools)
            )
        entries.append((server, tools))
    return tuple(entries)


def _normalize_relative_file(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise RolePolicyError(f"unsafe project-relative file path: {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RolePolicyError(f"unsafe project-relative file path: {value!r}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
