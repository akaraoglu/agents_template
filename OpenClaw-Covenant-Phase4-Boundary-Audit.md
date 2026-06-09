# OpenClaw Covenant Phase 4 Boundary Audit

Date: 2026-06-02

This audit records the current runtime boundary map after Phase 3A and the first universal-loop slices.

## Deferred Old Roadmap Items

Deferred until a live universal-loop path proves they are the bottleneck:

- Canonical state migration
- Large event-ledger expansion
- Capability bundles
- Generated context packs
- Typed task-graph operations
- WorkflowEngine / LangGraph as the agent runtime
- Broad prompt rewrites

## Current Role-Specific Runtime Paths

- Smith planning: transitional compatibility path that still uses a prepare phase, explicit next-action contract, and terminal handoff to Niaobe.
- Architect design: design-only path that writes `management/architecture/T001.md` and then hands off to Niaobe.
- Morpheus implementation: live universal-loop candidate; writes drafts, manifest, validation evidence, and terminal result data for Niaobe validation.
- Oracle verification: runtime-owned verification path that writes validation evidence and reports a pass/fail outcome back to Niaobe.
- Niaobe routing: parent boundary that validates child outcomes, records handoffs, and decides the next owner.

## Five Runtime Boundaries

| Path | Workspace | Task | Change | Verification | Handoff |
| --- | --- | --- | --- | --- | --- |
| Smith planning | project workspace + draft aliases | sequential task planning | planning docs only | plan structure / task list | Smith -> Niaobe |
| Architect design | project workspace | `management/architecture/T001.md` | design doc | required section validation | Architect -> Niaobe |
| Morpheus implementation | project workspace + runtime drafts | `README.md`, `src/main.py`, `tests/test_main.py` | code + tests | declared unit test command | Morpheus -> Niaobe |
| Oracle verification | project workspace + validation output | `management/validation/T001_REPORT.md` | report file | test execution / verdict | Oracle -> Niaobe |
| Niaobe routing | project root + runtime state | ownership and task state | state transitions only | parent validation of child reports | Niaobe -> next owner |

## Silent Or Semi-Silent Waiting States

Observed or explicitly guarded states that must not hide the next step:

- `awaiting_artifacts`
- `repair_needed` without repair feedback visible to the agent
- missing `result.json`
- valid drafts with no terminal `result.json`
- state that implies humans must infer the next command
- finish-line draft readiness without explicit runtime outcome

## First Universal-Loop Path

Selected path: Morpheus implementation.

Reason:

- It exercises real file creation, validation, and terminalization.
- It exposed the finish-line stall most clearly.
- It is the smallest path that proves whether runtime-owned completion works.

## Failure-Layer Classification Checklist

Before changing runtime code, classify the fault as one of:

- stale session
- unsynced prompt/tool surface
- agent non-compliance
- runtime validation bug
- state or identity bug
- canary expectation bug

## Prompt / Tool Sync Checklist

- Verify live prompt surfaces match the repo prompts.
- Verify active sessions are fresh before using a canary failure as a design signal.
- Verify the agent saw the current task packet and helper contract.
- Do not treat a stale session as proof that the protocol is wrong.

## Compatibility Inventory

- Smith prepare flow: compatibility-only, kept working while phase-specific choreography is reduced.
- Architect path helpers: compatibility internals, not new agent-facing protocol.
- Morpheus prepare/complete split: transitional, should collapse into one universal work-report outcome later.
- Oracle verification helpers: compatibility internals until the universal work report owns terminalization.
- Niaobe routing helpers: runtime internals, not agent-facing workflow choreography.

## Terminalization Inventory

- Current converted paths still expose some transitional `prepare -> write drafts -> complete` behavior.
- The remaining agent-facing finish surface should shrink toward one universal report submission.
- Runtime outcome handling must own persistence, validation, and next-owner routing.
- Separate finalizer commands should disappear from agent-facing paths after the universal loop is stable.
