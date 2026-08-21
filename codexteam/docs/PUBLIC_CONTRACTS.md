# Public Contracts

CodexTeam has one contract set. Contract IDs and filenames are unversioned;
every record retains `schema_version` for future compatible evolution.

| Contract | Schema | Authority |
|---|---|---|
| Handoff | `schemas/handoff.json` | Task objective, context, constraints, and acceptance |
| Execution specification | `schemas/execution-spec.json` | Immutable backend, profile, reasoning, guidance, permissions, and routing |
| AgentSpec | `schemas/agent-spec.json` | Optional specialization that can only narrow RolePolicy |
| Artifact report | Python validator | Review material; never closure authority |
| Result | `schemas/result.json` | Final worker report for one attempt |
| Session | `schemas/session.json` | Strict mutable continuation and lifecycle state |
| Role policy | `schemas/role-policy.json` | Role responsibility and permission ceiling |
| Gate record | `schemas/gate-record.json` | Development or Integration Gate observation |
| Commit plan/authorization/record | `schemas/commit-*.json` | Explicit local milestone commit workflow |

The handoff references `execution-spec.json`; it does not independently select a
backend, model, profile, reasoning effort, or AgentSpec. Session stores only the
execution-specification reference plus mutable continuation data. Unknown Session
fields fail closed.

All attempts use `artifact-report-v1`. The launcher derives
`results/reports/<TASK>-<attempt>.json`; the worker supplies only `version: 1`,
non-empty `summary`, evidence path strings, and limitation strings. Unknown
fields are ignored. Finalization seals identity, status, change manifest,
process metadata, and timestamps without a provider call.

Canonical `Context Mode: direct` tasks use an artifact-owned outcome instead of
worker terminal JSON. They declare one `Result Report`, one to five bounded
`Direct Context` line ranges, and fixed JSON-argv `Verification Commands`.
The launcher validates and injects those excerpts, denies worker read/search/bash
tools, permits only literal role-allowed edit paths, runs configured-gate checks
inside a networkless read-only bubblewrap boundary after the provider exits, and constructs
semantic evidence from the report plus deterministic records. Terminal model
text is not an acceptance contract in direct mode.

A timeout or opt-in Run Guard interruption preserves a captured thread for
same-attempt feedback. It does not create another lifecycle or contract format.
