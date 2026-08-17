from pathlib import Path

from codexteam_tools import spawn
from codexteam_tools.contracts import validate_handoff, validate_result
from codexteam_tools.roles import load_role_policy


def _profile(codex_home: Path, name: str, provider: str) -> None:
    model = "gpt-5.4-mini" if provider == "openai" else "qwen"
    (codex_home / f"{name}.config.toml").write_text(
        f'model = "{model}"\nmodel_provider = "{provider}"\n',
        encoding="utf-8",
    )


def _draft_args(workspace: Path, profile: str | None = None, reasoning: str | None = None):
    arguments = [
        "--phase",
        "draft",
        "--backend",
        "codex",
        "--team",
        "team-1",
        "--task",
        "T007",
        "--attempt",
        "att-001",
        "--role",
        "feature_planner",
        "--workspace",
        str(workspace),
        "--prompt",
        "Decompose the accepted feature design.",
        "--dry-run",
    ]
    if profile is not None:
        arguments[2:2] = ["--profile", profile]
    if reasoning is not None:
        arguments[2:2] = ["--reasoning-effort", reasoning]
    return spawn.build_parser().parse_args(arguments)


def test_feature_planner_manifest_has_advisory_only_boundary():
    policy = load_role_policy("feature_planner")

    assert policy.name == "codexteam_feature_planner"
    assert policy.skill_files == ("feature-planning.md",)
    assert policy.allows_change("results/T007-feature-plan.md")
    assert not policy.allows_change("ARCHITECTURE.md")
    assert not policy.allows_change("management/tasks/T008.md")
    assert not policy.allows_change("src/feature.py")
    assert not policy.allows_change("tests/test_feature.py")
    assert not policy.allows_change("TASKS.md")


def test_feature_planner_is_valid_in_handoff_and_result_contracts(result_factory):
    handoff = {
        "schema_version": "1.0",
        "handoff_id": "handoff-t007-att-001",
        "team_id": "team-1",
        "task_id": "T007",
        "attempt_id": "att-001",
        "agent_role": "feature_planner",
        "execution_spec": {
            "contract": "execution-spec", "path": "execution-spec.json",
            "digest": "a" * 64,
        },
        "workspace_root": "/tmp/project",
        "task_context": {"prompt": "Decompose the accepted feature design."},
        "constraints": {},
        "completion_criteria": ["Return an advisory feature plan."],
    }
    result = result_factory(
        task_id="T007",
        role="feature_planner",
        file_path="results/T007-feature-plan.md",
        artifact_ref="results/T007-feature-plan.md",
    )
    result["evidence"][0]["type"] = "artifact"

    assert validate_handoff(handoff) is handoff
    assert validate_result(result, expected_role="feature_planner") is result


def test_spawn_requires_explicit_curated_profile(
    tmp_path: Path, monkeypatch
):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    _profile(codex_home, "gpt54-mini", "openai")
    _profile(codex_home, "qwen36-27b", "ollama_local")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    default_workspace = tmp_path / "default-project"
    default_workspace.mkdir()
    import pytest
    with pytest.raises(ValueError, match="requires explicit"):
        spawn.prepare_request(_draft_args(default_workspace))
    default_request = spawn.prepare_request(_draft_args(default_workspace, "gpt54-mini", "high"))
    default_turn = spawn.prepare_turn(default_request)
    default_handoff = spawn.build_handoff(default_request)
    default_command = spawn.build_command(default_request, default_turn)

    assert default_request.profile == "gpt54-mini"
    assert default_request.role_policy.name == "codexteam_feature_planner"
    assert [path.name for path in default_request.skill_files] == [
        "feature-planning.md"
    ]
    assert default_handoff["agent_role"] == "feature_planner"
    assert default_handoff["instruction_bundle"]["files"] == [
        "feature-planning.md"
    ]
    assert any(
        argument.startswith("developer_instructions=")
        and "CodexTeam Feature Planner" in argument
        for argument in default_command
    )

    local_workspace = tmp_path / "local-project"
    local_workspace.mkdir()
    local_request = spawn.prepare_request(
        _draft_args(local_workspace, "qwen36-27b", "high")
    )
    assert local_request.profile == "qwen36-27b"
    assert local_request.model_provider == "ollama_local"
