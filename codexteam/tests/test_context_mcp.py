from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from codexteam_tools.context_mcp import (
    PROTOCOL_VERSION,
    ContextMcpServer,
    modern_meta,
)
from codexteam_tools.team_context import TeamContextError, TeamContextReader
from codexteam_tools.test_gates import run_gate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _configure_gate(project: Path) -> None:
    command = json.dumps(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; assert Path('src/main.py').read_text() == 'ok\\n'",
        ]
    )
    _write(
        project / "management/TEST_GATES.toml",
        (
            'schema_version = "1.0"\n'
            'verification_paths = ["src/**", "management/**"]\n\n'
            "[development]\n"
            "configured = true\n"
            "expected_max_seconds = 30\n"
            f"commands = [{command}]\n\n"
            "[integration]\n"
            "configured = true\n"
            "expected_max_seconds = 60\n"
            'includes = ["development"]\n'
            f"commands = [{command}]\n"
        ),
    )


@pytest.fixture
def context_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    projects = tmp_path / "projects"
    project = projects / "demo"
    memory = tmp_path / "memory"
    project.mkdir(parents=True)
    memory.mkdir()
    _write(project / "src/main.py", "ok\n")
    _write(
        project / "src/reader.py",
        "def bounded_reader():\n    return 'bounded context'\n",
    )
    _write(
        project / "PROJECT_STATE.md",
        "# Project State\n\n- Status: Active\n- Active Task: T002\n",
    )
    _write(
        project / "ARCHITECTURE.md",
        "# Architecture\n\nThe reader stays inside the project boundary.\n",
    )
    _write(
        project / "CURRENT_TASK.md",
        (
            "# Current Task\n\n"
            "- Task ID: T002\n"
            "- Status: In Progress\n"
            "- Objective: Add a bounded reader\n"
            "- Handoff: `management/tasks/T002.md`\n"
            "- Evidence: First line\n"
            "  continues here.\n"
        ),
    )
    _write(
        project / "TASKS.md",
        (
            "# Tasks\n\n"
            "| Task ID | Description | Status | Owner | Verification | Evidence |\n"
            "|---|---|---|---|---|---|\n"
            "| T001 | M1 Plan | Completed | lead | Passed | result |\n"
            "| T002 | M1 Reader | In Progress | developer | Pending | pending |\n"
            "| T003 | M1 Parallel work | In Progress | developer | Pending | pending |\n"
        ),
    )
    _write(
        project / "management/tasks/T002.md",
        (
            "# Task T002: Reader\n\n"
            "## Objective\n\nBuild the bounded reader.\n\n"
            "## Responsible AI\n\n`demo-developer` - Developer.\n\n"
            "## Dependencies\n\n- T001 must be complete.\n\n"
            "## Allowed Paths\n\n- `src/main.py`\n\n"
            "## Verification\n\nRun the focused tests.\n"
        ),
    )
    _write(
        project / "management/tasks/T003.md",
        (
            "# Task T003: Parallel work\n\n"
            "## Objective\n\nExercise conflict reporting.\n\n"
            "## Allowed Paths\n\n- `src/main.py`\n\n"
            "## Verification\n\nRun the focused tests.\n"
        ),
    )
    _write(
        project / "DECISIONS.md",
        (
            "# Decisions\n\n"
            "## D001 - Read-only context\n\n"
            "- Status: Accepted\n"
            "- Decision: Context retrieval remains read-only and bounded.\n"
        ),
    )
    _write(
        project / "OPEN_QUESTIONS.md",
        "# Open Questions\n\nNo question blocks the bounded reader.\n",
    )
    _write(
        memory / "decisions.md",
        (
            "# Decisions Memory\n\n## Entries\n\n"
            "- Test Engineers own the Integration Gate.\n"
            "- Run Guard interrupts three identical failed commands.\n"
        ),
    )
    _configure_gate(project)
    run_gate(project, "development")
    run_gate(project, "integration")
    _write(
        project
        / ".codexteam/runtime/sessions/team-demo/T002/att-001/turn-state.json",
        json.dumps(
            {
                "team_id": "team-demo",
                "task_id": "T002",
                "attempt_id": "att-001",
                "agent_role": "developer",
                "model_profile": "test-profile",
                "phase": "draft",
                "turn_number": 1,
                "status": "running",
                "updated_at": "2099-01-01T00:00:00Z",
                "timeout_seconds": 600,
            }
        ),
    )
    _write(
        project
        / ".codexteam/runtime/sessions/team-demo/T002/att-001/session.json",
        json.dumps(
            {
                "team_id": "team-demo",
                "task_id": "T002",
                "attempt_id": "att-001",
                "agent_role": "developer",
                "model_profile": "test-profile",
                "model_provider": "openai",
                "last_phase": "draft",
                "last_status": "draft_ready",
                "turn_count": 1,
                "created_at": "2099-01-01T00:00:00Z",
                "updated_at": "2099-01-01T00:00:01Z",
                "final_result_path": "results/T002-att-001.json",
            }
        ),
    )
    _write(
        project
        / ".codexteam/runtime/sessions/team-demo/T002/att-001/turns/001-draft.metrics.json",
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": "T002",
                "attempt_id": "att-001",
                "agent_role": "developer",
                "model_profile": "test-profile",
                "turn": {
                    "number": 1,
                    "phase": "draft",
                    "completed": True,
                    "duration_seconds": 12.5,
                },
                "usage": {
                    "delta": {
                        "input_tokens": 500,
                        "cached_input_tokens": 400,
                        "uncached_input_tokens": 100,
                        "output_tokens": 25,
                    }
                },
                "activity": {
                    "tool_calls": 4,
                    "failed_tool_calls": 1,
                    "command_calls": 3,
                    "failed_command_calls": 1,
                    "edit_events": 1,
                    "command_output_bytes": 2000,
                    "max_command_output_bytes": 1500,
                    "repeated_commands": [
                        {"fingerprint": "abc", "preview": "rg bounded", "count": 2}
                    ],
                    "largest_commands": [
                        {
                            "fingerprint": "abc",
                            "preview": "rg bounded",
                            "output_bytes": 1500,
                            "exit_code": 0,
                            "failed": False,
                        }
                    ],
                },
                "events": {"last_error": None},
            }
        ),
    )
    _write(
        project / "results/T002-att-001.json",
        json.dumps(
            {
                "schema_version": "1.0",
                "result_id": "result-t002-att-001",
                "team_id": "team-demo",
                "task_id": "T002",
                "agent_role": "developer",
                "attempt_id": "att-001",
                "status": "completed",
                "summary": "The bounded reader was implemented and verified.",
                "output": {
                    "exit_code": 0,
                    "stdout_tail": "PASS",
                    "stderr_tail": "",
                    "duration_seconds": 12.5,
                },
                "file_changes": [{"action": "modified", "path": "src/main.py"}],
                "evidence": [
                    {
                        "type": "test_output",
                        "artifact_ref": "src/main.py",
                        "summary": "The focused reader check passed.",
                    },
                    {
                        "type": "cli_invocation",
                        "artifact_ref": "results/gates/development.json",
                        "summary": "The configured Development Gate passed.",
                    }
                ],
                "requested_followups": [],
                "errors": [],
                "warnings": [],
                "limitations": [],
                "produced_at": "2099-01-01T00:00:01Z",
            }
        ),
    )
    _write(
        project
        / ".codexteam/runtime/sessions/team-parallel/T003/att-001/turn-state.json",
        json.dumps(
            {
                "team_id": "team-parallel",
                "task_id": "T003",
                "attempt_id": "att-001",
                "agent_role": "developer",
                "model_profile": "test-profile",
                "phase": "draft",
                "turn_number": 1,
                "status": "running",
                "updated_at": "2098-01-01T00:00:00Z",
                "timeout_seconds": 600,
            }
        ),
    )
    return projects, project, memory


def _request(
    request_id: int,
    method: str,
    params: dict | None = None,
) -> dict:
    values = dict(params or {})
    values["_meta"] = modern_meta()
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": values,
    }


def test_reader_returns_compact_source_backed_context(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, _, memory = context_fixture
    reader = TeamContextReader(projects, team_memory_root=memory)

    active = reader.get_active_task("demo")
    assert active["current"]["task_id"] == "T002"
    assert active["current"]["evidence"] == "First line continues here."
    assert active["ledger"]["owner"] == "developer"
    assert active["attempts"][0]["status"] == "running"
    assert {source["path"] for source in active["sources"]} == {
        "CURRENT_TASK.md",
        "TASKS.md",
        "management/tasks/T002.md",
    }
    assert all(len(source["sha256"]) == 64 for source in active["sources"])

    handoff = reader.get_task_handoff("demo", "t002")
    assert handoff["title"] == "Task T002: Reader"
    assert [section["title"] for section in handoff["sections"]] == [
        "Objective",
        "Responsible AI",
        "Dependencies",
        "Allowed Paths",
        "Verification",
    ]


def test_reader_and_mcp_accept_no_active_task_sentinel(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, project, memory = context_fixture
    _write(
        project / "CURRENT_TASK.md",
        "# Current Task\n\n- Task ID: nOnE\n- Status: Awaiting Operator Approval\n",
    )
    reader = TeamContextReader(projects, team_memory_root=memory)

    active = reader.get_active_task("demo")
    assert active["current"]["task_id"] == "nOnE"
    assert active["ledger"] is None
    assert active["ledger_warning"] is None
    assert active["attempts"] == []
    assert [source["path"] for source in active["sources"]] == ["CURRENT_TASK.md"]

    response = ContextMcpServer(reader).handle(
        _request(
            1,
            "tools/call",
            {"name": "get_active_task", "arguments": {"project": "demo"}},
        )
    )
    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"]["current"]["task_id"] == "nOnE"
    assert response["result"]["structuredContent"]["ledger"] is None


def test_reader_rejects_malformed_non_sentinel_active_task(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, project, memory = context_fixture
    _write(
        project / "CURRENT_TASK.md",
        "# Current Task\n\n- Task ID: Not-A-Task\n- Status: In Progress\n",
    )
    reader = TeamContextReader(projects, team_memory_root=memory)

    with pytest.raises(ValueError, match="invalid task ID"):
        reader.get_active_task("demo")


def test_requested_row_survives_unrelated_ledger_validation_failure(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, project, memory = context_fixture
    tasks = project / "TASKS.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8")
        + "| T004 | Review | In Review | reviewer | Pending | pending |\n",
        encoding="utf-8",
    )
    reader = TeamContextReader(projects, team_memory_root=memory)

    active = reader.get_active_task("demo")
    assert active["ledger"]["task_id"] == "T002"
    assert "invalid task status" in active["ledger_warning"]
    assert "requested row read exactly" in active["ledger_warning"]


def test_gate_status_validates_current_workspace_and_reports_staleness(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, project, memory = context_fixture
    reader = TeamContextReader(projects, team_memory_root=memory)

    current = reader.get_gate_status("demo")
    assert [gate["current"] for gate in current["gates"]] == [True, True]
    assert current["gates"][1]["record"]["status"] == "passed"
    assert current["gates"][1]["configured_commands"]

    _write(project / "src/main.py", "changed\n")
    stale = reader.get_gate_status("demo")
    assert [gate["current"] for gate in stale["gates"]] == [False, False]
    assert all("stale" in gate["freshness_error"] for gate in stale["gates"])


def test_project_task_and_handoff_insights_are_bounded(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, _, memory = context_fixture
    server = ContextMcpServer(TeamContextReader(projects, team_memory_root=memory))

    overview = server.insights.get_project_overview("demo")
    assert overview["active_task"] == "T002"
    assert overview["task_counts"] == {"Completed": 1, "In Progress": 2}
    assert overview["running_or_stale_attempts"][0]["task"] == "T002"
    assert overview["git"]["available"] is False

    tasks = server.insights.list_tasks(
        "demo",
        status="In Progress",
        milestone="M1",
        limit=1,
    )
    assert tasks["matched"] == 2
    assert len(tasks["tasks"]) == 1
    assert tasks["truncated"] is True
    assert tasks["tasks"][0]["evidence"] == "pending"

    context = server.insights.get_task_context(
        "demo",
        "T002",
        role="developer",
    )
    assert context["dependencies"] == [
        {
            "task_id": "T001",
            "status": "Completed",
            "description": "M1 Plan",
            "blocking": False,
        }
    ]
    assert context["blocking_dependencies"] == []
    assert context["role_policy"]["role"] == "developer"
    assert context["architecture_references"] == [
        "ARCHITECTURE.md",
        "DECISIONS.md",
    ]
    assert context["stale_attempts"] == []
    parallel = next(
        attempt
        for attempt in context["concurrent_attempts"]
        if attempt["task"] == "T003"
    )
    assert parallel["possible_path_conflicts"] == [
        {"requested": "src/main.py", "active": "src/main.py"}
    ]


def test_attempt_result_and_cost_insights_avoid_raw_transcripts(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, project, memory = context_fixture
    server = ContextMcpServer(TeamContextReader(projects, team_memory_root=memory))

    attempt = server.insights.get_attempt_summary(
        "demo",
        "T002",
        "att-001",
    )
    assert attempt["turns_total"] == 1
    assert attempt["usage_delta_totals"]["input_tokens"] == 500
    assert attempt["turns"][0]["activity"]["tool_calls"] == 4
    assert attempt["result"]["summary"].startswith("The bounded reader")
    assert "stdout_tail" not in attempt["result"]

    result = server.insights.validate_result_record(
        "demo",
        "T002",
        "att-001",
        role="developer",
    )
    assert result["valid"] is True
    assert result["evidence"][0]["exists"] is True
    assert len(result["evidence"][0]["sha256"]) == 64
    assert result["evidence"][1]["current"] is True

    hotspots = server.insights.get_cost_hotspots(
        "demo",
        phase="draft",
        limit=1,
    )
    assert hotspots["matched_turns"] == 1
    assert hotspots["hotspots"][0]["usage_delta"]["input_tokens"] == 500
    assert hotspots["largest_commands"][0]["output_bytes"] == 1500
    assert hotspots["repeated_commands"][0]["repeat_count"] == 2

    (project / "src/main.py").unlink()
    invalid = server.insights.validate_result_record(
        "demo",
        "T002",
        "att-001",
    )
    assert invalid["valid"] is False
    assert "artifact is missing" in invalid["errors"][0]
    assert invalid["evidence"][1]["current"] is False


def test_repository_search_is_ranked_bounded_and_contained(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, _, memory = context_fixture
    server = ContextMcpServer(TeamContextReader(projects, team_memory_root=memory))

    result = server.repository.search_repository(
        "demo",
        "BOUNDED",
        scope="source",
        limit=2,
    )
    assert result["matches"][0]["path"] == "src/reader.py"
    assert "bounded_reader" in result["matches"][0]["text"]
    assert result["case_sensitive"] is False
    assert result["sources"][0]["bytes"] > 0
    with pytest.raises((TeamContextError, ValueError), match="unsafe"):
        server.repository.search_repository(
            "demo",
            "bounded",
            path="../demo",
        )
    with pytest.raises((TeamContextError, ValueError), match="unsafe"):
        server.repository.search_repository(
            "demo",
            "bounded",
            file_glob="../*.py",
        )


def test_change_summary_reports_status_and_suspicious_generated_files(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    project = projects / "git-demo"
    project.mkdir(parents=True)
    _write(project / "tracked.txt", "first\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=project, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
        cwd=project,
        check=True,
    )
    _write(project / "tracked.txt", "second\n")
    _write(project / ".playwright-cli/page.png", "generated\n")
    server = ContextMcpServer(TeamContextReader(projects))

    summary = server.repository.get_change_summary(
        "git-demo",
        detail="diff",
        limit=10,
    )
    assert summary["clean"] is False
    assert summary["counts"]["unstaged"] == 1
    assert summary["counts"]["untracked"] == 1
    assert summary["counts"]["suspicious"] == 1
    assert summary["suspicious_paths"] == [".playwright-cli/page.png"]
    assert "tracked.txt" in summary["diff_excerpt"]["unstaged"]
    assert len(summary["diff_excerpt"]["unstaged"]) <= 2_000


def test_memory_search_is_ranked_bounded_and_source_backed(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, _, memory = context_fixture
    reader = TeamContextReader(projects, team_memory_root=memory)

    result = reader.search_team_memory(
        "demo",
        "Run Guard failed commands",
        scope="all",
        limit=2,
    )
    assert result["matches"][0]["scope"] == "team"
    assert result["matches"][0]["source"] == "team-memory/decisions.md"
    assert "Run Guard" in result["matches"][0]["text"]
    source = next(
        source
        for source in result["sources"]
        if source["path"] == "team-memory/decisions.md"
    )
    assert len(source["sha256"]) == 64
    assert len(result["matches"]) <= 2

    project_only = reader.search_team_memory(
        "demo",
        "read-only bounded",
        scope="project",
    )
    assert project_only["matches"][0]["source"] == "DECISIONS.md"
    with pytest.raises(TeamContextError, match="searchable term"):
        reader.search_team_memory("demo", "x")


def test_reader_rejects_project_traversal_and_symlink_escape(
    context_fixture: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    projects, _, memory = context_fixture
    reader = TeamContextReader(projects, team_memory_root=memory)

    with pytest.raises(TeamContextError, match="invalid project"):
        reader.get_active_task("../demo")
    outside = tmp_path / "outside"
    outside.mkdir()
    (projects / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises((TeamContextError, ValueError), match="escapes"):
        reader.get_active_task("escape")


def test_modern_protocol_discovery_tool_list_and_calls(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, _, memory = context_fixture
    server = ContextMcpServer(TeamContextReader(projects, team_memory_root=memory))

    discover = server.handle(_request(1, "server/discover"))
    assert discover["result"]["resultType"] == "complete"
    assert discover["result"]["supportedVersions"] == [PROTOCOL_VERSION]
    assert discover["result"]["capabilities"] == {"tools": {"listChanged": False}}

    listed = server.handle(_request(2, "tools/list"))
    tools = listed["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
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
    ]
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)

    called = server.handle(
        _request(
            3,
            "tools/call",
            {"name": "get_active_task", "arguments": {"project": "demo"}},
        )
    )
    result = called["result"]
    assert result["resultType"] == "complete"
    assert result["isError"] is False
    assert result["structuredContent"]["current"]["task_id"] == "T002"
    assert result["structuredContent"]["query_stats"]["returned_bytes"] > 0
    assert result["structuredContent"]["query_stats"]["source_bytes"] > 0
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_modern_protocol_errors_are_actionable(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, _, memory = context_fixture
    server = ContextMcpServer(TeamContextReader(projects, team_memory_root=memory))

    mismatch = _request(1, "tools/list")
    mismatch["params"]["_meta"][
        "io.modelcontextprotocol/protocolVersion"
    ] = "2025-11-25"
    response = server.handle(mismatch)
    assert response["error"]["code"] == -32022
    assert response["error"]["data"]["supported"] == [PROTOCOL_VERSION]

    unknown = server.handle(
        _request(
            2,
            "tools/call",
            {"name": "missing", "arguments": {}},
        )
    )
    assert unknown["error"]["code"] == -32602

    bad_argument = server.handle(
        _request(
            3,
            "tools/call",
            {
                "name": "get_active_task",
                "arguments": {"project": "demo", "extra": True},
            },
        )
    )
    assert bad_argument["result"]["isError"] is True
    assert "unknown arguments" in bad_argument["result"]["content"][0]["text"]


def test_stdio_transport_is_newline_delimited_and_read_only(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, project, memory = context_fixture
    server = ContextMcpServer(TeamContextReader(projects, team_memory_root=memory))
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    requests = [
        _request(1, "server/discover"),
        _request(
            2,
            "tools/call",
            {
                "name": "search_team_memory",
                "arguments": {
                    "project": "demo",
                    "query": "Integration Gate",
                    "scope": "all",
                },
            },
        ),
    ]
    input_stream = io.StringIO(
        "".join(json.dumps(request) + "\n" for request in requests)
    )
    output_stream = io.StringIO()

    assert server.serve(input_stream, output_stream) == 0
    responses = [
        json.loads(line) for line in output_stream.getvalue().splitlines()
    ]
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[1]["result"]["isError"] is False
    after = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    assert after == before


def test_legacy_client_compatibility_does_not_change_modern_version(
    context_fixture: tuple[Path, Path, Path],
) -> None:
    projects, _, memory = context_fixture
    server = ContextMcpServer(TeamContextReader(projects, team_memory_root=memory))

    initialized = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "legacy-test", "version": "1"},
            },
        }
    )
    assert initialized["result"]["protocolVersion"] == "2025-11-25"
    listed = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    assert "resultType" not in listed["result"]
    assert PROTOCOL_VERSION == "2026-07-28"
