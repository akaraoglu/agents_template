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
    create_lead_checkpoint,
    stop_from_stdin,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind a Lead session, create a checkpoint, clear delivered bindings, or capture Stop."
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
    checkpoint = subparsers.add_parser("checkpoint")
    checkpoint.add_argument("--project", required=True)
    subparsers.add_parser("stop")
    args = parser.parse_args(argv)
    if args.command == "stop":
        return stop_from_stdin()
    try:
        if args.command == "clear-delivered":
            removed = clear_delivered_project_bindings(args.project)
            print(json.dumps({"removed": [str(path) for path in removed]}))
            return 0
        if args.command == "checkpoint":
            path, checkpoint_data = create_lead_checkpoint(args.project)
            active = checkpoint_data["project_state"].get("Active Task")
            print(json.dumps({
                "checkpoint": str(path),
                "active_task": active,
                "resume_prompt": (
                    f"Continue CodexTeam project {checkpoint_data['project_root']} from "
                    f"{path}. Read only its canonical_refs, then the active handoff."
                ),
            }))
            return 0
        path = bind_session(args.project, args.task, reset_existing=args.reset)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"bound": str(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
