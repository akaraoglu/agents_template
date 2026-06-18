# CodexTeam Self-Improvement Tools

These tools automate recurring orchestration patterns to reduce token usage and eliminate repetitive scripting.

## Quick Reference

| Tool | What It Does | Saves ~Tokens | Usage |
|------|-------------|---------------|-------|
| `init-project.py` | Creates full project workspace with standard boilerplate | 80/project | `init-project.py <name> --tasks T001,T002` |
| `update-tasks.py` | Safely updates TASKS.md table rows (no fragile sed) | 30/task | `update-tasks.py TASKS.md --task T002 --status Completed ...` |
| `verify-result.py` | Validates result JSONs for Fix #6 compliance + contract shape | 50/spawn | `verify-result.py results/t002.json --task t002` |
| `close-loop.sh` | Full close-loop: verify → update tasks → delivery report | 100/project | `close-loop.sh PROJECT_DIR --task T003 --tests "pytest ..."` |

## Tool Details

### 1. init-project.py
Creates a complete project workspace with standard structure:
```
/home/alik/workspace/codexspace/projects/<NAME>-<TIMESTAMP>/
├── PROJECT.md       ← Requirements table template
├── TASKS.md         ← Task tracking table
├── results/         ← For spawn result JSONs  
├── src/             ← Source code directory
└── tests/           ← Test suite directory
```

**Usage:**
```bash
init-project.py fibonacci-e2e-test
# Creates: .../fibonacci-e2e-test-20260618-153045/ with all structure

# With custom tasks:
init-project.py my-app --tasks T001,T002,T003,T004
```

### 2. update-tasks.py
Replaces fragile sed commands for updating TASKS.md markdown tables:

**What it fixes:**
- sed breaks on long lines with pipes `|` in values → this handles them correctly
- Multiple invocations don't corrupt the table → uses proper row matching  
- Supports partial updates (only change fields you specify)

**Usage:**
```bash
# Update T002 to completed
update-tasks.py TASKS.md \
    --task T002 \
    --status Completed \
    --verification "7/7 tests pass independently" \
    --evidence "\`results/t002.json\`"

# Add history entry only:
update-tasks.py TASKS.md --task T001 --history "T001 completed at 15:34"
```

### 3. verify-result.py
Validates spawn result JSONs for contract compliance and Fix #6 template placeholder bugs:

**Checks performed:**
1. File exists and is valid JSON ✅
2. Required keys present (`task_id`, `status`, `summary`) ✅  
3. Status is a single valid word (not `"completed | failed | partial | blocked"`) ✅
4. No template placeholders in values ✅
5. Task ID matches expected value (if provided) ✅

**Usage:**
```bash
# Basic validation:
verify-result.py results/t002.json

# With task ID verification:
verify-result.py results/t003.json --task t003

# Strict mode (checks evidence array, proper list types):  
verify-result.py results/t004.json --strict

# Exit codes: 0=valid, 1=invalid/missing
```

### 4. close-loop.sh
Automates the full leader close-loop sequence in one command:

**What it does:**
1. Verifies result JSON exists and is Fix #6 compliant ✅
2. Runs optional test command if `--tests` given ✅  
3. Updates TASKS.md with completion status ✅
4. Checks if all tasks are done → writes DELIVERY.md ✅

**Usage:**
```bash
# Basic close-loop (no tests):
close-loop.sh PROJECT_DIR --task t002

# With test verification:
close-loop.sh PROJECT_DIR \
    --task t003 \
    --tests "cd PROJECT && python3 -m pytest tests/ -v" \
    --deliveries "src/fibonacci.py|tests/test_fibonacci.py"

# Exit codes: 0=success, 1=result invalid, 2=tests failed
```

## Token Savings Projection

Based on E2E test run data (4 tasks spawned):

| Pattern | Manual tokens | With tools | Savings |
|---------|---------------|------------|---------|
| Project setup (PROJECT.md + TASKS.md) | ~150 | 30 | -120 |
| Task updates (sed commands) × 4 | ~80 | 60 | -20 |  
| Result verification × 3 | ~60 | 30 | -30 |
| Close-loop sequence | ~90 | 40 | -50 |
| **Total per project** | **~380** | **~160** | **-220 (~58% reduction)** |

## When to Use

| Situation | Tool |
|-----------|------|
| Starting a new orchestration project | `init-project.py` |
| After spawning an agent, updating task status | `update-tasks.py` |
| Checking if spawn results are Fix #6 compliant | `verify-result.py` |  
| Finalizing a completed task with full close-loop | `close-loop.sh` |

## Maintenance Notes

- All tools use Python 3.12+ (matches agent environment)  
- close-loop.sh is bash but delegates to Python tools for reliability
- No external dependencies beyond stdlib
- Located in `codexteam/scripts/` (writable, outside read-only `.agents/`)
