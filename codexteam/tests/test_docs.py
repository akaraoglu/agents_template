import json
import os
import subprocess
from pathlib import Path


CODEXTEAM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CODEXTEAM_ROOT.parent


def test_machine_schemas_are_valid_json():
    for path in sorted((CODEXTEAM_ROOT / "schemas").glob("*.json")):
        assert json.loads(path.read_text(encoding="utf-8"))["$schema"]

    result_schema = json.loads((CODEXTEAM_ROOT / "schemas" / "result-v1.json").read_text(encoding="utf-8"))
    assert result_schema["properties"]["file_changes"]["items"]["required"] == ["path", "action"]
    assert result_schema["properties"]["evidence"]["items"]["required"] == ["type", "artifact_ref", "summary"]
    expected_roles = {
        "architect",
        "developer",
        "documenter",
        "git_steward",
        "leader",
        "reviewer",
        "tester",
    }
    handoff_schema = json.loads((CODEXTEAM_ROOT / "schemas" / "handoff-v1.json").read_text(encoding="utf-8"))
    assert set(handoff_schema["properties"]["agent_role"]["enum"]) == expected_roles
    assert set(result_schema["properties"]["agent_role"]["enum"]) == expected_roles
    gate_schema = json.loads((CODEXTEAM_ROOT / "schemas" / "gate-record-v1.json").read_text(encoding="utf-8"))
    assert "configuration_digest" in gate_schema["required"]


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
        ".codexteam/lead-prompt-<task>-<attempt>.md",
        "jq '{status, summary, file_changes, evidence, errors, warnings, limitations}'",
        "30 minutes, 12 worker turns",
    )
    for marker in required_boot_markers:
        assert marker in boot


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
        "development-testing.md",
        "integration-testing.md",
        "git-steward.md",
    ):
        content = (CODEXTEAM_ROOT / ".agents" / "skills" / name).read_text(
            encoding="utf-8"
        )
        for heading in required_headings:
            assert heading in content, f"missing {heading!r} in {name}"


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
