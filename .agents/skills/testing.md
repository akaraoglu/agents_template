# Testing

## Purpose
Choose, write, and run tests that validate behavior without unnecessary scope.

## Trigger
Use this skill when code changes affect behavior, bug fixes, or integration
points.

## Inputs
- Changed files or feature area
- Existing test conventions
- Available test commands

## Steps
1. Inspect how the repo currently tests the affected area.
2. Prefer targeted tests before broader suites.
3. If tests already exist, update or add tests only when necessary to validate
   the change.
4. Keep fixtures simple and deterministic.
5. Run the smallest relevant set first, then broader quality gates if needed.

## OpenClaw V4 Rule
- For V4 agent-flow work under `AgenticTeam/`, start with the smallest matching
  focused test, usually:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest -q tests/test_v4_*.py`
- For conductor/project-start changes, add the V4 dry-run team gate:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_v4_team.py --dry-run --project-root /tmp/openclaw-v4-dryrun --project-id dryrun-v4 --title "Dryrun V4" --goal "Create a small Python CLI with tests."`
- For lower-level Smith/Morpheus/Oracle end-to-end behavior, run the V4 Fibonacci conductor gate:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_test.py --project-root /home/alik/workspace/clawspace/projects/active`
- For real full-team acceptance, run the Neo-driven V4 Fibonacci gate:
  `PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python AgenticTeam/scripts/run_e2e_fibonacci_v4_neo_test.py --project-root /home/alik/workspace/clawspace/projects/active`
- Pair V4 agent-flow work with `.agents/playbooks/openclaw-canary-playbook.md`.

## Verification
- New or updated tests fail before the fix when applicable.
- Tests pass after the change.
- No flaky timing or environment assumptions are introduced.

## Notes
- Do not overfit tests to internal implementation details.
- Avoid large test rewrites unless explicitly requested.
- If a test cannot be run, record what blocked it.
