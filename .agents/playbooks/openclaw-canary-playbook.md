# OpenClaw V4 Validation Playbook

## Goal
Validate the V4 team through the real Neo intake path:

`Master request -> Neo -> run_v4_team -> Smith -> Morpheus -> Smith -> Oracle -> Smith -> Neo report`

Typed event files, leases, TaskPacks, WorkResults, OracleResults, and the
project-management markdown files are the source of truth. Chat handoffs and
legacy phase canaries are no longer the control plane.

## Trigger
Use this playbook for:
- V4 project startup failures
- Smith planning or task-progress regressions
- Morpheus worker stalls, blocks, or bad artifacts
- Oracle verification failures
- final `PROJECT_STATE.md` / `.openclaw/state.json` disagreement

## Default gates
- Focused unit tests:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_*.py`
- V4 dry-run team gate:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_v4_team.py --dry-run --project-root /tmp/openclaw-v4-dryrun --project-id dryrun-v4 --title "Dryrun V4" --goal "Create a small Python CLI with tests."`
- V4 Fibonacci E2E gate:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --project-root /home/alik/workspace/clawspace/projects/active`
- V4 Neo-driven Fibonacci E2E acceptance gate:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_neo_test.py --project-root /home/alik/workspace/clawspace/projects/active`
- Live prompt/config sync preview:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/sync_live_openclaw.py --agent neo --agent smith --agent morpheus --agent oracle`

## Core routine
1. Reproduce with the narrowest V4 gate that covers the failure.
2. Inspect the V4 project files: `.openclaw/events.jsonl`, `.openclaw/state.json`,
   `PROJECT_STATE.md`, `CURRENT_TASK.md`, and `management/BACKLOG.md`.
3. Identify the first boundary where expected behavior diverged:
   `project_start`, `smith_plan`, `taskpack_scope`, `worker_tools`,
   `work_result`, `oracle_result`, `smith_finalization`, or `sync`.
4. Make the smallest relevant fix.
5. Rerun the same narrow gate.
6. Run `tests/test_v4_*.py`.
7. Run the lower-level V4 Fibonacci E2E gate when debugging Smith/Morpheus/Oracle directly.
8. Run the Neo-driven V4 Fibonacci E2E acceptance gate before calling the full team path stable.
9. Record durable lessons in the smallest appropriate `.agents/memory/` file.

## Routing Rules
- Durable V4 behavior or contract change -> `.agents/memory/decisions.md`
- Mistake pattern or outdated assumption -> `.agents/memory/corrections.md`
- Concrete user request / action history -> `.agents/memory/changelog.md`
- Reusable execution workflow -> `.agents/skills/` or `.agents/playbooks/`
- Tool invocation / environment usage -> `.agents/capabilities/tools.md`

## Principles
- Keep OpenClaw as the agent/tool platform, but keep V4 control state typed.
- Do not reintroduce chat handoffs, phase wrappers, or per-agent runtime scripts
  for ordinary project progress.
- Runtime owns boundaries: workspace layout, leases, allowed artifacts, typed
  events, final state sync, and deterministic validation gates.
- Agents own judgment inside bounded tools: planning, implementation, testing,
  blocking, repair, and verification reports.
