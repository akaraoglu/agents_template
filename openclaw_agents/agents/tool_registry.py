"""Bounded and executable tool registry for visible agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import AgentTurnRequest, ToolCall, ToolResult
from .registry import AgentProfile


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    arguments: dict[str, str]

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
        }


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        pieces = [piece.strip() for piece in value.replace("\n", ",").split(",")]
        return [piece for piece in pieces if piece]
    return []


def _policy_surface(surface: str) -> str:
    return "project_topic" if surface and surface != "dm" else "dm"


class ToolRegistry:
    def available_tools(self, profile: AgentProfile) -> list[ToolSpec]:
        names: list[str] = []
        for skill in profile.allowed_skills:
            if skill == "project_context":
                names.extend(
                    [
                        "list_open_projects",
                        "get_project_context",
                        "get_project_management_surface",
                        "list_blocked_projects",
                    ]
                )
            elif skill == "workspace_ops":
                names.append("read_project_file")
            elif skill == "sdd_artifact_ops":
                names.extend(["list_execution_handoffs", "list_projection_events"])
            elif skill == "execution_handoff":
                names.extend(
                    [
                        "get_pending_execution_handoff",
                        "get_execution_state",
                        "start_execution_handoff",
                        "report_execution_blocker",
                        "report_execution_verification",
                    ]
                )
            elif skill == "web_research":
                names.extend(["web_search", "fetch_url", "research_brief"])

        if "web_research" in profile.allowed_services:
            names.extend(["web_search", "fetch_url", "research_brief"])
        if "workspace_write" in profile.allowed_services:
            names.append("write_project_file")
        if "command_runner" in profile.allowed_services:
            names.append("run_workspace_command")
        if "direct_project_mutation" in profile.allowed_services:
            names.extend(["create_project_surface", "update_project_state"])
        if "execution_state" in profile.allowed_services:
            names.extend(
                [
                    "get_pending_execution_handoff",
                    "get_execution_state",
                    "start_execution_handoff",
                    "report_execution_blocker",
                    "report_execution_verification",
                ]
            )

        unique: list[str] = []
        for name in names:
            if name not in unique:
                unique.append(name)
        return [self._build_spec(name) for name in unique]

    def execute(
        self,
        call: ToolCall,
        *,
        profile: AgentProfile,
        request: AgentTurnRequest,
        env: Any,
    ) -> ToolResult:
        available = {spec.name for spec in self.available_tools(profile)}
        if call.tool_name not in available:
            return ToolResult(
                tool_name=call.tool_name,
                ok=False,
                output={},
                error=f"Tool '{call.tool_name}' is not allowed for {profile.agent_id}.",
            )

        arguments = call.arguments
        decision = env.policy_service.evaluate_tool_call(
            profile=profile,
            tool_name=call.tool_name,
            arguments=arguments,
            surface=_policy_surface(request.conversation_surface),
        )
        if decision.disposition == "deny":
            return ToolResult(
                tool_name=call.tool_name,
                ok=False,
                output={},
                error=decision.message or decision.reason,
            )
        if decision.disposition == "needs_confirmation":
            return ToolResult(
                tool_name=call.tool_name,
                ok=False,
                output={},
                error=decision.message or "This tool requires a confirmation-gated path.",
            )

        try:
            if call.tool_name == "list_open_projects":
                include_done = bool(arguments.get("include_done", False))
                projects = env.project_registry.list_projects(include_done=include_done)
                payload = [
                    {
                        "id": row["id"],
                        "name": row.get("name", row["id"]),
                        "status": row.get("status", "NEW"),
                        "summary": row.get("summary", ""),
                    }
                    for row in projects
                ]
                return ToolResult(tool_name=call.tool_name, ok=True, output={"projects": payload})

            if call.tool_name == "get_project_context":
                project_context = self._project_context(arguments, request, env)
                if project_context.get("ambiguous"):
                    return ToolResult(tool_name=call.tool_name, ok=True, output=project_context)
                project_id = project_context.get("project_id")
                if not project_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=True,
                        output={"status": "not_found", "message": "No project context matched the request."},
                    )
                project = env.state_store.get_project(project_id) or {}
                return ToolResult(
                    tool_name=call.tool_name,
                    ok=True,
                    output={
                        "status": "ok",
                        "project": {
                            "id": project_id,
                            "name": project.get("name", project_id),
                            "summary": project.get("summary", ""),
                            "status": project.get("status", "NEW"),
                            "next_actions": project.get("next_actions", []),
                            "milestones": project.get("milestones", []),
                            "backlog_items": project.get("backlog_items", []),
                            "blockers": project.get("blockers", []),
                            "decisions": project.get("decisions", []),
                            "backlog_count": project.get("backlog_count", 0),
                            "workspace_path": project.get("workspace_path"),
                        },
                    },
                )

            if call.tool_name == "get_project_management_surface":
                project_context = self._project_context(arguments, request, env)
                if project_context.get("ambiguous"):
                    return ToolResult(tool_name=call.tool_name, ok=True, output=project_context)
                project_id = project_context.get("project_id")
                if not project_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=True,
                        output={"status": "not_found", "message": "No project context matched the request."},
                    )
                project = env.state_store.get_project(project_id) or {}
                files = env.workspace_service.read_management_surface(project_id)
                return ToolResult(
                    tool_name=call.tool_name,
                    ok=True,
                    output={
                        "status": "ok",
                        "project": {
                            "id": project_id,
                            "name": project.get("name", project_id),
                            "summary": project.get("summary", ""),
                            "status": project.get("status", "NEW"),
                            "next_actions": project.get("next_actions", []),
                            "milestones": project.get("milestones", []),
                            "backlog_items": project.get("backlog_items", []),
                            "blockers": project.get("blockers", []),
                            "decisions": project.get("decisions", []),
                            "workspace_path": project.get("workspace_path"),
                        },
                        "files": files,
                    },
                )

            if call.tool_name == "list_blocked_projects":
                blocked = env.project_registry.get_blocked_projects()
                return ToolResult(tool_name=call.tool_name, ok=True, output={"projects": blocked})

            if call.tool_name == "read_project_file":
                path = str(arguments.get("path") or "").strip()
                if not path:
                    return ToolResult(tool_name=call.tool_name, ok=False, output={}, error="The 'path' argument is required.")
                project_context = self._project_context(arguments, request, env)
                if project_context.get("ambiguous"):
                    return ToolResult(tool_name=call.tool_name, ok=True, output=project_context)
                project_id = project_context.get("project_id")
                if not project_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="Project context is required before reading a project file.",
                    )
                content = env.workspace_service.read_project_file(project_id, path)
                return ToolResult(
                    tool_name=call.tool_name,
                    ok=True,
                    output={"project_id": project_id, "path": path, "content": content},
                )

            if call.tool_name == "write_project_file":
                path = str(arguments.get("path") or "").strip()
                content = str(arguments.get("content") or "")
                if not path:
                    return ToolResult(tool_name=call.tool_name, ok=False, output={}, error="The 'path' argument is required.")
                project_context = self._project_context(arguments, request, env)
                if project_context.get("ambiguous"):
                    return ToolResult(tool_name=call.tool_name, ok=True, output=project_context)
                project_id = project_context.get("project_id")
                if not project_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="Project context is required before writing a project file.",
                    )
                written = env.workspace_service.write_project_file(project_id, path, content)
                env.audit_log.record(
                    action_type="workspace_write",
                    actor_agent=request.agent_id,
                    outcome="ok",
                    project_id=project_id,
                    payload={"tool_name": call.tool_name, "path": path},
                )
                return ToolResult(
                    tool_name=call.tool_name,
                    ok=True,
                    output={"project_id": project_id, "path": path, "written_path": str(written)},
                )

            if call.tool_name == "create_project_surface":
                name = str(arguments.get("name") or "").strip()
                summary = str(arguments.get("summary") or "").strip()
                if not name:
                    return ToolResult(tool_name=call.tool_name, ok=False, output={}, error="The 'name' argument is required.")
                project = env.project_provisioning.create_project_surface(
                    name=name,
                    summary=summary,
                    requested_by=request.sender_email,
                )
                event = env.projection_event_service.record_event(
                    event_type="project_kickoff",
                    project_id=project["id"],
                    summary=f"{request.agent_id} created project {project['name']}.",
                    payload={"created_by": request.sender_email, "source": "direct_mutation"},
                    actor_agent=request.agent_id,
                )
                env.audit_log.record(
                    action_type="project_create",
                    actor_agent=request.agent_id,
                    outcome="ok",
                    project_id=project["id"],
                    payload={"tool_name": call.tool_name, "name": name},
                )
                return ToolResult(
                    tool_name=call.tool_name,
                    ok=True,
                    output={"project": project, "projection_events": [event]},
                )

            if call.tool_name == "update_project_state":
                project_context = self._project_context(arguments, request, env)
                if project_context.get("ambiguous"):
                    return ToolResult(tool_name=call.tool_name, ok=True, output=project_context)
                project_id = project_context.get("project_id")
                if not project_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="Project context is required before updating project state.",
                    )
                updates = self._project_updates_from_arguments(arguments)
                if not updates:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="At least one project field to update is required.",
                    )
                project = env.project_provisioning.update_project_surface(
                    project_id=project_id,
                    updates=updates,
                    requested_by=request.sender_email,
                )
                projection_events = self._projection_events_for_project_update(
                    env,
                    request,
                    project=project,
                    updates=updates,
                )
                env.audit_log.record(
                    action_type="project_update",
                    actor_agent=request.agent_id,
                    outcome="ok",
                    project_id=project_id,
                    payload={"tool_name": call.tool_name, "updated_fields": sorted(updates.keys())},
                )
                return ToolResult(
                    tool_name=call.tool_name,
                    ok=True,
                    output={"project": project, "projection_events": projection_events},
                )

            if call.tool_name == "run_workspace_command":
                command = str(arguments.get("command") or "").strip()
                if not command:
                    return ToolResult(tool_name=call.tool_name, ok=False, output={}, error="The 'command' argument is required.")
                project_context = self._project_context(arguments, request, env)
                if project_context.get("ambiguous"):
                    return ToolResult(tool_name=call.tool_name, ok=True, output=project_context)
                project_id = project_context.get("project_id")
                cwd = arguments.get("cwd")
                if project_id:
                    root = env.workspace_service.resolve_workspace(project_id)
                    cwd = str((root / str(cwd)).resolve()) if cwd else str(root)
                    allowed_root = str(root)
                else:
                    allowed_root = None
                result = env.command_runner.run(
                    command,
                    cwd=str(cwd) if cwd else None,
                    timeout_seconds=int(arguments.get("timeout_seconds", 120)),
                    actor_agent=request.agent_id,
                    project_id=project_id,
                    allowed_root=allowed_root,
                )
                projection_events: list[dict[str, Any]] = []
                if project_id and request.conversation_surface != "control":
                    project = env.state_store.get_project(project_id) or {"name": project_id}
                    handoff = (request.execution_context or {}).get("handoff") or {}
                    event_type = "execution_started" if result["returncode"] == 0 else "execution_blocked"
                    projection_events.append(
                        env.projection_event_service.record_event(
                            event_type=event_type,
                            project_id=project_id,
                            summary=(
                                f"{request.agent_id} ran a workspace command for {project.get('name', project_id)}."
                                if result["returncode"] == 0
                                else f"{request.agent_id} hit an execution issue in {project.get('name', project_id)}."
                            ),
                            payload={
                                "command": result["command"],
                                "returncode": result["returncode"],
                                "handoff_id": handoff.get("handoff_id"),
                            },
                            actor_agent=request.agent_id,
                        )
                    )
                handoff = (request.execution_context or {}).get("handoff") or {}
                if request.agent_id == "niaobe" and handoff.get("handoff_id"):
                    env.execution_state.get_or_create_for_handoff(handoff, actor_agent=request.agent_id)
                result["projection_events"] = projection_events
                return ToolResult(tool_name=call.tool_name, ok=True, output=result)

            if call.tool_name == "web_search":
                query = str(arguments.get("query") or "").strip()
                result = env.web_research.search(query, limit=int(arguments.get("limit", 5)))
                return ToolResult(tool_name=call.tool_name, ok=True, output=result)

            if call.tool_name == "fetch_url":
                url = str(arguments.get("url") or "").strip()
                result = env.web_research.fetch_url(url, max_chars=int(arguments.get("max_chars", 4000)))
                return ToolResult(tool_name=call.tool_name, ok=True, output=result)

            if call.tool_name == "research_brief":
                query = str(arguments.get("query") or "").strip()
                if not query:
                    return ToolResult(tool_name=call.tool_name, ok=False, output={}, error="The 'query' argument is required.")
                result = env.web_research.research(
                    query,
                    search_limit=int(arguments.get("search_limit", 5)),
                    fetch_limit=int(arguments.get("fetch_limit", 3)),
                    max_chars=int(arguments.get("max_chars", 1600)),
                )
                return ToolResult(tool_name=call.tool_name, ok=True, output=result)

            if call.tool_name == "list_execution_handoffs":
                project_context = self._project_context(arguments, request, env)
                project_id = project_context.get("project_id")
                handoffs = env.state_store.list_handoffs(project_id=project_id)
                return ToolResult(tool_name=call.tool_name, ok=True, output={"handoffs": handoffs})

            if call.tool_name == "list_projection_events":
                project_context = self._project_context(arguments, request, env)
                project_id = project_context.get("project_id")
                events = env.projection_event_service.list_events(project_id=project_id)
                return ToolResult(tool_name=call.tool_name, ok=True, output={"events": events})

            if call.tool_name == "get_pending_execution_handoff":
                project_context = self._project_context(arguments, request, env)
                handoff = env.execution_state.get_pending_handoff(project_id=project_context.get("project_id"))
                if not handoff:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=True,
                        output={"status": "not_found", "message": "No pending execution handoff was found."},
                    )
                execution_state = env.execution_state.get_execution_state_for_handoff(handoff["handoff_id"])
                return ToolResult(
                    tool_name=call.tool_name,
                    ok=True,
                    output={"handoff": handoff, "execution_state": execution_state},
                )

            if call.tool_name == "get_execution_state":
                handoff_id = self._resolve_handoff_id(arguments, request, env)
                if not handoff_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=True,
                        output={"status": "not_found", "message": "No execution state was found."},
                    )
                execution_state = env.execution_state.get_execution_state_for_handoff(handoff_id)
                if not execution_state:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=True,
                        output={"status": "not_found", "message": "No execution state was found.", "handoff_id": handoff_id},
                    )
                return ToolResult(tool_name=call.tool_name, ok=True, output={"execution_state": execution_state})

            if call.tool_name == "start_execution_handoff":
                handoff_id = self._resolve_handoff_id(arguments, request, env)
                if not handoff_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="A pending handoff is required before execution can start.",
                    )
                result = env.execution_state.start_execution(handoff_id, actor_agent=request.agent_id)
                env.audit_log.record(
                    action_type="execution_start",
                    actor_agent=request.agent_id,
                    outcome="ok",
                    project_id=result["handoff"]["project_id"],
                    handoff_id=handoff_id,
                    payload={"tool_name": call.tool_name},
                )
                return ToolResult(tool_name=call.tool_name, ok=True, output=result)

            if call.tool_name == "report_execution_blocker":
                blocker = str(arguments.get("blocker") or "").strip()
                if not blocker:
                    return ToolResult(tool_name=call.tool_name, ok=False, output={}, error="The 'blocker' argument is required.")
                handoff_id = self._resolve_handoff_id(arguments, request, env)
                if not handoff_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="A pending handoff is required before a blocker can be reported.",
                    )
                result = env.execution_state.report_blocker(
                    handoff_id=handoff_id,
                    actor_agent=request.agent_id,
                    blocker=blocker,
                    next_step=str(arguments.get("next_step") or "").strip() or None,
                    escalation_target=str(arguments.get("escalation_target") or "agent_smith"),
                )
                env.audit_log.record(
                    action_type="execution_blocker",
                    actor_agent=request.agent_id,
                    outcome="ok",
                    project_id=result["handoff"]["project_id"],
                    handoff_id=handoff_id,
                    payload={"tool_name": call.tool_name, "blocker": blocker},
                )
                return ToolResult(tool_name=call.tool_name, ok=True, output=result)

            if call.tool_name == "report_execution_verification":
                verification_report = str(arguments.get("verification_report") or "").strip()
                if not verification_report:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="The 'verification_report' argument is required.",
                    )
                handoff_id = self._resolve_handoff_id(arguments, request, env)
                if not handoff_id:
                    return ToolResult(
                        tool_name=call.tool_name,
                        ok=False,
                        output={},
                        error="A pending handoff is required before verification can be reported.",
                    )
                result = env.execution_state.report_verification(
                    handoff_id=handoff_id,
                    actor_agent=request.agent_id,
                    report_summary=verification_report,
                    report_body=str(arguments.get("report_body") or "").strip() or None,
                )
                env.audit_log.record(
                    action_type="execution_verification",
                    actor_agent=request.agent_id,
                    outcome="ok",
                    project_id=result["handoff"]["project_id"],
                    handoff_id=handoff_id,
                    payload={"tool_name": call.tool_name},
                )
                return ToolResult(tool_name=call.tool_name, ok=True, output=result)
        except Exception as exc:  # pragma: no cover
            return ToolResult(tool_name=call.tool_name, ok=False, output={}, error=str(exc))

        return ToolResult(tool_name=call.tool_name, ok=False, output={}, error="Unsupported tool.")

    def _project_context(self, arguments: dict[str, Any], request: AgentTurnRequest, env: Any) -> dict[str, Any]:
        cleaned = str(arguments.get("project_ref") or "").strip()
        if cleaned:
            resolution = env.project_registry.find_project(cleaned)
            if resolution.project_id:
                return {"project_id": resolution.project_id, "ambiguous": False, "follow_up_question": None}
            if resolution.ambiguous:
                return {
                    "project_id": None,
                    "ambiguous": True,
                    "follow_up_question": resolution.follow_up_question,
                }
        if request.project_resolution.get("ambiguous"):
            return {
                "project_id": None,
                "ambiguous": True,
                "follow_up_question": request.project_resolution.get("follow_up_question"),
            }
        return {
            "project_id": request.project_resolution.get("project_id"),
            "ambiguous": False,
            "follow_up_question": None,
        }

    @staticmethod
    def _project_updates_from_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        for key in ("name", "summary", "status"):
            value = arguments.get(key)
            if value is not None and str(value).strip():
                updates[key] = str(value).strip()
        for list_key in ("next_actions", "milestones", "backlog_items", "blockers", "decisions"):
            values = _normalize_list(arguments.get(list_key))
            if values:
                updates[list_key] = values
        return updates

    @staticmethod
    def _projection_events_for_project_update(env: Any, request: AgentTurnRequest, *, project: dict[str, Any], updates: dict[str, Any]) -> list[dict[str, Any]]:
        project_id = project["id"]
        actor_agent = request.agent_id
        projection_events: list[dict[str, Any]] = []
        if any(key in updates for key in ("name", "summary")):
            projection_events.append(
                env.projection_event_service.record_event(
                    event_type="spec_updated",
                    project_id=project_id,
                    summary=f"{actor_agent} updated the project summary/spec for {project['name']}.",
                    payload={"updated_fields": [key for key in ("name", "summary") if key in updates]},
                    actor_agent=actor_agent,
                )
            )
        if any(key in updates for key in ("milestones", "next_actions", "decisions")):
            projection_events.append(
                env.projection_event_service.record_event(
                    event_type="plan_updated",
                    project_id=project_id,
                    summary=f"{actor_agent} updated the project plan for {project['name']}.",
                    payload={"updated_fields": [key for key in ("milestones", "next_actions", "decisions") if key in updates]},
                    actor_agent=actor_agent,
                )
            )
        if "backlog_items" in updates:
            projection_events.append(
                env.projection_event_service.record_event(
                    event_type="tasks_updated",
                    project_id=project_id,
                    summary=f"{actor_agent} updated tasks for {project['name']}.",
                    payload={"updated_fields": ["backlog_items"]},
                    actor_agent=actor_agent,
                )
            )
        if updates.get("status") == "CLOSED":
            projection_events.append(
                env.projection_event_service.record_event(
                    event_type="project_closed",
                    project_id=project_id,
                    summary=f"{actor_agent} closed project {project['name']}.",
                    payload={"updated_fields": ["status"]},
                    actor_agent=actor_agent,
                )
            )
        elif any(key in updates for key in ("status", "blockers")):
            projection_events.append(
                env.projection_event_service.record_event(
                    event_type="project_change_confirmed",
                    project_id=project_id,
                    summary=f"{actor_agent} updated execution or status fields for {project['name']}.",
                    payload={"updated_fields": [key for key in ("status", "blockers") if key in updates]},
                    actor_agent=actor_agent,
                )
            )
        return projection_events

    def _resolve_handoff_id(self, arguments: dict[str, Any], request: AgentTurnRequest, env: Any) -> str | None:
        handoff_id = str(arguments.get("handoff_id") or "").strip()
        if handoff_id:
            return handoff_id
        execution_context = request.execution_context or {}
        handoff = execution_context.get("handoff") or {}
        if handoff.get("handoff_id"):
            return str(handoff["handoff_id"])
        project_context = self._project_context(arguments, request, env)
        pending = env.execution_state.get_pending_handoff(project_id=project_context.get("project_id"))
        if pending:
            return str(pending["handoff_id"])
        project_id = project_context.get("project_id")
        if project_id:
            handoffs = env.state_store.list_handoffs(project_id=project_id, assignee_agent="niaobe")
            if handoffs:
                return str(handoffs[-1]["handoff_id"])
        return None

    @staticmethod
    def _build_spec(name: str) -> ToolSpec:
        specs = {
            "list_open_projects": ToolSpec(
                name="list_open_projects",
                description="List current projects from authoritative project memory.",
                arguments={"include_done": "Optional boolean. Include closed projects when true."},
            ),
            "get_project_context": ToolSpec(
                name="get_project_context",
                description="Get durable project state, milestones, blockers, and summary.",
                arguments={"project_ref": "Optional project id or project name fragment."},
            ),
            "get_project_management_surface": ToolSpec(
                name="get_project_management_surface",
                description="Read the durable project-management surface in one call, including status, milestones, backlog, blockers, decisions, and canonical workspace files.",
                arguments={"project_ref": "Optional project id or project name fragment."},
            ),
            "list_blocked_projects": ToolSpec(
                name="list_blocked_projects",
                description="List projects currently marked BLOCKED.",
                arguments={},
            ),
            "read_project_file": ToolSpec(
                name="read_project_file",
                description="Read a file from a resolved project workspace.",
                arguments={
                    "project_ref": "Optional project id or name fragment. Uses current context if omitted.",
                    "path": "Relative path within the project workspace.",
                },
            ),
            "write_project_file": ToolSpec(
                name="write_project_file",
                description="Write a file inside a resolved project workspace.",
                arguments={
                    "project_ref": "Optional project id or name fragment. Uses current context if omitted.",
                    "path": "Relative path within the project workspace.",
                    "content": "Full file content to write.",
                },
            ),
            "create_project_surface": ToolSpec(
                name="create_project_surface",
                description="Create a new project surface directly in authoritative state and workspace.",
                arguments={"name": "Project display name.", "summary": "Optional project summary."},
            ),
            "update_project_state": ToolSpec(
                name="update_project_state",
                description="Directly update durable project state such as summary, milestones, status, backlog, blockers, or next actions.",
                arguments={
                    "project_ref": "Optional project id or name fragment. Uses current context if omitted.",
                    "summary": "Optional new project summary.",
                    "status": "Optional new project status.",
                    "milestones": "Optional comma-separated list of milestones or an array.",
                    "next_actions": "Optional comma-separated list of next actions or an array.",
                    "backlog_items": "Optional comma-separated list of backlog items or an array.",
                    "blockers": "Optional comma-separated list of blockers or an array.",
                    "decisions": "Optional comma-separated list of decisions or an array.",
                },
            ),
            "run_workspace_command": ToolSpec(
                name="run_workspace_command",
                description="Run a shell command inside the repository boundary or a project workspace.",
                arguments={
                    "project_ref": "Optional project id or name fragment. Uses the project workspace as cwd when set.",
                    "command": "Shell command to execute.",
                    "cwd": "Optional cwd relative to the resolved workspace or repository root.",
                    "timeout_seconds": "Optional timeout in seconds.",
                },
            ),
            "web_search": ToolSpec(
                name="web_search",
                description="Search the web for recent or general information.",
                arguments={"query": "Search query string.", "limit": "Optional result count up to 10."},
            ),
            "fetch_url": ToolSpec(
                name="fetch_url",
                description="Fetch and summarize the text content of a URL.",
                arguments={"url": "HTTP or HTTPS URL to fetch.", "max_chars": "Optional maximum characters of extracted text to keep."},
            ),
            "research_brief": ToolSpec(
                name="research_brief",
                description="Search and fetch multiple web sources, returning a research packet with source metadata and citations.",
                arguments={
                    "query": "Research topic or question.",
                    "search_limit": "Optional number of search results to inspect.",
                    "fetch_limit": "Optional number of sources to fetch in detail.",
                    "max_chars": "Optional maximum excerpt characters per fetched source.",
                },
            ),
            "list_execution_handoffs": ToolSpec(
                name="list_execution_handoffs",
                description="List persisted execution handoff packets outside Zulip.",
                arguments={"project_ref": "Optional project id or name fragment."},
            ),
            "list_projection_events": ToolSpec(
                name="list_projection_events",
                description="List first-class projection events for a project thread.",
                arguments={"project_ref": "Optional project id or name fragment."},
            ),
            "get_pending_execution_handoff": ToolSpec(
                name="get_pending_execution_handoff",
                description="Get the latest pending execution handoff for a project.",
                arguments={"project_ref": "Optional project id or name fragment."},
            ),
            "get_execution_state": ToolSpec(
                name="get_execution_state",
                description="Read durable execution state for a handoff or project.",
                arguments={
                    "handoff_id": "Optional handoff id. Uses the active project handoff when omitted.",
                    "project_ref": "Optional project id or name fragment.",
                },
            ),
            "start_execution_handoff": ToolSpec(
                name="start_execution_handoff",
                description="Claim a pending execution handoff and mark execution as started.",
                arguments={
                    "handoff_id": "Optional handoff id. Uses the active project handoff when omitted.",
                    "project_ref": "Optional project id or name fragment.",
                },
            ),
            "report_execution_blocker": ToolSpec(
                name="report_execution_blocker",
                description="Persist an execution blocker and escalate it for project management visibility.",
                arguments={
                    "handoff_id": "Optional handoff id. Uses the active project handoff when omitted.",
                    "project_ref": "Optional project id or name fragment.",
                    "blocker": "Short blocker summary.",
                    "next_step": "Optional next step or escalation summary.",
                    "escalation_target": "Optional escalation target agent id.",
                },
            ),
            "report_execution_verification": ToolSpec(
                name="report_execution_verification",
                description="Persist verification results for an execution handoff.",
                arguments={
                    "handoff_id": "Optional handoff id. Uses the active project handoff when omitted.",
                    "project_ref": "Optional project id or name fragment.",
                    "verification_report": "Short verification summary.",
                    "report_body": "Optional longer verification note.",
                },
            ),
        }
        return specs[name]
