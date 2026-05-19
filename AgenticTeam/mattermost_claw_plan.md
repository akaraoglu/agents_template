# AgenticTeam — Mattermost + OpenClaw System Design

**Goal:** Autonomous 6-agent software development crew with minimal custom code.
**Stack:** OpenClaw (gateway + tools) · Mattermost (channel) · Ollama `gemma4:26b` (LLM) · Skills (workflow rules) · Tiny custom MCP (project logic only)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        HUMAN                                    │
│              (Mattermost DM or @neo mention)                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                 MATTERMOST  (self-hosted)                        │
│   6 bot accounts: neo · smith · niaobe · architect         │
│                   morpheus · oracle                              │
│   Channels: #projects  #ops  (+ per-project channels)           │
└──────┬──────────────────────────────────────────────────────────┘
       │  Bot API + WebSocket
┌──────▼──────────────────────────────────────────────────────────┐
│              OPENCLAW GATEWAY  (Node 24, local)                  │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │  neo    │ │smith│ │  niaobe  │ │architect │  ...       │
│  │ agent   │ │  agent   │ │  agent   │ │  agent   │           │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │           │            │             │                  │
│  ┌────▼───────────▼────────────▼─────────────▼──────────────┐  │
│  │              BUILT-IN TOOLS (zero custom code)            │  │
│  │  read · write · edit · exec · web_search · web_fetch     │  │
│  │  browser · image · sessions_spawn (sub-agents)           │  │
│  └────────────────────────────┬──────────────────────────────┘  │
│                               │                                  │
│  ┌────────────────────────────▼──────────────────────────────┐  │
│  │              SKILLS  (.agents/skills/)                     │  │
│  │  sdd-workflow · plan-mode · delegation · project-mgmt     │  │
│  │  per-agent role skills                                     │  │
│  └────────────────────────────┬──────────────────────────────┘  │
│                               │                                  │
│  ┌────────────────────────────▼──────────────────────────────┐  │
│  │           CUSTOM MCP SERVER  (Python, minimal)            │  │
│  │  project.gate_design · project.create_spec                │  │
│  │  audit.log · delegation.send                              │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────────┐
│              OLLAMA  (local, gemma4:26b)                         │
│  All 6 agents share the same Ollama instance                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## What OpenClaw Provides (Zero Custom Code)

| Capability | OpenClaw feature | We write |
|---|---|---|
| Mattermost integration | `@openclaw/mattermost` plugin | Nothing |
| File read/write/edit | Built-in `read`/`write`/`edit`/`apply_patch` | Nothing |
| Shell execution | Built-in `exec` with approval gates | Allowlist config only |
| Web search + fetch | Built-in `web_search` / `web_fetch` | Nothing |
| Image analysis | Built-in `image` | Nothing |
| Browser automation | Built-in `browser` | Nothing |
| Sub-agent spawning | Built-in `sessions_spawn` | Nothing |
| Session management | Built-in session system | Nothing |
| Ollama model routing | Built-in `ollama/*` provider | Config only |
| Multi-agent routing | `agents.list[]` in `openclaw.json` | Config only |
| Skill upgrades | `openclaw skills update --all` | Skill files only |

---

## What We Build (Custom, Minimal)

| What | Why OpenClaw can't | Lines est. |
|---|---|---|
| `SKILL.md` files (6–8 skills) | Our workflow rules (SDD, modes, delegation) | ~400 lines Markdown |
| `openclaw.json` config | Wire 6 agents to 6 MM bots + Ollama | ~150 lines JSON |
| `custom_mcp/server.py` | Project audit log + design gate (stateful) | ~200 lines Python |
| Agent prompts (6 × `system.md`) | Role identity and boundaries | ~300 lines Markdown |
| `scripts/setup.sh` | Create MM bots + OpenClaw onboarding | ~60 lines bash |

**Total custom code: ~200 lines Python, ~700 lines Markdown/config.**

---

## Environment & Software

| Software | Version | Install |
|---|---|---|
| Node.js | 24 (LTS) | `nvm install 24` |
| OpenClaw | latest | `npm install -g openclaw@latest` |
| Mattermost | latest (self-hosted) | Docker or native |
| Ollama | latest | `curl -fsSL https://ollama.ai/install.sh \| sh` |
| Model | `gemma4:26b` | `ollama pull gemma4:26b` |
| Python | 3.12 (`env-python/`) | Already present |
| MCP packages | fastmcp, pydantic | `env-python/bin/pip install fastmcp pydantic` |

> **Python rule:** All Python goes into `env-python/` only. Never system Python.

---

## File & Folder Structure

```
AgenticTeam/
│
├── mattermost_claw_plan.md        ← this file
├── mattermost_claw_backlog.md     ← prioritized backlog
│
├── config/
│   ├── openclaw.json              # [P1] OpenClaw gateway config — all 6 agents, MM tokens, Ollama
│   └── exec-approvals.json        # [P1] Shell command allowlist (safety gate)
│
├── skills/                        # Shared skills — all agents load these
│   ├── sdd-workflow/
│   │   └── SKILL.md               # [P2] SDD process: SPEC→DESIGN→TASK→CODE→REVIEW→DONE
│   ├── plan-mode/
│   │   └── SKILL.md               # [P1] PLAN/PROPOSE/EXECUTE rules per agent
│   ├── delegation/
│   │   └── SKILL.md               # [P2] How to delegate tasks via Mattermost message tool
│   └── project-management/
│       └── SKILL.md               # [P2] Project folder structure, file naming, git rules
│
├── agents/                        # Per-agent workspaces (OpenClaw agent workspace paths)
│   ├── neo/
│   │   ├── system.md              # [P1] Neo system prompt
│   │   └── skills/
│   │       └── SKILL.md           # [P1] Neo-specific overrides (PLAN only, no writes)
│   ├── smith/
│   │   ├── system.md              # [P2] Smith system prompt
│   │   └── skills/
│   │       └── SKILL.md           # [P2] Smith overrides (PLAN default, approves sub-agents)
│   ├── niaobe/
│   │   ├── system.md              # [P2] Niaobe system prompt
│   │   └── skills/
│   │       └── SKILL.md           # [P2] Niaobe overrides (execute on delegation)
│   ├── architect/
│   │   ├── system.md              # [P2] Architect system prompt
│   │   └── skills/
│   │       └── SKILL.md           # [P2] Architect overrides (design only, DESIGN.md gate)
│   ├── morpheus/
│   │   ├── system.md              # [P2] Morpheus system prompt
│   │   └── skills/
│   │       └── SKILL.md           # [P2] Morpheus overrides (coding, write access)
│   └── oracle/
│       ├── system.md              # [P2] Oracle system prompt
│       └── skills/
│           └── SKILL.md           # [P2] Oracle overrides (test + review, exec access)
│
├── custom_mcp/                    # Minimal Python MCP — project logic only
│   ├── server.py                  # [P3] FastMCP entry point
│   ├── tools/
│   │   ├── project.py             # [P3] create_spec, gate_design, list_tasks
│   │   └── audit.py               # [P3] append-only audit log (SQLite)
│   └── path_guard.py              # [P3] Prevent path traversal
│
├── projects/                      # Workspace root — all project folders live here
│   └── .gitkeep
│
└── scripts/
    ├── setup.sh                   # [P1] Install OpenClaw, MM plugin, create 6 bot accounts
    └── validate.sh                # [P1] Check Ollama, MM, OpenClaw health
```

---

## OpenClaw Configuration (`config/openclaw.json`)

```json
{
  "gateway": {
    "port": 18789
  },
  "models": {
    "providers": {
      "ollama": {
        "url": "http://localhost:11434"
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/gemma4:26b"
      },
      "workspace": "./projects",
      "tools": {
        "profile": "coding",
        "alsoAllow": ["sessions_spawn", "web_search", "web_fetch", "image"]
      },
      "skills": ["plan-mode", "sdd-workflow", "delegation", "project-management"]
    },
    "list": [
      {
        "id": "neo",
        "systemPrompt": "./agents/neo/system.md",
        "workspace": "./agents/neo",
        "skills": ["plan-mode"],
        "tools": { "alsoDeny": ["write", "edit", "apply_patch", "exec"] }
      },
      {
        "id": "smith",
        "systemPrompt": "./agents/smith/system.md",
        "workspace": "./agents/smith",
        "skills": ["plan-mode", "sdd-workflow", "delegation", "project-management"]
      },
      {
        "id": "niaobe",
        "systemPrompt": "./agents/niaobe/system.md",
        "workspace": "./agents/niaobe",
        "skills": ["sdd-workflow", "delegation", "project-management"]
      },
      {
        "id": "architect",
        "systemPrompt": "./agents/architect/system.md",
        "workspace": "./agents/architect",
        "skills": ["sdd-workflow", "project-management"],
        "tools": { "alsoDeny": ["exec"] }
      },
      {
        "id": "morpheus",
        "systemPrompt": "./agents/morpheus/system.md",
        "workspace": "./agents/morpheus",
        "skills": ["sdd-workflow", "project-management"]
      },
      {
        "id": "oracle",
        "systemPrompt": "./agents/oracle/system.md",
        "workspace": "./agents/oracle",
        "skills": ["sdd-workflow", "project-management"]
      }
    ]
  },
  "channels": {
    "mattermost": {
      "url": "${MATTERMOST_URL}",
      "chatmode": "oncall",
      "replyToMode": "all",
      "accounts": [
        { "token": "${MM_NEO_TOKEN}",        "agentId": "neo" },
        { "token": "${MM_SMITH_TOKEN}",      "agentId": "smith" },
        { "token": "${MM_NIAOBE_TOKEN}",     "agentId": "niaobe" },
        { "token": "${MM_ARCHITECT_TOKEN}",  "agentId": "architect" },
        { "token": "${MM_MORPHEUS_TOKEN}",   "agentId": "morpheus" },
        { "token": "${MM_ORACLE_TOKEN}",     "agentId": "oracle" }
      ]
    }
  }
}
```

> All `${VAR}` values go in shell environment — never hardcoded in JSON.

---

## Agent Roles

| Agent | MM Bot | Default Mode | Approver | Write Access | Can Delegate To |
|---|---|---|---|---|---|
| **Neo** | `@neo` | PLAN only | Human | ❌ None | — (escalates to Smith) |
| **Smith** | `@smith` | PLAN → human approves | Human | ✅ Limited | Niaobe |
| **Niaobe** | `@niaobe` | EXECUTE (on delegation) | Smith | ✅ Full | Architect, Morpheus, Oracle |
| **Architect** | `@architect` | EXECUTE (on delegation) | Niaobe | ✅ Docs only | — |
| **Morpheus** | `@morpheus` | EXECUTE (on delegation) | Niaobe | ✅ Code + files | — |
| **Oracle** | `@oracle` | EXECUTE (on delegation) | Niaobe | ✅ Tests + exec | — |

**Mode logic implemented as Skills** — no code needed:
- **PLAN:** Agent reads, analyzes, replies with proposal only. No file writes.
- **PROPOSE:** Agent drafts the change in a Mattermost reply. Waits for approval.
- **EXECUTE:** Agent executes only after explicit approval word ("go", "approved", "do it").

---

## Delegation Flow

```
Human @neo: "Build a REST API for user management"
│
├─[PLAN] Neo: analyzes request, asks clarifying questions
├─[PLAN] Neo: produces PRD summary, proposes to escalate to Smith
│
└─ Human approves → Neo posts to #projects @smith
   │
   ├─[PLAN] Smith: reviews PRD, creates SPEC.md draft
   ├─[PROPOSE] Smith: posts SPEC.md to Human for review
   └─ Human approves SPEC.md
      │
      ├─[EXECUTE] Smith: writes SPEC.md to projects/<slug>/SPEC.md
      └─[EXECUTE] Smith: delegates to Niaobe via @niaobe DM
         │
         ├─[EXECUTE] Niaobe: delegates to Architect for DESIGN.md
         │   └─[EXECUTE] Architect: writes DESIGN.md, posts to Niaobe
         │       └─ Niaobe reviews DESIGN.md (auto-approved if valid)
         │
         ├─[EXECUTE] Niaobe: creates task list (T001, T002, T003...)
         └─[EXECUTE] Niaobe: delegates T001 to Morpheus, T002 to Oracle (parallel)
             │
             ├─[EXECUTE] Morpheus: reads DESIGN.md + T001.md, writes code
             └─[EXECUTE] Oracle: writes tests, runs exec, reports back to Niaobe
                 │
                 └─ Niaobe: aggregates results, posts DONE to Smith
                     └─ Smith: posts to Human
```

---

## PLAN/PROPOSE/EXECUTE as Skills

Implemented entirely in `skills/plan-mode/SKILL.md`:

```markdown
---
name: plan-mode
description: Controls when an agent may read, propose, or execute changes.
---

## PLAN Mode (default for Neo and Smith)
- You may read files, search the web, and analyze information.
- You may NOT use write, edit, apply_patch, or exec tools.
- Respond with your analysis and a PROPOSAL only.
- Wait for an explicit approval word before switching to EXECUTE.
- Approval words: "go", "approved", "do it", "execute", "yes proceed".

## PROPOSE Mode
- Draft your intended changes in your Mattermost reply (show diffs/content inline).
- Do NOT call write/edit yet — show the human or your manager first.
- Label your reply with [PROPOSE] at the top.

## EXECUTE Mode (default for Niaobe, Architect, Morpheus, Oracle on delegation)
- A delegation message IS approval. Execute immediately.
- If blocked or ambiguous, switch to PROPOSE and message your manager.
- Never escalate to the human directly — escalate to your manager.

## Approval escalation chain
Neo → Human
Smith → Human
Niaobe → Smith
Architect, Morpheus, Oracle → Niaobe
```

---

## SDD (Spec-Driven Development) Workflow

### Tier 1 — System Level (human-gated, once per project)
```
SPEC.md   → Human approves (Smith proposes, Human approves)
DESIGN.md → Niaobe approves (Architect writes, Niaobe reviews)
```

### Tier 2 — Task Level (Niaobe-gated, per task, no human involvement)
```
T{id}.md  → Niaobe creates task brief from DESIGN.md
           → Morpheus/Oracle execute against T{id}.md as contract
           → Any deviation = PROPOSE back to Niaobe
```

### Project Folder Convention
```
projects/<slug>/
├── SPEC.md            # Human-approved requirements
├── DESIGN.md          # Architecture contract (Niaobe-approved)
├── tasks/
│   ├── T001.md        # Task brief (Niaobe-authored)
│   └── T002.md
├── src/               # Code (Morpheus writes here)
├── tests/             # Tests (Oracle writes here)
└── .openclaw/
    ├── audit.jsonl    # Append-only tool call log
    └── events.jsonl   # Agent activity log
```

---

## Custom MCP Server (Minimal — P3)

Only built after P1+P2 are stable. Three tools only:

| Tool | Purpose | Why not OpenClaw |
|---|---|---|
| `project.gate_design` | Check DESIGN.md exists before Morpheus writes code | Stateful business rule |
| `project.create_spec` | Atomic write + immediate git commit | Atomicity guarantee |
| `audit.log` | Append-only SQLite log with run_id + agent_id | Tamper-evident record |

```python
# custom_mcp/server.py — ~50 lines
from fastmcp import FastMCP
from tools.project import gate_design, create_spec
from tools.audit import log_event

mcp = FastMCP("agenticteam-mcp")
mcp.tool(gate_design)
mcp.tool(create_spec)
mcp.tool(log_event)

if __name__ == "__main__":
    mcp.run()
```

Run: `env-python/bin/python custom_mcp/server.py`

---

## Startup Sequence

```bash
# 1. Start Ollama (already running)
ollama serve &

# 2. Start Mattermost (if not running as service)
# (docker or native — assumed already up)

# 3. Start OpenClaw gateway
MATTERMOST_URL=http://localhost:8065 \
MM_NEO_TOKEN=xxx ... \
openclaw gateway --config config/openclaw.json

# 4. (P3) Start custom MCP server
env-python/bin/python custom_mcp/server.py &

# 5. Validate
./scripts/validate.sh
```

---

## Security Baseline (Minimal, Not Deferred)

| Risk | Mitigation | How |
|---|---|---|
| Shell RCE | `exec` approval gate | `exec-approvals.json` allowlist, ask=on-miss |
| Neo writing files | Tool deny list | `alsoDeny: [write, edit, exec]` in config |
| Prompt injection via web | OpenClaw content sandbox | Default behavior |
| Secrets in config | Env vars only | `${VAR}` in `openclaw.json` |
| Path traversal | OpenClaw workspace scoping | `workspace` field per agent |

---

## ADRs

| # | Decision | Rationale |
|---|---|---|
| ADR-01 | OpenClaw as primary runtime | Minimizes code; open-source upgrades are free |
| ADR-02 | Mattermost over Zulip | Only chat platform with native OpenClaw plugin |
| ADR-03 | Ollama `gemma4:26b` only | No cloud LLM; local inference; already running |
| ADR-04 | Skills for workflow rules | No code needed; updatable without deployment |
| ADR-05 | Custom MCP only for stateful business logic | Built-in tools cover everything else |
| ADR-06 | `env-python` for all Python | Single, controlled venv; no system Python |
| ADR-07 | Sub-agent spawning for delegation | OpenClaw native; no custom routing code |
| ADR-08 | PLAN/PROPOSE/EXECUTE as skill, not code | Fastest to iterate; LLM follows instructions |
| ADR-09 | Append-only audit via SQLite (P3) | Tamper-evident; queryable; simple |
| ADR-10 | Workspace per agent, shared projects/ | Isolation + shared artifact access |
