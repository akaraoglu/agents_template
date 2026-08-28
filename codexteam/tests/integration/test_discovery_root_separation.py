"""Integration coverage for discovery-root separation and MCP source isolation.

These tests exercise the real TeamContextReader and ContextMcpServer paths
against a synthetic split project tree. The assertions verify that discovery
search stays in the dedicated discoveries root, that source-root files under
src/ are not treated as discovery memory, and that task context still reports
the canonical architecture and decision sources from the control plane.
"""

from __future__ import annotations

from pathlib import Path

from codexteam_tools.context_mcp import ContextMcpServer
from codexteam_tools.team_context import TeamContextReader

PROJECT_ID = "demo"
OTHER_PROJECT_ID = "other"
TASK_ID = "T032"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_gate_config(project_root: Path) -> None:
    _write(
        project_root / "management/TEST_GATES.toml",
        (
            'schema_version = "1.0"\n'
            'verification_paths = ["docs/**", "discoveries/**", "management/**"]\n\n'
            "[development]\n"
            "configured = true\n"
            'execution_surface = "worker"\n'
            "expected_max_seconds = 30\n"
            'commands = [["python", "-c", "print(\'dev\')"]]\n\n'
            "[integration]\n"
            "configured = true\n"
            'execution_surface = "lead_host"\n'
            "expected_max_seconds = 60\n"
            'includes = ["development"]\n'
            'commands = [["python", "-c", "print(\'integration\')"]]\n'
        ),
    )


def _write_task_docs(project_root: Path) -> None:
    _write(
        project_root / "TASKS.md",
        (
            "# Tasks\n\n"
            "| Task ID | Description | Status | Owner | Verification | Evidence |\n"
            "|---|---|---|---|---|---|\n"
            "| T001 | Baseline setup | Completed | lead | Passed | evidence |\n"
            "| T032 | Verify discovery-root separation | In Progress | tester | Pending | pending |\n"
        ),
    )
    _write(
        project_root / "management/tasks/T032.md",
        (
            "# Task T032: Verify discovery-root separation\n\n"
            "## Objective\n\n"
            "Test control discoveries, source-root exclusion, project isolation, bounds, "
            "dates, and legacy architecture/decision retrieval.\n"
            "Legacy references live in `docs/architecture/2026-08-27_reader_contract.md` "
            "and `docs/decisions/ADR-0002-bounded-memory.md`.\n\n"
            "## Dependencies\n\n"
            "None.\n\n"
            "## Allowed Paths\n\n"
            "- `docs/**`\n"
            "- `discoveries/**`\n"
            "- `results/**`\n\n"
            "## Verification\n\n"
            "Run focused discovery tests.\n"
        ),
    )


def _write_project_sources(project_root: Path) -> None:
    _write(
        project_root / "ARCHITECTURE.md",
        (
            "# Architecture\n\n"
            "## Notes\n\n"
            "The gloriana architecture note stays in the control root.\n"
        ),
    )
    _write(
        project_root / "DECISIONS.md",
        (
            "# Decisions\n\n"
            "## D001 - Bounded memory\n\n"
            "- Status: Accepted\n"
            "- Date: 2026-08-27\n"
            "- Decision: The vulcana decision stays in the control root.\n"
        ),
    )
    _write(
        project_root / "docs/architecture/2026-08-27_reader_contract.md",
        (
            "# Reader Contract\n\n"
            "## Scope\n\n"
            "The falcons contract proves the legacy architecture path is still read.\n"
        ),
    )
    _write(
        project_root / "docs/decisions/ADR-0002-bounded-memory.md",
        (
            "# ADR-0002\n\n"
            "## D010 - Bounded memory\n\n"
            "- Status: Accepted\n"
            "- Date: 2026-08-26\n"
            "- Decision: The quetzal decision preserves legacy decision retrieval.\n"
        ),
    )
    _write(
        project_root / "discoveries/2026-08-27_migrated_discovery.md",
        (
            "# Discovery\n\n"
            "## Evidence\n\n"
            "The migrated-discovery token lives in discoveries/.\n"
        ),
    )
    _write(
        project_root / "src/discoveries/2026-08-27_legacy_discovery.md",
        (
            "# Legacy Discovery\n\n"
            "## Evidence\n\n"
            "The legacy-discovery-only token lives under src/discoveries/.\n"
        ),
    )


def _write_control_project(project_root: Path) -> None:
    _write_gate_config(project_root)
    _write_task_docs(project_root)
    _write_project_sources(project_root)


def _write_other_project(project_root: Path) -> None:
    _write(
        project_root / "discoveries/2026-08-27_cross_project.md",
        (
            "# Cross Project\n\n"
            "## Evidence\n\n"
            "The other-only token belongs to the other project.\n"
        ),
    )


def _build_workspace(tmp_path: Path) -> Path:
    projects_root = tmp_path / "projects"
    demo_root = projects_root / PROJECT_ID
    other_root = projects_root / OTHER_PROJECT_ID
    _write_control_project(demo_root)
    _write_other_project(other_root)
    return projects_root


def test_task_context_sources_stay_in_control_plane_and_exclude_source_tree(
    tmp_path: Path,
) -> None:
    projects_root = _build_workspace(tmp_path)
    server = ContextMcpServer(TeamContextReader(projects_root))

    context = server.insights.get_task_context(PROJECT_ID, TASK_ID, role="tester")
    source_paths = {source["path"] for source in context["sources"]}

    assert context["architecture_references"] == [
        "ARCHITECTURE.md",
        "DECISIONS.md",
        "docs/architecture/2026-08-27_reader_contract.md",
        "docs/decisions/ADR-0002-bounded-memory.md",
    ]
    assert {
        "TASKS.md",
        "management/TEST_GATES.toml",
        "management/tasks/T032.md",
        "role-policy/tester.toml",
        "ARCHITECTURE.md",
        "DECISIONS.md",
        "docs/architecture/2026-08-27_reader_contract.md",
        "docs/decisions/ADR-0002-bounded-memory.md",
    }.issubset(source_paths)
    assert all(not path.startswith("src/") for path in source_paths)


def test_team_memory_search_keeps_discoveries_bounded_and_legacy_sources_routed(
    tmp_path: Path,
) -> None:
    projects_root = _build_workspace(tmp_path)
    reader = TeamContextReader(projects_root)

    project_cases = [
        (
            "gloriana",
            "ARCHITECTURE.md",
            "project_architecture",
            None,
            None,
        ),
        (
            "falcons",
            "docs/architecture/2026-08-27_reader_contract.md",
            "project_architecture",
            None,
            None,
        ),
        (
            "vulcana",
            "DECISIONS.md",
            "project_decision",
            "Accepted",
            "2026-08-27",
        ),
        (
            "quetzal",
            "docs/decisions/ADR-0002-bounded-memory.md",
            "project_decision",
            "Accepted",
            "2026-08-26",
        ),
    ]
    for query, expected_source, expected_source_type, expected_status, expected_date in project_cases:
        result = reader.search_team_memory(PROJECT_ID, query, scope="project")
        assert result["searched_sources"] == 4
        match = result["matches"][0]
        assert match["source"] == expected_source
        assert match["source_type"] == expected_source_type
        assert match["status"] == expected_status
        assert match["date"] == expected_date

    discovery_result = reader.search_team_memory(
        PROJECT_ID,
        "migrated-discovery",
        scope="discoveries",
    )
    assert discovery_result["searched_sources"] == 1
    assert discovery_result["matches"] == [
        {
            "scope": "discoveries",
            "source_type": "project_discovery",
            "source": "discoveries/2026-08-27_migrated_discovery.md",
            "line": 3,
            "text": "## Evidence\n\nThe migrated-discovery token lives in discoveries/.",
            "status": None,
            "date": "2026-08-27",
            "truncated": False,
        }
    ]

    excluded = reader.search_team_memory(
        PROJECT_ID,
        "legacy-discovery-only",
        scope="all",
    )
    assert excluded["matches"] == []

    cross_project = reader.search_team_memory(
        PROJECT_ID,
        "other-only",
        scope="all",
    )
    assert cross_project["matches"] == []
