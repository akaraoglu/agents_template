# Team Brief

## Outcome

- Project: {{PROJECT_NAME}}
- Project ID: `{{PROJECT_ID}}`
- User-visible goal: {{PROJECT_GOAL}}
- Created: {{CREATED_AT}}

## Current Truth

- Phase: planning and specification
- Active task: `T001` — finalize requirements and the project skeleton
- Responsible AI: `project-lead-01` (leader)
- Last verified outcome: project workspace initialized; no product result exists yet

## Authority Order

1. `PROJECT.md` defines approved scope and acceptance criteria.
2. The active file under `management/tasks/` defines the bounded assignment.
3. The accepted result and referenced evidence prove what the worker produced.
4. `TASKS.md`, `PROJECT_STATE.md`, and `CURRENT_TASK.md` record leader-verified status.

This brief is orientation. If it conflicts with an authoritative source, report the conflict to the Project Lead.

## Team Responsibilities

- Project Lead: owns assignments, feedback, finalization permission, verification, and state transitions.
- Architect: owns requirement-traceable architecture and repository design without implementation or self-approval.
- Developer: owns scoped source, unit/algorithm and smoke tests, the Development Gate, self-review, and source revisions.
- Test Engineer (`tester` protocol role): owns integration/regression test engineering, the CI-equivalent Integration Gate, expectation integrity, and failure classification without production repairs.
- Reviewer: owns acceptance analysis and evidence-quality review without silently repairing work.
- Documenter: records verified truth and prepares operator-facing delivery material.
- Local Git Steward: prepares one verified local milestone commit only after Project Lead authorization; remote Git remains human-only.

## Working Agreement

- One responsible AI and one persistent session own each active task attempt.
- The worker returns a draft; a draft is not a `result-v1` record and does not close state.
- The Project Lead returns one consolidated feedback message per review round.
- Ordinary corrections resume the same session and attempt.
- Test Engineer product defects return through the Project Lead to the same Developer session before finalization; after correction, both gates rerun against the final revision.
- Architecture is approved before implementation and architecture conformance is reviewed before a milestone commit.
- The worker emits one final result only after the Project Lead accepts the draft.
- Independent verification is required before canonical project state advances.
- Routine uncertainty stays inside the team; only a genuine showstopper reaches the operator.

## Constraints and Current Handoff

- All writes stay inside the project root: `{{PROJECT_ROOT}}`.
- Dependencies require operator approval before introduction.
- Accepted system structure belongs in `ARCHITECTURE.md`, material architecture decisions in `docs/decisions/`, and broader project decisions in `DECISIONS.md`; detailed history belongs in task and result records.
- Next handoff: complete `management/tasks/T001.md`, obtain specification approval, then replace the generic implementation slice with project-specific, AI-owned tasks.
