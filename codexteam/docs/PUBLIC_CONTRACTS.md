# Public Contracts

CodexTeam has one contract set. Contract IDs and filenames are unversioned;
every record retains `schema_version` for future compatible evolution.
The registered Python validator is normative for cross-field invariants,
canonical identifier and timestamp forms, and exact integer representation that
JSON Schema cannot fully express.

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
| Milestone retrospective v1 | `schemas/milestone-retrospective.json` | Historical evidence-backed analysis; immutable and readable |
| Milestone retrospective v2 | Strict preparation record plus `schemas/milestone-retrospective-evaluation.json` | Staged evidence, tool-free Reviewer-derived judgment, and deterministic acceptance |
| Evaluator report | `schemas/milestone-retrospective-evaluation.json` | Prepared-packet-bound tool-free judgment; no task or implementation authority |
| Improvement proposal | `schemas/improvement-proposal.json` | Validated E3 backlog candidate initially recorded as `Proposed` |
| Improvement disposition | `schemas/improvement-disposition.json` | Immutable explicit human decision with no implementation authority |

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

New rounds use `prepare -> evaluate -> accept -> human decide`. Preparation is
content-addressed, makes no model call, and does not touch the backlog. The
Reviewer-derived `agent-evaluator` identity and guidance run in one dedicated,
schema-constrained local Ollama request over the prepared packet. It has no
tools, filesystem, MCP, cloud profile, retries, worker task, session, or other
project context; deterministic caller code alone may persist its report.
Deterministic acceptance validates the AgentSpec identity and digest plus all
report and evidence digests. The evaluator cannot raise evidence ceilings,
invent evidence, write backlog state, create tasks, or approve work.

An observation is not a cause. E1 permits observation, E2 permits
investigation, and only E3 permits a proposal with a concrete target and
mechanism, alternatives, falsifiable validation, and rollback. `NO_CHANGE` may
therefore retain observations and investigations. Applied acceptance adds only
validated E3 proposals to the backlog as `Proposed`. Presentation keeps impact,
change risk, change amount, reversibility, confidence, and action band
categorical; it may say `No candidate recommended this round`.

Only an explicit human `milestone-retrospective.py decide` command may
transition a proposal to `Approved`, `Rejected`, or `Deferred`, and applying any
decision requires `--human-approved`. Approval is for normal planning only: it
does not create a task, execute work, change guidance or contracts, or grant
implementation authority. Historical v1 analyses and dispositions remain
immutable and readable, without reclassification or backfill. See
`MILESTONE_RETROSPECTIVE.md`.
