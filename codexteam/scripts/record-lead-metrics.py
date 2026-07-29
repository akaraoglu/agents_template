#!/usr/bin/env python3
"""CLI wrapper for codexteam_tools.lead_metrics.record_lead_usage().

Records per-task Lead orchestration time and token usage into the project's
``.codexteam/runtime/lead-metrics.json`` file.  All six per-task values must
be supplied explicitly — the script does not discover or infer them.

Usage::

    record-lead-metrics.py \\
        --project /path/to/project \\
        --task T002 \\
        --profile gpt-4.1-mini \\
        --provider openai_cloud \\
        --duration-seconds 234 \\
        --input-tokens 50000 \\
        --cached-input-tokens 40000 \\
        --output-tokens 8000 \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codexteam_tools.lead_metrics import record_lead_usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record Lead orchestration metrics for one task.",
    )
    parser.add_argument("--project", required=True, help="Project root path")
    parser.add_argument("--task", required=True, help='Task ID, e.g. "T002"')
    parser.add_argument("--profile", required=True, help="Model profile string")
    parser.add_argument("--provider", required=True, help="Provider identifier")
    parser.add_argument(
        "--duration-seconds", type=float, required=True, help="Wall-clock seconds (≥ 0)"
    )
    parser.add_argument(
        "--input-tokens", type=int, required=True, help="Input tokens (≥ 0)"
    )
    parser.add_argument(
        "--cached-input-tokens", type=int, required=True, help="Cached input tokens (≥ 0)"
    )
    parser.add_argument(
        "--output-tokens", type=int, required=True, help="Output tokens (≥ 0)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only; do not write the metrics file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    error = record_lead_usage(
        project=args.project,
        task_id=args.task,
        profile=args.profile,
        provider=args.provider,
        duration_seconds=args.duration_seconds,
        input_tokens=args.input_tokens,
        cached_input_tokens=args.cached_input_tokens,
        output_tokens=args.output_tokens,
        dry_run=args.dry_run,
    )

    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
