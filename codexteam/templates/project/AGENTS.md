# Project Agent Rules

Read the active task handoff before acting. Start with its exact context targets.
Read `BRIEF.md`, `PROJECT.md`, `CURRENT_TASK.md`, or historical results only when
the handoff targets them or the assigned role owns planning or lifecycle state.
Expand beyond named targets only after a concrete missing dependency,
contradiction, or failing verification identifies the need, and record why.
Use the smallest relevant workflow under `.codexteam/skills/`.

`AGENTS.md` supplies common project rules to every worker. The launcher-selected role policy supplies the worker's specific Architect, Feature Planner (`feature_planner`), UX Designer (`ux_designer`), Developer, Test Engineer (`tester` protocol role), Reviewer, Documenter, Local Git Steward (`git_steward`), or Leader instructions. The complete role and skill bundle is pinned for the task attempt under ignored runtime state. Managed reference copies are under `.codexteam/roles/`; they do not override an active attempt.

## Minimal Engineering

Across design, planning, implementation, and verification, solve the exact
problem with the smallest complete change. Reuse existing mechanisms and add no
speculative feature, abstraction, role, schema, script, configuration, retry, or
control. For a nontrivial proposal, state the simplest design, unavoidable
structural changes, deliberate exclusions, and criticism before implementation.
Prefer fewer concepts and maintenance obligations—not merely fewer lines.
Contain necessary complexity behind a clear boundary and keep verification
proportional to the requested outcome and relevant regressions.

- Keep all writes inside this project root.
- Treat `BRIEF.md` as orientation; authoritative scope, handoff, evidence, and state files win on conflict.
- Do not start implementation until the project specification is approved.
- Do not claim completion without independent verification evidence.
- Developers own the configured Development Gate and normally `tests/unit/` plus `tests/smoke/`; Test Engineers use the `tester` protocol role and own the configured Integration Gate plus handoff-scoped integration/regression expectations.
- Test Engineer product defects return to the same Developer session before finalization. Test Engineers may change scoped tests but never production source or expectations merely to obtain a pass.
- Architects define requirement-traceable system and repository structure without changing source or approving their own design.
- Feature Planners may turn accepted architecture into advisory subtasks under `results/`; they do not implement, create canonical task IDs, change lifecycle state, spawn workers, or approve their own plans.
- Local Git Steward model turns are read-only. Only the deterministic executor may stage explicit Project Lead-approved paths and create one local commit at a verified boundary; all remote Git actions are prohibited.
- A worker writes the derived artifact report for Lead review; terminal text is diagnostic and no result/state transition occurs before acceptance.
- Ordinary feedback resumes the same responsible AI session and attempt.
- Only the Project Lead authorizes finalization and advances canonical management state.
- Workers report routine uncertainty to the Project Lead; only a genuine showstopper reaches the operator.
- Preserve unrelated files and document content.
- Stop when a task handoff's stop condition is reached.
- Do not repeat the same command or failure path when no relevant state changed and no new evidence was produced. Choose a materially different diagnostic or return the unresolved evidence to the Project Lead.
- For substantial discovery or deep research, preserve durable evidence-backed
  findings under this project root at
  `design/architecture/YYYY-MM-DD_descriptive_title.md`. Update an existing
  same-subject note when appropriate. Do not write project findings into the
  parent CodexTeam toolkit, another project, or a shared repository directory.
  If this project's exact root is unclear, ask the user or Project Lead before
  writing. Skip notes for routine inspection, transient diagnostics, duplicated
  documentation, or explicitly read-only work.
