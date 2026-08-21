import pytest

from codexteam_tools.tasks import (
    TaskDocumentError, parse_task_document, parse_task_handoff_metadata,
    update_task_document,
)


TASKS = """# Tasks

| Task ID | Description | Status | Owner | Verification | Evidence |
|---------|-------------|--------|-------|--------------|----------|
| T001 | Specify project | Planned | Writer | Not run | None |
| T002 | Implement project | Planned | Developer | Not run | None |

## Task History

- initialized

## Notes

Preserve this section.
"""


def test_update_task_row_and_history_preserves_other_content():
    updated = update_task_document(
        TASKS,
        "T001",
        status="Completed",
        verification="Passed independently",
        evidence="`results/T001.json`",
        history="T001 closed",
    )
    row = parse_task_document(updated).row("T001")
    assert row.status == "Completed"
    assert row.evidence == "`results/T001.json`"
    assert "- T001 closed\n\n## Notes" in updated
    assert "Preserve this section." in updated


def test_update_is_idempotent_for_same_history():
    once = update_task_document(TASKS, "T001", status="Ready", history="T001 ready")
    twice = update_task_document(once, "T001", status="Ready", history="T001 ready")
    assert twice == once


def test_missing_task_fails_without_fallback():
    with pytest.raises(TaskDocumentError, match="not found"):
        update_task_document(TASKS, "T999", status="Completed")


def test_pipe_in_update_is_rejected():
    with pytest.raises(TaskDocumentError, match="delimiters"):
        update_task_document(TASKS, "T001", verification="pass | fail")


def test_malformed_table_fails():
    malformed = TASKS.replace("| T001 | Specify project | Planned | Writer | Not run | None |", "| T001 | too | few |")
    with pytest.raises(TaskDocumentError, match="exactly 6 columns"):
        parse_task_document(malformed)


def test_task_handoff_metadata_is_strict_and_machine_readable():
    metadata = parse_task_handoff_metadata(
        "## Task Write Scope\n\n- `src/**`\n- `results/**`\n\n"
        "## Context Mode\n\n- `direct`\n\n"
        "## Execution Class\n\n- `small`\n\n"
        "## Result Report\n\n- `results/task/report.md`\n\n"
        "## Direct Context\n\n- `src/main.py:1-20`\n\n"
        "## Verification Commands\n\n- `[\"node\", \"test.js\"]`\n"
    )
    assert metadata.task_write_scope == ("src/**", "results/**")
    assert metadata.context_mode == "direct"
    assert metadata.execution_class == "small"
    assert metadata.result_report == "results/task/report.md"
    assert metadata.direct_context == (("src/main.py", 1, 20),)
    assert metadata.verification_commands == (("node", "test.js"),)

    with pytest.raises(TaskDocumentError, match="Context Mode"):
        parse_task_handoff_metadata("## Context Mode\n\n- `broad`\n")

    with pytest.raises(TaskDocumentError, match="Result Report"):
        parse_task_handoff_metadata("## Context Mode\n\n- `direct`\n")

    with pytest.raises(TaskDocumentError, match="Execution Class"):
        parse_task_handoff_metadata("## Execution Class\n\n- `large`\n")
