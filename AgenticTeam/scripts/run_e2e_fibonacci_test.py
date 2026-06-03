#!/usr/bin/env python3
"""Run the fixed Fibonacci Tree Visualizer E2E canary against the live team."""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from canaries.common import worker_draft_evidence

DEFAULT_TITLE = "run_e2e_fibonacci_test"
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_POLL_SECONDS = 15
DEFAULT_STALL_SECONDS = 180
DEFAULT_SPEC = (Path(__file__).resolve().parents[1] / "fixtures" / "fibonacci_tree_visualizer.md").read_text(encoding="utf-8")

REQUIRED_PLAN_STRINGS = (
    "## Overview",
    "## Phases",
    "T001: Core Fibonacci Logic & Tree Generation Engine",
    "T002: ASCII/Unicode Rendering Engine",
    "T003: CLI Interface & Parameter Implementation",
    "T004: Testing & Final Verification",
)
REQUIRED_TASK_FILES = ("T001.md", "T002.md", "T003.md", "T004.md")
REQUIRED_OUTPUTS = ("README.md", "src/main.py", "tests/test_main.py")
REQUIRED_HANDOFFS = (
    ("neo", "smith"),
    ("smith", "niaobe"),
    ("niaobe", "architect"),
    ("niaobe", "morpheus"),
    ("niaobe", "oracle"),
)
TERMINAL_PHASES = {"DONE", "BLOCKED"}


class CommandError(RuntimeError):
    """Raised when a subprocess command fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--stall-seconds", type=int, default=DEFAULT_STALL_SECONDS)
    parser.add_argument("--report-file", help="Optional path to write the final report.")
    return parser.parse_args()


def run(cmd: list[str], *, timeout: int = 120) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        details = "\n".join(part for part in (stdout, stderr) if part)
        raise CommandError(f"{' '.join(cmd)} failed with code {result.returncode}: {details}")
    return stdout


def gateway_is_listening() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", 18789)) == 0


def parse_project_id(output: str) -> str:
    match = re.search(r"Project ID:\s*([a-z0-9-]+)", output)
    if not match:
        raise CommandError(f"could not parse project id from new_project output:\n{output}")
    return match.group(1)


def parse_envelope(output: str) -> str:
    for raw in output.splitlines():
        if raw.startswith("ENVELOPE: "):
            return raw.split("ENVELOPE: ", 1)[1].strip()
    raise CommandError(f"handoff output did not contain ENVELOPE:\n{output}")


def send_session_message(session_key: str, message: str, *, timeout_ms: int = 20000) -> str:
    payload = json.dumps({"key": session_key, "message": message}, separators=(",", ":"))
    return run(
        [
            "openclaw",
            "gateway",
            "call",
            "sessions.send",
            "--json",
            "--params",
            payload,
            "--timeout",
            str(timeout_ms),
        ],
        timeout=max(30, timeout_ms // 1000 + 10),
    )


def parse_state_field(text: str, field: str) -> str:
    exact = re.compile(rf"^\s*{re.escape(field)}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    bullet = re.compile(rf"^\s*-\s*\*\*{re.escape(field)}\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = exact.search(text) or bullet.search(text)
    return match.group(1).strip().strip('"') if match else ""


def validation_report_paths(project_dir: Path) -> list[Path]:
    validation_dir = project_dir / "management" / "validation"
    if not validation_dir.exists():
        return []
    return sorted(path for path in validation_dir.glob("*_REPORT.md") if path.is_file())


def load_handoff_events(project_dir: Path) -> list[dict[str, object]]:
    handoff_path = project_dir / ".openclaw" / "handoffs.jsonl"
    if not handoff_path.exists():
        return []
    events: list[dict[str, object]] = []
    for raw in handoff_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def load_latest_worker_state(project_id: str, role: str) -> dict[str, object] | None:
    runs_root = Path("/home/alik/workspace/clawspace/workspaces") / role / "runs" / project_id
    if not runs_root.exists():
        return None
    states = sorted(
        (path for path in runs_root.glob("**/state.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    if not states:
        return None
    try:
        payload = json.loads(states[-1].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    payload["state_file"] = str(states[-1])
    return payload


def collect_plan_faults(project_dir: Path) -> list[str]:
    faults: list[str] = []
    plan_path = project_dir / "management" / "PLAN.md"
    if not plan_path.exists():
        return ["management/PLAN.md was not produced."]

    plan_text = plan_path.read_text(encoding="utf-8")
    missing_strings = [token for token in REQUIRED_PLAN_STRINGS if token not in plan_text]
    if missing_strings:
        faults.append(
            "management/PLAN.md is missing required deterministic planning content: "
            + ", ".join(missing_strings)
            + "."
        )

    task_dir = project_dir / "management" / "tasks"
    present_task_files = sorted(path.name for path in task_dir.glob("T*.md")) if task_dir.exists() else []
    missing_task_files = [name for name in REQUIRED_TASK_FILES if name not in present_task_files]
    extra_task_files = [name for name in present_task_files if name not in REQUIRED_TASK_FILES]
    if missing_task_files:
        faults.append("Missing required task files: " + ", ".join(missing_task_files) + ".")
    if extra_task_files:
        faults.append("Unexpected extra task files were created: " + ", ".join(extra_task_files) + ".")

    return faults


def collect_faults(project_id: str, project_dir: Path, state_text: str, *, timed_out: bool, stalled: bool) -> list[str]:
    faults: list[str] = []
    phase = parse_state_field(state_text, "phase").upper() or "missing"
    owner = parse_state_field(state_text, "owner") or "missing"
    waiting_for = parse_state_field(state_text, "waiting_for") or "missing"
    task_phase = parse_state_field(state_text, "task_phase") or "missing"
    blocked_reason = parse_state_field(state_text, "blocked_reason") or "none"
    active_task = parse_state_field(state_text, "active_task") or "T001"
    architect_worker = load_latest_worker_state(project_id, "architect")
    morpheus_worker = load_latest_worker_state(project_id, "morpheus")
    architecture_path = f"management/architecture/{active_task}.md"
    architect_drafts = worker_draft_evidence(project_id, "architect")
    architect_orphan_drafts = [
        item for item in architect_drafts if item.get("draft_file_exists") and not item.get("state_file_exists")
    ]

    if timed_out:
        faults.append(
            f"Timed out before terminal completion. Final state: owner={owner}, phase={phase}, task_phase={task_phase}, waiting_for={waiting_for}."
        )
    elif stalled:
        faults.append(
            f"Run stalled before terminal completion. Final state: owner={owner}, phase={phase}, task_phase={task_phase}, waiting_for={waiting_for}."
        )
    elif phase != "DONE":
        faults.append(
            f"Project did not reach DONE. Final state: owner={owner}, phase={phase}, task_phase={task_phase}, waiting_for={waiting_for}, blocked_reason={blocked_reason}."
        )

    faults.extend(collect_plan_faults(project_dir))

    if not (project_dir / architecture_path).exists():
        faults.append(f"Missing required architecture artifact: {architecture_path}.")
        if architect_orphan_drafts:
            faults.append(
                "Architect created draft.md outside runtime terminalization; no runtime state/result exists for: "
                + ", ".join(str(item["draft_file"]) for item in architect_orphan_drafts)
                + "."
            )
        elif (
            waiting_for == "architect"
            and task_phase == "DESIGN"
            and isinstance(architect_worker, dict)
            and str(architect_worker.get("status", "")).strip() == "awaiting_draft"
            and not architect_worker.get("last_error")
        ):
            faults.append(
                "Architect prepare succeeded but no design draft was terminalized; worker state is awaiting_draft with no runtime error."
            )

    missing_outputs = [path for path in REQUIRED_OUTPUTS if not (project_dir / path).exists()]
    if missing_outputs:
        faults.append("Missing required outputs: " + ", ".join(missing_outputs) + ".")
        if (
            waiting_for == "morpheus"
            and task_phase == "IMPLEMENT"
            and isinstance(morpheus_worker, dict)
            and str(morpheus_worker.get("status", "")).strip() == "awaiting_artifacts"
            and not morpheus_worker.get("last_error")
        ):
            faults.append(
                "Morpheus prepare succeeded but no draft artifacts were produced afterward; "
                "worker state is awaiting_artifacts with no runtime error."
            )

    reports = validation_report_paths(project_dir)
    if not reports:
        faults.append("No validation report was produced under management/validation/.")
    else:
        latest = reports[-1]
        report_text = latest.read_text(encoding="utf-8")
        if "PASS" not in report_text:
            faults.append(f"Validation report {latest.relative_to(project_dir)} does not contain PASS.")

    events = load_handoff_events(project_dir)
    if not events:
        faults.append("No handoff ledger was produced at .openclaw/handoffs.jsonl.")
    else:
        for expected_from, expected_to in REQUIRED_HANDOFFS:
            if not any(
                str(event.get("from", "")).strip().lower() == expected_from
                and str(event.get("to", "")).strip().lower() == expected_to
                and str(event.get("event_type", "")).strip() == "handoff_sent"
                for event in events
            ):
                faults.append(f"Handoff ledger never recorded expected transition {expected_from} -> {expected_to}.")

    return faults


def format_report(project_id: str, project_dir: Path, state_text: str, faults: list[str]) -> str:
    phase = parse_state_field(state_text, "phase") or "missing"
    owner = parse_state_field(state_text, "owner") or "missing"
    waiting_for = parse_state_field(state_text, "waiting_for") or "missing"
    task_phase = parse_state_field(state_text, "task_phase") or "missing"
    blocked_reason = parse_state_field(state_text, "blocked_reason") or "none"
    architect_worker = load_latest_worker_state(project_id, "architect")
    morpheus_worker = load_latest_worker_state(project_id, "morpheus")
    architect_drafts = worker_draft_evidence(project_id, "architect")

    lines = [
        "# Fibonacci E2E Report",
        "",
        f"- **project_id**: `{project_id}`",
        f"- **project_dir**: `{project_dir}`",
        f"- **owner**: `{owner}`",
        f"- **phase**: `{phase}`",
        f"- **task_phase**: `{task_phase}`",
        f"- **waiting_for**: `{waiting_for}`",
        f"- **blocked_reason**: `{blocked_reason}`",
        "",
        "## Findings",
        "",
    ]
    if faults:
        lines.extend(f"{index}. {fault}" for index, fault in enumerate(faults, start=1))
    else:
        lines.append("1. No faults detected in the tested scope.")
    if architect_worker:
        lines.extend(
            [
                "",
                "## Latest Architect Worker State",
                "",
                f"- **status**: `{architect_worker.get('status', 'unknown')}`",
                f"- **task_id**: `{architect_worker.get('task_id', 'unknown')}`",
                f"- **output_path**: `{architect_worker.get('output_path', 'missing')}`",
                f"- **state_file**: `{architect_worker.get('state_file', 'missing')}`",
                f"- **last_error**: `{architect_worker.get('last_error')}`",
            ]
        )
    if architect_drafts:
        lines.extend(["", "## Architect Draft Evidence", ""])
        for item in architect_drafts:
            lines.append(
                "- "
                f"`{item['draft_file']}` "
                f"(state={item['state_file_exists']}, result={item['result_file_exists']})"
            )
    if morpheus_worker:
        lines.extend(
            [
                "",
                "## Latest Morpheus Worker State",
                "",
                f"- **status**: `{morpheus_worker.get('status')}`",
                f"- **task_id**: `{morpheus_worker.get('task_id')}`",
                f"- **draft_write_root**: `{morpheus_worker.get('draft_write_root')}`",
                f"- **manifest_write_file**: `{morpheus_worker.get('manifest_write_file')}`",
                f"- **state_file**: `{morpheus_worker.get('state_file')}`",
                f"- **last_error**: `{morpheus_worker.get('last_error')}`",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "AgenticTeam" / "scripts"
    live_bin = Path("/home/alik/workspace/clawspace/bin")
    projects_root = Path("/home/alik/workspace/clawspace/projects/active")

    if not gateway_is_listening():
        report = "# Fibonacci E2E Report\n\n1. OpenClaw gateway is not listening on 127.0.0.1:18789.\n"
        if args.report_file:
            report_path = Path(args.report_file)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
        print(report, end="")
        return 1

    project_output = run(["bash", str(scripts_dir / "new_project.sh"), DEFAULT_TITLE], timeout=120)
    project_id = parse_project_id(project_output)
    project_dir = projects_root / project_id
    project_md_path = project_dir / "PROJECT.md"
    project_md_path.write_text(DEFAULT_SPEC.rstrip() + "\n", encoding="utf-8")

    state_path = project_dir / "PROJECT_STATE.md"
    scaffold_state_text = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
    scaffold_owner = parse_state_field(scaffold_state_text, "owner").lower()
    if scaffold_owner == "neo":
        run(
            [
                "bash",
                str(live_bin / "write_state.sh"),
                project_id,
                "HANDOFF_PENDING",
                "smith",
                "--actor",
                "neo",
                "--expect-owner",
                "neo",
                "--current-agent",
                "neo",
                "--note",
                "Fibonacci E2E canary prepared. Awaiting Smith receipt.",
            ],
            timeout=120,
        )

    handoff_output = run(
        [
            "bash",
            str(live_bin / "handoff.sh"),
            "neo",
            "smith",
            project_id,
            "Read PROJECT.md and create the required deterministic 4-task sequential plan.",
            "HANDOFF",
        ],
        timeout=120,
    )
    envelope = parse_envelope(handoff_output)
    send_session_message("agent:smith:main", envelope)

    handoff_path = project_dir / ".openclaw" / "handoffs.jsonl"
    deadline = time.time() + args.timeout_seconds
    last_snapshot = ""
    last_change_at = time.time()
    timed_out = False
    stalled = False

    while time.time() < deadline:
        if state_path.exists():
            state_text = state_path.read_text(encoding="utf-8")
            phase = parse_state_field(state_text, "phase").upper()
            handoff_count = len(handoff_path.read_text(encoding="utf-8").splitlines()) if handoff_path.exists() else 0
            snapshot = "|".join(
                [
                    parse_state_field(state_text, "owner"),
                    phase,
                    parse_state_field(state_text, "task_phase"),
                    parse_state_field(state_text, "waiting_for"),
                    str(handoff_count),
                ]
            )
            if snapshot != last_snapshot:
                last_snapshot = snapshot
                last_change_at = time.time()
            if phase in TERMINAL_PHASES:
                break
            if time.time() - last_change_at >= args.stall_seconds:
                stalled = True
                break
        time.sleep(args.poll_seconds)
    else:
        timed_out = True

    state_text = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
    faults = collect_faults(project_id, project_dir, state_text, timed_out=timed_out, stalled=stalled)
    report = format_report(project_id, project_dir, state_text, faults)

    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

    print(report, end="")
    return 1 if faults else 0


if __name__ == "__main__":
    raise SystemExit(main())
