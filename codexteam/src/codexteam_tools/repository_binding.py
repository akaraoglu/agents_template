from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .paths import ensure_existing_workspace, validate_identifier


class RepositoryBindingError(ValueError):
    pass


@dataclass(frozen=True)
class RepositoryBinding:
    control_root: Path
    work_root: Path
    git_root: Path
    git_prefix: str
    repo_id: str


def load_repository_binding(
    control_root: str | Path,
    work_root: str | Path,
    repo_id: str,
) -> RepositoryBinding:
    repo_id = validate_identifier(repo_id, label="repository ID")
    control = _safe_root(control_root, "control root")
    work = _safe_root(work_root, "work root")
    registry_path = control / "REPOSITORIES.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        raise RepositoryBindingError(f"repository registry is missing or unsafe: {registry_path}")
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RepositoryBindingError(f"invalid repository registry JSON: {exc}") from exc
    if not isinstance(registry, dict) or registry.get("schema_version") != "1.0":
        raise RepositoryBindingError("repository registry schema_version must be '1.0'")
    entries = registry.get("repositories")
    if not isinstance(entries, list):
        raise RepositoryBindingError("repository registry repositories must be a list")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("id") == repo_id]
    if len(matches) != 1:
        raise RepositoryBindingError(f"unknown or duplicate repository ID: {repo_id}")
    entry: dict[str, Any] = matches[0]
    if entry.get("write_policy") != "task-owned":
        raise RepositoryBindingError(f"repository {repo_id} write_policy must be task-owned")

    expected_work = _registered_work_root(entry, repo_id)
    if work != expected_work:
        raise RepositoryBindingError(
            f"work root does not match repository {repo_id}: expected {expected_work}, found {work}"
        )
    if (work / ".repo").exists() or (work / ".repo").is_symlink():
        raise RepositoryBindingError("work root must not be a repo manifest root")

    git_value = entry.get("git_root")
    if not isinstance(git_value, str) or not Path(git_value).is_absolute():
        raise RepositoryBindingError(f"repository {repo_id} git_root must be absolute")
    git_root = _safe_root(git_value, "Git root")
    observed_git_root = Path(_git(work, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if observed_git_root != git_root:
        raise RepositoryBindingError(
            f"Git root mismatch: expected {git_root}, found {observed_git_root}"
        )
    try:
        relative = work.relative_to(git_root)
    except ValueError as exc:
        raise RepositoryBindingError("work root must equal or be contained under Git root") from exc
    observed_prefix = relative.as_posix() or "."
    prefix = entry.get("git_prefix")
    if not _normalized_relative(prefix) or prefix != observed_prefix:
        raise RepositoryBindingError(
            f"repository git_prefix mismatch: expected {observed_prefix!r}, found {prefix!r}"
        )
    assert isinstance(prefix, str)

    remote_url = entry.get("remote_url")
    if remote_url is not None:
        if not isinstance(remote_url, str) or not remote_url:
            raise RepositoryBindingError(f"repository {repo_id} remote_url must be non-empty or null")
        observed_urls = {
            line.split(None, 1)[1]
            for line in _git(git_root, "config", "--get-regexp", r"^remote\..*\.url$").splitlines()
            if len(line.split(None, 1)) == 2
        }
        if remote_url not in observed_urls:
            raise RepositoryBindingError(
                f"repository remote_url mismatch: expected {remote_url!r}, found {sorted(observed_urls)!r}"
            )
    return RepositoryBinding(control, work, git_root, prefix, repo_id)


def _registered_work_root(entry: dict[str, Any], repo_id: str) -> Path:
    work_value = entry.get("work_root")
    checkout_value = entry.get("checkout_root")
    path_value = entry.get("path")
    direct = work_value is not None
    composed = checkout_value is not None or path_value is not None
    if direct == composed:
        raise RepositoryBindingError(
            f"repository {repo_id} requires either work_root or checkout_root plus path"
        )
    if direct:
        if not isinstance(work_value, str) or not Path(work_value).is_absolute():
            raise RepositoryBindingError(f"repository {repo_id} work_root must be absolute")
        return _safe_root(work_value, "registered work root")
    if not isinstance(checkout_value, str) or not Path(checkout_value).is_absolute():
        raise RepositoryBindingError(f"repository {repo_id} checkout_root must be absolute")
    if not _normalized_relative(path_value) or path_value == ".":
        raise RepositoryBindingError(f"repository {repo_id} path must be a normalized relative path")
    assert isinstance(path_value, str)
    checkout = _safe_root(checkout_value, "checkout root")
    expected = _safe_root(checkout / path_value, "registered work root")
    try:
        expected.relative_to(checkout)
    except ValueError as exc:
        raise RepositoryBindingError(f"repository {repo_id} escapes checkout root") from exc
    return expected


def _safe_root(value: str | Path, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise RepositoryBindingError(f"{label} must not be a symlink")
    return ensure_existing_workspace(raw)


def _normalized_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.as_posix() == value


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RepositoryBindingError(f"Git binding check failed: {detail}")
    return completed.stdout.strip()
