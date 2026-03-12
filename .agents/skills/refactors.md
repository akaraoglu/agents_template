# Refactors

## Purpose
Improve structure or readability while preserving behavior.

## Trigger
Use this skill when code needs cleanup, extraction, simplification, or reorganization without changing outcomes.

## Inputs
- Target files or modules
- Known pain points
- Existing tests or safety checks

## Steps
1. Confirm the task is structural, not behavioral.
2. Establish a safety net with existing tests or targeted checks.
3. Break the refactor into small, reviewable steps.
4. Preserve interfaces unless the task explicitly allows broader change.
5. Remove duplication and dead paths only when confidence is high.

## Verification
- Existing behavior remains unchanged
- Relevant tests pass
- The resulting structure is simpler than before

## Notes
- Do not mix feature work into a refactor unless explicitly requested.
- Prefer clarity over clever abstractions.
