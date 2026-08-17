from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_REQUEST_BYTES = 1_000_000
DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
MAX_TIMEOUT_SECONDS = 300.0
MAX_REQUEST_BYTES = 16_000_000
MAX_RESPONSE_BYTES = 16_000_000


class Mode(str, Enum):
    OPTIONAL = "optional"
    REQUIRED = "required"


@dataclass(frozen=True)
class ServerSpec:
    command: tuple[str, ...]
    expected_name: str
    expected_version: str
    allowed_tools: frozenset[str]
    mode: Mode = Mode.OPTIONAL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    environment: tuple[tuple[str, str], ...] = ()
    cwd: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, tuple) or not self.command or any(
            not isinstance(item, str) or not item for item in self.command
        ):
            raise ValueError("command must contain non-empty strings")
        if not self.expected_name or not self.expected_version:
            raise ValueError("expected server identity must be non-empty")
        if (
            not isinstance(self.allowed_tools, frozenset)
            or not self.allowed_tools
            or any(not isinstance(name, str) or not name for name in self.allowed_tools)
        ):
            raise ValueError("allowed_tools must contain non-empty names")
        if not isinstance(self.mode, Mode):
            raise ValueError("mode must be optional or required")
        if isinstance(self.timeout_seconds, bool) or not (
            0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout_seconds is outside the supported range")
        if isinstance(self.max_response_bytes, bool) or not (
            128 <= self.max_response_bytes <= MAX_RESPONSE_BYTES
        ):
            raise ValueError("max_response_bytes is outside the supported range")
        if isinstance(self.max_request_bytes, bool) or not (
            128 <= self.max_request_bytes <= MAX_REQUEST_BYTES
        ):
            raise ValueError("max_request_bytes is outside the supported range")
        if not isinstance(self.environment, tuple):
            raise ValueError("environment must be an immutable tuple")
        if len(dict(self.environment)) != len(self.environment):
            raise ValueError("environment contains duplicate names")
        if any(not name or not isinstance(value, str) for name, value in self.environment):
            raise ValueError("environment must contain string name/value pairs")


@dataclass(frozen=True)
class Provenance:
    server_name: str
    server_version: str
    tool: str
    duration_ms: float
    returned_bytes: int
    source_bytes: int | None = None
    cache_hit: bool | None = None
    error_class: str | None = None


@dataclass(frozen=True)
class AvailabilityResult:
    available: bool
    tools: tuple[str, ...]
    provenance: Provenance


@dataclass(frozen=True)
class CallResult:
    available: bool
    content: Any | None
    provenance: Provenance


class SidecarError(RuntimeError):
    """Bounded public failure for a required sidecar."""

    def __init__(self, server_name: str, error_class: str) -> None:
        self.server_name = server_name
        self.error_class = error_class
        super().__init__(f"MCP sidecar {server_name}: {error_class}")
