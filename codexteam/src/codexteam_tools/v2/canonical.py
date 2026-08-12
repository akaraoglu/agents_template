from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel


def validate_project_path(value: str) -> str:
    """Validate a canonical project-relative POSIX path."""
    if not value or "\x00" in value or "\\" in value or any(char in value for char in "*?[]"):
        raise ValueError("path must be a non-empty project-relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("path must not be absolute or contain '.', '..', or empty segments")
    return value


def validate_project_path_pattern(value: str) -> str:
    """Validate a safe project-relative fnmatch pattern using only * and **."""
    if not value or "\x00" in value or "\\" in value or any(char in value for char in "?[]"):
        raise ValueError("path pattern must be a safe project-relative POSIX glob")
    if "***" in value:
        raise ValueError("path pattern wildcards must be '*' or '**'")
    # Stars do not affect path traversal or segment validation.
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("path pattern must not be absolute or contain '.', '..', or empty segments")
    return value


def validate_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamp must be UTC-aware")
    return value


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        # Contract digests always cover the validated model representation.
        return _canonical_value(value.model_dump(mode="python", by_alias=True))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        validate_utc_datetime(value)
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical mappings require string keys")
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return value


def canonical_json(value: Any) -> str:
    """Return stable UTF-8 JSON with sorted object keys and no insignificant space."""
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def verify_digest(value: Any, expected_digest: str) -> bool:
    """Compare a canonical SHA-256 digest without timing-dependent equality."""
    return hmac.compare_digest(canonical_sha256(value), expected_digest)


sha256_digest = canonical_sha256
