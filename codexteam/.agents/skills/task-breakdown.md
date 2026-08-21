# Task Breakdown Skill

## Purpose

Turn a project specification into implementation tasks that can be executed, tested, and reviewed.

## When To Use

Use after `PROJECT.md` has a concrete MVP scope and acceptance criteria, or when the operator asks to replan work.

## Inputs Needed

- `PROJECT.md`
- `IMPLEMENTATION_PLAN.md`
- `TASKS.md`
- `management/BACKLOG.md`
- `.codexteam/skills/project-doc-map.md` in the generated project
- `.codexteam/skills/document-editing.md` in the generated project
- Current code state
- Known blockers

## Workflow

1. Identify the smallest deliverable MVP path.
2. Decide whether the work is one small coherent thin slice or needs the full multi-slice workflow.
3. For a small thin slice, assign the complete functional implementation to one Developer instead of splitting parser, renderer, CLI wiring, tests, or similar parts into generic developer tasks.
4. Give each role only `BRIEF.md`, its task handoff, and the exact requirement sections, files, or upstream evidence named in that handoff. Do not use "read the repository" or "read all project documents" as context.
5. Plan an evidence chain: accepted Architect design, Developer implementation plus Development Gate, Test Engineer integration/regression changes plus Integration Gate, Reviewer audit, then accepted evidence and review disposition to an optional Documenter and boundary-only Git Steward.
   For a new or materially redesigned interface, insert one `ux_designer` handoff after requirements and architecture constraints are known. It produces the implementation-ready interface design and may return for focused design QA; it is not a mandatory task for non-UI work or routine changes with an approved design.
6. After architecture acceptance, use a bounded `feature_planner` handoff when implementation spans multiple layers or owners, several acceptance areas, focused plus host-only verification, or overlapping-path sequencing. The planner proposes temporary subtasks; the Project Lead alone accepts them and creates canonical task IDs. Send unresolved architecture back to the Architect.
7. Split larger or materially independent work into project-specific tasks with one named responsible AI role and clear evidence.
8. Keep task IDs stable when possible.
9. Make each task independently reviewable.
10. Define expected files, checks, and acceptance evidence for each task. When a
   task changes a shared helper or representation, name its existing consumers
   and inherited focused contract tests in Context and Verification even when
   those tests remain outside the task's editable paths. Preserve accepted
   upstream semantics at the shared layer; satisfy presentation-only changes at
   the presentation seam. Route the current applicable `AC-*` references from
   `PROJECT.md` into the task without copying the full criteria or Verification
   Plan. Developer tasks identify criteria they implement, Test Engineer tasks
   identify rows they independently validate, and Reviewer tasks audit criterion
   evidence plus Delivery Criteria readiness. The Project Lead maintains the
   canonical criteria and mappings as project truth evolves.
11. Record dependencies explicitly.
12. Update `TASKS.md`, `management/BACKLOG.md`, and `management/tasks/T*.md`.
13. Treat each `management/tasks/T*.md` file as the contract passed to the team.

## Small-Project Role Flow

Use this proportional sequence for one coherent, low-risk slice. Architect through Reviewer are default initialized tasks; Documenter is optional and Git Steward runs only at a named verified boundary.

| Sequence | Responsible AI | Bounded outcome | Reused input |
|----------|----------------|-----------------|--------------|
| 1 | Project Lead | Approved brief, thin-slice handoffs, and evidence expectations | Approved project goal |
| 2 | Architect | Requirement-traceable code, dependency, repository, data-flow, and test architecture | Approved requirements and existing constraints |
| 3 | Developer | Functional slice, algorithm/unit tests, smoke test, and Development Gate | Accepted architecture, implementation handoff, named source files, configured gates |
| 4 | Test Engineer (`tester`) | Integration/regression tests, CI-equivalent Integration Gate, and classified evidence | Developer draft, changed files, and Development Gate evidence |
| 5 | Reviewer | Accept/revise decision against criteria, architecture, source/test diffs, and both gates | Architect, Developer, and Test Engineer results plus named artifacts |
| 6 | Documenter, when needed | Delivery material that states verified truth | Accepted gate evidence and Reviewer disposition |
| 7 | Local Git Steward, at a boundary | One explicit local commit plan and deterministic authorized commit | Current review, gate evidence, approved paths, branch, and HEAD |

This is one evidence pipeline, not seven fresh investigations. The Git Steward does not run after every turn and does not perform remote actions. Recommend medium reasoning effort for routine assignments. Use the full workflow when the project has multiple independent slices, parallel implementation ownership, migrations, security-sensitive behavior, broad architecture changes, or evidence that the slice is not actually small.

## Task Handoff Contract

Every new task handoff must begin with this human-facing summary:

```markdown
## Short Description

- Type: Bug fix
- Summary: Fix the repository chooser placement that prevents pointer and keyboard input.
- Outcome: Users can select local repositories again without changing backend or security contracts.
```

Choose one purpose type: `Feature`, `Bug fix`, `Design`, `Architecture`,
`Planning`, `Test`, `Review`, `Documentation`, or `Delivery`. Type describes
the work, not the assigned agent role. Summary states the concrete problem or
work in one plain sentence. Outcome states the intended human-visible or project
result in one plain sentence without prescribing implementation. Do not copy the
title, include implementation minutiae, or hide scope and acceptance requirements
in this summary.

Each task file must include:

- Short Description: purpose type, concrete summary, and intended outcome.
- Objective: one concrete outcome.
- Responsible AI: stable owner label, role, and default capability profile.
- Context: concise accepted facts and the reason additional context is needed; do
  not use it as a broad reading list.
- Context Targets, for context-heavy work: question-oriented exact files and
  headings, symbols, selectors, or test names that prevent whole-artifact rediscovery.
- Scope: what is included and excluded.
- Allowed paths: where the worker may edit.
- Required outputs: files or state that must exist when done.
- Verification: exact checks or evidence expected.
- Applicable acceptance criteria: current `AC-*` references from `PROJECT.md`
  and the task's implementation, validation, or review responsibility.
- Done criteria: observable completion rules.
- Stop conditions: when to stop and ask instead of guessing.
- Reporting: what evidence to write back.

The worker already receives the handoff and common project guidance. Carry a short
accepted fact in `Context` when it prevents rereading; do not assign several whole
design, plan, task, or result artifacts there. For context-heavy work, add two to
five `Context Targets` in this form:

```markdown
## Context Targets

- Question: Which committed-content states are required?
  Target: `docs/architecture/M29.md` — `Content states and bounds`
  Use: Preserve the accepted state model while changing presentation.
- Question: Which runner boundary must remain unchanged?
  Target: `internal/git/runner.go` — `validateCatFileExact`
  Use: Keep validation behavior and its existing callers unchanged.
- Question: Which focused regression proves the boundary?
  Target: `internal/git/runner_test.go` — `TestValidateCatFileExactRejectsRange`
  Use: Extend this test only if the accepted behavior changes.
```

Every Developer handoff names at least one source target and one focused test
target unless the task explicitly creates those files. Each target states how
its answer affects the implementation. A locator must be narrow enough to use
directly; a filename alone or `results/**` is not a target. Carry accepted
decisions into the handoff when a short factual statement is enough. The
Reporting field must make evidence reusable by the next role: exact commands,
observed results, and safe project-relative artifact paths. Do not require a
downstream role to rerun a passing check solely to recreate evidence.

Task capsules are not default Developer context. Load
`.agents/playbooks/task-capsule-pilot.md` only for an explicitly approved
`TASK CAPSULE PILOT` experiment.

## Expected Output

- Ordered task list
- Per-task goal, scope, files, verification, and done criteria
- One explicit responsible AI for every task
- Architect owns design without implementation or self-approval; one functional Developer owns a small coherent slice and Development Gate; a Test Engineer owns scoped integration/regression tests and the Integration Gate; Reviewer and optional Documenter receive separate bounded evidence responsibilities; Git Steward is boundary-only.
- When applicable, UX Designer owns interface design and design QA without production implementation or product acceptance.
- When applicable, Feature Planner produces an advisory decomposition after accepted architecture; it does not implement or own canonical task creation.
- Explicit blockers and dependencies
- Worker-ready task files that can be executed without chat history

## Validation

- Every acceptance criterion is covered by at least one task.
- Every current Verification Plan row is routed to its named verifier, and
  delivery work identifies the responsible Delivery Criteria rows.
- Every new task has a specific Type, Summary, and Outcome that a human can
  understand without opening implementation details.
- No task requires hidden knowledge from chat only.
- No task is so broad that verification is unclear.
- Feature Planner proposals use temporary labels until the Project Lead accepts and converts them into canonical tasks.
- Each task file has enough information for a different agent to run it safely.
- Context states accepted facts instead of a broad reading list; Context Targets
  provide exact locators and intended use.
- Developer work names at least one source and one focused test target unless it
  explicitly creates them.
- Shared-helper tasks name inherited consumers and contract tests that must pass
  without granting later roles authority to weaken those expectations.
- Both gate artifacts and Test Engineer failure classifications can flow to the Reviewer and Documenter without being translated or recreated.
- Every commit boundary names exact tasks and paths and requires current review plus Integration Gate or architecture-review evidence.
- Ordinary corrections can return to the same responsible AI without reconstructing ownership from chat.

## Common Mistakes

- Creating vague tasks like "finish app."
- Using an agent role as the task Type or repeating the title instead of
  summarizing the work and its intended outcome.
- Using generic role-only ownership such as "Agent" instead of a stable responsible AI label.
- Splitting by file instead of by user-visible behavior.
- Splitting one small functional slice across several Developers without an observed need.
- Invoking the Feature Planner for a small explicit slice or before architecture decisions are settled.
- Asking every role to read all documents, rediscover the same files, or rerun already sufficient evidence.
- Calling a filename, directory glob, or whole results tree a bounded Context Target.
- Hiding critical requirements in task descriptions only.
- Treating a presentation requirement as permission to change an accepted
  shared projection/domain contract, or omitting that contract's focused test
  from downstream verification.
- Replanning without preserving useful task history.
