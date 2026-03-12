# Bugfix Playbook

## Goal
Resolve a defect with minimal behavioral risk.

## Preconditions
- A clear bug report, failing case, or reproduction path exists
- The affected area of the codebase is identified
- The expected behavior or acceptance criteria are known, or clarified before coding

## Steps
1. Reproduce the bug and capture the expected behavior.
2. If the reproduction, scope, or expected outcome is unclear, ask targeted questions before implementing.
3. Narrow the fault to the smallest relevant area.
4. Implement the smallest fix that addresses the root cause.
5. Add or update tests only when necessary to validate the defect.
6. Run the smallest relevant quality gates for the touched area.

## Verification
- The original reproduction succeeds or the failure is gone
- Relevant tests pass
- Adjacent behavior remains intact

## Recovery
- Revert only the isolated fix if it introduces regressions
- Document any unresolved edge cases for follow-up
