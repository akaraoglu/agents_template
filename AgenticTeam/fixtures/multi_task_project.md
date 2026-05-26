# Project: Multi Task Project

## Goal
Exercise a deterministic multi-task planning flow with more than one sequential task.

## Requirements
1. The planning layer should create more than one task in a stable order.
2. Task activation must remain sequential.

## Acceptance Criteria
1. `management/PLAN.md` and `management/BACKLOG.md` describe multiple tasks.
2. `CURRENT_TASK.md` points to the first task only.

## Determinism Rules
- Keep the order stable.
- Use explicit task ids.
