# Spec-Driven Development (SDD)

## Purpose

This document defines a reusable, project-agnostic way to start new software, AI, data, or systems projects before implementation begins.

The main idea is simple:

1. **Phase 1 - Initial Planning and Specification** answers **Why** the project exists and **How** it must be shaped.
2. **Phase 2 - Implementation Plan** answers **What** will be built first, in what order, and with which milestones and tasks.

This split prevents teams from jumping into implementation with unclear goals, vague scope, hidden assumptions, and incomplete validation rules. It is also a better fit for AI-assisted engineering, because AI agents fill gaps aggressively when specifications are incomplete.

## Core Principle

SDD is not just "write a plan before coding."

It means the project should start with a **spec-first package** that is specific enough to:

- guide humans and AI agents
- prevent scope drift
- expose assumptions early
- document decisions and rationale
- define how success will be verified
- create a clear readiness gate before implementation

In practice, a good SDD start combines the strengths of:

- a **project brief** for context and alignment
- a **decision log / ADR mindset** for durable choices and tradeoffs
- an **implementation plan** for milestones, task breakdown, and sequencing

## Why Use Two Phases

Many projects fail early because planning and implementation are mixed together too soon. The usual failure mode is:

- a goal is stated loosely
- implementation starts immediately
- scope expands silently
- architecture gets shaped by early code rather than by explicit decisions
- testing proves functions work, but not that the system matches intent

The two-phase model separates concerns:

- **Phase 1** makes the project legible.
- **Phase 2** makes the work executable.

If a project skips Phase 1, Phase 2 becomes guesswork.

If a project skips Phase 2, Phase 1 remains a static document with no delivery path.

## Phase 1 - Initial Planning and Specification

### Phase 1 Goal

Produce a planning package that is precise enough for a human or AI agent to understand:

- why the project exists
- what success means
- what is in and out of scope
- what cannot be changed
- what has already been decided
- how the work will be verified

### Phase 1 Output

At the end of Phase 1, the team should have:

- a core project brief or spec
- a decision log
- a visible list of open questions and risks
- a definition-of-ready gate

Implementation should remain blocked until this package is accepted.

### Phase 1 Recommended Sections

#### 1. Background and Problem Statement

Describe the context that created the project.

Capture:

- the problem or opportunity
- why now
- the business, user, research, or operational trigger
- relevant prior work or earlier attempts

Questions:

- What problem are we solving?
- Why is this worth doing now?
- What prior context must be understood first?

#### 2. Stakeholders, Owners, and Users

Clarify who matters before defining the solution.

Capture:

- sponsor or owner
- decision-maker
- primary users or operators
- reviewers and collaborators
- teams affected by the outcome

Questions:

- Who approves the work?
- Who uses the result?
- Who can block or reshape it?

#### 3. Outcomes

This is one of the most important SDD fields.

Outcomes define the concrete state that must be true when the work is successful. They should be stated as system or user results, not vague feature labels.

Capture:

- desired end state
- user-visible outcomes
- system-level outcomes
- operational outcomes
- business or technical success signals

Good examples:

- "A user can complete X without manual intervention."
- "The system emits Y output with latency under Z."
- "A training run can be reproduced from config and data manifests."

Questions:

- What must be true when the project is done?
- What should a user, operator, or system be able to do afterward?
- What would count as obvious success?

#### 4. In-Scope and Out-of-Scope Boundaries

This is another mandatory SDD field.

In-scope and out-of-scope lists prevent teams and agents from expanding work implicitly. The out-of-scope list is often as important as the in-scope list.

Capture:

- what the first version includes
- what is intentionally excluded
- what is deferred to later phases
- what related work should not be mixed into this effort

Questions:

- What exactly belongs in this project?
- What should not be touched in this phase?
- What tempting adjacent work must stay out?

#### 5. Constraints and Assumptions

This is a mandatory SDD field.

Constraints limit the solution space. Assumptions fill current knowledge gaps, but they must be written down explicitly so they can be challenged later.

Capture:

- technical constraints
- platform or environment constraints
- performance or cost limits
- compliance or security rules
- team/process constraints
- assumptions the project currently relies on

Questions:

- What must remain true for the current plan to work?
- What limits the design or implementation space?
- Which assumptions have not yet been verified?

#### 6. Existing References and Prior Art

Projects should not start from a blank slate when useful references already exist.

Capture:

- similar internal projects
- external repositories or papers
- existing design patterns
- APIs, standards, or model references
- lessons learned from earlier work

Questions:

- What should we reuse or emulate?
- Which existing project defines the baseline behavior?
- Where have similar mistakes already been solved?

#### 7. Inputs, Outputs, and Interfaces

Projects often fail because the interfaces are vague even when the goal sounds clear.

Capture:

- data inputs
- user inputs
- APIs, files, schemas, and protocols
- outputs, artifacts, or side effects
- boundaries between systems or modules

Questions:

- What goes into the system?
- What must come out?
- Which contracts must remain stable?

#### 8. Decisions Already Made

This is a mandatory SDD field.

A common early-project failure is treating already-made decisions as still open, or worse, letting tools ignore them and invent alternatives. This section should capture decisions that are settled enough to constrain future work.

Capture:

- approved architectural choices
- fixed datasets, APIs, or frameworks
- non-negotiable constraints
- accepted tradeoffs
- deferred decisions that are intentionally not settled yet

Questions:

- What has already been decided?
- Which choices are fixed for this phase?
- Which choices remain open and must not be treated as final?

#### 9. Risks and Open Questions

This section protects the team from pretending uncertainty does not exist.

Capture:

- unresolved technical questions
- business or operational risks
- dependency risks
- data or environment risks
- ambiguous requirements that still need clarification

Questions:

- What could break the plan?
- What must be clarified before implementation?
- Which unknowns deserve experiments or validation spikes?

#### 10. Verification Criteria

This is a mandatory SDD field.

Verification criteria explain how the project will prove it met the intent. This is more than "tests should pass." The criteria should connect directly to the stated outcomes.

Capture:

- acceptance criteria
- measurable thresholds
- tests, evaluations, or review gates
- expected artifacts or evidence
- edge cases or non-functional requirements that must be checked

Questions:

- How will we know the result is correct?
- What evidence proves the system meets the required outcome?
- What should fail the work even if the code runs?

#### 11. Definition of Ready

Phase 1 should end with a hard gate.

A project is ready to enter implementation only when:

- the outcomes are clear
- the scope boundaries are explicit
- the major constraints are documented
- decisions already made are recorded
- verification criteria are concrete
- the major open questions are either resolved or explicitly accepted

## Phase 2 - Implementation Plan

### Phase 2 Goal

Turn the approved Phase 1 spec into an execution plan.

If Phase 1 answers **Why** and **How the project must be shaped**, then Phase 2 answers **What will be built, in what order, and how delivery will be staged**.

Phase 2 is not where core project intent should be invented. If a major foundational issue changes during Phase 2, the team should return to Phase 1 and update the spec first.

### Phase 2 Output

At the end of Phase 2, the team should have:

- a first implementation slice
- milestone definitions
- implementation phases
- a task breakdown
- dependency sequencing
- milestone-level verification expectations

### Phase 2 Recommended Sections

#### 1. Implementation Objective

State what the first implementation effort is trying to deliver.

This should translate the Phase 1 outcome into a buildable objective without reopening the fundamental spec.

#### 2. First Thin Slice

Define the smallest end-to-end version worth building first.

A good first slice:

- exercises the main architecture path
- proves the highest-risk assumptions early
- creates a usable skeleton for later work
- stays small enough to inspect and correct quickly

#### 3. Milestones

Break the project into meaningful checkpoints.

Each milestone should represent a coherent capability, not just a vague amount of effort.

Good milestone examples:

- project skeleton and environment ready
- core data/interface path working
- baseline feature path working end-to-end
- validation path and tracking in place
- first reviewable version complete

#### 4. Implementation Phases

Group work into logical phases when a single milestone list is too flat.

Typical phase patterns:

- setup and scaffolding
- core architecture
- data or integration wiring
- feature completion
- validation and hardening
- release or handoff preparation

#### 5. Task Breakdown

Break each milestone into discrete tasks that can be reviewed, estimated, and assigned.

Good tasks are:

- small enough to complete and verify
- independent where possible
- specific about the component they affect
- connected to a milestone or acceptance point

Avoid writing implementation plans as one giant task such as "build the system."

#### 6. Dependency and Sequencing Plan

Not all tasks can run in parallel.

Capture:

- prerequisite tasks
- blocking dependencies
- tasks that can be parallelized safely
- external dependencies that need coordination

This reduces wasted work and helps the team choose the right order of execution.

#### 7. Verification by Milestone

Every milestone should say how it will be checked.

Capture:

- tests or evaluations that must pass
- artifacts that must be produced
- review criteria
- performance or correctness gates

This keeps verification connected to delivery instead of postponing it to the very end.

#### 8. Tracking and Traceability

Implementation planning should also define how execution will be tracked.

Capture:

- run or experiment tracking
- decision updates
- config or environment snapshots
- issue or task tracking style
- progress reporting rhythm

#### 9. Definition of Done by Milestone

Each milestone should have its own exit condition.

This avoids the common anti-pattern where tasks are marked complete because coding stopped, not because the result met the intended standard.

## Suggested Workflow

1. Open the project with a short brief, not code.
2. Fill Phase 1 with explicit outcomes, scope, constraints, decisions, and verification.
3. Record durable decisions and rationale as they are accepted.
4. Keep open questions visible instead of burying them inside implementation notes.
5. Approve a definition-of-ready gate before coding starts.
6. Build Phase 2 only after Phase 1 is accepted.
7. Start with the first thin slice, not the full end-state.
8. Tie each milestone to verification.
9. Update the decision log when implementation changes a durable assumption.
10. If core intent changes, return to Phase 1 before continuing.

## Common Failure Modes

- starting implementation before outcomes are clear
- treating feature names as outcomes
- failing to write an out-of-scope list
- keeping assumptions implicit
- mixing open questions with already-approved decisions
- writing an implementation plan before the spec is ready
- using tests as the only form of validation when the real requirement is architectural or operational
- letting AI or teammates fill gaps that should have been specified

## Minimal Artifact Set

For most projects, the following is enough:

1. **Spec / Project document** - the main Phase 1 artifact
2. **Decision log** - durable accepted choices and rationale
3. **Implementation plan** - Phase 2 milestones, phases, and tasks
4. **Task or milestone tracker** - execution status

These may live in one document or several files, but the responsibilities should remain distinct.

## Recommended Markdown File Set by Phase

The minimal artifact set above is the conceptual core. In day-to-day project work, it is often useful to map those artifacts to explicit markdown files so the team knows what to create and when to update it.

### Core File Set

| File | Start in | Purpose | Update when |
| --- | --- | --- | --- |
| `PROJECT.md` | Phase 1 | Main project spec or brief: background, stakeholders, outcomes, scope, constraints, interfaces, risks, verification, and definition of ready | The spec changes |
| `DECISIONS.md` or `docs/adr/` | Phase 1 | Durable accepted decisions, rationale, tradeoffs, and consequences | A durable decision is made, changed, or reversed |
| `OPEN_QUESTIONS.md` | Phase 1 (optional) | Visible unresolved questions, assumptions to validate, and blockers to readiness | Questions are added, answered, deferred, or retired |
| `IMPLEMENTATION_PLAN.md` | Phase 2 | The implementation view: first thin slice, milestones, phases, sequencing, dependencies, and milestone verification | Delivery strategy, milestones, or sequencing changes |
| `TASKS.md` | Phase 2 | Active execution tracker with task status, dependencies, and short notes | Continuously during delivery |
| `STATUS.md` or `PROGRESS.md` | During implementation (optional) | Human-readable checkpoints: done, doing, blocked, next | At a regular reporting rhythm |
| `README.md` | During implementation | Repo map, setup, run commands, and usage notes once the project becomes runnable | Workflow or setup changes |

### What to Create in Phase 1

Phase 1 should focus on the **Why** and **How** of the project. In most cases, create:

1. `PROJECT.md`
2. `DECISIONS.md` or an ADR folder
3. optionally `OPEN_QUESTIONS.md` if the uncertainty is large enough to deserve its own visible list

`PROJECT.md` should explicitly contain the mandatory SDD fields:

- outcomes
- in-scope and out-of-scope
- constraints and assumptions
- decisions already made
- verification criteria

It should also contain the supporting context:

- background
- stakeholders
- inputs, outputs, and interfaces
- risks and open questions
- definition of ready

### What to Create in Phase 2

Phase 2 should answer the **What** of delivery. Once the Phase 1 readiness gate is accepted, create:

1. `IMPLEMENTATION_PLAN.md`
2. `TASKS.md`

`IMPLEMENTATION_PLAN.md` should cover:

- first thin slice
- milestones
- implementation phases
- dependency order
- milestone-level verification

`TASKS.md` should turn the plan into discrete executable items. It is the working surface for day-to-day execution rather than the place to restate the full spec.

### What to Maintain During Implementation

Once implementation starts, the document set should be maintained with clear roles:

- update `TASKS.md` continuously as work moves
- update `DECISIONS.md` whenever a durable technical or process choice is accepted
- update `PROJECT.md` only when the underlying spec changes
- update `IMPLEMENTATION_PLAN.md` when milestone order, slicing, or sequencing changes
- update `README.md` once setup and run instructions become stable enough to share
- optionally keep `STATUS.md` or `PROGRESS.md` for periodic human-readable checkpoints

This separation matters. If every change goes into the same file, the project becomes hard to reason about. Keeping the files distinct helps preserve the line between **spec**, **decision**, **plan**, and **execution state**.

### Optional Domain-Specific Files

Some projects need a few additional files, but these should be added only when the project complexity justifies them:

- `VALIDATION.md` or `TEST_PLAN.md` for large or regulated verification requirements
- `DATA.md` for ML, analytics, or data-heavy systems
- `API_CONTRACTS.md` for integration-heavy systems
- `EXPERIMENT_LOG.md` for research or ML iteration-heavy projects

### Practical Minimum

If the team wants the smallest possible SDD document set, use these four files:

1. `PROJECT.md`
2. `DECISIONS.md`
3. `IMPLEMENTATION_PLAN.md`
4. `TASKS.md`

That is usually enough to keep the project aligned without creating document overhead too early.

## Practical Rule

Before implementation starts, every new project should produce a two-phase SDD package:

- **Phase 1 - Initial Planning and Specification**
  - outcomes
  - in-scope and out-of-scope
  - constraints and assumptions
  - decisions already made
  - verification criteria
  - supporting context, interfaces, risks, and definition of ready
- **Phase 2 - Implementation Plan**
  - first thin slice
  - milestones
  - implementation phases
  - task breakdown
  - sequencing and dependencies
  - milestone-level verification

This makes the project understandable before it becomes executable.
