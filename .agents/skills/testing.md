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

## Verification
- New or updated tests fail before the fix when applicable.
- Tests pass after the change.
- No flaky timing or environment assumptions are introduced.

## Notes
- Do not overfit tests to internal implementation details.
- Avoid large test rewrites unless explicitly requested.
- If a test cannot be run, record what blocked it.
