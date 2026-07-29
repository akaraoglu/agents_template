import json

from codexteam_tools.run_guard import ExactFailedRepeatGuard


def event(item: dict) -> str:
    return json.dumps({"type": "item.completed", "item": item}) + "\n"


def command(
    value: str = "API_KEY=secret pytest -q",
    output: str = "same failure",
    *,
    exit_code: int = 1,
    status: str = "failed",
) -> str:
    return event(
        {
            "type": "command_execution",
            "command": value,
            "aggregated_output": output,
            "exit_code": exit_code,
            "status": status,
        }
    )


def test_exact_failed_repeat_guard_triggers_and_redacts_preview():
    guard = ExactFailedRepeatGuard()

    assert guard.observe_line(command()) is None
    assert guard.observe_line(command()) is None
    decision = guard.observe_line(command())

    assert decision is not None
    assert decision.count == 3
    assert "API_KEY=<redacted>" in decision.reason
    assert "secret" not in decision.reason
    assert guard.observe_line(command()) is None


def test_different_command_resets_failed_repeat_streak():
    guard = ExactFailedRepeatGuard()

    assert guard.observe_line(command()) is None
    assert guard.observe_line(command()) is None
    assert guard.observe_line(command("pytest -q tests/test_other.py")) is None
    assert guard.observe_line(command()) is None
    assert guard.observe_line(command()) is None


def test_file_change_resets_failed_repeat_streak():
    guard = ExactFailedRepeatGuard()

    assert guard.observe_line(command()) is None
    assert guard.observe_line(command()) is None
    assert guard.observe_line(event({"type": "file_change", "status": "completed"})) is None
    assert guard.observe_line(command()) is None
    assert guard.observe_line(command()) is None


def test_reasoning_does_not_hide_consecutive_failed_commands():
    guard = ExactFailedRepeatGuard()

    assert guard.observe_line(command()) is None
    assert guard.observe_line(event({"type": "reasoning", "text": "try again"})) is None
    assert guard.observe_line(command()) is None
    decision = guard.observe_line(command())

    assert decision is not None
    assert decision.count == 3


def test_passing_command_resets_failed_repeat_streak():
    guard = ExactFailedRepeatGuard()

    assert guard.observe_line(command()) is None
    assert guard.observe_line(command()) is None
    assert guard.observe_line(command(exit_code=0, status="completed")) is None
    assert guard.observe_line(command()) is None
    assert guard.observe_line(command()) is None
