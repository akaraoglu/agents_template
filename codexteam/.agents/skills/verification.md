# Verification Skill

## Purpose

Prove that project work satisfies the acceptance criteria.

## When To Use

Use before marking any task done, before delivery, and after debugging fixes.

## Inputs Needed

- Acceptance criteria
- Current task
- Test files
- Run commands
- Recent failure output

## Workflow

1. Identify which acceptance criteria the current work claims to satisfy.
2. Choose the smallest relevant verification first.
3. Run tests or smoke checks from the project root.
4. Capture exact command names and result summaries.
5. If a check fails, move to debugging instead of claiming partial success.
6. Run broader checks before delivery when the change affects shared behavior.
7. Record evidence in task docs and `RESULT.md`.

## Expected Output

- Commands run
- Pass/fail result
- Evidence linked to acceptance criteria
- Known limitations or blockers

## Validation

- Verification is runnable by another agent or operator.
- Evidence is not just a prose claim.
- Failed checks are not hidden.

## Common Mistakes

- Saying "should work" without running anything.
- Running an irrelevant check.
- Ignoring flaky or partial failures.
- Forgetting to update `RESULT.md`.
