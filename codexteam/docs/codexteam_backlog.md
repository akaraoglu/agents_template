# CodexTeam Backlog

## Context Engineering

### P0 - Compact execution capsule

- Inject only task-applicable rules, exact context targets, gate routing, write
  scope, and the output contract for ordinary worker turns.
- Keep complete pinned guidance snapshots for audit, continuation, and explicit
  exceptional retrieval without requiring workers to read every file.
- Validate against the matched scheduler benchmark while preserving correctness,
  scope control, and the draft-feedback-final lifecycle.
- Evidence: `design/architecture/2026-08-14_opencode_token_and_latency_findings.md`.

### P0 - Explicit OpenCode tool allowlist

- Replace the normal worker wildcard permission with the smallest practical
  role-aware set of read, search, edit, and command tools.
- Deny task-management tools such as `todowrite` unless a measured workflow
  demonstrates a need.
- Preserve the existing read-only finalizer restrictions and test representative
  and negative role workflows.

### P1 - Context-pressure telemetry

- Surface existing prompt and context measurements in bounded attempt summaries
  and cost hotspots.
- Include prompt bytes, available guidance bytes, MCP response bytes, accepted
  checkpoint bytes, first/last/max step input tokens, and context growth relative
  to the selected model limit when available.
- Establish warning thresholds from observed runs before introducing automatic
  session behavior.

### P1 - Canonical project-memory retrieval

- Expand bounded, ranked project-memory search across `DECISIONS.md`,
  `OPEN_QUESTIONS.md`, `ARCHITECTURE.md`, `docs/decisions/*.md`, and
  `design/architecture/*.md`.
- Return bounded excerpts with source path and line, content digest, decision
  status when available, date or recency, and visible truncation.
- Define lifecycle rules: accepted decisions belong in `DECISIONS.md` or an ADR,
  unresolved questions in `OPEN_QUESTIONS.md`, temporary observations in task or
  result records, and superseded decisions remain visibly marked. Never promote
  runtime transcripts into memory automatically.
- Keep retrieval just in time. Give workers exact handoff facts first and query
  project memory only for a concrete missing decision; return source references
  rather than injecting the complete memory corpus.
- Evaluate a concise generated memory index that maps topics to canonical
  headings and paths. Derive it from canonical documents and never treat it as
  an independent source of truth.
- Preserve strict project binding and prevent cross-project memory leakage.

### P1 - Smaller MCP payload ceilings

- Add a serialized response ceiling for context MCP results and reduce the
  startup task-context allowance from its current broad limit.
- Return concise structured fields and exact source references rather than large
  embedded artifacts.
- Keep truncation, source size, returned size, and source digests observable.

### P2 - Worker context checkpoint and rotation experiment

- After context-pressure telemetry establishes a real threshold, evaluate an
  explicit worker rotation path for long correction chains.
- Use a digest-bound checkpoint containing accepted state, unresolved feedback,
  changed paths, evidence references, and the immutable ExecutionSpec reference.
- Treat rotation as an intentional lifecycle transition, not silent automatic
  summarization, and preserve logical attempt identity only if the contract can
  prove continuity safely.

## Deliberate Exclusions

- Do not replace all completed tool results with generic acknowledgements;
  retain decision-bearing evidence needed for debugging and verification.
- Do not add an append-only generic `NOTES.md`; prefer canonical project state,
  task handoffs, results, decisions, and architecture notes.
- Do not enable nested worker execution or add more sub-agent layers.
- Do not use lossy model-generated worker-history summaries until checkpoint
  fidelity, evidence preservation, and rollback are independently validated.
