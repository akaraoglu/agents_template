"""Registry-backed runtime agent profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class AgentProfile:
    agent_id: str
    role_type: str
    runtime_mode: str
    purpose: str
    dm_surface: str
    allowed_surfaces: list[str]
    allowed_skills: list[str]
    allowed_services: list[str]
    policy_profile: str
    workspace_access: str
    zulip_visibility: str
    escalation_targets: list[str]
    memory_profile: dict[str, Any]


class AgentRegistryService:
    def __init__(self, path: str | Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[1]
        self.path = Path(path or (base_dir / "config" / "agent_registry.yaml"))
        self._raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}

    def get(self, agent_id: str) -> AgentProfile | None:
        defaults = self._raw.get("defaults", {})
        raw = (self._raw.get("agents") or {}).get(agent_id)
        if not raw:
            return None
        return AgentProfile(
            agent_id=agent_id,
            role_type=str(raw.get("role_type", "")),
            runtime_mode=str(raw.get("runtime_mode", "free_conversational")),
            purpose=str(raw.get("purpose", "")),
            dm_surface=str(raw.get("dm_surface", "")),
            allowed_surfaces=list(raw.get("allowed_surfaces", defaults.get("allowed_surfaces", []))),
            allowed_skills=list(raw.get("allowed_skills", [])),
            allowed_services=list(raw.get("allowed_services", [])),
            policy_profile=str(raw.get("policy_profile", defaults.get("policy_profile", "advisory_default"))),
            workspace_access=str(raw.get("workspace_access", defaults.get("workspace_access", "read_only"))),
            zulip_visibility=str(raw.get("zulip_visibility", defaults.get("zulip_visibility", "visible"))),
            escalation_targets=list(raw.get("escalation_targets", [])),
            memory_profile=dict(raw.get("memory_profile", {})),
        )

    def visible_agents(self) -> list[str]:
        return list(self._raw.get("default_visible_agents", []))
