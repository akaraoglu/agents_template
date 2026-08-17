# Phase 4: Curated Execution Routing and Clean Cutover

## Status

Implemented as a clean execution-contract cutover.

## Completed Work

- Added `execution_registry.toml` as the authoritative curated inventory.
- Defined only `codex` and `opencode` as backends.
- Added backend-scoped profile identities, model definitions, reasoning mappings,
  and qualification records.
- Added read-only `inspect-execution-catalog.py` queries for support and host
  availability.
- Draft requires explicit backend, profile, and reasoning.
- Feedback/final reject those selectors and load the pinned ExecutionSpec.
- Removed profile/reasoning defaults from RolePolicy and OpenCode alias authority.
- Rejected arbitrary installed Codex profiles and unsupported reasoning.
- Moved immutable runtime selection solely into the registry-backed ExecutionSpec.
- Reduced session state to mutable lifecycle progression and references.

## Cutover Policy

Pre-cutover active attempts must finish before deployment or be abandoned. No
legacy readers, dual writing, shape detection, backfill, or permanent feature
flag are provided. Existing project Markdown and accepted `result-current` records
remain valid history.

## Initial Profiles

- `codex/qwen36-27b`
- `codex/gpt54-mini`
- `opencode/qwen36-27b`
- `opencode/muse-glimmer`
- `opencode/ornith35b`

Installation alone does not imply support. Launchable profiles require curated
definitions, backend implementation, documentation, and qualification evidence.
