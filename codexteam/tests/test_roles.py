import json
import shutil
import tomllib
from pathlib import Path

import pytest

from codexteam_tools.roles import (
    DEFAULT_ROLES_ROOT,
    LOCAL_MCP_TOOL_CATALOG,
    RolePolicyError,
    load_all_role_policies,
    load_role_policy,
    load_role_policy_snapshot,
)


def test_all_canonical_role_policies_are_unique_and_complete():
    policies = load_all_role_policies()
    assert {policy.role for policy in policies} == {
        "architect",
        "developer",
        "documenter",
        "feature_planner",
        "git_steward",
        "leader",
        "reviewer",
        "tester",
        "ux_designer",
    }
    assert len({policy.name for policy in policies}) == 9
    assert len({policy.digest for policy in policies}) == 9
    assert load_role_policy("feature_planner").default_profile == "gpt54-mini"
    assert all(
        policy.default_profile == "qwen36-27b"
        for policy in policies
        if policy.role != "feature_planner"
    )
    assert load_role_policy("leader").mcp_servers == (
        "codexteam-context",
        "github-readonly",
    )
    assert load_role_policy("tester").mcp_servers == (
        "codexteam-context",
        "playwright",
    )
    assert load_role_policy("architect").mcp_servers == ("local-docs",)
    assert load_role_policy("developer").mcp_servers == (
        "codexteam-context",
        "local-docs",
    )
    assert load_role_policy("reviewer").mcp_servers == ("codexteam-context",)
    assert load_role_policy("git_steward").mcp_servers == ("codexteam-context",)
    assert all(
        not policy.mcp_servers
        for policy in policies
        if policy.role not in {
            "architect",
            "developer",
            "git_steward",
            "leader",
            "reviewer",
            "tester",
        }
    )
    assert load_role_policy("developer").tools_for_server("codexteam-context") == (
        "get_task_context",
        "search_repository",
        "get_gate_status",
        "get_change_summary",
    )
    assert load_role_policy("tester").tools_for_server("codexteam-context") == (
        "get_task_context",
        "get_change_summary",
        "get_gate_status",
    )
    assert load_role_policy("reviewer").tools_for_server("codexteam-context") == (
        "get_task_context",
        "get_attempt_summary",
        "validate_result_record",
        "get_gate_status",
        "get_change_summary",
    )
    assert load_role_policy("git_steward").tools_for_server(
        "codexteam-context"
    ) == (
        "get_task_context",
        "get_change_summary",
        "get_gate_status",
    )
    for policy in policies:
        for server, tools in policy.mcp_tools:
            catalog = LOCAL_MCP_TOOL_CATALOG.get(server)
            if catalog is not None:
                assert set(tools) <= catalog


def test_role_policy_snapshot_digest_is_stable(tmp_path: Path):
    policy = load_role_policy("tester")
    snapshot = tmp_path / "role-policy.json"
    snapshot.write_text(json.dumps(policy.snapshot()))

    loaded = load_role_policy_snapshot(snapshot, expected_role="tester")
    assert loaded.snapshot() == policy.snapshot()

    changed = json.loads(snapshot.read_text())
    changed["description"] += " changed"
    snapshot.write_text(json.dumps(changed))
    with pytest.raises(RolePolicyError, match="digest mismatch"):
        load_role_policy_snapshot(snapshot, expected_role="tester")


def test_legacy_role_policy_snapshot_without_mcp_servers_remains_valid(tmp_path: Path):
    policy = load_role_policy("documenter")
    assert policy.mcp_servers == ()
    assert policy.mcp_servers_declared is False
    snapshot = tmp_path / "role-policy.json"
    snapshot.write_text(json.dumps(policy.snapshot()))

    loaded = load_role_policy_snapshot(snapshot, expected_role="documenter")

    assert loaded.snapshot() == policy.snapshot()
    assert "mcp_servers" not in loaded.snapshot()


def test_unknown_manifest_fields_are_rejected(tmp_path: Path):
    roles = tmp_path / "roles"
    shutil.copytree(DEFAULT_ROLES_ROOT, roles)
    manifest = roles / "developer.toml"
    manifest.write_text(manifest.read_text() + '\nunknown_setting = "no"\n')
    with pytest.raises(RolePolicyError, match="unknown fields"):
        load_role_policy("developer", roles_root=roles)


def test_invalid_mcp_server_name_is_rejected(tmp_path: Path):
    roles = tmp_path / "roles"
    shutil.copytree(DEFAULT_ROLES_ROOT, roles)
    manifest = roles / "developer.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'mcp_servers = ["codexteam-context", "local-docs"]',
            'mcp_servers = ["unsafe.server"]',
        )
    )

    with pytest.raises(RolePolicyError, match="mcp_servers must use names"):
        load_role_policy("developer", roles_root=roles)


def test_mcp_tool_server_must_be_allowed(tmp_path: Path):
    roles = tmp_path / "roles"
    shutil.copytree(DEFAULT_ROLES_ROOT, roles)
    manifest = roles / "developer.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'mcp_servers = ["codexteam-context", "local-docs"]',
            'mcp_servers = ["local-docs"]',
        )
    )

    with pytest.raises(
        RolePolicyError,
        match="mcp_tools servers must also appear in mcp_servers",
    ):
        load_role_policy("developer", roles_root=roles)


def test_unknown_locally_owned_mcp_tool_is_rejected(tmp_path: Path):
    roles = tmp_path / "roles"
    shutil.copytree(DEFAULT_ROLES_ROOT, roles)
    manifest = roles / "developer.toml"
    manifest.write_text(
        manifest.read_text().replace(
            '"get_gate_status"',
            '"invented_context_tool"',
        )
    )

    with pytest.raises(
        RolePolicyError,
        match="unknown locally owned tools: invented_context_tool",
    ):
        load_role_policy("developer", roles_root=roles)


def test_empty_mcp_tool_mapping_is_rejected(tmp_path: Path):
    roles = tmp_path / "roles"
    shutil.copytree(DEFAULT_ROLES_ROOT, roles)
    manifest = roles / "reviewer.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'mcp_tools = { codexteam-context = ["get_task_context", "get_attempt_summary", "validate_result_record", "get_gate_status", "get_change_summary"] }',
            "mcp_tools = {}",
        )
    )

    with pytest.raises(RolePolicyError, match="mcp_tools cannot be empty"):
        load_role_policy("reviewer", roles_root=roles)


def test_role_policy_symlinks_are_rejected(tmp_path: Path):
    roles = tmp_path / "roles"
    shutil.copytree(DEFAULT_ROLES_ROOT, roles)
    manifest = roles / "developer.toml"
    source = roles / "developer-source.toml"
    manifest.rename(source)
    manifest.symlink_to(source.name)
    with pytest.raises(RolePolicyError, match="must not be a symlink"):
        load_role_policy("developer", roles_root=roles)


def test_role_boundaries_match_responsibilities():
    developer = load_role_policy("developer")
    tester = load_role_policy("tester")
    reviewer = load_role_policy("reviewer")
    documenter = load_role_policy("documenter")
    architect = load_role_policy("architect")
    feature_planner = load_role_policy("feature_planner")
    git_steward = load_role_policy("git_steward")

    assert developer.allows_change("src/main.py")
    assert developer.allows_change("tests/unit/test_algorithm.py")
    assert developer.allows_change("tests/smoke/test_startup.py")
    assert not developer.allows_change("TASKS.md")
    assert not developer.allows_change("PROJECT.md")
    assert not developer.allows_change(".codexteam/roles/developer.toml")
    assert not developer.allows_change("tests/integration/test_workflow.py")
    assert not developer.allows_change("golden/expected-output.txt")
    assert tester.allows_change("tests/integration/test_workflow.py")
    assert tester.allows_change("tests/regression/test_product_defect.py")
    assert tester.allows_change("golden/expected-output.txt")
    assert not tester.allows_change("tests/test_main.py")
    assert not tester.allows_change("tests/unit/test_algorithm.py")
    assert not tester.allows_change("tests/smoke/test_startup.py")
    assert not tester.allows_change("src/main.py")
    assert reviewer.allows_change("results/review.txt")
    assert not reviewer.allows_change("tests/test_main.py")
    assert documenter.allows_change("docs/usage.md")
    assert not documenter.allows_change("src/main.py")
    assert architect.allows_change("ARCHITECTURE.md")
    assert architect.allows_change("docs/decisions/ADR-0001.md")
    assert not architect.allows_change("src/main.py")
    assert not architect.allows_change("TASKS.md")
    assert feature_planner.allows_change("results/feature-plan.md")
    assert not feature_planner.allows_change("src/main.py")
    assert not feature_planner.allows_change("TASKS.md")
    assert not git_steward.allows_change("src/main.py")
    assert not git_steward.allows_change(".codexteam/runtime/git-steward/m1/plan.json")


def test_developer_and_test_engineer_have_distinct_testing_skills():
    developer = load_role_policy("developer")
    tester = load_role_policy("tester")

    assert list(developer.skill_files) == [
        "implementation.md",
        "development-testing.md",
    ]
    assert list(tester.skill_files) == [
        "integration-testing.md",
        "verification.md",
    ]
    assert "Test Engineer" in tester.developer_instructions
    assert "integration gate" in tester.developer_instructions


def test_developer_planned_lane_is_conditional_and_same_session():
    developer = load_role_policy("developer")
    root = DEFAULT_ROLES_ROOT.parent
    implementation = (root / ".agents/skills/implementation.md").read_text(
        encoding="utf-8"
    )
    development_testing = (
        root / ".agents/skills/development-testing.md"
    ).read_text(encoding="utf-8")
    orchestration = (
        root / ".agents/skills/subagent-orchestration.md"
    ).read_text(encoding="utf-8")
    capsule_playbook = (
        root / ".agents/playbooks/task-capsule-pilot.md"
    ).read_text(encoding="utf-8")

    assert "When the handoff explicitly contains `PLANNED LANE`" in (
        developer.developer_instructions
    )
    assert "do not modify files" in developer.developer_instructions
    assert "exact `PLAN ACCEPTED`" in developer.developer_instructions
    assert "PLAN Txxx/att-xxx" in implementation
    assert "same session" in implementation
    assert "CONTEXT GAP" in implementation
    assert "CAPSULE CHECKPOINT" not in implementation
    assert "Do not search personal memory" in implementation
    assert "CAPSULE CHECKPOINT" in capsule_playbook
    assert "Do not combine it with `PLANNED LANE`" in capsule_playbook
    assert sum(
        line.lstrip().startswith("--skill-file")
        for line in capsule_playbook.splitlines()
    ) == 3
    assert "run Chromium after implementation by default" in development_testing
    assert "Test Engineer owns the broader Chromium" in development_testing
    assert "Treat the next `DRAFT` as the implementation draft" in orchestration
    assert "Do not add a new task type, agent, result schema" in orchestration


def test_native_projection_source_manifests_are_valid_toml():
    for path in DEFAULT_ROLES_ROOT.glob("*.toml"):
        assert tomllib.loads(path.read_text())["role"] == path.stem
