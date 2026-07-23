# Project Initialization Skill

## Purpose

Initiate a real project with enough information for a team to implement it safely.

## When To Use

Use when the operator asks to create, start, initialize, or define a project.

When Codex starts in `/home/alik/workspace/agent_template/codexteam`, first read `AGENTS.md` and `.agents/LEAD_BOOT.md`. The root session remains the Project Lead throughout initialization and later execution.

## Inputs Needed

- Project name
- User goal
- Intended users or operators
- MVP scope
- Non-goals
- Constraints
- Preferred runtime or language, if any
- Verification expectation
- `.codexteam/skills/project-doc-map.md` in a generated project
- `.codexteam/skills/document-editing.md` in a generated project

## Workflow

1. Reuse facts already supplied and ask only for missing material details. Establish the aim, users, MVP scope, non-goals, constraints, acceptance criteria, verification expectation, and delivery outcome.
2. Present the proposed project description and project-management plan for approval.
3. Preview the canonical initializer from the guaranteed repository root:
   `./scripts/init-project.py "<name>" --goal "<goal>" --projects-root ./projects --dry-run`
4. After approval, run the same command without `--dry-run`.
5. Treat initialization as structure creation only. The generated task files are scaffolding, not approved implementation assignments, and no worker may be spawned yet.
6. Update `PROJECT.md` first with the approved project aim, scope, description, and acceptance criteria.
7. Then update the initialization file set:
   - `PROJECT.md`: full project contract covering goal, users/operators, MVP scope, non-goals, requirements, acceptance criteria, constraints, architecture notes, verification plan, delivery criteria, and open questions.
   - `BRIEF.md`: one-page team orientation with current truth, authority order, role ownership, and working agreement.
   - `PROJECT_STATE.md`: current phase, selected project, and implementation readiness.
   - `CURRENT_TASK.md`: current focus and next required approval.
   - `OPEN_QUESTIONS.md`: unresolved questions or explicit closure.
   - `DECISIONS.md`: accepted project decisions and cross-cutting tradeoffs.
   - `ARCHITECTURE.md`: accepted code, component, dependency, data-flow, repository, and test architecture.
   - `docs/decisions/`: material architecture decision records.
   - `IMPLEMENTATION_PLAN.md`: phase plan and gates.
   - `TASKS.md`: task table with status, owner, verification, and evidence columns.
   - `management/PLAN.md`: execution order and handoff rules.
   - `management/BACKLOG.md`: ready queue and blocked queue.
   - `management/TEST_GATES.toml`: authoritative shell-free Development and Integration Gate command arrays, verification paths, and duration expectations.
   - `management/TEST_GATES.md`: gate ownership and evidence explanation.
   - `management/GIT_POLICY.md`: exact-root, boundary, staging, and local-only commit policy.
   - `management/tasks/T001.md` through `T005.md`: default task handoff contracts; `T006` is optional documentation reconciliation.
8. Configure a fast Developer-owned Development Gate covering algorithm/unit and smoke behavior, plus a Test Engineer-owned Integration Gate that invokes the Development Gate before broader CI-equivalent checks. External CI and leader closure must use `run-test-gate.py --gate integration` or an exact wrapper.
9. Create project-specific milestones, architecture, implementation plan, and task breakdown only after the specification is testable. Replace generic scaffold wording, and give every task attempt or evidence stage one stable responsible AI label and role.
10. Stop and ask for approval before implementation or worker spawning starts. An explicit instruction such as `GO` authorizes execution.

## Expected Output

- Strong `PROJECT.md`
- A project created beneath `./projects`
- An exact standalone local Git repository with no fabricated commit or identity
- One-page `BRIEF.md` that a new agent can use without chat history
- Clear open questions or an explicit statement that none remain
- Initial task plan ready for approval
- Worker-ready task files with clear context, scope, allowed paths, outputs, verification, evidence, and stop conditions
- Configured, reproducible Development and Integration Gate commands with no `TBD` values

## Validation

- Acceptance criteria are observable and testable.
- Requirements are specific enough to implement.
- Non-goals prevent scope drift.
- Verification plan names concrete checks.
- The Integration Gate invokes the Development Gate before broader checks.
- Architect-owned design is approved before implementation when the structure is new or materially changing.
- Git boundaries are explicit and all remote actions remain human-only.
- Every task attempt or evidence stage names one responsible AI and supports same-session revision.

## Common Mistakes

- Accepting a one-line goal as a complete spec.
- Filling unknowns with generic placeholders.
- Starting implementation without user approval.
- Creating tasks that do not map to acceptance criteria.
- Passing a task to the team without enough context to execute it independently.
- Treating initializer task scaffolding as an approved implementation plan.
- Starting implementation or spawning a worker before the operator authorizes execution.
