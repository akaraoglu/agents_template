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

## Tooling

### P0 - Hardened test-gate execution

- Run each configured gate command in a dedicated process group and terminate
  descendants on timeout so test servers and browser processes cannot survive a
  failed gate.
- Define and document a minimal environment inheritance policy, including
  credentials, proxies, network access, and project-required variables.
- Keep command arrays shell-free and add bounded output capture without losing
  the diagnostic tails required for evidence.

### P1 - External MCP capability inspector

- Extend the existing inspection workflow to report registered server identity,
  enabled state, advertised tools, configured role subsets, and readiness.
- Keep local metadata inspection as the default; require an explicit live probe
  and never expose credentials or authentication values.
- Use it to detect host catalog drift and unavailable optional interfaces such
  as Playwright before a worker starts.

### P1 - Controlled visual evidence capture

- Evaluate a deterministic host-side CLI or test-gate workflow for fixed desktop
  and mobile viewport captures, local URLs, and accessibility-tree evidence.
- Keep navigation and capture bounded; do not grant arbitrary page interaction,
  uploads, evaluation, or remote browsing.
- Let UX Designers inspect named artifacts and Test Engineers verify behavior;
  screenshots remain supporting evidence rather than automatic acceptance.

### P1 - Local documentation source adapters

- Extend the existing `local-docs` index with adapters only for recurring
  installed stacks, such as Node packages, Go packages, Rust crates, local man
  pages, OpenAPI specifications, and project-approved framework documentation.
- Preserve the existing list, search, and read MCP tools rather than adding a
  server or tool for each ecosystem.
- Require offline, deterministic collection, source versions, content digests,
  bounded sections, and representative negative tests.

### P2 - Project-local source navigation

Adopt source navigation progressively per project rather than introducing a
global code graph or always-running language service.

1. **Default - Handoff targets and ripgrep.** Keep exact source and test targets
   in task handoffs and use the existing bounded `search_repository` text search.
   This remains the default for small and medium projects.
2. **Indexed - Project-local Ctags.** Evaluate a deterministic Universal Ctags
   index for symbol and definition lookup when text search causes repeated broad
   discovery. Store tags and provenance in ignored project runtime state, rebuild
   explicitly, expose bounded results through `search_repository`, and keep
   ripgrep as the fresh-reference fallback.
3. **Advanced - Language-native semantic tools.** Add project-specific LSP,
   compiler, or semantic-index commands only when definitions, references,
   implementations, call sites, or refactoring accuracy require them. Do not add
   a permanent global LSP catalog or one MCP server per language.

- For indexed and advanced levels, record project identity, tool/version, source
  Git state, dirty status, generation time, supported languages, and visible
  stale or partial status.
- Measure precision, missed dependencies, query and indexing time, response
  bytes, model tool calls, input tokens, correction rounds, and integration
  defects before promotion.

### P2 - Browser readiness canary

- Add a deterministic preflight for browser-dependent projects that checks the
  pinned browser version, server identity, allowed tool subset, local-page
  navigation, and cleanup.
- Keep the canary Lead/operator initiated and expose browser tools to the Test
  Engineer only after readiness succeeds.

### Project-specific development gates

Adopt these through project Development or Integration Gate command arrays when
the stack and acceptance criteria require them, rather than exposing them as
permanent CodexTeam MCP tools:

- Python: Ruff, Pyright or mypy, pytest, coverage, Bandit, and `pip-audit`.
- JavaScript and TypeScript: ESLint, TypeScript, Vitest or Jest, Playwright, axe,
  and `npm audit`.
- Go: `go test`, `go vet`, Staticcheck, and `govulncheck`.
- Rust: rustfmt, Clippy, Cargo tests, and `cargo audit`.
- C and C++: CMake/CTest, Clang-Tidy, sanitizers, and cppcheck.
- Cross-stack: Semgrep, Gitleaks, license-policy checks, API/schema compatibility,
  migration validation, mutation testing, complexity checks, deterministic
  benchmarks, and bounded load tests.

### Permanent tool admission criteria

A permanent CodexTeam tool must:

1. Address a recurring, evidence-backed problem.
2. Have one clear purpose that does not overlap an existing tool.
3. Return bounded, structured, source-backed output.
4. Support explicit role and phase restrictions.
5. Have safe defaults, useful errors, and deterministic cleanup.
6. Demonstrate a correctness, safety, time, token, or reliability improvement.
7. Be preferable to extending an existing CLI, test gate, documentation adapter,
   or MCP tool.

## Deliberate Exclusions

- Do not replace all completed tool results with generic acknowledgements;
  retain decision-bearing evidence needed for debugging and verification.
- Do not add an append-only generic `NOTES.md`; prefer canonical project state,
  task handoffs, results, decisions, and architecture notes.
- Do not enable nested worker execution or add more sub-agent layers.
- Do not use lossy model-generated worker-history summaries until checkpoint
  fidelity, evidence preservation, and rollback are independently validated.
- Do not add a general-purpose shell or code-execution MCP server.
- Do not add writable GitHub tools, remote lifecycle mutation, or a writable
  dashboard controller under the current authority model.
- Do not add one MCP server per language tool, an always-loaded LSP catalog, or
  a generic vector-memory service without measured recurring need.
- Do not add automatic retries, model switching, ownership transfer, or task
  splitting that bypasses Project Lead review and preserved evidence.
