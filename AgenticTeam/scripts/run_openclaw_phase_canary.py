#!/usr/bin/env python3
"""Run one OpenClaw phase canary."""

from __future__ import annotations

import argparse
from pathlib import Path

from canaries.common import CanaryError, render_markdown_report, write_report
from canaries.phase_canaries import CANARY_RUNNERS, run_phase_canary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=sorted(CANARY_RUNNERS))
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--stall-seconds", type=int)
    parser.add_argument("--report-file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = run_phase_canary(args.phase, timeout_seconds=args.timeout_seconds, stall_seconds=args.stall_seconds)
    except Exception as exc:
        summary = {
            "schema_version": 1,
            "canary": args.phase,
            "status": "FAIL",
            "project_id": "unknown",
            "project_dir": "unknown",
            "contract": {
                "starting_state": "unknown",
                "allowed_agents": [],
                "expected_files": [],
                "expected_state_fields": {},
                "expected_handoffs": [],
                "expected_terminal_state": "unknown",
                "failure_timeout_seconds": args.timeout_seconds or 0,
                "stall_timeout_seconds": args.stall_seconds or 0,
            },
            "checked_invariants": [
                {
                    "name": "runner:exception",
                    "passed": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ],
            "first_failed_invariant": {
                "name": "runner:exception",
                "passed": False,
                "detail": f"{type(exc).__name__}: {exc}",
            },
            "final_state": {},
            "latest_handoff_event": None,
            "latest_worker_state": None,
            "sync_drift": "unknown",
            "session_freshness": "unknown",
            "terminal_state": "error",
            "suggested_fault_layer": "unknown",
            "first_failed_boundary": "runner exception",
            "preflight": {},
            "delivery_evidence": None,
            "session_excerpt": "",
        }
    write_report(summary, args.report_file)
    print(render_markdown_report(summary), end="")
    return 0 if summary["status"] in {"PASS", "PASS_WITH_WARNINGS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
