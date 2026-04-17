"""Minimal Zulip/runtime diagnostics skill surface."""

from __future__ import annotations

from typing import Any

from .event_dedupe_store import EventDedupeStore
from .message_mapping_store import MessageMappingStore
from openclaw_agents.services.audit_log import AuditLogService
from openclaw_agents.services.conversation_memory import ConversationMemoryService
from openclaw_agents.services.execution_state import ExecutionStateService
from openclaw_agents.services.internal_loop import InternalLoopService
from openclaw_agents.services.projection_events import ProjectionEventService
from openclaw_agents.services.state_store import StateStore
from openclaw_agents.services.working_memory import WorkingMemoryService
from .zulip_plugin import ZulipRuntimePlugin


class OpsDiagnostics:
    def __init__(
        self,
        plugin: ZulipRuntimePlugin,
        dedupe_store: EventDedupeStore,
        mapping_store: MessageMappingStore,
        state_store: StateStore,
        projection_event_service: ProjectionEventService,
        conversation_memory: ConversationMemoryService,
        working_memory: WorkingMemoryService,
        audit_log: AuditLogService,
        execution_state_service: ExecutionStateService,
        internal_loop_service: InternalLoopService,
    ) -> None:
        self.plugin = plugin
        self.dedupe_store = dedupe_store
        self.mapping_store = mapping_store
        self.state_store = state_store
        self.projection_event_service = projection_event_service
        self.conversation_memory = conversation_memory
        self.working_memory = working_memory
        self.audit_log = audit_log
        self.execution_state_service = execution_state_service
        self.internal_loop_service = internal_loop_service

    def check_bot_status(self) -> dict[str, Any]:
        return self.plugin.health()

    def inspect_checkpoint_state(self) -> dict[str, Any]:
        return self.dedupe_store.get_checkpoint()

    def inspect_message_mappings(self) -> dict[str, Any]:
        return self.mapping_store.dump()

    def diagnostics_snapshot(self) -> dict[str, Any]:
        mappings = self.mapping_store.dump()
        handoffs = self.state_store.list_handoffs()
        execution_states = self.execution_state_service.list_states()
        internal_runs = self.internal_loop_service.list_runs()
        return {
            "plugin": self.plugin.health(),
            "checkpoint": self.dedupe_store.get_checkpoint(),
            "processed_events": self.dedupe_store.processed_count(),
            "mapped_messages": len(mappings.get("message_links", {})),
            "project_topics": len(mappings.get("project_topics", {})),
            "projects": len(self.state_store.list_projects()),
            "pending_approvals": len(self.state_store.list_pending_approvals()),
            "handoffs": {
                "total": len(handoffs),
                "pending": len([row for row in handoffs if row.get("status") == "PENDING"]),
                "in_progress": len([row for row in handoffs if row.get("status") == "IN_PROGRESS"]),
                "blocked": len([row for row in handoffs if row.get("status") == "BLOCKED"]),
            },
            "execution_states": {
                "total": len(execution_states),
                "started": len([row for row in execution_states if row.get("status") == "IN_PROGRESS"]),
                "in_progress": len([row for row in execution_states if row.get("status") == "IN_PROGRESS"]),
                "blocked": len([row for row in execution_states if row.get("status") == "BLOCKED"]),
                "verification_reported": len(
                    [row for row in execution_states if row.get("status") == "VERIFICATION_REPORTED"]
                ),
            },
            "projection_events": len(self.projection_event_service.list_events()),
            "internal_runs": {
                "total": len(internal_runs),
                "active": len([row for row in internal_runs if row.get("status") == "ACTIVE"]),
                "blocked": len([row for row in internal_runs if row.get("status") == "BLOCKED"]),
                "completed": len([row for row in internal_runs if row.get("status") == "COMPLETED"]),
            },
            "audit_entries": len(self.state_store.list_audit_entries()),
            "audit_tail": self.audit_log.tail(limit=5),
            "conversation_memory": self.conversation_memory.stats(),
            "working_memory": self.working_memory.stats(),
        }
