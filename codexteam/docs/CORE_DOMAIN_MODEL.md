# CodexTeam Core Domain Model

This document defines the core orchestration concepts used by CodexTeam after the initial MVP thin slice. These concepts are part of the domain model, not UI, adapter, MCP, HTTP, or test-only behavior.

## 1. Layering Rule

CodexTeam keeps domain behavior in core services:

```text
controller
  -> policy
  -> state store
  -> task, run, message, approval, review engines
  -> workspace manager
  -> adapters
  -> board read models
```

Adapters, worker processes, terminal rendering, HTTP, MCP, and operator scripts must call controller/core commands. They must not own task transitions, policy decisions, review decisions, approval decisions, workspace lifecycle decisions, or audit writes.

## 2. WorkerResult

A `WorkerResult` is an untrusted report from a worker attempt. It never directly completes a task.

Required fields:

| Field | Purpose |
| --- | --- |
| `result_id` | Stable result identity for deduplication and audit. |
| `team_id` | Team scope. |
| `task_id` | Task the result claims to address. |
| `agent_id` | Worker that produced the result. |
| `attempt_id` | Attempt that produced the result. |
| `status` | Controlled worker-result status. |
| `summary` | Bounded human-readable summary. |
| `evidence` | Typed evidence records. |
| `requested_actions` | Structured action requests. |
| `warnings` | Non-fatal concerns. |
| `limitations` | Known incomplete or unverified parts. |
| `produced_at` | Timestamp from the worker envelope or controller receive time. |

Worker-result statuses:

```text
completed
needs_review
blocked
failed
checkpointed
refused
```

`invalid` is reserved for controller validation results. A worker cannot self-report a trusted `invalid` state.

Controller rules:

- A worker status is a claim, not a task transition.
- `completed` can at most move the task toward review after validation.
- `checkpointed` is partial progress and must not count as final evidence.
- Malformed, oversized, cross-team, cross-task, or cross-attempt results fail closed and are audited.
- A result can be accepted only once for an attempt.
- Replaying the same `result_id` with identical content is idempotent.
- Replaying the same `result_id` with different content is rejected as a conflict.
- A final attempt result must not be replaced by another final result unless an explicit retry creates a new attempt.

## 2.1 EvidenceRecord

`EvidenceRecord` replaces raw evidence strings for new structured worker flows.

Required fields:

| Field | Purpose |
| --- | --- |
| `evidence_id` | Stable evidence identity. |
| `team_id` | Team scope. |
| `task_id` | Task scope. |
| `agent_id` | Producing worker. |
| `attempt_id` | Attempt that produced the evidence. |
| `result_id` | Worker result that carried the evidence. |
| `evidence_type` | Controlled evidence type. |
| `summary` | Bounded summary. |
| `content` | Bounded inline content when applicable. |
| `artifact_ref` | Runtime artifact reference when content is stored separately. |
| `metadata` | JSON-safe bounded metadata. |

Allowed Phase 11 evidence types:

```text
text
json
artifact_ref
```

Phase 11 limits:

- Maximum 10 evidence records per worker result.
- Maximum 8 KiB per inline evidence content field.
- Maximum 2 KiB per summary.
- Artifact references must point inside the assigned runtime workspace or team artifact area.
- Evidence must be append-only after acceptance; corrections require a new result or retry attempt.

## 3. RequestedAction

A `RequestedAction` is a structured request for CodexTeam to do something. Workers request actions; the controller decides whether an action is allowed.

Required fields:

| Field | Purpose |
| --- | --- |
| `action_id` | Stable action identity. |
| `requested_by` | Agent or user that requested the action. |
| `team_id` | Team scope. |
| `task_id` | Task scope when applicable. |
| `workspace_id` | Workspace scope for file and workspace actions. |
| `action_type` | Controlled action type. |
| `target_scope` | Exact target files, workspace, task, or state object. |
| `reason` | Why the action is requested. |
| `risk_level` | `low`, `medium`, `high`, or `blocked`. |
| `requires_review` | Whether review must gate the action. |
| `requires_human_approval` | Whether a human approval is required. |
| `policy_decision_id` | Policy decision reference after evaluation. |
| `approval_id` | Approval or denial reference when required. |
| `audit_ids` | Related audit event references. |
| `state` | Current action state. |

Allowed initial action types:

```text
submit_evidence
send_message
request_review
propose_workspace_change
request_apply
request_cleanup
request_retry
request_checkpoint
request_pause
request_resume
```

Phase 11 action allowlist:

```text
submit_evidence
request_review
```

All other action types are future-capability placeholders and must be rejected or denied during Phase 11.

Rejected action categories:

```text
execute_command
run_shell
apply_raw_patch
delete_path
read_any_file
```

Action states:

```text
proposed
denied
approved
executed
failed
cancelled
```

## 4. Attempts, Checkpoints, and Worker Health

A task is the work item. An attempt is one try to complete that work by one worker.

Every worker execution creates an `Attempt`, including the first successful execution. Retries create new attempts and preserve previous attempt history.

Attempt records should capture:

- `attempt_id`
- `team_id`
- `task_id`
- `agent_id`
- `run_id`
- `workspace_id`
- start and finish timestamps
- status
- policy profile
- input summary
- result references
- checkpoint references
- retry lineage

Checkpoint records represent partial progress only. They may support resume, but they must not complete a task or replace final evidence.

Worker health is observed by adapters and interpreted by core policy/controller logic. Health states:

```text
healthy
idle
paused
stale
failed
unknown
```

Resume decisions:

```text
resume_same_attempt
retry_new_attempt
replace_worker
mark_failed
require_human_decision
```

Stale policy must define heartbeat timeout, maximum attempt runtime, retry limits, retry permission scope, and board/audit visibility requirements.

## 5. Workspace Lifecycle

Workspace cleanup and archive behavior must be lifecycle-driven. Filesystem shape alone is not evidence that cleanup is safe.

Workspace states:

```text
active
review_locked
applied
rejected_preserved
archived
cleanup_eligible
cleaned
```

Required transition gates:

| From | To | Required gate |
| --- | --- | --- |
| `active` | `review_locked` | Valid worker result submitted for review. |
| `review_locked` | `applied` | Review approval and apply success. |
| `review_locked` | `rejected_preserved` | Review rejection. |
| `applied` | `archived` | Archive bundle created. |
| `rejected_preserved` | `archived` | Rejection evidence archived. |
| `archived` | `cleanup_eligible` | Retention policy satisfied. |
| `cleanup_eligible` | `cleaned` | Explicit cleanup approval. |

Invalid transitions include:

- `active` to `cleaned`
- `review_locked` to `cleaned`
- `rejected_preserved` to `cleaned` without archive
- `archived` to `active`

## 6. ChangeProposal

A `ChangeProposal` is reviewable evidence for a bounded target change. It is not an apply operation.

Required proposal data:

- task ID
- agent ID
- attempt ID
- workspace ID
- affected paths
- summary
- risk notes
- reversal notes
- validation evidence
- bounded target scope

Change flow:

```text
WorkerResult
  -> RequestedAction
  -> ChangeProposal
  -> ReviewDecision
  -> ApprovalDecision
  -> ApplyOperation
```

Workers may create proposal artifacts inside their assigned workspace. Only the controller may apply reviewed and approved changes to target project files.

## 7. ReviewDecision and ApprovalDecision

Review and approval are separate.

- A `ReviewDecision` decides whether evidence or a proposal is technically reviewable and acceptable.
- An approval record records a human authorization or denial for an action that requires human control.

A worker cannot review or approve its own output.

Naming rule:

- `ApprovalDecision` may remain an enum/status if already used in code.
- New persisted approval decision data should use the existing approval record model or a clearly named `ApprovalRecord`.
- Do not add a second persisted class named `ApprovalDecision` if it conflicts with existing enum/status names.

## 7.1 Phase 11 Minimal Review Lock

Full workspace lifecycle implementation is deferred until the workspace archive/cleanup phase. Phase 11 still requires one minimal safety transition:

```text
active -> review_locked
```

When a valid worker result is accepted for review:

- the assigned workspace becomes review-locked;
- additional worker writes to that workspace are denied until review is resolved or a retry/new attempt creates an allowed workspace;
- the review lock is visible in board/review state;
- the transition is audited.

This prevents review from becoming stale while preserving full archive and cleanup lifecycle for the later dedicated phase.

## 8. BoardReadModel and OperatorCommand

Board rendering is read-only.

Operator workflows use two separate concepts:

- `BoardReadModel`: builds display state from source state, audit, approvals, reviews, workspaces, and runs.
- `OperatorCommand`: describes user intent and is handled by the controller.

Rendering code must not mutate state directly.

## 9. EvidenceBundleExporter

E2E evidence bundles are generated by tooling from core state and audit records. They are not required for normal runtime operation.

Each E2E bundle should include:

- scenario ID
- team ID
- policy profile
- fixture summary
- agent roster
- task graph
- workspace map
- approvals
- reviews
- attempts and checkpoints
- board snapshots
- audit export
- final verdict
- known limitations

The exporter belongs in E2E tooling. Core must produce enough structured records for the exporter to work.

Phase 11 does not require full evidence bundle export. It must produce a smaller E2E summary with team ID, task ID, agent ID, run ID, attempt ID, result ID, evidence IDs, review state, workspace lock state, audit count, invalid-output result when tested, and final verdict. Full release-grade bundles begin in the E2E evidence-bundle phase.
