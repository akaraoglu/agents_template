# Zulip Project Workflow

Use this document to run projects in Zulip in a way that stays visible and
traceable.

This is the recommended operating model when:
- `AgentSmith` is the main front door
- `Niaobe` owns project management and acceptance
- `Architect` handles project and management documents
- `Morpheus` fronts the software team
- `Oracle` verifies execution results

## Goal

Do not make the human guess:
- whether `AgentSmith` called `Architect`
- whether `Architect` handed work to `Morpheus`
- whether `Morpheus` actually ran the team
- whether `Oracle` validated the result

Instead, make the flow explicit in Zulip.

## Core Rule

Every important handoff must be visible in Zulip before and after it happens.

That means:
- announce the next actor
- announce the current phase
- announce the result
- announce the next decision point

Do not let the system silently jump from one agent to another.

V3 note:
- use light thread coordination, not strict topic ownership
- any visible role may answer a direct DM from the human
- in shared topics, a role should speak when mentioned, handed work, or already
  active in the exchange

## Recommended Streams

Use these streams:
- `assistant`: discussion-first stream for `AgentSmith`, `Yoda`, and
  `Architect`
- `projects`: canonical project-tracking stream
- `software`: execution stream for `Morpheus` and the software team
- `ops`: optional operational and bridge-admin stream

If you want the smallest useful version, keep:
- `assistant`
- `projects`
- `software`

## Canonical Thread Model

### 1. One Project Control Topic

Each project gets one canonical control topic in the `projects` stream.

Recommended format:
- `project: <project-slug>`

This topic is the main place a human should follow.

It should contain:
- project creation
- current goal
- current milestone
- current story or task
- current owner
- current phase
- blockers
- latest result
- next expected action

### 2. One Execution Topic Per Software Task

Each software execution request gets its own topic in the `software` stream.

Recommended format:
- `task: <project-slug> / <task-id> / <short-title>`

This topic is for:
- implementation progress
- code status
- validation output
- execution-specific discussion

### 3. Optional Decision Topics

Use separate decision topics only when needed.

Recommended format:
- `decision: <project-slug> / <short-title>`

This is useful for:
- architecture choices
- scope changes
- milestone changes

## Best Way To Follow A Project

The best model is:
- use `projects > project: <project-slug>` as the canonical project timeline
- let `AgentSmith` do intake and visible handoff
- let `Niaobe` drive the next project decision when project management is needed
- keep detailed execution in `software > task: ...`
- let `Oracle` post validation back into the project control topic for
  acceptance

That gives you:
- one place to follow the project
- one place for detailed implementation work
- no silent handoffs

## Role Responsibilities In Zulip

### AgentSmith

`AgentSmith` is the visible intake and routing layer.

He should:
- accept the first request
- ask clarifying questions
- create the project if needed
- open or identify the project control topic
- hand the project to `Niaobe`
- tell the human which `projects > project: <slug>` topic now owns the work

`AgentSmith` should not remain the long-running hidden project orchestrator
after the handoff.

### Niaobe

`Niaobe` drives project flow and acceptance decisions when project management is
needed.

She should:
- call `Architect` first for scope, milestones, stories, and tasks
- decide when work is ready for `Morpheus`
- consume `Oracle` validation results
- decide whether the result is accepted, needs rework, or needs clarification
- ask the human blocking questions when needed

### Architect

`Architect` owns project-management state.

He should:
- update `PROJECT.md`
- update `management/STATUS.md`
- update milestones, backlog, stories, and tasks
- post concise planning and management summaries
- explicitly declare when a task is `ready` for software execution

`Architect` should primarily speak in:
- the project control topic
- or an `assistant` discussion thread when still shaping the work

### Morpheus

`Morpheus` owns software execution.

He should:
- accept only concrete, ready work
- work in a dedicated `software` task topic
- post execution-phase updates
- post the execution result
- hand execution output to `Oracle`

### Oracle

`Oracle` owns truth-checking and verification.

She should:
- validate independently from `Morpheus`
- post what was verified
- post what remains unverified
- distinguish `done` from `verified`
- post blockers or failed validation clearly
- report the visible validation result into `projects > project: <project-slug>`
  so `Niaobe` can own the acceptance decision

## Required Status Protocol

Use explicit status prefixes in Zulip.

Recommended prefixes:
- `[STATUS]`
- `[HANDOFF]`
- `[ACTION]`
- `[RESULT]`
- `[BLOCKER]`
- `[QUESTION]`

Examples:
- `[STATUS] Project initialized. Architect is preparing milestones.`
- `[HANDOFF] Passing TASK-003 to Morpheus in software > task: claw / TASK-003 / login form`
- `[STATUS] Morpheus is coding. Oracle has not validated yet.`
- `[RESULT] Oracle verified TASK-003. STATUS.md updated.`
- `[BLOCKER] Architect cannot mark the story ready because acceptance criteria are still vague.`

## Minimum Posting Rules

### AgentSmith must post when:

- a request is received
- a new project is being created
- a project folder has been initialized
- the project topic is handed to `Niaobe` or another visible role
- the next human-visible active role has changed

### Niaobe must post when:

- the project thread is accepted
- `Architect` is being consulted
- a task becomes ready for `Morpheus`
- `Oracle` has returned validation
- work is accepted, sent back for rework, or blocked on clarification

### Architect must post when:

- project docs were created or updated
- a milestone changed
- a story changed state
- a task changed state
- work becomes `ready` for software
- management validation is complete

### Morpheus must post when:

- execution starts
- planner is consulted
- coder starts editing
- tester starts validating
- execution completes
- execution is blocked

### Oracle must post when:

- validation starts
- validation passes
- validation fails
- the validation result has been handed back to `Niaobe`
- evidence is incomplete

## Recommended Phase Model

Use one shared phase vocabulary across all streams and docs.

Recommended phases:
- `intake`
- `clarifying`
- `project_init`
- `planning`
- `ready_for_software`
- `executing`
- `validating`
- `verified`
- `blocked`
- `stopped`

`AgentSmith` should keep the current phase visible in the project control topic.

## Recommended Commands

### Human-facing commands

- `/status`
- `/stop`
- `/project list`
- `/project use <slug>`
- `/project status`
- `/project clear`
- `/manage ...`
- `/architect ...`
- `/delegate ...`

### Usage

- Use `/manage ...` when you want AgentSmith to orchestrate the full flow:
  consult Architect first, update the planning layer, and only then hand ready
  work to Morpheus.
- Use `/architect ...` when you want direct planning or document work.
- Use `/delegate ...` when you want AgentSmith to turn a ready task into a
  software handoff.
- Use `/status` in any active thread to see the current phase.
- Use `/stop` to stop the active run for that thread.

Recommended rule:
- for small discussion or clarification, use normal chat
- for direct planning only, use `/architect ...`
- for full Architect-first orchestration, use `/manage ...`
- for explicit software handoff only, use `/delegate ...`

## Canonical Flow For A New Project

1. Human asks `AgentSmith` for a new project or idea.
2. For a full managed flow, the human uses `/manage ...`.
3. `AgentSmith` asks clarifying questions when still needed.
4. `AgentSmith` posts `[STATUS] intake` or `[STATUS] clarifying`.
5. `AgentSmith` creates the project folder from `project_template/`.
6. `AgentSmith` opens or references `projects > project: <project-slug>`.
7. `AgentSmith` posts `[HANDOFF]` to `Architect`.
8. `Architect` creates or updates:
   - `PROJECT.md`
   - `management/STATUS.md`
   - `management/MILESTONES.md`
   - `management/BACKLOG.md`
   - story and task files as needed
9. `Architect` posts a summary and marks the next task `ready` if appropriate.
10. `AgentSmith` mirrors that summary into the project control topic.
11. If software work is ready, `AgentSmith` posts `[HANDOFF]` to `Morpheus`
    and references the software topic.
12. `Morpheus` runs in `software > task: ...`.
13. `Oracle` validates the result.
14. `AgentSmith` mirrors the outcome back into `projects > project: <slug>`.
15. `Architect` updates the management docs and final phase.

## Mirror Rule

This rule is the most important one.

When `Morpheus` or `Oracle` are working in `software > task: ...`, `AgentSmith`
must still keep `projects > project: <slug>` updated with short status posts.

That means a human can follow the project without living in the software stream.

Minimum mirrored events:
- execution started
- coding in progress
- validation started
- task done
- task verified
- blocked or stopped

## Linking Rule

Every major handoff should include a reference to the other thread.

Examples:
- project topic links to the software task topic
- software task topic links back to the project topic

This avoids detached conversations.

## Document Rule

Zulip is the visible workflow layer. The repository is still the durable source
of truth.

When status changes in Zulip, the responsible agent should also update the
matching project documents:
- `management/STATUS.md`
- story files
- task files
- `DECISIONS.md` or `RISKS.md` when needed

Do not let chat status drift away from the documents.

## Recommended V3 For This Template

For the current template, the recommended visible project loop is:
- `AgentSmith` as the main inbox and visible router
- `Niaobe` as the project-loop owner
- `Architect` for planning and project-doc work
- `Morpheus` for software execution in the `software` stream
- `Oracle` for visible validation before project closure
- one `projects > project: <slug>` topic as the canonical project timeline

Recommended large-task entrypoint:
- DM `AgentSmith` or hand work to `@Niaobe` explicitly so the gateway can keep
  the routing visible

This gives you one clear place to follow project progress while still keeping
implementation details in the right execution stream.
