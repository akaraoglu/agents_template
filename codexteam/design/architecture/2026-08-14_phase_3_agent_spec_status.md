# Phase 3: AgentSpec Specialization Overlays

## Status

Implemented. Project Leads can select one curated technical specialization for
a new attempt without creating a new lifecycle role or changing its execution
profile.

## Shared Model

```text
Protocol Role       = lifecycle responsibility and authority ceiling
AgentSpec           = technical specialization and permission narrowing
Execution Profile   = backend, model, reasoning, and runtime settings
Task Handoff        = exact task objective, context, paths, and acceptance
Execution Spec      = immutable resolved combination for one attempt
```

## Completed Work

- Added strict `agent-spec` schema and loader.
- AgentSpecs are optional; omission keeps `agent_spec: null`.
- Added initial specialists:
  - `python-developer`
  - `go-developer`
  - `frontend-developer`
  - `cpp-developer`
  - `cpp-embedded-developer`
  - `security-reviewer`
  - `accessibility-reviewer`
- Added catalog-owned reusable specialist guidance.
- Added draft-only `--agent-spec`; omission uses the ordinary role.
- Feedback and finalization reject AgentSpec overrides and reuse the pinned
  snapshot.
- Historical pre-cutover attempts are not resumed or backfilled.
- Pinned the complete AgentSpec snapshot, reference, specialist guidance, and
  effective-policy digest.
- Kept canonical `roles/*.toml` as the responsibility and authority ceiling.
- Enforced permission intersection for paths, denials, MCP servers/tools, and
  evidence types.
- Preserved base MCP restrictions for retained servers when another server is
  narrowed.
- Updated status output and handoff templates to show Role, AgentSpec, and
  Execution Profile separately.
- Added `docs/AGENT_SPECS.md`.

## Effective Policy Rules

```text
effective permission
  = RolePolicy ceiling
  intersection AgentSpec overlay
  intersection available task scope
  intersection workspace boundary
```

- Role denials always win.
- AgentSpec denials add restrictions.
- AgentSpec allowed paths cannot broaden the RolePolicy.
- MCP servers and tools are intersected.
- Evidence types are intersected.
- Base-role guidance precedes AgentSpec guidance.
- AgentSpecs cannot select models, backends, reasoning, tasks, stages, gates,
  project state, closure, or Git authority.

## Compatibility

- Omitted AgentSpec returns the exact base RolePolicy behavior.
- Existing projects require no migration.
- AgentSpec and execution profile selection remain independent.
- Capability transfer or another AgentSpec requires a new attempt.
- No automatic specialist routing or arbitrary capability stacking is present.
- Draft, feedback, final, result, gate, and close-loop authority is unchanged.

## Verification Summary

Current repository verification passes with the environment-dependent `rg` test
skipped when unavailable. Independent review found and verified fixes for MCP
tool broadening and valid path-narrowing semantics.

## Original Plan Summary

1. Define a strict role-bound specialization contract.
2. Prove omission preserves ordinary RolePolicy behavior.
3. Add explicit Lead selection and immutable attempt pinning.
4. Intersect, never broaden, the RolePolicy ceiling.
5. Append and pin specialist guidance.
6. Roll out a small curated pilot set before adding more specifications.

## Deferred Work

- Automatic specialist selection.
- Multiple AgentSpecs or arbitrary capability stacking.

Task-handoff write-scope enforcement, model/reasoning controls, and backend
adapter extraction were completed in subsequent phases and are no longer
deferred.
