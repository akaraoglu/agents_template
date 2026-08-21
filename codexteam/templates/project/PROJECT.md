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

The Project Lead maintains these criteria throughout execution. Add or refine a
criterion when implementation, testing, review, or an operator request exposes a
new required outcome or preservation boundary. Keep the criteria observable and
update the Verification Plan with each change. Only a material product or scope
decision requires operator input; the operator is not required to verify every
criterion.

- **AC-01 - Dependency-safe execution:** Planned tasks execute only after their declared dependencies are satisfied.
- **AC-02 - Independent product evidence:** Implemented product behavior has independently checked integration and review evidence.
- **AC-03 - Runnable delivery:** The delivered artifact and run instructions exist inside the project root.

## Constraints

- Project ID: `{{PROJECT_ID}}`
- Project root: `{{PROJECT_ROOT}}`
- Created: `{{CREATED_AT}}`
- Dependencies require operator approval before introduction.

## Architecture Notes

The accepted system structure is recorded in `ARCHITECTURE.md`; material architecture decisions use ADRs under `docs/decisions/` and accepted cross-project decisions remain in `DECISIONS.md`.

## Verification Plan

The Project Lead maintains this mapping as acceptance criteria and project checks
are refined during planning and execution. Each named verifier produces the
evidence for its rows; operator verification is not required unless explicitly
listed. Exact automated commands remain in `management/TEST_GATES.toml`.

| Criterion | Validation | Verifier | Expected Evidence |
|---|---|---|---|
| `AC-01` | Check declared dependencies before each task advances and audit canonical task state. | Project Lead | Synchronized `TASKS.md`, project state, and accepted upstream results. |
| `AC-02` | Run the configured Development and Integration Gates and independently audit product behavior, coverage, and freshness. | Test Engineer and Reviewer | Accepted Integration Gate snapshots and findings-first review evidence. |
| `AC-03` | Exercise the documented run procedure and inspect the delivered files. | Test Engineer | Acceptance smoke evidence and final file manifest. |

## Delivery Criteria

The Project Lead checks this delivery evidence after acceptance verification is
complete. Delivery checks do not replace the Verification Plan.

| Delivery Requirement | Validation | Responsible Role | Expected Evidence |
|---|---|---|---|
| All current applicable acceptance criteria are satisfied. | Compare every Verification Plan row with current accepted evidence. | Project Lead | Accepted gate snapshots, review disposition, and verified results. |
| Delivered files are complete and contain no unintended artifacts. | Inspect the final project manifest and relevant Git changes. | Project Lead | Recorded manifest audit with unexplained files resolved. |
| Run instructions work as documented. | Execute the documented launch or usage procedure from the project root. | Test Engineer | Acceptance smoke evidence with the exact command and observed result. |
| Delivery reporting is accurate about outputs and limitations. | Compare `DONE_REPORT.md` and delivery documentation with accepted results and evidence. | Reviewer | Findings-first delivery review with no unresolved blocking discrepancy. |

## Open Questions

See `OPEN_QUESTIONS.md`.
