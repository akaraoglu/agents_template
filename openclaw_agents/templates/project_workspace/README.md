# Project Workspace Template

This directory is the minimum per-project workspace scaffold for the new control-plane model.

## Purpose

Use one isolated workspace per project. The workspace is the operational surface for `Morpheus` and the internal software team. Project-local runtime state and project history live under `.agents/`, while the shared scheduler registry remains outside the project.

## Required Invariants

- One mutable workspace belongs to one project.
- `PROJECT.md` and `management/` are the human-readable source of truth inside the workspace.
- If workspace state and Zulip summaries disagree, fix the workspace first and mirror the correction through the gateway afterward.
- Switching away from a project is safe only after state and artifact refs are persisted.

## Minimum Structure

- `PROJECT.md`
- `management/STATUS.md`
- `management/MILESTONES.md`
- `management/BACKLOG.md`
- `management/DECISIONS.md`
- `management/TEST_REPORT.md`

## Recommended Structure

- `artifacts/outgoing/`
- `artifacts/reports/`
- `tests/`
- `.agents/project.db`
- `.agents/runtime/incoming/`
- `.agents/runtime/runtime_responses/`
- `.agents/openclaw/workspace/`
- `.agents/openclaw/agents/`

## How To Instantiate

1. Copy this template into a new project-specific workspace directory.
2. Replace every placeholder in `PROJECT.md` and `management/`.
3. Register the workspace in the control-plane database with a stable `workspace_ref`, `repo_root`, `branch_or_worktree_id`, and `last_clean_commit_or_checkpoint`.
4. Do not make the project schedulable until the workspace validates cleanly.

## Working Agreement

- `Niobe` owns project routing.
- `Morpheus` owns the software loop.
- `Planner`, `Implementer`, and `Tester` remain internal by default.
- `Oracle` verifies the project against the charter and acceptance evidence.
