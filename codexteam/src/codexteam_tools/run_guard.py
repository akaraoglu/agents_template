from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .turn_metrics import NON_TOOL_ITEM_TYPES, command_observation


DEFAULT_REPEAT_LIMIT = 3


@dataclass(frozen=True)
class GuardDecision:
    reason: str
    command_fingerprint: str
    output_fingerprint: str
    count: int


class ExactFailedRepeatGuard:
    """Detect consecutive identical failed commands without intervening tool evidence."""

    def __init__(self, *, repeat_limit: int = DEFAULT_REPEAT_LIMIT) -> None:
        if repeat_limit < 2:
            raise ValueError("repeat limit must be at least 2")
        self.repeat_limit = repeat_limit
        self._signature: tuple[str, int | None, str] | None = None
        self._count = 0
        self._triggered = False

    def observe_line(self, raw_line: str) -> GuardDecision | None:
        if self._triggered:
            return None
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            self._reset()
            return None
        if not isinstance(event, dict) or event.get("type") != "item.completed":
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
        if not observation["failed"]:
            self._reset()
            return None
        output = _command_output(item)
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
