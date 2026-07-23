# Implementation Plan

## Objective

Deliver the approved thin slice for {{PROJECT_NAME}} and prove it meets `PROJECT.md`.

## Sequence

1. `T001`: finalize requirements and project skeleton.
2. `T002`: design and approve the code and project architecture.
3. `T003`: implement the approved thin slice and pass the Development Gate.
4. `T004`: engineer and pass the independent Integration/CI Gate.
5. `T005`: review evidence and architecture conformance.
6. `T006`: reconcile documentation when the project includes that optional task.

## Gates

- Implementation is blocked until `T001` is approved.
- Implementation is blocked until the Project Lead accepts `T002` architecture, unless T001 explicitly records that the existing architecture remains sufficient.
- T001 must configure reproducible Development and Integration Gate commands.
- The Integration Gate must invoke the Development Gate before broader checks.
- Test Engineer product defects return to the Developer before either role finalizes the affected deliverable.
- Integration verification must be performed independently of the implementation claim and may not repair production source.
- Delivery is blocked until every planned task is completed with evidence.
- A local milestone commit is blocked until the Project Lead marks the verified task group commit-ready under `management/GIT_POLICY.md`.
