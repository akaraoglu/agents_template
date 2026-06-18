# Corrections Memory

## Purpose
Record mistakes, outdated assumptions, and corrected guidance that future agents should not repeat.

## Entries
- CodexTeam conversational UX must be agent-first, not parser-first. A deterministic English-to-command parser is acceptable only as a safety/control scaffold; the primary `talk_to_leader.py` experience should use the real leader conversation agent with internal validated tool calls, stored confirmations, and natural responses.
- Do not describe controller-synthesized project files as real team implementation. `run_real_life_project_e2e.py` is a scaffold gate test; real implementation proof must use a worker adapter or local Codex execution such as `run_real_worker_project_e2e.py`.
- Do not assume project files are UTF-8 text when snapshotting or diffing a live project runtime. Project runtime file tracking must compare raw bytes so a single binary or non-UTF8 file does not break the entire leader run.

## Orchestration Rules (Fibonacci Multi-Agent POC, 2026-06-17)

### Lesson: Execution ≠ Completion
A task is **not complete** until all four conditions are met:
1. Deliverables physically exist on disk
2. `results/<task>.json` report is persisted with status, artifacts, and verification data
3. `TASKS.md` row updated to Completed with evidence link
4. `PROJECT_STATE.md` phase advanced appropriately

### Gap Observed in T002
- Subagent wrote fibonacci.py + test_fibonacci.py ✅
- JSON report was never saved ❌
- TASKS.md remained Pending ❌
- PROJECT_STATE.md showed "In Progress" forever ❌

### Rule: Leader Must Close the Loop
Before advancing to next task, leader must execute:
```
verify_deliverables_exist(task) → save_results_json(task) → update_tasks_md(task) → advance_phase()
```
If any step fails, **do not queue the next task**. Retry or report blocked state.

### Rule: Idempotency Check Before Spawn
Before spawning subagent for task N:
- Check if deliverables already exist on disk
- Check if `results/<task>.json` exists with "completed" status
- If both true, skip spawn and advance phase directly
- If only partially complete, resume from last known state

### Rule: Verification Before Completion
Leader must run tests independently of subagent claims.
Subagent may report success but implementation could be wrong.
Leader validation step is mandatory gate before marking complete.
