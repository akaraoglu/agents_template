"""Ops diagnostics skill wrapper."""

from __future__ import annotations

from typing import Any

from openclaw_agents.communication.ops_diagnostics import OpsDiagnostics


class ZulipOpsSkill:
    def __init__(self, diagnostics: OpsDiagnostics) -> None:
        self.diagnostics = diagnostics

    def snapshot(self) -> dict[str, Any]:
        return self.diagnostics.diagnostics_snapshot()

