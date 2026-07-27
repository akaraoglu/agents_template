# Feature Planning Skill

## Purpose

Turn an approved feature and accepted architecture into a small set of coherent,
worker-ready implementation assignments for Project Lead review.

## When To Use

Use after requirements are approved when implementation spans multiple layers,
owners, acceptance areas, or verification stages and one Developer is unlikely
to complete it as one coherent draft.

Use the Architect first when component boundaries, public contracts, data flow,
security boundaries, or technology choices remain unresolved. Do not use this
skill for a small task whose behavior, files, dependencies, and checks are
already explicit.

## Inputs Needed

- The approved feature outcome and acceptance criteria
- Accepted `ARCHITECTURE.md` or an explicit Project Lead decision that no
  architecture change is needed
- Named source, test, and integration boundaries
- Existing task dependencies and accepted upstream evidence
- Available responsible roles and model profiles

## Workflow

1. Restate the user-visible outcome and list decisions that are already frozen.
2. Identify implementation seams by behavior and dependency, not by file count.
3. Propose temporary subtask labels such as `S1`, `S2`, and `S3`. Do not assign
   canonical `Txxx` IDs; the Project Lead owns canonical task creation.
4. Give each proposed subtask one coherent outcome, one responsible role and
   profile, exact allowed paths, upstream inputs, and focused verification.
5. Keep production implementation with a Developer. Keep integration or
   regression engineering with the Test Engineer and acceptance audit with the
   Reviewer.
6. Name the integration owner and the final source revision that downstream
   verification must test.
7. Mark which subtasks are safely parallel and which must be sequential. Treat
   overlapping source paths, shared contracts, migrations, and shared test
   fixtures as sequential unless the accepted architecture proves otherwise.
8. Name existing consumers and inherited contract tests whenever a shared
   helper, representation, or public interface changes.
9. List only genuine unresolved decisions for the Project Lead. Return
   architecture uncertainty to the Architect instead of disguising it as an
   implementation task.
10. Write the advisory plan under `results/` and return it for Project Lead
    acceptance. Do not implement it or alter canonical project state.

## Commands To Run

Use read-only discovery only when the handoff names code that must be mapped:

```bash
rg -n "<contract-or-symbol>" <named-source-and-test-paths>
git diff -- <named-source-and-test-paths>
```

No command is required when the approved documents already provide sufficient
boundaries. Do not run implementation, lifecycle, task activation, agent spawn,
or Git mutation commands.

## Expected Output

One concise advisory Markdown artifact under `results/` containing:

- Feature outcome
- Frozen decisions and accepted architecture reference
- Proposed temporary subtasks with dependencies and order
- Responsible role and selected profile for each subtask
- Exact allowed paths and excluded boundaries
- Focused verification and inherited contract checks
- Integration owner and downstream evidence flow
- Parallel or sequential safety
- Decisions required from the Project Lead

The Project Lead may accept, revise, merge, or reject the proposal, then creates
or updates canonical task files.

## Validation

- Every acceptance criterion maps to at least one proposed subtask.
- Each implementation subtask has one observable outcome and one owner.
- No two parallel subtasks edit overlapping paths or the same contract.
- Source, focused verification, Integration Gate, and review ownership are
  explicit.
- Shared-helper changes name their consumers and inherited contract tests.
- The plan contains no speculative feature, new architecture, or canonical task
  ID.
- Only `results/**` changed during the Feature Planner attempt.

## Common Mistakes Or Failure Modes

- Splitting work by file instead of user-visible behavior
- Giving one Developer several independent outcomes and test domains
- Creating tiny coordination-heavy tasks that are cheaper to keep together
- Treating unresolved architecture as an implementation detail
- Assigning integration tests or acceptance approval to the Developer
- Parallelizing work that touches the same contract or source path
- Creating canonical task IDs or editing `TASKS.md` from the planner role
- Implementing the proposed plan or approving it without Project Lead review

## Related Files

- `.agents/skills/task-breakdown.md`
- `.agents/skills/project-lead.md`
- `.agents/skills/subagent-orchestration.md`
- `.agents/skills/architecture-design.md`
- `roles/feature_planner.toml`
