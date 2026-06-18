# Feature Playbook

## Goal
Add or change behavior intentionally while keeping the repo coherent.

## Preconditions
- The requested behavior is understood
- The relevant entry points and conventions are identified
- Acceptance criteria are known, or clarified before implementation

## Steps
1. Inspect similar features and existing patterns.
2. If multiple valid approaches exist, present 2-3 options with tradeoffs before choosing one.
3. Define the smallest useful slice of the feature.
4. Implement the change in the established architecture.
5. Add or update tests only when necessary to validate the new behavior.
6. Run the appropriate validation commands.

## Verification
- The requested behavior works as intended
- Tests cover the new path
- The implementation matches repo conventions

## Recovery
- Disable or revert the feature slice if it causes regressions
- Record follow-up work that was intentionally deferred
