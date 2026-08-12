from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

from .canary import FIXED_TIME, run_fake_canary, run_live_opencode_canary
from .catalog import load_catalog
from .compiler import compile_pipeline
from pydantic import ValidationError

from .models import AcceptanceCriterion, ActorRef, EvidenceType, WorkItem
from .qualification import run_muse_qualification
from .runtime import RuntimeErrorBase
from .runtime import DEFAULT_OPENCODE_MODEL
from .storage import StorageError


class _InvalidCLI(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _InvalidCLI(message)


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _sample_work_item() -> WorkItem:
    return WorkItem(
        schema_version="2.0",
        kind="work_item",
        work_item_id="cli-compile-preview",
        title="Compile preview",
        objective="Preview the deterministic v2 canary pipeline.",
        acceptance_criteria=(
            AcceptanceCriterion(
                id="preview", statement="The selected pipeline compiles.",
                required_evidence_types=(EvidenceType.TEST_OUTPUT,),
            ),
        ),
        approved_scope=("project/**",),
    )


def _emit(value: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Experimental CodexTeam v2 deterministic canary tools.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("catalog-check", help="validate the complete pinned v2 catalog")
    check.add_argument("--json", action="store_true", dest="command_json", help=argparse.SUPPRESS)
    compile_command = subparsers.add_parser("compile", help="compile a deterministic pipeline preview")
    compile_command.add_argument("--optional", default="", help="comma-separated optional stages: architecture,ux")
    compile_command.add_argument("--json", action="store_true", dest="command_json", help=argparse.SUPPRESS)
    canary = subparsers.add_parser("canary", help="run the fake or live adaptive canary")
    backend = canary.add_mutually_exclusive_group(required=True)
    backend.add_argument("--fake", action="store_true", help="use the deterministic fake adapter")
    backend.add_argument(
        "--live-opencode", action="store_true",
        help="use OpenCode 1.18.16 with the pinned local Muse Glimmer model",
    )
    canary.add_argument(
        "--scenario", choices=(
            "happy", "defect-loop", "malformed", "forbidden-write", "assurance-fail",
            "review-return", "assurance-blocking", "review-blocking", "missing-capability",
            "context-mismatch", "external-workspace",
        ), default="happy"
    )
    canary.add_argument("--workspace", type=Path, help="create the canary in this absent or empty directory")
    canary.add_argument(
        "--model", default=DEFAULT_OPENCODE_MODEL,
        help="OpenCode model; active AgentSpecs require ollama/muse-glimmer:30b",
    )
    canary.add_argument("--timeout-seconds", type=int, default=600, help="maximum seconds per model turn")
    canary.add_argument("--overall-timeout-seconds", type=int, default=3600, help="maximum seconds for all model turns")
    canary.add_argument(
        "--opencode-executable", type=Path,
        default=Path("/home/alik/.opencode/bin/opencode"), help=argparse.SUPPRESS,
    )
    canary.add_argument("--dry-run", action="store_true", help="validate invocation without filesystem mutation")
    canary.add_argument("--json", action="store_true", dest="command_json", help=argparse.SUPPRESS)
    qualification = subparsers.add_parser(
        "qualify-muse", help="run the focused Muse Glimmer qualification gate"
    )
    mode = qualification.add_mutually_exclusive_group()
    mode.add_argument(
        "--direct-only", action="store_true", help="run metadata and direct Ollama checks only"
    )
    mode.add_argument(
        "--opencode", action="store_true", help="also run the three minimal OpenCode sessions"
    )
    qualification.add_argument(
        "--workspace", type=Path, help="use this absent or empty qualification workspace"
    )
    qualification.add_argument(
        "--timeout", type=int, default=600, help="maximum seconds per model request or turn"
    )
    qualification.add_argument(
        "--dry-run", action="store_true", help="run model-free preflight and plan model checks"
    )
    qualification.add_argument("--json", action="store_true", dest="command_json", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _InvalidCLI as exc:
        print(json.dumps({"error": str(exc), "status": "invalid_input"}, sort_keys=True), file=sys.stderr)
        return 2
    as_json = bool(args.json or getattr(args, "command_json", False))
    try:
        if args.command == "qualify-muse":
            result = run_muse_qualification(
                workspace=args.workspace,
                include_opencode=args.opencode,
                dry_run=args.dry_run,
                timeout_seconds=args.timeout,
            )
            _emit(result.as_dict(), as_json=as_json)
            return 0 if result.verdict in {"QUALIFIED", "DRY_RUN"} else 1
        catalog = load_catalog(_root() / "v2")
        if args.command == "catalog-check":
            lock = catalog.catalog_lock()
            _emit({"catalog_digest": lock["catalog_digest"], "definitions": len(lock["definitions"]), "status": "ok"}, as_json=as_json)
            return 0
        if args.command == "compile":
            selected = tuple(item for item in args.optional.split(",") if item)
            compiled = compile_pipeline(
                catalog, _sample_work_item(), selected,
                ActorRef(actor_id="cli-lead", kind="project_lead"), FIXED_TIME,
            )
            _emit(
                {
                    "plan_id": compiled.plan.plan_id,
                    "selection_trace": list(compiled.selection_trace),
                    "stages": [stage.stage for stage in compiled.plan.stages],
                },
                as_json=as_json,
            )
            return 0
        if args.live_opencode:
            if args.scenario != "happy":
                raise ValueError("--scenario is supported only with --fake")
            result = run_live_opencode_canary(
                model=args.model,
                workspace=args.workspace,
                dry_run=args.dry_run,
                timeout_seconds=args.timeout_seconds,
                overall_timeout_seconds=args.overall_timeout_seconds,
                executable=args.opencode_executable,
            )
        else:
            result = run_fake_canary(
                scenario=args.scenario, workspace=args.workspace, dry_run=args.dry_run
            )
        _emit(result.as_dict(), as_json=as_json)
        return 0
    except ValidationError as exc:
        _emit({"error": str(exc), "status": "invalid_input"}, as_json=True)
        return 2
    except ValueError as exc:
        status = "invalid_input" if args.command == "compile" else "failed"
        _emit({"error": str(exc), "status": status}, as_json=True)
        return 2 if status == "invalid_input" else 1
    except (RuntimeErrorBase, StorageError, RuntimeError, OSError) as exc:
        _emit({"error": str(exc), "status": "failed"}, as_json=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
