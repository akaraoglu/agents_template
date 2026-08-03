from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .turn_metrics import NON_TOOL_ITEM_TYPES, command_observation


DEFAULT_REPEAT_LIMIT = 3
DEFAULT_MAX_COMMAND_OUTPUT_BYTES = 32 * 1024
CONTEXT_SERVER = "codexteam-context"
BROAD_DISCOVERY = (
    re.compile(r"(?:^|[\s;&|])(?:rg|ripgrep)\s+--files\b"),
    re.compile(r"(?:^|[\s;&|])find\s+\.?(?:\s|$)"),
    re.compile(r"(?:^|[\s;&|])git\s+status\b(?![^;&|]*\s--\s+[^;&|]+)"),
    re.compile(r"(?:^|[\s;&|])git\s+diff\b(?![^;&|]*\s--\s+[^;&|]+)"),
)


@dataclass(frozen=True)
class GuardDecision:
    reason: str
    command_fingerprint: str
    output_fingerprint: str
    count: int


class ExactFailedRepeatGuard:
    """Interrupt repeated failures, oversized output, and post-context broad discovery."""

    def __init__(
        self,
        *,
        repeat_limit: int = DEFAULT_REPEAT_LIMIT,
        max_command_output_bytes: int = DEFAULT_MAX_COMMAND_OUTPUT_BYTES,
    ) -> None:
        if repeat_limit < 2:
            raise ValueError("repeat limit must be at least 2")
        if max_command_output_bytes < 1:
            raise ValueError("max command output bytes must be positive")
        self.repeat_limit = repeat_limit
        self.max_command_output_bytes = max_command_output_bytes
        self._signature: tuple[str, int | None, str] | None = None
        self._count = 0
        self._triggered = False
        self._bounded_context_seen = False

    def observe_line(self, raw_line: str) -> GuardDecision | None:
        if self._triggered:
            return None
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            self._reset()
            return None
        if not isinstance(event, dict):
            return None
        if _successful_context_call(event):
            self._bounded_context_seen = True
            self._reset()
            return None
        if event.get("type") != "item.completed":
            return None
        item = event.get("item")
        if not isinstance(item, dict):
            self._reset()
            return None
        if item.get("type") != "command_execution":
            if item.get("type") not in NON_TOOL_ITEM_TYPES:
                self._reset()
            return None

        observation = command_observation(item)
        output = _command_output(item)
        output_bytes = len(output.encode("utf-8"))
        if output_bytes > self.max_command_output_bytes:
            self._triggered = True
            return GuardDecision(
                reason=(
                    "run guard interrupted the turn after command output exceeded "
                    f"{self.max_command_output_bytes} bytes ({output_bytes} bytes): "
                    f"{observation['preview']}; full output remains in the private turn JSONL"
                ),
                command_fingerprint=observation["fingerprint"],
                output_fingerprint=hashlib.sha256(output.encode("utf-8")).hexdigest()[:16],
                count=1,
            )
        if self._bounded_context_seen and _is_broad_discovery(item):
            self._triggered = True
            return GuardDecision(
                reason=(
                    "run guard interrupted broad shell discovery after successful bounded "
                    f"context: {observation['preview']}; use search_repository or return a "
                    "concrete CONTEXT GAP to the Project Lead"
                ),
                command_fingerprint=observation["fingerprint"],
                output_fingerprint=hashlib.sha256(output.encode("utf-8")).hexdigest()[:16],
                count=1,
            )
        if not observation["failed"]:
            self._reset()
            return None
        output_fingerprint = hashlib.sha256(output.encode("utf-8")).hexdigest()[:16]
        signature = (
            observation["fingerprint"],
            observation["exit_code"],
            output_fingerprint,
        )
        if signature == self._signature:
            self._count += 1
        else:
            self._signature = signature
            self._count = 1
        if self._count < self.repeat_limit:
            return None

        self._triggered = True
        preview = observation["preview"]
        return GuardDecision(
            reason=(
                "run guard interrupted the turn after "
                f"{self._count} consecutive identical failed commands: {preview}"
            ),
            command_fingerprint=observation["fingerprint"],
            output_fingerprint=output_fingerprint,
            count=self._count,
        )

    def _reset(self) -> None:
        self._signature = None
        self._count = 0


def _command_output(item: dict[str, Any]) -> str:
    output = item.get("aggregated_output")
    if isinstance(output, str):
        return output
    output = item.get("output")
    return output if isinstance(output, str) else ""


def _successful_context_call(event: dict[str, Any]) -> bool:
    if event.get("type") == "item.completed":
        item = event.get("item")
        return bool(
            isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == CONTEXT_SERVER
            and item.get("status") == "completed"
        )
    if event.get("type") != "event_msg":
        return False
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "mcp_tool_call_end":
        return False
    invocation = payload.get("invocation")
    return bool(
        isinstance(invocation, dict)
        and invocation.get("server") == CONTEXT_SERVER
        and "Err" not in (payload.get("result") or {})
    )


def _is_broad_discovery(item: dict[str, Any]) -> bool:
    command = item.get("command")
    if not isinstance(command, str):
        return False
    return any(pattern.search(command) for pattern in BROAD_DISCOVERY)
