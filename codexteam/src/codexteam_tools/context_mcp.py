from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, TextIO

from .contracts import AGENT_ROLES
from .paths import PathValidationError
from .repository_context import (
    CHANGE_DETAIL_LEVELS,
    MAX_CHANGE_PATHS,
    MAX_REPOSITORY_RESULTS,
    REPOSITORY_SEARCH_MODES,
    REPOSITORY_SEARCH_SCOPES,
    RepositoryContextReader,
)
from .tasks import TaskDocumentError
from .team_context import (
    MAX_MEMORY_RESULTS,
    MEMORY_SCOPES,
    TeamContextError,
    TeamContextReader,
)
from .team_insights import (
    COST_PHASES,
    MAX_ATTEMPT_TURNS,
    MAX_COST_RESULTS,
    MAX_TASK_RESULTS,
    TeamInsightsReader,
)
from .test_gates import GateConfigError

PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")
SERVER_NAME = "codexteam-context-pilot"
SERVER_VERSION = "0.3.0"
BOUND_PROJECT_ENV = "CODEXTEAM_CONTEXT_PROJECT"
SERVER_INSTRUCTIONS = (
    "Read-only CodexTeam project context. Prefer one focused call over broad file reads. "
    "Treat returned source paths and SHA-256 values as provenance, not task authority."
)


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }


class ContextMcpServer:
    def __init__(
        self,
        reader: TeamContextReader,
        *,
        bound_project: str | None = None,
    ) -> None:
        self.reader = reader
        if bound_project is not None:
            reader.project_root(bound_project)
        self.bound_project = bound_project
        self.repository = RepositoryContextReader(reader)
        self.insights = TeamInsightsReader(reader, self.repository)
        self.legacy_protocol: str | None = None
        self.tools = (
            Tool(
                "get_active_task",
                "Get Active Task",
                "Return the canonical current-task fields, matching ledger row, and active attempts.",
                _object_schema(
                    {
                        "project": {
                            "type": "string",
                            "description": "Project directory name under the configured projects root.",
                        }
                    },
                    required=("project",),
                ),
                self._get_active_task,
            ),
            Tool(
                "get_project_overview",
                "Get Project Overview",
                "Return project progress, active work, attention items, gates, and Git state.",
                _object_schema(
                    {"project": {"type": "string"}},
                    required=("project",),
                ),
                self._get_project_overview,
            ),
            Tool(
                "list_tasks",
                "List Tasks",
                "Return bounded task rows filtered by status, owner, milestone, or attention.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "status": {"type": "string", "maxLength": 80},
                        "owner": {"type": "string", "maxLength": 120},
                        "milestone": {
                            "type": "string",
                            "pattern": "^M[0-9]{1,6}$",
                        },
                        "attention_only": {"type": "boolean", "default": False},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_TASK_RESULTS,
                            "default": 20,
                        },
                    },
                    required=("project",),
                ),
                self._list_tasks,
            ),
            Tool(
                "get_task_handoff",
                "Get Task Handoff",
                "Return one canonical task handoff as ordered sections plus its ledger row.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "task_id": {
                            "type": "string",
                            "pattern": "^T[0-9]{3,6}$",
                        },
                    },
                    required=("project", "task_id"),
                ),
                self._get_task_handoff,
            ),
            Tool(
                "get_task_context",
                "Get Task Context",
                "Return handoff, dependencies, role boundary, concurrent work, and gate commands.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "task_id": {
                            "type": "string",
                            "pattern": "^T[0-9]{3,6}$",
                        },
                        "role": {
                            "type": "string",
                            "enum": sorted(AGENT_ROLES),
                        },
                    },
                    required=("project", "task_id"),
                ),
                self._get_task_context,
            ),
            Tool(
                "get_attempt_summary",
                "Get Attempt Summary",
                "Return bounded attempt state, turn metrics, token deltas, and result fields.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "task_id": {
                            "type": "string",
                            "pattern": "^T[0-9]{3,6}$",
                        },
                        "attempt_id": {
                            "type": "string",
                            "pattern": "^att-[0-9]{3,6}$",
                        },
                        "max_turns": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_ATTEMPT_TURNS,
                            "default": 5,
                        },
                    },
                    required=("project", "task_id", "attempt_id"),
                ),
                self._get_attempt_summary,
            ),
            Tool(
                "get_gate_status",
                "Get Test Gate Status",
                "Return configured Development and Integration commands and validate record freshness.",
                _object_schema(
                    {"project": {"type": "string"}},
                    required=("project",),
                ),
                self._get_gate_status,
            ),
            Tool(
                "validate_result_record",
                "Validate Result Record",
                "Validate result identity, contract, and referenced evidence without returning process tails.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "task_id": {
                            "type": "string",
                            "pattern": "^T[0-9]{3,6}$",
                        },
                        "attempt_id": {
                            "type": "string",
                            "pattern": "^att-[0-9]{3,6}$",
                        },
                        "role": {
                            "type": "string",
                            "enum": sorted(AGENT_ROLES),
                        },
                    },
                    required=("project", "task_id", "attempt_id"),
                ),
                self._validate_result_record,
            ),
            Tool(
                "get_cost_hotspots",
                "Get Cost Hotspots",
                "Rank bounded turn metrics by input tokens with failed, repeated, and largest commands.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "task_id": {
                            "type": "string",
                            "pattern": "^T[0-9]{3,6}$",
                        },
                        "phase": {
                            "type": "string",
                            "enum": list(COST_PHASES),
                            "default": "all",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_COST_RESULTS,
                            "default": 10,
                        },
                    },
                    required=("project",),
                ),
                self._get_cost_hotspots,
            ),
            Tool(
                "search_team_memory",
                "Search Team Memory",
                "Search bounded project decisions and configured CodexTeam memory; return ranked source-backed entries.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "scope": {
                            "type": "string",
                            "enum": list(MEMORY_SCOPES),
                            "default": "all",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_MEMORY_RESULTS,
                            "default": 3,
                        },
                    },
                    required=("project", "query"),
                ),
                self._search_team_memory,
            ),
            Tool(
                "search_repository",
                "Search Repository",
                "Return ranked, bounded source matches without broad file output.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "mode": {
                            "type": "string",
                            "enum": list(REPOSITORY_SEARCH_MODES),
                            "default": "fixed",
                        },
                        "scope": {
                            "type": "string",
                            "enum": list(REPOSITORY_SEARCH_SCOPES),
                            "default": "all",
                        },
                        "case_sensitive": {
                            "type": "boolean",
                            "default": False,
                        },
                        "path": {"type": "string", "maxLength": 240},
                        "file_glob": {"type": "string", "maxLength": 120},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_REPOSITORY_RESULTS,
                            "default": 10,
                        },
                    },
                    required=("project", "query"),
                ),
                self._search_repository,
            ),
            Tool(
                "get_change_summary",
                "Get Change Summary",
                "Return bounded Git status, diff statistics, suspicious paths, and optional excerpts.",
                _object_schema(
                    {
                        "project": {"type": "string"},
                        "detail": {
                            "type": "string",
                            "enum": list(CHANGE_DETAIL_LEVELS),
                            "default": "summary",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_CHANGE_PATHS,
                            "default": 40,
                        },
                    },
                    required=("project",),
                ),
                self._get_change_summary,
            ),
        )
        if self.bound_project is not None:
            self.tools = tuple(
                replace(tool, input_schema=_without_project(tool.input_schema))
                for tool in self.tools
            )
        self._tools_by_name = {tool.name: tool for tool in self.tools}

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(request_id, -32600, "Invalid Request")
        if "id" not in message:
            self._handle_notification(method)
            return None
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            return _error(None, -32600, "Invalid Request")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return _error(request_id, -32602, "Invalid params")
        if method == "initialize":
            return self._initialize_legacy(request_id, params)

        version_error = self._validate_modern_version(request_id, params)
        if version_error is not None:
            return version_error
        if method == "server/discover":
            return _result(request_id, self._discover())
        if method == "tools/list":
            return _result(request_id, self._list_tools())
        if method == "tools/call":
            return self._call_tool(request_id, params)
        return _error(request_id, -32601, f"Method not found: {method}")

    def serve(self, input_stream: TextIO, output_stream: TextIO) -> int:
        for raw_line in input_stream:
            try:
                message = json.loads(raw_line)
            except json.JSONDecodeError:
                response = _error(None, -32700, "Parse error")
            else:
                response = self.handle(message)
            if response is not None:
                output_stream.write(
                    json.dumps(response, separators=(",", ":"), ensure_ascii=True) + "\n"
                )
                output_stream.flush()
        return 0

    def _discover(self) -> dict[str, Any]:
        return {
            "resultType": "complete",
            "supportedVersions": [PROTOCOL_VERSION],
            "capabilities": {"tools": {"listChanged": False}},
            "_meta": _server_meta(),
            "instructions": self._instructions(),
            "ttlMs": 300_000,
            "cacheScope": "public",
        }

    def _list_tools(self) -> dict[str, Any]:
        result = {
            "tools": [tool.definition() for tool in self.tools],
        }
        if self.legacy_protocol is None:
            result.update(
                {
                    "resultType": "complete",
                    "_meta": _server_meta(),
                    "ttlMs": 300_000,
                    "cacheScope": "public",
                }
            )
        return result

    def _call_tool(
        self,
        request_id: str | int,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, -32602, "Malformed tools/call request")
        tool = self._tools_by_name.get(name)
        if tool is None:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        started = time.perf_counter()
        try:
            _validate_arguments(tool.input_schema, arguments)
            handler_arguments = dict(arguments)
            if self.bound_project is not None:
                handler_arguments["project"] = self.bound_project
            value = tool.handler(handler_arguments)
        except (
            GateConfigError,
            OSError,
            PathValidationError,
            TaskDocumentError,
            TeamContextError,
            ValueError,
        ) as exc:
            value = _with_query_stats(
                {"error": str(exc)},
                started=started,
            )
            return _result(request_id, self._tool_result(value, is_error=True))
        value = _with_query_stats(value, started=started)
        return _result(request_id, self._tool_result(value, is_error=False))

    def _tool_result(self, value: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        value,
                        separators=(",", ":"),
                        sort_keys=True,
                        ensure_ascii=True,
                    ),
                }
            ],
            "structuredContent": value,
            "isError": is_error,
        }
        if self.legacy_protocol is None:
            result["resultType"] = "complete"
            result["_meta"] = _server_meta()
        return result

    def _initialize_legacy(
        self,
        request_id: str | int,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        if requested not in LEGACY_PROTOCOL_VERSIONS:
            return _error(
                request_id,
                -32602,
                f"This server supports modern MCP {PROTOCOL_VERSION}; "
                f"legacy compatibility is limited to {', '.join(LEGACY_PROTOCOL_VERSIONS)}",
            )
        self.legacy_protocol = str(requested)
        return _result(
            request_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": self._instructions(),
            },
        )

    def _instructions(self) -> str:
        if self.bound_project is None:
            return SERVER_INSTRUCTIONS
        return (
            SERVER_INSTRUCTIONS
            + " This worker server is bound to its current project; tool calls do not "
            "accept a project argument."
        )

    def _validate_modern_version(
        self,
        request_id: str | int,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.legacy_protocol is not None:
            return None
        meta = params.get("_meta")
        if not isinstance(meta, dict):
            return _error(request_id, -32602, "Missing required request _meta")
        requested = meta.get("io.modelcontextprotocol/protocolVersion")
        capabilities = meta.get("io.modelcontextprotocol/clientCapabilities")
        if requested != PROTOCOL_VERSION:
            return _error(
                request_id,
                -32022,
                "Unsupported protocol version",
                data={"supported": [PROTOCOL_VERSION], "requested": requested},
            )
        if not isinstance(capabilities, dict):
            return _error(
                request_id,
                -32602,
                "Missing io.modelcontextprotocol/clientCapabilities",
            )
        return None

    def _handle_notification(self, method: str) -> None:
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return

    def _get_active_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.reader.get_active_task(arguments["project"])

    def _get_project_overview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.insights.get_project_overview(arguments["project"])

    def _list_tasks(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.insights.list_tasks(
            arguments["project"],
            status=arguments.get("status"),
            owner=arguments.get("owner"),
            milestone=arguments.get("milestone"),
            attention_only=arguments.get("attention_only", False),
            limit=arguments.get("limit", 20),
        )

    def _get_task_handoff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.reader.get_task_handoff(
            arguments["project"],
            arguments["task_id"],
        )

    def _get_task_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.insights.get_task_context(
            arguments["project"],
            arguments["task_id"],
            role=arguments.get("role"),
        )

    def _get_attempt_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.insights.get_attempt_summary(
            arguments["project"],
            arguments["task_id"],
            arguments["attempt_id"],
            max_turns=arguments.get("max_turns", 5),
        )

    def _get_gate_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.reader.get_gate_status(arguments["project"])

    def _validate_result_record(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.insights.validate_result_record(
            arguments["project"],
            arguments["task_id"],
            arguments["attempt_id"],
            role=arguments.get("role"),
        )

    def _get_cost_hotspots(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.insights.get_cost_hotspots(
            arguments["project"],
            task_id=arguments.get("task_id"),
            phase=arguments.get("phase", "all"),
            limit=arguments.get("limit", 10),
        )

    def _search_team_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.reader.search_team_memory(
            arguments["project"],
            arguments["query"],
            scope=arguments.get("scope", "all"),
            limit=arguments.get("limit", 3),
        )

    def _search_repository(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.repository.search_repository(
            arguments["project"],
            arguments["query"],
            mode=arguments.get("mode", "fixed"),
            scope=arguments.get("scope", "all"),
            case_sensitive=arguments.get("case_sensitive", False),
            path=arguments.get("path"),
            file_glob=arguments.get("file_glob"),
            limit=arguments.get("limit", 10),
        )

    def _get_change_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.repository.get_change_summary(
            arguments["project"],
            detail=arguments.get("detail", "summary"),
            limit=arguments.get("limit", 40),
        )


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _without_project(schema: dict[str, Any]) -> dict[str, Any]:
    properties = dict(schema["properties"])
    if "project" not in properties:
        return schema
    del properties["project"]
    return {
        **schema,
        "properties": properties,
        "required": [name for name in schema["required"] if name != "project"],
    }


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    properties = schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise TeamContextError(f"unknown arguments: {', '.join(unknown)}")
    missing = [name for name in schema["required"] if name not in arguments]
    if missing:
        raise TeamContextError(f"missing arguments: {', '.join(missing)}")
    for name, value in arguments.items():
        field = properties[name]
        expected = field.get("type")
        if expected == "string":
            if not isinstance(value, str):
                raise TeamContextError(f"{name} must be a string")
            if "minLength" in field and len(value) < field["minLength"]:
                raise TeamContextError(f"{name} is too short")
            if "maxLength" in field and len(value) > field["maxLength"]:
                raise TeamContextError(f"{name} is too long")
            if "pattern" in field and re.fullmatch(field["pattern"], value) is None:
                raise TeamContextError(f"{name} has invalid format")
            if "enum" in field and value not in field["enum"]:
                raise TeamContextError(f"{name} must be one of: {', '.join(field['enum'])}")
        elif expected == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise TeamContextError(f"{name} must be an integer")
            if value < field.get("minimum", value) or value > field.get("maximum", value):
                raise TeamContextError(f"{name} is outside the allowed range")
        elif expected == "boolean":
            if not isinstance(value, bool):
                raise TeamContextError(f"{name} must be a boolean")


def _with_query_stats(
    value: dict[str, Any],
    *,
    started: float,
) -> dict[str, Any]:
    result = dict(value)
    stats: dict[str, Any] = {
        "duration_ms": 0.0,
        "returned_bytes": 0,
        "source_bytes": _source_bytes(result),
        "cache_hit": False,
    }
    result["query_stats"] = stats
    for _ in range(4):
        stats["duration_ms"] = round((time.perf_counter() - started) * 1_000, 3)
        stats["returned_bytes"] = len(
            json.dumps(
                result,
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=True,
            ).encode("utf-8")
        )
    return result


def _source_bytes(value: Any) -> int:
    sources: dict[str, int] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            path = item.get("path")
            digest = item.get("sha256")
            size = item.get("bytes")
            if (
                isinstance(path, str)
                and isinstance(digest, str)
                and isinstance(size, int)
                and not isinstance(size, bool)
            ):
                sources[path] = size
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return sum(sources.values())


def _server_meta() -> dict[str, dict[str, str]]:
    return {
        "io.modelcontextprotocol/serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        }
    }


def _result(request_id: str | int, value: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(
    request_id: str | int | None,
    code: int,
    message: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def modern_meta() -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {
            "name": "codexteam-context-pilot-test",
            "version": SERVER_VERSION,
        },
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Read-only CodexTeam context MCP server ({PROTOCOL_VERSION})."
    )
    parser.add_argument(
        "--projects-root",
        required=True,
        type=Path,
        help="Directory containing allowed CodexTeam projects",
    )
    parser.add_argument(
        "--team-memory-root",
        type=Path,
        help="Optional directory containing read-only CodexTeam memory Markdown",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        reader = TeamContextReader(
            args.projects_root,
            team_memory_root=args.team_memory_root,
        )
        bound_project = os.environ.get(BOUND_PROJECT_ENV)
        if bound_project is not None and not bound_project.strip():
            raise TeamContextError(f"{BOUND_PROJECT_ENV} must not be empty")
        server = ContextMcpServer(reader, bound_project=bound_project)
    except (OSError, PathValidationError, TeamContextError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return server.serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
