# CodexTeam Backlog

## Priority Summary

Backlog priority considers four kinds of gain separately:

- **Production safety:** prevents leaked processes, credentials, stale evidence,
  or unreliable execution across every project.
- **Large-project quality:** helps workers preserve accepted architecture and
  decisions across long-lived, multi-component work.
- **Product verification:** improves repeatable evidence for a specific product
  class such as browser interfaces.
- **Observability and efficiency:** measures or reduces context, latency, and
  operational uncertainty without directly changing product correctness.

Current recommended order:

1. Harden test-gate process and environment handling.
2. Add simple canonical project-memory retrieval for long-lived projects.
3. Standardize controlled visual evidence capture for UI projects.
4. Add browser readiness checks as the preflight for that capture workflow.
5. Improve MCP inspection and context telemetry when they answer an observed
   diagnostic need.
6. Add ecosystem documentation adapters or source indexes only after a recurring
   project-specific need is demonstrated.

Completed and superseded work remains visible below so future planning does not
repeat it.

## Context Engineering

### Deferred - Compact execution capsule

**Status:** Existing context controls are sufficient; further compaction is not
currently justified.

**Gain:** Low or uncertain efficiency gain.

**Risk:** Moderate correctness and maintenance risk because prompt projection
would gain ordinary-versus-special branching and might omit role, testing, or
evidence rules needed by uncommon tasks.

- Inject only task-applicable rules, exact context targets, gate routing, write
  scope, and the output contract for ordinary worker turns.
- Keep complete pinned guidance snapshots for audit, continuation, and explicit
  exceptional retrieval without requiring workers to read every file.
- Validate against the matched scheduler benchmark while preserving correctness,
  scope control, and the draft-feedback-final lifecycle.
- Evidence: `design/architecture/2026-08-14_opencode_token_and_latency_findings.md`.
- Already implemented: canonical task handoffs, exact context targets, task write
  scope, delta-only feedback, artifact reports, provider-free finalization, and
  full pinned guidance for continuation and audit.
- Current Codex behavior loads the substantial fixed guidance mainly once on the
  draft. Feedback is already a small correction delta, and finalization invokes
  no model. The remaining fixed guidance is small relative to qualified model
  context and may improve behavioral consistency.
- Retain one low-risk consistency fix as separate maintenance work: when full
  guidance is projected, build the first model prompt from the pinned guidance
  snapshot rather than the mutable source file.
- Reopen compaction only when matched Codex runs show fixed initial guidance is
  materially responsible for latency, context exhaustion, excessive uncached
  tokens, or correction failures.
- Promotion would require equivalent correctness and scope cleanliness, no
  increase in correction turns, at least 50% smaller launcher-generated draft
  text, and at least 30% lower median uncached input tokens across representative
  ordinary tasks.

### Closed - Explicit OpenCode tool allowlist

**Status:** Superseded. OpenCode draft and feedback execution are disabled while
its implementation and historical records remain available.

**Gain:** No current gain while execution remains disabled.

- Replace the normal worker wildcard permission with the smallest practical
  role-aware set of read, search, edit, and command tools.
- Deny task-management tools such as `todowrite` unless a measured workflow
  demonstrates a need.
- Preserve the existing read-only finalizer restrictions and test representative
  and negative role workflows.
- Reopen only if OpenCode execution is intentionally restored behind an
  enforceable OS sandbox. A tool allowlist alone is not host containment.

### P1 - Context-pressure telemetry

**Status:** Partially completed.

**Gain:** Medium observability gain; low direct product gain.

**Risk:** Low if telemetry remains bounded and does not drive automatic lifecycle
behavior.

- Surface existing prompt and context measurements in bounded attempt summaries
  and cost hotspots.
- Include prompt bytes, available guidance bytes, MCP response bytes, accepted
  checkpoint bytes, first/last/max step input tokens, and context growth relative
  to the selected model limit when available.
- Establish warning thresholds from observed runs before introducing automatic
  session behavior.
- Already implemented: worker prompt bytes, guidance snapshot bytes, tool/output
  observations, token usage, and model-step measurements where the backend
  exposes them.
- Remaining work is to account clearly for model-visible context not represented
  by current prompt bytes, including role instructions, discovered `AGENTS.md`,
  enabled tool schemas, and persistent history.
- Add thresholds only after enough real Codex runs establish useful distributions.
  Do not turn a warning into automatic rotation, retry, or model switching.

### P1 - Canonical project-memory retrieval

**Status:** Open; second-highest overall priority.

**Gain:** High large-project quality gain. It reduces repeated discovery and
contradictions with accepted architecture, especially in long-lived programs
such as Bubo.

**Risk:** Moderate. Ranking or stale-state errors could surface the wrong
decision, so canonical source references must remain authoritative.

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
- Start with deterministic ranked text and heading search, not embeddings or a
  vector service.
- Search only canonical memory sources and return concise excerpts with exact
  file/line references and digests.
- Require explicit visible status for accepted, unresolved, and superseded
  decisions. Never infer durable memory from worker transcripts.
- Acceptance requires project isolation tests, bounded output, stale-index
  detection, representative conflicting/superseded decisions, and evidence that
  workers consult memory only for a concrete missing fact.

### P1 - Live Codex subagent progress streaming

**Status:** Open; execution uses the curated local `qwen38-27b` profile.

**Gain:** High operational visibility for long Codex turns and faster detection
of stalled workers, without changing the private evidence model.

**Risk:** Moderate. Live output must remain bounded and redacted; private
prompts, secrets, and unbounded command output must not reach the terminal.

- Reuse the existing Codex `--json` stdout stream and Python queue; do not add a
  shell wrapper, command substitution, `tee`, `jq`, or App Server dependency.
- Make `activity` the default Codex debug stream while preserving explicit
  `off` and `assistant` behavior.
- Render safe bounded thread/turn lifecycle, commands, file changes, tool/MCP
  activity, agent messages, reasoning summaries, command status/output metadata,
  and errors as events arrive.
- Keep raw JSONL private and authoritative; redact credentials, prompts, secrets,
  and sensitive arguments. Do not claim or expose private chain-of-thought.
- Preserve timeout, process-group cleanup, result parsing, role restrictions,
  and existing OpenCode behavior.
- Acceptance requires delayed fake-Codex JSONL tests proving immediate output,
  ordering, flush behavior, `off` silence, redaction, bounds, malformed-event
  handling, timeout cleanup, and unchanged persisted evidence.
- Execution uses only the curated, host-available profile reported by
  `inspect-execution-catalog.py`; current selection is `qwen38-27b`.

### Deferred - Smaller MCP payload ceilings

**Status:** Partially completed; current responses are already bounded and
observable.

**Gain:** Low-to-medium context efficiency gain.

**Risk:** Moderate diagnostic loss if useful evidence is truncated too early.

- Add a serialized response ceiling for context MCP results and reduce the
  startup task-context allowance from its current broad limit.
- Return concise structured fields and exact source references rather than large
  embedded artifacts.
- Keep truncation, source size, returned size, and source digests observable.
- Tighten ceilings only after telemetry identifies a recurring oversized tool or
  response shape. Prefer concise fields and source locators before reducing hard
  byte limits.

### Deferred - Worker context checkpoint and rotation experiment

**Status:** Open only as a future experiment; no current need demonstrated.

**Gain:** Potentially high only after actual context exhaustion.

**Risk:** High lifecycle and evidence-continuity risk.

- After context-pressure telemetry establishes a real threshold, evaluate an
  explicit worker rotation path for long correction chains.
- Use a digest-bound checkpoint containing accepted state, unresolved feedback,
  changed paths, evidence references, and the immutable ExecutionSpec reference.
- Treat rotation as an intentional lifecycle transition, not silent automatic
  summarization, and preserve logical attempt identity only if the contract can
  prove continuity safely.
- Persistent feedback sessions currently work and should remain the default.
- Reopen only when telemetry proves long correction chains exceed practical
  context or reliability bounds. Do not rotate proactively to optimize ordinary
  prompt size.

## Tooling

### P0 - Hardened test-gate execution

**Status:** Open; highest overall priority.

**Gain:** Very high production-safety and evidence-integrity gain across every
project.

**Risk:** Low-to-moderate. Process-group and environment changes can break valid
project gates, so compatibility tests and clear opt-in environment variables are
required.

- Run each configured gate command in a dedicated process group and terminate
  descendants on timeout so test servers and browser processes cannot survive a
  failed gate.
- Define and document a minimal environment inheritance policy, including
  credentials, proxies, network access, and project-required variables.
- Keep command arrays shell-free and add bounded output capture without losing
  the diagnostic tails required for evidence.
- This addresses observed classes of failure: surviving browser/test servers,
  occupied ports, descendant processes after timeouts, and credentials or proxy
  settings reaching test commands unintentionally.
- Run each command in a dedicated process group, terminate and reap the complete
  group on timeout or interruption, and verify cleanup before starting the next
  command.
- Build the gate environment from a documented minimal allowlist plus explicit
  project-configured variables. Do not inherit arbitrary secrets, SSH agent
  sockets, database URLs, or cloud credentials by default.
- Preserve project-required PATH, locale, certificate, and explicitly approved
  tool variables. Report missing requirements as infrastructure failures rather
  than weakening the policy.
- Acceptance requires descendant cleanup tests, timeout tests, environment
  leakage negatives, legitimate environment positives, bounded output evidence,
  and unchanged Development-before-Integration ordering.

### P1 - External MCP capability inspector

**Status:** Partially completed.

**Gain:** Medium operational-reliability gain when optional MCP interfaces are
used; lower priority while Codex can operate without them.

**Risk:** Low for metadata inspection; moderate for live probes that may contact
external services.

- Extend the existing inspection workflow to report registered server identity,
  enabled state, advertised tools, configured role subsets, and readiness.
- Keep local metadata inspection as the default; require an explicit live probe
  and never expose credentials or authentication values.
- Use it to detect host catalog drift and unavailable optional interfaces such
  as Playwright before a worker starts.
- Existing execution-profile catalog inspection already reports curated runtime
  availability. Remaining work should focus specifically on MCP server identity,
  advertised tool drift, role subsets, and an explicit non-default live probe.

### P1 - Controlled visual evidence capture

**Status:** Partially completed in EnerGIT; open as a reusable workflow.

**Gain:** High product-verification gain for browser/UI projects.

**Risk:** Low-to-moderate if constrained to local URLs, fixed viewports, named
artifacts, and deterministic cleanup.

- Evaluate a deterministic host-side CLI or test-gate workflow for fixed desktop
  and mobile viewport captures, local URLs, and accessibility-tree evidence.
- Keep navigation and capture bounded; do not grant arbitrary page interaction,
  uploads, evaluation, or remote browsing.
- Let UX Designers inspect named artifacts and Test Engineers verify behavior;
  screenshots remain supporting evidence rather than automatic acceptance.
- Reuse the proven EnerGIT pattern rather than introducing a browser MCP with
  arbitrary interaction authority.
- Standardize fixed desktop/mobile viewports, light/dark states, screenshot and
  accessibility-tree artifact naming, console/runtime error capture, and process
  cleanup.
- Keep it project-gate-driven. Non-UI projects should incur no browser setup or
  tool context.

### P1 - Local documentation source adapters

**Status:** Open conditionally.

**Gain:** Medium, ecosystem-dependent quality gain.

**Risk:** Moderate maintenance and stale-documentation risk.

- Extend the existing `local-docs` index with adapters only for recurring
  installed stacks, such as Node packages, Go packages, Rust crates, local man
  pages, OpenAPI specifications, and project-approved framework documentation.
- Preserve the existing list, search, and read MCP tools rather than adding a
  server or tool for each ecosystem.
- Require offline, deterministic collection, source versions, content digests,
  bounded sections, and representative negative tests.
- Add one adapter only after multiple tasks repeatedly need the same installed
  documentation source. Prefer extending the existing list/search/read contract
  over creating ecosystem-specific tools.

### P2 - Project-local source navigation

**Status:** Default level completed; indexed and semantic levels remain optional
project-specific experiments.

**Gain:** Default text navigation is high-value and low-risk. Ctags or semantic
tools have uncertain gain until broad discovery repeatedly causes defects or
excessive work.

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
- Mark the default exact-target plus bounded repository-search level complete.
- Pilot Universal Ctags in one large component before any platform-wide
  adoption. Language-native semantic tooling should remain a project gate or
  explicit task capability, not a permanently loaded global service.

### P2 - Browser readiness canary

**Status:** Partially completed in project-specific browser gates.

**Gain:** Medium reliability gain for UI projects, mainly by failing before an
expensive browser workflow.

**Risk:** Low when read-only and Lead initiated.

- Add a deterministic preflight for browser-dependent projects that checks the
  pinned browser version, server identity, allowed tool subset, local-page
  navigation, and cleanup.
- Keep the canary Lead/operator initiated and expose browser tools to the Test
  Engineer only after readiness succeeds.
- Implement after controlled visual capture is standardized so the canary checks
  the exact browser, server, viewport, and cleanup contract that later gates use.

### Project-specific development gates

**Status:** Completed as a CodexTeam capability; individual projects still choose
the commands appropriate to their stack and acceptance criteria.

**Gain:** Very high verification quality with low central maintenance because
tools remain project-local command arrays.

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

**Status:** Active policy; retain as the gate for every future tooling proposal.

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
