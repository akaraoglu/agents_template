from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .contracts import AGENT_ROLES, EVIDENCE_TYPES
from .roles import MCP_SERVER_PATTERN, MCP_TOOL_PATTERN, RolePolicy

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENT_SPECS_ROOT = CODEXTEAM_ROOT / "agent_specs"
AGENT_SPEC_ID = re.compile(r"[a-z][a-z0-9-]{1,63}")
DEDICATED_AGENT_SPEC_IDS = {"agent-evaluator"}
AGENT_SPEC_FIELDS = {
    "schema_version", "agent_spec_id", "version", "base_role", "description",
    "capabilities", "guidance_files", "permission_overlay",
}
OVERLAY_FIELDS = {
    "allowed_change_patterns", "denied_change_patterns", "mcp_servers", "mcp_tools",
    "allowed_evidence_types",
}


class AgentSpecError(ValueError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    schema_version: str
    agent_spec_id: str
    version: str
    base_role: str
    description: str
    capabilities: tuple[str, ...]
    guidance_files: tuple[str, ...]
    allowed_change_patterns: tuple[str, ...]
    denied_change_patterns: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    mcp_tools: tuple[tuple[str, tuple[str, ...]], ...]
    allowed_evidence_types: tuple[str, ...]
    digest: str
    source_path: Path

    def reference(self) -> dict[str, str]:
        return {"id": self.agent_spec_id, "version": self.version, "digest": self.digest}

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "agent_spec_id": self.agent_spec_id,
            "version": self.version,
            "base_role": self.base_role,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "guidance_files": list(self.guidance_files),
            "permission_overlay": {
                "allowed_change_patterns": list(self.allowed_change_patterns),
                "denied_change_patterns": list(self.denied_change_patterns),
                "mcp_servers": list(self.mcp_servers),
                "mcp_tools": {server: list(tools) for server, tools in self.mcp_tools},
                "allowed_evidence_types": list(self.allowed_evidence_types),
            },
            "digest": self.digest,
        }

    def allows_change(self, relative_path: str) -> bool:
        if any(fnmatchcase(relative_path, pattern) for pattern in self.denied_change_patterns):
            return False
        return not self.allowed_change_patterns or any(
            fnmatchcase(relative_path, pattern) for pattern in self.allowed_change_patterns
        )


def load_agent_spec(
    agent_spec_id: str,
    *,
    expected_role: str | None = None,
    root: str | Path = DEFAULT_AGENT_SPECS_ROOT,
) -> AgentSpec:
    if not isinstance(agent_spec_id, str) or not AGENT_SPEC_ID.fullmatch(agent_spec_id):
        raise AgentSpecError(f"invalid AgentSpec ID: {agent_spec_id!r}")
    catalog = Path(root).expanduser().resolve(strict=True)
    candidate = catalog / f"{agent_spec_id}.toml"
    if candidate.is_symlink():
        raise AgentSpecError(f"AgentSpec must not be a symlink: {candidate}")
    path = candidate.resolve(strict=True)
    try:
        path.relative_to(catalog)
    except ValueError as exc:
        raise AgentSpecError(f"AgentSpec escapes catalog root: {path}") from exc
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise AgentSpecError(f"invalid AgentSpec TOML: {path}: {exc}") from exc
    return agent_spec_from_mapping(data, source_path=path, expected_role=expected_role)


def load_agent_spec_snapshot(path: str | Path, *, expected_role: str) -> AgentSpec:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise AgentSpecError(f"AgentSpec snapshot must not be a symlink: {candidate}")
    snapshot_path = candidate.resolve(strict=True)
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentSpecError(f"invalid AgentSpec snapshot: {snapshot_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentSpecError("AgentSpec snapshot must be an object")
    value = dict(data)
    digest = value.pop("digest", None)
    spec = agent_spec_from_mapping(value, source_path=snapshot_path, expected_role=expected_role)
    if digest != spec.digest:
        raise AgentSpecError(
            f"AgentSpec snapshot digest mismatch: expected {spec.digest}, found {digest}"
        )
    return replace(spec, digest=digest)


def resolve_agent_spec(
    role: str,
    selected: str | None,
    *,
    root: str | Path = DEFAULT_AGENT_SPECS_ROOT,
) -> AgentSpec | None:
    if role not in AGENT_ROLES:
        raise AgentSpecError(f"unsupported AgentSpec role: {role}")
    if selected is None:
        return None
    if selected in DEDICATED_AGENT_SPEC_IDS:
        raise AgentSpecError(
            f"AgentSpec {selected} is reserved for its dedicated execution path"
        )
    return load_agent_spec(selected, expected_role=role, root=root)


def guidance_paths(spec: AgentSpec) -> tuple[Path, ...]:
    root = spec.source_path.parent / "guidance"
    paths: list[Path] = []
    for name in spec.guidance_files:
        if Path(name).name != name or "\\" in name:
            raise AgentSpecError(f"unsafe AgentSpec guidance file: {name!r}")
        path = (root / name).resolve(strict=True)
        try:
            path.relative_to(root.resolve(strict=True))
        except ValueError as exc:
            raise AgentSpecError(f"AgentSpec guidance escapes catalog: {path}") from exc
        if path.is_symlink() or not path.is_file():
            raise AgentSpecError(f"AgentSpec guidance is missing or unsafe: {path}")
        paths.append(path)
    return tuple(paths)


def agent_spec_from_mapping(
    data: Any,
    *,
    source_path: Path,
    expected_role: str | None = None,
) -> AgentSpec:
    if not isinstance(data, dict):
        raise AgentSpecError("AgentSpec must be a TOML object")
    errors: list[str] = []
    missing = sorted(AGENT_SPEC_FIELDS - set(data))
    unknown = sorted(set(data) - AGENT_SPEC_FIELDS)
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    if data.get("schema_version") != "1.0" or data.get("version") != "1.0":
        errors.append("schema_version and version must be '1.0'")
    agent_spec_id = data.get("agent_spec_id")
    if not isinstance(agent_spec_id, str) or not AGENT_SPEC_ID.fullmatch(agent_spec_id):
        errors.append("agent_spec_id must be a lowercase hyphenated identifier")
        agent_spec_id = ""
    role_value = data.get("base_role")
    role = role_value if isinstance(role_value, str) else ""
    if role not in AGENT_ROLES:
        errors.append("base_role must be a protocol role")
    elif expected_role is not None and role != expected_role:
        errors.append(f"base role mismatch: expected {expected_role}, found {role}")
    description = _text(data.get("description"), "description", errors)
    capabilities = _strings(data.get("capabilities"), "capabilities", errors)
    if any(not AGENT_SPEC_ID.fullmatch(item) for item in capabilities):
        errors.append("capabilities must use lowercase hyphenated identifiers")
    guidance = _strings(data.get("guidance_files"), "guidance_files", errors)
    overlay = data.get("permission_overlay")
    if not isinstance(overlay, dict) or set(overlay) != OVERLAY_FIELDS:
        errors.append("permission_overlay fields do not match agent-spec")
        overlay = {}
    allowed = _patterns(overlay.get("allowed_change_patterns", []), "allowed_change_patterns", errors)
    denied = _patterns(overlay.get("denied_change_patterns", []), "denied_change_patterns", errors)
    servers = _strings(overlay.get("mcp_servers", []), "mcp_servers", errors)
    if any(not MCP_SERVER_PATTERN.fullmatch(server) for server in servers):
        errors.append("mcp_servers contain an invalid server name")
    tools = _tools(overlay.get("mcp_tools", {}), errors)
    if any(server not in servers for server, _ in tools):
        errors.append("mcp_tools servers must appear in mcp_servers")
    evidence = _strings(overlay.get("allowed_evidence_types", []), "allowed_evidence_types", errors)
    if set(evidence) - EVIDENCE_TYPES:
        errors.append("allowed_evidence_types contain unsupported values")
    if errors:
        raise AgentSpecError(f"invalid AgentSpec {source_path}: " + "; ".join(errors))
    canonical = {
        "schema_version": "1.0", "agent_spec_id": agent_spec_id, "version": "1.0",
        "base_role": role, "description": description,
        "capabilities": list(capabilities), "guidance_files": list(guidance),
        "permission_overlay": {
            "allowed_change_patterns": list(allowed), "denied_change_patterns": list(denied),
            "mcp_servers": list(servers), "mcp_tools": {server: list(items) for server, items in tools},
            "allowed_evidence_types": list(evidence),
        },
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return AgentSpec(
        "1.0", agent_spec_id, "1.0", role, description, capabilities, guidance,
        allowed, denied, servers, tools, evidence, digest, source_path,
    )


def effective_role_policy(base: RolePolicy, spec: AgentSpec) -> RolePolicy:
    if spec.base_role != base.role:
        raise AgentSpecError(f"AgentSpec {spec.agent_spec_id} does not match role {base.role}")
    if (
        not spec.capabilities and not spec.guidance_files
        and not spec.allowed_change_patterns and not spec.denied_change_patterns
        and not spec.mcp_servers and not spec.mcp_tools
        and not spec.allowed_evidence_types
    ):
        return base
    allowed = base.allowed_change_patterns
    if spec.allowed_change_patterns:
        for pattern in spec.allowed_change_patterns:
            if not any(_pattern_subset(pattern, ceiling) for ceiling in base.allowed_change_patterns):
                raise AgentSpecError(f"AgentSpec allowed path broadens role policy: {pattern}")
        allowed = spec.allowed_change_patterns
    denied = tuple(dict.fromkeys((*base.denied_change_patterns, *spec.denied_change_patterns)))
    evidence = base.allowed_evidence_types
    if spec.allowed_evidence_types:
        if not set(spec.allowed_evidence_types) <= set(base.allowed_evidence_types):
            raise AgentSpecError("AgentSpec evidence types broaden role policy")
        evidence = tuple(item for item in base.allowed_evidence_types if item in spec.allowed_evidence_types)
    servers = base.mcp_servers
    if spec.mcp_servers:
        if not set(spec.mcp_servers) <= set(base.mcp_servers):
            raise AgentSpecError("AgentSpec MCP servers broaden role policy")
        servers = tuple(server for server in base.mcp_servers if server in spec.mcp_servers)
    base_tools = dict(base.mcp_tools)
    tools = base.mcp_tools
    if spec.mcp_tools:
        overlay_tools = dict(spec.mcp_tools)
        narrowed: list[tuple[str, tuple[str, ...]]] = []
        for server in servers:
            base_selected = base_tools.get(server)
            selected = overlay_tools.get(server)
            if selected is None:
                if base_selected is not None:
                    narrowed.append((server, base_selected))
                continue
            if base_selected is not None and not set(selected) <= set(base_selected):
                raise AgentSpecError(f"AgentSpec MCP tools broaden role policy: {server}")
            narrowed.append(
                (
                    server,
                    tuple(item for item in base_selected if item in selected)
                    if base_selected is not None
                    else selected,
                )
            )
        tools = tuple(narrowed)
    return replace(
        base,
        developer_instructions=(
            base.developer_instructions
            + f"\n\nAgentSpec {spec.agent_spec_id}: {spec.description}"
            + (
                " Capabilities: " + ", ".join(spec.capabilities) + "."
                if spec.capabilities
                else ""
            )
        ),
        allowed_change_patterns=allowed,
        denied_change_patterns=denied,
        allowed_evidence_types=evidence,
        mcp_servers=servers,
        mcp_tools=tools,
    )


def effective_policy_digest(policy: RolePolicy) -> str:
    value = {
        "role": policy.role,
        "sandbox_mode": policy.sandbox_mode,
        "allowed_change_patterns": list(policy.allowed_change_patterns),
        "denied_change_patterns": list(policy.denied_change_patterns),
        "allowed_evidence_types": list(policy.allowed_evidence_types),
        "mcp_servers": list(policy.mcp_servers),
        "mcp_tools": {server: list(tools) for server, tools in policy.mcp_tools},
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _pattern_subset(candidate: str, ceiling: str) -> bool:
    if candidate == ceiling or ceiling == "**":
        return True
    if ceiling.endswith("/**") and candidate.startswith(ceiling[:-2]):
        return True
    if not any(char in candidate for char in "*?["):
        return fnmatchcase(candidate, ceiling)
    return False


def _text(value: Any, field: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        errors.append(f"{field} must be a non-empty string of at most 500 characters")
        return ""
    return value.strip()


def _strings(value: Any, field: str, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{field} must be a string list")
        return ()
    if len(value) != len(set(value)):
        errors.append(f"{field} cannot contain duplicates")
    return tuple(value)


def _patterns(value: Any, field: str, errors: list[str]) -> tuple[str, ...]:
    patterns = _strings(value, field, errors)
    for pattern in patterns:
        if pattern.startswith("/") or "\\" in pattern or ".." in pattern.split("/"):
            errors.append(f"unsafe {field} pattern: {pattern}")
    return patterns


def _tools(value: Any, errors: list[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, dict):
        errors.append("mcp_tools must be an object")
        return ()
    result = []
    for server in sorted(value):
        items = _strings(value[server], f"mcp_tools.{server}", errors)
        if any(not MCP_TOOL_PATTERN.fullmatch(item) for item in items):
            errors.append(f"mcp_tools.{server} contains an invalid tool name")
        result.append((server, items))
    return tuple(result)
