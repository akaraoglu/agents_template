from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .paths import ensure_existing_workspace
from .repository_binding import RepositoryBindingError, load_repository_binding

CONTROL_PRODUCT_PATHS = ("src", "tests/unit", "tests/smoke", "tests/integration")
SOURCE_CONTROL_PATHS = (
    ".codexteam",
    "AGENTS.md",
    "management",
    "results",
    "REPOSITORIES.json",
    "BRIEF.md",
    "TASKS.md",
    "CURRENT_TASK.md",
    "IMPLEMENTATION_PLAN.md",
    "OPEN_QUESTIONS.md",
    "PROJECT_STATE.md",
    "RESULT.md",
    "DONE_REPORT.md",
    "DELIVERY.md",
    "BLOCKED_REPORT.md",
)
SOURCE_DISCOVERY_PATH = "discoveries"


def _git_index_control_paths(
    work: Path,
    *,
    allowed_paths: frozenset[str] = frozenset(),
) -> tuple[bool, tuple[str, ...]]:
    pathspecs = tuple(
        relative
        for relative in (*SOURCE_CONTROL_PATHS, SOURCE_DISCOVERY_PATH)
        if relative not in allowed_paths
    )
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--", *pathspecs],
            cwd=work,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False, ()
    if completed.returncode != 0:
        return False, ()
    tracked = tuple(line for line in completed.stdout.splitlines() if line)
    contaminated = tuple(
        relative
        for relative in pathspecs
        if any(path == relative or path.startswith(f"{relative}/") for path in tracked)
    )
    return True, contaminated


def audit_separation(projects_root: str | Path) -> dict[str, Any]:
    root = ensure_existing_workspace(projects_root)
    projects: list[dict[str, Any]] = []
    errors: list[str] = []
    for control in sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink()):
        project_errors: list[str] = []
        for relative in CONTROL_PRODUCT_PATHS:
            path = control / relative
            if path.exists() or path.is_symlink():
                project_errors.append(f"control contains product scaffold: {relative}")
        registry_path = control / "REPOSITORIES.json"
        repositories: list[dict[str, Any]] = []
        if not registry_path.is_file() or registry_path.is_symlink():
            project_errors.append("missing safe REPOSITORIES.json")
        else:
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                project_errors.append(f"invalid REPOSITORIES.json: {exc}")
                registry = {}
            entries = registry.get("repositories") if isinstance(registry, dict) else None
            if not isinstance(entries, list):
                project_errors.append("REPOSITORIES.json repositories must be a list")
            else:
                for entry in entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        project_errors.append("repository entry is invalid")
                        continue
                    work_value = entry.get("work_root")
                    if work_value is None:
                        checkout, relative = entry.get("checkout_root"), entry.get("path")
                        work_value = str(Path(checkout) / relative) if isinstance(checkout, str) and isinstance(relative, str) else None
                    if not isinstance(work_value, str):
                        project_errors.append(f"repository {entry['id']} has no work root")
                        continue
                    work = Path(work_value).expanduser().resolve(strict=False)
                    repo_errors = []
                    central_exception = work == Path("/home/alik/workspace/agent_template/codexteam")
                    git_index_checked = False
                    try:
                        binding = load_repository_binding(control, work, entry["id"])
                    except (OSError, RepositoryBindingError, ValueError) as exc:
                        repo_errors.append(f"invalid repository binding: {exc}")
                        repositories.append({
                            "id": entry["id"],
                            "work_root": str(work),
                            "central_exception": central_exception,
                            "git_index_checked": git_index_checked,
                            "errors": repo_errors,
                        })
                        project_errors.extend(
                            f"{entry['id']}: {error}" for error in repo_errors
                        )
                        continue
                    work = binding.work_root
                    allowed_paths = (
                        frozenset({".codexteam", "AGENTS.md", SOURCE_DISCOVERY_PATH})
                        if central_exception
                        else frozenset()
                    )
                    for relative in SOURCE_CONTROL_PATHS:
                        if relative in allowed_paths:
                            continue
                        path = work / relative
                        if path.exists() or path.is_symlink():
                            repo_errors.append(f"source contains control artifact: {relative}")
                    if (
                        SOURCE_DISCOVERY_PATH not in allowed_paths
                        and (work / SOURCE_DISCOVERY_PATH).exists()
                    ):
                        repo_errors.append(
                            f"source contains control discovery notes: {SOURCE_DISCOVERY_PATH}"
                        )
                    git_index_checked, indexed_paths = _git_index_control_paths(
                        work,
                        allowed_paths=allowed_paths,
                    )
                    if not git_index_checked:
                        repo_errors.append("source Git index could not be inspected")
                    repo_errors.extend(
                        f"source Git index contains control artifact: {relative}"
                        for relative in indexed_paths
                    )
                    repositories.append({
                        "id": entry["id"],
                        "work_root": str(work),
                        "central_exception": central_exception,
                        "git_index_checked": git_index_checked,
                        "errors": repo_errors,
                    })
                    project_errors.extend(f"{entry['id']}: {error}" for error in repo_errors)
        errors.extend(f"{control.name}: {error}" for error in project_errors)
        projects.append({"project": control.name, "errors": project_errors, "repositories": repositories})
    return {
        "schema_version": "1.0",
        "projects_root": str(root),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "projects": projects,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit CodexTeam control/source separation.")
    parser.add_argument("projects_root", nargs="?", default="/home/alik/workspace/codexspace/projects")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = audit_separation(args.projects_root)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Separation audit: {result['status']}")
        for error in result["errors"]:
            print(f"- {error}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
