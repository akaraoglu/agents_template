from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import AGENT_ROLES
from .execution_registry import (
    ExecutionRegistryError,
    disabled_execution_reason,
    execution_backend_enabled,
    host_availability,
    load_execution_registry,
    require_execution_backend_enabled,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect curated CodexTeam execution support.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("backends", "models", "profiles"):
        child = subparsers.add_parser(name)
        child.add_argument("--backend")
        child.add_argument("--json", action="store_true")
    profile = subparsers.add_parser("profile")
    profile.add_argument("--backend", required=True)
    profile.add_argument("--profile", required=True)
    profile.add_argument("--json", action="store_true")
    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("--backend", required=True)
    resolve.add_argument("--profile", required=True)
    resolve.add_argument("--role", required=True)
    resolve.add_argument("--reasoning", required=True)
    resolve.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = load_execution_registry()
        if args.command == "backends":
            payload = [
                {
                    **item,
                    "execution_enabled": execution_backend_enabled(item["backend_id"]),
                    "disabled_reason": disabled_execution_reason(item["backend_id"]),
                }
                for item in registry.backends.values()
            ]
        elif args.command == "models":
            profiles = registry.profiles_for_backend(args.backend) if args.backend else registry.profiles.values()
            model_ids = {item["model_id"] for item in profiles}
            payload = [registry.models[item] for item in sorted(model_ids)]
        elif args.command == "profiles":
            profiles = registry.profiles_for_backend(args.backend) if args.backend else tuple(registry.profiles.values())
            payload = [
                {
                    **item,
                    "canonical_profile": f"{item['backend_id']}/{item['profile_id']}",
                    "supported": execution_backend_enabled(item["backend_id"]),
                    "execution_enabled": execution_backend_enabled(item["backend_id"]),
                    **(
                        host_availability(
                            registry,
                            item["backend_id"],
                            item["profile_id"],
                            codex_home=Path.home() / ".codex",
                        )
                        if execution_backend_enabled(item["backend_id"])
                        else {
                            "host_available": False,
                            "reason_unavailable": disabled_execution_reason(item["backend_id"]),
                        }
                    ),
                }
                for item in profiles
            ]
        else:
            if args.command == "resolve" and args.role not in AGENT_ROLES:
                raise ExecutionRegistryError(f"unsupported agent role: {args.role}")
            if args.command == "resolve":
                require_execution_backend_enabled(args.backend)
            reasoning = args.reasoning if args.command == "resolve" else registry.profiles[(args.backend, args.profile)]["supported_reasoning_requests"][0]
            resolved = registry.resolve(args.backend, args.profile, reasoning)
            enabled = execution_backend_enabled(args.backend)
            payload = {
                **resolved.reference(runtime_version=None, backend_material_digest="unavailable"),
                "supported": enabled,
                "execution_enabled": enabled,
                **(
                    host_availability(registry, args.backend, args.profile)
                    if enabled
                    else {
                        "host_available": False,
                        "reason_unavailable": disabled_execution_reason(args.backend),
                    }
                ),
            }
            if args.command == "resolve":
                payload["role"] = args.role
    except (ExecutionRegistryError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
