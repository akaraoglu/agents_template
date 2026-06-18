# Sub-Agent Orchestration Skill

## Purpose
Standardized workflow for spawning, managing, and collecting results from local `codex` subagents. This skill enables a leader agent to delegate work to specialized role sub-agents while maintaining structured handoffs, verification gates, and dashboard-ready result artifacts.

## When to Use This Skill
- Delegating tasks to sub-agents with different roles (developer, tester, reviewer)
- Multi-agent project execution where leader coordinates but doesn't execute directly
- Tasks requiring timeout protection, result capture, and idempotent retries
- Any workflow needing structured JSON handoffs for future dashboard integration

## Inputs Needed
| Input | Source | Required |
|-------|--------|----------|
| Project workspace path | Leader context / PROJECT_STATE.md | ✅ |
| Task ID (e.g., t002) | TASKS.md | ✅ |
| Agent role assignment | Leader judgment | ✅ |
| Model profile selection | Profile matrix below | ✅ |
| Handoff prompt/context | IMPLEMENTATION_PLAN.md, task file | ✅ |

## Step-by-Step Workflow

### Phase 1: Pre-Spawn Validation (Idempotency Check)
Before spawning any sub-agent, verify the task isn't already complete:
```bash
# Check if deliverables exist
ls -la <workspace>/results/<task_id>*.json
cat <workspace>/TASKS.md | grep <task_id>

# If JSON exists with "completed" status AND disk artifacts exist → SKIP SPAWN
# If partially complete → RESUME from last known state
```

**Rule:** Never spawn a sub-agent for work that's already verified and persisted.

### Phase 2: Profile Selection Matrix
Choose the model profile based on task role:

| Role | Recommended Profile | Rationale |
|------|---------------------|-----------|
| Developer (implementation) | `qwen36-27b` | Strong code generation, good reasoning |
| Tester (verification) | `qwen36-27b` | Needs to run commands + analyze output |
| Reviewer (code quality) | `gemma4-26b` | Good at critique + structured feedback |
| Writer (docs) | `gemma4-26b` | Sufficient for markdown generation |
| Complex debugging | `qwen36-27b` | Multi-step reasoning strength |

**Available Profiles:** These must exist as `~/.codex/<name>.config.toml`:
- **`qwen36-27b`** → Ollama local qwen3.6-27b (default for most tasks)
- **`gemma4-26b`** → Ollama local gemma4-26b (reviews, docs)

**Fallback:** If preferred model unavailable, use `qwen36-27b`. Never use untested profiles.

### Phase 3: Construct Handoff Prompt
Build the system prompt from three parts:

```
[PART A] ORCHESTRATION CONTRACT (injected by leader/spawn script)
- Role assignment + task ID
- Workspace path + writable directories
- JSON response format contract
- Timeout expectations

[PART B] RELEVANT SKILLS (read from .agents/skills/*.md)
- Only inject skills relevant to this role
- Developer gets: implementation.md, coding-standards.md
- Tester gets: testing.md, verification.md
- Writer gets: document-editing.md

[PART C] TASK SPECIFIC DETAILS
- From IMPLEMENTATION_PLAN.md or task file (T002.md etc)
- Dependencies already completed
- Constraints (stdlib-only, no external libs, etc)
- Completion criteria checklist
```

**Rule:** Do not inject all skills to every sub-agent. Keep context window efficient by injecting only relevant guidance.

### Phase 4: Execute Spawn
Use `spawn-subagent.sh` for standardized execution:

```bash
# Basic spawn with prompt file
.agents/scripts/spawn-subagent.sh \
    --profile qwen36-27b \
    --task t002 \
    --workspace /path/to/project \
    --add-dir /home/alik/workspace/codexspace \
    --prompt-file /tmp/handoff-prompt.json

# Inline prompt (for quick tasks)
.agents/scripts/spawn-subagent.sh \
    --profile qwen36-27b \
    --task t003 \
    --workspace /path/to/project \
    --prompt "Run all tests and verify against PROJECT.md test cases"

# Dry-run first (validate without executing)
.agents/scripts/spawn-subagent.sh \
    --profile qwen36-27b \
    --task t002 \
    --workspace /path/to/project \
    --dry-run
```

**Key parameters:**
- `--add-dir`: Add writable directories (use `/home/alik/workspace/codexspace` for project writes)
- `--timeout`: Override default 600s timeout (default: 10 min)
- `--prompt-file`: JSON handoff with full context (preferred for complex tasks)

### Phase 5: Result Collection & Validation
After spawn completes, leader MUST verify:

```bash
# 1. Check result JSON was created
ls -la <workspace>/results/<task_id>-*.json

# 2. Validate status field
cat <workspace>/results/<task_id>-*.json | python3 -c \
    "import sys,json; print(json.load(sys.stdin)['status'])"

# 3. Independently verify deliverables (DO NOT trust sub-agent claims)
cd <workspace> && python3 -m pytest -q   # or other verification command

# 4. If status=completed AND tests pass → Close loop
#    If status=failed OR tests fail → Retry or escalate
```

### Phase 6: Close Loop (Execution ≠ Completion Rule)
A task is **NOT complete** until ALL four conditions are met:
1. ✅ Deliverables physically exist on disk
2. ✅ `results/<task>.json` persisted with correct status
3. ✅ `TASKS.md` row updated to "Completed" with evidence link
4. ✅ `PROJECT_STATE.md` phase advanced appropriately

```bash
# Update TASKS.md (example)
sed -i 's/| T002 .* Pending/| T002 | Completed | Developer | 9\/9 tests pass | results\/t002.json/' \
    <workspace>/TASKS.md

# Update PROJECT_STATE.md phase
# Advance to next phase or mark delivered
```

**Rule:** Leader must close the loop. Never advance to next task without verifying previous task is fully booked.

## Expected Output
| Artifact | Location | Format |
|----------|----------|--------|
| Sub-agent result | `results/<task>-<timestamp>.json` | JSON (contract below) |
| TASKS.md update | Project root | Markdown table row → Completed |
| PROJECT_STATE.md | Project root | Phase advanced |
| Leader validation log | Leader memory/context | Inline notes |

## Validation Steps
1. Result JSON is valid and parseable
2. Status field matches actual work done (spot-check)
3. Independent test run passes (leader doesn't trust sub-agent blindly)
4. TASKS.md evidence column links to result file
5. No orphaned temp files or incomplete artifacts

## Common Mistakes / Failure Modes

| Mistake | Consequence | Prevention |
|---------|-------------|------------|
| Spawn without idempotency check | Wasted time, duplicate work | Always check results/ + TASKS.md first |
| Trust sub-agent status blindly | False "completed" marks | Leader runs tests independently |
| Forget to update TASKS.md | Stale project state | Close-loop checklist mandatory |
| Inject all skills to every agent | Context window waste | Role-specific skill injection only |
| No timeout protection | Sub-agent hangs forever | spawn-subagent.sh default: 600s |
| Skip result JSON persistence | Lost evidence, no dashboard data | spawn script auto-persists; leader verifies |
| Using non-existent profile name | Falls through to OpenAI → network blocked | Only use `qwen36-27b` or `gemma4-26b` |
| Spawn fails with "Read-only file system" | codex can't write session state | spawn-subagent.sh redirects CODEX_HOME to a writable temp dir and seeds it with your profiles |
| Nested spawn reaches api.openai.com / network blocked | child codex inherits the parent sandbox's network namespace | run from a real terminal (un-nested), or set `network_access=true` on the parent |

## Related Files
| File | Purpose |
|------|---------|
| `.agents/scripts/spawn-subagent.sh` | Shell wrapper for codex exec |
| `.agents/skills/project-lead.md` | Leader orchestration overview |
| `.agents/skills/project_management.md` | Task breakdown + planning |
| `.agents/memory/corrections.md` | Orchestration lessons learned |
| `results/*.json` (project) | Dashboard-ready result artifacts |

## Result JSON Contract (What Every Sub-Agent Must Return)

```json
{
  "task_id": "t002",
  "status": "completed | failed | partial | blocked",
  "summary": "Brief description of what was done",
  "file_changes": [
    {"path": "src/fibonacci.py", "action": "created"},
    {"path": "tests/test_fibonacci.py", "action": "created"}
  ],
  "evidence": [
    {
      "type": "test_output",
      "artifact_ref": "test-results.log",
      "summary": "pytest passed 9/9 tests",
      "metadata": {"pass_count": 9, "fail_count": 0}
    }
  ],
  "errors": [],
  "warnings": ["Used temporary test data"],
  "limitations": ["No performance benchmarks"],
  "completed_at": "2026-06-17T15:30:00+03:00"
}
```

**Status Meanings:**
- `completed`: Work done, tests pass, ready for leader validation
- `failed`: Work attempted but couldn't finish; errors array populated
- `partial`: Some work done, incomplete deliverables
- `blocked`: External dependency missing or access denied; needs leader intervention
- `needs_review`: Work done but requires leader inspection before advance

**Common Mistakes:**
- Returning JSON mid-stream instead of at the end (breaks spawn-subagent.sh capture)
- Omitting file_changes array even when no files changed (dashboard needs it)
- Using wrong task_id or team_id (breaks traceability chain)
- Forgetting to write result to disk in `results/`

## Schema References
Full contract details are in the schemas directory:
- **Handoff (Leader → Subagent):** `.agents/schemas/handoff_contract.md`
- **Result (Subagent → Leader):** `.agents/schemas/result_contract.md`

Both are markdown-reference only — not enforced by Python today. Dashboard consumers can parse them directly from spawn-subagent.sh logs and `results/*.json` files.

## Local Smoke Test
Run from a **real terminal**, not nested inside another codex agent — a nested child
inherits the parent sandbox's empty network namespace and can't reach Ollama.

```bash
# 1. Prerequisites: Ollama up + profiles present
ollama ps                                   # qwen3.6-27b / gemma4-26b loaded or loadable
ls ~/.codex/qwen36-27b.config.toml ~/.codex/gemma4-26b.config.toml

# 2. Dry-run (no model call) — confirms the command + prompt are built correctly
.agents/scripts/spawn-subagent.sh \
    --profile qwen36-27b --task t000 \
    --workspace /tmp/sa-ws --prompt "noop" --dry-run

# 3. Live spawn — ask for a sentinel deliverable, then verify
mkdir -p /tmp/sa-ws
.agents/scripts/spawn-subagent.sh \
    --profile qwen36-27b --task t000 \
    --workspace /tmp/sa-ws \
    --prompt "Create results/ok.txt containing SPAWN_OK, then report the result JSON."

# 4. Check the captured result AND the real deliverable (don't trust status blindly)
cat /tmp/sa-ws/results/t000-*.json | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])"
cat /tmp/sa-ws/results/ok.txt
```

**Pass criteria:** result JSON `status` is `completed` AND the deliverable exists on disk.
If the spawn instead reaches `api.openai.com`, you're running nested — rerun from a plain
terminal, or set `network_access=true` on the parent codex process.
