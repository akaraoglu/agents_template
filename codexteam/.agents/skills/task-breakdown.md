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
6. Split larger or materially independent work into project-specific tasks with one named responsible AI role and clear evidence.
7. Keep task IDs stable when possible.
8. Make each task independently reviewable.
9. Define expected files, checks, and acceptance evidence for each task.
10. Record dependencies explicitly.
11. Update `TASKS.md`, `management/BACKLOG.md`, and `management/tasks/T*.md`.
12. Treat each `management/tasks/T*.md` file as the contract passed to the team.

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

Each task file must include:

- Objective: one concrete outcome.
- Responsible AI: stable owner label, role, and default capability profile.
- Context: docs and files the worker must read first.
- Scope: what is included and excluded.
- Allowed paths: where the worker may edit.
- Required outputs: files or state that must exist when done.
- Verification: exact checks or evidence expected.
- Done criteria: observable completion rules.
- Stop conditions: when to stop and ask instead of guessing.
- Reporting: what evidence to write back.

The Context field defaults to `BRIEF.md`, this handoff, and a short list of named files or upstream artifacts. The Reporting field must make evidence reusable by the next role: exact commands, observed results, and safe project-relative artifact paths. Do not require a downstream role to rerun a passing check solely to recreate evidence.

## Expected Output

- Ordered task list
- Per-task goal, scope, files, verification, and done criteria
- One explicit responsible AI for every task
- Architect owns design without implementation or self-approval; one functional Developer owns a small coherent slice and Development Gate; a Test Engineer owns scoped integration/regression tests and the Integration Gate; Reviewer and optional Documenter receive separate bounded evidence responsibilities; Git Steward is boundary-only.
- Explicit blockers and dependencies
- Worker-ready task files that can be executed without chat history

## Validation

- Every acceptance criterion is covered by at least one task.
- No task requires hidden knowledge from chat only.
- No task is so broad that verification is unclear.
- Each task file has enough information for a different agent to run it safely.
- Context names the necessary files and upstream evidence instead of assigning repository-wide rediscovery.
- Both gate artifacts and Test Engineer failure classifications can flow to the Reviewer and Documenter without being translated or recreated.
- Every commit boundary names exact tasks and paths and requires current review plus Integration Gate or architecture-review evidence.
- Ordinary corrections can return to the same responsible AI without reconstructing ownership from chat.

## Common Mistakes

- Creating vague tasks like "finish app."
- Using generic role-only ownership such as "Agent" instead of a stable responsible AI label.
- Splitting by file instead of by user-visible behavior.
- Splitting one small functional slice across several Developers without an observed need.
- Asking every role to read all documents, rediscover the same files, or rerun already sufficient evidence.
- Hiding critical requirements in task descriptions only.
- Replanning without preserving useful task history.
