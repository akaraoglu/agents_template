# Tools and Environment

Use repo-native tooling first. Inspect local scripts, config files, and existing commands before inventing new ones.

## Project Workflow
- This repository includes Python code.
- The agent should be able to run scripts, inspect results, debug issues, and refine the solution until it meets the acceptance criteria.

## Environment
- Python version: `3.12.10`
- Dependency manager: `pip + venv`
- OS assumptions: Windows and Linux

## Activate Python Environment
- For this repository, activate the local venv before any Python-based command:
  `source ./env-python/bin/activate`
- Windows PowerShell: `..\\env-python\\Scripts\\Activate.ps1`
- Windows cmd: `..\\env-python\\Scripts\\activate.bat`

## Standard Commands
- Install dependencies: `pip install -r requirements.txt`
- Run tests: `pytest`
- Run a script: `python path/to/script.py`
- Lint or typecheck: use the repo-specific command if present

## OpenClaw/Zulip Local Runtime
- Live crew implementation: `claw_agents_team/`
- Local runtime config: `/home/alik/workspace/clawspace/system/config/runtime.local.yaml`
- Zulip bot credentials: `/home/alik/workspace/clawspace/system/config/zulip_bots_email_and_keys.txt`
- Use the credential file directly for live smoke tests; do not search the workspace for Zulip accounts.
- To initiate a human-like smoke request, use an unconfigured bot account from the credential file, such as `morpheus-bot@bots.localdomain`, so the configured crew bots do not ignore their own messages.
- Runtime SQLite ActionStore: `/home/alik/workspace/clawspace/system/runtime/openclaw_runtime.sqlite3`
- Project root: `/home/alik/workspace/clawspace/projects/active`
- Phase canary runner:
  `bash AgenticTeam/scripts/run_openclaw_phase_canary.sh --phase <neo_project_create|smith_planning|smith_niaobe_handoff|architect_worker_runtime|morpheus_direct_implementation|oracle_verification>`
- Canary suite runner:
  `bash AgenticTeam/scripts/run_canary_suite.sh`
- Fixed OpenClaw E2E canary:
  `bash AgenticTeam/scripts/run_e2e_fibonacci_test.sh --report-file /home/alik/.copilot/session-state/27757261-2eab-44e0-a711-3a33df12c25c/files/fibonacci-e2e-report.md`
- Use the smallest matching phase canary first, then rerun the Fibonacci E2E
  canary as the end-to-end baseline.

## Working Rules
- Prefer `rg` and `rg --files` for search.
- Run the smallest relevant command first.
- Inspect real command output before making follow-up changes.
- If a quality gate cannot be run, record what was tried and why it failed.
- Replace the example commands above with repo-specific commands as the project matures.
