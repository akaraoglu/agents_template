from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from codexteam_tools.turn_metrics import (
    MODEL_STEP_LIMIT,
    TOOL_TYPE_LIMIT,
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

    assert summary["metric_scope"] == "worker_turn"
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


def test_codex_summary_retains_exact_top_level_shape_and_values():
    summary = summarize(
        jsonl(
            {"type": "item.completed", "item": {"type": "agent_message"}},
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 4,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 1,
                },
            },
        ),
        context_bytes={"worker_prompt_bytes": 999},
    )

    assert set(summary) == {
        "schema_version",
        "metric_scope",
        "task_id",
        "attempt_id",
        "agent_role",
        "model_profile",
        "source_event_file",
        "turn",
        "usage",
        "activity",
        "events",
        "generated_at",
    }
    assert summary["usage"] == {
        "cumulative": {
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "uncached_input_tokens": 6,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        },
        "delta": {
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "uncached_input_tokens": 6,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        },
        "delta_mode": "initial",
    }
    assert summary["activity"]["agent_messages"] == 1


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


def test_load_summary_accepts_records_with_and_without_additive_opencode_fields(
    tmp_path: Path,
):
    old_record = summarize(jsonl({"type": "turn.completed", "usage": {}}))
    new_record = summarize(
        jsonl({"type": "step_finish", "part": {"reason": "stop", "tokens": {}}}),
        backend="opencode",
        context_bytes={"lead_prompt_source_bytes": 4},
    )
    for name, record in (("old.metrics.json", old_record), ("new.metrics.json", new_record)):
        path = tmp_path / name
        path.write_text(json.dumps(record), encoding="utf-8")
        assert load_summary(path) == record


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


def test_opencode_summary_projects_per_turn_delta_and_adds_previous_cumulative():
    text = jsonl(
        {"type": "text", "sessionID": "ses-1", "part": {"text": "working"}},
        {"type": "tool_use", "sessionID": "ses-1", "part": {
            "tool": "read", "state": {"status": "completed"}
        }},
        {"type": "step_finish", "sessionID": "ses-1", "part": {
            "reason": "tool-calls",
            "tokens": {"input": 10, "output": 2, "reasoning": 1,
                       "cache": {"read": 3, "write": 1}},
        }},
        {"type": "step_finish", "sessionID": "ses-1", "part": {
            "reason": "stop",
            "tokens": {"input": 20, "output": 5, "reasoning": 2,
                       "cache": {"read": 4, "write": 2}},
        }},
    )
    summary = summarize(text, backend="opencode", previous_summary={
        "usage": {"cumulative": {"input_tokens": 999}}
    })
    assert summary["execution_backend"] == "opencode"
    assert summary["turn"]["completed"] is True
    assert summary["usage"]["cumulative"] == {
        "input_tokens": 1039,
        "cached_input_tokens": 7,
        "uncached_input_tokens": 33,
        "output_tokens": 10,
        "reasoning_output_tokens": 3,
    }
    assert summary["usage"]["delta"] == {
        "input_tokens": 40,
        "cached_input_tokens": 7,
        "uncached_input_tokens": 33,
        "output_tokens": 10,
        "reasoning_output_tokens": 3,
    }
    assert summary["usage"]["delta_mode"] == "per_turn"
    assert summary["model_steps"] == [
        {
            "ordinal": 1,
            "reason": "tool-calls",
            "input_tokens": 14,
            "cached_input_tokens": 3,
            "uncached_input_tokens": 11,
            "cache_write_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
        },
        {
            "ordinal": 2,
            "reason": "stop",
            "input_tokens": 26,
            "cached_input_tokens": 4,
            "uncached_input_tokens": 22,
            "cache_write_tokens": 2,
            "output_tokens": 7,
            "reasoning_output_tokens": 2,
        },
    ]
    assert summary["backend_usage"] == {
        "model_steps": 2,
        "first_step_input_tokens": 14,
        "last_step_input_tokens": 26,
        "max_step_input_tokens": 26,
        "cache_write_tokens": 3,
        "tool_text_output_bytes_by_tool": {},
    }
    assert summary["activity"]["tool_calls"] == 1
    assert summary["activity"]["item_type_counts"] == {
        "agent_message": 1,
        "tool:read": 1,
        "tool_use": 1,
    }


def test_opencode_metrics_require_stop_for_completion():
    summary = summarize(
        jsonl(
            {"type": "text", "sessionID": "ses-1", "part": {"text": "partial"}},
            {"type": "step_finish", "sessionID": "ses-1", "part": {
                "reason": "length", "tokens": {"input": 1, "output": 1}
            }},
        ),
        backend="opencode",
    )
    assert summary["turn"]["completed"] is False


def test_opencode_tool_metrics_classify_outputs_and_failures_without_raw_text():
    secret_outputs = {
        "read": "résumé",
        "bash": "private bash output",
        "edit": "edited",
        "write": "written",
    }
    text = jsonl(
        *[
            {
                "type": "tool_use",
                "part": {
                    "tool": tool,
                    "state": {
                        "status": "error" if tool == "bash" else "completed",
                        "output": output,
                        "metadata": {"exit_code": 7 if tool == "bash" else 0},
                    },
                },
            }
            for tool, output in secret_outputs.items()
        ]
    )

    summary = summarize(text, backend="opencode")

    assert summary["activity"]["tool_calls"] == 4
    assert summary["activity"]["failed_tool_calls"] == 1
    assert summary["activity"]["item_type_counts"] == {
        "tool:bash": 1,
        "tool:edit": 1,
        "tool:read": 1,
        "tool:write": 1,
        "tool_use": 4,
    }
    assert summary["backend_usage"]["tool_text_output_bytes_by_tool"] == {
        tool: len(output.encode("utf-8"))
        for tool, output in sorted(secret_outputs.items())
    }
    serialized = json.dumps(summary, ensure_ascii=False)
    assert all(output not in serialized for output in secret_outputs.values())


def test_context_bytes_are_opencode_only_and_unicode_safe():
    measurements = {
        "lead_prompt_source_bytes": len("café".encode("utf-8")),
        "worker_prompt_bytes": len("こんにちは".encode("utf-8")),
    }

    opencode = summarize("", backend="opencode", context_bytes=measurements)
    codex = summarize("", context_bytes=measurements)

    assert opencode["context_bytes"] == measurements
    assert "context_bytes" not in codex
    assert "model_steps" not in codex
    assert "backend_usage" not in codex


def test_opencode_usage_is_per_turn_delta_and_cumulative_across_turns():
    first = summarize(
        jsonl({
            "type": "step_finish",
            "part": {
                "reason": "stop",
                "tokens": {
                    "input": 10,
                    "output": 2,
                    "reasoning": 1,
                    "cache": {"read": 3, "write": 1},
                },
            },
        }),
        backend="opencode",
    )
    second = summarize(
        jsonl({
            "type": "step_finish",
            "part": {
                "reason": "stop",
                "tokens": {
                    "input": 4,
                    "output": 1,
                    "reasoning": 0,
                    "cache": {"read": 2, "write": 0},
                },
            },
        }),
        backend="opencode",
        turn_number=2,
        previous_summary=first,
    )

    assert second["usage"]["delta"] == {
        "input_tokens": 6,
        "cached_input_tokens": 2,
        "uncached_input_tokens": 4,
        "output_tokens": 1,
        "reasoning_output_tokens": 0,
    }
    assert second["usage"]["cumulative"] == {
        "input_tokens": 20,
        "cached_input_tokens": 5,
        "uncached_input_tokens": 15,
        "output_tokens": 4,
        "reasoning_output_tokens": 1,
    }
    assert second["usage"]["delta_mode"] == "per_turn"


def test_opencode_cumulative_usage_tolerates_old_or_reset_previous_summary():
    old = {"usage": {"cumulative": {"input_tokens": 100, "output_tokens": 9}}}
    summary = summarize(
        jsonl({
            "type": "step_finish",
            "part": {"reason": "stop", "tokens": {"input": 2, "output": 1}},
        }),
        backend="opencode",
        previous_summary=old,
    )

    assert summary["usage"]["delta"]["input_tokens"] == 2
    assert summary["usage"]["cumulative"] == {
        "input_tokens": 102,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 2,
        "output_tokens": 10,
        "reasoning_output_tokens": 0,
    }


def test_opencode_error_metrics_keep_only_bounded_name_and_data_message():
    summary = summarize(
        jsonl({
            "type": "error",
            "error": {
                "name": "ProviderError",
                "data": {
                    "message": "request failed",
                    "responseBody": "SECRET-BODY",
                    "headers": {"authorization": "SECRET-TOKEN"},
                },
                "metadata": {"private": "SECRET-METADATA"},
            },
        }),
        backend="opencode",
    )

    assert summary["events"]["last_error"] == "ProviderError: request failed"
    serialized = json.dumps(summary)
    assert "SECRET" not in serialized


def test_opencode_failed_bash_error_text_counts_as_output_without_persisting_text():
    error_text = "command failed: café"
    summary = summarize(
        jsonl({
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {
                    "status": "error",
                    "input": {"command": "false"},
                    "error": error_text,
                    "metadata": {"exit": 1},
                },
            },
        }),
        backend="opencode",
    )

    assert summary["activity"]["failed_tool_calls"] == 1
    assert summary["backend_usage"]["tool_text_output_bytes_by_tool"] == {
        "bash": len(error_text.encode("utf-8"))
    }
    assert error_text not in json.dumps(summary, ensure_ascii=False)


def test_opencode_observation_lists_are_bounded_and_sorted():
    steps = [
        {
            "type": "step_finish",
            "part": {"reason": "tool-calls", "tokens": {"input": index}},
        }
        for index in range(MODEL_STEP_LIMIT + 2)
    ]
    tools = [
        {
            "type": "tool_use",
            "part": {
                "tool": f"tool{index:03d}",
                "state": {"status": "completed", "output": "x"},
            },
        }
        for index in range(TOOL_TYPE_LIMIT + 2)
    ]
    summary = summarize(jsonl(*(steps + tools)), backend="opencode")

    assert summary["backend_usage"]["model_steps"] == MODEL_STEP_LIMIT + 2
    assert len(summary["model_steps"]) == MODEL_STEP_LIMIT
    assert summary["model_steps"][-1]["ordinal"] == MODEL_STEP_LIMIT
    by_tool = summary["backend_usage"]["tool_text_output_bytes_by_tool"]
    assert len(by_tool) == TOOL_TYPE_LIMIT
    assert list(by_tool) == sorted(by_tool)


def test_opencode_malformed_tokens_are_safely_zeroed():
    summary = summarize(
        jsonl({
            "type": "step_finish",
            "part": {
                "reason": {"unsafe": "object"},
                "tokens": {
                    "input": "ten",
                    "output": -2,
                    "reasoning": float("nan"),
                    "cache": {"read": True, "write": float("inf")},
                },
            },
        }),
        backend="opencode",
    )

    assert summary["model_steps"] == [{
        "ordinal": 1,
        "reason": "unknown",
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }]
