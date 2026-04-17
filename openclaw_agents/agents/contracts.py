"""Agent runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    ok: bool
    output: dict[str, Any]
    error: str | None = None


@dataclass(slots=True)
class ActionIntent:
    kind: str = "none"
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundMessage:
    target_type: str
    sender_agent: str
    content_markdown: str
    message_kind: str = "consultation_reply"
    project_id: str | None = None
    task_id: str | None = None
    target_email: str | None = None
    stream_name: str | None = None
    topic_name: str | None = None


@dataclass(slots=True)
class ProjectionDispatch:
    event: dict[str, Any]
    sender_agent: str


@dataclass(slots=True)
class AgentTurnRequest:
    agent_id: str
    conversation_surface: str
    sender_email: str
    raw_content: str
    session_key: str
    stream_name: str | None
    topic_name: str | None
    dm_participants: list[str]
    recent_conversation: list[dict[str, Any]]
    project_context: dict[str, Any] | None
    project_resolution: dict[str, Any]
    working_memory: dict[str, Any]
    execution_context: dict[str, Any] | None
    event: dict[str, Any]


@dataclass(slots=True)
class AgentTurnResponse:
    status: str = "handled"
    outbound_messages: list[OutboundMessage] = field(default_factory=list)
    projection_dispatches: list[ProjectionDispatch] = field(default_factory=list)
    action_intents: list[ActionIntent] = field(default_factory=list)
    working_memory: dict[str, Any] | None = None
    tool_results: list[ToolResult] = field(default_factory=list)
    internal_output: dict[str, Any] | None = None
