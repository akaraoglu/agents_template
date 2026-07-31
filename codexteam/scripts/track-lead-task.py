#!/usr/bin/env python3
"""Bind or service automatic Lead metrics capture for one Codex session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from codexteam_tools.lead_tracking import (
    bind_session,
    clear_delivered_project_bindings,
    stop_from_stdin,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind a Lead session, clear delivered bindings, or capture Stop."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    bind = subparsers.add_parser("bind")
    bind.add_argument("--project", required=True)
    bind.add_argument("--task", required=True)
    bind.add_argument(
        "--reset",
        action="store_true",
        help="Discard an existing stale binding instead of checkpointing it",
    )
    clear = subparsers.add_parser("clear-delivered")
    clear.add_argument("--project", required=True)
    subparsers.add_parser("stop")
    args = parser.parse_args(argv)
    if args.command == "stop":
        return stop_from_stdin()
    try:
        if args.command == "clear-delivered":
            removed = clear_delivered_project_bindings(args.project)
            print(json.dumps({"removed": [str(path) for path in removed]}))
            return 0
        path = bind_session(args.project, args.task, reset_existing=args.reset)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"bound": str(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
