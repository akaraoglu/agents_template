from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import RESULT_STATUSES, ResultValidationError, validate_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a CodexTeam result contract.")
    parser.add_argument("result", type=Path, help="Result JSON path")
    parser.add_argument("--task", help="Expected task ID")
    parser.add_argument("--team", help="Expected team ID")
    parser.add_argument("--attempt", help="Expected attempt ID")
    parser.add_argument("--role", help="Expected agent role")
    parser.add_argument("--expected-status", choices=tuple(sorted(RESULT_STATUSES)))
    parser.add_argument("--json", action="store_true", help="Print the validated result")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with args.result.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"ERROR: result file not found: {args.result}")
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: invalid result file: {exc}")
        return 1

    try:
        validate_result(data)
    except ResultValidationError as exc:
        print(f"INVALID: {args.result}")
        for error in exc.errors:
            print(f"- {error}")
        return 1

    try:
        validate_result(
            data,
            expected_task=args.task,
            expected_status=args.expected_status,
            expected_team=args.team,
            expected_attempt=args.attempt,
            expected_role=args.role,
        )
    except ResultValidationError as exc:
        print(f"MISMATCH: {args.result}")
        for error in exc.errors:
            print(f"- {error}")
        return 2

    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"Valid: {args.result}")
        print(f"Task: {data['task_id']}; status: {data['status']}; attempt: {data['attempt_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
