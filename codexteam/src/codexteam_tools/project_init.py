from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .files import atomic_write_text
from .paths import contained_path, normalize_task_id, projects_root, slugify_project_name, validate_identifier
from .project_guidance import expected_project_guidance

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_ROOT = CODEXTEAM_ROOT / "templates" / "project"
SKILLS_ROOT = CODEXTEAM_ROOT / ".agents" / "skills"
PROJECT_SKILLS = (
    "debugging.md",
    "delivery.md",
    "development-testing.md",
    "document-editing.md",
    "architecture-design.md",
    "git-steward.md",
    "implementation.md",
    "integration-testing.md",
    "project-doc-map.md",
    "project-lead.md",
    "sdd-workflow.md",
    "subagent-orchestration.md",
    "task-breakdown.md",
    "testing.md",
    "ux-ui-design.md",
    "verification.md",
)
TASK_DEFINITIONS = {
    "T001": ("Finalize requirements and project skeleton", "project-lead-01"),
    "T002": ("Design the code and project architecture", "architect-01"),
    "T003": ("Implement the approved thin slice", "developer-01"),
    "T004": ("Engineer and run the integration/CI gate", "test-engineer-01"),
    "T005": ("Review evidence and architecture conformance", "reviewer-01"),
    "T006": ("Reconcile documentation with verified delivery evidence", "documenter-01"),
}
DEFAULT_TASKS = ("T001", "T002", "T003", "T004", "T005")
OPTIONAL_TASK_HANDOFFS = {
    "T006": """# Task T006: Reconcile documentation with verified delivery evidence

## Objective

Make project documentation agree with the implementation and independently verified evidence.

## Responsible AI

`documenter-01` — documenter role; default `qwen36-27b` profile.

## Context

Read `PROJECT.md`, `RESULT.md`, accepted result files, verification artifacts, and `.codexteam/skills/document-editing.md`.

## Scope

Operator-facing documentation and delivery records only. Do not change implementation behavior or invent evidence.

## Allowed Paths

Project Markdown files, delivery documentation, and documentation-focused tests when explicitly required.

## Required Outputs

Documentation that uses accurate lifecycle language and cites the verified commands and artifacts.

## Verification

Compare every delivery claim with the accepted result and independent verification evidence.

## Done Criteria

Documentation is internally consistent and contains no unsupported completion or verification claim.

## Stop Conditions

Stop if required evidence is missing or authoritative project documents conflict.

## Reporting

Return a documentation draft first. The Project Lead owns acceptance and canonical state closure.
""",
}


@dataclass(frozen=True)
class InitializationPlan:
    project_id: str
    project_dir: Path
    files: tuple[str, ...]
    tasks: tuple[str, ...]
    initialize_git: bool


def initialize_project(
    name: str,
    goal: str,
    *,
    root: str | Path | None = None,
    project_id: str | None = None,
    tasks: tuple[str, ...] = DEFAULT_TASKS,
    template_root: str | Path = DEFAULT_TEMPLATE_ROOT,
    dry_run: bool = False,
    initialize_git: bool = True,
    now: datetime | None = None,
) -> InitializationPlan:
    clean_goal = goal.strip()
    if not clean_goal:
        raise ValueError("project goal cannot be empty")

    normalized_tasks = _normalize_tasks(tasks)
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    identifier = project_id or f"{slugify_project_name(name)}-{timestamp}"
    identifier = validate_identifier(identifier, label="project ID")
    canonical_root = projects_root(root)
    destination = contained_path(canonical_root, identifier, label="project directory")
    template = Path(template_root).expanduser().resolve(strict=True)
    if not template.is_dir():
        raise ValueError(f"template root is not a directory: {template}")
    if destination.exists():
        raise FileExistsError(f"project already exists: {destination}")

    replacements = {
        "{{PROJECT_NAME}}": name.strip(),
        "{{PROJECT_ID}}": identifier,
        "{{PROJECT_GOAL}}": clean_goal,
        "{{PROJECT_ROOT}}": str(destination),
        "{{CREATED_AT}}": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "{{TASK_ROWS}}": _task_rows(normalized_tasks),
    }

    rendered: dict[str, str] = {}
    for source in sorted(template.rglob("*")):
        if source.is_symlink():
            raise ValueError(f"template cannot contain symlinks: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(template).as_posix()
        if relative.startswith("management/tasks/") and Path(relative).stem not in normalized_tasks:
            continue
        content = source.read_text(encoding="utf-8")
        for token, value in replacements.items():
            content = content.replace(token, value)
        unresolved = sorted(token for token in replacements if token in content)
        if unresolved:
            raise ValueError(f"unresolved template tokens in {source}: {', '.join(unresolved)}")
        rendered[relative] = content

    for skill_name in PROJECT_SKILLS:
        source = SKILLS_ROOT / skill_name
        if not source.is_file():
            raise FileNotFoundError(f"required project skill is missing: {source}")
        rendered[f".codexteam/skills/{skill_name}"] = source.read_text(encoding="utf-8")

    rendered.update(expected_project_guidance())

    for task_id in normalized_tasks:
        optional_handoff = OPTIONAL_TASK_HANDOFFS.get(task_id)
        if optional_handoff is not None:
            rendered.setdefault(f"management/tasks/{task_id}.md", optional_handoff)

    active_task = normalized_tasks[0]
    active_description, _ = TASK_DEFINITIONS[active_task]
    rendered["CURRENT_TASK.md"] = _update_bullets(
        rendered["CURRENT_TASK.md"],
        {
            "Task ID": active_task,
            "Status": "In Progress",
            "Objective": active_description + ".",
            "Handoff": f"`management/tasks/{active_task}.md`",
            "Next Action": "Read the handoff and satisfy its completion criteria.",
        },
    )
    rendered["PROJECT_STATE.md"] = _update_bullets(
        rendered["PROJECT_STATE.md"],
        {
            "Active Task": active_task,
            "Next Action": f"Execute {active_task}: {active_description}.",
        },
    )

    for directory in (
        "src",
        "docs/architecture",
        "tests/unit",
        "tests/smoke",
        "tests/integration",
        "results",
    ):
        rendered[f"{directory}/.gitkeep"] = ""

    plan = InitializationPlan(
        project_id=identifier,
        project_dir=destination,
        files=tuple(sorted(rendered)),
        tasks=normalized_tasks,
        initialize_git=initialize_git,
    )
    if dry_run:
        return plan

    destination.mkdir(parents=True, exist_ok=False)
    for relative, content in rendered.items():
        atomic_write_text(contained_path(destination, relative, label="template output"), content)
    if initialize_git:
        _initialize_git_repository(destination)
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a complete CodexTeam project workspace.")
    parser.add_argument("name", help="Human-readable project name")
    parser.add_argument("--goal", required=True, help="Concrete project goal")
    parser.add_argument("--project-id", help="Stable project directory ID; timestamped slug by default")
    parser.add_argument("--projects-root", help="Override CODEXTEAM_PROJECTS_ROOT")
    parser.add_argument("--tasks", default=",".join(DEFAULT_TASKS), help="Comma-separated canonical task IDs")
    parser.add_argument("--template-root", default=str(DEFAULT_TEMPLATE_ROOT), help="Project template directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the file plan without writing")
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Do not initialize the new project as a standalone local Git repository",
    )
    parser.add_argument("--json", action="store_true", help="Print the initialization plan as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = initialize_project(
            args.name,
            args.goal,
            root=args.projects_root,
            project_id=args.project_id,
            tasks=tuple(item.strip() for item in args.tasks.split(",") if item.strip()),
            template_root=args.template_root,
            dry_run=args.dry_run,
            initialize_git=not args.no_git,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    payload = {
        "dry_run": args.dry_run,
        "project_id": plan.project_id,
        "project_dir": str(plan.project_dir),
        "tasks": list(plan.tasks),
        "files": list(plan.files),
        "initialize_git": plan.initialize_git,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        action = "Would create" if args.dry_run else "Created"
        print(f"{action}: {plan.project_dir}")
        print(f"Tasks: {', '.join(plan.tasks)}")
        print(f"Files: {len(plan.files)}")
        print(f"Standalone Git repository: {'yes' if plan.initialize_git else 'no'}")
    return 0


def _normalize_tasks(tasks: tuple[str, ...]) -> tuple[str, ...]:
    if not tasks:
        raise ValueError("at least one task is required")
    normalized = tuple(normalize_task_id(task) for task in tasks)
    if len(set(normalized)) != len(normalized):
        raise ValueError("task IDs must be unique")
    unsupported = sorted(set(normalized) - TASK_DEFINITIONS.keys())
    if unsupported:
        raise ValueError(f"unsupported task IDs for template v1: {', '.join(unsupported)}")
    return normalized


def _task_rows(tasks: tuple[str, ...]) -> str:
    rows = []
    for index, task_id in enumerate(tasks):
        description, owner = TASK_DEFINITIONS[task_id]
        status = "In Progress" if index == 0 else "Planned"
        rows.append(f"| {task_id} | {description} | {status} | {owner} | Not run | None |")
    return "\n".join(rows)


def _update_bullets(text: str, values: dict[str, str]) -> str:
    lines = text.splitlines()
    found: set[str] = set()
    for index, line in enumerate(lines):
        for key, value in values.items():
            if line.startswith(f"- {key}:"):
                lines[index] = f"- {key}: {value}"
                found.add(key)
                break
    missing = [key for key in values if key not in found]
    if missing:
        raise ValueError(
            "project template is missing required state fields: " + ", ".join(missing)
        )
    return "\n".join(lines).rstrip() + "\n"


def _initialize_git_repository(project: Path) -> None:
    executable = shutil.which("git")
    if executable is None:
        raise FileNotFoundError("git executable is required unless --no-git is used")
    completed = subprocess.run(
        [executable, "init", "--initial-branch", "main", str(project)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise OSError(f"failed to initialize standalone Git repository: {detail}")
    top = subprocess.run(
        [executable, "-C", str(project), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if top.returncode != 0 or Path(top.stdout.strip()).resolve(strict=True) != project.resolve(strict=True):
        raise OSError("initialized Git repository root does not match the project root")


if __name__ == "__main__":
    raise SystemExit(main())
