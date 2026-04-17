"""Prompt-driven runtime manager for visible agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openclaw_agents.communication.dm_context_resolver import DMContextResolver
from openclaw_agents.communication.topic_router import TopicRouter
from openclaw_agents.services import (
    AuditLogService,
    ArtifactRefService,
    CommandRunnerService,
    ConversationMemoryService,
    ExecutionStateService,
    InternalLoopService,
    PolicyService,
    ProjectMutationService,
    ProjectProvisioningService,
    ProjectRegistryService,
    ProjectionEventService,
    StateStore,
    WebResearchService,
    WorkingMemoryService,
    WorkspaceService,
)

from .contracts import (
    ActionIntent,
    AgentTurnRequest,
    AgentTurnResponse,
    OutboundMessage,
    ProjectionDispatch,
    ToolCall,
    ToolResult,
)
from .model_client import ModelClient, ModelClientError, ModelMapService, OllamaModelClient
from .prompt_loader import PromptLoader
from .registry import AgentProfile, AgentRegistryService
from .tool_registry import ToolRegistry


@dataclass(slots=True)
class AgentEnvironment:
    state_store: StateStore
    project_registry: ProjectRegistryService
    project_provisioning: ProjectProvisioningService
    workspace_service: WorkspaceService
    artifact_ref_service: ArtifactRefService
    policy_service: PolicyService
    mutation_service: ProjectMutationService
    projection_event_service: ProjectionEventService
    conversation_memory: ConversationMemoryService
    working_memory: WorkingMemoryService
    command_runner: CommandRunnerService
    web_research: WebResearchService
    dm_context_resolver: DMContextResolver
    topic_router: TopicRouter
    registry: AgentRegistryService
    audit_log: AuditLogService
    execution_state: ExecutionStateService
    internal_loop: InternalLoopService


class BaseRuntimeAgent:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    def handle_turn(self, request: AgentTurnRequest, env: AgentEnvironment) -> AgentTurnResponse:
        raise NotImplementedError

    @staticmethod
    def _reply_to_surface(
        request: AgentTurnRequest,
        *,
        sender_agent: str,
        content: str,
        project_id: str | None = None,
        task_id: str | None = None,
        message_kind: str = "consultation_reply",
    ) -> AgentTurnResponse:
        if request.conversation_surface == "control":
            return AgentTurnResponse(
                internal_output={
                    "reply": content,
                    "sender_agent": sender_agent,
                    "project_id": project_id,
                    "task_id": task_id,
                    "message_kind": message_kind,
                }
            )
        target_type = "dm" if request.conversation_surface == "dm" else "stream"
        return AgentTurnResponse(
            outbound_messages=[
                OutboundMessage(
                    target_type=target_type,
                    sender_agent=sender_agent,
                    target_email=request.sender_email if target_type == "dm" else None,
                    stream_name=request.stream_name if target_type == "stream" else None,
                    topic_name=request.topic_name if target_type == "stream" else None,
                    content_markdown=content,
                    project_id=project_id,
                    task_id=task_id,
                    message_kind=message_kind,
                )
            ]
        )


class PromptDrivenRuntimeAgent(BaseRuntimeAgent):
    def __init__(
        self,
        agent_id: str,
        *,
        prompt_loader: PromptLoader,
        model_map: ModelMapService,
        model_client: ModelClient | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_rounds: int = 3,
    ) -> None:
        super().__init__(agent_id)
        self.prompt_loader = prompt_loader
        self.model_map = model_map
        self.model_client = model_client or OllamaModelClient()
        self.tool_registry = tool_registry or ToolRegistry()
        self.max_tool_rounds = max_tool_rounds

    def handle_turn(self, request: AgentTurnRequest, env: AgentEnvironment) -> AgentTurnResponse:
        profile = env.registry.get(self.agent_id)
        if profile is None:
            return self._reply_to_surface(
                request,
                sender_agent=self.agent_id,
                content="This agent profile is not registered.",
            )

        prompt_text = self.prompt_loader.load(self.agent_id)
        tools = self.tool_registry.available_tools(profile)
        tool_results: list[ToolResult] = []
        seen_tool_calls: set[tuple[str, str]] = set()
        last_error: str | None = None

        for _ in range(self.max_tool_rounds + 1):
            payload = self._invoke_brain(
                profile=profile,
                prompt_text=prompt_text,
                request=request,
                tools=tools,
                tool_results=tool_results,
            )
            if payload is None:
                last_error = "model_unavailable"
                break

            parsed_calls = self._parse_tool_calls(payload.get("tool_calls"))
            if parsed_calls:
                executed_any = False
                for call in parsed_calls:
                    signature = (call.tool_name, json.dumps(call.arguments, sort_keys=True))
                    if signature in seen_tool_calls:
                        continue
                    seen_tool_calls.add(signature)
                    tool_results.append(
                        self.tool_registry.execute(call, profile=profile, request=request, env=env)
                    )
                    executed_any = True
                if executed_any:
                    continue

            reply = str(payload.get("reply") or "").strip()
            action_intent = self._parse_action_intent(payload.get("action_intent"))
            working_memory = payload.get("working_memory")
            if not isinstance(working_memory, dict):
                working_memory = request.working_memory

            if not reply:
                if tool_results:
                    reply = self._reply_from_tool_results(profile, request, tool_results)
                else:
                    reply = self._default_free_reply(profile)

            return self._build_response(
                request,
                reply=reply,
                working_memory=working_memory,
                action_intent=action_intent,
                tool_results=tool_results,
            )

        return self._fallback_response(request, env, last_error=last_error)

    def _invoke_brain(
        self,
        *,
        profile: AgentProfile,
        prompt_text: str,
        request: AgentTurnRequest,
        tools: list[Any],
        tool_results: list[ToolResult],
    ) -> dict[str, Any] | None:
        spec = self.model_map.get(self.agent_id)
        system_prompt = self._build_system_prompt(profile, prompt_text, model_name=spec.model)
        user_payload = {
            "conversation_surface": request.conversation_surface,
            "sender_email": request.sender_email,
            "raw_content": request.raw_content,
            "project_context": request.project_context,
            "project_resolution": request.project_resolution,
            "execution_context": request.execution_context,
            "recent_conversation": request.recent_conversation[-8:],
            "working_memory": request.working_memory,
            "tool_results": [self._tool_result_payload(result) for result in tool_results],
            "available_tools": [tool.as_prompt_payload() for tool in tools],
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, indent=2, sort_keys=True)},
        ]
        try:
            if hasattr(self.model_client, "complete_json"):
                return self.model_client.complete_json(spec=spec, messages=messages)
            if hasattr(self.model_client, "generate_json"):
                return self.model_client.generate_json(
                    target=spec,
                    system_prompt=system_prompt,
                    user_prompt=messages[-1]["content"],
                )
            raise ModelClientError("Model client does not implement a supported structured interface")
        except ModelClientError:
            return None

    def _build_system_prompt(self, profile: AgentProfile, prompt_text: str, *, model_name: str) -> str:
        think_prefix = "<|think|>\n" if model_name.startswith("gemma4:") else ""
        capability_map = {
            "neo": (
                "- Neo may directly research, execute commands, write project files, and mutate project state when the user explicitly asks or when it is necessary to complete the requested task.\n"
            ),
            "agent_smith": (
                "- AgentSmith may discuss scope, blockers, priorities, milestones, backlog, status, and closeout freely.\n"
                "- When a project-affecting change is requested, AgentSmith should usually return an action_intent of kind project_mutation_request with a structured payload.\n"
                "- Valid project mutation payload fields include action, project_ref, name, summary, status, milestones, next_actions, backlog_items, blockers, and decisions.\n"
                "- Confirmation is still handled outside the reply.\n"
            ),
            "niaobe": (
                "- Niaobe is bounded to approved execution handoffs and execution-state reporting.\n"
                "- Use execution-handoff and execution-state tools before answering about progress.\n"
                "- Do not negotiate project scope or mutate project plans directly.\n"
                "- Escalate project-level blockers to AgentSmith through blocker reporting.\n"
            ),
            "morpheus": (
                "- Morpheus owns the internal software-development loop after an approved execution handoff is active.\n"
                "- Focus on orchestration clarity, delivery risk, and what the next internal worker needs to know.\n"
                "- If execution cannot proceed, return an action_intent with kind execution_blocker and a payload containing blocker and next_step.\n"
            ),
            "planner": (
                "- Planner produces the ordered execution plan, checkpoints, and verification gates.\n"
                "- Keep the plan concise and grounded in the active handoff and project surface.\n"
                "- If the work cannot proceed, return an action_intent with kind execution_blocker.\n"
            ),
            "implementer": (
                "- Implementer produces the concrete execution work package and may use bounded workspace tools on the control surface.\n"
                "- If execution is blocked, return an action_intent with kind execution_blocker and a payload containing blocker and next_step.\n"
            ),
            "tester": (
                "- Tester assesses whether the execution package is ready for verification sign-off.\n"
                "- If verification is ready, return an action_intent with kind verification_report and a payload containing report_summary and optionally report_body.\n"
                "- If testing cannot proceed, return an action_intent with kind execution_blocker.\n"
            ),
        }
        capability_rule = capability_map.get(self.agent_id, "")
        return (
            f"{think_prefix}{prompt_text}\n\n"
            f"Agent profile:\n"
            f"- agent_id: {profile.agent_id}\n"
            f"- runtime_mode: {profile.runtime_mode}\n"
            f"- policy_profile: {profile.policy_profile}\n"
            f"- allowed_surfaces: {', '.join(profile.allowed_surfaces)}\n"
            f"- allowed_skills: {', '.join(profile.allowed_skills)}\n\n"
            "You are operating inside the OpenClaw agent runtime.\n"
            "Be broadly conversational rather than command-driven.\n"
            "Use tools when you need authoritative project, execution, or workspace data.\n"
            "Do not claim that a mutation was applied unless the system confirms it separately.\n"
            "If project context is ambiguous, ask a concise follow-up question.\n"
            "When thinking is enabled, keep your internal thought channel separate from the final JSON answer.\n"
            "When research tool outputs include sources or citations, ground the answer in those sources and cite them inline using markers like [1], [2].\n"
            "On the control surface, your reply is an internal runtime summary and is not sent directly to Zulip unless a separate system action projects it.\n"
            "Return a single JSON object with this shape:\n"
            "{\n"
            '  "reply": "natural language reply to the human",\n'
            '  "tool_calls": [{"tool_name": "name", "arguments": {}}],\n'
            '  "action_intent": {"kind": "none|project_mutation_request|escalate_to_agent_smith|execution_blocker|verification_report", "summary": "", "payload": {}},\n'
            '  "working_memory": {}\n'
            "}\n"
            "Rules:\n"
            "- If you need tools first, return tool_calls and leave reply empty.\n"
            "- If you already have enough information, return reply and an empty tool_calls list.\n"
            f"{capability_rule}"
            "- Never mention the JSON protocol.\n"
        )

    @staticmethod
    def _parse_tool_calls(raw_calls: Any) -> list[ToolCall]:
        parsed: list[ToolCall] = []
        if not isinstance(raw_calls, list):
            return parsed
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            tool_name = str(raw.get("tool_name") or raw.get("name") or "").strip()
            if not tool_name:
                continue
            arguments = raw.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            parsed.append(ToolCall(tool_name=tool_name, arguments=arguments))
        return parsed

    @staticmethod
    def _parse_action_intent(raw_intent: Any) -> ActionIntent | None:
        if not isinstance(raw_intent, dict):
            return None
        kind = str(raw_intent.get("kind") or "none").strip()
        if not kind or kind == "none":
            return None
        payload = raw_intent.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        return ActionIntent(kind=kind, summary=str(raw_intent.get("summary") or ""), payload=payload)

    def _build_response(
        self,
        request: AgentTurnRequest,
        *,
        reply: str,
        working_memory: dict[str, Any],
        action_intent: ActionIntent | None,
        tool_results: list[ToolResult],
    ) -> AgentTurnResponse:
        project_id = self._project_id_from_tool_results(tool_results) or request.project_resolution.get("project_id")
        response = self._reply_to_surface(
            request,
            sender_agent=self.agent_id,
            content=reply,
            project_id=project_id,
        )
        response.working_memory = working_memory
        response.tool_results = tool_results
        if action_intent is not None:
            response.action_intents.append(action_intent)
        response.projection_dispatches = self._projection_dispatches_from_tool_results(tool_results)
        return response

    def _projection_dispatches_from_tool_results(self, tool_results: list[ToolResult]) -> list[ProjectionDispatch]:
        dispatches: list[ProjectionDispatch] = []
        seen: set[str] = set()
        for result in tool_results:
            events = result.output.get("projection_events", []) if isinstance(result.output, dict) else []
            if not isinstance(events, list):
                continue
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_id = str(event.get("event_id") or "")
                if event_id and event_id in seen:
                    continue
                if event_id:
                    seen.add(event_id)
                dispatches.append(ProjectionDispatch(event=event, sender_agent=self.agent_id))
        return dispatches

    @staticmethod
    def _project_id_from_tool_results(tool_results: list[ToolResult]) -> str | None:
        for result in reversed(tool_results):
            output = result.output if isinstance(result.output, dict) else {}
            project = output.get("project")
            if isinstance(project, dict) and project.get("id"):
                return str(project["id"])
            project_id = output.get("project_id")
            if project_id:
                return str(project_id)
        return None

    @staticmethod
    def _tool_result_payload(result: ToolResult) -> dict[str, Any]:
        return {
            "tool_name": result.tool_name,
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
        }

    def _reply_from_tool_results(
        self,
        profile: AgentProfile,
        request: AgentTurnRequest,
        tool_results: list[ToolResult],
    ) -> str:
        last = tool_results[-1]
        if last.tool_name == "list_open_projects":
            projects = last.output.get("projects", [])
            if not projects:
                return "There are no active projects right now."
            lines = [f"- {row.get('name', row.get('id'))} [{row.get('status', 'NEW')}]" for row in projects]
            return "Here are the active projects:\n" + "\n".join(lines)
        if last.tool_name == "get_project_context":
            if last.output.get("ambiguous"):
                return str(last.output.get("follow_up_question") or "Which project should I use?")
            project = (last.output.get("project") or {}) if last.ok else {}
            if project:
                return (
                    f"{project.get('name', project.get('id'))} [{project.get('status', 'NEW')}]. "
                    f"Summary: {project.get('summary', 'No summary yet.')}"
                )
        if last.tool_name == "get_project_management_surface":
            if last.output.get("ambiguous"):
                return str(last.output.get("follow_up_question") or "Which project should I use?")
            project = (last.output.get("project") or {}) if last.ok else {}
            if project:
                milestones = project.get("milestones", [])[:3]
                backlog = project.get("backlog_items", [])[:3]
                blockers = project.get("blockers", [])[:2]
                parts = [
                    f"{project.get('name', project.get('id'))} [{project.get('status', 'NEW')}].",
                    f"Summary: {project.get('summary', 'No summary yet.')}",
                ]
                if milestones:
                    parts.append("Milestones: " + "; ".join(str(item) for item in milestones))
                if backlog:
                    parts.append("Backlog: " + "; ".join(str(item) for item in backlog))
                if blockers:
                    parts.append("Blockers: " + "; ".join(str(item) for item in blockers))
                return " ".join(parts)
        if last.tool_name == "research_brief":
            citations = list(last.output.get("citations", []))
            sources = list(last.output.get("sources", []))
            if not sources:
                return "I searched the web but did not get enough usable sources back."
            bullets = []
            for source in sources[:3]:
                citation_index = source.get("citation_index", len(bullets) + 1)
                title = source.get("title", "Untitled source")
                domain = source.get("domain", "")
                snippet = source.get("search_snippet") or source.get("content_excerpt", "")
                snippet = str(snippet).strip()
                if len(snippet) > 180:
                    snippet = snippet[:177] + "..."
                bullets.append(f"- [{citation_index}] {title} ({domain}): {snippet}")
            reply = "I researched this and here are the strongest sources I found:\n" + "\n".join(bullets)
            if citations:
                reply += "\n\nSources:\n" + "\n".join(f"- {citation}" for citation in citations[:3])
            return reply
        if last.tool_name == "fetch_url" and last.ok:
            title = last.output.get("title") or last.output.get("domain") or last.output.get("url")
            excerpt = str(last.output.get("content", "")).strip()
            if len(excerpt) > 220:
                excerpt = excerpt[:217] + "..."
            return f"I fetched {title}. Key excerpt: {excerpt}"
        if last.tool_name == "get_pending_execution_handoff":
            handoff = last.output.get("handoff") or {}
            if handoff:
                return (
                    f"I found handoff {handoff.get('handoff_id')} for {handoff.get('project_name', handoff.get('project_id'))}. "
                    f"Status: {handoff.get('status', 'PENDING')}. Summary: {handoff.get('summary', 'No summary available.')}"
                )
        if last.tool_name == "get_execution_state":
            state = last.output.get("execution_state") or {}
            if state:
                blockers = state.get("blockers") or []
                suffix = f" Blockers: {', '.join(str(item) for item in blockers)}." if blockers else ""
                return (
                    f"Execution state for {state.get('project_name', state.get('project_id'))} is {state.get('status', 'PENDING')}."
                    f"{suffix}"
                )
        if last.tool_name == "start_execution_handoff":
            handoff = last.output.get("handoff") or {}
            if handoff:
                return (
                    f"I started execution for {handoff.get('project_name', handoff.get('project_id'))} "
                    f"under handoff {handoff.get('handoff_id')}."
                )
        if last.tool_name == "report_execution_blocker":
            project = last.output.get("project") or {}
            state = last.output.get("execution_state") or {}
            blocker = (state.get("blockers") or ["the reported blocker"])[-1]
            if project:
                return (
                    f"I reported an execution blocker for {project.get('name', project.get('id'))}: "
                    f"{blocker}. AgentSmith should now see the escalation."
                )
        if last.tool_name == "report_execution_verification":
            project = last.output.get("project") or {}
            if project:
                return (
                    f"I recorded verification results for {project.get('name', project.get('id'))} "
                    f"and moved the project into verification review."
                )
        if last.error:
            return last.error
        if self.agent_id == "agent_smith" and request.project_resolution.get("ambiguous"):
            return str(request.project_resolution.get("follow_up_question"))
        return self._default_free_reply(profile)

    def _default_free_reply(self, profile: AgentProfile) -> str:
        if self.agent_id == "neo":
            return (
                "I can discuss architecture, research options, inspect project state, run workspace commands, and apply direct project updates when needed. "
                "Ask naturally and I’ll use the available context."
            )
        if self.agent_id == "agent_smith":
            return (
                "I can manage project surfaces, milestones, blockers, handoffs, and change proposals. "
                "Tell me the change in normal language."
            )
        if self.agent_id == "niaobe":
            return (
                "I operate on approved execution handoffs, execution progress, blockers, and verification state. "
                "Ask about an execution handoff or project execution status."
            )
        if self.agent_id == "morpheus":
            return "I own the internal software loop and keep the execution stages coherent."
        if self.agent_id == "planner":
            return "I produce the internal execution plan and checkpoints."
        if self.agent_id == "implementer":
            return "I produce the internal implementation work package."
        if self.agent_id == "tester":
            return "I assess verification readiness and report the outcome."
        return f"{profile.purpose}."

    def _fallback_response(
        self,
        request: AgentTurnRequest,
        env: AgentEnvironment,
        *,
        last_error: str | None,
    ) -> AgentTurnResponse:
        lower = request.raw_content.lower()
        if request.project_resolution.get("ambiguous"):
            return self._reply_to_surface(
                request,
                sender_agent=self.agent_id,
                content=str(request.project_resolution.get("follow_up_question")),
            )
        if self.agent_id == "neo":
            if any(token in lower for token in ("active project", "open project", "projects", "status")):
                projects = env.project_registry.list_projects()
                if not projects:
                    return self._reply_to_surface(request, sender_agent="neo", content="There are no active projects right now.")
                lines = [f"- {row.get('name', row['id'])} [{row.get('status', 'NEW')}]" for row in projects]
                return self._reply_to_surface(
                    request,
                    sender_agent="neo",
                    content="Here are the active projects:\n" + "\n".join(lines),
                )
            suffix = " The local model was unavailable, so I’m replying from the bootstrap fallback." if last_error else ""
            profile = env.registry.get("neo")
            assert profile is not None
            return self._reply_to_surface(
                request,
                sender_agent="neo",
                content=self._default_free_reply(profile=profile) + suffix,
            )
        if self.agent_id == "agent_smith":
            suffix = " The local model was unavailable, so I’m replying from the bootstrap fallback." if last_error else ""
            profile = env.registry.get("agent_smith")
            assert profile is not None
            return self._reply_to_surface(
                request,
                sender_agent="agent_smith",
                content=self._default_free_reply(profile=profile) + suffix,
            )
        if self.agent_id in {"morpheus", "planner", "implementer", "tester"}:
            profile = env.registry.get(self.agent_id)
            assert profile is not None
            suffix = " The local model was unavailable, so I’m replying from the bootstrap fallback." if last_error else ""
            return self._reply_to_surface(
                request,
                sender_agent=self.agent_id,
                content=self._default_free_reply(profile=profile) + suffix,
            )
        return self._reply_to_surface(
            request,
            sender_agent=self.agent_id,
            content="I’m currently operating in bounded fallback mode.",
        )


class AgentRuntimeManager:
    def __init__(
        self,
        *,
        env: AgentEnvironment,
        prompt_loader: PromptLoader | None = None,
        model_map: ModelMapService | None = None,
        model_client: ModelClient | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.env = env
        self.prompt_loader = prompt_loader or PromptLoader()
        self.model_map = model_map or ModelMapService()
        self.model_client = model_client or OllamaModelClient()
        self.tool_registry = tool_registry or ToolRegistry()
        self._agents: dict[str, BaseRuntimeAgent] = {
            "neo": PromptDrivenRuntimeAgent(
                "neo",
                prompt_loader=self.prompt_loader,
                model_map=self.model_map,
                model_client=self.model_client,
                tool_registry=self.tool_registry,
            ),
            "agent_smith": PromptDrivenRuntimeAgent(
                "agent_smith",
                prompt_loader=self.prompt_loader,
                model_map=self.model_map,
                model_client=self.model_client,
                tool_registry=self.tool_registry,
            ),
            "niaobe": PromptDrivenRuntimeAgent(
                "niaobe",
                prompt_loader=self.prompt_loader,
                model_map=self.model_map,
                model_client=self.model_client,
                tool_registry=self.tool_registry,
            ),
            "morpheus": PromptDrivenRuntimeAgent(
                "morpheus",
                prompt_loader=self.prompt_loader,
                model_map=self.model_map,
                model_client=self.model_client,
                tool_registry=self.tool_registry,
            ),
            "planner": PromptDrivenRuntimeAgent(
                "planner",
                prompt_loader=self.prompt_loader,
                model_map=self.model_map,
                model_client=self.model_client,
                tool_registry=self.tool_registry,
            ),
            "implementer": PromptDrivenRuntimeAgent(
                "implementer",
                prompt_loader=self.prompt_loader,
                model_map=self.model_map,
                model_client=self.model_client,
                tool_registry=self.tool_registry,
            ),
            "tester": PromptDrivenRuntimeAgent(
                "tester",
                prompt_loader=self.prompt_loader,
                model_map=self.model_map,
                model_client=self.model_client,
                tool_registry=self.tool_registry,
            ),
        }

    @staticmethod
    def build_session_key(event: dict[str, Any]) -> str:
        if event.get("conversation_surface") == "dm":
            sender = event.get("sender_email", "")
            recipient = event.get("recipient_agent", "")
            return f"dm::{recipient}::{sender}"
        if event.get("conversation_surface") == "control":
            control_key = str(event.get("control_key") or event.get("event_id") or "runtime")
            recipient = str(event.get("recipient_agent") or "control")
            return f"control::{recipient}::{control_key}"
        return f"topic::{event.get('stream_name', '')}::{event.get('topic_name', '')}"

    def _resolve_project(self, event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if event.get("conversation_surface") == "control":
            execution_context = event.get("execution_context") or {}
            project_id = (
                event.get("project_id")
                or execution_context.get("project_id")
                or (execution_context.get("handoff") or {}).get("project_id")
            )
            project = self.env.state_store.get_project(project_id) if project_id else None
            return {
                "project_id": project_id,
                "ambiguous": False,
                "follow_up_question": None,
                "candidates": [project] if project else [],
            }, project
        if event.get("conversation_surface") == "dm":
            resolution = self.env.dm_context_resolver.resolve(event)
            project_id = resolution.get("project_id")
            project = self.env.state_store.get_project(project_id) if project_id else None
            return resolution, project
        topic_name = str(event.get("topic_name") or "")
        project_id = self.env.topic_router.resolve_project_id(topic_name)
        project = self.env.state_store.get_project(project_id) if project_id else None
        return {
            "project_id": project_id,
            "ambiguous": False,
            "follow_up_question": None,
            "candidates": [project] if project else [],
        }, project

    def handle_event(self, event: dict[str, Any]) -> AgentTurnResponse:
        agent_id = str(event.get("recipient_agent") or "").strip().lower().replace(" ", "_")
        if not agent_id and event.get("conversation_surface") != "dm":
            return AgentTurnResponse(status="topic_received")
        agent = self._agents.get(agent_id)
        profile = self.env.registry.get(agent_id)
        if not agent:
            if event.get("conversation_surface") != "dm":
                return AgentTurnResponse(status="ignored")
            return AgentTurnResponse(
                outbound_messages=[
                    OutboundMessage(
                        target_type="dm",
                        sender_agent=agent_id or "gateway",
                        target_email=event.get("sender_email", ""),
                        content_markdown="I received your message, but that agent is not enabled in this foundation slice.",
                    )
                ]
            )
        if profile is not None:
            surface_decision = self.env.policy_service.evaluate_surface_access(
                profile,
                surface=str(event.get("conversation_surface", "")),
            )
            if surface_decision.disposition == "deny":
                if event.get("conversation_surface") == "control":
                    return AgentTurnResponse(
                        internal_output={"reply": surface_decision.message or surface_decision.reason}
                    )
                return AgentTurnResponse(
                    outbound_messages=[
                        OutboundMessage(
                            target_type="dm" if event.get("conversation_surface") == "dm" else "stream",
                            sender_agent=agent_id,
                            target_email=event.get("sender_email", "") if event.get("conversation_surface") == "dm" else None,
                            stream_name=event.get("stream_name"),
                            topic_name=event.get("topic_name"),
                            content_markdown=surface_decision.message or surface_decision.reason,
                        )
                    ]
                )

        session_key = self.build_session_key(event)
        project_resolution, project = self._resolve_project(event)
        memory_scope_key = self._memory_scope_key(
            agent_id=agent_id,
            session_key=session_key,
            project_resolution=project_resolution,
        )
        recent_conversation = self._recent_conversation(profile=profile, session_key=session_key)
        if self._conversation_memory_enabled(profile):
            self.env.conversation_memory.append_message(
                session_key,
                role="human",
                sender=event.get("sender_email", ""),
                content=str(event.get("raw_content", "")),
                event_id=str(event.get("event_id", "")),
            )

        request = AgentTurnRequest(
            agent_id=agent_id,
            conversation_surface=str(event.get("conversation_surface", "")),
            sender_email=str(event.get("sender_email", "")),
            raw_content=str(event.get("raw_content", "")),
            session_key=session_key,
            stream_name=event.get("stream_name"),
            topic_name=event.get("topic_name"),
            dm_participants=list(event.get("dm_participants", [])),
            recent_conversation=recent_conversation,
            project_context=project,
            project_resolution=project_resolution,
            working_memory=self._working_memory(profile=profile, agent_id=agent_id, scope_key=memory_scope_key),
            execution_context=event.get("execution_context"),
            event=event,
        )

        if agent_id == "agent_smith":
            confirmation = self._handle_agent_smith_confirmation(request)
            if confirmation is not None:
                self._persist_response_state(agent_id, session_key, memory_scope_key, confirmation, profile=profile)
                return confirmation

        response = agent.handle_turn(request, self.env)
        response = self._apply_system_actions(request, response)
        self._persist_response_state(agent_id, session_key, memory_scope_key, response, profile=profile)
        return response

    def _handle_agent_smith_confirmation(self, request: AgentTurnRequest) -> AgentTurnResponse | None:
        resolution = self.env.policy_service.resolve_confirmation(
            raw_text=request.raw_content,
            requester_email=request.sender_email,
            owner_agent="agent_smith",
        )
        if not resolution.matched:
            return None
        if resolution.message:
            return BaseRuntimeAgent._reply_to_surface(
                request,
                sender_agent="agent_smith",
                content=resolution.message,
            )
        assert resolution.approval is not None
        if resolution.status != "APPROVED":
            return BaseRuntimeAgent._reply_to_surface(
                request,
                sender_agent="agent_smith",
                content=f"Confirmation recorded as {resolution.status}. No project mutation was applied.",
                task_id=resolution.approval["approval_id"],
                message_kind="approval_result",
            )

        execution = self.env.mutation_service.apply_confirmed_change(resolution.approval)
        content = (
            f"Approved and applied: {execution.summary}\n"
            f"Project: {execution.project['name']} ({execution.project['id']})\n"
            f"Handoff: {execution.handoff['handoff_id']}"
        )
        return AgentTurnResponse(
            outbound_messages=[
                OutboundMessage(
                    target_type="dm",
                    sender_agent="agent_smith",
                    target_email=request.sender_email,
                    content_markdown=content,
                    project_id=execution.project["id"],
                    task_id=execution.handoff["handoff_id"],
                    message_kind="approval_result",
                )
            ],
            projection_dispatches=[
                ProjectionDispatch(event=event, sender_agent="agent_smith")
                for event in execution.projection_events
            ],
        )

    def _apply_system_actions(self, request: AgentTurnRequest, response: AgentTurnResponse) -> AgentTurnResponse:
        if request.agent_id == "agent_smith":
            return self._apply_agent_smith_actions(request, response)
        if request.agent_id == "niaobe":
            return self._apply_niaobe_actions(request, response)
        return response

    def _apply_agent_smith_actions(self, request: AgentTurnRequest, response: AgentTurnResponse) -> AgentTurnResponse:
        structured_change = self._structured_change_from_response(request, response)
        classified = self.env.policy_service.classify_action(request.raw_content)
        wants_mutation = structured_change is not None or classified != "free_conversation"
        if not wants_mutation:
            return response

        profile = self.env.registry.get("agent_smith")
        if profile is None:
            return response

        decision = self.env.policy_service.evaluate_action_intent(
            profile=profile,
            intent_kind="project_mutation_request",
            request=request,
            payload=structured_change or {},
        )
        if decision.disposition == "deny":
            return BaseRuntimeAgent._reply_to_surface(
                request,
                sender_agent="agent_smith",
                content=f"Policy denied this change request: {decision.reason}.",
            )

        if structured_change and structured_change.get("action") == "needs_follow_up":
            return BaseRuntimeAgent._reply_to_surface(
                request,
                sender_agent="agent_smith",
                content=str(structured_change.get("error") or "Which project should I use?"),
            )

        if request.project_resolution.get("ambiguous") and not (
            structured_change and (structured_change.get("action") == "create_project" or structured_change.get("project_id"))
        ):
            return BaseRuntimeAgent._reply_to_surface(
                request,
                sender_agent="agent_smith",
                content=str(request.project_resolution.get("follow_up_question")),
            )

        change, error = self.env.mutation_service.build_change_request(
            request.raw_content,
            context_project_id=request.project_resolution.get("project_id"),
            structured_change=structured_change,
        )
        if error:
            return BaseRuntimeAgent._reply_to_surface(
                request,
                sender_agent="agent_smith",
                content=error,
            )
        assert change is not None

        approval = self.env.policy_service.request_confirmation(
            owner_agent="agent_smith",
            requester_email=request.sender_email,
            change=change,
        )

        prefix = ""
        if response.outbound_messages:
            prefix = response.outbound_messages[0].content_markdown.strip()
        approval_prompt = (
            f"{approval['preview']}\n\n"
            f"Approval ID: {approval['approval_id']}\n"
            f"Reply with 'confirm {approval['approval_id']}' to approve or "
            f"'reject {approval['approval_id']}' to cancel."
        )
        if prefix:
            approval_prompt = f"{prefix}\n\n{approval_prompt}"

        routed = BaseRuntimeAgent._reply_to_surface(
            request,
            sender_agent="agent_smith",
            content=approval_prompt,
            project_id=change.get("project_id"),
            task_id=approval["approval_id"],
            message_kind="approval_request",
        )
        project_id = change.get("project_id")
        if project_id:
            proposed = self.env.projection_event_service.record_event(
                event_type="project_change_proposed",
                project_id=project_id,
                summary=f"AgentSmith proposed a project change for {project_id}.",
                payload={
                    "approval_id": approval["approval_id"],
                    "requested_by": request.sender_email,
                    "preview": approval["preview"],
                    "updated_fields": sorted(field for field in change.keys() if field not in {"action", "project_id", "request_text"}),
                },
                actor_agent="agent_smith",
            )
            routed.projection_dispatches = [ProjectionDispatch(event=proposed, sender_agent="agent_smith")]
        routed.working_memory = response.working_memory
        return routed

    def _apply_niaobe_actions(self, request: AgentTurnRequest, response: AgentTurnResponse) -> AgentTurnResponse:
        profile = self.env.registry.get("niaobe")
        if profile is None:
            return response
        escalation_payload = self._niaobe_escalation_payload(response)
        if not escalation_payload:
            return response
        decision = self.env.policy_service.evaluate_action_intent(
            profile=profile,
            intent_kind="escalate_to_agent_smith",
            request=request,
            payload=escalation_payload,
        )
        if decision.disposition == "deny":
            return response
        response.outbound_messages.append(
            OutboundMessage(
                target_type="dm",
                sender_agent="niaobe",
                target_email="agentsmith-bot@bots.localdomain",
                content_markdown=escalation_payload.get(
                    "summary",
                    "Niaobe reported an execution blocker that needs AgentSmith attention.",
                ),
                project_id=escalation_payload.get("project_id"),
                task_id=escalation_payload.get("handoff_id"),
                message_kind="execution_escalation",
            )
        )
        return response

    def _structured_change_from_response(
        self,
        request: AgentTurnRequest,
        response: AgentTurnResponse,
    ) -> dict[str, Any] | None:
        for intent in response.action_intents:
            if intent.kind != "project_mutation_request":
                continue
            payload = dict(intent.payload)
            payload.setdefault("request_text", intent.summary or request.raw_content)
            action = str(payload.get("action") or "").strip().lower()
            if action == "create_project":
                return payload

            project_ref = str(payload.get("project_ref") or "").strip()
            if project_ref:
                resolution = self.env.project_registry.find_project(project_ref)
                if resolution.ambiguous:
                    return {
                        "action": "needs_follow_up",
                        "error": resolution.follow_up_question or "I found multiple matching projects. Which one should I use?",
                    }
                if resolution.project_id:
                    payload["project_id"] = resolution.project_id
                else:
                    return {
                        "action": "needs_follow_up",
                        "error": f"I couldn't find a matching project for '{project_ref}'. Which project should I use?",
                    }
            elif request.project_resolution.get("ambiguous"):
                return {
                    "action": "needs_follow_up",
                    "error": str(request.project_resolution.get("follow_up_question") or "Which project should I use?"),
                }
            elif request.project_resolution.get("project_id"):
                payload["project_id"] = request.project_resolution.get("project_id")
            return payload
        return None

    @staticmethod
    def _conversation_memory_enabled(profile: AgentProfile | None) -> bool:
        if profile is None:
            return True
        return profile.memory_profile.get("conversational_memory", "read_write") != "none"

    def _recent_conversation(self, *, profile: AgentProfile | None, session_key: str) -> list[dict[str, Any]]:
        if profile is None:
            return self.env.conversation_memory.recent_messages(session_key, max_age_seconds=6 * 3600)
        return self.env.conversation_memory.recent_messages_for_profile(
            session_key,
            memory_profile=profile.memory_profile,
            limit=12,
        )

    @staticmethod
    def _memory_scope_key(
        *,
        agent_id: str,
        session_key: str,
        project_resolution: dict[str, Any],
    ) -> str:
        project_id = project_resolution.get("project_id")
        if agent_id == "niaobe" and project_id:
            return f"execution::{project_id}"
        if agent_id == "niaobe":
            return f"execution::{session_key}"
        if agent_id in {"morpheus", "planner", "implementer", "tester"} and project_id:
            return f"internal::{project_id}"
        return session_key

    def _working_memory(self, *, profile: AgentProfile | None, agent_id: str, scope_key: str) -> dict[str, Any]:
        if profile is None:
            return self.env.working_memory.get_state(agent_id, scope_key)
        return self.env.working_memory.get_state_for_profile(
            agent_id,
            scope_key,
            memory_profile=profile.memory_profile,
        )

    def _persist_response_state(
        self,
        agent_id: str,
        session_key: str,
        memory_scope_key: str,
        response: AgentTurnResponse,
        *,
        profile: AgentProfile | None,
    ) -> None:
        if response.working_memory is not None and (
            profile is None or profile.memory_profile.get("working_memory", "read_write") != "none"
        ):
            self.env.working_memory.put_state(agent_id, memory_scope_key, response.working_memory)

        if not self._conversation_memory_enabled(profile):
            return
        for message in response.outbound_messages:
            self.env.conversation_memory.append_message(
                session_key,
                role="agent",
                sender=message.sender_agent,
                content=message.content_markdown,
                event_id=None,
            )

    @staticmethod
    def _niaobe_escalation_payload(response: AgentTurnResponse) -> dict[str, Any] | None:
        for result in response.tool_results:
            if not result.ok:
                continue
            output = result.output if isinstance(result.output, dict) else {}
            escalation = output.get("escalation")
            if isinstance(escalation, dict):
                return escalation
        for intent in response.action_intents:
            if intent.kind == "escalate_to_agent_smith":
                return dict(intent.payload)
        return None

    def process_pending_handoffs(self, *, limit: int = 5) -> list[tuple[dict[str, Any], AgentTurnResponse]]:
        pending = self.env.state_store.list_handoffs(
            status="PENDING",
            assignee_agent="niaobe",
        )[: max(1, limit)]
        responses: list[tuple[dict[str, Any], AgentTurnResponse]] = []
        for handoff in pending:
            execution_state, start_event = self.env.execution_state.intake_handoff(
                handoff,
                actor_agent="niaobe",
            )
            event = {
                "event_id": f"system::handoff::{handoff['handoff_id']}",
                "source_type": "execution_handoff_ready",
                "conversation_surface": "project_topic",
                "recipient_agent": "niaobe",
                "sender_email": "system@openclaw.local",
                "raw_content": (
                    "A new approved execution handoff is ready. Summarize the first execution step, "
                    "and only use execution-state tools for blockers or verification."
                ),
                "stream_name": handoff.get("canonical_stream", "projects"),
                "topic_name": handoff.get("canonical_topic", f"project/{handoff['project_id']}"),
                "execution_context": {
                    "handoff_id": handoff["handoff_id"],
                    "handoff": handoff,
                    "execution_state": execution_state,
                    "trigger": "system_handoff_intake",
                },
            }
            response = self.handle_event(event)
            if start_event:
                response.projection_dispatches.insert(
                    0,
                    ProjectionDispatch(event=start_event, sender_agent="niaobe"),
                )
            responses.append((event, response))
            self.env.internal_loop.ensure_run_for_handoff(
                handoff,
                execution_state=execution_state,
            )

        active_handoffs = {}
        for row in self.env.state_store.list_handoffs(assignee_agent="niaobe"):
            active_handoffs[row["handoff_id"]] = row
            if row.get("status") in {"IN_PROGRESS", "BLOCKED"}:
                self.env.internal_loop.ensure_run_for_handoff(
                    row,
                    execution_state=self.env.execution_state.get_execution_state_for_handoff(row["handoff_id"]),
                )
        for run in self.env.internal_loop.next_work_items(limit=max(1, limit)):
            handoff = active_handoffs.get(run["handoff_id"]) or self.env.state_store.get_handoff(run["handoff_id"])
            if not handoff:
                continue
            execution_state = self.env.execution_state.get_execution_state_for_handoff(run["handoff_id"])
            control_event = self.env.internal_loop.build_stage_event(
                run,
                handoff=handoff,
                project=self.env.state_store.get_project(run["project_id"]),
                execution_state=execution_state,
            )
            internal_response = self.handle_event(control_event)
            stage_effects = self.env.internal_loop.apply_stage_response(
                run,
                internal_response,
                handoff=handoff,
            )
            projection_events = list(stage_effects.get("projection_events", []))
            if projection_events:
                effect_response = AgentTurnResponse(
                    projection_dispatches=[
                        ProjectionDispatch(
                            event=event,
                            sender_agent=stage_effects.get("sender_agent", "niaobe"),
                        )
                        for event in projection_events
                    ]
                )
            else:
                effect_response = AgentTurnResponse()
            escalation = stage_effects.get("escalation")
            if isinstance(escalation, dict):
                effect_response.outbound_messages.append(
                    OutboundMessage(
                        target_type="dm",
                        sender_agent="niaobe",
                        target_email="agentsmith-bot@bots.localdomain",
                        content_markdown=str(
                            escalation.get(
                                "summary",
                                "Internal execution work is blocked and needs AgentSmith attention.",
                            )
                        ),
                        project_id=escalation.get("project_id"),
                        task_id=escalation.get("handoff_id"),
                        message_kind="execution_escalation",
                    )
                )
            if effect_response.outbound_messages or effect_response.projection_dispatches:
                responses.append((control_event, effect_response))
        return responses
