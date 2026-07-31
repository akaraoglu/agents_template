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

## Planned Lane Pilot

Use this only when the handoff explicitly contains `PLANNED LANE`. The first turn is a planning checkpoint, not an implementation draft:

1. Inspect the handoff and only its named source, test, design, and evidence files.
2. Do not edit files or run builds, tests, formatters, generators, or other commands likely to write.
3. Identify observed behavior, exact likely change paths, contracts, dependencies, uncertainties, Developer-owned tests, the targeted browser smoke when needed, Development Gate commands, and stop conditions.
4. Return:

```text
PLAN Txxx/att-xxx

Behavior and non-goals:
Files and contracts:
Dependencies and uncertainties:
Implementation sequence:
Developer-owned tests:
Browser smoke:
Development Gate:
Stop conditions:
```

Wait for the Project Lead's exact `PLAN ACCEPTED`. Then resume this same session, revise the plan when new code evidence requires it, report any material scope expansion, and follow the normal workflow below. A plan is a reviewed hypothesis, not permission to conceal a newly discovered dependency.

### Task Capsule Pilot

When the handoff explicitly says `TASK CAPSULE PILOT`, read its capsule before
other source discovery. Verify the capsule against the SHA-256 pinned in the
handoff, then verify every named source/test hash in one command. Use the capsule
as a starting map, not as proof. A missing or mismatched capsule is a reported
handoff gap, never permission to trust stale content. One focused expansion is
allowed when an uncertainty, stale source hash, missing consumer, or conflicting
source contract requires it; state the reason before expanding.

Before exceeding 12 tool calls, after three failed calls, before a second broad
repository scan, or before repeating a command without relevant file changes,
return this checkpoint before at most one additional bounded action:

```text
CAPSULE CHECKPOINT

Known:
Unknown:
Why another call is required:
Next bounded action:
Stop condition:
```

Do not suppress a real dependency to stay below the checkpoint. Report the gap
so the Lead can correct the capsule. All normal Development Gate and independent
Integration Gate requirements remain unchanged.

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

When `local-docs` is available and implementation depends on an indexed
installed library or CodexTeam contract, start with one narrow `search_docs`
call and a limit of at most five. Do not guess source IDs; omit the filter when
the exact indexed ID is unknown, and call `list_doc_sources` only when an exact
source or version filter is required. Use `read_doc` only for the winning
locator. The index is reference evidence, not proof of current product
behavior; verify the implementation with the normal Development Gate.

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
