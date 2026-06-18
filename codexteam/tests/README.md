# CodexTeam Tests

Unit, integration, smoke, E2E, security, and state-corruption validation lives here.

Use the repo-local environment for validation:

`PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q`

Phase-scoped helper:

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase1`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase2`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase3`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase4`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase5`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase6`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase7`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase8`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase9`

`./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase phase10`

Smoke and probe runners:

- `codexteam/tests/smoke/codex_local_smoke.py`
- `codexteam/tests/smoke/codex_appserver_probe.py`
- `codexteam/tests/smoke/run_phase9_local_worker_smoke.py`
- `codexteam/tests/smoke/run_leader_project_template_smoke.py`
- `codexteam/tests/smoke/run_real_leader_runtime_smoke.py`

E2E runners:

- `codexteam/tests/e2e/run_phase11_structured_worker_e2e.py`
- `codexteam/tests/e2e/run_phase12_workspace_action_e2e.py`
- `codexteam/tests/e2e/run_phase13_change_proposal_e2e.py`
- `codexteam/tests/e2e/run_project_edit_e2e.py`
- `codexteam/tests/e2e/run_real_life_project_e2e.py`
- `codexteam/tests/e2e/run_real_worker_project_e2e.py`
