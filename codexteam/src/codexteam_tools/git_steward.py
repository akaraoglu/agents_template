from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import atomic_write_json, atomic_write_text
from .paths import contained_path, ensure_existing_workspace, normalize_task_id, safe_relative_path, validate_identifier
from .test_gates import GateConfigError, load_gate_config, run_gate, validate_current_gate_record

HEX_OBJECT = re.compile(r"[a-f0-9]{40,64}")
PROHIBITED_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
PROHIBITED_NAMES = {".env", "auth.json", "credentials.json", "id_rsa", "id_ed25519"}
PROHIBITED_SUFFIXES = {".bak", ".key", ".orig", ".pem", ".pyc", ".pyo", ".rej", ".swp", ".tmp"}
ARCHITECTURE_COMMIT_PATTERNS = (
    "ARCHITECTURE.md",
    "DECISIONS.md",
    "docs/architecture/**",
    "docs/decisions/**",
    "results/**",
)


class GitStewardError(ValueError):
    pass


def inspect_repository(
    project: str | Path,
    *,
    boundary_id: str,
    task_ids: tuple[str, ...],
    verification_kind: str = "integration",
    architecture_evidence: str | None = None,
) -> dict[str, Any]:
    root = exact_git_root(project)
    boundary = validate_identifier(boundary_id, label="boundary ID")
    tasks = tuple(normalize_task_id(task) for task in task_ids)
    if not tasks:
        raise GitStewardError("at least one task ID is required")
    branch = _branch(root)
    head = _head(root)
    staged = _name_list(_git(root, "diff", "--cached", "--name-only", "-z", allow_failure=True).stdout)
    tracked = set(_name_list(_git(root, "diff", "--name-only", "-z", allow_failure=True).stdout))
    untracked = set(_name_list(_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout))
    changed = tuple(sorted(tracked | untracked | set(staged)))
    unsafe = tuple(path for path in changed if _unsafe_reason(path) is not None)
    verification = _verification(root, verification_kind, architecture_evidence)
    return {
        "schema_version": "1.0",
        "boundary_id": boundary,
        "project_root": str(root),
        "branch": branch,
        "expected_head": head,
        "task_ids": list(tasks),
        "changed_paths": list(changed),
        "staged_paths": list(staged),
        "unsafe_paths": list(unsafe),
        "verification": verification,
    }


def load_commit_plan(project: str | Path, plan_path: str | Path) -> dict[str, Any]:
    root = exact_git_root(project)
    candidate = Path(plan_path).expanduser().resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GitStewardError("commit plan must be inside the project root") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise GitStewardError(f"commit plan is missing or unsafe: {candidate}")
    try:
        plan = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GitStewardError(f"invalid commit plan JSON: {exc}") from exc
    validate_commit_plan(plan, root)
    return plan


def validate_commit_plan(plan: Any, project: Path) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise GitStewardError("commit plan must be a JSON object")
    required = {
        "schema_version", "boundary_id", "project_root", "branch", "expected_head",
        "task_ids", "paths", "excluded_paths", "verification", "commit_subject",
        "commit_body", "pr_title", "pr_summary", "warnings",
    }
    optional = {"untrack_paths"}
    unknown = sorted(set(plan) - required - optional)
    missing = sorted(required - set(plan))
    errors: list[str] = []
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if plan.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    try:
        validate_identifier(plan.get("boundary_id", ""), label="boundary ID")
    except (AttributeError, ValueError) as exc:
        errors.append(str(exc))
    if plan.get("project_root") != str(project):
        errors.append("project_root does not match the exact Git root")
    branch = plan.get("branch")
    if not isinstance(branch, str) or not branch or len(branch) > 255:
        errors.append("branch must be a non-empty string of at most 255 characters")
    elif _git(project, "check-ref-format", "--branch", branch, allow_failure=True).returncode != 0:
        errors.append("branch is not a valid Git branch name")
    head = plan.get("expected_head")
    if head is not None and (not isinstance(head, str) or not HEX_OBJECT.fullmatch(head)):
        errors.append("expected_head must be null or a full lowercase Git object ID")
    tasks = plan.get("task_ids")
    if not isinstance(tasks, list) or not tasks:
        errors.append("task_ids must be a non-empty list")
    else:
        try:
            normalized = [normalize_task_id(item) for item in tasks]
            if normalized != tasks or len(tasks) != len(set(tasks)):
                errors.append("task_ids must be unique canonical task IDs")
        except (AttributeError, ValueError) as exc:
            errors.append(str(exc))
    normalized_paths: dict[str, list[str]] = {}
    for field, required_paths in (("paths", True), ("excluded_paths", False), ("untrack_paths", False)):
        if field == "untrack_paths" and field not in plan:
            continue
        values = plan.get(field)
        if not isinstance(values, list) or (required_paths and not values):
            errors.append(f"{field} must be {'a non-empty' if required_paths else 'an'} array")
            continue
        seen: set[str] = set()
        normalized_values: list[str] = []
        for value in values:
            try:
                normalized = safe_relative_path(value, label=field).as_posix()
                normalized_values.append(normalized)
                if normalized in seen:
                    errors.append(f"{field} cannot contain duplicates")
                seen.add(normalized)
                reason = _unsafe_reason(normalized)
                if field in {"paths", "untrack_paths"} and reason:
                    errors.append(f"unsafe approved path {normalized!r}: {reason}")
            except (AttributeError, ValueError) as exc:
                errors.append(str(exc))
        normalized_paths[field] = normalized_values
    untrack_paths = normalized_paths.get("untrack_paths", [])
    if untrack_paths:
        path_overlap = sorted(set(untrack_paths) & set(normalized_paths.get("paths", [])))
        excluded_overlap = sorted(set(untrack_paths) & set(normalized_paths.get("excluded_paths", [])))
        if path_overlap:
            errors.append("approved and untrack paths overlap: " + ", ".join(path_overlap))
        if excluded_overlap:
            errors.append("excluded and untrack paths overlap: " + ", ".join(excluded_overlap))
        errors.extend(_validate_untrack_paths(project, tuple(untrack_paths)))
    verification = plan.get("verification")
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
    else:
        if set(verification) != {"kind", "artifact_ref", "workspace_digest"}:
            errors.append("verification must contain kind, artifact_ref, and workspace_digest")
        if verification.get("kind") not in {"integration", "architecture"}:
            errors.append("verification.kind must be integration or architecture")
        try:
            safe_relative_path(verification.get("artifact_ref"), label="verification artifact")
        except (AttributeError, ValueError) as exc:
            errors.append(str(exc))
        digest = verification.get("workspace_digest")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            errors.append("verification.workspace_digest must be a lowercase SHA-256 digest")
        if verification.get("kind") == "architecture" and isinstance(plan.get("paths"), list):
            invalid = [path for path in plan["paths"] if not _architecture_commit_path(path)]
            if invalid:
                errors.append("architecture-only plans contain non-architecture paths: " + ", ".join(invalid))
    for field, maximum in (("commit_subject", 72), ("commit_body", 4000), ("pr_title", 200), ("pr_summary", 10000)):
        value = plan.get(field)
        if not isinstance(value, str) or (field != "commit_body" and not value.strip()) or len(value) > maximum:
            errors.append(f"{field} must be a valid string of at most {maximum} characters")
    if isinstance(plan.get("commit_subject"), str) and "\n" in plan["commit_subject"]:
        errors.append("commit_subject must be one line")
    for field in ("warnings",):
        value = plan.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{field} must be a list of strings")
    if errors:
        raise GitStewardError("invalid commit plan: " + "; ".join(errors))
    return plan


def authorize_plan(
    project: str | Path,
    plan_path: str | Path,
    *,
    apply: bool = False,
) -> tuple[dict[str, Any], Path]:
    root = exact_git_root(project)
    plan = load_commit_plan(root, plan_path)
    _validate_plan_against_repository(root, plan)
    verification = _verification_from_plan(root, plan)
    authorization = {
        "schema_version": "1.0",
        "boundary_id": plan["boundary_id"],
        "project_root": str(root),
        "branch": plan["branch"],
        "expected_head": plan["expected_head"],
        "plan_digest": _json_digest(plan),
        "approved_paths": plan["paths"],
        "verification": verification,
        "authorized_at": _utc_now(),
    }
    if "untrack_paths" in plan:
        authorization["untrack_paths"] = plan["untrack_paths"]
    destination = _runtime_path(root, plan["boundary_id"], "authorization.json")
    if apply:
        atomic_write_json(destination, authorization)
        destination.chmod(0o600)
    return authorization, destination


def commit_authorized_plan(
    project: str | Path,
    plan_path: str | Path,
    authorization_path: str | Path,
    *,
    apply: bool = False,
) -> tuple[dict[str, Any], Path]:
    root = exact_git_root(project)
    plan = load_commit_plan(root, plan_path)
    authorization = _load_authorization(root, authorization_path)
    _match_authorization(plan, authorization)
    _validate_plan_against_repository(root, plan)
    verification = _verification_from_plan(root, plan)
    if verification != authorization.get("verification"):
        raise GitStewardError("verification evidence changed after authorization")
    preview = {
        "schema_version": "1.0",
        "boundary_id": plan["boundary_id"],
        "status": "ready",
        "project_root": str(root),
        "branch": plan["branch"],
        "head_before": plan["expected_head"],
        "approved_paths": plan["paths"],
        "untrack_paths": plan.get("untrack_paths", []),
        "verification": verification,
    }
    destination = _runtime_path(root, plan["boundary_id"], "commit-record.json")
    if not apply:
        return preview, destination
    _require_identity(root)
    _require_no_active_hooks(root)
    candidate_tree, candidate_gate = _candidate_tree_and_verification(root, plan)
    preview["candidate_tree"] = candidate_tree
    preview["candidate_gate"] = candidate_gate
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").stdout.strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    index_backup = index_path.read_bytes() if index_path.is_file() else None
    try:
        _stage_paths(root, tuple(plan["paths"]))
        untrack_paths = tuple(plan.get("untrack_paths", []))
        _untrack_paths(root, untrack_paths)
        _verify_untracked_paths(root, untrack_paths)
        staged_tree = _git(root, "write-tree").stdout.strip()
        if staged_tree != candidate_tree:
            raise GitStewardError("real staged tree differs from the verified candidate tree")
        message = _commit_message(plan)
        committed = _git(
            root,
            "-c", "commit.gpgSign=false",
            "commit", "--no-verify", "--file", "-",
            input_text=message,
            allow_failure=True,
        )
        if committed.returncode != 0:
            raise GitStewardError(committed.stderr.strip() or "git commit failed")
    except Exception:
        _restore_index(index_path, index_backup)
        raise
    head_after = _head(root)
    if head_after is None or head_after == plan["expected_head"]:
        raise GitStewardError("Git HEAD did not advance after commit")
    tree_after = _git(root, "rev-parse", f"{head_after}^{{tree}}").stdout.strip()
    if tree_after != candidate_tree:
        raise GitStewardError("committed tree differs from the verified candidate tree")
    committed_paths = _commit_paths(root, head_after)
    expected_paths = set(plan["paths"]) | set(plan.get("untrack_paths", []))
    if set(committed_paths) != expected_paths:
        raise GitStewardError("committed path set differs from the approved plan")
    record = {
        "schema_version": "1.0",
        "boundary_id": plan["boundary_id"],
        "status": "committed",
        "project_root": str(root),
        "branch": plan["branch"],
        "head_before": plan["expected_head"],
        "head_after": head_after,
        "tree": tree_after,
        "committed_paths": committed_paths,
        "verification": verification,
        "commit_subject": plan["commit_subject"],
        "committed_at": _utc_now(),
    }
    atomic_write_json(destination, record)
    destination.chmod(0o600)
    summary_path = _runtime_path(root, plan["boundary_id"], "PR_SUMMARY.md")
    atomic_write_text(summary_path, f"# {plan['pr_title']}\n\n{plan['pr_summary'].rstrip()}\n")
    summary_path.chmod(0o600)
    return record, destination


def exact_git_root(project: str | Path) -> Path:
    root = ensure_existing_workspace(project)
    completed = _git(root, "rev-parse", "--show-toplevel", allow_failure=True)
    if completed.returncode != 0:
        raise GitStewardError(f"project is not a Git repository: {root}")
    reported = Path(completed.stdout.strip()).resolve(strict=True)
    if reported != root:
        raise GitStewardError(f"assigned workspace is not the exact Git root: {root}; found {reported}")
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and create verified local milestone commits.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("project")
    inspect_parser.add_argument("--boundary", required=True)
    inspect_parser.add_argument("--tasks", required=True)
    inspect_parser.add_argument("--verification-kind", choices=("integration", "architecture"), default="integration")
    inspect_parser.add_argument("--architecture-evidence")
    inspect_parser.add_argument("--json", action="store_true")
    authorize_parser = subparsers.add_parser("authorize")
    authorize_parser.add_argument("project")
    authorize_parser.add_argument("--plan", required=True)
    authorize_parser.add_argument("--apply", action="store_true")
    authorize_parser.add_argument("--json", action="store_true")
    commit_parser = subparsers.add_parser("commit")
    commit_parser.add_argument("project")
    commit_parser.add_argument("--plan", required=True)
    commit_parser.add_argument("--authorization", required=True)
    commit_parser.add_argument("--apply", action="store_true")
    commit_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            payload = inspect_repository(
                args.project,
                boundary_id=args.boundary,
                task_ids=tuple(item.strip() for item in args.tasks.split(",") if item.strip()),
                verification_kind=args.verification_kind,
                architecture_evidence=args.architecture_evidence,
            )
            destination = None
        elif args.command == "authorize":
            payload, destination = authorize_plan(args.project, args.plan, apply=args.apply)
        else:
            payload, destination = commit_authorized_plan(
                args.project,
                args.plan,
                args.authorization,
                apply=args.apply,
            )
    except (FileNotFoundError, GateConfigError, GitStewardError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Boundary: {payload['boundary_id']}")
        print(f"Status: {payload.get('status', 'inspected')}")
        if destination is not None:
            print(f"Record: {destination}")
        if payload.get("head_after"):
            print(f"Commit: {payload['head_after']}")
    return 0


def _validate_plan_against_repository(root: Path, plan: dict[str, Any]) -> None:
    if _branch(root) != plan["branch"]:
        raise GitStewardError("current branch differs from the commit plan")
    if _head(root) != plan["expected_head"]:
        raise GitStewardError("Git HEAD differs from the commit plan")
    staged = _name_list(_git(root, "diff", "--cached", "--name-only", "-z", allow_failure=True).stdout)
    if staged:
        raise GitStewardError("repository already contains staged changes: " + ", ".join(staged))
    tracked = set(_name_list(_git(root, "diff", "--name-only", "-z", allow_failure=True).stdout))
    untracked = set(_name_list(_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout))
    available = tracked | untracked
    approved = set(plan["paths"])
    excluded = set(plan["excluded_paths"])
    untrack = set(plan.get("untrack_paths", []))
    overlap = sorted(approved & excluded)
    if overlap:
        raise GitStewardError("approved and excluded paths overlap: " + ", ".join(overlap))
    overlap = sorted(approved & untrack)
    if overlap:
        raise GitStewardError("approved and untrack paths overlap: " + ", ".join(overlap))
    overlap = sorted(excluded & untrack)
    if overlap:
        raise GitStewardError("excluded and untrack paths overlap: " + ", ".join(overlap))
    missing = sorted(approved - available)
    if missing:
        raise GitStewardError("approved paths are not current changes: " + ", ".join(missing))
    unknown_excluded = sorted(excluded - available)
    if unknown_excluded:
        raise GitStewardError("excluded paths are not current changes: " + ", ".join(unknown_excluded))
    unclassified = sorted(available - approved - excluded - untrack)
    if unclassified:
        raise GitStewardError("commit plan leaves changed paths unclassified: " + ", ".join(unclassified))


def _verification(root: Path, kind: str, architecture_evidence: str | None) -> dict[str, str]:
    if kind == "integration":
        try:
            record = validate_current_gate_record(root, "integration")
        except GateConfigError as exc:
            raise GitStewardError(str(exc)) from exc
        return {
            "kind": "integration",
            "artifact_ref": "results/gates/integration.json",
            "workspace_digest": record["workspace_digest"],
        }
    if kind != "architecture" or not architecture_evidence:
        raise GitStewardError("architecture verification requires --architecture-evidence")
    relative = safe_relative_path(architecture_evidence, label="architecture evidence").as_posix()
    path = contained_path(root, relative, label="architecture evidence")
    if path.is_symlink() or not path.is_file():
        raise GitStewardError(f"architecture evidence is missing or unsafe: {path}")
    return {
        "kind": "architecture",
        "artifact_ref": relative,
        "workspace_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _verification_from_plan(root: Path, plan: dict[str, Any]) -> dict[str, str]:
    proposed = plan["verification"]
    current = _verification(
        root,
        proposed["kind"],
        proposed["artifact_ref"] if proposed["kind"] == "architecture" else None,
    )
    if current != proposed:
        raise GitStewardError("commit plan verification is stale or does not match current evidence")
    return current


def _candidate_tree_and_verification(root: Path, plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _require_identity(root)
    with tempfile.TemporaryDirectory(prefix="codexteam-git-index-") as temporary:
        index_path = Path(temporary) / "index"
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index_path)
        if plan["expected_head"] is None:
            _git(root, "read-tree", "--empty", env=env)
        else:
            _git(root, "read-tree", plan["expected_head"], env=env)
        _stage_paths(root, tuple(plan["paths"]), env=env)
        untrack_paths = tuple(plan.get("untrack_paths", []))
        _untrack_paths(root, untrack_paths, env=env)
        _verify_untracked_paths(root, untrack_paths, env=env)
        tree = _git(root, "write-tree", env=env).stdout.strip()
    if plan["verification"]["kind"] == "architecture":
        return tree, {"status": "not_applicable", "kind": "architecture"}
    parent_args = ("-p", plan["expected_head"]) if plan["expected_head"] else ()
    candidate = _git(
        root,
        "commit-tree", tree, *parent_args,
        input_text="CodexTeam candidate verification\n",
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="codexteam-candidate-") as temporary:
        candidate_root = Path(temporary) / "worktree"
        _git(root, "worktree", "add", "--detach", str(candidate_root), candidate)
        try:
            record = run_gate(
                candidate_root,
                "integration",
                execution_surface=load_gate_config(candidate_root).integration_surface,
            )
        finally:
            _git(root, "worktree", "remove", "--force", str(candidate_root), allow_failure=True)
            _git(root, "worktree", "prune", allow_failure=True)
    if record.get("status") != "passed":
        raise GitStewardError("Integration Gate failed against the candidate commit tree")
    return tree, {
        "status": "passed",
        "kind": "integration",
        "workspace_digest": record["workspace_digest"],
        "duration_seconds": record["duration_seconds"],
    }


def _stage_paths(root: Path, paths: tuple[str, ...], env: dict[str, str] | None = None) -> None:
    for relative in paths:
        path = contained_path(root, relative, label="approved path")
        if path.exists() or path.is_symlink():
            _git(root, "add", "--", relative, env=env)
        else:
            result = _git(root, "rm", "--cached", "--ignore-unmatch", "--", relative, env=env, allow_failure=True)
            if result.returncode != 0:
                raise GitStewardError(f"failed to stage deleted path: {relative}")


def _untrack_paths(root: Path, paths: tuple[str, ...], env: dict[str, str] | None = None) -> None:
    if not paths:
        return
    result = _git(root, "rm", "--cached", "--", *paths, env=env, allow_failure=True)
    if result.returncode != 0:
        raise GitStewardError(result.stderr.strip() or "failed to untrack approved paths")


def _verify_untracked_paths(
    root: Path,
    paths: tuple[str, ...],
    *,
    env: dict[str, str] | None = None,
) -> None:
    tracked = _tracked_paths(root, env=env)
    for relative in paths:
        path = contained_path(root, relative, label="untrack path")
        if not path.is_file():
            raise GitStewardError(f"untrack path is no longer a file on disk: {relative}")
        if relative in tracked:
            raise GitStewardError(f"untrack path remains in the index: {relative}")


def _validate_untrack_paths(root: Path, paths: tuple[str, ...]) -> list[str]:
    tracked = _tracked_paths(root)
    errors: list[str] = []
    for relative in paths:
        path = contained_path(root, relative, label="untrack path")
        if path.is_dir():
            errors.append(f"untrack path cannot select a directory: {relative}")
        elif not path.is_file():
            errors.append(f"untrack path is missing: {relative}")
        if relative not in tracked:
            errors.append(f"untrack path is not tracked: {relative}")
        if not _is_ignored(root, relative):
            errors.append(f"untrack path is not ignored: {relative}")
    return errors


def _tracked_paths(root: Path, *, env: dict[str, str] | None = None) -> set[str]:
    return set(_name_list(_git(root, "ls-files", "-z", env=env).stdout))


def _is_ignored(root: Path, relative: str) -> bool:
    result = _git(root, "check-ignore", "--no-index", "--quiet", "--", relative, allow_failure=True)
    return result.returncode == 0


def _load_authorization(root: Path, path_value: str | Path) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve(strict=True)
    try:
        path.relative_to(root / ".codexteam" / "runtime" / "git-steward")
    except ValueError as exc:
        raise GitStewardError("authorization must be under ignored Git Steward runtime storage") from exc
    if path.is_symlink() or not path.is_file():
        raise GitStewardError(f"authorization is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GitStewardError(f"invalid authorization JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise GitStewardError("authorization schema_version must be '1.0'")
    return value


def _match_authorization(plan: dict[str, Any], authorization: dict[str, Any]) -> None:
    expected = {
        "boundary_id": plan["boundary_id"],
        "project_root": plan["project_root"],
        "branch": plan["branch"],
        "expected_head": plan["expected_head"],
        "plan_digest": _json_digest(plan),
        "approved_paths": plan["paths"],
        "verification": plan["verification"],
    }
    if "untrack_paths" in plan:
        expected["untrack_paths"] = plan["untrack_paths"]
    mismatches = [key for key, value in expected.items() if authorization.get(key) != value]
    if mismatches:
        raise GitStewardError("authorization does not match the plan: " + ", ".join(mismatches))


def _commit_message(plan: dict[str, Any]) -> str:
    body = plan["commit_body"].strip()
    sections = [plan["commit_subject"].strip()]
    if body:
        sections.append(body)
    sections.append(
        "\n".join(
            (
                f"CodexTeam-Boundary: {plan['boundary_id']}",
                f"CodexTeam-Tasks: {','.join(plan['task_ids'])}",
                f"CodexTeam-Verification: {plan['verification']['artifact_ref']}",
            )
        )
    )
    return "\n\n".join(sections).rstrip() + "\n"


def _commit_paths(root: Path, commit: str) -> list[str]:
    output = _git(root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", commit).stdout
    return sorted(_name_list(output))


def _require_identity(root: Path) -> None:
    for key in ("user.name", "user.email"):
        value = _git(root, "config", "--get", key, allow_failure=True).stdout.strip()
        if not value:
            raise GitStewardError(f"Git identity {key} is not configured")


def _require_no_active_hooks(root: Path) -> None:
    configured = _git(root, "config", "--path", "--get", "core.hooksPath", allow_failure=True).stdout.strip()
    if configured:
        hooks = Path(configured)
        if not hooks.is_absolute():
            hooks = root / hooks
    else:
        hooks = Path(_git(root, "rev-parse", "--git-path", "hooks").stdout.strip())
        if not hooks.is_absolute():
            hooks = root / hooks
    if hooks.is_dir():
        active = sorted(path.name for path in hooks.iterdir() if path.is_file() and not path.name.endswith(".sample") and os.access(path, os.X_OK))
        if active:
            raise GitStewardError("active Git hooks require human handling: " + ", ".join(active))


def _restore_index(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".index.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _runtime_path(root: Path, boundary: str, name: str) -> Path:
    return contained_path(root, f".codexteam/runtime/git-steward/{boundary}/{name}", label="Git Steward runtime path")


def _unsafe_reason(relative: str) -> str | None:
    parts = relative.split("/")
    if any(part in PROHIBITED_PARTS for part in parts):
        return "prohibited runtime or repository metadata"
    if relative.startswith(".codexteam/runtime/"):
        return "ignored CodexTeam runtime"
    name = parts[-1]
    if name in PROHIBITED_NAMES or Path(name).suffix.lower() in PROHIBITED_SUFFIXES:
        return "secret-like, temporary, or backup file"
    return None


def _architecture_commit_path(relative: str) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in ARCHITECTURE_COMMIT_PATTERNS)


def _branch(root: Path) -> str:
    result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD", allow_failure=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise GitStewardError("Git Steward requires a named branch, not detached HEAD")
    return result.stdout.strip()


def _head(root: Path) -> str | None:
    result = _git(root, "rev-parse", "--verify", "HEAD", allow_failure=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _name_list(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split("\0") if item)


def _json_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git(
    root: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        raise FileNotFoundError("git executable is required")
    completed = subprocess.run(
        [executable, "-C", str(root), *arguments],
        text=True,
        input=input_text,
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 and not allow_failure:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
        raise GitStewardError(f"git {' '.join(arguments)} failed: {detail}")
    return completed


if __name__ == "__main__":
    raise SystemExit(main())
