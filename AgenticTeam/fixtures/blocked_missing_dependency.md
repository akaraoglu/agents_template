# Project: Blocked Missing Dependency

## Goal
Exercise a deterministic blocked path for an implementation task that cannot complete without a missing dependency.

## Requirements
1. The task should require a dependency that is intentionally unavailable.
2. The worker should report the blocker exactly instead of guessing or silently stopping.

## Acceptance Criteria
1. The project reaches a blocked outcome with an exact reason.
2. No fake success artifacts are produced.

## Determinism Rules
- The missing dependency is the intended outcome.
- Do not create extra tasks or workaround logic.
