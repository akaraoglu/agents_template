# Agentic Software Development Plan Template

Use this document as a lighter, agent-ready replacement for a classic
RUP-style Software Development Plan.

This template keeps the useful parts of RUP:
- clear scope
- milestones and releases
- roles and responsibilities
- risk and acceptance planning
- reporting and control

But it adapts them for a chat-first, agent-assisted software organization:
- visible role handoffs
- short loops instead of heavy phase bureaucracy
- direct DMs to specialist agents
- lightweight thread coordination instead of rigid ownership

## How To Use This Template

1. Copy this file into the project folder.
2. Replace placeholders in `UPPER_SNAKE_CASE`.
3. Keep the plan concise.
4. Update it at milestone boundaries, not after every tiny task.
5. Let detailed execution live in backlog, stories, tasks, and Zulip threads.

Recommended project location:
- `projects/PROJECT_SLUG/management/SDP.md`

---

## 0. Document Control

- Project: `PROJECT_NAME`
- Project slug: `PROJECT_SLUG`
- Owner: `PROJECT_OWNER`
- Version: `VERSION`
- Status: `draft | active | revised | archived`
- Last updated: `YYYY-MM-DD`
- Related docs:
  - `PROJECT.md`
  - `Vision / Charter`
  - `STATUS.md`
  - `BACKLOG.md`
  - `MILESTONES.md`
  - `Risk log`

## 1. Purpose

Describe why this plan exists.

Example:

> This Software Development Plan defines how `PROJECT_NAME` will be delivered,
> which roles are responsible for planning, execution, and validation, and how
> milestones, risks, quality gates, and reporting will be managed.

## 2. Scope

State what is in scope and out of scope.

### In Scope
- `IN_SCOPE_ITEM_1`
- `IN_SCOPE_ITEM_2`
- `IN_SCOPE_ITEM_3`

### Out of Scope
- `OUT_OF_SCOPE_ITEM_1`
- `OUT_OF_SCOPE_ITEM_2`

## 3. Objectives And Success Criteria

### Objectives
- `OBJECTIVE_1`
- `OBJECTIVE_2`
- `OBJECTIVE_3`

### Success Criteria
- `SUCCESS_CRITERION_1`
- `SUCCESS_CRITERION_2`
- `SUCCESS_CRITERION_3`

## 4. Assumptions And Constraints

### Assumptions
- `ASSUMPTION_1`
- `ASSUMPTION_2`

### Constraints
- `CONSTRAINT_1`
- `CONSTRAINT_2`
- `CONSTRAINT_3`

Examples:
- fixed deadline
- hardware limits
- dependency on third-party APIs
- sandbox/runtime restrictions
- staffing or budget limits

## 5. Deliverables

List what this project is expected to produce.

### Product Deliverables
- `RELEASED_PRODUCT`
- `DEPLOYMENT_ARTIFACTS`
- `TEST_SUITES`
- `CONFIGURATION_FILES`

### Documentation Deliverables
- `ARCHITECTURE_DOC`
- `SETUP_GUIDE`
- `RELEASE_NOTES`
- `OPERATIONS_NOTES`

### Internal Project Artifacts
- `BACKLOG`
- `MILESTONES`
- `TASKS`
- `RISK_LOG`
- `STATUS_REPORTS`

## 6. Organization And Roles

Define the human and agent operating structure.

### Human Leadership
- `CEO / Director`: `HUMAN_OWNER`

### Visible Agent Roles
- `Neo`: CTO, broad technical execution and technical direction
- `AgentSmith`: Head of Engineering, front-door discussion and routing
- `Niaobe`: Project Manager, project loop and delivery decisions
- `Architect`: planning, milestones, stories, acceptance criteria
- `Morpheus`: software execution manager
- `Oracle`: independent validation and QA
- `Yoda`: advisory critique and strategic second opinion

### Optional Internal Roles
- `planner`
- `coder`
- `tester`

### Responsibility Summary

| Role | Primary Responsibility | Typical Outputs |
| --- | --- | --- |
| Human Director | goals, escalation, final priorities | direction, approvals |
| Neo | direct execution, deep technical work | code, analysis, reviews |
| AgentSmith | intake, clarification, visible handoff | answers, handoffs |
| Niaobe | project loop, next-owner decisions | project decisions, status |
| Architect | planning and structure | milestones, stories, criteria |
| Morpheus | implementation loop | code changes, execution reports |
| Oracle | validation loop | pass/fail, evidence |
| Yoda | critique and reframing | risks, second opinions |

## 7. Development Model

Choose the operating model for the project.

Recommended default:
- milestone-driven
- iteration-based
- backlog-managed
- risk-first early work
- visible handoffs in Zulip

### Recommended Phases

Use lightweight phases instead of heavy RUP ceremony:
- `Discovery`
- `Planning`
- `Execution`
- `Validation`
- `Release / Closeout`

### Iteration Model

Each iteration should:
- reduce risk
- produce working progress
- keep planning and execution aligned
- end with a visible result or decision

## 8. Milestones And Releases

### Milestone Plan

| Milestone | Goal | Exit Criteria | Owner |
| --- | --- | --- | --- |
| `M1` | `MILESTONE_GOAL_1` | `EXIT_CRITERIA_1` | `OWNER_1` |
| `M2` | `MILESTONE_GOAL_2` | `EXIT_CRITERIA_2` | `OWNER_2` |
| `M3` | `MILESTONE_GOAL_3` | `EXIT_CRITERIA_3` | `OWNER_3` |

### Release Plan

| Release | Scope | Validation Gate | Target |
| --- | --- | --- | --- |
| `R1` | `RELEASE_SCOPE_1` | `VALIDATION_GATE_1` | `DATE_OR_WINDOW_1` |
| `R2` | `RELEASE_SCOPE_2` | `VALIDATION_GATE_2` | `DATE_OR_WINDOW_2` |

## 9. Backlog And Work Breakdown

Point to the real execution structure:
- epics
- stories
- tasks
- acceptance criteria

### Backlog Policy
- keep backlog prioritized
- every active story must have acceptance criteria
- every implementation task must point back to a story or milestone
- do not start execution work without a visible readiness decision

## 10. Agent Loops And Operating Rules

This is the agent-adapted part that replaces heavier process bureaucracy.

### Direct DM Rule
- all main visible roles are DM-able
- roles are defaults, not cages
- direct human instruction can override the default loop unless safety or
  coordination requires escalation

### Project Loop
1. Human or `AgentSmith` asks `Niaobe`
2. `Niaobe` decides the next role
3. `Architect`, `Morpheus`, or `Oracle` responds
4. `Niaobe` decides continue, rework, escalate, or complete

### Software Loop
1. Human, `AgentSmith`, or `Niaobe` asks `Morpheus`
2. `Morpheus` runs planner/coder/tester as needed
3. `Morpheus` reports execution result
4. `Oracle` or `Niaobe` decides the next step

### Validation Loop
1. Human, `Niaobe`, or `Morpheus` asks `Oracle`
2. `Oracle` validates against acceptance criteria
3. `Oracle` returns pass/fail plus evidence
4. `Niaobe` or the human decides accept or rework

### Advisory Loop
1. Human, `Neo`, or `AgentSmith` asks `Yoda`
2. `Yoda` critiques assumptions, scope, or risk
3. Work returns visibly to the operational role

## 11. Communication And Handoffs

Use a lightweight visible handoff format.

```text
TYPE: HANDOFF
FROM: ROLE_NAME
TO: ROLE_NAME
PROJECT: PROJECT_SLUG or n/a
SUMMARY: Why the handoff is happening
NEXT: What the target role should do next
```

### Communication Rules
- shared-topic replies happen on mention, handoff, or active exchange
- no hidden nested spawning inside agent sandboxes
- host-side gateway performs cross-agent execution
- detailed phase chatter should stay out of normal threads unless explicitly requested

## 12. Reporting Plan

Keep reporting lightweight and visible.

### Standard Status Fields
- current state
- blocker
- next action
- current owner
- current milestone

### Reporting Cadence
- per major decision
- per handoff
- per validation result
- per milestone review

### Standard Status Artifacts
- `STATUS.md`
- Zulip thread summaries
- milestone updates
- risk updates

## 13. Quality And Acceptance Plan

### Quality Gates
- planning gate
- implementation gate
- validation gate
- release gate

### Acceptance Criteria Rules
- every story must define acceptance criteria
- validation must reference those criteria
- Oracle acceptance or explicit human acceptance closes the work

### Required Validation Evidence
- test results
- screenshots or logs when relevant
- performance checks when relevant
- regression check summary

## 14. Risk Management Plan

Track risks explicitly.

| Risk | Impact | Likelihood | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| `RISK_1` | `HIGH/MED/LOW` | `HIGH/MED/LOW` | `MITIGATION_1` | `OWNER_1` |
| `RISK_2` | `HIGH/MED/LOW` | `HIGH/MED/LOW` | `MITIGATION_2` | `OWNER_2` |

### Risk Rules
- address architectural and tooling risks early
- escalate blockers visibly
- attach mitigation ownership
- revise risk severity when reality changes

## 15. Technical Process Plan

### Methods
- iterative delivery
- code review
- targeted testing
- visible handoffs

### Tools
- OpenClaw
- Zulip
- version control
- CI or local test runners
- project-specific tooling

### Infrastructure
- runtime environment
- sandbox or host execution model
- package/dependency model
- deployment targets

## 16. Change Control

### What Requires Explicit Approval
- scope increases
- milestone shifts
- release date changes
- architecture direction changes
- risky dependency or platform changes

### What Can Change Within The Team Loop
- task ordering
- local implementation details
- replanning within the current milestone

## 17. Closeout Plan

Project completion should include:
- accepted deliverables
- final validation
- release or deployment handoff
- documentation cleanup
- open follow-up items captured
- final retrospective or lessons learned

## 18. Appendix: Lightweight Starter Example

```text
Project: Plate Enhancement
Milestone: M2 - Pure NumPy validation path
Owner: Niaobe
Execution lead: Morpheus
Validation lead: Oracle
Advisor: Yoda

Current objective:
- remove SciPy dependency from validation path
- restore green integration tests

Exit criteria:
- tests pass in the current runtime
- Oracle validates acceptance criteria
- release notes updated
```

---

## Recommendation

For your setup, this document should be:
- shorter than classic RUP
- more structured than ad hoc agile notes
- centered on roles, milestones, handoffs, and acceptance

Use this as the top-level project operating plan.
Use backlog, tasks, and Zulip threads for the day-to-day execution detail.
