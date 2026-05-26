#!/usr/bin/env python3
"""Shared contracts for OpenClaw worker-runtime entrypoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerContract:
    role: str
    phase: str
    expected_from: str
    expected_to: str
    required_read_templates: tuple[str, ...]
    output_path_template: str
    draft_file_name: str
    verify_patterns: tuple[str, ...]
    blocked_codes: tuple[str, ...] = (
        "missing_input",
        "ambiguous_spec",
        "envelope_invalid",
        "capability_gap",
        "other",
    )

    @property
    def session_key(self) -> str:
        return f"agent:{self.expected_from}:main"

    def render_read_paths(self, *, task_id: str) -> tuple[str, ...]:
        return tuple(template.format(task_id=task_id) for template in self.required_read_templates)

    def render_output_path(self, *, task_id: str) -> str:
        return self.output_path_template.format(task_id=task_id)

    def render_verify_patterns(self, *, task_id: str) -> tuple[str, ...]:
        return tuple(pattern.format(task_id=task_id) for pattern in self.verify_patterns)

    def done_message(self, *, task_id: str, output_path: str) -> str:
        return f"DONE: {output_path} written for {task_id}."

    def blocked_message(self, *, code: str, reason: str) -> str:
        return f"BLOCKED[{code}]: {reason}"


@dataclass(frozen=True)
class PlanningProjectContract:
    role: str
    phase: str
    expected_from: str
    expected_to: str
    required_read_paths: tuple[str, ...]
    manifest_file_name: str
    draft_dir_name: str
    success_to: str
    blocked_to: str
    blocked_codes: tuple[str, ...] = (
        "missing_input",
        "ambiguous_spec",
        "envelope_invalid",
        "capability_gap",
        "verification_failed",
        "delivery_failed",
        "other",
    )
    allowed_artifact_patterns: tuple[str, ...] = (
        r"management/PLAN\.md",
        r"management/BACKLOG\.md",
        r"management/tasks/T\d{3}\.md",
        r"CURRENT_TASK\.md",
    )
    plan_patterns: tuple[str, ...] = (
        r"^## Overview",
        r"^## Phases",
    )

    @property
    def blocked_session_key(self) -> str:
        return f"agent:{self.blocked_to}:main"

    @property
    def success_session_key(self) -> str:
        return f"agent:{self.success_to}:main"

    def handoff_instructions(self, *, task_id: str) -> str:
        return (
            f"Task {task_id} is ready. Read CURRENT_TASK.md and management/tasks/{task_id}.md, "
            "then run Design -> Implement -> Verify for that task only. "
            "Report TASK_DONE or TASK_BLOCKED to Smith."
        )

    def ready_note(self, *, task_id: str) -> str:
        return f"Sequential plan created. {task_id} ready for Niaobe."

    def blocked_message(self, *, code: str, reason: str) -> str:
        return f"BLOCKED[{code}]: Smith planning failed. Reason: {reason}"


@dataclass(frozen=True)
class ArtifactWorkerContract:
    role: str
    phase: str
    expected_from: str
    expected_to: str
    required_read_templates: tuple[str, ...]
    manifest_file_name: str
    draft_dir_name: str
    exec_role: str = ""
    blocked_codes: tuple[str, ...] = (
        "missing_input",
        "ambiguous_spec",
        "envelope_invalid",
        "capability_gap",
        "verification_failed",
        "test_failed",
        "other",
    )

    @property
    def session_key(self) -> str:
        return f"agent:{self.expected_from}:main"

    def render_read_paths(self, *, task_id: str) -> tuple[str, ...]:
        return tuple(template.format(task_id=task_id) for template in self.required_read_templates)

    @property
    def project_exec_role(self) -> str:
        return self.exec_role or self.role

    def done_message(self, *, artifacts: list[str], test_command: list[str], test_summary: str) -> str:
        return (
            "DONE: "
            f"Artifacts={', '.join(artifacts)}. "
            f"Test summary={test_summary}. "
            f"Command={' '.join(test_command)}."
        )

    def blocked_message(self, *, code: str, reason: str) -> str:
        return f"BLOCKED: Reason={reason}. Evidence={code}. Needs=runtime or task input fix."


ARCHITECT_CONTRACT = WorkerContract(
    role="architect",
    phase="DESIGN",
    expected_from="niaobe",
    expected_to="architect",
    required_read_templates=(
        "PROJECT.md",
        "CURRENT_TASK.md",
        "management/tasks/{task_id}.md",
    ),
    output_path_template="management/architecture/{task_id}.md",
    draft_file_name="draft.md",
    verify_patterns=(
        "{task_id}",
        "^## Overview",
        "^## Approach",
        "^## File Changes",
        "^## Interfaces",
        "^## Risks",
        "^## Implementation Notes",
        "^## Test Strategy",
    ),
)


MORPHEUS_CONTRACT = ArtifactWorkerContract(
    role="morpheus",
    phase="IMPLEMENT",
    expected_from="niaobe",
    expected_to="morpheus",
    required_read_templates=(
        "PROJECT.md",
        "CURRENT_TASK.md",
        "management/tasks/{task_id}.md",
        "management/architecture/{task_id}.md",
    ),
    manifest_file_name="manifest.json",
    draft_dir_name="drafts",
    exec_role="implementer",
)


SMITH_PLANNING_CONTRACT = PlanningProjectContract(
    role="smith",
    phase="HANDOFF",
    expected_from="neo",
    expected_to="smith",
    required_read_paths=("PROJECT.md",),
    manifest_file_name="manifest.json",
    draft_dir_name="drafts",
    success_to="niaobe",
    blocked_to="neo",
)
