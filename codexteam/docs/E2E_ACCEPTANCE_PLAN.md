# CodexTeam E2E Acceptance Plan

This document defines release-grade end-to-end validation for CodexTeam. It is behavior-focused and must be implemented against the core architecture in `CORE_DOMAIN_MODEL.md`.

The implementation sequence remains in `../IMPLEMENTATION_PLAN.md`. This document defines what the final E2E gates must prove.

## 1. Scenario IDs

| ID | Scenario | Primary gate |
| --- | --- | --- |
| E2E-001 | Structured worker result | Worker contract gate |
| E2E-002 | Workspace-local requested action | Action safety gate |
| E2E-003 | Review-gated change proposal | Review/apply gate |
| E2E-004 | Board and operator workflow | Operator UX gate |
| E2E-005 | Failure, denial, and retry | Reliability gate |
| E2E-006 | Workspace archive and cleanup | Workspace lifecycle gate |
| E2E-007 | Multi-agent leader delegation | Orchestration gate |
| E2E-008 | Combined release rehearsal | Release gate |

## 2. Global Rules

All scenarios must obey these rules:

- Do not use external repositories as fixtures.
- Do not copy source code, prompts, fixtures, command syntax, or tests from external projects.
- Do not install dependencies.
- Do not require network access.
- Do not run untrusted scripts.
- Do not execute shell text produced by an agent.
- Do not read credentials, hidden secrets, browser profiles, tokens, or unrelated user directories.
- Do not write outside approved roots.
- Do not bypass policy, review, approval, audit, or workspace isolation for test convenience.
- Do not delete unreviewed, rejected-unarchived, or active workspace evidence.

## 3. Scenario Requirements

### E2E-001: Structured Worker Result

Must prove:

- Worker start requires explicit approval.
- A real local `gemma4:12b` worker returns a valid `WorkerResult`.
- Result IDs and scope fields match known team, task, agent, and attempt records.
- The worker `completed` claim does not directly complete the task.
- Evidence is stored as typed, bounded records and becomes review input after validation.
- Only `submit_evidence` and `request_review` requested actions are accepted in this phase.
- The assigned workspace becomes review-locked after valid reviewable output.
- Project files remain unchanged.
- Malformed output fails closed and is audited.
- Replayed identical results are idempotent and conflicting replays are rejected.
- Reloading state from disk preserves task, run, attempt, evidence, review, workspace lock, and audit consistency.

### E2E-002: Workspace-Local Requested Action

Must prove:

- A worker can request a bounded generated artifact inside its assigned workspace.
- Path traversal, hidden paths, secret-looking names, symlink escapes, and oversized content are denied.
- Denied actions leave runtime and project files unchanged.
- Policy decisions, action state, and audit records agree.

### E2E-003: Review-Gated Change Proposal

Must prove:

- A worker can submit a structured `ChangeProposal`.
- Proposal metadata includes task, worker, attempt, workspace, affected paths, summary, risk notes, reversal notes, and validation evidence.
- Review and approval are separate.
- Apply is impossible before review and explicit approval.
- Rejected proposals are preserved.
- Approved apply is limited to approved target paths.

### E2E-004: Board and Operator Workflow

Must prove:

- Board output shows team goal, roster, task states, attempts, dependencies, pending approvals, review queue, recent messages, policy denials, risk alerts, and workspace status.
- Board rendering is read-only.
- Operator actions are routed through controller commands.
- Board refresh agrees with source state and audit.
- No raw state editing is required.

### E2E-005: Failure, Denial, and Retry

Must prove:

- Invalid worker output is rejected without controller crash.
- Approval denial prevents the requested action.
- Worker timeout or stale health is visible.
- Retry creates a new attempt and preserves failed attempt history.
- Retry does not broaden permissions.
- Checkpoints remain partial progress and do not become final evidence.

### E2E-006: Workspace Archive and Cleanup

Must prove:

- Workspace lifecycle prevents unsafe cleanup.
- Active and review-locked workspaces cannot be cleaned.
- Rejected work is preserved until archived and approved for cleanup.
- Archive metadata includes team, agent, task, review, approval, policy, retention, and change summary records.
- Cleanup is scoped to the approved workspace only.
- Workspace state, filesystem state, board, and audit agree.

### E2E-007: Multi-Agent Leader Delegation

Must prove:

- One leader coordinates at least two workers and at least three tasks.
- Workers use separate writable workspaces.
- Dependency-blocked work does not start early.
- Worker evidence is required before final synthesis.
- Final synthesis references worker evidence.
- Audit shows plan approval, assignments, transitions, messages, reviews, and final synthesis.

### E2E-008: Combined Release Rehearsal

Must prove in one integrated local run:

- Multi-agent delegation.
- Structured worker results.
- Invalid output rejection and retry.
- Review-gated proposal.
- One approval denial.
- One approved apply.
- Workspace archive or cleanup decision.
- Final board, state store, workspace records, and audit agreement.

## 4. Evidence Bundle

Every E2E run must produce a reviewable evidence bundle with:

- scenario ID
- team ID
- policy profile
- fixture summary
- agent roster
- task graph
- workspace map
- approval decisions
- review decisions
- attempts and checkpoints
- failure or retry history when applicable
- board snapshots
- audit export
- final verdict
- known limitations

## 5. Board Consistency Checks

At key points, E2E tooling must compare board output with source state:

- task counts by status
- pending approval count
- review queue count
- worker health and attempt status
- workspace lifecycle status
- recent messages
- policy denial count
- final team state

A mismatch is a blocker unless it is an intentional delayed-refresh behavior with visible timestamp metadata.

## 6. Release Blockers

E2E release validation is blocked if any of these occur:

- Worker output bypasses validation.
- Worker `completed` directly completes a task.
- Worker writes outside its assigned workspace.
- Requested actions bypass policy.
- Review or approval can be self-granted by a worker.
- Apply occurs before review and approval.
- Denied actions still execute.
- Retry erases failed attempt history.
- Cleanup deletes active, review-locked, or rejected-unarchived work.
- Restart or resume loses tasks, messages, approvals, workspaces, attempts, or audit records.
- Board hides pending approvals, denials, stale workers, or review-required work.
- Any test disables policy checks to pass.

## 7. Execution Order

Use this order for implementation and validation:

1. Structured worker result.
2. Workspace-local requested action.
3. Review-gated change proposal.
4. Board and operator workflow.
5. Failure, denial, retry, and health behavior.
6. Workspace archive and cleanup.
7. Multi-agent leader delegation.
8. Combined release rehearsal.
