# Implementation Skill

## Purpose

Implement project changes safely inside the project workspace.

## When To Use

Use when writing or modifying source, tests, docs, scripts, configuration, or examples.

## Inputs Needed

- Current task
- Relevant requirements and acceptance criteria
- Existing source and tests
- Project constraints
- Verification command

## Workflow

1. Read the relevant files before editing.
2. Keep changes inside the project root.
3. Make the smallest coherent change that satisfies the current task.
4. Prefer standard library and existing project patterns.
5. Avoid new dependencies unless the operator approved them.
6. Add or update tests for behavior, not just implementation details.
7. Run focused verification.
8. Update project docs and task state with what changed.

## Expected Output

- Source changes scoped to the current task
- Tests or smoke checks for the behavior
- Updated project state docs

## Validation

- Changed files are relevant to the task.
- Tests pass or failures are documented with exact output.
- No files outside the project root changed.
- No secrets, generated caches, or unrelated artifacts are added.

## Common Mistakes

- Editing before reading.
- Adding dependencies to avoid simple code.
- Making broad refactors during an MVP task.
- Treating generated code as done without tests.
