# CodexTeam Architecture Readiness Review

## Status

Phase 0 architecture hardening is accepted. Phase 1 implementation is limited to core primitives.

This review remains as the architecture reference that led to the accepted decisions in `../DECISIONS.md` and delivery sequence in `../IMPLEMENTATION_PLAN.md`.

## Verification Findings

- `codexteam/` contains the SDD package and initial folders for `agents/`, `docs/`, `scripts/`, `src/`, `templates/`, and `tests/`.
- `/home/alik/workspace/codexspace` exists and is currently empty.
- Ollama has `gemma4:12b`, `gemma4-26b:latest`, and `gemma4:26b` installed.
- `gemma4:12b` supports tools and thinking and succeeded through `codex exec --oss --local-provider ollama`.
- A Codex app-server JSON-RPC probe also succeeded with `gemma4:12b`.
- `codex exec --profile gemma4-26b` now succeeds through the standalone `~/.codex/gemma4-26b.config.toml` profile.
- That profile now points `model_catalog_json` at `~/.codex/model_catalogs/local-models.json` instead of a repository path.
- `codex exec --oss --local-provider ollama -m gemma4-26b` failed because Codex tried to pull the untagged model name.
- `codex exec --oss --local-provider ollama -m gemma4-26b:latest` succeeded for a non-editing smoke test.
- The successful smoke test logged a non-fatal model-list refresh error against Ollama's model listing response, so MVP should use exact model tags and not depend on model auto-discovery.

## Core Architecture Recommendation

CodexTeam should be a local Python orchestrator with explicit ports/adapters.

The durable core should not be MCP, HTTP, or a Codex app-server client. Those are integration surfaces. The core should own state, policy, task lifecycle, messages, workspace boundaries, approvals, audit, and board data. Interfaces can call the core later.

Recommended center:

- `controller`: validates operations, calls policy, updates state, writes audit events.
- `state_store`: atomic JSON state plus append-only JSONL audit under `/home/alik/workspace/codexspace`.
- `policy_engine`: deny-by-default checks for paths, process launches, network, secrets, hidden files, merge, cleanup, and destructive actions.
- `task_engine`: team, task, plan, dependency, evidence, and review lifecycle.
- `messaging_engine`: immutable local messages between leader, workers, and system actors.
- `workspace_manager`: isolated per-team and per-task workspaces under `/home/alik/workspace/codexspace`.
- `adapter_manager`: dry-run, manual, and local Codex/Ollama adapters behind policy.
- `board`: read-only projection of current state, blockers, approvals, risk, and review queue.
- `review_manager`: summarizes evidence and requires human approval before merge or cleanup.

## Accepted Architecture Decisions

### AD-C001 - Core-first, adapter-driven design

- Decision: implement CodexTeam as a pure local core plus adapters.
- Rationale: MCP, HTTP, and app-server interfaces should not leak into core domain rules.
- MVP impact: core can be tested without running agents or servers.

### AD-C002 - Terminal board first

- Decision: MVP board is terminal-first.
- Rationale: the first operator problem is trust and observability, not rich UI.
- MVP impact: implement board as deterministic text output from state snapshots.

### AD-C003 - Defer HTTP UI

- Decision: no HTTP server in MVP.
- Rationale: local HTTP adds process, auth, CSRF/origin, port, and lifecycle concerns before the core is proven.
- Later path: add a loopback-only read-only HTTP status server after the terminal board works.

### AD-C004 - Defer MCP server

- Decision: do not build CodexTeam itself as an MCP server for MVP.
- Rationale: MCP is valuable when other agents or tools need to call CodexTeam, but the core is not a tool protocol.
- Later path: expose a narrow MCP adapter around stable core operations such as create team, read board, submit approval, and fetch evidence.

### AD-C005 - Use exact local Ollama model tags

- Decision: worker launch policy must use exact local model tags.
- Rationale: untagged `gemma4-26b` attempted a pull and failed, while exact model tags worked.
- MVP impact: model availability checks must compare exact tags from `ollama list`.

### AD-C006 - Use `gemma4:12b` for development and tests

- Decision: use `gemma4:12b` for development, tests, smoke checks, and early local worker validation.
- Rationale: it is installed, supports tools/thinking, and works through Codex while being faster than 26B-class models.
- MVP impact: `gemma4-26b:latest` is deferred for later quality improvements.

### AD-C007 - Dry-run before real workers

- Decision: keep the first thin slice dry-run only.
- Rationale: this proves state, audit, approvals, board, and policy without process execution risk.
- MVP impact: real Codex/Ollama workers start only after policy and workspace boundaries have negative tests.

### AD-C008 - Worker adapter first

- Decision: implement the first local worker path through structured `codex exec --json` invocations.
- Rationale: it is simpler and easier to audit than starting with app-server or MCP server lifecycle.
- MVP impact: Codex app-server and MCP are later adapters behind the same core interface.

### AD-C009 - Repository-local helper scripts

- Decision: create small scripts under `codexteam/scripts/` for local model smoke tests, structured local Codex runs, and app-server probing.
- Rationale: scripts give future agents stable tools and avoid fragile command lines.
- MVP impact: scripts must use standard library Python unless the human user approves dependencies.

## Proposed Runtime Layout

Phase 0 should decide and document a layout close to this:

```text
/home/alik/workspace/codexspace/
  state/
  audit/
  logs/
  workspaces/
  messages/
  approvals/
  tmp/
```

The implementation should treat this as runtime state. Nothing here should be committed.

## Recommended Local Worker Shape

The real adapter should not start until Phase 9, but the command shape should be decided in Phase 0.

Proposed safe baseline:

```bash
codex exec --oss --local-provider ollama -m gemma4:12b \
  --sandbox workspace-write \
  --ephemeral \
  --json \
  -C <assigned-task-workspace> \
  -c approval_policy="never" \
  "<bounded task prompt>"
```

The adapter must construct this command from structured arguments, never from raw agent text.

## Phase 0 Decision Work

Before implementation, Phase 0 should resolve:

1. Confirm core-first architecture.
2. Confirm terminal board first and no HTTP server for MVP.
3. Confirm MCP as later adapter, not MVP core.
4. Confirm runtime layout under `/home/alik/workspace/codexspace`.
5. Pin `gemma4:12b` and smoke-test command.
6. Define local helper script/tool contracts.
7. Define worker workspace strategy.
8. Define approval schema.
9. Define security policy profile and negative test matrix.
10. Define Phase 1 entry gate.
