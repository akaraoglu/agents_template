# AgenticTeam — Mattermost + OpenClaw Backlog

**Principle:** Minimal working system first, agile improvements after.
**Stack:** OpenClaw · Mattermost · Ollama `gemma4:26b` · Skills · Custom MCP (P3+)

---

## Priority Bands

| Band | Goal | Done when |
|---|---|---|
| **P1** | Neo talks to human via Mattermost | Human gets a reply from @neo |
| **P2** | Full 6-agent team with delegation | Morpheus writes code triggered by human request |
| **P3** | SDD workflow + design gate | SPEC→DESIGN→CODE flow works end to end |
| **P4** | Custom MCP (audit + gate) | Append-only log, gate_design enforced |
| **P5** | Security hardening | Exec approvals, Neo write-deny, path scoping |
| **P6** | Improvements + observability | Backlog items that emerge from real use |

---

## P1 — Neo Online (MVP)

**Goal:** One agent (@neo) responds to a human in Mattermost using `gemma4:26b`.

| ID | Item | Size |
|---|---|---|
| MC-001 | Install Node 24 + OpenClaw (`npm install -g openclaw@latest`) | XS |
| MC-002 | Install + configure self-hosted Mattermost (Docker recommended) | S |
| MC-003 | Create Neo bot account in Mattermost, capture bot token | XS |
| MC-004 | Install `@openclaw/mattermost` plugin (`openclaw plugins install @openclaw/mattermost`) | XS |
| MC-005 | Write `config/openclaw.json` — Neo agent only, MM token, Ollama endpoint | S |
| MC-006 | Set Ollama provider: `ollama/gemma4:26b` as `agents.defaults.model.primary` | XS |
| MC-007 | Write `agents/neo/system.md` — Neo identity, PLAN-only rules | S |
| MC-008 | Write `skills/plan-mode/SKILL.md` — PLAN/PROPOSE/EXECUTE rules | S |
| MC-009 | Add `alsoDeny: [write, edit, apply_patch, exec]` to Neo agent config | XS |
| MC-010 | Write `scripts/validate.sh` — ping Ollama, MM, OpenClaw health endpoint | S |
| MC-011 | Start OpenClaw gateway, DM @neo, verify reply from `gemma4:26b` | XS |

**P1 DoD:** Human sends "hello" to @neo in Mattermost. Neo replies in PLAN mode using local Ollama. No file writes possible from Neo.

---

## P2 — Full Team Online

**Goal:** All 6 agents running. Smith can delegate to Niaobe. Niaobe can delegate to Morpheus/Oracle.

| ID | Item | Size |
|---|---|---|
| MC-012 | Create 5 remaining MM bot accounts (smith, niaobe, architect, morpheus, oracle) | S |
| MC-013 | Expand `openclaw.json` with all 6 agent entries + MM account tokens | S |
| MC-014 | Write `agents/smith/system.md` — manager role, PLAN default, delegates to Niaobe | S |
| MC-015 | Write `agents/niaobe/system.md` — PM role, execute on delegation, delegates to sub-agents | S |
| MC-016 | Write `agents/architect/system.md` — design role, no exec, DESIGN.md output | S |
| MC-017 | Write `agents/morpheus/system.md` — coder role, write access, honours DESIGN.md | S |
| MC-018 | Write `agents/oracle/system.md` — QA role, write+exec access, tests + reports | S |
| MC-019 | Write `skills/delegation/SKILL.md` — how agents post structured delegation via `message` tool | S |
| MC-020 | Write `skills/project-management/SKILL.md` — project folder layout, file naming, git rules | S |
| MC-021 | Write `skills/sdd-workflow/SKILL.md` — SPEC→DESIGN→TASK→CODE→REVIEW→DONE flow | M |
| MC-022 | Test: Human → Neo → Smith → Niaobe → Morpheus delegation chain end to end | M |
| MC-023 | Tune: ensure sub-agents don't respond to wrong MM channels/mentions | S |

**P2 DoD:** Human asks @neo to build a feature. Chain reaches Morpheus who writes a file.

---

## P3 — SDD Workflow

**Goal:** SPEC.md and DESIGN.md are human-gated and Niaobe-gated respectively before any code is written.

| ID | Item | Size |
|---|---|---|
| MC-024 | Smith: add PROPOSE step — draft SPEC.md inline in MM reply before writing file | S |
| MC-025 | Smith: wait for human approval word before calling `write` on SPEC.md | S |
| MC-026 | Architect: always produce DESIGN.md as output of task | S |
| MC-027 | Niaobe: review DESIGN.md before delegating to Morpheus (skill rule) | S |
| MC-028 | Morpheus: check DESIGN.md exists before writing code (skill rule + `read` call) | S |
| MC-029 | Niaobe: write T{id}.md task briefs before delegating to Morpheus/Oracle | S |
| MC-030 | Test: request without SPEC.md — verify Smith proposes first, waits for approval | S |
| MC-031 | Test: request without DESIGN.md — verify Morpheus blocks, Niaobe escalates | S |

**P3 DoD:** Two-tier SDD gate works. No code written without approved SPEC + reviewed DESIGN.

---

## P4 — Custom MCP Server

**Goal:** Append-only audit log + programmatic design gate. ~200 lines Python.

| ID | Item | Size |
|---|---|---|
| MC-032 | `env-python/bin/pip install fastmcp pydantic` | XS |
| MC-033 | Write `custom_mcp/path_guard.py` — block path traversal (5 lines) | XS |
| MC-034 | Write `custom_mcp/tools/audit.py` — `audit.log(agent_id, tool, args, result)` → SQLite | S |
| MC-035 | Write `custom_mcp/tools/project.py` — `gate_design(slug)` returns pass/fail | S |
| MC-036 | Write `custom_mcp/server.py` — FastMCP server, 3 tools | S |
| MC-037 | Register custom MCP server in `openclaw.json` under `mcp` key | XS |
| MC-038 | Replace skill-based design gate (MC-028) with MCP `gate_design` call | S |
| MC-039 | Test: audit.log written for every Morpheus file write | S |

**P4 DoD:** Every agent tool call is logged. `gate_design` enforced server-side, not just as a skill.

---

## P5 — Security Hardening

**Goal:** Tighten exec, scoping, and escalation paths.

| ID | Item | Size |
|---|---|---|
| MC-040 | Write `config/exec-approvals.json` — allowlist safe commands (git, pytest, npm test) | S |
| MC-041 | Set `tools.exec.ask: "on-miss"` — anything outside allowlist asks for approval | XS |
| MC-042 | Set Oracle `tools.exec.security: "allowlist"` — exec only approved commands | XS |
| MC-043 | Add `sandbox.mode: "non-main"` for Morpheus + Oracle — isolate their sessions | S |
| MC-044 | Verify `${VAR}` pattern used for all secrets — no hardcoded tokens | XS |
| MC-045 | Audit skill files for prompt injection risks (web content injected into skills) | S |
| MC-046 | Add `tools.web_fetch.maxBytes: 50000` to limit web content injected into context | XS |

**P5 DoD:** Shell execution is allowlisted. Sessions are sandboxed. No secrets in config files.

---

## P6 — Observability & Improvements

**Goal:** Items that emerge from real use — add to this band as discovered.

| ID | Item | Size |
|---|---|---|
| MC-047 | Add `#ops` Mattermost channel for OpenClaw system alerts | XS |
| MC-048 | Cron job: daily `openclaw skills update --all` to pull community improvements | XS |
| MC-049 | ClawHub skill: install `github` skill for Morpheus (PR creation, branch push) | XS |
| MC-050 | ClawHub skill: install `code-review` skill for Oracle | XS |
| MC-051 | Add second Morpheus instance for parallel task execution | S |
| MC-052 | `custom_mcp/tools/project.py`: `list_tasks(slug)` — return pending T{id}.md files | S |
| MC-053 | Add per-project Mattermost channel (auto-created by Smith on project start) | M |
| MC-054 | Skill: `openclaw skills install memory` — persistent agent memory across sessions | S |
| MC-055 | Tune `gemma4:26b` system prompts based on real delegation failure patterns | ongoing |
| MC-056 | Evaluate `gemma4:31b` for Architect (heavier reasoning for design tasks) | S |

---

## P7 — Shared Agent Runtime Redesign

**Goal:** Replace prompt-owned lifecycle choreography with a runtime-owned task lifecycle while keeping agent-owned judgment for planning, implementation, design, review, and validation.

**Principle:** Agents decide what to do; runtime controls task identity, context, evidence, validation gates, and final acceptance.

| ID | Item | Size |
|---|---|---|
| MC-057 | Design `AgentTaskRuntime` shared state model: `project_id`, `task_id`, `agent_role`, `run_id`, status, required outputs, artifact manifest, validation plan, validation runs, validation report, and final decision | M |
| MC-058 | Replace agent-facing `prepare` with runtime-owned bootstrap that creates the run, resolves project paths, gathers bounded context, and starts the agent with a compact task packet | M |
| MC-059 | Add stale-run protection: one active task per agent session, run identity checks, and clean block/rotate behavior before accepting a different task envelope | M |
| MC-060 | Define the platform-owned LangGraph lifecycle: `bootstrap -> agent_decision -> artifact_collection -> validation -> evidence_check -> repair_or_done` | M |
| MC-061 | Add shared `validation_evidence`: declared validation plan, controlled `project_exec` run logs, exit code, summary, and agent validation report | M |
| MC-062 | Make Morpheus the first vertical slice: remove Morpheus-facing `prepare`, require artifacts, test files, validation command, and validation report, then accept `DONE` only after evidence passes | L |
| MC-063 | Update Morpheus isolated canary to assert no exposed `prepare`, clean run identity, required artifacts, tests, validation command execution, passing evidence, and no stale run path reuse | M |
| MC-064 | Migrate Architect to `AgentTaskRuntime`: runtime bootstraps context, Architect drafts design, runtime verifies required design sections and design evidence before handoff | M |
| MC-065 | Migrate Smith to `AgentTaskRuntime`: runtime verifies planning completeness, dependency ordering, task files, and one-by-one handoff readiness | M |
| MC-066 | Migrate Oracle to `AgentTaskRuntime`: runtime verifies reviewed artifacts, controlled validation execution, review report, and explicit PASS/FAIL evidence | M |
| MC-067 | Run validation sequence: Morpheus isolated canary twice, full phase suite, Fibonacci E2E, then Architect/Smith/Oracle isolated canaries after each migration | M |

**P7 DoD:** Agents no longer depend on exposed `prepare`/printed runtime paths. Runtime owns lifecycle and evidence gates. Agents still own judgment and write their own role-specific artifacts/reports. Full Fibonacci E2E passes without stale-session contamination.

---

## Skills Update Policy

```bash
# Run weekly (or add as cron in openclaw.json)
openclaw skills update --all

# Install community skills as needed
openclaw skills install github
openclaw skills install code-review
openclaw skills install memory
```

Community skill updates go live immediately — no deployment needed.

---

## Quick Reference: Key Commands

```bash
# Start gateway
MATTERMOST_URL=http://localhost:8065 \
MM_NEO_TOKEN=xxx MM_SMITH_TOKEN=xxx ... \
openclaw gateway --config config/openclaw.json

# Health check
openclaw health
openclaw doctor

# Skill management
openclaw skills list
openclaw skills install <slug>
openclaw skills update --all

# Sub-agent control (from Mattermost)
/subagents list
/subagents log <id>

# Custom MCP (P4)
env-python/bin/python custom_mcp/server.py

# Validate everything
./scripts/validate.sh
```

---

## Sizing Legend

| Size | Effort |
|---|---|
| XS | < 30 min |
| S | 30 min – 2 hrs |
| M | 2–4 hrs |
| L | 4–8 hrs |
