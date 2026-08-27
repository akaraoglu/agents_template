"""
Integration tests for live Codex progress streaming (AC-07).

These tests exercise delayed fake-Codex JSONL streams through spawn.run_process
without modifying production source. They verify ordering, flushing, default
activity rendering, explicit off/assistant modes, redaction/bounded output,
malformed events, timeout cleanup, and unchanged private JSONL capture.
"""
from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import pytest

import src.codexteam_tools.spawn as spawn


def _write_fake_codex(tmp_path: Path, script_body: str) -> Path:
    fake = tmp_path / "fake-codex"
    fake.write_text(script_body)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake


def test_delayed_output_before_exit_and_ordering(tmp_path: Path, capsys):
    """Delayed JSONL events must be projected in order before process exit."""
    events = [
        {"type": "item.started", "item": {"type": "command_execution", "command": "echo first"}},
        {"type": "tool_use", "part": {"tool": "read", "state": {"status": "started", "input": {"filePath": "a.txt"}}}},
        {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed", "input": {"filePath": "a.txt"}}}},
    ]
    body = (
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        f"events = {events!r}\n"
        "for e in events:\n"
        "    print(json.dumps(e), flush=True)\n"
        "    time.sleep(0.05)\n"
    )
    fake = _write_fake_codex(tmp_path, body)

    result = spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), cwd=tmp_path,
        debug_stream="activity",
    )

    debug = capsys.readouterr().err
    idx_started = debug.find("[worker item] command_execution started")
    idx_tool_started = debug.find("[worker tool] read started")
    idx_tool_completed = debug.find("[worker tool] read completed")
    assert idx_started != -1 and idx_tool_started != -1 and idx_tool_completed != -1
    assert idx_started < idx_tool_started < idx_tool_completed
    assert "[worker process] completed" in debug
    assert result.stdout == "".join(json.dumps(e) + "\n" for e in events)


def test_default_activity_mode_and_explicit_off_and_assistant(tmp_path: Path, capsys):
    """Default activity rendering, explicit off suppresses output, assistant prints only text."""
    events_activity = [
        {"type": "tool_use", "part": {"tool": "bash", "state": {"status": "completed", "input": {"command": "echo hi"}}}},
        {"type": "text", "part": {"text": "Hello"}},
    ]
    body_act = (
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events_activity!r}\n"
        "for e in events: print(json.dumps(e), flush=True)\n"
    )
    fake = _write_fake_codex(tmp_path, body_act)
    spawn.run_process([str(fake)], prompt="", timeout_seconds=5, env=spawn.os.environ.copy(), debug_stream="activity")
    debug = capsys.readouterr().err
    assert "[worker tool] bash completed" in debug
    assert "[worker assistant]" in debug

    capsys.readouterr()
    spawn.run_process([str(fake)], prompt="", timeout_seconds=5, env=spawn.os.environ.copy(), debug_stream="off")
    debug_off = capsys.readouterr().err
    assert "[worker tool]" not in debug_off
    assert "[worker assistant]" not in debug_off

    events_assistant = [
        {"type": "text", "part": {"text": "Assistant line"}},
        {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed", "input": {"filePath": "secret.txt"}}}},
    ]
    body_assist = (
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events_assistant!r}\n"
        "for e in events: print(json.dumps(e), flush=True)\n"
    )
    fake2 = _write_fake_codex(tmp_path, body_assist)
    spawn.run_process([str(fake2)], prompt="", timeout_seconds=5, env=spawn.os.environ.copy(), debug_stream="assistant")
    debug_assist = capsys.readouterr().err
    assert "[worker assistant]" in debug_assist
    assert "Assistant line" in debug_assist
    assert "[worker tool]" not in debug_assist


def test_redaction_bounded_output_and_private_jsonl_unchanged(tmp_path: Path, capsys):
    """Redaction, bounded output, and private JSONL capture remain unchanged."""
    events_path = tmp_path / "events.jsonl"
    events = [
        {"type": "tool_use", "part": {"tool": "bash", "state": {
            "status": "completed",
            "input": {"command": "API_KEY=super-secret curl https://example.com", "workdir": str(tmp_path)},
            "output": "secret output",
        }}},
        {"type": "tool_use", "part": {"tool": "write", "state": {
            "status": "completed",
            "input": {"filePath": "out.txt", "content": "A" * 5000},
        }}},
    ]
    body = (
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events!r}\n"
        "for e in events: print(json.dumps(e), flush=True)\n"
    )
    fake = _write_fake_codex(tmp_path, body)
    result = spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), cwd=tmp_path,
        events_path=events_path,
        debug_stream="activity",
    )
    debug = capsys.readouterr().err
    assert "API_KEY=<redacted>" in debug
    assert "super-secret" not in debug
    assert "content: 5000 bytes" in debug
    assert "A" * 5000 not in debug
    assert events_path.read_text() == "".join(json.dumps(e) + "\n" for e in events)
    assert result.stdout == "".join(json.dumps(e) + "\n" for e in events)


def test_malformed_and_unknown_events_do_not_crash(tmp_path: Path, capsys):
    """Malformed JSON and unknown event types are tolerated."""
    body = (
        "#!/usr/bin/env python3\n"
        "print('NOT JSON', flush=True)\n"
        "import json\n"
        "print(json.dumps({'type':'unknown_type','part':{}}), flush=True)\n"
        "print(json.dumps({'type':'tool_use','part':{'tool':'unknown_tool','state':{'status':'completed'}}}), flush=True)\n"
    )
    fake = _write_fake_codex(tmp_path, body)
    result = spawn.run_process([str(fake)], prompt="", timeout_seconds=5, env=spawn.os.environ.copy(), debug_stream="activity")
    debug = capsys.readouterr().err
    assert "[worker process] completed" in debug
    assert "[worker tool] unknown_tool completed" in debug


def test_timeout_cleanup_and_partial_capture(tmp_path: Path, capsys):
    """Timeout kills process and drains output; private capture remains partial."""
    events_path = tmp_path / "events.jsonl"
    body = (
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        "for i in range(100):\n"
        "    print(json.dumps({'type':'step_start','part':{'step':i}}), flush=True)\n"
        "    time.sleep(0.1)\n"
    )
    fake = _write_fake_codex(tmp_path, body)
    start = time.monotonic()
    result = spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=0.25,
        env=spawn.os.environ.copy(), events_path=events_path,
        debug_stream="activity",
    )
    elapsed = time.monotonic() - start
    assert result.timed_out
    lines = events_path.read_text().splitlines()
    assert len(lines) > 0
    debug = capsys.readouterr().err
    assert "[worker process]" in debug


def test_unchanged_private_jsonl_capture_with_delayed_stream(tmp_path: Path):
    """Private JSONL capture is raw, ordered, and unchanged despite streaming."""
    events_path = tmp_path / "events.jsonl"
    events = [
        {"type": "thread.started"},
        {"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed", "input": {"filePath": "secret"}}}},
        {"type": "turn.completed"},
    ]
    body = (
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        f"events = {events!r}\n"
        "for e in events:\n"
        "    print(json.dumps(e), flush=True)\n"
        "    time.sleep(0.02)\n"
    )
    fake = _write_fake_codex(tmp_path, body)
    result = spawn.run_process(
        [str(fake)], prompt="", timeout_seconds=5,
        env=spawn.os.environ.copy(), events_path=events_path,
        debug_stream="off",
    )
    captured = [json.loads(l) for l in events_path.read_text().splitlines()]
    assert captured == events
    assert result.stdout == "".join(json.dumps(e) + "\n" for e in events)
