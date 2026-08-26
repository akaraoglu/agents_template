from __future__ import annotations

import argparse
from pathlib import Path

from .files import atomic_write_text
from .native_agents import GENERATED_MARKER, expected_native_agents
from .paths import ensure_existing_workspace
from .roles import DEFAULT_ROLES_ROOT, RolePolicyError, load_all_role_policies

MANAGED_MARKER = "# Managed by CodexTeam role policy. Do not edit."
DEFAULT_SKILLS_ROOT = Path(__file__).resolve().parents[2] / ".agents" / "skills"
PROJECT_SKILLS = (
    "debugging.md",
    "delivery.md",
    "development-testing.md",
    "document-editing.md",
    "architecture-design.md",
    "codexteam-self-improvement.md",
    "feature-planning.md",
    "git-steward.md",
    "implementation.md",
    "integration-testing.md",
    "project-doc-map.md",
    "project-lead.md",
    "sdd-workflow.md",
    "subagent-orchestration.md",
    "task-breakdown.md",
    "team-context-mcp.md",
    "testing.md",
    "ux-ui-design.md",
    "verification.md",
)
GUIDANCE_README = """# Managed CodexTeam Role Guidance

These files are discoverable project references generated from the CodexTeam role policy manifests.

- `roles/` describes each worker's role instructions, defaults, guidance bundle, change boundary, and evidence types.
- `native-agents/` projects the same role identity into optional Codex native custom-agent configuration.
- The launcher loads the toolkit role manifest and selected skills at the first draft turn, then pins the role snapshot, skill contents, and both digests under `.codexteam/runtime/` for every continuation.
- Project `AGENTS.md` contains common project rules. It does not replace the selected worker role.

Refresh these managed references with `scripts/sync-project-guidance.py`. Do not edit them in place.
"""


def expected_project_guidance(
    *,
    roles_root: str | Path = DEFAULT_ROLES_ROOT,
    skills_root: str | Path = DEFAULT_SKILLS_ROOT,
) -> dict[str, str]:
    policies = load_all_role_policies(roles_root=roles_root)
    files = {
        f".codexteam/roles/{policy.role}.toml": (
            MANAGED_MARKER
            + "\n"
            + policy.source_path.read_text(encoding="utf-8").lstrip()
        )
        for policy in policies
    }
    files.update(
        {
            f".codexteam/native-agents/{name}": content
            for name, content in expected_native_agents(roles_root=roles_root).items()
        }
    )
    files[".codexteam/README.md"] = GUIDANCE_README
    skill_root = Path(skills_root).expanduser().resolve(strict=True)
    for skill_name in PROJECT_SKILLS:
        source = skill_root / skill_name
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"required project skill is missing or unsafe: {source}")
        files[f".codexteam/skills/{skill_name}"] = source.read_text(encoding="utf-8")
    return files


def sync_project_guidance(
    project: str | Path,
    *,
    roles_root: str | Path = DEFAULT_ROLES_ROOT,
    skills_root: str | Path = DEFAULT_SKILLS_ROOT,
    apply: bool = False,
) -> tuple[str, ...]:
    project_root = ensure_existing_workspace(project)
    if not (project_root / "PROJECT.md").is_file():
        raise ValueError(f"not an initialized CodexTeam project: {project_root}")
    changes: list[str] = []
    for relative, content in expected_project_guidance(
        roles_root=roles_root,
        skills_root=skills_root,
    ).items():
        target = project_root / relative
        if target.is_symlink():
            raise RolePolicyError(f"refusing to replace symlink: {target}")
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing == content:
                continue
            if not _managed_content(relative, existing):
                raise RolePolicyError(f"refusing to replace unmanaged project guidance: {target}")
            action = "update"
        else:
            action = "create"
        changes.append(f"{action} {relative}")
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, content)
    return tuple(changes)


def _managed_content(relative: str, content: str) -> bool:
    if relative == ".codexteam/README.md":
        return content == GUIDANCE_README or content.startswith("# Managed CodexTeam Role Guidance")
    if relative.startswith(".codexteam/skills/"):
        return True
    return content.startswith(MANAGED_MARKER) or content.startswith(GENERATED_MARKER)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or refresh managed role guidance in an existing CodexTeam project."
    )
    parser.add_argument("project")
    parser.add_argument("--roles-root", default=str(DEFAULT_ROLES_ROOT))
    parser.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true", help="Exit 1 when managed guidance is stale")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        changes = sync_project_guidance(
            args.project,
            roles_root=args.roles_root,
            skills_root=args.skills_root,
            apply=args.apply,
        )
    except (FileNotFoundError, OSError, RolePolicyError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    for change in changes:
        print(change)
    if not changes:
        print(f"Current: {Path(args.project).expanduser().resolve(strict=False)}")
    elif not args.apply:
        print("Preview only; pass --apply to write changes.")
    if args.check and changes:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
