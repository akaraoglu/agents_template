from __future__ import annotations

import json
from pathlib import Path

import pytest

from codexteam_tools import webui


TASKS = """# Tasks

| Task ID | Description | Status | Owner | Verification | Evidence |
|---------|-------------|--------|-------|--------------|----------|
| T001 | Implement the product | Completed | developer-01 | Passed | `results/T001-verification.txt` |
| T002 | Verify the product | In Progress | tester-01 | Pending | Pending |
"""


def write_project(
    root: Path,
    project_id: str,
    *,
    status: str = "ACTIVE",
    report: bool = True,
    input_tokens: int | None = 250,
    output_tokens: int = 30,
    updated_at: str = "2026-07-22T09:00:10Z",
) -> Path:
    project = root / project_id
    project.mkdir()
    (project / "PROJECT.md").write_text(f"# {project_id}\n", encoding="utf-8")
    (project / "PROJECT_STATE.md").write_text(
        f"# Project State\n\n- Status: {status}\n- Active Task: T002\n- Updated At: {updated_at}\n",
        encoding="utf-8",
    )
    (project / "TASKS.md").write_text(TASKS, encoding="utf-8")
    if report:
        results = project / "results"
        results.mkdir()
        (results / "e2e-report.md").write_text(
            """# E2E Report

- Elapsed seconds: 10
- Lifecycle verdict: PASS
- Product verdict: PASS
- Evidence verdict: PASS
- Management verdict: PASS
- Manifest verdict: PASS
- Performance verdict: PASS
""",
            encoding="utf-8",
        )

    session = project / ".codexteam/runtime/sessions" / project_id / "T001" / "att-001"
    turns = session / "turns"
    turns.mkdir(parents=True)
    session_data = {
        "task_id": "T001",
        "attempt_id": "att-001",
        "model_profile": "qwen36-27b",
        "model_provider": "ollama_local",
        "last_phase": "final",
        "last_status": "finalized",
        "turn_count": 3,
        "created_at": "2026-07-22T09:00:00Z",
        "updated_at": "2026-07-22T09:00:09Z",
        "turns": [
            {"number": 1, "phase": "draft", "status": "draft_ready", "duration_seconds": 2},
            {"number": 2, "phase": "feedback", "status": "correction_needed", "duration_seconds": 1},
            {"number": 3, "phase": "final", "status": "finalized", "duration_seconds": 3},
        ],
    }
    (session / "session.json").write_text(json.dumps(session_data), encoding="utf-8")
    for number, phase in ((1, "draft"), (2, "feedback"), (3, "final")):
        events = [{"type": "turn.started"}]
        if input_tokens is not None:
            events.append(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": input_tokens if number == 3 else number * 50,
                        "cached_input_tokens": 50 if number == 3 else 0,
                        "output_tokens": output_tokens if number == 3 else number * 5,
                    },
                }
            )
        (turns / f"{number:03d}-{phase}.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
    return project


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_load_project_aggregates_existing_artifacts(tmp_path: Path):
    project = write_project(tmp_path, "active-run")
    failed_session = project / ".codexteam/runtime/sessions/active-run/T002/att-001"
    turns = failed_session / "turns"
    turns.mkdir(parents=True)
    failed = {
        "task_id": "T002",
        "attempt_id": "att-001",
        "model_profile": "gpt54-mini",
        "model_provider": "openai",
        "last_phase": "draft",
        "last_status": "turn_failed",
        "last_turn_path": ".codexteam/runtime/sessions/active-run/T002/att-001/turns/001-draft.txt",
        "turn_count": 1,
        "created_at": "2026-07-22T09:00:05Z",
        "updated_at": "2026-07-22T09:00:10Z",
        "turns": [{"number": 1, "phase": "draft", "status": "turn_failed", "duration_seconds": 4}],
    }
    (failed_session / "session.json").write_text(json.dumps(failed), encoding="utf-8")
    (turns / "001-draft.jsonl").write_text('{"type":"turn.failed","message":"worker stopped"}\n', encoding="utf-8")
    (turns / "001-draft.stderr.txt").write_text("worker stopped\n", encoding="utf-8")

    loaded = webui.load_project(tmp_path, "active-run")

    assert loaded["status"] == "ACTIVE"
    assert loaded["task_total"] == 2
    assert loaded["task_completed"] == 1
    assert loaded["task_failed"] == 1
    assert loaded["turns"] == 4
    assert loaded["corrections"] == 1
    assert loaded["failed_turns"] == 2
    assert loaded["elapsed_seconds"] == 10
    assert loaded["elapsed_source"] == "E2E report"
    assert loaded["local_tokens"] == 280
    assert loaded["local_tokens"] != 445  # Per-turn cumulative records must not be summed.
    assert loaded["local_input_tokens"] == 250
    assert loaded["local_output_tokens"] == 30
    assert loaded["cloud_tokens"] is None
    assert loaded["cloud_input_tokens"] is None
    assert loaded["cloud_output_tokens"] is None
    assert loaded["cached_tokens"] is None
    assert loaded["error"] == "worker stopped"
    assert loaded["diagnostic_path"].endswith("001-draft.stderr.txt")
    assert [task["id"] for task in loaded["tasks"]] == ["T002", "T001"]
    tasks = {task["id"]: task for task in loaded["tasks"]}
    assert tasks["T001"]["duration_seconds"] == 6
    assert tasks["T001"]["owner"] == "developer-01"
    assert tasks["T001"]["profile"] == "qwen36-27b"
    assert tasks["T001"]["attempts"][0]["turn_details"][0]["phase"] == "draft"
    assert [phase["state"] for phase in tasks["T001"]["phases"]] == ["complete", "warning", "complete", "complete", "complete"]
    assert tasks["T002"]["needs_attention"] is True
    assert loaded["verdicts"]["manifest"] == "PASS"


def test_missing_metrics_are_unknown_and_project_states_list(tmp_path: Path):
    for project_id, status in (
        ("active", "ACTIVE"),
        ("delivered", "DELIVERED"),
        ("failed", "FAILED"),
    ):
        write_project(tmp_path, project_id, status=status)
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "PROJECT.md").write_text("# Incomplete\n", encoding="utf-8")

    projects = webui.list_projects(tmp_path)
    assert {item["id"] for item in projects} == {"active", "delivered", "failed", "incomplete"}
    missing = next(item for item in projects if item["id"] == "incomplete")
    assert missing["status"] == "unknown"
    assert missing["elapsed_seconds"] is None
    assert missing["cloud_tokens"] is None
    assert all(value == "unknown" for value in missing["verdicts"].values())

    response = webui.create_app(tmp_path).test_client().get("/projects/incomplete")
    assert response.status_code == 200
    assert b"unknown" in response.data


def test_noncanonical_multi_table_ledger_remains_visible(tmp_path: Path):
    project = write_project(tmp_path, "extended")
    ledger = (project / "TASKS.md").read_text(encoding="utf-8")
    ledger = ledger.replace("| T001 | Implement the product | Completed |", "| T001 | Implement the product | Completed — ACCEPT |")
    ledger += """

## Later tasks

| T003 | Add the project view | Planned | web-developer | Pending | Pending |
"""
    (project / "TASKS.md").write_text(ledger, encoding="utf-8")

    loaded = webui.load_project(tmp_path, "extended")

    assert loaded["task_total"] == 3
    assert {task["id"] for task in loaded["tasks"]} == {"T001", "T002", "T003"}


def test_interrupted_turn_uses_persisted_status_and_jsonl_diagnostic(tmp_path: Path):
    project = write_project(tmp_path, "interrupted")
    session_path = project / ".codexteam/runtime/sessions/interrupted/T001/att-001/session.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    session["last_status"] = "interrupted"
    session["last_turn_path"] = ".codexteam/runtime/sessions/interrupted/T001/att-001/turns/003-final.txt"
    session["turns"][-1]["status"] = "interrupted"
    session_path.write_text(json.dumps(session), encoding="utf-8")

    loaded = webui.load_project(tmp_path, "interrupted")
    task = loaded["tasks"][0]
    assert task["failed_turns"] == 2
    assert task["error"] == "interrupted"
    assert task["diagnostic_path"].endswith("003-final.jsonl")


def test_product_only_report_does_not_replace_session_elapsed_time(tmp_path: Path):
    project = write_project(tmp_path, "product-only")
    report = project / "results/e2e-report.md"
    report.write_text(
        report.read_text(encoding="utf-8").replace("- Elapsed seconds: 10", "- Profile: `product-only`\n- Elapsed seconds: 0"),
        encoding="utf-8",
    )
    loaded = webui.load_project(tmp_path, "product-only")
    assert loaded["elapsed_seconds"] == 10
    assert loaded["elapsed_source"] == "session timestamps"


def test_routes_render_escape_reload_and_never_write(tmp_path: Path):
    project = write_project(tmp_path, "render-run")
    (project / "PROJECT.md").write_text("# <script>alert(1)</script>\n", encoding="utf-8")
    commit_record = project / ".codexteam/runtime/git-steward/milestone-001/commit-record.json"
    commit_record.parent.mkdir(parents=True)
    commit_record.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "committed",
                "boundary_id": "milestone-001",
                "branch": "main",
                "head_after": "1234567890abcdef1234567890abcdef12345678",
                "commit_subject": "feat: complete verified slice",
                "committed_at": "2026-07-22T09:01:00Z",
                "committed_paths": ["src/main.py", "tests/test_main.py"],
            }
        ),
        encoding="utf-8",
    )
    client = webui.create_app(tmp_path).test_client()
    before = snapshot(tmp_path)

    listing = client.get("/")
    detail = client.get("/projects/render-run")
    assert listing.status_code == detail.status_code == 200
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in detail.data
    assert b"<script>alert(1)</script>" not in detail.data
    assert b"developer-01" in detail.data and b"qwen36-27b" in detail.data
    assert b"Task execution" in detail.data
    assert b"Milestone commits" in detail.data
    assert b"1234567890ab" in detail.data
    assert b"feat: complete verified slice" in detail.data
    assert b"Draft" in detail.data and b"Feedback" in detail.data and b"Verify" in detail.data
    assert b"Compare runs" not in listing.data
    assert snapshot(tmp_path) == before

    state = project / "PROJECT_STATE.md"
    state.write_text(state.read_text(encoding="utf-8").replace("ACTIVE", "DELIVERED"), encoding="utf-8")
    assert b"DELIVERED" in client.get("/projects/render-run").data
    after_expected_operator_change = snapshot(tmp_path)
    client.get("/")
    assert client.get("/compare").status_code == 404
    assert snapshot(tmp_path) == after_expected_operator_change
    assert before != after_expected_operator_change

    for method in (client.post, client.put, client.delete):
        assert method("/projects/render-run").status_code == 405


def test_theme_menu_defaults_to_system_and_serves_three_modes(tmp_path: Path):
    write_project(tmp_path, "theme-run")
    client = webui.create_app(tmp_path).test_client()

    markup = client.get("/").data
    script = client.get("/static/theme.js")
    stylesheet = client.get("/static/webui.css")

    assert b'id="theme-select"' in markup
    assert markup.index(b'value="system" selected') < markup.index(b'value="light"') < markup.index(b'value="dark"')
    assert b"System Default" in markup
    assert script.status_code == stylesheet.status_code == 200
    assert b"codexteam-theme" in script.data and b"localStorage" in script.data
    assert b':root[data-theme="dark"]' in stylesheet.data
    assert b"prefers-color-scheme: dark" in stylesheet.data
    assert b".attempt" in stylesheet.data and b"background: white" not in stylesheet.data


def test_projects_are_ordered_by_latest_activity(tmp_path: Path):
    write_project(tmp_path, "older", updated_at="2026-07-22T10:00:00Z")
    write_project(tmp_path, "newest", updated_at="2026-07-22T12:00:00Z")
    write_project(tmp_path, "middle", updated_at="2026-07-22T11:00:00Z")

    projects = webui.list_projects(tmp_path)

    assert [project["id"] for project in projects] == ["newest", "middle", "older"]
    listing = webui.create_app(tmp_path).test_client().get("/").data
    assert listing.index(b"newest") < listing.index(b"middle") < listing.index(b"older")


def test_invalid_unknown_and_symlink_projects_are_rejected(tmp_path: Path):
    write_project(tmp_path, "real")
    outside = tmp_path.parent / "outside-project"
    outside.mkdir(exist_ok=True)
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    client = webui.create_app(tmp_path).test_client()

    assert client.get("/projects/missing").status_code == 404
    assert client.get("/projects/..%2Foutside-project").status_code == 404
    assert client.get("/projects/linked").status_code == 404
    assert "linked" not in [item["id"] for item in webui.list_projects(tmp_path)]
    assert client.get("/compare?baseline=real").status_code == 404


def test_main_binds_only_to_loopback(monkeypatch: pytest.MonkeyPatch):
    observed = {}

    def fake_run(self, **kwargs):
        observed.update(kwargs)

    monkeypatch.setattr(webui.Flask, "run", fake_run)
    assert webui.main() == 0
    assert observed == {"host": "127.0.0.1", "port": 5000, "debug": False, "use_reloader": False}
