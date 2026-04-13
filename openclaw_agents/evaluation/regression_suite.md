# Regression Suite

This document defines the minimum regression coverage for the current control-plane implementation.

## Goals

- catch schema drift between prompts, routing, and persisted state
- catch scheduler regressions around leases, pause, resume, switch, and recovery
- catch gateway regressions around authoritative versus non-authoritative Zulip messages
- catch artifact persistence and reload failures
- keep one reproducible end-to-end happy path working

## Test Layers

### 1. Contract Validation

Run on every change to config, schemas, prompts, or state-machine files.

- JSON schemas parse
- YAML config files load
- prompt files exist for every agent in `agent_registry.yaml`
- every task type in routing rules maps to a registered agent
- Niobe and Morpheus state machines preserve the required invariants

### 2. Persistence And Store Tests

Exercise `openclaw_agents/database/store.py` against a temporary SQLite database.

- schema initialization is idempotent
- project, scheduling, workspace, lease, snapshot, and control-event records round-trip
- JSON fields are normalized and reloaded correctly
- orchestrator lease rows are auto-created for `niobe` and `morpheus`

### 3. Scheduler Tests

Exercise:

- queue inspection and eligibility explanations
- single active lease per orchestrator
- lease renewal, release, and stale-lease expiry
- pause and resume control commands
- switch safety at valid and invalid boundaries
- forced interrupt creating recovery requirements
- workspace validation blocking unsafe resume

### 4. Gateway Tests

Exercise `openclaw_agents/communication/zulip_gateway.py` with synthetic `GatewayEvent` inputs.

- free-form human intake creates a `FRAME_PROJECT` task for `AgentSmith`
- authoritative task assignment validates and dispatches correctly
- authoritative task result persists and routes correctly
- control commands persist immutable control events
- duplicate Zulip message ids are dropped
- malformed YAML or schema violations are rejected without mutating authoritative state

### 5. Artifact Tests

Exercise `artifact_serializers.py` and `artifact_parsers.py`.

- inline JSON artifact round-trip
- workspace-backed artifact round-trip
- artifact refs persist with the correct project and task ids
- report artifacts land under the expected workspace path

### 6. Recovery Tests

Exercise:

- missing snapshot blocks resume
- missing workspace state blocks resume
- missing repo root or workspace path blocks resume
- manual workspace repair followed by successful validation
- recovery event persistence for forced interrupt and failed resume assessment

### 7. End-To-End Smoke Path

Keep one scriptable path that proves the intended MVP still works:

1. seed a project and workspace
2. send a free-form intake message
3. let `AgentSmith` frame the project
4. let `Niobe` choose the next step
5. persist a design artifact
6. persist a software delivery artifact
7. persist a verification report
8. verify closure eligibility

## Minimum Acceptance Bar

- no placeholder prompt or runbook files remain except intentionally deferred operational wrappers
- contract validation passes
- scheduler, gateway, artifact, and recovery smoke tests pass
- the end-to-end smoke path produces persisted project, task, artifact, snapshot, and control-event records

## Current Known Gap

- `Neo` and `MASTER` execution logic remains intentionally deferred. The regression suite should keep them out of required end-to-end coverage until their runtime behavior is implemented.
