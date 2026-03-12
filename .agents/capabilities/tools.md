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
- Linux or macOS: `source ../env-python/bin/activate`
- Windows PowerShell: `..\\env-python\\Scripts\\Activate.ps1`
- Windows cmd: `..\\env-python\\Scripts\\activate.bat`

## Standard Commands
- Install dependencies: `pip install -r requirements.txt`
- Run tests: `pytest`
- Run a script: `python path/to/script.py`
- Lint or typecheck: use the repo-specific command if present

## Working Rules
- Prefer `rg` and `rg --files` for search.
- Run the smallest relevant command first.
- Inspect real command output before making follow-up changes.
- If a quality gate cannot be run, record what was tried and why it failed.
- Replace the example commands above with repo-specific commands as the project matures.
