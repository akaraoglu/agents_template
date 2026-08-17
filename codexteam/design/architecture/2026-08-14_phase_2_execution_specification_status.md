# Phase 2: Immutable Execution Specification

## Status

Implemented. Every new current draft attempt receives one immutable execution
specification in its existing session directory.

## Completed Work

- Added `execution-spec-current` to the contract registry.
- Added `schemas/execution-spec-current.json` and the current-native builder/validator in
  `codexteam_tools.execution_spec`.
- New attempts write `execution-spec-current.json` before worker execution.
- Dry-run displays the resolved specification without writing files.
- Session current stores the specification contract, path, and digest reference.
- Feedback and final turns reload and verify the same specification.
- Identity, RolePolicy, guidance, backend, model, reasoning, permissions,
  handoff digest, and gate-routing drift fail closed.
- OpenCode records requested role reasoning separately from its unproven
  effective effort using `provider_default`.
- Handoff provenance stores only source path and exact content digest.
- Raw prompts, feedback, credentials, tokens, MCP queries, and MCP responses are
  excluded.
- Pre-cutover active attempts without the current specification are not resumed
  and are never backfilled.
- Status and attempt summaries distinguish valid, absent, and invalid specs.
- Worker-side specification tampering is detected before evidence/state writes.
- Failed finalization restores result, session, and prior turn-state consistently.

## Authority Model

| Record | Authority |
|---|---|
| Task handoff | Canonical task objective and acceptance authority |
| RolePolicy | Lifecycle responsibility and permission ceiling |
| Execution specification | Immutable supporting identity for one attempt |
| Session | Mutable draft/feedback/final progression |
| Result current | Final worker report |
| Gates and close-loop | Verification and canonical closure authority |

The execution specification cannot approve work, run gates, accept evidence,
close tasks, or authorize Git operations.

## Stored Inputs

- Team, task, attempt, role, and workspace identity.
- Handoff source path and content digest.
- RolePolicy identity and digest.
- AgentSpec reference, initially nullable and populated by Phase 3.
- Guidance files and bundle digest.
- Curated backend/model/profile definition digests and runtime version.
- Explicit requested/effective reasoning mapping, support status, and verbosity.
- Effective sandbox, write roots, MCP permissions, and bound MCP project.
- Existing current gate route and execution surface.

## Verification Summary

The final current Phase 0-2 gate passed with the environment-dependent `rg` test
excluded. Independent review found and verified fixes for tamper races,
failure-atomic rollback, reasoning continuity, handoff-byte identity, and corrupt
spec observability.

## Original Plan Summary

1. Resolve current current configuration in `prepare_request`.
2. Build and display a strict in-memory execution specification.
3. Write it once before the draft worker starts.
4. Store only its reference in mutable session state.
5. Verify it on feedback/final without changing current lifecycle authority.

## Deferred Work

AgentSpec selection and effective-policy intersection were implemented in Phase
3. Curated reasoning control was implemented in Phase 4, and backend adapter
extraction was implemented in Phase 5.
