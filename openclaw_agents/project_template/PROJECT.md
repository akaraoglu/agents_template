# PROJECT.md

Keep this file factual and current. It is the **top-level project charter and
operating model** for one project.

Use it for the stable truth:
- what the project is
- why it exists
- what success looks like
- who does what
- how work should move through the system

Do **not** duplicate:
- milestone tables
- backlog contents
- daily status
- detailed task lists

Those belong in `management/`.

## Project Identity

- Project name:
- Project slug:
- Owner or lead:
- Main repository path:
- Primary runtime or deployment target:

## Project Summary

- What the project does
- Who it serves
- What problem it solves

## Goals

### Primary Goals
- `PRIMARY_GOAL_1`
- `PRIMARY_GOAL_2`

### Secondary Goals
- `SECONDARY_GOAL_1`
- `SECONDARY_GOAL_2`

## Non-Goals

- `NON_GOAL_1`
- `NON_GOAL_2`

## Current Focus

- Current main outcome:
- Current active milestone:
- Current release target:

## Scope

### In Scope
- `IN_SCOPE_1`
- `IN_SCOPE_2`

### Out Of Scope
- `OUT_OF_SCOPE_1`
- `OUT_OF_SCOPE_2`

## Constraints

- Technical constraints:
- Product or UX constraints:
- Delivery or timeline constraints:
- Security or compliance constraints:
- Runtime or tooling constraints:

## Success Criteria

- `SUCCESS_CRITERION_1`
- `SUCCESS_CRITERION_2`
- `SUCCESS_CRITERION_3`

## Deliverables

### Product Deliverables
- `DELIVERABLE_1`
- `DELIVERABLE_2`

### Documentation Deliverables
- `DOC_DELIVERABLE_1`
- `DOC_DELIVERABLE_2`

## Role Model

### Human
- Human owner / director:

### Visible Agent Roles
- `Neo`: CTO-level direct execution, deep technical work, major technical judgment
- `AgentSmith`: discussion, clarification, routing, visible handoff
- `Niaobe`: project loop, project decisions, coordination
- `Architect`: planning, stories, milestones, acceptance criteria
- `Morpheus`: software execution manager
- `Oracle`: validation and QA
- `Yoda`: critique, reframing, second opinions

## Loops And Handoffs

### Project Loop
1. Human or `AgentSmith` asks `Niaobe`
2. `Niaobe` decides the next role
3. `Architect`, `Morpheus`, or `Oracle` responds
4. `Niaobe` decides continue, rework, escalate, or complete

### Software Loop
1. Human, `Neo`, `AgentSmith`, or `Niaobe` asks `Morpheus`
2. `Morpheus` runs the software execution loop
3. `Morpheus` reports execution result
4. `Oracle`, `Niaobe`, or the human decides the next step

### Validation Loop
1. Human, `Niaobe`, `Neo`, or `Morpheus` asks `Oracle`
2. `Oracle` validates against acceptance criteria
3. `Oracle` returns pass/fail plus evidence
4. `Niaobe` or the human decides accept or rework

### Advisory Loop
1. Human, `Neo`, or `AgentSmith` asks `Yoda`
2. `Yoda` critiques assumptions, risk, or direction
3. Work returns visibly to the operational role

## Quality Gates

### Ready
- planning and scope are clear enough to execute
- acceptance criteria exist
- dependencies are known

### Done
- implementation is complete for the scoped task
- required files and docs are updated
- local checks have run as expected

### Verified
- Oracle or explicit human review accepts the result
- acceptance criteria are satisfied
- regressions are addressed or explicitly accepted

## Architecture Notes

- Important modules, services, and data flows:
- Existing patterns the agents should preserve:
- External systems or integrations that matter:
- Technical boundaries the team should not cross casually:

## Dependencies And Integrations

- External libraries:
- APIs or services:
- Runtime dependencies:
- Data dependencies:

## Key Files And Directories

- Files or directories the agents will touch most often
- Critical entrypoints
- Critical configs
- Critical test paths

## Commands

- Setup:
- Test:
- Lint:
- Typecheck:
- Run:
- Build:
- Deploy:

## Stakeholders And Communication

- Main human stakeholders:
- Preferred feedback loop:
- Main Zulip streams or threads:
- Where decisions should be recorded:

## Management File Map

Use the management files like this:

- `management/MILESTONES.md`
  - milestone plan and exit criteria
- `management/BACKLOG.md`
  - prioritized work inventory
- `management/STATUS.md`
  - current state, blockers, next actions
- `management/DECISIONS.md`
  - durable decisions
- `management/RISKS.md`
  - risk register and assumptions
- `management/stories/`
  - story definitions
- `management/tasks/`
  - concrete execution tasks

## Risks And Open Questions

- Known risks:
- Missing information:
- Decisions still pending:
