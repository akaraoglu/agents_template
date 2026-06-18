# Project Initialization Skill

## Purpose

Initiate a real project with enough information for a team to implement it safely.

## When To Use

Use when the operator asks to create, start, initialize, or define a project.

## Inputs Needed

- Project name
- User goal
- Intended users or operators
- MVP scope
- Non-goals
- Constraints
- Preferred runtime or language, if any
- Verification expectation
- `.codexteam/skills/project-doc-map.md`
- `.codexteam/skills/document-editing.md`

## Workflow

1. Ask for missing details if the request is vague.
2. Create or update `PROJECT.md` with concrete sections:
   - Goal
   - Users / Operators
   - MVP Scope
   - Non-Goals
   - Requirements
   - Acceptance Criteria
   - Constraints
   - Architecture Notes
   - Verification Plan
   - Delivery Criteria
   - Open Questions
3. Update the initialization file set:
   - `PROJECT.md`: full project contract.
   - `BRIEF.md`: concise operator-readable summary.
   - `PROJECT_STATE.md`: current phase, selected project, and implementation readiness.
   - `CURRENT_TASK.md`: current focus and next required approval.
   - `OPEN_QUESTIONS.md`: unresolved questions or explicit closure.
   - `DECISIONS.md`: accepted assumptions and architecture choices.
   - `IMPLEMENTATION_PLAN.md`: phase plan and gates.
   - `TASKS.md`: task table with status, owner, verification, and evidence columns.
   - `management/PLAN.md`: execution order and handoff rules.
   - `management/BACKLOG.md`: ready queue and blocked queue.
   - `management/tasks/T001.md` through `T004.md`: task handoff contracts.
4. Create the initial task breakdown only after the spec is testable.
5. Stop and ask for approval before implementation starts.

## Expected Output

- Strong `PROJECT.md`
- Useful `BRIEF.md`
- Clear open questions or an explicit statement that none remain
- Initial task plan ready for approval
- Worker-ready task files with clear context, scope, allowed paths, outputs, verification, evidence, and stop conditions

## Validation

- Acceptance criteria are observable and testable.
- Requirements are specific enough to implement.
- Non-goals prevent scope drift.
- Verification plan names concrete checks.

## Common Mistakes

- Accepting a one-line goal as a complete spec.
- Filling unknowns with generic placeholders.
- Starting implementation without user approval.
- Creating tasks that do not map to acceptance criteria.
- Passing a task to the team without enough context to execute it independently.
