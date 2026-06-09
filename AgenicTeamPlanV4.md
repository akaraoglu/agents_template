# AgenticTeam V4 Plan: Lean Autonomous Software Team

## Purpose

V4 is a simplification plan for AgenticTeam/OpenClaw after repeated failures in the full multi-agent hierarchy.

The objective is still the same:

- accept a user software goal
- plan useful tasks
- implement code and tests
- verify against acceptance criteria
- repair when possible
- report a reliable final result

The change is organizational. V4 removes unnecessary live coordination edges and makes the system easier to reason about.

V4 should be built as a small verified lane beside the existing system first. Do not delete V3 paths until the V4 lane passes repeated end-to-end tests.

V4 now adopts the useful parts of the separate V6 design review:

```text
V4-simple team organization + V6-style typed tool plane.
```

That means the team stays small for the first lane, while the tool and runtime boundaries become sharper.

## Problem Statement

The current team became too hard to stabilize because the work is split across too many conversational owners:

```text
Neo -> Smith -> Niaobe -> Architect -> Niaobe -> Morpheus -> Niaobe -> Oracle -> Niaobe -> Smith
```

This creates many failure points:

- stale session memory can replay old task envelopes
- one agent can think work is done while project state disagrees
- parent agents can look for child result files using corrupted or stale run ids
- tool errors can be followed by success-shaped prose
- agents can write artifacts but forget to report
- agents can report without verified evidence
- repeated child completion events can advance or reset state more than once
- markdown state, worker `state.json`, handoff ledger, and session transcript can disagree
- small role changes require prompt, runtime, canary, allowlist, and session-sync changes

The deeper issue is not that agents cannot write code. The deeper issue is that chat sessions are being used as a control plane.

V4 treats LLM agents as reasoning workers, not as reliable distributed-system infrastructure.

## Core V4 Principle

Agents decide how to solve work. Tools and state decide what is true.

In V4:

- Smith owns project progress.
- Morpheus/Worker owns one bounded task attempt, including task-local planning, implementation, and tests.
- Oracle owns independent overall project validation.
- Runtime is roads only: identity, leases, capability grants, sandbox lifecycle, event logging, resource limits, and kill switches.
- Tools own scoped capabilities: file writes, patches, tests, work submission, verification, evidence recording, and safe failure messages.
- Chat/prose is never the source of truth.

The runtime must not become a smart project manager. It should not decide architecture quality, code correctness, merge readiness, or role-specific step order.

The tools must be sharp, typed, scoped, inspectable, and reversible.

## V6 Lessons Adopted

The V6 design file has the right infrastructure philosophy, but too much team shape for the next step. V4 adopts the infrastructure philosophy while keeping the lean team.

### Adopt

- **Roads-only runtime**: runtime handles identity, leases, capability grants, sandbox lifecycle, event logs, resource limits, and kill switches.
- **Typed tools over shell wrappers**: agents call `fs.write`, `fs.patch`, `tests.run`, `work.submit`, and `oracle.verify` rather than constructing fragile shell commands.
- **Work-order leases**: every task attempt has a lease; stale attempts cannot mutate files or submit results.
- **Append-only event ledger**: tool calls, work submissions, verification, errors, and state transitions are recorded as events.
- **Messages are reports only**: Mattermost/session messages provide visibility, not authoritative state transitions.
- **Structured tool errors**: denied paths, denied commands, stale leases, and invalid payloads return repairable typed errors.
- **Sandbox broker later**: Docker and network access should be brokered by narrow tools, not exposed directly to normal agents.

### Defer

- Default Niaobe orchestration.
- Mandatory separate Architect handoff.
- PR open/review/merge lifecycle.
- Trinity, Sentinel, and release roles.
- Full SDD ceremony for every small task.
- MCP server implementation before the internal tool surface is stable.

### Reject For First Slice

- Agent-facing raw `RUN_DIR`/`NEXT_REQUIRED` contracts.
- File content passed through shell arguments.
- Multiple manually edited state sources.
- Runtime-owned semantic QA.
- A full team hierarchy before one Morpheus Worker lane is boring and repeatable.

## Target Team Organization

V4 starts with four active roles:

```text
Neo -> Smith -> Morpheus/Worker -> Smith -> Oracle -> Smith -> Neo
```

### Neo

Neo is the user-facing intake and final-report agent.

Responsibilities:

- understand the human request
- create or update `PROJECT.md`
- hand the project to Smith
- receive final project result or escalation
- communicate with the human

Neo does not manage task sequencing.

### Smith

Smith is the single conductor.

Responsibilities:

- create `PLAN.md`
- maintain `BACKLOG.md`
- maintain `CURRENT_TASK.md`
- select the next task
- call Morpheus/Worker for task execution
- call Oracle for final overall project validation
- decide task done, blocked, retry, or replan
- mark project done
- report to Neo

Smith is the only normal writer of project progress state.

### Morpheus As Worker

Morpheus is the first V4 Worker.

Morpheus/Worker is the bounded software work specialist.

Responsibilities:

- understand one task
- create the task-local plan/design needed to implement that task
- write implementation artifacts
- write or update task tests
- run diagnostic checks and task self-tests when useful
- repair within retry budget
- submit exactly one `WorkResult`

Worker replaces the initial live split between Architect and Morpheus.

If design output is needed, Worker writes it as an artifact, for example:

```text
management/architecture/T001.md
```

### Oracle

Oracle is the independent overall project verifier.

Responsibilities:

- read the project goal, plan, completed task results, artifacts, tests, and acceptance criteria
- run or inspect project-level verification evidence
- write an overall validation report
- return `PASS`, `FAIL`, or `NEEDS_REVIEW`

Oracle does not repair.

Oracle is not a required gate after every task in the first V4 lane. Smith can optionally call Oracle for a risky task later, but the default first-slice rule is:

```text
Morpheus self-verifies each task.
Oracle verifies the whole project before Smith marks PROJECT DONE.
```

## Roles Paused In V4 First Slice

### Niaobe

Pause Niaobe in the first V4 lane.

Reason:

Niaobe currently acts as a live middle manager between Smith and worker agents. That extra layer creates duplicated state ownership, child-result path lookup failures, repeated completion replay, and stale-session confusion.

Niaobe may return later only if the simpler Smith-owned loop is stable and there is a clear need for a coordinator layer.

### Architect As Separate Live Agent

Pause Architect as a separate live handoff target in the first V4 lane.

Reason:

The system does not need a separate live design handoff until the task loop is reliable. Worker can produce design artifacts as part of its task attempt.

Architect may return later as a specialist called directly by Smith, not through Niaobe.

### Morpheus As Old Implementer Protocol

Retain Morpheus implementation ability and make it the first V4 Worker path, but remove old protocol obligations from the agent-facing path.

Morpheus/Worker should not need to remember raw run dirs, draft aliases, `NEXT_REQUIRED`, or role-specific report commands.

## Source Of Truth

V4 needs one authoritative state model.

Recommended project-local structure:

```text
PROJECT.md
PLAN.md
BACKLOG.md
CURRENT_TASK.md
.openclaw/
  events.jsonl
  state.json
  attempts/
    T001/
      attempt-001/
        task_pack.json
        work_result.json
        oracle_result.json
        evidence/
```

### Event Log

`.openclaw/events.jsonl` is the canonical history.

Each event is append-only and typed:

```json
{
  "event_id": "...",
  "timestamp": "2026-06-08T00:00:00Z",
  "project_id": "...",
  "actor": "smith",
  "event_type": "task_dispatched",
  "task_id": "T001",
  "attempt_id": "attempt-001",
  "payload": {}
}
```

Events must be append-only. No agent should edit historical events.

Required event types:

- `project_created`
- `plan_created`
- `task_activated`
- `task_dispatched`
- `work_submitted`
- `work_repair_requested`
- `work_blocked`
- `oracle_dispatched`
- `oracle_passed`
- `oracle_failed`
- `task_done`
- `task_blocked`
- `task_replanned`
- `project_done`
- `project_blocked`
- `lease_acquired`
- `lease_released`
- `tool_called`
- `tool_succeeded`
- `tool_failed`

### State Snapshot

`.openclaw/state.json` is a derived snapshot of current truth.

It may be rewritten atomically by Smith/runtime tools, but it must be reconstructable from events.

Minimum fields:

```json
{
  "project_id": "...",
  "phase": "PLANNING | IN_PROGRESS | DONE | BLOCKED",
  "owner": "smith",
  "active_task": "T001",
  "active_attempt": "attempt-001",
  "waiting_for": "worker | oracle | smith | neo | none",
  "last_completed_task": null,
  "last_result": null,
  "updated_at": "..."
}
```

### Markdown Files

Markdown remains important because agents and humans read it easily.

But markdown is a view, not the authoritative control source.

Rules:

- `PROJECT.md`: durable user goal and constraints.
- `PLAN.md`: ordered task plan.
- `BACKLOG.md`: task list and progress summary.
- `CURRENT_TASK.md`: readable active task brief.
- `PROJECT_STATE.md`: optional compatibility view generated from `.openclaw/state.json`.

Smith/runtime tools should update markdown views from state/events, not rely on every agent manually editing them.

### Communication Is Not State

Mattermost, DMs, OpenClaw session text, and agent prose are visibility surfaces. They are not state transitions.

If an agent says `DONE` in chat but does not call `work.submit`, the project is not done.

If an agent says it handed off work but no event/lease/result exists, the handoff did not happen.

Every important state transition must be represented by a typed event and, where relevant, a typed result object.

## Contracts

### TaskPack

Smith dispatches a `TaskPack` to Morpheus/Worker.

Minimum shape:

```json
{
  "schema_version": 4,
  "project_id": "...",
  "task_id": "T001",
  "attempt_id": "attempt-001",
  "role": "worker",
  "workspace_root": "/home/alik/workspace/clawspace/projects/active/...",
  "goal": "...",
  "acceptance_criteria": [],
  "required_outputs": [],
  "allowed_write_paths": [],
  "relevant_files": [],
  "recommended_verification": {
    "command": ["python3", "-m", "pytest", "-q"],
    "optional": true
  },
  "report_destination": "tool://submit_work_result",
  "repair_budget": 2,
  "previous_failure": null
}
```

TaskPack must be short. The agent should use read/search tools for extra context instead of receiving a giant prompt.

### WorkResult

Morpheus/Worker submits one `WorkResult`.

```json
{
  "schema_version": 4,
  "project_id": "...",
  "scope": "project",
  "task_id": null,
  "attempt_id": null,
  "agent": "worker",
  "status": "DONE | BLOCKED | FAILED | NEEDS_REVIEW",
  "summary": "...",
  "changed_files": [],
  "artifact_manifest": {
    "created": [],
    "changed": [],
    "moved": [],
    "deleted": []
  },
  "verification": {
    "performed": true,
    "command": [],
    "status": "pass | fail | skipped",
    "summary": "...",
    "evidence_paths": []
  },
  "blocker": null,
  "known_gaps": []
}
```

Rules:

- `DONE` requires verification evidence.
- `DONE` requires required outputs to exist in the declared workspace.
- `DONE` requires an artifact manifest when files changed.
- `BLOCKED` requires a blocker and smallest next action.
- Runtime rejects missing, malformed, or prose-only results.

### OracleResult

Oracle submits one `OracleResult`.

```json
{
  "schema_version": 4,
  "project_id": "...",
  "task_id": "T001",
  "attempt_id": "attempt-001",
  "verdict": "PASS | FAIL | NEEDS_REVIEW",
  "summary": "...",
  "checks": [],
  "evidence_paths": [],
  "blocking_findings": [],
  "non_blocking_findings": []
}
```

Smith accepts project completion only after Oracle returns a project-level `PASS` or Smith explicitly records a human-approved exception.

For the first V4 lane, Oracle is required for final project validation. Later, Smith may call Oracle for task-level verification when risk justifies it.

## Tool Strategy

V4 should move from raw command contracts to intention-level tools.

Agents should call tools like:

```text
read_project_file
write_artifact
list_project_files
run_tests
submit_work_result
submit_blocked
request_oracle_verification
failure_analyze
```

Agents should not construct:

```text
bash /home/.../morpheus_run_task.sh report "/some/run/dir"
```

The tool should know the current project, task, attempt, workspace, and run directory.

### V6-Style Tool Categories

The first V4 lane should expose a small subset of the V6 tool plane. Keep the names final-ish even if the first implementation is internal Python/OpenClaw-native rather than MCP.

| Category | First V4 Tools | Purpose |
| --- | --- | --- |
| Workspace discovery | `workspace.inspect`, `repo.map`, `repo.search`, `fs.list`, `fs.read` | Let agents understand project structure before editing. |
| Path and policy preflight | `path.validate`, `cmd.preflight`, `policy.check` | Let agents validate intended actions before mutation. |
| File operations | `fs.write`, `fs.patch`, `fs.mkdir` | Safe scoped edits inside the project/work order. |
| Execution and tests | `tests.discover`, `tests.run`, `cmd.run` | Run task diagnostics and project validation with structured evidence. |
| Work completion | `work.submit`, `work.block`, `work.status` | Submit evidence-backed results or blockers. |
| Oracle validation | `oracle.verify`, `oracle.report` | Final whole-project verification in the first V4 lane. |
| State and events | `state.read`, `events.append`, `events.query` | Read truth and record auditable actions. |
| Communication | `message.post`, `message.dm` | Visibility only; never authoritative state. |
| Future PR lifecycle | `pr.open`, `pr.status`, `pr.review`, `pr.merge` | Deferred until the local task loop is stable. |

### Tool Design Rules

Every V4 tool must:

- have a typed schema
- know `project_id`, `task_id`, `attempt_id`, actor, workspace, and lease where relevant
- return structured success, warning, and failure data
- fail closed when scope is unclear
- write a concise event to the ledger
- return a repair hint for common agent mistakes
- be idempotent where practical

No V4 tool may:

- accept giant file payloads through shell arguments
- infer project identity from current working directory alone
- return only human prose when structured output is possible
- silently mutate state outside declared scope
- let agents bypass sandbox or path boundaries
- decide semantic project success in runtime infrastructure

### Agent Editing Rule

Before modifying files, Morpheus/Worker should:

```text
1. Inspect the workspace if structure is unknown.
2. Validate intended paths with path.validate.
3. Write or patch through fs.write/fs.patch.
4. Inspect the actual result with fs.read or git.diff.
5. Run task-level tests with tests.run when useful.
6. Submit through work.submit or work.block.
```

The preflight step is an instruction-level expectation. The file/test/work tools still enforce hard boundaries if the agent skips it.

### MCP Direction

Use MCP as the long-term tool boundary, not as the team orchestrator.

The target is an OpenClaw Workbench tool server with typed tools:

- `project.read`
- `project.search`
- `artifact.write`
- `artifact.list`
- `artifact.manifest`
- `tests.run`
- `work.submit`
- `work.block`
- `oracle.verify`
- `state.read`
- `events.append`
- `failure.analyze`

MCP benefits:

- clear tool schemas
- consistent tool discovery
- reusable clients
- fewer prompt-specific shell commands
- typed errors that agents can repair from

MCP risks:

- it does not solve orchestration by itself
- unsafe tool servers can widen access too much
- stdio/server lifecycle bugs can become new failure modes
- tool admission and permissions must be explicit

V4 policy:

- start with internal Python tool functions or OpenClaw-native tools using MCP-shaped schemas
- add an MCP server adapter only after the simple V4 loop passes
- never expose arbitrary filesystem or arbitrary shell MCP tools to all agents
- require project-scoped permissions for every write/exec tool

## Runtime Responsibility

Runtime/tools own:

- project lookup
- task attempt id creation
- work-order lease creation, validation, and release
- workspace path normalization
- allowed write path checks
- artifact existence checks
- test command execution wrappers
- WorkResult validation
- OracleResult validation
- event append
- state snapshot update
- markdown view rendering
- duplicate event idempotency
- retry budget counters
- structured tool denial and repair hints

Runtime/tools do not own:

- design judgment
- implementation strategy
- choosing exact code structure
- deciding how to fix failed tests
- inventing new tasks unless Smith asks
- semantic QA or final project acceptance
- project-management sequencing beyond enforcing valid leases and state transitions

## Smith Responsibility

Smith is the only conductor.

Smith loop:

```text
1. Read PROJECT.md.
2. Create or update PLAN.md and BACKLOG.md.
3. Select next pending task.
4. Create TaskPack.
5. Dispatch Morpheus/Worker.
6. Receive WorkResult.
7. If invalid, request Morpheus/Worker repair.
8. If blocked, decide replan, retry, or escalate.
9. If valid, mark task done and activate next task.
10. When all planned tasks are done, dispatch Oracle for whole-project validation.
11. Receive OracleResult.
12. If project PASS, mark project done.
13. If project FAIL, create a repair task for Morpheus/Worker using Oracle evidence.
```

Smith may replan future tasks when new facts appear, but must not change `PROJECT.md` goal without human/Neo approval.

Smith must be idempotent:

- duplicate Morpheus/Worker DONE must not advance twice
- duplicate Oracle project PASS must not mark the project done twice
- out-of-order task result must be rejected
- result for non-current attempt must be ignored or recorded as stale

## Morpheus/Worker Responsibility

Morpheus/Worker loop:

```text
1. Read TaskPack.
2. Inspect relevant files.
3. Create the task-local plan/design needed for this task.
4. Write required artifacts.
5. Write or update tests for this task.
6. Run diagnostic tests or task self-tests if useful.
7. Repair within budget.
8. Submit WorkResult.
9. If blocked, submit BLOCKED with exact reason.
```

Worker should not know run-dir internals.

Worker should not route messages to Oracle or Smith directly except through `submit_work_result`.

Worker should not edit project progress state.

## Oracle Responsibility

Oracle loop:

```text
1. Read PROJECT.md, PLAN.md, BACKLOG.md, all accepted WorkResults, artifacts, tests, and acceptance criteria.
2. Run whole-project validation or inspect accumulated evidence.
3. Write overall validation report.
4. Submit OracleResult.
```

Oracle should not repair code.

Oracle should not mark project state.

Oracle should not call Worker directly.

## Failure Handling

V4 failure policy must be simple and typed.

### Tool Failure

Tool returns structured error:

```json
{
  "status": "error",
  "code": "exec_allowlist | path_denied | validation_failed | timeout | missing_artifact",
  "message": "...",
  "repair_hint": "..."
}
```

Agent can retry only if the error is repairable.

### Agent Empty Stop

If an agent stops without a result:

- runtime records `agent_empty_stop`
- same TaskPack is retried once with a compact recovery prompt
- after retry budget, Smith receives `BLOCKED(agent_empty_stop)`

Do not leave project in silent `awaiting_artifacts`.

### Test Failure

If Morpheus/Worker's diagnostic test fails:

- Morpheus/Worker should repair
- if Morpheus/Worker cannot repair, submit `BLOCKED` or `NEEDS_REVIEW`
- runtime should not require Morpheus/Worker to call another command after a valid WorkResult exists

### Stale Session

V4 should prefer attempt-scoped sessions.

Each TaskPack attempt should create or use a fresh task-scoped session:

```text
agent:worker:project:<project_id>:task:<task_id>:attempt:<attempt_id>
```

No main-session task accumulation for Morpheus/Worker or Oracle in the V4 lane.

### Duplicate Messages

Every dispatch/result carries:

- `project_id`
- `task_id`
- `attempt_id`
- `event_id`

Tools reject duplicate terminal results for the same attempt unless they are exact idempotent repeats.

### Wrong Project Or Task

Result is invalid if:

- project id mismatches active project
- task id is not current
- attempt id is not current
- actor role is not allowed for the result type

## Observability

The failure analyzer becomes part of the normal V4 loop.

Required run report for every E2E canary:

- final project state
- event timeline
- current owner/waiting_for
- latest TaskPack
- latest WorkResult
- latest OracleResult
- repeated tool calls
- denied commands
- stale session evidence
- likely fault layer

The failure analyzer should be integrated as a Smith/Neo diagnostic tool later, but the first slice can keep it as a local CLI.

## V4 Project Lifecycle

```text
1. Neo creates project.
2. Smith plans tasks.
3. Smith activates T001.
4. Smith dispatches Morpheus/Worker attempt T001/A001.
5. Morpheus/Worker submits WorkResult.
6. Runtime validates WorkResult.
7. Smith marks T001 done or sends repair.
8. Repeat for next task.
9. Smith dispatches Oracle for whole-project validation.
10. Oracle submits OracleResult.
11. Smith marks project done or creates a repair task.
12. Neo reports to user.
```

No Niaobe in first slice.

No Architect as separate live target in first slice.

No worker-to-worker handoffs in first slice.

## Migration Plan

### Phase 0: Freeze And Map

Goal: avoid another broad rewrite.

Tasks:

- Keep current V3 system intact.
- Add V4 feature flag or separate entrypoint.
- Record current V3 known failures.
- Map reusable code:
  - `covenant_contracts.py`
  - `worker_runtime.py`
  - `agent_tools.py`
  - `task_progress.py`
  - `failure_analyzer.py`
  - existing canaries
- First Worker implementation target is Morpheus behind a V4 task packet.

Gate:

- V3 tests still pass.
- V4 path is isolated and does not change live default behavior.

### Phase 1: V4 Contracts

Goal: define the small V4 truth model.

Tasks:

- Add `TaskPackV4`.
- Add `WorkResultV4`.
- Add `OracleResultV4`.
- Add `EventV4`.
- Add focused tests for valid and invalid objects.
- Reuse existing Covenant contract code where it fits.

Gate:

- Invalid DONE without evidence is rejected.
- Wrong task/attempt result is rejected.
- Valid WorkResult and OracleResult are accepted.

### Phase 2: Project Event Store

Goal: one authoritative event/state source.

Tasks:

- Add project-local `.openclaw/events.jsonl` append helper.
- Add `.openclaw/state.json` snapshot helper.
- Add idempotency by `event_id`.
- Add work-order lease fields to active attempts.
- Add markdown view renderer for `PROJECT_STATE.md`, `BACKLOG.md`, and `CURRENT_TASK.md`.

Gate:

- State reconstructs from event log.
- Duplicate terminal result does not advance twice.
- Stale lease cannot mutate task artifacts or submit terminal results.
- Markdown view matches state snapshot.

### Phase 3: V6-Style Typed Tool Surface

Goal: remove raw path/command protocol from agents.

Tasks:

- Implement internal tool functions with MCP-shaped schemas:
  - `workspace.inspect`
  - `path.validate`
  - `fs.read`
  - `fs.write`
  - `fs.patch`
  - `tests.run`
  - `work.submit`
  - `work.block`
  - `oracle.verify`
  - `oracle.report`
- Keep wrappers project-scoped and task-scoped.
- Return structured errors with repair hints.

Gate:

- Agent does not need run dir or draft alias in prompt.
- Tool tests prove path normalization and allow/deny behavior.
- File content does not travel through shell command arguments.
- Tool denial returns structured error with repair hint.

### Phase 4: Smith Direct Conductor

Goal: Smith directly owns the task loop.

Tasks:

- Add V4 Smith prompt/tool guidance.
- Add Smith helper for plan/backlog/current task updates through event/state tools.
- Create work-order leases before dispatch.
- Dispatch Worker directly.
- Dispatch Oracle directly only for whole-project validation in the first lane.
- Remove Niaobe from V4 lane.

Gate:

- Smith can activate T001 and dispatch Morpheus/Worker from a project without Niaobe.
- Duplicate Smith handoff does not create duplicate active attempts.
- Smith does not advance from messages alone; it advances from typed WorkResult/OracleResult events.

### Phase 5: Morpheus Worker

Goal: Morpheus can plan, implement, test, repair, and submit one task as V4 Worker.

Tasks:

- Reuse Morpheus capability as V4 Worker.
- Give Worker one short TaskPack.
- Require Morpheus to produce task-local planning/design as part of the task attempt when needed.
- Worker writes artifacts through `write_artifact`.
- Worker writes or updates task tests through `write_artifact`.
- Worker submits WorkResult through `submit_work_result`.
- Runtime validates and stores result.
- Add recovery for empty stop and missing WorkResult.

Gate:

- Morpheus/Worker cannot leave task silently waiting after doing work.
- Morpheus/Worker can pass a simple implementation task with tests.
- Morpheus/Worker BLOCKED result reaches Smith with reason.

### Phase 6: Oracle Overall Project Verification

Goal: Oracle verifies the whole project without Niaobe after Smith has accepted all task WorkResults.

Tasks:

- Smith dispatches Oracle after all planned task WorkResults are accepted.
- Oracle receives project goal, plan/backlog, all accepted WorkResults, artifacts, tests, and acceptance criteria.
- Oracle submits OracleResult.
- Smith marks project done only after project-level PASS.

Gate:

- Oracle PASS marks project done.
- Oracle FAIL creates a repair task for Morpheus/Worker.
- Oracle result for stale project state is rejected.

### Phase 7: Fibonacci V4 E2E

Goal: prove the simple loop.

Tasks:

- Add `run_e2e_fibonacci_v4_test.sh` or equivalent isolated canary.
- Run full four-task Fibonacci flow:
  - Smith plans exactly four tasks.
  - Morpheus/Worker completes each task with task-local planning, implementation, and tests.
  - Smith advances tasks after accepted WorkResults.
  - Oracle verifies the final whole project.
  - Smith advances tasks.
  - Smith marks project done.
- Run the test three times with fresh sessions.

Gate:

- 3 consecutive passes.
- No manual repair.
- No stale session contamination.
- No duplicate terminal advancement.
- Failure analyzer reports no hidden unresolved state.

### Phase 8: MCP Adapter

Goal: expose the stable V4 tool surface through MCP if still useful.

Tasks:

- Wrap V4 internal tools as MCP server tools.
- Keep tool names explicit and scoped.
- Add tool admission policy.
- Add structured audit logs.
- Add MCP server tests independent of live agents.

Gate:

- MCP tools behave exactly like internal V4 tools.
- No arbitrary filesystem/shell access is exposed.
- MCP failures return structured repairable errors.

### Phase 9: Deferred PR, Sandbox, And Specialist Capabilities

Goal: adopt the remaining useful V6 capabilities only after the local Smith/Morpheus/Oracle loop is reliable.

Deferred V6 capabilities:

- PR tools: `pr.open`, `pr.status`, `pr.review`, `pr.request_changes`, `pr.merge`, `pr.revert`.
- Sandbox broker: rootless/user-namespace containers, no ordinary agent access to the host Docker socket, scoped network classes.
- Release roles: Trinity for release/merge, Sentinel for security/policy review.
- Niaobe as a coordinator for multiple concurrent work orders.
- Architect as a separate direct Smith-called specialist for design-heavy work.

Gate:

- Fibonacci V4 E2E has passed 3 consecutive times.
- One induced repair has completed through Morpheus/Worker without manual intervention.
- Oracle has passed one whole-project validation and failed one induced validation with a repair task.
- Failure analyzer reports no unresolved state or stale-session contamination.

### Phase 10: Optional Specialist Reintroduction

Goal: add specialization only after the simple loop is reliable.

Possible additions:

- Architect as direct Smith-called design specialist.
- Separate Implementer if Worker becomes too broad.
- Tester specialist if Oracle becomes overloaded.
- Niaobe only if there is a real need for concurrent multi-task coordination.

Rules:

- Specialists report directly to Smith.
- Specialists use the same TaskPack/WorkResult shape.
- No specialist may own project progress state.
- No new role gets added unless it reduces observed complexity.

## Acceptance Criteria For V4

V4 is useful only when it can pass these gates:

- A fresh Fibonacci E2E project completes 3 consecutive times.
- Smith is the only project progress owner.
- Every task has exactly one current attempt.
- Morpheus/Worker can submit DONE only with artifacts and verification.
- Oracle can independently pass/fail whole-project validation.
- Failed Oracle validation returns to Morpheus/Worker as a repair task.
- Duplicate messages do not advance the project twice.
- Stale attempt results are rejected.
- No task remains silently waiting without a next action.
- Failure analyzer can explain any failed run with a clear layer.
- Agents do not need to construct raw run-dir report commands.
- File changes go through typed file tools, not shell payload wrappers.
- Work-order leases prevent stale attempts from mutating or submitting results.
- Mattermost/session messages are treated as reports, not truth.

## What We Keep From V3

Keep:

- OpenClaw as the agent/tool/session platform.
- Local Ollama model execution.
- Existing project directory layout under clawspace.
- Existing contract lessons: WorkResult, VerificationEvidence, ArtifactManifest.
- Existing project-rooted file and exec safety ideas.
- Failure analyzer.
- Canary discipline.
- Smith planning concepts.
- Oracle as verifier.
- Morpheus implementation capability as the first V4 Worker.

## What We Stop Doing In First V4 Slice

Stop:

- live Smith -> Niaobe -> worker chains
- Niaobe-owned child result resolution
- Architect as mandatory separate live handoff
- Worker-facing raw `RUN_DIR` and `NEXT_REQUIRED` protocol
- shell-wrapper payload writing
- untyped raw command protocols for normal work submission
- long-lived worker main-session task accumulation
- treating markdown as authoritative state
- writing new role-specific lifecycle scripts for each failure
- fixing every failed run by adding more prompt ceremony

## Design Risks

### Risk: Morpheus/Worker Becomes Too Broad

Mitigation:

Keep Morpheus/Worker task-scoped. If tasks are too broad, Smith splits them smaller. Do not split Worker into more agents until the loop passes reliably.

### Risk: Smith Becomes Bottleneck

Mitigation:

This is acceptable initially. Reliability is more important than parallelism. After stability, Smith can run multiple independent task attempts with event-based locks.

### Risk: MCP Adds New Complexity

Mitigation:

Build MCP after internal tools are stable. MCP is an adapter, not the first implementation.

### Risk: Markdown Views Drift

Mitigation:

Generate markdown views from event/state tools. Do not ask agents to manually keep all markdown files synchronized.

### Risk: Oracle Blocks Too Much

Mitigation:

Oracle is required only for whole-project validation in the first V4 lane. Later, Smith may use risk-based task-level verification policy.

## First Implementation Slice Recommendation

Do not migrate everything.

Build the smallest V4 lane:

```text
new_project_v4
smith_v4_plan
smith_v4_dispatch_morpheus_worker
morpheus_worker_v4_submit
smith_v4_dispatch_oracle_project_validation
oracle_project_v4_submit
smith_v4_advance
run_e2e_fibonacci_v4
```

Use existing code internally where possible, but expose a simpler agent-facing contract.

First live test:

```text
Fibonacci Tree Visualizer, four sequential tasks
```

Success means:

- T001 done and verified
- T002 done and verified
- T003 done and verified
- T004 done and verified
- Morpheus/Worker produced task-local plans, implementation artifacts, and tests for each task
- Oracle project-level validation PASS
- project marked DONE
- final report sent to Neo/user

## Final Recommendation

V4 should not be a bigger version of V3.

V4 should be the minimum reliable autonomous software team:

```text
Neo for human interface.
Smith for project control.
Morpheus/Worker for bounded task planning, implementation, and tests.
Oracle for whole-project validation.
Tools for truth.
Events for memory.
Markdown for readability.
```

Once that loop is boring and repeatable, specialization can come back.
