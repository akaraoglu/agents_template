# SDD Workflow Skill

## Purpose

Apply specification-driven development from initial request through delivery.

## When To Use

Use for project initiation, scope changes, feature work, bug fixes, and delivery decisions.

## Inputs Needed

- User goal
- Current project specification
- Open questions
- Existing code and tests
- Constraints and non-goals

## Workflow

1. Clarify: find missing details, ambiguous terms, and risky assumptions.
2. Specify: update `PROJECT.md`, `BRIEF.md`, and acceptance criteria.
3. Design: record architecture and implementation decisions in `DECISIONS.md`.
4. Plan: update `IMPLEMENTATION_PLAN.md`, `TASKS.md`, and `management/PLAN.md`.
5. Implement: make the smallest useful change inside the project root.
6. Test: run focused checks first, then broader checks when risk requires it.
7. Verify: compare results against acceptance criteria.
8. Report: update `PROJECT_STATE.md`, `DONE_REPORT.md`, `BLOCKED_REPORT.md`, or `RESULT.md`.

## Expected Output

- A testable specification before implementation
- A plan that can be executed task by task
- Verification evidence tied to acceptance criteria

## Validation

- Each implementation task traces back to at least one requirement or acceptance criterion.
- Each completed task has evidence.
- Any blocked work records the exact missing input or failed check.

## Common Mistakes

- Starting implementation before the MVP scope is testable.
- Letting docs drift from code.
- Treating a model-generated answer as evidence.
- Skipping verification because the change looks obvious.
