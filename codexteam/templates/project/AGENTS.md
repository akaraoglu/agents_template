# Project Agent Rules

Read `BRIEF.md`, `PROJECT.md`, `CURRENT_TASK.md`, and the active task handoff before editing.
Use the smallest relevant workflow under `.codexteam/skills/`.

`AGENTS.md` supplies common project rules to every worker. The launcher-selected role policy supplies the worker's specific Architect, Feature Planner (`feature_planner`), UX Designer (`ux_designer`), Developer, Test Engineer (`tester` protocol role), Reviewer, Documenter, Local Git Steward (`git_steward`), or Leader instructions. The complete role and skill bundle is pinned for the task attempt under ignored runtime state. Managed reference copies are under `.codexteam/roles/`; they do not override an active attempt.

- Keep all writes inside this project root.
- Treat `BRIEF.md` as orientation; authoritative scope, handoff, evidence, and state files win on conflict.
- Do not start implementation until the project specification is approved.
- Do not claim completion without independent verification evidence.
- Developers own the configured Development Gate and normally `tests/unit/` plus `tests/smoke/`; Test Engineers use the `tester` protocol role and own the configured Integration Gate plus handoff-scoped integration/regression expectations.
- Test Engineer product defects return to the same Developer session before finalization. Test Engineers may change scoped tests but never production source or expectations merely to obtain a pass.
- Architects define requirement-traceable system and repository structure without changing source or approving their own design.
- Feature Planners may turn accepted architecture into advisory subtasks under `results/`; they do not implement, create canonical task IDs, change lifecycle state, spawn workers, or approve their own plans.
- Local Git Steward model turns are read-only. Only the deterministic executor may stage explicit Project Lead-approved paths and create one local commit at a verified boundary; all remote Git actions are prohibited.
- A worker draft is conversational output, not a `result-v1` record or a state transition.
- Ordinary feedback resumes the same responsible AI session and attempt.
- Only the Project Lead authorizes finalization and advances canonical management state.
- Workers report routine uncertainty to the Project Lead; only a genuine showstopper reaches the operator.
- Preserve unrelated files and document content.
- Stop when a task handoff's stop condition is reached.
