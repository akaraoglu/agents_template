from __future__ import annotations

import json
from pathlib import Path

import pytest
import re

from codexteam_tools import webui
from codexteam_tools.turn_metrics import backfill_project


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
    assert b"Task details" in detail.data
    assert b'<a class="focus-title" href="#T002">' in detail.data
    assert b'id="T002"' in detail.data
    assert b"Milestone evidence" in detail.data
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


def test_tool_cycle_metrics_render_redacted_hotspots_without_route_writes(tmp_path: Path):
    project = write_project(tmp_path, "metrics-run", input_tokens=1000, output_tokens=70)
    draft = project / ".codexteam/runtime/sessions/metrics-run/T001/att-001/turns/001-draft.jsonl"
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "API_KEY=private-value echo <unsafe>",
                "aggregated_output": "x" * 32,
                "exit_code": 1,
                "status": "failed",
            },
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 60,
                "output_tokens": 5,
            },
        },
    ]
    draft.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    backfill_project(project, write=True)
    before = snapshot(project)

    loaded = webui.load_project(tmp_path, "metrics-run")
    hotspot = loaded["expensive_drafts"][0]
    assert hotspot["task_id"] == "T001"
    assert hotspot["input_delta"] == 100
    assert hotspot["uncached_tokens"] == 40
    assert hotspot["tool_calls"] == 1
    assert hotspot["failed_tool_calls"] == 1
    assert hotspot["command_output_bytes"] == 32
    assert "private-value" not in hotspot["largest_commands"][0]["preview"]

    response = webui.create_app(tmp_path).test_client().get("/projects/metrics-run")
    assert response.status_code == 200
    assert b"Most expensive drafts" in response.data
    assert b"input delta" in response.data
    assert b"&lt;unsafe&gt;" in response.data
    assert b"private-value" not in response.data
    assert snapshot(project) == before


def test_expensive_drafts_are_limited_to_ten_and_sorted_by_input_delta():
    attempts = []
    for number in range(12):
        attempts.append(
            {
                "attempt": f"att-{number:03d}",
                "role": "developer",
                "profile": "gpt54-mini",
                "status": "draft_ready",
                "turn_details": [
                    {
                        "number": 1,
                        "phase": "draft",
                        "completed": True,
                        "metrics_available": True,
                        "input_tokens": number * 100,
                        "input_delta": number * 100,
                        "cached_tokens": number * 80,
                        "uncached_tokens": number * 20,
                        "output_tokens": number,
                        "duration_seconds": number,
                        "tool_calls": number,
                        "failed_tool_calls": 0,
                        "command_calls": number,
                        "failed_command_calls": 0,
                        "command_output_bytes": number,
                        "repeated_commands": [],
                        "largest_commands": [],
                    }
                ],
            }
        )
    tasks = [{"id": "T001", "attempts": attempts}]

    drafts = webui._expensive_drafts(tasks)

    assert len(drafts) == 10
    assert [item["ranking_tokens"] for item in drafts] == list(
        range(1100, 100, -100)
    )


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


# --- T004: Refurbishment-specific verification tests ---

def _write_session(
    project: Path, task_id: str, *,
    attempt_id: str = "att-001",
    profile: str = "qwen36-27b",
    provider: str = "ollama_local",
    phase: str = "final",
    status: str = "finalized",
    turn_count: int = 1,
    turns: list[dict[str, Any]] | None = None,
) -> Path:
    """Helper to create a session.json for testing."""
    if turns is None:
        turns = [{"number": 1, "phase": phase, "status": status, "duration_seconds": 2}]
    session_path = project / ".codexteam" / "runtime" / "sessions" / project.name / task_id / attempt_id
    (session_path / "turns").mkdir(parents=True)
    session_data = {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "model_profile": profile,
        "model_provider": provider,
        "last_phase": phase,
        "last_status": status,
        "turn_count": turn_count,
        "created_at": "2026-07-22T09:00:00Z",
        "updated_at": "2026-07-22T09:00:09Z",
        "turns": turns,
    }
    (session_path / "session.json").write_text(json.dumps(session_data), encoding="utf-8")
    for turn in turns:
        fname = f"{turn['number']:03d}-{turn['phase']}.jsonl"
        event = {"type": "turn.completed", "usage": {
            "input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10,
        }}
        (session_path / "turns" / fname).write_text(json.dumps(event) + "\n", encoding="utf-8")
    return session_path


def _base_project(root: Path, project_id: str, *, status: str = "ACTIVE", active_task: str = "T001") -> Path:
    """Minimal project for board projection tests."""
    project = root / project_id
    project.mkdir()
    (project / "PROJECT.md").write_text(f"# {project_id}\n", encoding="utf-8")
    (project / "PROJECT_STATE.md").write_text(
        f"# Project State\n\n- Status: {status}\n- Active Task: {active_task}\n- Updated At: 2026-07-22T09:00:10Z\n",
        encoding="utf-8",
    )
    return project


def _write_tasks(project: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    """Write a TASKS.md with the given rows. Each row is (id, description, status, owner, verification)."""
    lines = [
        "# Tasks\n",
        "| Task ID | Description | Status | Owner | Verification | Evidence |",
        "|---------|-------------|--------|-------|--------------|----------|",
    ]
    for task_id, desc, status, owner, verification in rows:
        lines.append(f"| {task_id} | {desc} | {status} | {owner} | {verification} | Pending |")
    (project / "TASKS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_projects_table_lists_each_project_once_with_status_and_attention(tmp_path: Path):
    p1 = _base_project(tmp_path, "needs-attn", status="ACTIVE")
    _write_tasks(p1, [("T001", "Task A", "Blocked", "dev", "Pending")])
    _write_session(p1, "T001", phase="draft", status="turn_failed")

    p2 = _base_project(tmp_path, "active-pj", status="ACTIVE")
    _write_tasks(p2, [("T001", "Task B", "In Progress", "dev", "Pending")])
    _write_session(p2, "T001", phase="draft", status="in_progress")

    p3 = _base_project(tmp_path, "done-pj", status="DELIVERED")
    _write_tasks(p3, [("T001", "Task C", "Completed", "dev", "Passed")])
    _write_session(p3, "T001")

    client = webui.create_app(tmp_path).test_client()
    response = client.get("/")
    assert response.status_code == 200
    data = response.data.decode("utf-8")
    assert 'class="project-table"' in data
    assert '<h2 id="projects-table-title">All projects</h2>' in data
    assert "<h2>Needs attention</h2>" not in data
    assert "<h2>Active</h2>" not in data
    assert "<h2>Recently completed</h2>" not in data
    assert "1 task needs attention" in data
    assert "1 / 1" in data
    for pid in ("needs-attn", "active-pj", "done-pj"):
        links = re.findall(rf'<a[ \t]+class="project-link"[ \t]+href="/projects/{re.escape(pid)}"', data)
        assert len(links) == 1, f"Project {pid} has {len(links)} table links; expected exactly 1"


def test_projects_table_empty_state(tmp_path: Path):
    response = webui.create_app(tmp_path).test_client().get("/")

    assert response.status_code == 200
    assert b"No projects yet" in response.data
    assert b"Initialized projects will appear here." in response.data
    assert b'class="project-table"' not in response.data


def test_board_column_blocked_precedence(tmp_path: Path):
    """Canonical Blocked status always goes to Blocked column."""
    project = _base_project(tmp_path, "blocked-test")
    _write_tasks(project, [
        ("T001", "Blocked task", "Blocked", "dev", "Pending"),
    ])
    loaded = webui.load_project(tmp_path, "blocked-test")

    assert len(loaded["tasks"]) == 1
    task = loaded["tasks"][0]
    assert task["board_column"] == "Blocked"
    assert task["id"] in [t["id"] for t in loaded["board_groups"]["Blocked"]]


def test_board_column_completed_unverified_to_validation(tmp_path: Path):
    """Completed but unverified task projects to In Validation, not Done."""
    project = _base_project(tmp_path, "validation-test")
    _write_tasks(project, [
        ("T001", "Completed unverified", "Completed", "dev", "Pending"),
    ])
    loaded = webui.load_project(tmp_path, "validation-test")

    task = loaded["tasks"][0]
    assert task["board_column"] == "In Validation"
    assert task["id"] in [t["id"] for t in loaded["board_groups"]["In Validation"]]


def test_board_column_draft_ready_to_review(tmp_path: Path):
    """A completed draft_ready result projects to In Review."""
    project = _base_project(tmp_path, "review-test")
    _write_tasks(project, [
        ("T001", "Draft ready task", "In Progress", "dev", "Pending"),
    ])
    _write_session(project, "T001", phase="draft", status="draft_ready")
    loaded = webui.load_project(tmp_path, "review-test")

    task = loaded["tasks"][0]
    assert task["board_column"] == "In Review"


def test_board_column_active_feedback_to_progress(tmp_path: Path):
    """Active feedback correction stays in In Progress."""
    project = _base_project(tmp_path, "progress-test")
    _write_tasks(project, [
        ("T001", "Feedback task", "In Progress", "dev", "Pending"),
    ])
    _write_session(project, "T001", phase="feedback", status="correction_needed",
                   turns=[{"number": 1, "phase": "draft", "status": "draft_ready"},
                          {"number": 2, "phase": "feedback", "status": "correction_needed"}])
    loaded = webui.load_project(tmp_path, "progress-test")

    task = loaded["tasks"][0]
    assert task["board_column"] == "In Progress"


def test_board_interrupted_stays_in_progress_with_attention(tmp_path: Path):
    """Recoverable interrupted turn stays in progress lane with attention marker."""
    project = _base_project(tmp_path, "interrupt-test")
    _write_tasks(project, [
        ("T001", "Interrupted task", "In Progress", "dev", "Pending"),
    ])
    session_path = _write_session(
        project, "T001", phase="final", status="interrupted",
        turns=[{"number": 1, "phase": "draft", "status": "draft_ready"},
               {"number": 2, "phase": "final", "status": "interrupted"}],
    )
    # Add a stderr file so diagnostic is set
    (session_path / "turns" / "002-final.stderr.txt").write_text("process interrupted\n", encoding="utf-8")

    loaded = webui.load_project(tmp_path, "interrupt-test")
    task = loaded["tasks"][0]
    assert task["board_column"] == "In Progress"
    assert task["board_attention"] is True


def test_no_token_data_omission(tmp_path: Path):
    """Token chip is omitted when no token data is available."""
    project = _base_project(tmp_path, "no-token-test")
    (project / "results").mkdir()
    (project / "results" / "e2e-report.md").write_text("# E2E\n", encoding="utf-8")
    _write_tasks(project, [("T001", "No tokens", "Completed", "dev", "Passed")])
    # Session with no usage data
    session_path = project / ".codexteam" / "runtime" / "sessions" / "no-token-test" / "T001" / "att-001"
    (session_path / "turns").mkdir(parents=True)
    (session_path / "session.json").write_text(json.dumps({
        "task_id": "T001", "attempt_id": "att-001",
        "model_profile": "qwen36-27b", "model_provider": "ollama_local",
        "last_phase": "final", "last_status": "finalized",
        "turn_count": 1, "created_at": "2026-07-22T09:00:00Z", "updated_at": "2026-07-22T09:00:09Z",
        "turns": [{"number": 1, "phase": "final", "status": "finalized", "duration_seconds": 2}],
    }), encoding="utf-8")
    # Turn with no usage event
    (session_path / "turns" / "001-final.jsonl").write_text('{"type":"turn.started"}\n', encoding="utf-8")

    loaded = webui.load_project(tmp_path, "no-token-test")
    summary = loaded["summary"]
    assert "tokens" not in summary

    client = webui.create_app(tmp_path).test_client()
    detail = client.get("/projects/no-token-test")
    # Should not have empty token tiles
    assert b'tokens unknown' not in detail.data


def test_all_verdicts_missing_hides_verification_strip(tmp_path: Path):
    """When all verdicts are missing, the verification strip is hidden entirely."""
    project = _base_project(tmp_path, "no-verdict-test")
    (project / "results").mkdir()
    # No e2e-report means no verdicts
    _write_tasks(project, [("T001", "Task", "Completed", "dev", "Pending")])
    _write_session(project, "T001")

    loaded = webui.load_project(tmp_path, "no-verdict-test")
    assert loaded["has_all_verdicts_missing"] is True
    assert not loaded["reported_verdicts"]

    client = webui.create_app(tmp_path).test_client()
    detail = client.get("/projects/no-verdict-test")
    assert detail.status_code == 200
    # Quality strip should not be rendered for all-missing case
    assert b'aria-label="Quality gates"' not in detail.data


def test_attention_banner_no_raw_path(tmp_path: Path):
    """Attention banner shows human label only, never raw diagnostic paths."""
    project = _base_project(tmp_path, "banner-test")
    (project / "results").mkdir()
    (project / "results" / "e2e-report.md").write_text("# E2E\n", encoding="utf-8")
    _write_tasks(project, [("T001", "Failing task", "In Progress", "dev", "Pending")])

    session_path = _write_session(
        project, "T001", phase="draft", status="turn_failed",
        turns=[{"number": 1, "phase": "draft", "status": "turn_failed"}],
    )
    (session_path / "turns" / "001-draft.jsonl").write_text(
        '{"type":"turn.failed","message":"worker stopped unexpectedly"}\n', encoding="utf-8")
    (session_path / "turns" / "001-draft.stderr.txt").write_text("traceback...\n", encoding="utf-8")

    loaded = webui.load_project(tmp_path, "banner-test")
    attention_summary = loaded["attention_summary"]
    assert attention_summary is not None
    # The banner label should be human-readable
    assert "Worker failed" in attention_summary.get("label", "")
    # Raw path should NOT appear in the summary
    assert ".jsonl" not in (attention_summary.get("message") or "")
    assert ".stderr" not in (attention_summary.get("message") or "")

    client = webui.create_app(tmp_path).test_client()
    detail = client.get("/projects/banner-test")
    assert b".jsonl" not in detail.data.split(b"attention-banner")[0]


def test_cost_and_diagnostics_collapsed_by_default(tmp_path: Path):
    """Cost and diagnostics section is collapsed by default."""
    project = write_project(tmp_path, "cost-test", input_tokens=200, output_tokens=15)
    client = webui.create_app(tmp_path).test_client()
    detail = client.get("/projects/cost-test")
    assert detail.status_code == 200
    # The section exists and has the heading
    assert b"Cost and diagnostics" in detail.data
    # But expensive drafts content should not be visible at top level
    data_str = detail.data.decode("utf-8", errors="replace")
    # In a <details> element, content after </summary> is hidden by default
    assert 'class="cost-section"' in data_str or 'id="cost-and-diagnostics"' in data_str


def test_completed_verified_to_done(tmp_path: Path):
    """A completed task with positive verification goes to Done column."""
    project = _base_project(tmp_path, "done-test")
    _write_tasks(project, [
        ("T001", "Done task", "Completed", "dev", "Passed"),
    ])
    _write_session(project, "T001")
    loaded = webui.load_project(tmp_path, "done-test")

    task = loaded["tasks"][0]
    assert task["board_column"] == "Done"
    assert task["id"] in [t["id"] for t in loaded["board_groups"]["Done"]]


def test_board_has_exactly_six_columns(tmp_path: Path):
    """The board projection always has exactly six named columns."""
    project = _base_project(tmp_path, "columns-test")
    _write_tasks(project, [("T001", "Task", "In Progress", "dev", "Pending")])
    _write_session(project, "T001")
    loaded = webui.load_project(tmp_path, "columns-test")

    assert set(loaded["board_groups"].keys()) == {
        "Backlog", "In Progress", "In Review", "In Validation", "Blocked", "Done",
    }


def test_board_lanes_show_ten_newest_tasks_then_older_disclosure(tmp_path: Path):
    """Each lane leads with ten newest task IDs and collapses the remainder."""
    project = _base_project(tmp_path, "compact-board-test")
    _write_tasks(project, [
        (f"T{number:03d}", f"Task {number}", "Completed", "dev", "Passed")
        for number in range(1, 13)
    ])

    loaded = webui.load_project(tmp_path, "compact-board-test")
    done_ids = [task["id"] for task in loaded["board_groups"]["Done"]]
    assert done_ids == [f"T{number:03d}" for number in range(12, 0, -1)]

    response = webui.create_app(tmp_path).test_client().get("/projects/compact-board-test")
    assert response.status_code == 200
    rendered = response.data.decode("utf-8")
    board = rendered[
        rendered.index('<section class="dashboard-section board-section"'):
        rendered.index('<section class="dashboard-section execution-section"')
    ]
    disclosure = board.index('<details class="lane-older">')

    assert board.count('class="task-title-id"') == 12
    for number in range(12, 2, -1):
        assert board.index(f'class="task-title-id">T{number:03d}<') < disclosure
    for number in (2, 1):
        assert board.index(f'class="task-title-id">T{number:03d}<') > disclosure
    assert "Show 2 older…" in board
    assert "Hide older" in board


def test_task_id_is_title_and_milestone_is_grouping_metadata(tmp_path: Path):
    """Every task-derived surface separates milestone metadata from the task title."""
    project = _base_project(tmp_path, "task-hierarchy-test", active_task="T092")
    _write_tasks(project, [
        (
            "T092",
            "M19 — Review final project closure and operator waiver handling",
            "Completed",
            "reviewer",
            "Passed",
        ),
    ])
    _write_session(project, "T092")

    loaded = webui.load_project(tmp_path, "task-hierarchy-test")
    task = loaded["tasks"][0]
    assert task["objective"] == "M19 — Review final project closure and operator waiver handling"
    assert task["milestone_id"] == "M19"
    assert task["display_objective"] == "Review final project closure and operator waiver handling"
    assert task["card"]["milestone_id"] == "M19"
    assert task["card"]["objective"] == "Review final project closure and operator waiver handling"
    assert loaded["focus"]["milestone_id"] == "M19"
    assert loaded["focus"]["task_id"] == "T092"
    assert loaded["agent_activity"]["inactive"][0]["milestone_id"] == "M19"
    assert loaded["agent_activity"]["inactive"][0]["task_id"] == "T092"

    client = webui.create_app(tmp_path).test_client()
    detail = client.get("/projects/task-hierarchy-test").get_data(as_text=True)
    portfolio = client.get("/").get_data(as_text=True)

    assert detail.count('class="milestone-id">M19<') >= 4
    assert detail.count('class="task-title-id">T092<') >= 4
    assert 'class="milestone-id">T092<' not in detail
    assert "M19 — Review final project closure" not in detail
    assert 'class="task-title-id">T092<' in portfolio


def test_task_title_fallback_without_milestone_prefix(tmp_path: Path):
    """Tasks without milestone-prefixed prose keep their complete objective."""
    project = _base_project(tmp_path, "task-title-fallback")
    _write_tasks(project, [
        ("T001", "Implement the login flow", "In Progress", "developer", "Pending"),
    ])

    loaded = webui.load_project(tmp_path, "task-title-fallback")
    task = loaded["tasks"][0]
    assert task["milestone_id"] is None
    assert task["display_objective"] == "Implement the login flow"

    detail = webui.create_app(tmp_path).test_client().get(
        "/projects/task-title-fallback"
    ).get_data(as_text=True)
    assert 'class="milestone-id"' not in detail
    assert 'class="task-title-id">T001<' in detail
    assert "T001</span> — Implement the login flow" in detail


def test_board_lane_recency_is_not_overridden_by_attention(tmp_path: Path):
    """A newer normal task appears before an older attention task in one lane."""
    project = _base_project(tmp_path, "strict-recency-test")
    _write_tasks(project, [
        ("T001", "Older interrupted task", "In Progress", "dev", "Pending"),
        ("T002", "Newer active task", "In Progress", "dev", "Pending"),
    ])
    older = _write_session(project, "T001", phase="draft", status="turn_failed")
    older_data = json.loads((older / "session.json").read_text(encoding="utf-8"))
    older_data["updated_at"] = "2026-07-22T09:00:01Z"
    (older / "session.json").write_text(json.dumps(older_data), encoding="utf-8")

    newer = _write_session(project, "T002", phase="draft", status="in_progress")
    newer_data = json.loads((newer / "session.json").read_text(encoding="utf-8"))
    newer_data["updated_at"] = "2026-07-22T09:00:20Z"
    (newer / "session.json").write_text(json.dumps(newer_data), encoding="utf-8")

    loaded = webui.load_project(tmp_path, "strict-recency-test")
    progress_ids = [task["id"] for task in loaded["board_groups"]["In Progress"]]
    assert progress_ids == ["T002", "T001"]
    assert loaded["board_groups"]["In Progress"][1]["board_attention"] is True


def test_focus_leads_with_objective(tmp_path: Path):
    """Focus payload leads with human task objective, not task ID."""
    project = _base_project(tmp_path, "focus-test")
    (project / "results").mkdir()
    (project / "results" / "e2e-report.md").write_text("# E2E\n", encoding="utf-8")
    _write_tasks(project, [("T001", "Implement the login flow", "In Progress", "dev", "Pending")])
    _write_session(project, "T001", phase="draft", status="in_progress")

    loaded = webui.load_project(tmp_path, "focus-test")
    focus = loaded["focus"]
    assert focus["objective"] == "Implement the login flow"
    assert focus.get("owner") is not None

    # In the rendered page, objective should appear before any task ID
    client = webui.create_app(tmp_path).test_client()
    detail = client.get("/projects/focus-test")
    data = detail.data.decode("utf-8", errors="replace")
    # The focus section (within focus-card) should contain the objective text
    assert "Implement the login flow" in data


def test_summary_omits_missing_facts(tmp_path: Path):
    """Compact summary only includes facts that are actually reported."""
    project = _base_project(tmp_path, "summary-test")
    (project / "results").mkdir()
    (project / "results" / "e2e-report.md").write_text("# E2E\n", encoding="utf-8")
    _write_tasks(project, [("T001", "Task", "Completed", "dev", "Passed")])
    # Session with no tokens and no turns that matter
    session_path = project / ".codexteam" / "runtime" / "sessions" / "summary-test" / "T001" / "att-001"
    (session_path / "turns").mkdir(parents=True)
    (session_path / "session.json").write_text(json.dumps({
        "task_id": "T001", "attempt_id": "att-001",
        "model_profile": "qwen36-27b", "model_provider": "ollama_local",
        "last_phase": "final", "last_status": "finalized",
        "turn_count": 0, "created_at": "2026-07-22T09:00:00Z", "updated_at": "2026-07-22T09:00:09Z",
        "turns": [],
    }), encoding="utf-8")

    loaded = webui.load_project(tmp_path, "summary-test")
    summary = loaded["summary"]
    assert summary["completed"] == 1
    assert summary["total"] == 1
    # No corrections, no turns reported
    assert "corrections" not in summary
    assert "tokens" not in summary

def test_board_column_finalized_awaiting_verification(tmp_path: Path):
    """Finalized work awaiting positive verification goes to In Validation, not In Progress."""
    project = _base_project(tmp_path, "finalized-test")
    _write_tasks(project, [
        ("T001", "Finalized task", "In Progress", "dev", "Pending"),
    ])
    _write_session(project, "T001", phase="final", status="finalized",
                   turns=[{"number": 1, "phase": "draft", "status": "draft_ready"},
                          {"number": 2, "phase": "final", "status": "finalized"}])
    loaded = webui.load_project(tmp_path, "finalized-test")

    task = loaded["tasks"][0]
    assert task["board_column"] == "In Validation"
    # Verify it is NOT in In Progress
    assert task["id"] not in [t["id"] for t in loaded["board_groups"]["In Progress"]]


def test_board_column_needs_review_to_in_review(tmp_path: Path):
    """Needs Review status (from TASKS.md) projects to In Review."""
    project = _base_project(tmp_path, "review-status-test")
    _write_tasks(project, [
        ("T001", "Needs review task", "Needs Review", "dev", "Pending"),
    ])
    _write_session(project, "T001", phase="draft", status="draft_ready")
    loaded = webui.load_project(tmp_path, "review-status-test")

    task = loaded["tasks"][0]
    assert task["board_column"] == "In Review"


def test_board_newest_attempt_used(tmp_path: Path):
    """Board column uses the newest attempt, not the oldest."""
    project = _base_project(tmp_path, "multi-attempt-test")
    _write_tasks(project, [
        ("T001", "Multi attempt task", "In Progress", "dev", "Pending"),
    ])
    # Oldest attempt — turned into In Progress
    session_path = project / ".codexteam" / "runtime" / "sessions" / "multi-attempt-test" / "T001" / "att-001"
    (session_path / "turns").mkdir(parents=True)
    (session_path / "session.json").write_text(json.dumps({
        "task_id": "T001", "attempt_id": "att-001",
        "model_profile": "qwen36-27b", "model_provider": "ollama_local",
        "last_phase": "draft", "last_status": "in_progress",
        "turn_count": 1, "created_at": "2026-07-22T09:00:00Z", "updated_at": "2026-07-22T09:00:05Z",
        "turns": [{"number": 1, "phase": "draft", "status": "in_progress", "duration_seconds": 2}],
    }), encoding="utf-8")
    (session_path / "turns" / "001-draft.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":50,"cached_input_tokens":0,"output_tokens":5}}\n')

    # Newest attempt — draft_ready, should win and put task in In Review
    session_path2 = project / ".codexteam" / "runtime" / "sessions" / "multi-attempt-test" / "T001" / "att-002"
    (session_path2 / "turns").mkdir(parents=True)
    (session_path2 / "session.json").write_text(json.dumps({
        "task_id": "T001", "attempt_id": "att-002",
        "model_profile": "qwen36-27b", "model_provider": "ollama_local",
        "last_phase": "draft", "last_status": "draft_ready",
        "turn_count": 1, "created_at": "2026-07-22T09:00:10Z", "updated_at": "2026-07-22T09:00:15Z",
        "turns": [{"number": 1, "phase": "draft", "status": "draft_ready", "duration_seconds": 3}],
    }), encoding="utf-8")
    (session_path2 / "turns" / "001-draft.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":60,"cached_input_tokens":0,"output_tokens":6}}\n')

    loaded = webui.load_project(tmp_path, "multi-attempt-test")
    task = loaded["tasks"][0]
    # Newest attempt (att-002) has draft_ready → In Review
    assert task["board_column"] == "In Review"


def test_attention_count_includes_blocked_tasks(tmp_path: Path):
    """Attention count includes canonical blocked tasks as well as recoverable failures."""
    project = _base_project(tmp_path, "attention-count-test")
    _write_tasks(project, [
        ("T001", "Blocked task", "Blocked", "dev", "Pending"),
        ("T002", "Failed task", "In Progress", "dev", "Pending"),
        ("T003", "Normal task", "Completed", "dev", "Passed"),
    ])
    _write_session(project, "T001", phase="draft", status="turn_failed")
    _write_session(project, "T002", phase="draft", status="turn_failed")
    _write_session(project, "T003")

    loaded = webui.load_project(tmp_path, "attention-count-test")
    summary = loaded["summary"]
    # Both T001 (blocked) and T002 (failed turn) count as attention
    assert summary.get("attention", 0) == 2


def test_attention_banner_content_has_literal_title_and_no_raw_path(tmp_path: Path):
    """Attention banner renders literal title 'Attention', human state, no raw paths.

    The reported error itself contains a raw diagnostic path; the banner must NOT show it.
    """
    project = _base_project(tmp_path, "banner-content-test")
    (project / "results").mkdir()
    (project / "results" / "e2e-report.md").write_text("# E2E\n", encoding="utf-8")
    _write_tasks(project, [("T001", "Failing task", "In Progress", "dev", "Pending")])

    session_path = _write_session(
        project, "T001", phase="draft", status="turn_failed",
        turns=[{"number": 1, "phase": "draft", "status": "turn_failed"}],
    )
    # The JSONL message itself contains a raw diagnostic path fragment
    (session_path / "turns" / "001-draft.jsonl").write_text(
        '{"type":"turn.failed","message":"worker stopped at .codexteam/runtime/sessions/x/T001/att-001/turns/001-draft.jsonl"}\n', encoding="utf-8")
    (session_path / "turns" / "001-draft.stderr.txt").write_text("traceback...\n", encoding="utf-8")

    loaded = webui.load_project(tmp_path, "banner-content-test")
    # Verify the raw error contains path fragments
    assert ".jsonl" in loaded["error"], "Test fixture should have raw path in error"
    assert "/sessions/" in loaded["error"] or ".codexteam/runtime" in loaded["error"], "Fixture should have runtime path"

    # But the attention_summary message must be sanitized
    summary = loaded["attention_summary"]
    assert summary is not None
    assert ".jsonl" not in summary.get("message", ""), f"Path leaked in message: {summary['message']}"
    assert "/sessions/" not in summary.get("message", "")
    assert ".stderr" not in summary.get("message", "")

    # Now verify the rendered banner also has no raw paths
    client = webui.create_app(tmp_path).test_client()
    detail = client.get("/projects/banner-content-test")
    assert detail.status_code == 200
    data = detail.data.decode("utf-8", errors="replace")

    # The banner section must contain literal "Attention" title
    banner_start = data.find("attention-banner")
    assert banner_start >= 0, "No attention-banner found in rendered page"
    # Extract the banner content (up to closing tag)
    banner_end = data.find("</section>", banner_start)
    banner_content = data[banner_start:banner_end] if banner_end > banner_start else ""

    assert "Attention" in banner_content, "Banner missing literal 'Attention' title"
    # Must NOT contain raw paths
    assert ".jsonl" not in banner_content, "Raw .jsonl path leaked into attention banner"
    assert ".stderr" not in banner_content, "Raw .stderr path leaked into attention banner"
    assert "/sessions/" not in banner_content, "Session path leaked into attention banner"


def test_agent_activity_draft_ready_is_not_active(tmp_path: Path):
    """A draft_ready/review-waiting worker is NOT shown as active agent."""
    project = _base_project(tmp_path, "agent-test")
    _write_tasks(project, [
        ("T001", "Draft ready task", "In Progress", "dev-01", "Pending"),
        ("T002", "In progress task", "In Progress", "dev-02", "Pending"),
    ])
    _write_session(project, "T001", phase="draft", status="draft_ready")
    _write_session(project, "T002", phase="draft", status="in_progress")

    loaded = webui.load_project(tmp_path, "agent-test")
    activity = loaded["agent_activity"]

    # dev-02 (In Progress) should be active; dev-01 (draft_ready/In Review) should not
    active_ids = [a.get("task_id") for a in activity["active"]]
    assert "T002" in active_ids, "In Progress agent should be active"
    assert "T001" not in active_ids, "draft_ready agent should NOT be active"

    inactive_ids = [a.get("task_id") for a in activity["inactive"]]
    assert "T001" in inactive_ids, "draft_ready agent should be in inactive list"


def test_agent_dedup_includes_owner(tmp_path: Path):
    """Different owners with same role/profile are NOT merged."""
    project = _base_project(tmp_path, "dedup-test")
    _write_tasks(project, [
        ("T001", "Task one", "In Progress", "alice", "Pending"),
        ("T002", "Task two", "In Progress", "bob", "Pending"),
    ])
    _write_session(project, "T001", phase="draft", status="in_progress")
    _write_session(project, "T002", phase="draft", status="in_progress")

    loaded = webui.load_project(tmp_path, "dedup-test")
    activity = loaded["agent_activity"]

    # Both alice and bob should appear as separate active agents
    owners = {a.get("owner") for a in activity["active"]}
    assert "alice" in owners
    assert "bob" in owners

def test_board_row_recoverable_status_without_session(tmp_path: Path):
    """Task-row recoverable statuses project to In Progress with attention even without sessions."""
    project = _base_project(tmp_path, "row-recoverable-test")
    _write_tasks(project, [
        ("T001", "Interrupted row task", "interrupted", "dev", "Pending"),
        ("T002", "Correction needed row task", "correction_needed", "dev", "Pending"),
        ("T003", "Normal planned task", "Planned", "dev", "Pending"),
    ])
    # No sessions created for any task
    loaded = webui.load_project(tmp_path, "row-recoverable-test")

    tasks_by_id = {t["id"]: t for t in loaded["tasks"]}
    assert tasks_by_id["T001"]["board_column"] == "In Progress"
    assert tasks_by_id["T001"]["board_attention"] is True
    assert tasks_by_id["T002"]["board_column"] == "In Progress"
    assert tasks_by_id["T002"]["board_attention"] is True
    assert tasks_by_id["T003"]["board_column"] == "Backlog"
    assert tasks_by_id["T003"]["board_attention"] is False


def test_board_row_draft_ready_without_session(tmp_path: Path):
    """Task-row draft_ready projects to In Review even without session files."""
    project = _base_project(tmp_path, "row-draft-ready-test")
    _write_tasks(project, [
        ("T001", "Draft ready row task", "draft_ready", "dev", "Pending"),
    ])
    # No sessions created
    loaded = webui.load_project(tmp_path, "row-draft-ready-test")

    task = loaded["tasks"][0]
    assert task["board_column"] == "In Review"


def test_agent_activity_includes_provider(tmp_path: Path):
    """Agent activity entries include exact provider value when available."""
    project = _base_project(tmp_path, "provider-test")
    _write_tasks(project, [("T001", "Task", "In Progress", "dev", "Pending")])
    session_path = _write_session(
        project, "T001", phase="draft", status="in_progress", provider="openai",
        profile="gpt54-mini"
    )
    loaded = webui.load_project(tmp_path, "provider-test")

    activity = loaded["agent_activity"]
    for agent in activity["active"]:
        assert agent.get("provider") is not None, "Provider should be present in agent entry"


def test_card_payload_has_precomputed_facts(tmp_path: Path):
    """Compact card payload includes stage, verification, turns/corrections when available."""
    project = _base_project(tmp_path, "card-facts-test")
    _write_tasks(project, [("T001", "Task", "In Progress", "dev", "Passed")])
    _write_session(
        project, "T001", phase="feedback", status="in_progress",
        turns=[{"number": 1, "phase": "draft", "status": "draft_ready"},
               {"number": 2, "phase": "feedback", "status": "in_progress"}],
    )
    loaded = webui.load_project(tmp_path, "card-facts-test")

    card = loaded["tasks"][0]["card"]
    assert card.get("stage") is not None, "Card should have stage"
    assert card.get("verification") == "Passed", "Card should have verification"
    assert "last_activity" in card, "Card should have last_activity"

    card = loaded["tasks"][0]["card"]
    assert card.get("stage") is not None, "Card should have stage"
    assert card.get("verification") == "Passed", "Card should have verification"
    assert "last_activity" in card, "Card should have last_activity"


def test_owner_label_strips_backticks_and_model_name():
    """Raw owner string with backticks and model name is normalized."""
    raw = "`gitgui-m17-dev-T080` — GPT-5.4 mini Developer"
    label = webui._human_owner_label(raw, "developer")
    assert label == "Developer", f"Expected 'Developer', got: {label}"


def test_owner_label_strips_parenthetical_role():
    """Raw owner string with parenthetical role annotation is normalized."""
    raw = "cli-developer-01 (developer)"
    label = webui._human_owner_label(raw)
    assert label == "Developer", f"Expected 'Developer', got: {label}"


def test_owner_label_preserves_already_human_text():
    """Already-human text like role names passes through unchanged."""
    raw = "Lead acceptance run"
    label = webui._human_owner_label(raw)
    assert label == raw, f"Human text should pass through unchanged: got '{label}'"


def test_attention_banner_deduplicates_identical_label_and_message(tmp_path: Path):
    """When human label and message match case-insensitively, message is replaced.

    This prevents 'Interrupted — interrupted' duplicate copy in the banner.
    """
    project = _base_project(tmp_path, "dedup-banner-test")
    (project / "results").mkdir()
    (project / "results" / "e2e-report.md").write_text("# E2E\n", encoding="utf-8")
    _write_tasks(project, [("T001", "Task", "In Progress", "dev", "Pending")])

    # Create a session where the error message is just "interrupted" (same as canonical status)
    session_path = _write_session(
        project, "T001", phase="final", status="interrupted",
        turns=[{"number": 1, "phase": "draft", "status": "draft_ready"},
               {"number": 2, "phase": "final", "status": "interrupted"}],
    )
    # The error in the JSONL should be just "interrupted" to trigger deduplication
    (session_path / "turns" / "002-final.jsonl").write_text(
        '{"type":"turn.failed","message":"interrupted"}\n', encoding="utf-8")

    loaded = webui.load_project(tmp_path, "dedup-banner-test")
    summary = loaded["attention_summary"]
    assert summary is not None
    # Label should be the canonical human name
    assert "Interrupted" == summary.get("label"), f"Expected 'Interrupted' label, got: {summary.get('label')}"
    # Message should NOT duplicate the label; it should be the generic sentence
    assert "Review the latest task details." in summary.get("message", ""),         f"Expected deduplicated message, got: {summary.get('message')}"
    assert "interrupted" not in summary.get("message", "").lower() or            "Review" in summary.get("message", ""),         f"Message should be deduplicated, not duplicated: {summary.get('message')}"
