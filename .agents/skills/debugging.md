# Debugging

## Purpose
Find the root cause of a bug or failing behavior with minimal guesswork.

## Trigger
Use this skill when a defect, regression, or unexplained failure must be diagnosed.

## Inputs
- Failing symptom or error message
- Reproduction steps, if available
- Relevant logs, tests, or code paths

## Steps
1. Reproduce the problem in the smallest possible scope.
2. Identify the boundary where expected behavior diverges from actual behavior.
3. Inspect the code and recent assumptions around that boundary.
4. Form one concrete hypothesis at a time and test it.
5. Fix the root cause, not just the visible symptom.
6. Add or update a test if the bug could recur.

## Verification
- Reproduction no longer fails
- Relevant tests pass
- Nearby behavior still works as expected

## Notes
- Avoid speculative changes across multiple areas at once.
- Record durable lessons in `.agents/memory/corrections.md` when appropriate.
