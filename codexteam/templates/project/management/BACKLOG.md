# Backlog

## Ready Queue

- T001

## Blocked Queue

- T002 depends on approved T001 requirements and configured Development and Integration Gate commands.
- T003 depends on Project Lead acceptance of T002 architecture, or an explicit decision that the existing architecture remains sufficient.
- T004 depends on a T003 Developer draft and passing Development Gate evidence; T003 remains revisable until Test Engineer product defects are resolved.
- T005 depends on current passing Development and Integration Gate evidence from T003 and T004.

## Improvement Proposals

Applied milestone retrospective analysis appends every qualified proposal here
with its stable ID, category, scope, impact, confidence, evidence, trigger,
expected gain, validation, rollback, `Status: Proposed`, and
`Human disposition: None`. Only an explicit human
`milestone-retrospective.py decide --human-approved --apply` command may change
status to `Approved`, `Rejected`, or `Deferred`. Approval authorizes planning
only; it does not create a task, start work, change guidance or contracts, or
grant implementation authority.
