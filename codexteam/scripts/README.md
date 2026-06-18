# CodexTeam Scripts

Small committed helper scripts belong here.

Scripts must validate inputs, use safe defaults, avoid credentials, and support preview or dry-run behavior when practical.

## Local Codex Tools

These scripts use Python standard library only:

- `codex_local_run.py`: structured wrapper around `codex exec --json` for local worker-adapter development.
- `run_codexteam_tests.py`: run CodexTeam tests with the local source path configured.
- `../bin/codexteam board`: standalone read-only board command with text and JSON output, no leader/model dependency.
- `create_team.py`, `approve_plan.py`, `create_task.py`, `run_worker.py`, `show_board.py`, `approve_review.py`, and `reject_review.py`: operator-facing MVP commands routed through controller APIs or read-only board APIs.
- `talk_to_leader.py`: conversational leader entrypoint that routes project understanding into the real project runtime and explicit control operations into controller-backed commands.

Smoke, probe, and E2E runners now live under `codexteam/tests/smoke/` and `codexteam/tests/e2e/`.

Examples:

```bash
./env-python/bin/python codexteam/scripts/codex_local_run.py "Summarize README.md in one sentence."
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase1
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase2
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase3
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase4
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase5
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase6
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase7
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase8
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase9
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase10
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase11
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase12
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase13
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase14
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase15
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase16
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase17
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase18
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase19
./env-python/bin/python codexteam/scripts/talk_to_leader.py --team team-1
./env-python/bin/python codexteam/bin/codexteam board team-1
./env-python/bin/python codexteam/bin/codexteam board team-1 --json
./env-python/bin/python codexteam/scripts/create_team.py team-1 "Investigate local task"
./env-python/bin/python codexteam/scripts/approve_plan.py team-1 plan-1
./env-python/bin/python codexteam/scripts/create_task.py team-1 task-1 "Do the work" --ready --assign-agent worker-1
./env-python/bin/python codexteam/scripts/run_worker.py team-1 task-1 worker-1 run-1 workspace-1 attempt-1 --approve-start
```
