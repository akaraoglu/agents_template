import json
import os
import subprocess
from pathlib import Path


CODEXTEAM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CODEXTEAM_ROOT.parent


def test_machine_schemas_are_valid_json():
    for path in sorted((CODEXTEAM_ROOT / "schemas").glob("*.json")):
        assert json.loads(path.read_text(encoding="utf-8"))["$schema"]

    result_schema = json.loads((CODEXTEAM_ROOT / "schemas" / "result.json").read_text(encoding="utf-8"))
    assert result_schema["properties"]["file_changes"]["items"]["required"] == ["path", "action"]
    assert result_schema["properties"]["evidence"]["items"]["required"] == ["type", "artifact_ref", "summary"]
    expected_roles = {
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
    handoff_schema = json.loads((CODEXTEAM_ROOT / "schemas" / "handoff.json").read_text(encoding="utf-8"))
    assert set(handoff_schema["properties"]["agent_role"]["enum"]) == expected_roles
    assert set(result_schema["properties"]["agent_role"]["enum"]) == expected_roles
    openai_schema = json.loads(
        (CODEXTEAM_ROOT / "schemas" / "result-openai.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(openai_schema["properties"]["agent_role"]["enum"]) == expected_roles
    assert openai_schema["properties"]["produced_at"]["pattern"] == "Z$"
    gate_schema = json.loads((CODEXTEAM_ROOT / "schemas" / "gate-record.json").read_text(encoding="utf-8"))
    assert "configuration_digest" in gate_schema["required"]
    assert "execution_surface" in gate_schema["properties"]
    assert "execution_surface" not in gate_schema["required"]
    role_schema = json.loads(
        (CODEXTEAM_ROOT / "schemas" / "role-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert role_schema["properties"]["digest"]["pattern"] == "^[a-f0-9]{64}$"
    assert role_schema["properties"]["mcp_tools"]["minProperties"] == 1


def test_openai_result_schema_is_a_strict_projection():
    stored = json.loads(
        (CODEXTEAM_ROOT / "schemas" / "result.json").read_text(encoding="utf-8")
    )
    output = json.loads(
        (CODEXTEAM_ROOT / "schemas" / "result-openai.json").read_text(
            encoding="utf-8"
        )
    )

    assert output["required"] == stored["required"]
    assert set(output["properties"]) == set(stored["properties"])

    def assert_strict_objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", ())) == set(node.get("properties", ()))
            if "const" in node or "enum" in node:
                assert "type" in node
            for value in node.values():
                assert_strict_objects(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict_objects(value)

    assert_strict_objects(output)


def test_documentation_has_no_obsolete_runtime_references():
    banned = (
        "talk_to_leader.py",
        "show_board.py",
        "run_codexteam_tests.py",
        "codexspace_a",
        "gemma4:12b",
        "PHASE19_SUMMARY_DONE",
        "src/codexteam/",
    )
    paths = list(CODEXTEAM_ROOT.rglob("*.md"))
    paths.extend((REPO_ROOT / ".agents" / "memory").glob("*.md"))
    for path in paths:
        content = path.read_text(encoding="utf-8")
        for marker in banned:
            assert marker not in content, f"obsolete reference {marker!r} in {path}"


def test_active_docs_describe_one_execution_system():
    readme = (CODEXTEAM_ROOT / "README.md").read_text(encoding="utf-8")
    scripts = (CODEXTEAM_ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
    assert "CodexTeam has one project execution system" in readme
    assert "Codex and OpenCode are supported backends" in readme
    assert "version selector" not in readme
    assert not (CODEXTEAM_ROOT / "scripts" / ("run-" + "project.sh")).exists()


def test_public_command_wrappers_are_executable_and_have_help():
    commands = (
        CODEXTEAM_ROOT / "scripts" / "init-project.py",
        CODEXTEAM_ROOT / "scripts" / "update-tasks.py",
        CODEXTEAM_ROOT / "scripts" / "verify-result.py",
        CODEXTEAM_ROOT / "scripts" / "inspect-role-policies.py",
        CODEXTEAM_ROOT / "scripts" / "manage-native-agents.py",
        CODEXTEAM_ROOT / "scripts" / "subagent-status.py",
        CODEXTEAM_ROOT / "scripts" / "sync-project-guidance.py",
        CODEXTEAM_ROOT / "scripts" / "run-test-gate.py",
        CODEXTEAM_ROOT / "scripts" / "git-steward.py",
        CODEXTEAM_ROOT / "scripts" / "close-loop.sh",
        CODEXTEAM_ROOT / ".agents" / "scripts" / "spawn-subagent.sh",
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for command in commands:
        assert os.access(command, os.X_OK), f"command is not executable: {command}"
        completed = subprocess.run(
            [str(command), "--help"],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "usage:" in completed.stdout.lower()


def test_documentation_index_targets_exist():
    expected = (
        "ARCHITECTURE_REVIEW.md",
        "CORE_DOMAIN_MODEL.md",
        "PUBLIC_CONTRACTS.md",
        "RUNTIME_LAYOUT.md",
        "USER_GUIDE.md",
        "SECURITY_GUIDE.md",
        "SECURITY_TEST_MATRIX.md",
        "E2E_ACCEPTANCE_PLAN.md",
        "COLD_START_CANARY_2026-07-17.md",
        "ADAPTER_GUIDE.md",
        "AGENT_SPECS.md",
        "OPTIONAL_INTERFACES.md",
        "TROUBLESHOOTING.md",
        "rules/project_isolation.md",
    )
    for relative in expected:
        assert (CODEXTEAM_ROOT / "docs" / relative).is_file()


def test_cold_start_project_lead_bootstrap_is_discoverable():
    agents = (CODEXTEAM_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    boot_path = CODEXTEAM_ROOT / ".agents" / "LEAD_BOOT.md"
    assert boot_path.is_file()
    boot = boot_path.read_text(encoding="utf-8")

    required_agents_markers = (
        "/home/alik/workspace/agent_template/codexteam",
        "CodexTeam Project Lead",
        ".agents/LEAD_BOOT.md",
        "Default New-Project Lifecycle",
        "./projects",
        "explicit execution instruction",
        "absolute `Created:` path",
        "shell redirection",
        "Handle it yourself",
        "do not spawn agents",
        "acceptance-level product check",
        "Keep orchestration proportional",
        "Do not repeat the same command or failure path",
        ".agents/skills/codexteam-self-improvement.md",
    )
    for marker in required_agents_markers:
        assert marker in agents

    required_boot_markers = (
        "./scripts/init-project.py",
        "--projects-root ./projects",
        "./.agents/scripts/spawn-subagent.sh",
        "--phase feedback",
        "./scripts/verify-result.py",
        "./scripts/close-loop.sh",
        "Initialization creates the canonical file structure and task scaffolding",
        "Copy the exact project ID and absolute `Created:` path",
        "autonomously manages the team",
        "--trust-parent-sandbox",
        ".agents/playbooks/nested-worker-sandbox.md",
        "same execution surface",
        "does not test model connectivity",
        "MCP is not required",
        "feature_planner",
        ".codexteam/lead-prompt-<task>-<attempt>.md",
        "jq '{status, summary, file_changes, evidence, errors, warnings, limitations}'",
        "30 minutes, 12 worker turns",
    )
    for marker in required_boot_markers:
        assert marker in boot


def test_run_guard_is_documented_as_opt_in_and_resumable():
    readme = (CODEXTEAM_ROOT / "README.md").read_text(encoding="utf-8")
    user_guide = (CODEXTEAM_ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    contracts = (CODEXTEAM_ROOT / "docs" / "PUBLIC_CONTRACTS.md").read_text(
        encoding="utf-8"
    )

    assert "--run-guard" in readme
    assert "three consecutive identical failed command results" in user_guide
    assert "command result over 32 KiB" in user_guide
    assert "broad repository" in user_guide
    assert "preserves a captured thread" in user_guide
    assert "timeout or opt-in Run Guard" in contracts


def test_root_facing_docs_use_guaranteed_base_folder_commands():
    paths = (
        CODEXTEAM_ROOT / "README.md",
        CODEXTEAM_ROOT / "scripts" / "README.md",
        CODEXTEAM_ROOT / "scripts" / "TOOLS-README.md",
        CODEXTEAM_ROOT / "docs" / "USER_GUIDE.md",
        CODEXTEAM_ROOT / ".agents" / "LEAD_BOOT.md",
        CODEXTEAM_ROOT / ".agents" / "capabilities" / "tools.md",
        CODEXTEAM_ROOT / ".agents" / "skills" / "project-init.md",
        CODEXTEAM_ROOT / ".agents" / "skills" / "subagent-orchestration.md",
    )
    stale_markers = (
        "codexteam/scripts/",
        "codexteam/.agents/scripts/",
        "\n./env-python/bin/python",
        "/home/alik/workspace/codexspace/projects/",
    )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        for marker in stale_markers:
            assert marker not in content, f"stale root command {marker!r} in {path}"

    readme = (CODEXTEAM_ROOT / "README.md").read_text(encoding="utf-8")
    tools = (CODEXTEAM_ROOT / ".agents" / "capabilities" / "tools.md").read_text(
        encoding="utf-8"
    )
    canonical_test_command = "../env-python/bin/python -m pytest -q tests"
    assert canonical_test_command in readme
    assert canonical_test_command in tools


def test_combined_cold_start_team_delivery_acceptance_is_documented():
    plan = (CODEXTEAM_ROOT / "docs" / "E2E_ACCEPTANCE_PLAN.md").read_text(
        encoding="utf-8"
    )
    required_markers = (
        "E2E-006: Cold Start Through Team Delivery",
        "do not inject the CodexTeam protocol",
        "absolute `Created:` path",
        "responsible-AI handoffs",
        "autonomous orchestration, not solo implementation",
        "persistent draft → feedback → final sessions",
        "shell redirection",
        "exact project path",
        "--trust-parent-sandbox",
        "approved host-level route",
        "dry run alone is not connectivity evidence",
        "Acceptance audit",
        "Proportional performance",
        "Schema-valid results and `DELIVERED` state do not override",
    )
    for marker in required_markers:
        assert marker in plan


def test_specialist_role_skills_have_complete_reusable_workflow_sections():
    required_headings = (
        "## Purpose",
        "## When To Use",
        "## Inputs Needed",
        "## Workflow",
        "## Commands To Run",
        "## Expected Output",
        "## Validation",
        "## Common Mistakes Or Failure Modes",
        "## Related Files",
    )
    for name in (
        "architecture-design.md",
        "feature-planning.md",
        "development-testing.md",
        "integration-testing.md",
        "git-steward.md",
        "ux-ui-design.md",
        "codexteam-self-improvement.md",
    ):
        content = (CODEXTEAM_ROOT / ".agents" / "skills" / name).read_text(
            encoding="utf-8"
        )
        for heading in required_headings:
            assert heading in content, f"missing {heading!r} in {name}"


def test_project_lead_progressively_discloses_self_improvement_workflow():
    lead = (
        CODEXTEAM_ROOT / ".agents" / "skills" / "project-lead.md"
    ).read_text(encoding="utf-8")
    skill = (
        CODEXTEAM_ROOT / ".agents" / "skills" / "codexteam-self-improvement.md"
    ).read_text(encoding="utf-8")

    assert "## Self-Improvement Boundary" in lead
    assert "At a stable boundary" in lead
    assert "Existing attempt bundles remain pinned" in lead
    assert "observed -> proposed -> candidate -> verified -> accepted" in skill
    assert "A negative case where the skill or tool should not activate" in skill
    assert "Loading all skills into every agent" in skill


def test_project_lead_context_mcp_workflow_is_discoverable_and_bounded():
    agents = (CODEXTEAM_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    lead = (
        CODEXTEAM_ROOT / ".agents" / "skills" / "project-lead.md"
    ).read_text(encoding="utf-8")
    skill = (
        CODEXTEAM_ROOT / ".agents" / "skills" / "team-context-mcp.md"
    ).read_text(encoding="utf-8")

    assert ".agents/skills/team-context-mcp.md" in agents
    assert ".agents/skills/team-context-mcp.md" in lead
    for tool in (
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
    ):
        assert f"`{tool}`" in skill
    assert "Do not call the full tool set as a routine preflight" in skill
    assert "context, not proof" in skill
    assert "one narrow fallback" in skill


def test_context_target_guidance_requires_exact_source_and_test_locators():
    lead = (
        CODEXTEAM_ROOT / ".agents" / "skills" / "project-lead.md"
    ).read_text(encoding="utf-8")
    breakdown = (
        CODEXTEAM_ROOT / ".agents" / "skills" / "task-breakdown.md"
    ).read_text(encoding="utf-8")

    assert "question, exact file" in lead
    assert "one source and one focused test target" in lead
    assert "Question:" in breakdown
    assert "Target:" in breakdown
    assert "Use:" in breakdown
    assert "a filename alone or `results/**` is not a target" in breakdown


def test_project_test_gate_template_defines_distinct_owners_and_ci_parity():
    content = (
        CODEXTEAM_ROOT / "templates" / "project" / "management" / "TEST_GATES.md"
    ).read_text(encoding="utf-8")
    required_markers = (
        "## Development Gate",
        "Owner: Developer",
        "## Integration Gate",
        "Owner: Test Engineer (`tester` protocol role)",
        "runs the Development Gate first",
        "External CI must invoke this command or an exact wrapper around it",
        "Every modified assertion, fixture expectation, or golden value",
        "same Developer session",
    )
    for marker in required_markers:
        assert marker in content
