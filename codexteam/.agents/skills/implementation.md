# Implementation Skill

## Purpose

Implement a bounded project change safely, verify it, and revise it in response to Project Lead feedback.

## When To Use

Use when assigned responsibility for source, related tests, scoped technical documentation, scripts, or configuration.

## Inputs Needed

- Current task handoff and acceptance criteria
- Existing source and tests
- Project constraints and accepted decisions
- Verification command
- Project Lead feedback for revision turns

## Workflow

1. Read the relevant files before editing and restate the bounded outcome internally.
2. Keep changes inside the project root and within the handoff's allowed paths.
3. Make the smallest coherent implementation that satisfies the task.
4. Prefer the standard library and established project patterns.
5. Add or update Developer-owned algorithm/unit, changed-area regression, and smoke tests when needed.
6. Run the configured Development Gate and self-review the diff. Do not claim integration acceptance.
7. Return a draft describing the outcome, exact evidence, uncertainties, and proposed disposition.
8. On feedback, preserve accepted work and change only the rejected part.
9. Update only scoped technical documentation. Propose status to the Project Lead; do not close canonical task state.

## Communication Example

Good: “Draft: the Fibonacci renderer and focused tests changed; 8 tests pass. CLI integration has not yet been independently verified.”

Bad: mark `TASKS.md` complete or claim delivery after running only local unit tests.

## Expected Output

- Source changes scoped to the current task
- Focused algorithm/unit and smoke checks plus Development Gate evidence
- A reviewable draft and, after acceptance, one accurate final result

## Validation

- Changed files are relevant and inside allowed paths.
- Tests pass or failures are reported with exact output.
- Accepted code is not churned during revisions.
- No secrets, generated caches, unrelated artifacts, or false state transitions are added.

## Common Mistakes

- Editing before reading
- Broad refactors during a bounded task
- Hiding failed checks
- Replacing accepted work while addressing narrow feedback
- Treating a developer draft as independently verified completion
- Creating a one-off helper script for a correction that can be made directly and reviewed plainly

## Related Files

- `.agents/skills/development-testing.md`
- `.agents/skills/subagent-orchestration.md`
- Active file under `management/tasks/`
