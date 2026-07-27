import json
import shutil
import tomllib
from pathlib import Path

import pytest

from codexteam_tools.roles import (
    DEFAULT_ROLES_ROOT,
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


def test_unknown_manifest_fields_are_rejected(tmp_path: Path):
    roles = tmp_path / "roles"
    shutil.copytree(DEFAULT_ROLES_ROOT, roles)
    manifest = roles / "developer.toml"
    manifest.write_text(manifest.read_text() + '\nunknown_setting = "no"\n')
    with pytest.raises(RolePolicyError, match="unknown fields"):
        load_role_policy("developer", roles_root=roles)


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

    assert "When the handoff explicitly contains `PLANNED LANE`" in (
        developer.developer_instructions
    )
    assert "do not modify files" in developer.developer_instructions
    assert "exact `PLAN ACCEPTED`" in developer.developer_instructions
    assert "PLAN Txxx/att-xxx" in implementation
    assert "same session" in implementation
    assert "run Chromium after implementation by default" in development_testing
    assert "Test Engineer owns the broader Chromium" in development_testing
    assert "Treat the next `DRAFT` as the implementation draft" in orchestration
    assert "Do not add a new task type, agent, result schema" in orchestration


def test_native_projection_source_manifests_are_valid_toml():
    for path in DEFAULT_ROLES_ROOT.glob("*.toml"):
        assert tomllib.loads(path.read_text())["role"] == path.stem
