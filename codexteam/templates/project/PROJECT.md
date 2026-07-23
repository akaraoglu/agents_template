# {{PROJECT_NAME}}

## Goal

{{PROJECT_GOAL}}

## Users and Operators

The operator who initialized this project and the assigned CodexTeam workers.

## MVP Scope

- Finalize observable acceptance criteria in `T001`.
- Design and approve the project architecture in `T002`.
- Implement only the approved thin slice in `T003`.
- Engineer and run the independent CI-equivalent Integration Gate in `T004`.
- Review evidence and architecture conformance in `T005`.

## Non-Goals

- Work not approved in this project specification.
- Writes outside `{{PROJECT_ROOT}}`.
- Completion based only on a worker claim.

## Requirements

- The implementation must satisfy the approved acceptance criteria.
- Every completed task must link to persisted evidence under `results/`.
- Verification must be runnable from the project root.
- The project must define a fast Development Gate and a CI-equivalent Integration Gate in `management/TEST_GATES.toml`; the Integration Gate runs the Development Gate first.

## Acceptance Criteria

- `T001` through `T005` are completed in dependency order.
- Every completed task has independently checked evidence.
- The delivered artifact and run instructions exist inside the project root.

## Constraints

- Project ID: `{{PROJECT_ID}}`
- Project root: `{{PROJECT_ROOT}}`
- Created: `{{CREATED_AT}}`
- Dependencies require operator approval before introduction.

## Architecture Notes

The accepted system structure is recorded in `ARCHITECTURE.md`; material architecture decisions use ADRs under `docs/decisions/` and accepted cross-project decisions remain in `DECISIONS.md`.

## Verification Plan

`T001` configures both project-specific gate command arrays. The Architect defines the structure in `T002`; the Developer runs the Development Gate in `T003`; the Test Engineer runs the Integration Gate in `T004`; `T005` checks architecture conformance, source, test changes, gate composition, and evidence against this document before delivery.

## Delivery Criteria

All planned tasks are completed, verification passes, and `DONE_REPORT.md` identifies the delivered files and known limitations.

## Open Questions

See `OPEN_QUESTIONS.md`.
