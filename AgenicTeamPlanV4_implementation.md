# AgenticTeam V4 Implementation Plan

Source design: `AgenicTeamPlanV4.md`

## Purpose

This document turns the V4 design into an implementation sequence agents can follow without broad rewrites.

Primary goal:

```text
Build the lean V4 lane beside V3:
Neo -> Smith -> Morpheus/Worker -> Smith -> Oracle -> Smith -> Neo
```

V4 must prove that work can complete through typed tools, event-backed state, leases, and evidence-backed results before any V3 path is removed or any paused specialist role is reintroduced.

## Non-Negotiable Rules

- Work one phase at a time.
- Before editing a phase, state the expected behavior.
- Make the smallest validated change that advances the phase.
- Keep V3 behavior intact unless a phase explicitly says otherwise.
- Do not delete V3 runtime, prompts, canaries, or compatibility paths during this plan.
- Do not make V4 the live default until the V4 E2E gate passes.
- Do not add Niaobe, Architect, PR tools, sandbox broker, or release roles to the first V4 lane.
- Do not expose raw `RUN_DIR`, draft aliases, or `NEXT_REQUIRED` as the normal V4 agent contract.
- Do not pass file content through shell command arguments.
- Do not treat chat, Mattermost, markdown, or session prose as authoritative state.
- Stop on validation failure and repair before continuing.

## Implementation Shape

Prefer additive files and thin adapters first.

Likely implementation areas:

- `AgenticTeam/scripts/`
- `AgenticTeam/config/`
- `AgenticTeam/agents/`
- `AgenticTeam/templates/`
- `AgenticTeam/fixtures/`
- `tests/`
- `.agents/memory/`

Recommended V4 module names:

```text
AgenticTeam/scripts/v4_contracts.py
AgenticTeam/scripts/v4_events.py
AgenticTeam/scripts/v4_tools.py
AgenticTeam/scripts/v4_smith.py
AgenticTeam/scripts/v4_worker.py
AgenticTeam/scripts/v4_oracle.py
AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py
```

These names are recommendations, not mandatory. If an existing module can be extended cleanly without coupling V4 to V3 behavior, reuse it.

## Evidence Standard

Every phase report must include:

- Phase ID
- Expected behavior
- Files changed
- Validation commands
- Result
- Evidence paths or command output summary
- Known gaps
- Next phase

Every milestone report must include:

- Milestone ID
- Completed phases
- Gate status
- Regression status
- Whether the next milestone is allowed to start

## Validation Levels

Use the narrowest useful validation first, then broaden at milestone gates.

Level 1: focused unit tests

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/<focused_test_file>.py
```

Level 2: related runtime tests

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_covenant_contracts.py tests/test_worker_runtime.py
```

Level 3: full local suite

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Level 4: V4 canary or E2E

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --timeout-seconds 900 --stall-seconds 180
```

If the exact V4 E2E entrypoint does not exist yet, the phase that creates it must also define its validation command.

## Stop Conditions

Stop and report blocked if any of these are true:

- A task can reach DONE without `WorkResultV4` evidence.
- A stale attempt can mutate files or submit a terminal result.
- Smith advances from chat text instead of a typed event/result.
- Oracle PASS/FAIL is accepted for the wrong project state.
- Markdown views disagree with `.openclaw/state.json`.
- Tool denial returns only prose without a typed failure code and repair hint.
- File content is passed through shell command arguments.
- A V4 change breaks V3 tests without an explicit approved compatibility decision.
- The next change requires deleting or rewriting a broad V3 subsystem.

## Milestone 0: Baseline And Isolation

Goal: create a safe V4 work lane without changing V3 live behavior.

### Phase 0.1: Baseline Current System

Expected behavior:

V3 tests and current focused canaries have a known baseline before V4 work starts.

Tasks:

- Record current `git status --short`.
- Run the full local test suite.
- Run or inspect the latest relevant V3 canary baseline.
- Record known failures instead of fixing unrelated issues.
- Confirm V4 work will be additive and gated.

Validation:

```bash
git status --short
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Gate:

- Baseline is recorded.
- Known failures, if any, are classified.
- No V4 edits have started before baseline evidence exists.

### Phase 0.2: Add V4 Isolation Switch

Expected behavior:

V4 code can be imported and tested without becoming the default live path.

Tasks:

- Add a V4 feature flag or explicit V4 entrypoint.
- Ensure existing V3 scripts remain default.
- Add a tiny smoke test proving V4 is off unless explicitly selected.
- Document how an agent invokes V4 during tests.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_bootstrap.py
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Gate:

- V4 is isolated.
- V3 tests still pass or have the same known baseline failures.
- No live OpenClaw default has changed.

Milestone 0 gate:

- V4 has an explicit isolated entrypoint or flag.
- The repo has a clean baseline report.
- Work may proceed to contracts only.

## Milestone 1: V4 Contracts

Goal: define the typed truth objects before implementing behavior.

### Phase 1.1: Add Contract Models

Expected behavior:

`TaskPackV4`, `WorkResultV4`, `OracleResultV4`, `EventV4`, and `LeaseV4` can be validated without touching live runtime.

Tasks:

- Reuse `covenant_contracts.py` where it fits.
- Add V4-specific adapters only where existing Covenant models are too broad or V3-shaped.
- Define required fields for:
  - project identity
  - task identity
  - attempt identity
  - actor
  - lease
  - artifacts
  - verification evidence
  - status
  - repair/block reason
- Add focused positive and negative tests.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_contracts.py
```

Gate:

- Invalid object shapes are rejected.
- Missing `work_result` style payloads get repair feedback.
- Valid minimal objects pass.

### Phase 1.2: Add Completion Validation Rules

Expected behavior:

DONE cannot be accepted unless required evidence, artifacts, task id, attempt id, and lease are valid.

Tasks:

- Add `validate_work_result_v4`.
- Add `validate_oracle_result_v4`.
- Add exact repair-feedback examples for invalid responses.
- Add tests for:
  - DONE without evidence
  - DONE with missing artifacts
  - DONE with stale lease
  - DONE for wrong task
  - BLOCKED with reason
  - FAILED with reason
  - Oracle PASS with evidence
  - Oracle FAIL with repair reason

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_contracts.py
```

Gate:

- False DONE is impossible at the contract layer.
- Oracle PASS/FAIL is typed and evidence-backed.

Milestone 1 gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_contracts.py tests/test_covenant_contracts.py
```

Allowed to proceed only when V4 contracts pass and Covenant contract regressions are absent.

## Milestone 2: Event Store, State Snapshot, And Leases

Goal: create the authoritative V4 truth layer.

### Phase 2.1: Add Append-Only Event Store

Expected behavior:

Project-local `.openclaw/events.jsonl` records typed V4 events idempotently.

Tasks:

- Add event append helper.
- Add deterministic or caller-supplied `event_id`.
- Add duplicate-event handling.
- Add event read/query helper.
- Store tool calls, tool failures, dispatches, submissions, state transitions, lease changes, and Oracle results.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_events.py
```

Gate:

- Duplicate events do not create duplicate transitions.
- Corrupt events are rejected with actionable errors.

### Phase 2.2: Add State Snapshot Renderer

Expected behavior:

`.openclaw/state.json` is derived from events, and markdown files are rendered views.

Tasks:

- Add state projection from events.
- Add atomic write for `.openclaw/state.json`.
- Render `PROJECT_STATE.md`, `BACKLOG.md`, and `CURRENT_TASK.md` from state.
- Add drift detection between state and markdown.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_events.py tests/test_v4_state.py
```

Gate:

- State reconstructs from events.
- Markdown views match state.
- Manual markdown mutation is detected as drift.

### Phase 2.3: Add Lease Enforcement

Expected behavior:

Only the current live attempt lease can mutate artifacts or submit terminal results.

Tasks:

- Add lease create, validate, renew if needed, release, and expire behavior.
- Tie lease to project id, task id, attempt id, actor, and capability scope.
- Add stale lease tests for file writes, test runs, work submit, and Oracle submit.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_state.py tests/test_v4_leases.py
```

Gate:

- Stale attempts fail closed.
- Duplicate terminal results do not advance state twice.
- Active lease state is visible in `.openclaw/state.json`.

Milestone 2 gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_events.py tests/test_v4_state.py tests/test_v4_leases.py
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Allowed to proceed only when V4 state is event-backed and V3 tests are not regressed.

## Milestone 3: Typed Tool Plane

Goal: replace fragile shell payload contracts with typed, scoped tools.

### Phase 3.1: Add Read And Discovery Tools

Expected behavior:

Agents can inspect project structure and read files through scoped tools.

Tasks:

- Add `workspace.inspect`.
- Add `repo.map` or equivalent project tree summary.
- Add `repo.search`.
- Add `fs.list`.
- Add `fs.read`.
- Ensure tools know project id, task id, attempt id, actor, workspace, and lease where relevant.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_tools.py -k "inspect or read or search or list"
```

Gate:

- Reads are scoped to the declared workspace.
- Outside-workspace reads fail with structured repair feedback.

### Phase 3.2: Add Safe Mutation Tools

Expected behavior:

Agents can write, patch, and create directories only inside allowed paths for the active lease.

Tasks:

- Add `path.validate`.
- Add `fs.mkdir`.
- Add `fs.write`.
- Add `fs.patch`.
- Add structured error codes:
  - `path_outside_workspace`
  - `path_not_allowed`
  - `stale_lease`
  - `invalid_payload`
  - `content_too_large`
- Record every mutation as an event.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_tools.py -k "path or write or patch or mkdir"
```

Gate:

- No shell-argument file payload path exists in the V4 tool path.
- Denied writes return repair hints.
- Mutations produce audit events.

### Phase 3.3: Add Execution And Evidence Tools

Expected behavior:

Agents can discover and run tests through scoped tools that store evidence.

Tasks:

- Add `tests.discover`.
- Add `tests.run`.
- Add limited `cmd.preflight`.
- Add limited `cmd.run` only if needed and only through allowlisted project commands.
- Store command, exit code, output summary, and evidence path.
- Return structured tool-denial errors.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_tools.py -k "tests or cmd or evidence"
```

Gate:

- Test evidence is stored and referenced by result validation.
- Denied commands are first-class tool failures.
- Runtime does not hide or stringify denial into success-shaped prose.

### Phase 3.4: Add Work And Oracle Submission Tools

Expected behavior:

Agents submit terminal results through typed tools, not chat or raw report commands.

Tasks:

- Add `work.submit`.
- Add `work.block`.
- Add `work.status`.
- Add `oracle.verify`.
- Add `oracle.report`.
- Enforce contract validation before terminal state transition.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_tools.py tests/test_v4_contracts.py
```

Gate:

- `work.submit` rejects invalid DONE.
- `work.block` requires actionable reason.
- `oracle.report` rejects stale state.
- Chat-only DONE does not mutate state.

Milestone 3 gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_tools.py tests/test_v4_contracts.py tests/test_v4_events.py tests/test_v4_state.py
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Allowed to proceed only when the typed tool plane can complete a simulated task without raw shell payloads.

## Milestone 4: Smith Direct Conductor

Goal: Smith becomes the only V4 project progress owner.

### Phase 4.1: Add Smith V4 Planning Path

Expected behavior:

Smith can create a plan, backlog, current task, and state through V4 events without Niaobe.

Tasks:

- Add V4 Smith prompt/tool guidance.
- Add a Smith V4 planning helper or tool path.
- Create `PLAN.md`, `BACKLOG.md`, `CURRENT_TASK.md`, and `.openclaw/state.json` as rendered views/state.
- Ensure `PROJECT.md` remains the immutable goal unless explicitly amended by the user.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_smith.py -k "plan or backlog or current"
```

Gate:

- Smith creates task plan from a project fixture.
- State and markdown agree.
- Niaobe is not part of the V4 path.

### Phase 4.2: Add Smith Task Dispatch

Expected behavior:

Smith activates the next task, creates a lease, dispatches one TaskPack to Morpheus/Worker, and records the event.

Tasks:

- Add `smith_v4_dispatch_worker`.
- Create one active attempt per task.
- Add duplicate-dispatch idempotency.
- Add repair/block handling hooks without implementing broad replanning yet.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_smith.py -k "dispatch or lease or duplicate"
```

Gate:

- Duplicate Smith dispatch does not create duplicate active attempts.
- Smith does not advance from messages alone.
- TaskPack is short and points agents to read/search tools for context.

### Phase 4.3: Add Smith Result Handling

Expected behavior:

Smith accepts valid WorkResult events, marks tasks done, activates next tasks, creates repair tasks on block/fail, and stops after final Oracle result.

Tasks:

- Add `smith_v4_accept_work_result`.
- Add next-pending task transition.
- Add duplicate terminal idempotency.
- Add out-of-order result rejection.
- Add final Oracle dispatch trigger after all planned tasks are accepted.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_smith.py
```

Gate:

- Duplicate TASK_DONE does not advance twice.
- Out-of-order WorkResult is rejected.
- All tasks done triggers Oracle dispatch, not project DONE.

Milestone 4 gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_smith.py tests/test_task_progress.py
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Allowed to proceed only when Smith can run the project-progress loop in pure unit/integration tests without Niaobe.

## Milestone 5: Morpheus Worker Lane

Goal: Morpheus can complete one bounded task through V4 tools and one WorkResult.

### Phase 5.1: Add Morpheus V4 Task Packet Surface

Expected behavior:

Morpheus receives a compact TaskPack and typed tool instructions, not run-dir/report-command ceremony.

Tasks:

- Add V4 Morpheus prompt/tool section.
- Keep current V3 Morpheus surfaces intact.
- Register V4 task-scoped sessions or equivalent isolated execution context.
- Include explicit rule: if work cannot complete, call `work.block` with reason.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_morpheus.py -k "packet or prompt or session"
```

Gate:

- TaskPack does not expose raw run directory protocol.
- Morpheus has typed write/test/submit/block actions.

### Phase 5.2: Add Single-Task Worker Canary

Expected behavior:

Morpheus completes a tiny task with implementation, test evidence, and WorkResult.

Tasks:

- Add a small V4 worker fixture.
- Dispatch Morpheus through Smith or a direct V4 worker harness.
- Require at least one artifact and one verification evidence record.
- Validate accepted WorkResult advances state.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_v4_worker_canary.py --fixture minimal_python_cli --timeout-seconds 300 --stall-seconds 90
```

Gate:

- Morpheus submits WorkResult through typed tool path.
- DONE without evidence is rejected in the same canary family.
- Empty stop becomes repairable or blocked, not silent waiting.

### Phase 5.3: Add Worker Repair Loop

Expected behavior:

If tests fail or validation rejects the result, Morpheus gets compact repair feedback and can retry within budget.

Tasks:

- Add retry budget to TaskPack/attempt state.
- Feed structured failure back to Morpheus.
- Ensure repair attempts keep the same task but new attempt identity if needed.
- Add tests for failed test -> repair -> accepted result.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_morpheus.py -k "repair or retry or blocked"
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_v4_worker_canary.py --fixture minimal_python_cli --induce-failure --timeout-seconds 450 --stall-seconds 120
```

Gate:

- Repair is driven by structured evidence, not prose guessing.
- Retry budget exhaustion returns BLOCKED to Smith.

Milestone 5 gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_morpheus.py tests/test_v4_tools.py tests/test_v4_smith.py
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_v4_worker_canary.py --fixture minimal_python_cli --timeout-seconds 300 --stall-seconds 90
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Allowed to proceed only when Morpheus can finish one task through V4 without raw report commands.

## Milestone 6: Oracle Whole-Project Verification

Goal: Oracle validates final project state after Smith accepts all WorkResults.

### Phase 6.1: Add Oracle V4 Verification Surface

Expected behavior:

Oracle receives project goal, plan, accepted WorkResults, artifacts, tests, and acceptance criteria through scoped tools/context.

Tasks:

- Add V4 Oracle prompt/tool section.
- Keep V3 Oracle behavior intact.
- Add `oracle.verify` and `oracle.report` integration with V4 state.
- Ensure Oracle cannot mutate project artifacts.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_oracle.py -k "surface or verify or report"
```

Gate:

- Oracle reads enough evidence to judge project acceptance.
- Oracle cannot write implementation files.

### Phase 6.2: Add Oracle Result Handling In Smith

Expected behavior:

Smith marks project DONE only after Oracle PASS; Oracle FAIL creates a repair task for Morpheus.

Tasks:

- Add Smith handling for `OracleResultV4`.
- Add PASS transition to project DONE.
- Add FAIL transition to repair task.
- Add stale Oracle result rejection.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_oracle.py tests/test_v4_smith.py -k "oracle"
```

Gate:

- PASS marks project DONE.
- FAIL creates a repair task without changing `PROJECT.md`.
- Stale Oracle result is rejected.

### Phase 6.3: Add Oracle Positive And Negative Canaries

Expected behavior:

Oracle can pass a correct completed project and fail an induced broken project with repair evidence.

Tasks:

- Add small completed fixture.
- Add induced-failure fixture.
- Add analyzer evidence for Oracle fail path.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_v4_oracle_canary.py --fixture completed_minimal_project --timeout-seconds 300 --stall-seconds 90
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_v4_oracle_canary.py --fixture broken_minimal_project --expect-fail --timeout-seconds 300 --stall-seconds 90
```

Gate:

- Correct project passes.
- Broken project fails with repair task.
- Oracle failure does not mark project DONE.

Milestone 6 gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_oracle.py tests/test_v4_smith.py tests/test_v4_contracts.py
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
```

Allowed to proceed only when Oracle is integrated as final verifier and not as a per-task bottleneck.

## Milestone 7: V4 Fibonacci E2E

Goal: prove the full lean loop.

### Phase 7.1: Add Isolated V4 Fibonacci Runner

Expected behavior:

The V4 Fibonacci test creates a fresh project and runs through Smith, Morpheus, Smith, Oracle, Smith without Niaobe.

Tasks:

- Add `run_e2e_fibonacci_v4_test.py` or equivalent.
- Use a fresh project id for every run.
- Use fresh task-scoped sessions.
- Capture event log, state snapshot, worker results, Oracle report, and failure analyzer output.
- Do not reuse V3 live project state.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --dry-run
```

Gate:

- Dry run shows the intended V4 lane and expected files.
- Runner refuses to use Niaobe.

### Phase 7.2: Run First Live V4 Fibonacci

Expected behavior:

One Fibonacci project completes through V4 or fails with a clear fault layer.

Tasks:

- Run one fresh V4 Fibonacci E2E.
- If it fails, run failure analyzer.
- Fix only the classified layer.
- Rerun the same canary after repair.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --timeout-seconds 900 --stall-seconds 180
```

Gate:

- Either PASS, or failure analyzer identifies one clear layer and the phase stops for repair.
- No silent waiting state is accepted.

### Phase 7.3: Three Consecutive Passes

Expected behavior:

V4 proves repeatability, not a lucky single pass.

Tasks:

- Run three fresh V4 Fibonacci projects.
- Reset or rotate only V4 task-scoped sessions between runs as defined by the runner.
- Compare event/state/report shape across runs.
- Confirm no duplicate terminal advancement.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --repeat 3 --timeout-seconds 900 --stall-seconds 180
```

Gate:

- 3 consecutive passes.
- Failure analyzer reports no unresolved state.
- Smith is the only progress owner.
- Morpheus handles all implementation tasks.
- Oracle passes final whole-project validation.

Milestone 7 gate:

- V4 can be considered a candidate lane after three consecutive Fibonacci passes.
- V3 is still present and testable.
- A user decision is required before making V4 default.

## Milestone 8: V4 Default Decision

Goal: decide whether V4 becomes the default lane.

### Phase 8.1: Default-Readiness Audit

Expected behavior:

The team can see exactly what changes if V4 becomes default.

Tasks:

- List V3 entrypoints that would remain available.
- List V4 entrypoints that would become default.
- List prompt/config sync changes required.
- List rollback path.
- Run full tests and the latest V4 Fibonacci repeat gate.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --repeat 3 --timeout-seconds 900 --stall-seconds 180
```

Gate:

- Human approval is required before changing live default behavior.
- No code change in this phase should flip the default without approval.

### Phase 8.2: Controlled Default Switch

Expected behavior:

If approved, new test projects use V4 by default while V3 remains available as fallback.

Tasks:

- Switch only the approved entrypoint/config.
- Keep V3 fallback documented.
- Sync live OpenClaw config only if approved.
- Run one smoke project and one Fibonacci project.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --timeout-seconds 900 --stall-seconds 180
```

Gate:

- Default switch succeeds.
- Rollback path is still valid.

Milestone 8 gate:

- V4 can be default only after explicit user approval and passing validation.

## Milestone 9: MCP Adapter And Deferred V6 Capabilities

Goal: add richer infrastructure only after the lean lane is stable.

### Phase 9.1: MCP Adapter

Expected behavior:

The stable V4 tool plane is exposed through MCP-shaped tools without changing semantics.

Tasks:

- Wrap internal V4 tools as MCP server tools.
- Keep schemas identical or mechanically mapped.
- Add MCP tests independent of live agents.
- Deny arbitrary filesystem and shell access.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_mcp_tools.py tests/test_v4_tools.py
```

Gate:

- MCP adapter returns the same success/failure semantics as internal tools.
- No broader host access is exposed.

### Phase 9.2: Sandbox Broker

Expected behavior:

Docker/network capability is brokered by typed tools, not handed to normal agents.

Tasks:

- Design before implementation.
- Add sandbox capability classes.
- Add network policy classes.
- Add audit events.
- Add tests for denied host socket access.

Validation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_sandbox_broker.py
```

Gate:

- Human approval required before implementation.
- No ordinary agent gets raw host Docker socket access.

### Phase 9.3: PR And Specialist Roles

Expected behavior:

PR lifecycle and specialist roles are introduced only when they reduce proven complexity.

Tasks:

- Decide whether PR tools are needed.
- Decide whether Architect should return as a direct Smith-called specialist.
- Decide whether Niaobe is needed for concurrent work orders.
- Decide whether Trinity/Sentinel are needed for release/security gates.
- Every new role must use the same TaskPack/WorkResult or OracleResult pattern.

Validation:

Defined per approved design.

Gate:

- Human approval required.
- New roles must not own project progress state.
- New roles must not reintroduce chat as control plane.

## Phase Report Template

Use this at the end of every phase:

```text
Phase:
Expected behavior:
Files changed:
Validation commands:
Result:
Evidence:
Known gaps:
Next phase:
Gate status: PASS | FAIL | BLOCKED
```

## Milestone Report Template

Use this before moving to the next milestone:

```text
Milestone:
Completed phases:
Gate validation:
Regression validation:
Faults found:
Repairs made:
Evidence:
Decision needed:
Next milestone allowed: yes | no
```

## Recommended First Work Order

Start with Milestone 0 only.

First agent instruction:

```text
Implement AgenticTeam V4 Milestone 0 from AgenicTeamPlanV4_implementation.md.
Do not start Milestone 1.
Record baseline, add only the V4 isolation switch or entrypoint, run the stated validations, and stop with a phase report.
```

## Final Rule

V4 succeeds when it removes failure classes instead of moving them.

If a proposed fix adds another role-specific script, another long prompt protocol, or another state source, stop and redesign the phase around typed tools, leases, events, and evidence.
