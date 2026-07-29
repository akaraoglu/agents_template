from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from codexteam_tools.lead_tracking import (
    TOOLKIT_ROOT,
    bind_session,
    capture_stop,
    set_pending_transition,
    stop_from_stdin,
)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _transcript(
    path: Path,
    events: list[tuple[str, dict[str, int]]],
    *,
    provider: str = "openai",
) -> None:
    lines = [
        json.dumps(
            {
                "timestamp": "2026-07-28T10:00:00Z",
                "type": "session_meta",
                "payload": {"model_provider": provider},
            }
        )
    ]
    lines.extend(
        json.dumps(
            {
                "timestamp": timestamp,
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": totals},
                },
            }
        )
        for timestamp, totals in events
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _payload(root: Path, transcript: Path, *, session: str = "session-1") -> dict[str, str]:
    return {
        "session_id": session,
        "hook_event_name": "Stop",
        "cwd": str(root),
        "transcript_path": str(transcript),
        "model": "gpt-5.6-luna",
        "turn_id": "turn-1",
    }


def _metrics(project: Path, task: str) -> dict:
    data = json.loads(
        (project / ".codexteam/runtime/lead-metrics.json").read_text(encoding="utf-8")
    )
    return data["tasks"][task]


def test_bind_uses_root_marker_and_first_stop_excludes_earlier_usage(tmp_path: Path):
    root = tmp_path / "codexteam"
    project = root / "projects" / "sample"
    project.mkdir(parents=True)
    marker = bind_session(
        project,
        "T001",
        session_id="session-1",
        lead_root=root,
        started_at=_time("2026-07-28T10:01:00Z"),
    )
    transcript = tmp_path / "turn.jsonl"
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:00:30Z",
                {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 10},
            ),
            (
                "2026-07-28T10:02:00Z",
                {"input_tokens": 130, "cached_input_tokens": 25, "output_tokens": 18},
            ),
        ],
    )

    assert marker.parent == root / ".codexteam/runtime/lead-sessions"
    assert capture_stop(
        _payload(root, transcript),
        lead_root=root,
        now=_time("2026-07-28T10:02:00Z"),
    ) == "captured"
    assert marker.exists()
    assert json.loads(marker.read_text(encoding="utf-8"))["baseline"]["input_tokens"] == 100
    record = _metrics(project, "T001")
    assert record["provider"] == "openai"
    assert record["profile"] == "gpt-5.6-luna"
    assert record["input_tokens"] == 30
    assert record["cached_input_tokens"] == 5
    assert record["output_tokens"] == 8


def test_ordinary_stops_keep_marker_and_update_cumulative_task_usage(tmp_path: Path):
    root = tmp_path / "codexteam"
    project = root / "projects" / "sample"
    project.mkdir(parents=True)
    marker = bind_session(
        project,
        "T001",
        session_id="session-1",
        lead_root=root,
        started_at=_time("2026-07-28T10:01:00Z"),
    )
    transcript = tmp_path / "turn.jsonl"
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:00:30Z",
                {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
            ),
            (
                "2026-07-28T10:02:00Z",
                {"input_tokens": 20, "cached_input_tokens": 4, "output_tokens": 8},
            ),
        ],
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "captured"

    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:00:30Z",
                {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
            ),
            (
                "2026-07-28T10:03:00Z",
                {"input_tokens": 30, "cached_input_tokens": 7, "output_tokens": 12},
            ),
        ],
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "captured"
    assert marker.exists()
    record = _metrics(project, "T001")
    assert record["input_tokens"] == 20
    assert record["cached_input_tokens"] == 5
    assert record["output_tokens"] == 9


def test_pending_transition_captures_old_task_then_starts_new_baseline(tmp_path: Path):
    root = tmp_path / "codexteam"
    project = root / "projects" / "sample"
    project.mkdir(parents=True)
    marker = bind_session(
        project,
        "T001",
        session_id="session-1",
        lead_root=root,
        started_at=_time("2026-07-28T10:01:00Z"),
    )
    transcript = tmp_path / "turn.jsonl"
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:00:30Z",
                {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
            ),
            (
                "2026-07-28T10:02:00Z",
                {"input_tokens": 20, "cached_input_tokens": 4, "output_tokens": 8},
            ),
        ],
    )
    assert set_pending_transition(
        project,
        "T001",
        "T002",
        session_id="session-1",
        lead_root=root,
    )
    assert capture_stop(
        _payload(root, transcript),
        lead_root=root,
        now=_time("2026-07-28T10:02:00Z"),
    ) == "captured"
    assert _metrics(project, "T001")["output_tokens"] == 5
    next_marker = json.loads(marker.read_text(encoding="utf-8"))
    assert next_marker["task_id"] == "T002"
    assert next_marker["baseline"]["output_tokens"] == 8
    assert "pending_transition" not in next_marker


def test_final_transition_removes_marker_after_capture(tmp_path: Path):
    root = tmp_path / "codexteam"
    project = root / "projects" / "sample"
    project.mkdir(parents=True)
    marker = bind_session(
        project,
        "T001",
        session_id="session-1",
        lead_root=root,
        started_at=_time("2026-07-28T10:01:00Z"),
    )
    transcript = tmp_path / "turn.jsonl"
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:00:30Z",
                {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
            ),
            (
                "2026-07-28T10:02:00Z",
                {"input_tokens": 20, "cached_input_tokens": 4, "output_tokens": 8},
            ),
        ],
    )
    assert set_pending_transition(
        project,
        "T001",
        None,
        session_id="session-1",
        lead_root=root,
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "captured"
    assert _metrics(project, "T001")["output_tokens"] == 5
    assert not marker.exists()


def test_unbound_mismatch_reset_and_missing_provider_preserve_data(tmp_path: Path):
    root = tmp_path / "codexteam"
    project = root / "projects" / "sample"
    project.mkdir(parents=True)
    transcript = tmp_path / "turn.jsonl"
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:02:00Z",
                {"input_tokens": 5, "cached_input_tokens": 1, "output_tokens": 2},
            )
        ],
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "unbound"

    marker = bind_session(
        project,
        "T001",
        session_id="session-1",
        lead_root=root,
        started_at=_time("2026-07-28T10:03:00Z"),
    )
    assert capture_stop(_payload(project, transcript), lead_root=root) == "mismatch"

    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    marker_data["baseline"] = {
        "input_tokens": 10,
        "cached_input_tokens": 2,
        "output_tokens": 3,
    }
    marker.write_text(json.dumps(marker_data), encoding="utf-8")
    assert capture_stop(_payload(root, transcript), lead_root=root) == "reset"

    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:04:00Z",
                {"input_tokens": 15, "cached_input_tokens": 3, "output_tokens": 5},
            )
        ],
        provider="",
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "no-provider"
    assert marker.exists()
    assert not (project / ".codexteam/runtime/lead-metrics.json").exists()


def test_malformed_pending_transition_preserves_last_valid_record(tmp_path: Path):
    root = tmp_path / "codexteam"
    project = root / "projects" / "sample"
    project.mkdir(parents=True)
    marker = bind_session(
        project,
        "T001",
        session_id="session-1",
        lead_root=root,
        started_at=_time("2026-07-28T10:01:00Z"),
    )
    transcript = tmp_path / "turn.jsonl"
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:00:30Z",
                {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3},
            ),
            (
                "2026-07-28T10:02:00Z",
                {"input_tokens": 20, "cached_input_tokens": 4, "output_tokens": 8},
            ),
        ],
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "captured"
    before = _metrics(project, "T001").copy()
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    marker_data["pending_transition"] = {}
    marker.write_text(json.dumps(marker_data), encoding="utf-8")
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:03:00Z",
                {"input_tokens": 30, "cached_input_tokens": 6, "output_tokens": 12},
            )
        ],
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "preserved"
    assert _metrics(project, "T001") == before


def test_boolean_baseline_is_rejected_without_writing_metrics(tmp_path: Path):
    root = tmp_path / "codexteam"
    project = root / "projects" / "sample"
    project.mkdir(parents=True)
    marker = bind_session(
        project,
        "T001",
        session_id="session-1",
        lead_root=root,
        started_at=_time("2026-07-28T10:01:00Z"),
    )
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    marker_data["baseline"] = {
        "input_tokens": True,
        "cached_input_tokens": 0,
        "output_tokens": 0,
    }
    marker.write_text(json.dumps(marker_data), encoding="utf-8")
    transcript = tmp_path / "turn.jsonl"
    _transcript(
        transcript,
        [
            (
                "2026-07-28T10:02:00Z",
                {"input_tokens": 5, "cached_input_tokens": 1, "output_tokens": 2},
            )
        ],
    )
    assert capture_stop(_payload(root, transcript), lead_root=root) == "invalid"
    assert not (project / ".codexteam/runtime/lead-metrics.json").exists()


def test_stop_stdin_is_fail_open_for_invalid_and_unbound_payloads():
    assert stop_from_stdin(io.StringIO("not json")) == 0
    assert stop_from_stdin(io.StringIO(json.dumps({"hook_event_name": "Stop"}))) == 0


def test_repository_stop_hook_runs_tracker_with_short_timeout():
    data = json.loads((TOOLKIT_ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))
    handler = data["hooks"]["Stop"][0]["hooks"][0]
    assert handler["type"] == "command"
    assert handler["command"].endswith("/codexteam/scripts/track-lead-task.py stop")
    assert handler["timeout"] == 2
