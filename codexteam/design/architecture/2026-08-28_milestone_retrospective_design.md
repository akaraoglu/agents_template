# Milestone Retrospective Design

## Scope

This design records the implemented post-milestone retrospective contract in
`src/codexteam_tools/milestone_retrospective.py`. It covers evidence binding,
deterministic qualification, optional local advisory analysis, persisted
artifacts, proposal disposition, authority, and recovery.

## Design

The retrospective is a bounded operation over one named milestone boundary and
an ordered set of completed task IDs. It supports a same-root project through a
Git Steward commit record, or one registered split-root repository through an
exact repository binding and full commit object ID. It does not migrate old
evidence, infer task membership, create tasks, implement proposals, or perform
remote operations.

Evidence is accepted only when each task ledger row is `Completed`, its one
result record resolves to the matching runtime attempt and role, and that
attempt has exactly one accepted Integration Gate snapshot. The snapshot record
digest, filename, task, attempt, gate, project root, and repository binding are
validated. The milestone commit must carry exact boundary, ordered-task, and
verification trailers. Its Integration Gate verification workspace digest must
match an accepted snapshot from an included task. Same-root operation also
binds the Git Steward record and committed verification bytes to current Git.

Signal qualification is deterministic. Sanitized runtime metrics, structured
result findings, accepted gates, lead usage, commit identity, and source digests
are persisted as evidence; private output tails and command text are excluded.
Qualified signals always produce strict embedded improvement proposals in
`Proposed` state. An applied round also appends those proposals to the project
backlog. The optional model pass is advisory only: one schema-constrained,
tool-free request to a curated local Ollama profile. It cannot alter signal
qualification, proposal creation, or authority.

Proposal IDs include a 64-bit hash of the exact boundary identifier, preventing
normalization collisions while remaining stable across preview and apply.

## Contracts And State

`analysis.json` conforms to `schemas/milestone-retrospective.json` and contains
exactly `schema_version`, `boundary_id`, `evidence_digest`, `disposition`,
`signals`, `proposals`, and `advisory_model`. A successful round persists one of
two dispositions: `NO_CHANGE` exactly when proposals are empty, otherwise
`PROPOSALS_RECORDED`. Embedded proposals conform to
`schemas/improvement-proposal.json` and always declare that they create no task
and grant no implementation authority.

`BLOCKED_INSUFFICIENT_EVIDENCE` is a transient response envelope, not a third
persisted analysis disposition. It reports one bounded blocking reason with
no new retrospective by default. If artifact publication succeeded before a
backlog write interruption, the response truthfully reports the partial
mutation and artifact root so the same boundary can recover it.

Only `decide` writes a separate immutable record conforming to
`schemas/improvement-disposition.json`. Applying any approve, reject, or defer
decision requires explicit `--human-approved`. Approval scope is
`planning-only`; every decision records `creates_task: false` and
`grants_implementation_authority: false`, and the record binds the exact
proposal content by SHA-256.

## Atomicity And Recovery

Mutation is serialized by a nonblocking project file lock. Analysis validates
the backlog before publication, writes a complete temporary artifact tree, and
atomically renames it into place. A repeated unchanged round validates and
reuses existing evidence, analysis, report, and proposal blocks. Any changed or
unsafe state blocks instead of overwriting evidence.

Disposition recovery intentionally writes the immutable decision first. An
identical rerun can detect that record and complete a missing backlog update;
conflicting disposition or backlog content fails closed. These rules make
normal reruns idempotent and interruption recovery explicit without retries or
rollback machinery.

## Verification Sources

- Strict validators and output construction:
  `src/codexteam_tools/milestone_retrospective.py`
- Behavioral, authority, identity, advisory, and recovery tests:
  `tests/test_milestone_retrospective.py`
- Contract registry and schema presence checks: `tests/test_contracts.py`
- Documentation and generated-project checks: `tests/test_docs.py` and
  `tests/test_project_init.py`
