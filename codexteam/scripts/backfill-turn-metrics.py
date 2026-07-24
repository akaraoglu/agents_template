#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codexteam_tools.turn_metrics import backfill_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or write missing CodexTeam per-turn metrics sidecars."
    )
    parser.add_argument("project", help="Initialized CodexTeam project root")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write sidecars; the default is a read-only preview",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing valid sidecars; requires --write",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        records = backfill_project(
            args.project,
            write=args.write,
            overwrite=args.overwrite,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0
    counts = Counter(record["action"] for record in records)
    mode = "WRITE" if args.write else "PREVIEW"
    print(f"Mode: {mode}")
    print(f"Turns: {len(records)}")
    for action, count in sorted(counts.items()):
        print(f"{action}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
