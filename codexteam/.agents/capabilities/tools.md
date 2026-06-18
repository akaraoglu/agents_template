# Tools and Environment

Use repo-native tooling first. Inspect local scripts, config files, and existing
commands before inventing new ones.

## Environment
- Python projects use the repo-local `env-python/` virtual environment.
- Create or refresh the virtual environment with `./setup_local_env.sh`.
- Dependency manager: `pip + venv`.
- Treat `env-python/` as generated local state, not source guidance.

## Python Commands
- If `env-python/` is missing, run:
  `./setup_local_env.sh`
- Use the repo-local interpreter for validation:
  `./env-python/bin/python`
- Standard test command:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q`
- Focused tests:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_*.py`

## Working Rules
- Prefer `rg` and `rg --files` for search.
- Run the smallest relevant command first.
- Inspect real command output before making follow-up changes.
- If a quality gate cannot be run, record what was tried and why it failed.
