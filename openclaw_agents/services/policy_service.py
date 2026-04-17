"""Profile-aware policy evaluation and confirmation handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openclaw_agents.communication.approval_helpers import ApprovalHelpers
from openclaw_agents.services.audit_log import AuditLogService
from openclaw_agents.services.state_store import StateStore


@dataclass(slots=True)
class ConfirmationResolution:
    matched: bool
    status: str | None = None
    approval: dict[str, Any] | None = None
    message: str | None = None


@dataclass(slots=True)
class PolicyDecision:
    action_kind: str
    disposition: str
    reason: str
    message: str | None = None
    escalation_target: str | None = None

    @property
    def decision(self) -> str:
        return self.disposition

    @property
    def requires_confirmation(self) -> bool:
        return self.disposition == "needs_confirmation"


class PolicyService:
    _READ_ACTIONS = {
        "read_project_state",
        "read_workspace",
        "read_projection_events",
        "read_execution_handoffs",
        "read_execution_state",
        "web_research",
        "conversation",
    }

    _TOOL_ACTIONS = {
        "list_open_projects": "read_project_state",
        "get_project_context": "read_project_state",
        "get_project_management_surface": "read_project_state",
        "list_blocked_projects": "read_project_state",
        "read_project_file": "read_workspace",
        "list_projection_events": "read_projection_events",
        "list_execution_handoffs": "read_execution_handoffs",
        "get_pending_execution_handoff": "read_execution_handoffs",
        "get_execution_state": "read_execution_state",
        "web_search": "web_research",
        "fetch_url": "web_research",
        "research_brief": "web_research",
        "write_project_file": "workspace_write",
        "run_workspace_command": "workspace_command",
        "create_project_surface": "direct_project_mutation",
        "update_project_state": "direct_project_mutation",
        "start_execution_handoff": "execution_handoff_consume",
        "report_execution_blocker": "execution_status_update",
        "report_execution_verification": "verification_report",
    }

    def __init__(self, state_store: StateStore, audit_log: AuditLogService | None = None) -> None:
        self.helpers = ApprovalHelpers(state_store)
        self.audit_log = audit_log

    def classify_action(self, raw_text: str) -> str:
        return self.helpers.classify_action(raw_text)

    def request_confirmation(self, owner_agent: str, requester_email: str, change: dict[str, Any]) -> dict[str, Any]:
        return self.helpers.request_confirmation(owner_agent, requester_email, change)

    def resolve_confirmation(
        self,
        *,
        raw_text: str,
        requester_email: str,
        owner_agent: str,
    ) -> ConfirmationResolution:
        approval_id, decision = self.helpers.parse_confirmation_text(raw_text)
        if not decision:
            return ConfirmationResolution(matched=False)

        pending = self.helpers.list_pending(requester_email, owner_agent)
        if not pending:
            return ConfirmationResolution(matched=True, message="There is no pending confirmation for your account.")

        target = None
        if approval_id:
            target = next((row for row in pending if row["approval_id"] == approval_id), None)
            if not target:
                return ConfirmationResolution(
                    matched=True,
                    message=f"Approval ID {approval_id} was not found in pending requests.",
                )
        elif len(pending) == 1:
            target = pending[0]
        else:
            ids = ", ".join(row["approval_id"] for row in pending)
            return ConfirmationResolution(
                matched=True,
                message=f"Multiple approvals are pending. Please include one ID: {ids}",
            )

        recorded = self.helpers.record_confirmation(
            target["approval_id"], result=decision, confirmer_email=requester_email
        )
        return ConfirmationResolution(matched=True, status=decision, approval=recorded)

    def evaluate_surface_access(self, profile: Any, *, surface: str) -> PolicyDecision:
        normalized_surface = "project_topic" if surface and surface not in {"dm", "control"} else surface
        if normalized_surface in set(profile.allowed_surfaces):
            return self._decision(profile.agent_id, "surface_access", "allow", f"{surface} allowed")
        message = (
            "I operate on execution handoffs and project execution state. "
            "Project changes and human-facing planning should go through AgentSmith."
            if profile.agent_id == "niaobe"
            else f"{profile.agent_id} is not enabled on the {surface} surface."
        )
        return self._decision(
            profile.agent_id,
            "surface_access",
            "deny",
            f"{surface} is outside the allowed surfaces",
            message=message,
        )

    def evaluate_tool_call(
        self,
        *,
        profile: Any,
        tool_name: str,
        arguments: dict[str, Any],
        surface: str,
    ) -> PolicyDecision:
        action_kind = self._TOOL_ACTIONS.get(tool_name, "unknown_tool")
        return self.evaluate_action(
            profile=profile,
            action_kind=action_kind,
            payload={"tool_name": tool_name, "arguments": arguments},
            surface=surface,
        )

    def evaluate_action_intent(
        self,
        *,
        profile: Any,
        intent_kind: str,
        request: Any,
        payload: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        return self.evaluate_action(
            profile=profile,
            action_kind=intent_kind,
            payload=payload or {},
            surface=("project_topic" if getattr(request, "conversation_surface", "dm") not in {"dm", "control"} else getattr(request, "conversation_surface", "dm")),
        )

    def evaluate_action(
        self,
        *,
        profile: Any,
        action_kind: str,
        payload: dict[str, Any] | None = None,
        surface: str | None = None,
    ) -> PolicyDecision:
        payload = payload or {}
        surface = surface or "dm"
        normalized_surface = "project_topic" if surface not in {"dm", "control"} else surface
        if normalized_surface not in set(profile.allowed_surfaces):
            return self._decision(
                profile.agent_id,
                action_kind,
                "deny",
                f"surface '{normalized_surface}' not allowed",
                message=f"{profile.agent_id} cannot operate on the {normalized_surface} surface.",
            )

        policy_profile = str(profile.policy_profile)
        if action_kind in self._READ_ACTIONS:
            return self._decision(profile.agent_id, action_kind, "allow", "read or research action allowed")

        if policy_profile == "neo_executive":
            if action_kind in {"workspace_write", "workspace_command", "direct_project_mutation", "execution_status_update"}:
                return self._decision(profile.agent_id, action_kind, "allow", "executive policy permits action")
            if action_kind in {"project_mutation_request", "escalate_to_agent_smith", "verification_report"}:
                return self._decision(profile.agent_id, action_kind, "allow", "executive policy permits structured action")

        if policy_profile == "project_manager":
            if action_kind == "project_mutation_request":
                return self._decision(
                    profile.agent_id,
                    action_kind,
                    "needs_confirmation",
                    "project-affecting mutations require confirmation",
                )
            if action_kind in {"workspace_write", "workspace_command", "direct_project_mutation"}:
                return self._decision(
                    profile.agent_id,
                    action_kind,
                    "deny",
                    "project manager profile cannot directly execute or mutate through tools",
                    message="I can propose the project change, but the system must confirm it before applying anything.",
                )
            if action_kind in {"escalate_to_niaobe", "project_projection"}:
                return self._decision(profile.agent_id, action_kind, "allow", "managerial coordination is allowed")

        if policy_profile == "bounded_orchestrator":
            if action_kind in {"execution_handoff_consume", "execution_status_update", "verification_report"}:
                return self._decision(profile.agent_id, action_kind, "allow", "bounded execution action allowed")
            if action_kind == "escalate_to_agent_smith":
                return self._decision(
                    profile.agent_id,
                    action_kind,
                    "escalate",
                    "execution blockers should escalate to AgentSmith",
                    escalation_target="agent_smith",
                )
            if action_kind == "workspace_command":
                return self._decision(profile.agent_id, action_kind, "allow", "bounded execution command allowed")
            if action_kind in {"direct_project_mutation", "project_mutation_request"}:
                return self._decision(
                    profile.agent_id,
                    action_kind,
                    "deny",
                    "bounded execution profile cannot mutate project state directly",
                    message="I can report execution progress and blockers, but project changes must go through AgentSmith.",
                )

        if policy_profile == "internal_orchestrator":
            if action_kind in {"execution_blocker", "verification_report", "escalate_to_agent_smith"}:
                disposition = "escalate" if action_kind == "escalate_to_agent_smith" else "allow"
                target = "agent_smith" if action_kind == "escalate_to_agent_smith" else None
                return self._decision(
                    profile.agent_id,
                    action_kind,
                    disposition,
                    "internal orchestration action allowed",
                    escalation_target=target,
                )
            if action_kind in {"workspace_command", "workspace_write", "direct_project_mutation", "project_mutation_request"}:
                return self._decision(
                    profile.agent_id,
                    action_kind,
                    "deny",
                    "internal orchestrator does not perform direct workspace or project mutations",
                )

        if policy_profile == "internal_planner":
            if action_kind in {"execution_blocker", "escalate_to_agent_smith"}:
                disposition = "escalate" if action_kind == "escalate_to_agent_smith" else "allow"
                target = "agent_smith" if action_kind == "escalate_to_agent_smith" else None
                return self._decision(
                    profile.agent_id,
                    action_kind,
                    disposition,
                    "internal planner escalation allowed",
                    escalation_target=target,
                )
            if action_kind in {"workspace_command", "workspace_write", "direct_project_mutation", "project_mutation_request", "verification_report"}:
                return self._decision(profile.agent_id, action_kind, "deny", "internal planner is read-only")

        if policy_profile == "internal_implementer":
            if action_kind in {"workspace_command", "workspace_write", "execution_blocker"}:
                return self._decision(profile.agent_id, action_kind, "allow", "internal implementer action allowed")
            if action_kind in {"direct_project_mutation", "project_mutation_request", "verification_report"}:
                return self._decision(profile.agent_id, action_kind, "deny", "internal implementer cannot finalize project or verification state")

        if policy_profile == "internal_tester":
            if action_kind in {"workspace_command", "execution_blocker", "verification_report"}:
                return self._decision(profile.agent_id, action_kind, "allow", "internal tester action allowed")
            if action_kind in {"workspace_write", "direct_project_mutation", "project_mutation_request"}:
                return self._decision(profile.agent_id, action_kind, "deny", "internal tester cannot mutate project state directly")

        if action_kind == "project_mutation_request":
            return self._decision(profile.agent_id, action_kind, "needs_confirmation", "default mutation confirmation")
        if action_kind in {"workspace_command", "workspace_write", "direct_project_mutation"}:
            return self._decision(profile.agent_id, action_kind, "deny", "default policy denies direct side effects")
        if action_kind.startswith("escalate_"):
            target = action_kind.removeprefix("escalate_to_")
            return self._decision(profile.agent_id, action_kind, "escalate", "default escalation", escalation_target=target)
        return self._decision(profile.agent_id, action_kind, "deny", "unsupported action under current policy")

    def _decision(
        self,
        actor_agent: str,
        action_kind: str,
        disposition: str,
        reason: str,
        *,
        message: str | None = None,
        escalation_target: str | None = None,
    ) -> PolicyDecision:
        if self.audit_log is not None:
            self.audit_log.record(
                action_type="policy_decision",
                actor_agent=actor_agent,
                outcome=disposition,
                payload={"action_kind": action_kind, "reason": reason, "message": message},
            )
        return PolicyDecision(
            action_kind=action_kind,
            disposition=disposition,
            reason=reason,
            message=message,
            escalation_target=escalation_target,
        )
