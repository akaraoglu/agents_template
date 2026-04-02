# Communication Contract

Use this document to keep visible multi-agent communication standardized across
`AgentSmith`, `Niaobe`, `Architect`, `Morpheus`, `Oracle`, and future roles.

This contract is for:
- visible Zulip updates
- cross-role handoff envelopes
- result summaries
- project-level decisions

It is not meant to force every model to produce identical prose. It is meant
to make the important state machine predictable and machine-readable.

## Design Rules

- Prefer explicit fields over free-form narration for orchestration-critical
  messages.
- Keep visible messages short enough for humans to scan.
- Keep role-specific behavior consistent without erasing role personality.
- Separate handoff, status, result, and decision messages clearly.
- Require explicit project identity for project-scoped work.

## Visible Status Contract

All visible status updates should support these fields:

- `STATE`
- `OWNER`
- `SUMMARY`
- `BLOCKERS`
- `NEXT_ACTION`

Recommended meaning:
- `STATE`: current lifecycle state such as `intake`, `planning`,
  `ready_for_software`, `executing`, `validating`, `blocked`, `verified`
- `OWNER`: role currently owning the next step
- `SUMMARY`: 1-3 sentence explanation of what is happening
- `BLOCKERS`: explicit blocker summary or `none`
- `NEXT_ACTION`: immediate next step

Example:

```text
STATE: planning
OWNER: Niaobe
SUMMARY: Architect is updating milestone scope and story readiness for Phase 2.
The current pass is focused on acceptance criteria and task sequencing before
software execution begins.
BLOCKERS: none
NEXT_ACTION: Review Architect output and decide whether Morpheus should start.
```

## Handoff Contract

All cross-role handoffs should support these fields:

- `REQUEST_ID`
- `PROJECT_SLUG`
- `DISPATCHED_BY`
- `AUTHORIZED_VIA`
- `FROM_ROLE`
- `TO_ROLE`
- `PURPOSE`
- `INPUT_SUMMARY`
- `SUCCESS_CRITERIA`
- `RETURN_TO`
- `VISIBILITY_TOPIC`

Recommended meaning:
- `REQUEST_ID`: stable handoff ID
- `PROJECT_SLUG`: selected project slug, required for project-scoped work
- `DISPATCHED_BY`: actual role that triggered the handoff
- `AUTHORIZED_VIA`: granted skill or capability used to permit the handoff
- `FROM_ROLE`: sender
- `TO_ROLE`: next owner
- `PURPOSE`: why this handoff exists
- `INPUT_SUMMARY`: concise task brief
- `SUCCESS_CRITERIA`: what the receiver must satisfy
- `RETURN_TO`: role that should consume the result
- `VISIBILITY_TOPIC`: thread or topic that humans should follow

Example:

```text
REQUEST_ID: pm-fibonacci-001
PROJECT_SLUG: fibonacci-demo
DISPATCHED_BY: AgentSmith
AUTHORIZED_VIA: role-dispatcher
FROM_ROLE: AgentSmith
TO_ROLE: Niaobe
PURPOSE: Initialize project planning and determine whether software execution
should start.
INPUT_SUMMARY: Create the project skeleton, define the first story, and prepare
implementation work for a Fibonacci generator with configurable depth.
SUCCESS_CRITERIA: Project docs exist, the first story is ready or a blocker is
explicit, and the next owner is named.
RETURN_TO: AgentSmith
VISIBILITY_TOPIC: projects > project: fibonacci-demo
```

## Result Contract

All visible results should support these fields:

- `RESULT`
- `SUMMARY`
- `ARTIFACTS`
- `RISKS`
- `RECOMMENDED_NEXT_OWNER`

Recommended meaning:
- `RESULT`: `done`, `accepted`, `blocked`, `failed`, `needs_rework`
- `SUMMARY`: concise explanation of the outcome
- `ARTIFACTS`: files, stories, tasks, or outputs touched
- `RISKS`: residual risk summary or `none`
- `RECOMMENDED_NEXT_OWNER`: who should own the next step

## Decision Contract

All project-level decisions should support these fields:

- `DECISION`
- `REASON`
- `NEXT_OWNER`
- `NEXT_ACTION`

Recommended decision values:
- `accept`
- `rework_to_morpheus`
- `clarify_with_architect`
- `ask_human`
- `blocked`

## Role Specialization

Each role can add its own fields on top of the shared contract.

### AgentSmith

Additional useful fields:
- `ROUTE`
- `ROUTING_REASON`
- `HANDOFF_TARGET`

### Niaobe

Additional useful fields:
- `PM_DECISION`
- `PROJECT_STATE`
- `NEXT_OWNER`

### Architect

Additional useful fields:
- `PLAN_READY`
- `ARTIFACTS_UPDATED`
- `OPEN_QUESTIONS`

### Morpheus

Additional useful fields:
- `EXECUTION_STATE`
- `TASK_RESULT`
- `IMPLEMENTATION_NOTES`

### Oracle

Additional useful fields:
- `QA_DECISION`
- `EVIDENCE`
- `REGRESSION_RISK`

## Parsing Rules

Shared runners and bridges should be tolerant and accept:
- multiline `KEY:` blocks
- inline `KEY: value` lines
- markdown-decorated headings such as `**KEY:**`

Do not make orchestration depend on one exact formatting style.

## Human Readability Rule

Even when the fields are structured, the `SUMMARY` should still read like a
normal concise update, not like raw JSON pasted into chat.

The contract is for clarity and deterministic routing, not robotic tone.
