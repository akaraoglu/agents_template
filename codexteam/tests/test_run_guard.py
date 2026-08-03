from __future__ import annotations

import json

from codexteam_tools.run_guard import ExactFailedRepeatGuard


def _line(event: dict) -> str:
    return json.dumps(event)


def _command(
    value: str,
    output: str = "ok",
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


def _context_call() -> dict:
    return {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "codexteam-context",
            "tool": "get_task_context",
            "status": "completed",
        },
    }


def test_guard_interrupts_oversized_output_and_preserves_size():
    guard = ExactFailedRepeatGuard(max_command_output_bytes=32)

    decision = guard.observe_line(_line(_command("rg -n target src", "x" * 33)))

    assert decision is not None
    assert "exceeded 32 bytes (33 bytes)" in decision.reason
    assert "private turn JSONL" in decision.reason


def test_guard_blocks_broad_shell_discovery_after_bounded_context():
    guard = ExactFailedRepeatGuard()
    assert guard.observe_line(_line(_context_call())) is None

    decision = guard.observe_line(_line(_command("git status --short")))

    assert decision is not None
    assert "broad shell discovery" in decision.reason
    assert "CONTEXT GAP" in decision.reason


def test_guard_allows_scoped_shell_check_after_bounded_context():
    guard = ExactFailedRepeatGuard()
    assert guard.observe_line(_line(_context_call())) is None

    assert (
        guard.observe_line(
            _line(_command("git status --short -- src/main.py tests/test_main.py"))
        )
        is None
    )


def test_guard_still_interrupts_exact_failed_repeat_and_redacts_preview():
    guard = ExactFailedRepeatGuard()
    failed = _line(
        _command(
            "API_KEY=secret pytest -q",
            "same failure",
            exit_code=1,
            status="failed",
        )
    )

    assert guard.observe_line(failed) is None
    assert guard.observe_line(failed) is None
    decision = guard.observe_line(failed)

    assert decision is not None
    assert decision.count == 3
    assert "API_KEY=<redacted>" in decision.reason
    assert "secret" not in decision.reason


def test_guard_resets_repeat_streak_for_different_command_and_file_change():
    guard = ExactFailedRepeatGuard()
    failed = _line(_command("pytest -q", "failure", exit_code=1, status="failed"))
    other = _line(
        _command("pytest -q tests/test_other.py", "failure", exit_code=1, status="failed")
    )

    assert guard.observe_line(failed) is None
    assert guard.observe_line(failed) is None
    assert guard.observe_line(other) is None
    assert guard.observe_line(failed) is None
    assert guard.observe_line(failed) is None
    assert guard.observe_line(_line({"type": "item.completed", "item": {"type": "file_change"}})) is None
    assert guard.observe_line(failed) is None


def test_guard_does_not_treat_failed_context_call_as_routing_checkpoint():
    guard = ExactFailedRepeatGuard()
    failed_call = _context_call()
    failed_call["item"]["status"] = "failed"
    failed_call["item"]["error"] = "invalid arguments"

    assert guard.observe_line(_line(failed_call)) is None
    assert guard.observe_line(_line(_command("git status --short"))) is None
