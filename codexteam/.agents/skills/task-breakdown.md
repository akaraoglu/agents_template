# Task Breakdown Skill

## Purpose

Turn a project specification into implementation tasks that can be executed, tested, and reviewed.

## When To Use

Use after `PROJECT.md` has a concrete MVP scope and acceptance criteria, or when the operator asks to replan work.

## Inputs Needed

- `PROJECT.md`
- `IMPLEMENTATION_PLAN.md`
- `TASKS.md`
- `management/BACKLOG.md`
- `.codexteam/skills/project-doc-map.md`
- `.codexteam/skills/document-editing.md`
- Current code state
- Known blockers

## Workflow

1. Identify the smallest deliverable MVP path.
2. Split work into sequential tasks with clear ownership and evidence.
3. Keep task IDs stable when possible.
4. Make each task independently reviewable.
5. Define expected files, checks, and acceptance evidence for each task.
6. Record dependencies explicitly.
7. Update `TASKS.md`, `management/BACKLOG.md`, and `management/tasks/T*.md`.
8. Treat each `management/tasks/T*.md` file as the contract passed to the team.

## Task Handoff Contract

Each task file must include:

- Objective: one concrete outcome.
- Context: docs and files the worker must read first.
- Scope: what is included and excluded.
- Allowed paths: where the worker may edit.
- Required outputs: files or state that must exist when done.
- Verification: exact checks or evidence expected.
- Done criteria: observable completion rules.
- Stop conditions: when to stop and ask instead of guessing.
- Reporting: what evidence to write back.

## Expected Output

- Ordered task list
- Per-task goal, scope, files, verification, and done criteria
- Explicit blockers and dependencies
- Worker-ready task files that can be executed without chat history

## Validation

- Every acceptance criterion is covered by at least one task.
- No task requires hidden knowledge from chat only.
- No task is so broad that verification is unclear.
- Each task file has enough information for a different agent to run it safely.

## Common Mistakes

- Creating vague tasks like "finish app."
- Splitting by file instead of by user-visible behavior.
- Hiding critical requirements in task descriptions only.
- Replanning without preserving useful task history.
