# Implementation Skill

## Purpose

Implement a bounded project change safely, verify it, and revise it in response to Project Lead feedback.

## When To Use

Use when assigned responsibility for source, related tests, scoped technical documentation, scripts, or configuration.

## Inputs Needed

- Current task handoff and acceptance criteria
- Existing source and tests
- Project constraints and accepted decisions
- Verification command
- Project Lead feedback for revision turns

## Planned Lane Pilot

Use this only when the handoff explicitly contains `PLANNED LANE`. The first turn is a planning checkpoint, not an implementation draft:

1. Inspect the handoff and only its named source, test, design, and evidence files.
2. Do not edit files or run builds, tests, formatters, generators, or other commands likely to write.
3. Identify observed behavior, exact likely change paths, contracts, dependencies, uncertainties, Developer-owned tests, the targeted browser smoke when needed, Development Gate commands, and stop conditions.
4. Return:

```text
PLAN Txxx/att-xxx

Behavior and non-goals:
Files and contracts:
Dependencies and uncertainties:
Implementation sequence:
Developer-owned tests:
Browser smoke:
Development Gate:
Stop conditions:
```

Wait for the Project Lead's exact `PLAN ACCEPTED`. Then resume this same session, revise the plan when new code evidence requires it, report any material scope expansion, and follow the normal workflow below. A plan is a reviewed hypothesis, not permission to conceal a newly discovered dependency.

## Workflow

1. The selected skills are already injected and pinned in the attempt guidance bundle.
   Do not search the project or personal memory for another copy unless the handoff names
   a different project-local instruction as task context.
2. Restate the bounded outcome before editing. Treat discovery as context-heavy when
   dependencies, concurrent work, likely paths, or gate state are unclear; the shared
   worktree needs change triage; or a required symbol must be found across the repository.
3. For context-heavy discovery, start with the one smallest `codexteam-context` call:
   `get_task_context` for handoff/dependency boundaries, `search_repository` for a concrete
   source or accepted-artifact question, `get_change_summary` for shared-worktree triage,
   or `get_gate_status` for gate configuration or freshness. Skip MCP only when the
   handoff gives sufficient exact sections or symbols for a smaller direct read. The
   launcher has already bound this server to the workspace, so its tools omit `project`;
   do not infer or supply that argument.
4. Treat the handoff's `Context Targets` as the discovery plan. Read only their exact
   paths and headings, symbols, selectors, or test names. Do not search personal memory,
   enumerate the repository or `results/**`, or reopen whole upstream artifacts when
   those targets answer the question. Do not duplicate a sufficient MCP result with
   broad `rg`, `find`, tree, status, or whole-file output.
5. If an exact target is missing, stale, contradictory, or exposes a real dependency,
   allow one focused expansion. Before more than six pre-edit tool or command calls,
   return this single soft checkpoint instead of continuing broad discovery:

```text
CONTEXT GAP

Known:
Missing fact or dependency:
Why the named targets are insufficient:
Next bounded read:
Stop condition:
```

   This is not a task limit and does not count implementation, formatting, or
   verification calls. Do not use a checkpoint contract from another pilot.
6. Read the named source and test targets before editing.
7. Keep changes inside the project root and within the handoff's allowed paths.
8. Make the smallest coherent implementation that satisfies the task.
9. Prefer the standard library and established project patterns.
10. Add or update Developer-owned algorithm/unit, changed-area regression, and smoke tests when needed.
11. Run focused task checks and self-review the diff. The launcher runs the configured Development Gate after validating the draft. Do not claim integration acceptance.
12. Return a draft describing the outcome, exact evidence, uncertainties, and proposed disposition.
13. On feedback, preserve accepted work and change only the rejected part.
14. Update only scoped technical documentation. Propose status to the Project Lead; do not close canonical task state.

When `local-docs` is available and implementation depends on an indexed
installed library or CodexTeam contract, start with one narrow `search_docs`
call and a limit of at most five. Do not guess source IDs; omit the filter when
the exact indexed ID is unknown, and call `list_doc_sources` only when an exact
source or version filter is required. Use `read_doc` only for the winning
locator. The index is reference evidence, not proof of current product
behavior; verify the implementation with the normal Development Gate.

## Communication Example

Good: “Draft: the Fibonacci renderer and focused tests changed; 8 tests pass. CLI integration has not yet been independently verified.”

Bad: mark `TASKS.md` complete or claim delivery after running only local unit tests.

## Expected Output

- Source changes scoped to the current task
- Focused algorithm/unit and smoke checks plus Development Gate evidence
- A reviewable draft and, after acceptance, one accurate final result

## Validation

- Changed files are relevant and inside allowed paths.
- Tests pass or failures are reported with exact output.
- Accepted code is not churned during revisions.
- No secrets, generated caches, unrelated artifacts, or false state transitions are added.

## Common Mistakes

- Editing before reading
- Broad refactors during a bounded task
- Searching personal memory or enumerating broad result/repository paths after sufficient context routing
- Returning a checkpoint contract that was not injected for this attempt
- Hiding failed checks
- Replacing accepted work while addressing narrow feedback
- Treating a developer draft as independently verified completion
- Creating a one-off helper script for a correction that can be made directly and reviewed plainly

## Related Files

- `.agents/skills/development-testing.md`
- `.agents/skills/subagent-orchestration.md`
- `.agents/playbooks/task-capsule-pilot.md` for explicitly injected capsule experiments only
- Active file under `management/tasks/`
