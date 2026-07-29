#!/usr/bin/env python3
"""Bind or service automatic Lead metrics capture for one Codex session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from codexteam_tools.lead_tracking import bind_session, stop_from_stdin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind a Lead session or capture its Stop event.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bind = subparsers.add_parser("bind")
    bind.add_argument("--project", required=True)
    bind.add_argument("--task", required=True)
    subparsers.add_parser("stop")
    args = parser.parse_args(argv)
    if args.command == "stop":
        return stop_from_stdin()
    try:
        path = bind_session(args.project, args.task)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"bound": str(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
