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

1. Confirm every current applicable Verification Plan row has evidence from its
   named verifier or an explicit unresolved status.
2. Execute or inspect each Delivery Criteria row assigned to the current role,
   and confirm the Project Lead has evidence for the remaining rows. Delivery
   checks supplement rather than replace acceptance verification.
3. Run final verification or document why it cannot run.
4. Update `DONE_REPORT.md` with completed work.
5. Update `RESULT.md` with verification commands and results.
6. Update `PROJECT_STATE.md` to final delivered state.
7. Ensure `BLOCKED_REPORT.md` is empty or accurately explains unresolved blockers.
8. Summarize delivery contents and how to run or inspect the artifact.
9. Compare the committed HEAD with the final lifecycle state. If closing the Local Git
   Steward task changed tracked delivery files after the milestone commit, authorize a
   metadata-only closure commit that excludes product and unrelated files.

## Expected Output

- Delivery-ready project files
- Final verification evidence
- Operator-readable final report

## Validation

- The project can be inspected without chat history.
- Delivery report names changed files and verification.
- Remaining limitations are explicit.
- Verification Plan evidence and Delivery Criteria evidence remain distinguishable.
- The committed HEAD contains the final delivered lifecycle state, or the remaining
  metadata-only closure is reported explicitly.

## Common Mistakes

- Delivering without final verification.
- Hiding unresolved open questions.
- Leaving task state inconsistent with delivered files.
- Reporting internal implementation details instead of operator value.
