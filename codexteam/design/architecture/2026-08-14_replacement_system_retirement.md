# Replacement System Retirement

## Status

Completed. CodexTeam now has one project execution system and one unversioned
contract namespace. Git history is the archive for the discarded replacement
implementation.

## Retained System

- Project Lead draft, feedback, final, gate, review, close-loop, and Git Steward lifecycle.
- Codex and OpenCode backend adapters.
- Curated execution registry and immutable ExecutionSpec.
- Optional curated AgentSpecs.
- Existing `codexteam-context`, `local-docs`, and bounded local MCP sidecar.
- Strict task write scope, context provenance, and turn telemetry.

## Removed

- Replacement pipeline/runtime, schemas, catalogs, tests, fixtures, scripts, and documentation.
- Version router and execution-version environment selection.
- Generation labels in active contract IDs, schema filenames, runtime sidecars, and guidance.

Existing accepted project records remain historical data; new attempts use the
single current contract set.
