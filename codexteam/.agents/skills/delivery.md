# Delivery Skill

## Purpose

Prepare the project for operator handoff after implementation and verification.

## When To Use

Use when the operator asks for delivery, when all MVP tasks are done, or before final report generation.

## Inputs Needed

- Final `PROJECT.md`
- Completed tasks and evidence
- Verification results
- Changed file list
- Known limitations

## Workflow

1. Confirm all acceptance criteria have evidence.
2. Run final verification or document why it cannot run.
3. Update `DONE_REPORT.md` with completed work.
4. Update `RESULT.md` with verification commands and results.
5. Update `PROJECT_STATE.md` to final delivered state.
6. Ensure `BLOCKED_REPORT.md` is empty or accurately explains unresolved blockers.
7. Summarize delivery contents and how to run or inspect the artifact.

## Expected Output

- Delivery-ready project files
- Final verification evidence
- Operator-readable final report

## Validation

- The project can be inspected without chat history.
- Delivery report names changed files and verification.
- Remaining limitations are explicit.

## Common Mistakes

- Delivering without final verification.
- Hiding unresolved open questions.
- Leaving task state inconsistent with delivered files.
- Reporting internal implementation details instead of operator value.
