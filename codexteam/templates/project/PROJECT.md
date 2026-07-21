# {{PROJECT_NAME}}

## Goal

{{PROJECT_GOAL}}

## Users and Operators

The operator who initialized this project and the assigned CodexTeam workers.

## MVP Scope

- Finalize observable acceptance criteria in `T001`.
- Implement only the approved thin slice in `T002`.
- Verify the implementation independently in `T003`.
- Review evidence and prepare delivery in `T004`.

## Non-Goals

- Work not approved in this project specification.
- Writes outside `{{PROJECT_ROOT}}`.
- Completion based only on a worker claim.

## Requirements

- The implementation must satisfy the approved acceptance criteria.
- Every completed task must link to persisted evidence under `results/`.
- Verification must be runnable from the project root.

## Acceptance Criteria

- `T001` through `T004` are completed in dependency order.
- Every completed task has independently checked evidence.
- The delivered artifact and run instructions exist inside the project root.

## Constraints

- Project ID: `{{PROJECT_ID}}`
- Project root: `{{PROJECT_ROOT}}`
- Created: `{{CREATED_AT}}`
- Dependencies require operator approval before introduction.

## Architecture Notes

Architecture decisions are recorded in `DECISIONS.md` as they are approved.

## Verification Plan

`T003` defines and runs the project-specific verification commands. `T004` checks the evidence against this document before delivery.

## Delivery Criteria

All planned tasks are completed, verification passes, and `DONE_REPORT.md` identifies the delivered files and known limitations.

## Open Questions

See `OPEN_QUESTIONS.md`.
