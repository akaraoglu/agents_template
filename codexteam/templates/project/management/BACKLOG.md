# Backlog

## Ready Queue

- T001

## Blocked Queue

- T002 depends on approved T001 requirements and configured Development and Integration Gate commands.
- T003 depends on Project Lead acceptance of T002 architecture, or an explicit decision that the existing architecture remains sufficient.
- T004 depends on a T003 Developer draft and passing Development Gate evidence; T003 remains revisable until Test Engineer product defects are resolved.
- T005 depends on current passing Development and Integration Gate evidence from T003 and T004.

## Improvement Proposals

Applied v2 milestone retrospective acceptance appends each validated E3
proposal here with its stable ID, category, scope, categorical impact, change
risk, change amount, reversibility, confidence, action band, evidence, concrete
mechanism, alternatives, validation, rollback, `Status: Proposed`, and `Human
disposition: None`. Observations and investigation requests may remain in a
`NO_CHANGE` retrospective and do not enter this queue. Only an explicit human
`milestone-retrospective.py decide --human-approved --apply` command may change
status to `Approved`, `Rejected`, or `Deferred`. Approval authorizes planning
only; it does not create a task, start work, change guidance or contracts, or
grant implementation authority.
