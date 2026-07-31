from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from codexteam_tools.turn_metrics import (
    backfill_project,
    load_summary,
    metrics_path,
    previous_summary,
    summarize_turn,
    write_summary,
)


def jsonl(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def command(
    value: str,
    output: str,
    *,
    exit_code: int = 0,
    status: str = "completed",
) -> dict:
    return {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": value,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": status,
        },
    }


def summarize(text: str, **overrides) -> dict:
    values = {
        "task_id": "T001",
        "attempt_id": "att-001",
        "role": "developer",
        "profile": "gpt54-mini",
        "turn_number": 1,
        "phase": "draft",
        "duration_seconds": 12.3456,
        "source_event_file": "001-draft.jsonl",
        "generated_at": "2026-07-23T10:00:00Z",
    }
    values.update(overrides)
    return summarize_turn(text, **values)


def test_summary_records_tool_cycles_deltas_repeats_and_redacted_previews():
    text = jsonl(
        command("API_KEY=alpha tool run", "one\n"),
        command("API_KEY=beta tool run", "éé"),
        command("tool noisy", "x" * 20, exit_code=2),
        command("tool medium", "y" * 10),
        {
            "type": "item.completed",
            "item": {"type": "file_change", "status": "completed"},
        },
        {
            "type": "item.completed",
            "item": {"type": "web_search", "status": "failed"},
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "done"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1000,
                "cached_input_tokens": 700,
                "output_tokens": 80,
                "reasoning_output_tokens": 30,
            },
        },
    ) + "not-json\n"

    summary = summarize(text)

    assert summary["turn"] == {
        "number": 1,
        "phase": "draft",
        "completed": True,
        "duration_seconds": 12.346,
    }
    assert summary["usage"]["cumulative"]["uncached_input_tokens"] == 300
    assert summary["usage"]["delta"] == summary["usage"]["cumulative"]
    assert summary["usage"]["delta_mode"] == "initial"
    activity = summary["activity"]
    assert activity["tool_calls"] == 6
    assert activity["failed_tool_calls"] == 2
    assert activity["command_calls"] == 4
    assert activity["failed_command_calls"] == 1
    assert activity["edit_events"] == 1
    assert activity["agent_messages"] == 1
    assert activity["command_output_bytes"] == 38
    assert activity["max_command_output_bytes"] == 20
    assert [item["output_bytes"] for item in activity["largest_commands"]] == [20, 10, 4]
    assert activity["repeated_commands"][0]["count"] == 2
    assert "alpha" not in json.dumps(activity)
    assert "beta" not in json.dumps(activity)
    assert "<redacted>" in activity["repeated_commands"][0]["preview"]
    assert summary["events"]["parse_error_count"] == 1


def test_summary_derives_delta_from_previous_cumulative_usage():
    first = summarize(
        jsonl(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 60,
                    "output_tokens": 10,
                },
            }
        )
    )
    second = summarize(
        jsonl(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 175,
                    "cached_input_tokens": 110,
                    "output_tokens": 18,
                },
            }
        ),
        turn_number=2,
        phase="feedback",
        source_event_file="002-feedback.jsonl",
        previous_summary=first,
    )

    assert second["usage"]["delta"] == {
        "input_tokens": 75,
        "cached_input_tokens": 50,
        "uncached_input_tokens": 25,
        "output_tokens": 8,
        "reasoning_output_tokens": None,
    }
    assert second["usage"]["delta_mode"] == "cumulative"

    reset = summarize(
        jsonl(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 50,
                    "cached_input_tokens": 20,
                    "output_tokens": 5,
                },
            }
        ),
        turn_number=3,
        phase="final",
        source_event_file="003-final.jsonl",
        previous_summary=second,
    )
    assert reset["usage"]["delta_mode"] == "reset_or_non_monotonic"
    assert reset["usage"]["delta"]["input_tokens"] is None


def test_summary_aggregates_mcp_calls_without_persisting_payloads():
    text = jsonl(
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "codexteam-context",
                "tool": "get_project_overview",
                "arguments": {"project": "private-project"},
                "result": {
                    "content": [{"type": "text", "text": "private-result"}],
                    "structured_content": {
                        "query_stats": {
                            "duration_ms": 12.25,
                            "returned_bytes": 400,
                            "source_bytes": 1200,
                            "cache_hit": True,
                        }
                    },
                    "isError": False,
                },
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "codexteam-context",
                "tool": "search_repository",
                "arguments": {"query": "private-query"},
                "result": {"isError": True},
                "error": "query failed",
                "status": "failed",
            },
        },
        command("rg fallback", "fallback output"),
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 250,
                "cached_input_tokens": 200,
                "output_tokens": 20,
            },
        },
    )

    summary = summarize(text)
    activity = summary["activity"]
    mcp = activity["mcp"]

    assert activity["tool_calls"] == 3
    assert activity["failed_tool_calls"] == 1
    assert mcp == {
        "calls": 2,
        "failed_calls": 1,
        "server_duration_ms": 12.25,
        "client_duration_ms": 0.0,
        "returned_bytes": 400,
        "source_bytes": 1200,
        "response_bytes": 202,
        "cache_hits": 1,
        "max_returned_bytes": 400,
        "max_response_bytes": 186,
        "command_calls_after_failure": 1,
        "repeated_tools": [],
        "by_tool": [
            {
                "server": "codexteam-context",
                "tool": "get_project_overview",
                "calls": 1,
                "failed_calls": 0,
                "server_duration_ms": 12.25,
                "client_duration_ms": 0.0,
                "returned_bytes": 400,
                "source_bytes": 1200,
                "response_bytes": 186,
                "cache_hits": 1,
            },
            {
                "server": "codexteam-context",
                "tool": "search_repository",
                "calls": 1,
                "failed_calls": 1,
                "server_duration_ms": 0.0,
                "client_duration_ms": 0.0,
                "returned_bytes": 0,
                "source_bytes": 0,
                "response_bytes": 16,
                "cache_hits": 0,
            },
        ],
    }
    serialized = json.dumps(summary)
    assert "private-project" not in serialized
    assert "private-result" not in serialized
    assert "private-query" not in serialized


def test_summary_identifies_repeated_mcp_tools():
    call = {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "playwright",
            "tool": "browser_snapshot",
            "result": {"content": [{"type": "text", "text": "page"}]},
            "status": "completed",
        },
    }

    mcp = summarize(jsonl(call, call))["activity"]["mcp"]

    assert mcp["repeated_tools"] == [
        {"server": "playwright", "tool": "browser_snapshot", "calls": 2}
    ]
    assert mcp["response_bytes"] == 86


def test_summary_reads_internal_rollout_mcp_and_usage_events():
    text = jsonl(
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 55248,
                        "cached_input_tokens": 34944,
                        "output_tokens": 1611,
                        "reasoning_output_tokens": 973,
                    }
                },
            },
        },
        {
            "type": "response_item",
            "payload": {"type": "tool_search_call", "status": "completed"},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "mcp_tool_call_end",
                "invocation": {
                    "server": "codexteam-context",
                    "tool": "get_task_context",
                    "arguments": {"task_id": "T142"},
                },
                "duration": {"secs": 0, "nanos": 151892000},
                "result": {
                    "Ok": {
                        "structuredContent": {
                            "query_stats": {
                                "duration_ms": 24.44,
                                "returned_bytes": 4551,
                                "source_bytes": 78051,
                                "cache_hit": False,
                            }
                        },
                        "isError": False,
                    }
                },
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "mcp_tool_call_end",
                "invocation": {
                    "server": "other-server",
                    "tool": "unavailable",
                    "arguments": {},
                },
                "duration": {"secs": 1, "nanos": 500000},
                "result": {"Err": "not available"},
            },
        },
        {
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "done"},
        },
        {
            "type": "event_msg",
            "payload": {"type": "task_complete", "duration_ms": 29511},
        },
    )

    summary = summarize(text)
    activity = summary["activity"]
    mcp = activity["mcp"]

    assert summary["turn"]["completed"] is True
    assert summary["usage"]["cumulative"]["uncached_input_tokens"] == 20304
    assert activity["tool_calls"] == 3
    assert activity["failed_tool_calls"] == 1
    assert activity["agent_messages"] == 1
    assert mcp["calls"] == 2
    assert mcp["failed_calls"] == 1
    assert mcp["server_duration_ms"] == 24.44
    assert mcp["client_duration_ms"] == 1152.392
    assert mcp["returned_bytes"] == 4551
    assert mcp["source_bytes"] == 78051
    assert mcp["response_bytes"] > 0
    assert mcp["max_response_bytes"] > 0
    assert mcp["by_tool"][0]["tool"] == "get_task_context"
    assert mcp["by_tool"][1]["failed_calls"] == 1


def test_summary_write_is_private_validated_and_not_silently_overwritten(tmp_path: Path):
    path = tmp_path / "001-draft.metrics.json"
    summary = summarize(jsonl({"type": "turn.completed", "usage": {}}))

    write_summary(path, summary)

    assert load_summary(path) == summary
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_summary(path, summary)
    path.write_text('{"schema_version":"wrong"}\n', encoding="utf-8")
    assert load_summary(path) is None


def test_previous_summary_falls_back_to_legacy_event_usage(tmp_path: Path):
    (tmp_path / "001-draft.jsonl").write_text(
        jsonl(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 90,
                    "cached_input_tokens": 70,
                    "output_tokens": 4,
                },
            }
        ),
        encoding="utf-8",
    )

    prior = previous_summary(tmp_path, 2)

    assert prior["usage"]["cumulative"]["input_tokens"] == 90
    assert prior["usage"]["cumulative"]["uncached_input_tokens"] == 20


def test_backfill_previews_then_writes_missing_sidecars(tmp_path: Path):
    project = tmp_path / "project"
    turns = project / ".codexteam/runtime/sessions/team/T001/att-001/turns"
    turns.mkdir(parents=True)
    session = turns.parent / "session.json"
    session.write_text(
        json.dumps(
            {
                "task_id": "T001",
                "attempt_id": "att-001",
                "agent_role": "developer",
                "model_profile": "gpt54-mini",
                "turns": [
                    {"number": 1, "duration_seconds": 2},
                    {"number": 2, "duration_seconds": 3},
                ],
            }
        ),
        encoding="utf-8",
    )
    first = turns / "001-draft.jsonl"
    second = turns / "002-feedback.jsonl"
    first.write_text(
        jsonl(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 60,
                    "output_tokens": 10,
                },
            }
        ),
        encoding="utf-8",
    )
    second.write_text(
        jsonl(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 180,
                    "cached_input_tokens": 120,
                    "output_tokens": 15,
                },
            }
        ),
        encoding="utf-8",
    )

    preview = backfill_project(project)

    assert [item["action"] for item in preview] == ["would_create", "would_create"]
    assert not metrics_path(first).exists()
    written = backfill_project(project, write=True)
    assert [item["action"] for item in written] == ["created", "created"]
    assert load_summary(metrics_path(second))["usage"]["delta"]["input_tokens"] == 80
    assert [item["action"] for item in backfill_project(project)] == ["exists", "exists"]
    with pytest.raises(ValueError, match="requires --write"):
        backfill_project(project, overwrite=True)
