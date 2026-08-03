"""Parent-tool recording path for per-task Lead orchestration metrics.

Writes ``.codexteam/runtime/lead-metrics.json`` inside the given project
root.  The WebUI reader (S1, T010) consumes this file but imports nothing
from this module — read-only data boundary preserved.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import atomic_write_json


TASK_ID_RE = re.compile(r"T[0-9]{3,6}")


def _validate_numeric(name: str, value: object) -> None | str:
    """Return an error string unless value is a finite, non-bool number >= 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{name} must be a non-negative number"
    if value < 0 or not math.isfinite(value):
        return f"{name} must be a non-negative number"
    return None


def record_lead_usage(
    project: str | Path,
    *,
    task_id: str,
    profile: str,
    provider: str,
    duration_seconds: float,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    dry_run: bool = False,
) -> None | str:
    """Record one Lead orchestration usage entry.

    Parameters
    ----------
    project:
        Project root directory (must exist as a directory for real writes).
    task_id:
        e.g. ``"T002"`` — validated against the T + 3..6 digits pattern.
    profile, provider:
        Non-empty model-profile and provider strings.
    duration_seconds:
        Wall-clock orchestration time in seconds (≥ 0).
    input_tokens, cached_input_tokens, output_tokens:
        Codex-reported token counts (≥ 0); ``cached_input_tokens`` must not
        exceed ``input_tokens``.
    dry_run:
        Validate only; do not touch the filesystem or require the path.

    Returns
    -------
    None on success; a validation-error string on failure.
    """
    # --- Validation (applied before any I/O) --------------------------------

    if not isinstance(task_id, str):
        return "task_id must be a string"
    normalised = task_id.strip().upper()

    # 1. task_id pattern
    if not TASK_ID_RE.fullmatch(normalised):
        return f"invalid task ID: {task_id!r}; expected T followed by 3-6 digits"

    # 2. profile and provider are non-empty strings
    if not isinstance(profile, str) or not profile.strip():
        return "profile must be a non-empty string"
    if not isinstance(provider, str) or not provider.strip():
        return "provider must be a non-empty string"

    # 3. Numeric fields are non-negative, non-bool, finite numbers
    for name, value in (
        ("duration_seconds", duration_seconds),
        ("input_tokens", input_tokens),
        ("cached_input_tokens", cached_input_tokens),
        ("output_tokens", output_tokens),
    ):
        error = _validate_numeric(name, value)
        if error:
            return error

    # 4. Invariant: cached_input_tokens <= input_tokens
    if cached_input_tokens > input_tokens:
        return "cached_input_tokens must not exceed input_tokens"

    # 5. Dry-run: stop after validation without filesystem access
    if dry_run:
        return None

    # --- I/O path -----------------------------------------------------------

    project = Path(project).resolve()
    if not project.is_dir():
        return f"project path does not exist or is not a directory: {project}"

    runtime_dir = project / ".codexteam" / "runtime"
    metrics_path = runtime_dir / "lead-metrics.json"

    # Read existing data or start with an empty structure
    if metrics_path.is_file():
        try:
            data: dict[str, Any] = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "existing lead-metrics.json contains invalid JSON; refusing to overwrite"
        if not isinstance(data, dict):
            return "existing lead-metrics.json root is not an object; refusing to overwrite"
        if data.get("schema_version") != "1.0":
            return (
                f"existing lead-metrics.json has schema_version {data.get('schema_version')!r}; "
                "expected '1.0'; refusing to overwrite"
            )
        if not isinstance(data.get("tasks"), dict):
            return (
                "existing lead-metrics.json 'tasks' key is not an object; "
                "refusing to overwrite"
            )
    else:
        data: dict[str, Any] = {}

    tasks_map: dict[str, dict[str, Any]] = data.get("tasks") or {}
    data["tasks"] = tasks_map

    # Merge/replace the single task key
    task_record = {
        "metric_scope": "lead_orchestration",
        "profile": profile.strip(),
        "provider": provider.strip(),
        "duration_seconds": duration_seconds,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": input_tokens - cached_input_tokens,
        "output_tokens": output_tokens,
    }
    tasks_map[normalised] = task_record

    # Update metadata
    data["schema_version"] = "1.0"
    data["metric_scope"] = "lead_orchestration"
    data["generated_at"] = datetime.now(timezone.utc).isoformat()

    # Atomic write
    runtime_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(metrics_path, data)

    return None
