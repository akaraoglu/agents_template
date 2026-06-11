# Tools and Environment

Use repo-native tooling first. Inspect local scripts, config files, and existing
commands before inventing new ones.

## Project Workflow
- This repository includes Python code.
- The active OpenClaw team implementation is AgenticTeam.
- Agents should run scripts, inspect results, debug failures, and refine the
  solution until it meets acceptance criteria.

## Environment
- Python version: `3.12.10`
- Dependency manager: `pip + venv`
- OS assumptions: Windows and Linux

## Python Commands
- Use the repo-local interpreter for validation:
  `./env-python/bin/python`
- Standard test command:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q`
- Focused team tests:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_*.py`

## OpenClaw Team Runtime
- Local runtime config: `/home/alik/workspace/clawspace/system/config/runtime.local.yaml`
- Runtime SQLite ActionStore: `/home/alik/workspace/clawspace/system/runtime/openclaw_runtime.sqlite3`
- Active project root: `/home/alik/workspace/clawspace/projects/active`
- Team project starter/conductor:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_team.py`
- Live helper installed by sync:
  `/home/alik/workspace/clawspace/bin/run_team.sh`
- Persistent project creator:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/create_project.py`
- Fibonacci E2E:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_test.py --project-root /home/alik/workspace/clawspace/projects/active`
- Neo-driven Fibonacci E2E, the real full-team acceptance gate:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_neo_test.py --project-root /home/alik/workspace/clawspace/projects/active`
- Worker canary:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_worker_canary.py`
- Oracle canary:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_oracle_canary.py`
- Live sync preview:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/sync_live_openclaw.py --agent neo --agent smith --agent morpheus --agent oracle`

## Team Evidence Files
- `.openclaw/events.jsonl`: append-only typed event log.
- `.openclaw/state.json`: typed runtime mirror.
- `.openclaw/leases.json`: scoped tool leases.
- `PROJECT_STATE.md`, `CURRENT_TASK.md`, `management/PLAN.md`,
  `management/BACKLOG.md`, and `management/tasks/*.md`: human-readable project
  process surface.

## Working Rules
- Prefer `rg` and `rg --files` for search.
- Run the smallest relevant command first.
- Inspect real command output before making follow-up changes.
- If a quality gate cannot be run, record what was tried and why it failed.
