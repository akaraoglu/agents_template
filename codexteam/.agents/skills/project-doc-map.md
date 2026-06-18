# Project Document Map Skill

## Purpose

Map normal operator language to the correct project document before reading or editing.

## When To Use

Use whenever the operator mentions a document indirectly, such as "project description", "task file", "plan", "status", "result", or "handoff".

## Document Map

- `PROJECT.md`: full project contract, goal, scope, requirements, acceptance criteria, constraints, verification plan, delivery criteria, and open questions.
- `BRIEF.md`: short operator-readable project summary.
- `README.md`: user-facing usage and run instructions for the delivered artifact.
- `TASKS.md`: task table, owner, handoff file, verification, and evidence.
- `IMPLEMENTATION_PLAN.md`: implementation phases, gates, and sequence.
- `DECISIONS.md`: durable project decisions and accepted tradeoffs.
- `OPEN_QUESTIONS.md`: unresolved questions that need operator input.
- `PROJECT_STATE.md`: current project status, phase, active task, and readiness.
- `CURRENT_TASK.md`: immediate working focus and next action.
- `RESULT.md`: verification commands, outputs, and result evidence.
- `DONE_REPORT.md`: completed work and final operator summary.
- `BLOCKED_REPORT.md`: blockers, failed checks, and missing decisions.
- `management/PLAN.md`: execution plan and team workflow.
- `management/BACKLOG.md`: ready queue, blocked queue, and handoff queue.
- `management/tasks/T001.md`: requirements and project skeleton handoff.
- `management/tasks/T002.md`: implementation handoff.
- `management/tasks/T003.md`: verification handoff.
- `management/tasks/T004.md`: final verification and delivery handoff.

## Language Mapping

- "project doc", "project file", "project contract", "project description" usually means `PROJECT.md`.
- "short summary", "brief" means `BRIEF.md`.
- "tasks", "task table", "team tasks" means `TASKS.md`.
- "task one", "T001", "requirements task" means `management/tasks/T001.md`.
- "task two", "T002", "implementation task" means `management/tasks/T002.md`.
- "task three", "T003", "test task" means `management/tasks/T003.md`.
- "task four", "T004", "delivery task" means `management/tasks/T004.md`.
- "plan" usually means `IMPLEMENTATION_PLAN.md`; if the request is about team execution order, use `management/PLAN.md`.
- "status" or "state" means `PROJECT_STATE.md`.
- "current task" means `CURRENT_TASK.md`.
- "questions" means `OPEN_QUESTIONS.md`.
- "decisions" means `DECISIONS.md`.
- "results" or "test output" means `RESULT.md`.
- "done report" means `DONE_REPORT.md`.
- "blocked" means `BLOCKED_REPORT.md`.

## Workflow

1. Map the user's wording to the likely document.
2. If exactly one document matches, read it before editing.
3. If multiple documents match, ask which one the operator means.
4. If no document matches, list project files or ask a focused question.
5. Use `document-editing.md` before making changes.

## Common Mistakes

- Guessing a path when the wording is ambiguous.
- Editing `PROJECT.md` when the user meant a task handoff file.
- Editing a task file when the user meant the task table.
- Updating docs from memory instead of reading the current file.
