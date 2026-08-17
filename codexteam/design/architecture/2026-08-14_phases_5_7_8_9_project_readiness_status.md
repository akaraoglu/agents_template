# Phases 5, 7, 8, and 9: Project Readiness

## Status

Implemented for the current launcher. Phase 6 optimization remains intentionally
deferred until project execution is operating end to end.

## Phase 5

- Added one backend adapter protocol for preflight, draft start, feedback
  resume, finalization, event parsing, telemetry collection, and cleanup.
- Added parity implementations for Codex and OpenCode.
- Kept identity, session/result persistence, workspace auditing, lifecycle state,
  and result validation in the current launcher.

## Phase 7

- Kept Codex native `codexteam-context` and `local-docs` behavior unchanged.
- Reused the existing bounded local MCP sidecar for optional, project-bound
  OpenCode task context on canonical task handoffs.
- Added no MCP server, remote MCP support, retry loop, or new authority.
- Optional sidecar failure does not block ordinary execution.

## Phase 8

- Added machine-readable `Task Write Scope` sections to newly initialized
  canonical task handoffs.
- Pinned declared scope in ExecutionSpec and enforced RolePolicy, AgentSpec,
  task scope, and workspace containment together.
- Preserved legacy/ad-hoc handoffs without a scope section.
- Added private per-turn context-pack provenance containing only identities,
  digests, declared targets, MCP counts, durations, bytes, and source digests.

## Phase 9

- Extended the existing turn metrics with requested/effective reasoning,
  terminal reason, process classification, prompt bytes, model/tool activity,
  diagnostic digests, and MCP provenance.
- Metrics and context packs exclude prompt text, MCP queries/responses, event
  content, stderr content, credentials, and tokens.
