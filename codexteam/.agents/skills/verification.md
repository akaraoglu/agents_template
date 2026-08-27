# Verification Skill

## Purpose

Independently determine whether claimed work satisfies approved acceptance criteria and whether its evidence supports closure.

## When To Use

Use for draft review, final-result inspection, every task closure, and delivery audit.

## Inputs Needed

- Acceptance criteria and active handoff
- Worker draft or final result
- Current source, tests, and evidence artifacts
- Runnable verification commands
- Current temporal state

## Workflow

1. Identify the exact claims and current acceptance criteria under review. Read
   the applicable Verification Plan rows to identify the named validation,
   verifier, and expected evidence. Classify each applicable row as passed,
   failed, blocked, or unverified; the row is a plan, not proof. When
   `codexteam-context` is available, begin with `get_task_context` if the review boundary
   is not already exact. Use `get_attempt_summary`, `validate_result_record`,
   `get_gate_status`, and `get_change_summary` only for the corresponding review question.
    Do not use Bash, `find`, recursive `ls`, broad `grep`, or
    `read_mcp_resource` to rediscover context that the bound MCP tools provide.
   Do not repeat a sufficient MCP response with broad shell discovery. Treat every summary
   as an orientation aid, then inspect the named source and evidence required for the claim.
2. Inspect declared files and artifacts rather than trusting summaries.
3. Compare each claim with the actual artifact content. Artifact existence, schema validity, and another agent's acceptance are not substitutes for this comparison.
4. Run the smallest relevant command, then broader checks when shared behavior or delivery is affected. Include at least one exact-output or golden comparison for output-format requirements that the existing suite does not fully assert.
5. Record exact paths, counts, commands, observations, and whether a check is ready or actually passed.
6. Accept the draft, request precise revision, or report a genuine showstopper.
7. On failure, preserve evidence and return feedback to the responsible AI. Do not silently repair source unless assigned a separate implementation task.
8. Record final evidence only after checks have actually run.
9. Treat `results/gates/<gate>.json` as rolling status. At an accepted task boundary,
   require the content-addressed task-attempt snapshot under
   `results/gates/accepted/` and verify its embedded record matches the claim.
   Use `get_gate_status` for normal freshness/status context; inspect a raw record
   or command log only to diagnose a named failure.

## Communication Example

Good: “The E2E harness exists at `tests/test_cli.py`, but the documented command has not executed. Status: ready, not passed.”

Bad: “Everything looks good,” or converting a planned check into completion evidence.

## Expected Output

- An acceptance, revision request, or showstopper classification
- Reproducible command evidence mapped to acceptance criteria
- Criterion-level coverage that distinguishes planned validation, observed
  evidence, and unresolved gaps
- Clear separation between readiness, worker claims, and observed success

## Validation

- Another agent can rerun the checks.
- Every completion statement is backed by observed evidence.
- Failed checks and temporal limitations remain visible.
- Reviewer independence is preserved.
- Accepted gate evidence is immutable and names the exact task and attempt.

## Common Mistakes

- Saying “should work” without execution
- Repairing the work while reviewing it
- Reporting a planned or runnable check as passed
- Omitting exact paths, counts, or commands
- Advancing state from a worker claim alone
- Treating a file's existence as proof of claims that its content does not record
- Inferring exact rendering, determinism, or error-stream behavior from a broad “tests passed” line

## Related Files

- `.agents/skills/testing.md`
- `.agents/skills/subagent-orchestration.md`
- `RESULT.md`
