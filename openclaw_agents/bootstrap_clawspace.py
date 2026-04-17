"""Bootstrap and migrate the Option A runtime root under ~/workspace/clawspace."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from openclaw_agents.runtime_paths import RuntimePaths


def _copy_file(src: Path, dst: Path, *, overwrite: bool) -> bool:
    if not src.exists():
        return False
    if dst.exists() and not overwrite:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_tree(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return True


def bootstrap_clawspace(
    *,
    runtime_root: str | Path | None = None,
    overwrite_credentials: bool = False,
) -> dict[str, Any]:
    package_root = Path(__file__).resolve().parent
    repo_root = package_root.parent
    paths = RuntimePaths.from_root(runtime_root).ensure()

    legacy_data_root = package_root / "data"
    legacy_projects_root = package_root / "workspaces"
    credentials_source = repo_root / "software_team_setup" / "zulip_bots_email_and_keys.txt"
    credentials_target = paths.config_root / "zulip_bots_email_and_keys.txt"

    copied_state_files: list[str] = []
    copied_projects: list[str] = []

    for filename in (
        "state_store.json",
        "projection_events.json",
        "message_mappings.json",
        "event_dedupe.json",
        "conversation_memory.json",
        "working_memory.json",
    ):
        src = legacy_data_root / filename
        dst = paths.state_root / filename
        if _copy_file(src, dst, overwrite=False):
            copied_state_files.append(filename)

    copied_artifacts = _copy_tree(legacy_data_root / "artifacts", paths.artifacts_root)

    if legacy_projects_root.exists():
        for child in sorted(legacy_projects_root.iterdir()):
            if child.is_dir() and _copy_tree(child, paths.projects_root / child.name):
                copied_projects.append(child.name)

    copied_credentials = _copy_file(
        credentials_source,
        credentials_target,
        overwrite=overwrite_credentials,
    )

    return {
        "runtime_root": str(paths.root),
        "system_root": str(paths.system_root),
        "projects_root": str(paths.projects_root),
        "copied_state_files": copied_state_files,
        "copied_artifacts": copied_artifacts,
        "copied_projects": copied_projects,
        "copied_credentials": copied_credentials,
        "credentials_target": str(credentials_target),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap the OpenClaw runtime root under ~/workspace/clawspace")
    parser.add_argument("--runtime-root", help="Override the runtime root (defaults to OPENCLAW_ROOT or ~/workspace/clawspace)")
    parser.add_argument(
        "--overwrite-credentials",
        action="store_true",
        help="Replace the target credential bundle if it already exists",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = bootstrap_clawspace(
        runtime_root=args.runtime_root,
        overwrite_credentials=args.overwrite_credentials,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
