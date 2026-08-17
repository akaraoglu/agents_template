#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codexteam_tools.local_mcp import (  # noqa: E402
    LocalMcpClient,
    Mode,
    context_server_spec,
    local_docs_server_spec,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise the bounded local MCP sidecar.")
    parser.add_argument("--projects-root", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--local-docs-manifest", required=True, type=Path)
    parser.add_argument("--interpreter", default=sys.executable, type=Path)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context_spec = context_server_spec(
        args.projects_root,
        args.project,
        interpreter=args.interpreter,
        repository_root=args.repository_root,
        mode=Mode.OPTIONAL,
    )
    docs_spec = local_docs_server_spec(
        args.local_docs_manifest,
        interpreter=args.interpreter,
        repository_root=args.repository_root,
        mode=Mode.OPTIONAL,
    )
    summary: dict[str, object] = {}
    with LocalMcpClient(context_spec) as context, LocalMcpClient(docs_spec) as docs:
        context_available = context.start()
        docs_available = docs.start()
        context_call = context.call("get_active_task", {})
        docs_call = docs.call("search_docs", {"query": "MCP local documentation", "limit": 1})
        summary = {
            "success": context_call.available and docs_call.available,
            "context": {
                "available": context_available.available,
                "catalog_valid": context_available.available,
                "call_succeeded": context_call.available,
                "provenance": asdict(context_call.provenance),
            },
            "local_docs": {
                "available": docs_available.available,
                "catalog_valid": docs_available.available,
                "call_succeeded": docs_call.available,
                "provenance": asdict(docs_call.provenance),
            },
        }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
