#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def contains_template_placeholder(value: str) -> bool:
    return "YOUR_" in value


def resolve_path(base_dir: pathlib.Path, value: str) -> pathlib.Path:
    candidate = pathlib.Path(value)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def validate_project_workspace(path: pathlib.Path) -> None:
    if contains_template_placeholder(str(path)):
        raise RuntimeError(f"Replace template placeholders in workspace path: {path}")
    if not path.exists():
        raise RuntimeError(f"Project workspace does not exist: {path}")
    if not (path / "PROJECT.md").exists():
        raise RuntimeError(f"Missing PROJECT.md in project workspace: {path / 'PROJECT.md'}")


def load_registry(path: pathlib.Path) -> dict[str, Any]:
    payload = load_json(path)
    projects = payload.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise RuntimeError("Registry must define a non-empty 'projects' mapping.")

    normalized: dict[str, dict[str, Any]] = {}
    for slug, entry in projects.items():
        if contains_template_placeholder(slug):
            raise RuntimeError(f"Replace template placeholders in project slug: {slug}")
        if not isinstance(entry, dict):
            raise RuntimeError(f"Registry entry for {slug} must be an object.")
        workspace_value = entry.get("workspace")
        if not workspace_value:
            raise RuntimeError(f"Registry entry for {slug} is missing 'workspace'.")
        workspace = resolve_path(path.parent, workspace_value)
        normalized[slug] = {
            "slug": slug,
            "display_name": entry.get("display_name") or slug,
            "description": entry.get("description", ""),
            "workspace": workspace,
        }

    default_project = payload.get("default_project")
    if default_project is not None and default_project not in normalized:
        raise RuntimeError(f"Default project '{default_project}' is not present in the registry.")

    return {
        "default_project": default_project,
        "projects": normalized,
    }


def command_check(registry: dict[str, Any]) -> int:
    for slug, entry in registry["projects"].items():
        validate_project_workspace(entry["workspace"])
        print(f"OK: {slug} -> {entry['workspace']}")
    print(f"Default project: {registry['default_project']}")
    print("Registry check passed.")
    return 0


def command_list(registry: dict[str, Any]) -> int:
    default_project = registry["default_project"]
    for slug in sorted(registry["projects"]):
        entry = registry["projects"][slug]
        suffix = " (default)" if slug == default_project else ""
        description = f" - {entry['description']}" if entry["description"] else ""
        print(f"{slug}{suffix}: {entry['workspace']}{description}")
    return 0


def command_show(registry: dict[str, Any], slug: str) -> int:
    entry = registry["projects"].get(slug)
    if entry is None:
        raise RuntimeError(f"Unknown project slug: {slug}")
    print(f"slug: {slug}")
    print(f"display_name: {entry['display_name']}")
    print(f"workspace: {entry['workspace']}")
    print(f"description: {entry['description']}")
    print(f"default: {registry['default_project'] == slug}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and inspect a shared OpenClaw project registry")
    parser.add_argument("--registry", required=True, help="Path to the project registry JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Validate registry structure and project workspaces")
    subparsers.add_parser("list", help="List registered projects")

    show_parser = subparsers.add_parser("show", help="Show one project entry")
    show_parser.add_argument("slug", help="Project slug")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry_path = pathlib.Path(args.registry).resolve()
    if not registry_path.exists():
        raise RuntimeError(f"Registry file does not exist: {registry_path}")
    registry = load_registry(registry_path)

    if args.command == "check":
        return command_check(registry)
    if args.command == "list":
        return command_list(registry)
    if args.command == "show":
        return command_show(registry, args.slug)
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
