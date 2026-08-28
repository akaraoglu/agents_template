from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from codexteam_tools.agent_specs import (
    AgentSpecError,
    agent_spec_from_mapping,
    effective_role_policy,
    load_agent_spec,
    resolve_agent_spec,
)
from codexteam_tools.roles import load_role_policy


def test_agent_spec_is_optional_for_every_protocol_role():
    for role in (
        "architect", "developer", "tester", "reviewer", "documenter",
        "feature_planner", "ux_designer", "git_steward", "leader",
    ):
        assert resolve_agent_spec(role, None) is None


@pytest.mark.parametrize(
    "spec_id",
    (
        "python-developer", "go-developer", "frontend-developer",
        "cpp-developer", "cpp-embedded-developer", "security-reviewer",
        "accessibility-reviewer", "agent-evaluator",
    ),
)
def test_pilot_agent_specs_are_valid_and_model_free(spec_id: str):
    spec = load_agent_spec(spec_id)
    raw = spec.source_path.read_text()
    for forbidden in ("model =", "backend =", "reasoning", "task_id", "stage"):
        assert forbidden not in raw
    assert spec.reference()["digest"] == spec.digest


def test_frontend_specialization_requires_complete_accessible_ui_evidence():
    guidance = (
        load_agent_spec("frontend-developer").source_path.parent
        / "guidance"
        / "frontend-specialization.md"
    ).read_text()
    compact_guidance = " ".join(guidance.split())
    for marker in (
        "design system",
        "semantic HTML before ARIA",
        "mobile and desktop",
        "loading, empty, error, success",
        "console errors and failed network requests",
        "visual-capture infrastructure",
    ):
        assert marker in compact_guidance


def test_security_specialization_is_read_only_and_outputs_a_threat_model():
    guidance = (
        load_agent_spec("security-reviewer").source_path.parent
        / "guidance"
        / "security-review-specialization.md"
    ).read_text()
    compact_guidance = " ".join(guidance.split())
    for marker in (
        "protected assets and security objectives",
        "actors, entry points, data flows, and trust boundaries",
        "credible abuse cases",
        "attacker preconditions and exploit path",
        "impact, likelihood, residual risk",
        "Remain read-only",
        "do not implement product changes",
    ):
        assert marker in compact_guidance


def test_agent_evaluator_is_narrow_and_prepared_packet_only():
    spec = load_agent_spec("agent-evaluator", expected_role="reviewer")
    effective = effective_role_policy(load_role_policy("reviewer"), spec)
    assert spec.allowed_change_patterns == ()
    assert spec.denied_change_patterns == ()
    assert spec.mcp_servers == ()
    assert spec.mcp_tools == ()
    assert spec.allowed_evidence_types == ()
    assert effective.allowed_change_patterns == load_role_policy("reviewer").allowed_change_patterns

    guidance = (spec.source_path.parent / "guidance" / "agent-evaluator.md").read_text()
    compact_guidance = " ".join(guidance.split())
    for marker in (
        "exact immutable preparation packet",
        "no tools, filesystem, retries, MCP, cloud access, project context",
        "established facts from hypotheses",
        "plausible alternatives",
        "state the discriminator",
        "investigation request from a concrete change proposal",
        "do not compare speed across unlike work",
        "E1", "E2", "E3", "NO_CHANGE",
        "exactly one JSON report",
        "Do not write or change any file",
        "creates no task", "grants no implementation authority",
    ):
        assert marker in compact_guidance


def test_agent_evaluator_is_reserved_from_normal_worker_resolution():
    with pytest.raises(AgentSpecError, match="dedicated execution path"):
        resolve_agent_spec("reviewer", "agent-evaluator")


def test_role_mismatch_is_rejected():
    with pytest.raises(AgentSpecError, match="base role mismatch"):
        load_agent_spec("security-reviewer", expected_role="developer")


def test_agent_spec_cannot_broaden_role_permissions(tmp_path: Path):
    base = load_role_policy("reviewer")
    source = tmp_path / "broad.toml"
    mapping = {
        "schema_version": "1.0", "agent_spec_id": "broad-developer",
        "version": "1.0", "base_role": "reviewer", "description": "bad",
        "capabilities": [], "guidance_files": [],
        "permission_overlay": {
            "allowed_change_patterns": ["**"], "denied_change_patterns": [],
            "mcp_servers": [], "mcp_tools": {},
            "allowed_evidence_types": [],
        },
    }
    spec = agent_spec_from_mapping(mapping, source_path=source)
    with pytest.raises(AgentSpecError, match="broadens role policy"):
        effective_role_policy(base, spec)


def test_effective_policy_intersects_paths_mcp_and_evidence(tmp_path: Path):
    base = load_role_policy("developer")
    mapping = {
        "schema_version": "1.0", "agent_spec_id": "narrow-developer",
        "version": "1.0", "base_role": "developer", "description": "narrow",
        "capabilities": [], "guidance_files": [],
        "permission_overlay": {
            "allowed_change_patterns": ["src/**"],
            "denied_change_patterns": ["src/generated/**"],
            "mcp_servers": ["local-docs"],
            "mcp_tools": {"local-docs": ["search_docs"]},
            "allowed_evidence_types": ["test_output", "artifact"],
        },
    }
    spec = agent_spec_from_mapping(mapping, source_path=tmp_path / "narrow.toml")
    effective = effective_role_policy(base, spec)
    assert effective.allows_change("src/main.py")
    assert not effective.allows_change("tests/unit/test_main.py")
    assert not effective.allows_change("src/generated/code.py")
    assert effective.mcp_servers == ("local-docs",)
    assert effective.tools_for_server("local-docs") == ("search_docs",)
    assert effective.allowed_evidence_types == ("test_output", "artifact")


def test_agent_spec_digest_changes_with_definition(tmp_path: Path):
    source = load_agent_spec("python-developer").source_path
    first = load_agent_spec("python-developer")
    root = tmp_path / "specs"
    shutil.copytree(source.parent, root)
    path = root / "python-developer.toml"
    path.write_text(path.read_text().replace("Python implementation", "Python service"))
    second = load_agent_spec("python-developer", root=root)
    assert first.digest != second.digest


def test_narrowing_one_mcp_server_preserves_other_base_tool_restrictions(tmp_path: Path):
    base = load_role_policy("developer")
    mapping = {
        "schema_version": "1.0", "agent_spec_id": "docs-developer",
        "version": "1.0", "base_role": "developer", "description": "docs",
        "capabilities": [], "guidance_files": [],
        "permission_overlay": {
            "allowed_change_patterns": [], "denied_change_patterns": [],
            "mcp_servers": ["codexteam-context", "local-docs"],
            "mcp_tools": {"local-docs": ["search_docs"]},
            "allowed_evidence_types": [],
        },
    }
    spec = agent_spec_from_mapping(mapping, source_path=tmp_path / "docs.toml")
    effective = effective_role_policy(base, spec)
    assert effective.tools_for_server("codexteam-context") == base.tools_for_server(
        "codexteam-context"
    )
    assert effective.tools_for_server("local-docs") == ("search_docs",)


def test_literal_path_can_narrow_wildcard_role_path(tmp_path: Path):
    base = load_role_policy("documenter")
    mapping = {
        "schema_version": "1.0", "agent_spec_id": "readme-documenter",
        "version": "1.0", "base_role": "documenter", "description": "readme",
        "capabilities": [], "guidance_files": [],
        "permission_overlay": {
            "allowed_change_patterns": ["README.md"], "denied_change_patterns": [],
            "mcp_servers": [], "mcp_tools": {}, "allowed_evidence_types": [],
        },
    }
    spec = agent_spec_from_mapping(mapping, source_path=tmp_path / "readme.toml")
    assert effective_role_policy(base, spec).allowed_change_patterns == ("README.md",)
