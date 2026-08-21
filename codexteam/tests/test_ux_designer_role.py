from pathlib import Path

from codexteam_tools import spawn
from codexteam_tools.contracts import validate_handoff, validate_result
from codexteam_tools.roles import load_role_policy


def test_ux_designer_manifest_has_design_only_boundary():
    policy = load_role_policy("ux_designer")

    assert policy.name == "codexteam_ux_designer"
    assert policy.skill_files == ("ux-ui-design.md",)
    assert policy.allows_change("docs/ux/dashboard-design.md")
    assert policy.allows_change("prototypes/dashboard/index.html")
    assert policy.allows_change("results/dashboard-design-qa.md")
    assert not policy.allows_change("src/dashboard.py")
    assert not policy.allows_change("static/webui.css")
    assert not policy.allows_change("tests/test_dashboard.py")
    assert not policy.allows_change("TASKS.md")


def test_ux_designer_is_valid_in_handoff_and_result_contracts(result_factory):
    handoff = {
        "schema_version": "1.0",
        "handoff_id": "handoff-t007-att-001",
        "team_id": "team-1",
        "task_id": "T007",
        "attempt_id": "att-001",
        "agent_role": "ux_designer",
        "execution_spec": {
            "contract": "execution-spec", "path": "execution-spec.json",
            "digest": "a" * 64,
        },
        "workspace_root": "/tmp/project",
        "task_context": {"prompt": "Design the dashboard."},
        "constraints": {},
        "completion_criteria": ["Return an implementation-ready design."],
    }
    result = result_factory(
        task_id="T007",
        role="ux_designer",
        file_path="docs/ux/dashboard-design.md",
    )

    assert validate_handoff(handoff) is handoff
    assert validate_result(result, expected_role="ux_designer") is result


def test_spawn_dry_run_preparation_selects_ux_policy_and_skill(
    tmp_path: Path, monkeypatch
):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "qwen36-27b.config.toml").write_text(
        'model = "qwen3.6-27b"\nmodel_provider = "ollama_local"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    workspace = tmp_path / "project"
    workspace.mkdir()
    args = spawn.build_parser().parse_args(
        [
            "--phase",
            "draft",
            "--backend",
            "codex",
            "--profile",
            "qwen36-27b",
            "--reasoning-effort",
            "high",
            "--team",
            "team-1",
            "--task",
            "T007",
            "--attempt",
            "att-001",
            "--role",
            "ux_designer",
            "--workspace",
            str(workspace),
            "--prompt",
            "Design the dashboard.",
            "--dry-run",
        ]
    )

    request = spawn.prepare_request(args)
    turn = spawn.prepare_turn(request)
    handoff = spawn.build_handoff(request)
    command = spawn.build_command(request, turn)

    assert request.role_policy.name == "codexteam_ux_designer"
    assert [path.name for path in request.skill_files] == ["ux-ui-design.md"]
    assert handoff["agent_role"] == "ux_designer"
    assert handoff["instruction_bundle"]["files"] == ["ux-ui-design.md"]
    assert len(handoff["instruction_bundle"]["digest"]) == 64
    assert any(
        argument.startswith("developer_instructions=")
        and "CodexTeam UX/UI Designer" in argument
        for argument in command
    )
