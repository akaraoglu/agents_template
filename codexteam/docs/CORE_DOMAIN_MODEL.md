# CodexTeam Core Domain Model

## Project Workspace

A project workspace is an isolated directory containing the project specification, task ledger, task handoffs, source, tests, results, and delivery reports. The workspace path must resolve beneath the configured projects root.

## Task

Task IDs use canonical uppercase form such as `T001`. A task row contains description, status, owner, verification, and evidence. Supported states are:

```text
Planned -> Ready -> In Progress -> Needs Review -> Completed
                         |-> Blocked
```

The standard workflow uses:

- `T001`: specification and project skeleton
- `T002`: Architect-owned code and project architecture
- `T003`: Developer implementation and Development Gate
- `T004`: Test Engineer integration/CI gate and independent regression evidence
- `T005`: Reviewer acceptance and architecture conformance
- `T006`: optional documentation reconciliation

## Handoff

A handoff binds a team, task, attempt, role, model profile, workspace, constraints, task context, completion criteria, role-policy digest, and complete instruction-bundle digest. Its machine-readable shape is `schemas/handoff.json`.

## Result

A result is an untrusted report from one attempt. Result current requires stable identity, scope fields, status, summary, process output, file changes, evidence, follow-ups, errors, warnings, limitations, and a UTC timestamp.

Result statuses are:

```text
completed
failed
partial
blocked
needs_review
```

`completed` is a worker claim. It does not complete the task.

## Evidence

Evidence refers to a relative artifact inside the project workspace. Completed and review-ready results require at least one evidence entry. The leader confirms declared changed files and evidence artifacts exist before running independent verification.

## Close Loop

A task becomes `Completed` only when:

1. The latest task result is valid and has status `completed`.
2. Declared files and evidence artifacts exist within the project root.
3. An independent verification command exits successfully.
4. `TASKS.md`, `PROJECT_STATE.md`, `CURRENT_TASK.md`, and `RESULT.md` are synchronized.

Delivery is generated only when every planned task is completed.

## Verification Gates

`management/TEST_GATES.toml` is the machine-readable source for Development and Integration Gate argument arrays. Integration includes Development. Each passing record under `results/gates/` contains a manifest and digest of configured verification paths; stale records cannot authorize a milestone.

## Local Commit Boundary

The Local Git Steward is a boundary service, not a normal task-closure authority. Its model inspects and proposes an explicit path set. The Project Lead authorizes the exact plan digest, branch, HEAD, evidence, and paths. The deterministic executor reconstructs and re-verifies the candidate tree before creating one local commit. Remote Git actions are outside CodexTeam authority.
