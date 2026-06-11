import json
import subprocess
import sys
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_run_v4_team_dry_run_creates_and_completes_project(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "AgenticTeam/scripts/run_v4_team.py",
            "--dry-run",
            "--project-root",
            str(tmp_path),
            "--project-id",
            "tiny-markdown-counter-v4",
            "--title",
            "Tiny Markdown Counter",
            "--goal",
            "Create a Python CLI that counts lines, words, and characters.",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    project_dir = tmp_path / "tiny-markdown-counter-v4"
    assert f"V4_PROJECT_CREATED={project_dir}" in result.stdout
    assert "V4_TEAM_RESULT=DONE" in result.stdout

    state = json.loads((project_dir / ".openclaw" / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "DONE"
    assert state["waiting_for"] == "none"
    assert (project_dir / "management" / "tasks" / "T001.md").is_file()
    assert (project_dir / "README.md").is_file()
    assert (project_dir / "src" / "main.py").is_file()
    assert (project_dir / "tests" / "test_main.py").is_file()

    handoff_ledger = project_dir / ".openclaw" / "handoffs.jsonl"
    assert handoff_ledger.exists()
    assert handoff_ledger.read_text(encoding="utf-8") == ""


def test_neo_source_prompts_expose_only_v4_startup_path():
    combined = "\n".join(
        (REPO_ROOT / "AgenticTeam" / "agents" / "neo" / name).read_text(encoding="utf-8")
        for name in ("AGENT.md", "AGENTS.md", "SKILLS.md", "TOOLS.md")
    )

    assert "run_v4_team.sh" in combined
    assert "new_project.sh" not in combined
    assert "handoff.sh" not in combined
    assert "sessions_spawn" not in combined


def test_run_worker_task_final_no_result_blocks_project(tmp_path):
    from AgenticTeam.scripts.run_v4_team import run_worker_task
    from AgenticTeam.scripts.v4_smith import smith_plan_project

    smith_plan_project(
        str(tmp_path),
        "p1",
        "Demo",
        [{"task_id": "T001", "title": "Implement demo", "required_outputs": ["README.md"]}],
        goal="Create a demo.",
    )

    with mock.patch(
        "AgenticTeam.scripts.run_v4_team.V4OpenClawWorkerRunner.run",
        return_value="OpenClaw worker agent exited with code 1",
    ):
        assert run_worker_task(
            workspace_root=tmp_path,
            project_id="p1",
            task_id="T001",
            title="Implement demo",
            expected_artifacts=["README.md"],
            project_artifacts=["README.md"],
            dry_run=False,
            max_attempts=1,
            worker_backend="openclaw",
            worker_timeout_seconds=30,
        ) is False

    state = json.loads((tmp_path / ".openclaw" / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "BLOCKED"
    assert state["waiting_for"] == "smith"
    assert state["tasks"]["T001"]["status"] == "BLOCKED"
