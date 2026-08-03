#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codexteam_tools.context_mcp import modern_meta
from codexteam_tools.paths import normalize_task_id, validate_identifier
from codexteam_tools.roles import load_role_policy


class StdioClient:
    def __init__(
        self,
        server_script: Path,
        projects_root: Path,
        team_memory_root: Path | None,
    ) -> None:
        argv = [
            sys.executable,
            str(server_script),
            "--projects-root",
            str(projects_root),
        ]
        if team_memory_root is not None:
            argv.extend(["--team-memory-root", str(team_memory_root)])
        self.process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.next_id = 1

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        request_id = self.next_id
        self.next_id += 1
        values = dict(params or {})
        values["_meta"] = modern_meta()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": values,
        }
        self.process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"MCP server terminated without a response: {stderr}")
        response = json.loads(line)
        if response.get("id") != request_id:
            raise RuntimeError("MCP response ID mismatch")
        if "error" in response:
            raise RuntimeError(json.dumps(response["error"], sort_keys=True))
        return response

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)


def _read_existing(paths: list[Path]) -> bytes:
    return b"\n".join(path.read_bytes() for path in paths if path.is_file())


def _run_commands(commands: list[list[str]], cwd: Path) -> tuple[bytes, list[int]]:
    chunks: list[bytes] = []
    exit_codes: list[int] = []
    for argv in commands:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            check=False,
        )
        chunks.extend((completed.stdout, completed.stderr))
        exit_codes.append(completed.returncode)
    return b"\n".join(chunks), exit_codes


def _median_duration(operation, repeats: int) -> tuple[float, Any]:
    durations: list[float] = []
    last = None
    for _ in range(repeats):
        started = time.perf_counter()
        last = operation()
        durations.append((time.perf_counter() - started) * 1_000)
    return round(statistics.median(durations), 3), last


def _percent_reduction(before: int, after: int) -> float:
    if before == 0:
        return 0.0
    return round((before - after) * 100 / before, 1)


def _estimated_tokens(size: int) -> int:
    return (size + 3) // 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare read-only Team Context MCP retrieval with current file and shell paths."
    )
    parser.add_argument("--projects-root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--attempt", default="att-001")
    parser.add_argument("--role", default="developer")
    parser.add_argument("--team-memory-root", type=Path)
    parser.add_argument("--memory-query", default="responsive Commit")
    parser.add_argument("--repository-query", default="responsive")
    parser.add_argument("--repeats", type=int, default=7)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeats < 1 or args.repeats > 100:
        print("ERROR: --repeats must be between 1 and 100", file=sys.stderr)
        return 2
    task_id = normalize_task_id(args.task)
    attempt_id = validate_identifier(args.attempt, label="attempt ID")
    role_policy = load_role_policy(args.role)
    projects_root = args.projects_root.resolve(strict=True)
    project = (projects_root / args.project).resolve(strict=True)
    project.relative_to(projects_root)
    script_root = Path(__file__).resolve().parent
    server_script = script_root / "team-context-mcp.py"
    team_memory_root = (
        args.team_memory_root.resolve(strict=True)
        if args.team_memory_root is not None
        else None
    )
    memory_files = (
        sorted(team_memory_root.glob("*.md"))
        if team_memory_root is not None
        else []
    )
    memory_patterns = re.findall(
        r"[a-z0-9][a-z0-9_.-]*",
        args.memory_query.lower(),
    )
    gate_records = [
        project / "results/gates/development.json",
        project / "results/gates/integration.json",
    ]
    runtime_root = project / ".codexteam/runtime/sessions"
    runtime_state_files = (
        sorted(runtime_root.glob("*/*/*/session.json"))
        + sorted(runtime_root.glob("*/*/*/turn-state.json"))
        if runtime_root.is_dir()
        else []
    )
    attempt_dirs = (
        [
            path
            for path in runtime_root.glob(f"*/{task_id}/{attempt_id}")
            if path.is_dir()
        ]
        if runtime_root.is_dir()
        else []
    )
    attempt_dir = attempt_dirs[0] if len(attempt_dirs) == 1 else None
    attempt_metrics = (
        sorted((attempt_dir / "turns").glob("*.metrics.json"))
        if attempt_dir is not None
        else []
    )
    all_metrics = (
        sorted(runtime_root.glob("*/*/*/turns/*.metrics.json"))
        if runtime_root.is_dir()
        else []
    )
    result_path = project / f"results/{task_id}-{attempt_id}.json"
    if attempt_dir is not None:
        session_path = attempt_dir / "session.json"
        if session_path.is_file():
            try:
                session = json.loads(session_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                session = {}
            configured_result = session.get("final_result_path")
            if isinstance(configured_result, str):
                candidate = (project / configured_result).resolve(strict=False)
                try:
                    candidate.relative_to(project)
                except ValueError:
                    pass
                else:
                    result_path = candidate
    evidence_paths: list[Path] = []
    if result_path.is_file():
        try:
            result_record = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result_record = {}
        for item in result_record.get("evidence", []):
            if not isinstance(item, dict) or not isinstance(item.get("artifact_ref"), str):
                continue
            candidate = (project / item["artifact_ref"]).resolve(strict=False)
            try:
                candidate.relative_to(project)
            except ValueError:
                continue
            if candidate.is_file():
                evidence_paths.append(candidate)
    repository_files = [
        path
        for relative in ("web", "tests", "src", "internal", "cmd")
        for path in (project / relative).rglob("*")
        if path.is_file() and not path.is_symlink()
    ]
    result_projection = (
        "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));"
        "print(json.dumps({k:d.get(k) for k in "
        "('status','summary','file_changes','evidence','errors','warnings','limitations')},"
        "separators=(',',':')))"
    )
    scenarios = {
        "active_task": {
            "tool": "get_active_task",
            "arguments": {"project": args.project},
            "broad": [
                project / "CURRENT_TASK.md",
                project / "TASKS.md",
                project / f"management/tasks/{task_id}.md",
            ],
            "focused": [
                ["sed", "-n", "1,160p", "CURRENT_TASK.md"],
                ["rg", "--fixed-strings", f"| {task_id} |", "TASKS.md"],
                [
                    sys.executable,
                    str(script_root / "subagent-status.py"),
                    str(project),
                    "--json",
                ],
            ],
        },
        "project_overview": {
            "tool": "get_project_overview",
            "arguments": {"project": args.project},
            "broad": [
                project / "PROJECT_STATE.md",
                project / "CURRENT_TASK.md",
                project / "TASKS.md",
                project / "management/TEST_GATES.toml",
                *gate_records,
                *runtime_state_files,
            ],
            "focused": [
                ["sed", "-n", "1,160p", "PROJECT_STATE.md"],
                ["sed", "-n", "1,160p", "CURRENT_TASK.md"],
                [
                    sys.executable,
                    str(script_root / "subagent-status.py"),
                    str(project),
                    "--active-only",
                    "--json",
                ],
                ["git", "status", "--short"],
                [
                    sys.executable,
                    str(script_root / "run-test-gate.py"),
                    str(project),
                    "--gate",
                    "development",
                    "--check-record",
                    "--json",
                ],
                [
                    sys.executable,
                    str(script_root / "run-test-gate.py"),
                    str(project),
                    "--gate",
                    "integration",
                    "--check-record",
                    "--json",
                ],
            ],
        },
        "list_tasks": {
            "tool": "list_tasks",
            "arguments": {
                "project": args.project,
                "status": "In Progress",
                "limit": 20,
            },
            "broad": [project / "TASKS.md"],
            "focused": [
                ["rg", "-n", "--fixed-strings", "| In Progress |", "TASKS.md"],
            ],
        },
        "task_handoff": {
            "tool": "get_task_handoff",
            "arguments": {"project": args.project, "task_id": task_id},
            "broad": [
                project / "TASKS.md",
                project / f"management/tasks/{task_id}.md",
            ],
            "focused": [
                ["sed", "-n", "1,260p", f"management/tasks/{task_id}.md"],
                ["rg", "--fixed-strings", f"| {task_id} |", "TASKS.md"],
            ],
        },
        "task_context": {
            "tool": "get_task_context",
            "arguments": {
                "project": args.project,
                "task_id": task_id,
                "role": args.role,
            },
            "broad": [
                project / "TASKS.md",
                project / f"management/tasks/{task_id}.md",
                project / "ARCHITECTURE.md",
                project / "DECISIONS.md",
                project / "management/TEST_GATES.toml",
                script_root.parent / f"roles/{args.role}.toml",
                *runtime_state_files,
            ],
            "focused": [
                ["sed", "-n", "1,280p", f"management/tasks/{task_id}.md"],
                ["rg", "--fixed-strings", f"| {task_id} |", "TASKS.md"],
                ["sed", "-n", "1,220p", "management/TEST_GATES.toml"],
                ["sed", "-n", "1,240p", str(script_root.parent / f"roles/{args.role}.toml")],
                [
                    sys.executable,
                    str(script_root / "subagent-status.py"),
                    str(project),
                    "--active-only",
                    "--json",
                ],
            ],
        },
        "attempt_summary": {
            "tool": "get_attempt_summary",
            "arguments": {
                "project": args.project,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "max_turns": 5,
            },
            "broad": [
                *(
                    [
                        attempt_dir / "session.json",
                        attempt_dir / "turn-state.json",
                    ]
                    if attempt_dir is not None
                    else []
                ),
                *attempt_metrics,
                result_path,
            ],
            "focused": [
                [
                    sys.executable,
                    str(script_root / "subagent-status.py"),
                    str(project),
                    "--json",
                ],
                *(
                    [
                        [
                            sys.executable,
                            "-c",
                            result_projection,
                            str(result_path.relative_to(project)),
                        ]
                    ]
                    if result_path.is_file()
                    else []
                ),
                *[
                    ["sed", "-n", "1,240p", str(path.relative_to(project))]
                    for path in attempt_metrics[-5:]
                ],
            ],
        },
        "gate_status": {
            "tool": "get_gate_status",
            "arguments": {"project": args.project},
            "broad": [project / "management/TEST_GATES.toml", *gate_records],
            "focused": [
                ["sed", "-n", "1,220p", "management/TEST_GATES.toml"],
                [
                    sys.executable,
                    str(script_root / "run-test-gate.py"),
                    str(project),
                    "--gate",
                    "development",
                    "--check-record",
                    "--json",
                ],
                [
                    sys.executable,
                    str(script_root / "run-test-gate.py"),
                    str(project),
                    "--gate",
                    "integration",
                    "--check-record",
                    "--json",
                ],
            ],
        },
        "validate_result": {
            "tool": "validate_result_record",
            "arguments": {
                "project": args.project,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "role": args.role,
            },
            "broad": [result_path, *evidence_paths],
            "focused": [
                [
                    sys.executable,
                    str(script_root / "verify-result.py"),
                    str(result_path),
                    "--task",
                    task_id,
                    "--attempt",
                    attempt_id,
                    "--role",
                    args.role,
                ],
                *(
                    [
                        [
                            sys.executable,
                            "-c",
                            result_projection,
                            str(result_path.relative_to(project)),
                        ]
                    ]
                    if result_path.is_file()
                    else []
                ),
            ],
        },
        "cost_hotspots": {
            "tool": "get_cost_hotspots",
            "arguments": {
                "project": args.project,
                "phase": "draft",
                "limit": 10,
            },
            "broad": all_metrics,
            "focused": [
                [
                    "rg",
                    "-n",
                    "--fixed-strings",
                    '"input_tokens"',
                    ".codexteam/runtime/sessions",
                    "--glob",
                    "*.metrics.json",
                ],
            ],
        },
        "memory_search": {
            "tool": "search_team_memory",
            "arguments": {
                "project": args.project,
                "query": args.memory_query,
                "scope": "all",
                "limit": 3,
            },
            "broad": [
                project / "DECISIONS.md",
                project / "OPEN_QUESTIONS.md",
                *memory_files,
            ],
            "focused": [
                [
                    "rg",
                    "-n",
                    "-i",
                    "--fixed-strings",
                    *[
                        value
                        for pattern in memory_patterns
                        for value in ("-e", pattern)
                    ],
                    "DECISIONS.md",
                    "OPEN_QUESTIONS.md",
                    *[str(path) for path in memory_files],
                ]
            ],
        },
        "repository_search": {
            "tool": "search_repository",
            "arguments": {
                "project": args.project,
                "query": args.repository_query,
                "scope": "tests",
                "limit": 10,
            },
            "broad": repository_files,
            "focused": [
                [
                    "rg",
                    "-n",
                    "-i",
                    "--fixed-strings",
                    args.repository_query,
                    "web",
                    "tests",
                ],
            ],
        },
        "change_summary": {
            "tool": "get_change_summary",
            "arguments": {
                "project": args.project,
                "detail": "summary",
                "limit": 40,
            },
            "broad": [],
            "focused": [
                ["git", "status", "--short"],
                ["git", "diff", "--shortstat"],
                ["git", "diff", "--cached", "--shortstat"],
            ],
        },
    }

    client = StdioClient(server_script, projects_root, team_memory_root)
    try:
        discovery = client.call("server/discover")
        listed = client.call("tools/list")
        schema_bytes = len(
            json.dumps(
                listed["result"]["tools"],
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        allowed_tool_names = set(
            role_policy.tools_for_server("codexteam-context")
        )
        if "codexteam-context" not in role_policy.mcp_servers:
            effective_tools: list[dict[str, Any]] = []
        elif allowed_tool_names:
            effective_tools = [
                tool
                for tool in listed["result"]["tools"]
                if tool.get("name") in allowed_tool_names
            ]
        else:
            effective_tools = listed["result"]["tools"]
        effective_schema_bytes = len(
            json.dumps(
                effective_tools,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        report: dict[str, Any] = {
            "protocol": discovery["result"]["supportedVersions"][0],
            "project": args.project,
            "task": task_id,
            "role": role_policy.role,
            "repeats": args.repeats,
            "tool_schema_bytes": schema_bytes,
            "tool_schema_estimated_tokens": _estimated_tokens(schema_bytes),
            "effective_tool_names": [
                tool["name"]
                for tool in effective_tools
            ],
            "effective_tool_schema_bytes": effective_schema_bytes,
            "effective_tool_schema_estimated_tokens": _estimated_tokens(
                effective_schema_bytes
            ),
            "tool_schema_reduction_percent": _percent_reduction(
                schema_bytes,
                effective_schema_bytes,
            ),
            "token_estimate_note": "Estimated at 4 UTF-8 bytes/token; not provider billing usage.",
            "scenarios": {},
        }
        for name, scenario in scenarios.items():
            broad = _read_existing(scenario["broad"])
            focused_ms, focused_result = _median_duration(
                lambda scenario=scenario: _run_commands(
                    scenario["focused"],
                    project,
                ),
                args.repeats,
            )
            focused, focused_exit_codes = focused_result
            mcp_ms, response = _median_duration(
                lambda scenario=scenario: client.call(
                    "tools/call",
                    {
                        "name": scenario["tool"],
                        "arguments": scenario["arguments"],
                    },
                ),
                args.repeats,
            )
            structured = json.dumps(
                response["result"]["structuredContent"],
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            wire_result = json.dumps(
                response["result"],
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            report["scenarios"][name] = {
                "broad_read_bytes": len(broad),
                "focused_shell_bytes": len(focused),
                "focused_shell_exit_codes": focused_exit_codes,
                "mcp_structured_bytes": len(structured),
                "mcp_wire_result_bytes": len(wire_result),
                "broad_to_mcp_reduction_percent": _percent_reduction(
                    len(broad),
                    len(structured),
                ),
                "focused_to_mcp_reduction_percent": _percent_reduction(
                    len(focused),
                    len(structured),
                ),
                "focused_shell_median_ms": focused_ms,
                "mcp_roundtrip_median_ms": mcp_ms,
                "mcp_structured_estimated_tokens": _estimated_tokens(
                    len(structured)
                ),
            }
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
