#!/usr/bin/env python3
"""Shared self-healing primitives for OpenClaw worker runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecoveryDirective:
    """A structured instruction for a worker to repair recoverable output."""

    code: str
    message: str
    mode: str
    next_command: str
    attempt: int
    max_attempts: int
    missing_paths: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def exhausted(self) -> bool:
        return self.attempt >= self.max_attempts


def recovery_state_update(directive: RecoveryDirective) -> dict[str, object]:
    """Return durable state fields common to recoverable worker failures."""

    return {
        "status": "repair_needed",
        "last_error": {
            "code": directive.code,
            "message": directive.message,
        },
        "repair_guard": {
            "reason": directive.code,
            "mode": directive.mode,
            "attempt": directive.attempt,
            "max_attempts": directive.max_attempts,
            "missing_paths": list(directive.missing_paths),
            "allowed_repair_paths": list(directive.allowed_paths),
            "forbidden_repair_paths": list(directive.forbidden_paths),
        },
    }


def print_recovery_directive(directive: RecoveryDirective) -> None:
    """Print a stable repair envelope for model-facing worker tools."""

    print(f"WORKER_RUNTIME_REPAIR_REQUIRED[{directive.code}]: {directive.message}")
    print(f"REPAIR_MODE={directive.mode}")
    print(f"REPAIR_ATTEMPT={directive.attempt}/{directive.max_attempts}")
    if directive.missing_paths:
        print("MISSING_PATHS=" + ", ".join(directive.missing_paths))
    if directive.allowed_paths:
        print("ALLOWED_REPAIR_PATHS=" + ", ".join(directive.allowed_paths))
    if directive.forbidden_paths:
        print("FORBIDDEN_REPAIR_PATHS=" + ", ".join(directive.forbidden_paths))
    for key, value in directive.extra.items():
        print(f"{key}={value}")
    print(f"NEXT_REQUIRED={directive.next_command}")
