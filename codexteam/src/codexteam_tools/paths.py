from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

DEFAULT_PROJECTS_ROOT = Path("/home/alik/workspace/agent_template/codexteam/projects")
PROJECTS_ROOT_ENV = "CODEXTEAM_PROJECTS_ROOT"

TASK_ID_PATTERN = re.compile(r"T[0-9]{3,6}")
PROFILE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class PathValidationError(ValueError):
    pass


def projects_root(override: str | Path | None = None) -> Path:
    value = override or os.environ.get(PROJECTS_ROOT_ENV) or DEFAULT_PROJECTS_ROOT
    return Path(value).expanduser().resolve(strict=False)


def normalize_task_id(value: str) -> str:
    task_id = value.strip().upper()
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise PathValidationError(f"invalid task ID: {value!r}; expected T followed by 3-6 digits")
    return task_id


def validate_profile(value: str) -> str:
    profile = value.strip()
    if not PROFILE_PATTERN.fullmatch(profile):
        raise PathValidationError(f"invalid profile name: {value!r}")
    return profile


def validate_identifier(value: str, *, label: str) -> str:
    identifier = value.strip()
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise PathValidationError(f"invalid {label}: {value!r}")
    return identifier


def slugify_project_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise PathValidationError("project name cannot be empty")
    if "/" in name or "\\" in name or name in {".", ".."} or ".." in name.split():
        raise PathValidationError("project name cannot contain path separators or traversal segments")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug or len(slug) > 80:
        raise PathValidationError("project name must produce a 1-80 character slug")
    return slug


def safe_relative_path(value: str, *, label: str = "path", allow_dot: bool = False) -> PurePosixPath:
    if not isinstance(value, str) or not value.strip():
        raise PathValidationError(f"{label} must be a non-empty relative path")
    if "\\" in value:
        raise PathValidationError(f"{label} must use forward slashes")
    if value == "." and allow_dot:
        return PurePosixPath(value)
    if value == "." or value.startswith("./") or "//" in value:
        raise PathValidationError(f"unsafe {label}: {value!r}")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise PathValidationError(f"unsafe {label}: {value!r}")
    return candidate


def contained_path(root: Path, relative: str, *, label: str = "path") -> Path:
    safe = safe_relative_path(relative, label=label)
    canonical_root = root.expanduser().resolve(strict=False)
    candidate = (canonical_root / Path(*safe.parts)).resolve(strict=False)
    try:
        candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise PathValidationError(f"{label} escapes workspace root: {relative!r}") from exc
    return candidate


def ensure_existing_workspace(value: str | Path) -> Path:
    workspace = Path(value).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise PathValidationError(f"workspace is not a directory: {workspace}")
    return workspace
