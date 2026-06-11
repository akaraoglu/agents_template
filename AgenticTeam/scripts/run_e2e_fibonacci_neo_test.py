#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from AgenticTeam.scripts.run_e2e_fibonacci_test import validate_fibonacci_visualizer_project
from AgenticTeam.scripts.create_project import DEFAULT_PROJECT_ROOT
from AgenticTeam.scripts.project_layout import project_dir_for


DEFAULT_TITLE = "Fibonacci Tree Visualizer"
NEO_PROJECT_FILE = Path("/home/alik/workspace/clawspace/workspaces/neo/team_PROJECT.md")
LIVE_TEAM_COMMAND = "/home/alik/workspace/clawspace/bin/run_team.sh"


def default_project_id() -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-e2e-fibonacci-neo-{stamp}"


def load_fibonacci_project_info() -> str:
    fixture_path = REPO_ROOT / "AgenticTeam" / "fixtures" / "fibonacci_tree_visualizer.md"
    return fixture_path.read_text(encoding="utf-8")


def build_neo_fibonacci_request(
    *,
    project_id: str,
    title: str,
    project_root: Path,
    project_info: str,
) -> str:
    return f"""Neo, start this as a real team project through your normal project intake path.

This is the full-team Fibonacci E2E. Do not run Smith, Morpheus, or Oracle manually. Do not use legacy project scripts, handoff scripts, named-session routing, or subagents.

Use these exact project fields:
- Project ID: {project_id}
- Project title: {title}
- Project root: {project_root}
- Project goal file: {NEO_PROJECT_FILE}

Required action:
1. Write the full project information between PROJECT_INFO_BEGIN and PROJECT_INFO_END to `{NEO_PROJECT_FILE}`.
2. Run the team command in background mode, including the known Fibonacci fixture selector:
   `bash {LIVE_TEAM_COMMAND} --background --project-root {project_root} --project-id "{project_id}" --title "{title}" --project-file {NEO_PROJECT_FILE} --fixture fibonacci_tree_visualizer`
3. Do not wait inside your own turn for Smith, Morpheus, or Oracle to finish; the background runtime owns that loop.
4. Report the printed `TEAM_STARTED`, `PROJECT_ID`, `EXPECTED_PROJECT_PATH`, `TEAM_PID`, and `TEAM_LOG` values.
5. If the command fails, report the exact output and do not claim success.

PROJECT_INFO_BEGIN
{project_info.strip()}
PROJECT_INFO_END
"""


def run_neo_agent(request: str, *, session_key: str, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    command = [
        "openclaw",
        "agent",
        "--agent",
        "neo",
        "--session-key",
        session_key,
        "--message",
        request,
        "--timeout",
        str(timeout_seconds),
        "--thinking",
        "off",
    ]
    return subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_seconds + 120,
        check=False,
    )


def read_project_phase(project_dir: Path) -> str | None:
    state_path = project_dir / ".openclaw" / "state.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8")).get("phase")
    except json.JSONDecodeError:
        return None


def wait_for_terminal_project(project_dir: Path, *, timeout_seconds: int, poll_seconds: float = 5.0) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    terminal = {"DONE", "BLOCKED", "FAILED"}
    while time.monotonic() < deadline:
        phase = read_project_phase(project_dir)
        if phase in terminal:
            return phase
        time.sleep(poll_seconds)
    return read_project_phase(project_dir)


def validate_neo_e2e_project_structure(project_dir: Path) -> list[str]:
    errors: list[str] = []
    for task_id in ("T001", "T002", "T003", "T004"):
        task_file = project_dir / "management" / "tasks" / f"{task_id}.md"
        if not task_file.is_file():
            errors.append(f"missing management/tasks/{task_id}.md")
    events_path = project_dir / ".openclaw" / "events.jsonl"
    if not events_path.is_file():
        errors.append("missing .openclaw/events.jsonl")
    return errors


def run_neo_fibonacci_e2e(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    project_id = args.project_id or default_project_id()
    title = args.title
    project_dir = project_dir_for(project_root, project_id)

    if project_dir.exists():
        print(f"ERROR: project already exists: {project_dir}", file=sys.stderr)
        return 2

    request = build_neo_fibonacci_request(
        project_id=project_id,
        title=title,
        project_root=project_root,
        project_info=load_fibonacci_project_info(),
    )
    session_key = args.session_key or f"agent:neo:{project_id}"

    print(f"NEO_E2E_PROJECT_ID={project_id}", flush=True)
    print(f"NEO_E2E_SESSION_KEY={session_key}", flush=True)
    print("Sending project info to Neo through openclaw agent...", flush=True)
    result = run_neo_agent(request, session_key=session_key, timeout_seconds=args.timeout_seconds)

    if result.stdout.strip():
        print("\n=== Neo stdout ===")
        print(result.stdout.strip())
    if result.stderr.strip():
        print("\n=== Neo stderr ===", file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)

    if result.returncode != 0 and not project_dir.exists():
        print(f"ERROR: Neo agent command failed with exit code {result.returncode}", file=sys.stderr)
        print(f"ERROR: Neo did not create project directory: {project_dir}", file=sys.stderr)
        print("NEO_E2E_RESULT=BLOCKED")
        return 1

    phase = wait_for_terminal_project(
        project_dir,
        timeout_seconds=args.post_agent_timeout_seconds,
        poll_seconds=args.poll_seconds,
    )

    if result.returncode != 0 and phase != "DONE":
        print(f"ERROR: Neo agent command failed with exit code {result.returncode}", file=sys.stderr)
        print("Project was created, but it did not reach DONE after Neo returned.", file=sys.stderr)
        print("NEO_E2E_RESULT=BLOCKED")
        return 1

    if not project_dir.exists():
        print(f"ERROR: Neo did not create project directory: {project_dir}", file=sys.stderr)
        print("NEO_E2E_RESULT=BLOCKED")
        return 1

    errors = []
    errors.extend(validate_neo_e2e_project_structure(project_dir))
    errors.extend(validate_fibonacci_visualizer_project(project_dir))
    if phase != "DONE":
        errors.append(f"final phase is {phase!r}, expected DONE")

    if errors:
        print("ERROR: Neo-driven Fibonacci E2E validation failed:")
        for error in errors:
            print(f"- {error}")
        print(f"FINAL_PROJECT_PATH={project_dir}")
        print("NEO_E2E_RESULT=BLOCKED")
        return 1

    print(f"FINAL_PROJECT_PATH={project_dir}")
    print("NEO_E2E_RESULT=DONE")
    print("Neo-driven Fibonacci E2E passed.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the real Neo-intake Fibonacci E2E.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--project-id", help="Project id / directory slug. Defaults to timestamped Neo E2E slug.")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--session-key", help="Explicit Neo session key. Defaults to agent:neo:<project-id>.")
    parser.add_argument("--timeout-seconds", type=int, default=1200, help="Timeout passed to openclaw agent.")
    parser.add_argument("--post-agent-timeout-seconds", type=int, default=1200, help="Extra time to observe final project state after Neo returns.")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    return run_neo_fibonacci_e2e(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
