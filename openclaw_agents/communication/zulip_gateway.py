"""Transport-oriented Zulip gateway for the foundation bootstrap scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openclaw_agents.agents import AgentEnvironment, AgentRegistryService, AgentRuntimeManager
from openclaw_agents.runtime_paths import RuntimePaths, resolve_runtime_root
from openclaw_agents.services import (
    AuditLogService,
    ArtifactRefService,
    CommandRunnerService,
    ConversationMemoryService,
    ExecutionStateService,
    InternalLoopService,
    PolicyService,
    ProjectProvisioningService,
    ProjectRegistryService,
    ProjectionEventService,
    ProjectMutationService,
    StateStore,
    WebResearchService,
    WorkingMemoryService,
    WorkspaceService,
)

from .dm_context_resolver import DMContextResolver
from .event_dedupe_store import EventDedupeStore
from .message_mapping_store import MessageMappingStore
from .ops_diagnostics import OpsDiagnostics
from .projection_helpers import ProjectionHelpers
from .topic_router import TopicRouter
from .zulip_plugin import ZulipRuntimePlugin


class ZulipGateway:
    """Implements Zulip transport handling and dispatch into runtime agents."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        plugin: ZulipRuntimePlugin | None = None,
        state_store: StateStore | None = None,
        mapping_store: MessageMappingStore | None = None,
        dedupe_store: EventDedupeStore | None = None,
        workspace_service: WorkspaceService | None = None,
        project_registry: ProjectRegistryService | None = None,
        project_provisioning: ProjectProvisioningService | None = None,
        artifact_ref_service: ArtifactRefService | None = None,
        conversation_memory: ConversationMemoryService | None = None,
        working_memory: WorkingMemoryService | None = None,
        command_runner: CommandRunnerService | None = None,
        web_research: WebResearchService | None = None,
        projection_event_service: ProjectionEventService | None = None,
        audit_log: AuditLogService | None = None,
        execution_state: ExecutionStateService | None = None,
        internal_loop: InternalLoopService | None = None,
        policy_service: PolicyService | None = None,
        mutation_service: ProjectMutationService | None = None,
        agent_registry: AgentRegistryService | None = None,
        agent_runtime: AgentRuntimeManager | None = None,
    ) -> None:
        self.code_root = Path(__file__).resolve().parents[1]
        self.runtime_root = Path(base_dir).resolve() if base_dir is not None else resolve_runtime_root()
        self.paths = RuntimePaths.from_root(self.runtime_root).ensure()
        self.base_dir = self.runtime_root
        self.plugin = plugin or ZulipRuntimePlugin()
        self.state_store = state_store or StateStore(path=self.paths.state_root / "state_store.json")
        self.mapping_store = mapping_store or MessageMappingStore(
            path=self.paths.state_root / "message_mappings.json"
        )
        self.dedupe_store = dedupe_store or EventDedupeStore(
            path=self.paths.state_root / "event_dedupe.json"
        )
        self.workspace_service = workspace_service or WorkspaceService(
            workspace_root=self.paths.projects_root
        )
        self.project_registry = project_registry or ProjectRegistryService(self.state_store)
        self.project_provisioning = project_provisioning or ProjectProvisioningService(
            self.state_store, self.workspace_service
        )
        self.artifact_ref_service = artifact_ref_service or ArtifactRefService(
            self.state_store, artifacts_root=self.paths.artifacts_root
        )
        self.conversation_memory = conversation_memory or ConversationMemoryService(
            path=self.paths.state_root / "conversation_memory.json"
        )
        self.working_memory = working_memory or WorkingMemoryService(
            path=self.paths.state_root / "working_memory.json"
        )
        self.audit_log = audit_log or AuditLogService(self.state_store)
        self.command_runner = command_runner or CommandRunnerService(
            allowed_root=self.paths.root,
            audit_log=self.audit_log,
        )
        self.web_research = web_research or WebResearchService()
        self.projection_event_service = projection_event_service or ProjectionEventService(
            path=self.paths.state_root / "projection_events.json"
        )
        self.execution_state = execution_state or ExecutionStateService(
            self.state_store,
            self.project_provisioning,
            self.projection_event_service,
        )
        self.internal_loop = internal_loop or InternalLoopService(
            self.state_store,
            self.workspace_service,
            self.execution_state,
            self.projection_event_service,
            audit_log=self.audit_log,
        )
        self.policy_service = policy_service or PolicyService(self.state_store, audit_log=self.audit_log)
        self.topic_router = TopicRouter(self.mapping_store)
        self.dm_context_resolver = DMContextResolver(self.project_registry)
        self.projection_helpers = ProjectionHelpers(
            self.plugin, self.mapping_store, self.topic_router
        )
        self.ops_diagnostics = OpsDiagnostics(
            self.plugin,
            self.dedupe_store,
            self.mapping_store,
            state_store=self.state_store,
            projection_event_service=self.projection_event_service,
            conversation_memory=self.conversation_memory,
            working_memory=self.working_memory,
            audit_log=self.audit_log,
            execution_state_service=self.execution_state,
            internal_loop_service=self.internal_loop,
        )
        self.mutation_service = mutation_service or ProjectMutationService(
            self.project_provisioning,
            self.artifact_ref_service,
            self.projection_event_service,
            audit_log=self.audit_log,
        )
        self.agent_registry = agent_registry or AgentRegistryService(
            path=self.code_root / "config" / "agent_registry.yaml"
        )
        self.agent_runtime = agent_runtime or AgentRuntimeManager(
            env=AgentEnvironment(
                state_store=self.state_store,
                project_registry=self.project_registry,
                project_provisioning=self.project_provisioning,
                workspace_service=self.workspace_service,
                artifact_ref_service=self.artifact_ref_service,
                policy_service=self.policy_service,
                mutation_service=self.mutation_service,
                projection_event_service=self.projection_event_service,
                conversation_memory=self.conversation_memory,
                working_memory=self.working_memory,
                command_runner=self.command_runner,
                web_research=self.web_research,
                dm_context_resolver=self.dm_context_resolver,
                topic_router=self.topic_router,
                registry=self.agent_registry,
                audit_log=self.audit_log,
                execution_state=self.execution_state,
                internal_loop=self.internal_loop,
            )
        )

    def process_raw_event(self, raw_event: dict[str, Any]) -> dict[str, Any]:
        return self.process_event(self.plugin.normalize_inbound(raw_event))

    def process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("source_type") == "queue_expired":
            return self._handle_queue_expired(event)

        event_id = str(event["event_id"])
        if self.dedupe_store.seen(event_id):
            return {"status": "duplicate_dropped", "event_id": event_id}

        self.dedupe_store.mark_processed(event_id)
        self.dedupe_store.write_checkpoint(event.get("queue_id"), event_id)
        self.state_store.record_event({"event_id": event_id, "source_type": event.get("source_type")})

        response = self.agent_runtime.handle_event(event)
        return self._publish_agent_response(event, response)

    def process_pending_runtime_work(self, *, limit: int = 5) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for event, response in self.agent_runtime.process_pending_handoffs(limit=limit):
            results.append(self._publish_agent_response(event, response))
        return results

    def run_maintenance(self) -> dict[str, int]:
        conversation_removed = self.conversation_memory.cleanup(max_age_hours=72)
        working_removed = self.working_memory.cleanup(max_age_hours=24)
        return {
            "conversation_sessions_removed": conversation_removed,
            "working_scopes_removed": working_removed,
        }

    def _handle_queue_expired(self, event: dict[str, Any]) -> dict[str, Any]:
        queue_owner_agent = event.get("queue_owner_agent")
        new_queue_id = self.plugin.recreate_queue(queue_owner_agent=queue_owner_agent)
        self.dedupe_store.reset_for_new_queue(new_queue_id, consumer_id=queue_owner_agent)
        self.state_store.record_event(
            {
                "event_id": event.get("event_id"),
                "source_type": "queue_expired",
                "new_queue_id": new_queue_id,
                "queue_owner_agent": queue_owner_agent,
            }
        )
        return {"status": "queue_recovered", "new_queue_id": new_queue_id}

    def _publish_agent_response(self, event: dict[str, Any], response: Any) -> dict[str, Any]:
        message_ids: list[int] = []
        project_id: str | None = None
        for message in response.outbound_messages:
            project_id = project_id or message.project_id
            if message.target_type == "dm":
                result = self.plugin.send_dm(
                    target_email=message.target_email or event.get("sender_email", ""),
                    content_markdown=message.content_markdown,
                    project_id=message.project_id,
                    task_id=message.task_id,
                    message_kind=message.message_kind,
                    sender_agent=message.sender_agent,
                )
                self.mapping_store.link_message(
                    result.message_id,
                    project_id=message.project_id,
                    task_id=message.task_id,
                    topic_name=None,
                    message_kind=message.message_kind,
                )
                message_ids.append(result.message_id)
            else:
                result = self.plugin.reply_in_topic(
                    stream_name=message.stream_name or event.get("stream_name", "projects"),
                    topic_name=message.topic_name or event.get("topic_name", ""),
                    content_markdown=message.content_markdown,
                    project_id=message.project_id,
                    task_id=message.task_id,
                    message_kind=message.message_kind,
                    sender_agent=message.sender_agent,
                )
                self.mapping_store.link_message(
                    result.message_id,
                    project_id=message.project_id,
                    task_id=message.task_id,
                    topic_name=message.topic_name,
                    message_kind=message.message_kind,
                )
                message_ids.append(result.message_id)

        for dispatch in response.projection_dispatches:
            rendered = self.projection_helpers.post_projection_event(
                dispatch.event,
                sender_agent=dispatch.sender_agent,
            )
            project_id = project_id or dispatch.event.get("project_id")
            if project_id:
                project = self.state_store.get_project(project_id)
                if project:
                    self.mapping_store.set_primary_topic(
                        project_id,
                        stream_name=project.get("canonical_stream", "projects"),
                        topic_name=project.get("canonical_topic", f"project/{project_id}"),
                    )
            message_ids.append(rendered["message_id"])

        if not message_ids:
            return {
                "status": response.status,
                "project_id": project_id,
                "message_ids": [],
            }
        return {
            "status": "dm_replied" if event.get("conversation_surface") == "dm" else response.status,
            "project_id": project_id,
            "message_ids": message_ids,
            "message_id": message_ids[-1],
        }
