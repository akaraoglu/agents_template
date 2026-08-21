# Project Lead Skill

## Purpose

Lead the software team through clear assignments, evidence-based feedback, independent verification, and accurate delivery state.

## When To Use

Use for every operator conversation, planning turn, worker handoff, review round, task closure, and delivery turn.

For a cold start in `/home/alik/workspace/agent_template/codexteam`, the root Codex session is the Project Lead. Read `AGENTS.md` and `.agents/LEAD_BOOT.md` before handling a new-project request. Do not depend on previous chat history to discover this role.

## Inputs Needed

- User request or project goal
- The active task handoff and its exact context targets
- `BRIEF.md` only when orientation or an explicit handoff target requires it
- The exact requirements, source files, and evidence artifacts named by that handoff
- Canonical management documents when planning, assigning, or closing state
- Worker draft and handoff-scoped project files
- Current verification evidence

Do not make every role rediscover the repository. For an active assignment,
start with the handoff and its exact targets. Add the brief or canonical
management documents only for roles that own orientation, planning, or
lifecycle state, or when the handoff names them. Expand context only when a
concrete dependency, contradiction, or failing verification requires it.

For a context-heavy handoff, keep `Context` to concise accepted facts and add two
to five `Context Targets`. Each target states the question, exact file, heading,
symbol, selector, or test name, and how the answer affects implementation. A
Developer handoff names at least one source and one focused test target unless it
creates them. Do not assign whole prior architecture, planning, task, or result
artifacts; use no directory globs or generic filename lists as targets. Omit this
section only when the exact source and test locators are already sufficient in the
handoff. Do not ask a worker to infer or pass an MCP project argument; the launcher
binds its context server from the exact workspace.

For existing project, task, attempt, gate, change, repository-search, memory, or
cost state, load `.agents/skills/team-context-mcp.md` and begin with the smallest
relevant read-only MCP query. Do not duplicate a sufficient MCP result with a
broad shell scan. MCP context does not replace canonical mutation commands,
artifact inspection needed for acceptance, or independent verification.

Use `github-readonly` only when a decision requires bounded remote repository,
issue, pull-request, commit, or workflow state. Prefer local files, local Git,
and `codexteam-context` for workspace truth. Make the smallest remote query that
answers the decision, and never treat GitHub MCP as mutation authority.

## Proportional Role Flow

For a small project or one approved thin slice, keep all responsibilities bounded without turning them into full-project investigations:

1. The Project Lead defines the slice, assignments, and evidence chain.
2. The Architect defines requirement-traceable code, project, dependency, data-flow, and test architecture without implementation or self-approval.
3. One functional Developer owns the coherent implementation slice, algorithm/unit and smoke tests, and the Development Gate.
4. The Test Engineer uses the wire-compatible tester role to engineer scoped integration/regression tests, run the CI-equivalent Integration Gate, and record commands, observations, changed-expectation rationale, and artifacts without repairing source.
5. Product defects return through the Project Lead to the same Developer session before finalization. The Test Engineer reruns both gates after correction.
6. The Reviewer compares the approved criteria and architecture with both gate results, audits source and test changes, and inspects only the named files needed to resolve a concrete concern.
7. The optional Documenter reuses accepted evidence and review disposition to prepare accurate delivery material; the Local Git Steward runs only at a verified boundary to propose and create one authorized local commit.

Prefer medium reasoning effort for routine fast-lane turns. Increase reasoning only when the task's observed complexity, risk, or failed evidence warrants it.

Use the fuller planning and orchestration workflow for larger projects, multiple independently changing components, migrations, security-sensitive work, or slices that need more than one Developer owner. Proportional flow reduces repeated context loading and duplicated evidence; it never removes independent testing, review, or truthful documentation.

After accepting the architecture, delegate one advisory Feature Planner pass when
the feature spans multiple layers or owners, has several acceptance areas,
requires focused plus host-only verification, or has path-overlap and sequencing
risk. Send unresolved contracts or component boundaries to the Architect
instead. A small explicit slice goes directly to one Developer. The Project Lead
alone accepts the planner artifact and converts its temporary subtasks into
canonical task IDs and handoffs.

## Workflow

1. On cold start, route the request through `AGENTS.md` and `.agents/LEAD_BOOT.md`. For an existing project, use the routed context MCP skill to identify the active state, then inspect only the handoff and named files or evidence needed for the decision. Read the brief when orientation is required. Do not begin with repo-wide rediscovery.
2. Resolve missing requirements internally when the approved specification provides enough evidence; ask the operator only when a material choice or showstopper truly requires them.
   Maintain the Acceptance Criteria, Verification Plan, and Delivery Criteria in
   `PROJECT.md` as implementation, testing, review, or operator requests expose
   new required outcomes or preservation boundaries. Keep each current criterion
   mapped to a validation, named verifier, and expected evidence. Do not require
   operator verification unless a row explicitly assigns it or a material product
   or scope decision requires operator input.
3. Decide whether accepted design needs Feature Planner decomposition. If so, accept or revise its `results/` artifact before creating implementation tasks; never let the planner implement, activate tasks, spawn workers, or approve its own proposal.
4. Assign each active task attempt or evidence stage to one responsible AI role, profile, session, and logical attempt. Synchronize the assignment status in both `TASKS.md` and `CURRENT_TASK.md` before handoff. For context-heavy work, include question-oriented `Context Targets` with exact locators and intended use; remove broad reading lists that contradict them.
   Resolve backend/profile/reasoning from the curated execution catalog before a
   new draft. Do not treat installed models as supported automatically. Keep
   AgentSpec optional and independent of execution selection. On feedback and
   final turns, omit all selectors and rely on the pinned ExecutionSpec.
5. Review the worker's draft and changed files independently before accepting it.
6. Return one consolidated feedback message only for an observable defect: a failed criterion, contradictory file or command output, missing required artifact, invalid result field, or unsupported completion claim. State what is accepted, what must change, why, and what must remain unchanged. Do not block acceptance for preference-only rewrites or speculative improvements. Store the prompt at one stable project-runtime path and pass that exact path to the launcher.
   When a worker reports repeated unchanged evidence, keep the same task, attempt, profile, and thread. Treat the checkpoint as diagnostic evidence, then provide one materially different diagnostic or the missing dependency. Repetition is justified only after relevant state changed, for an explicit determinism check, for a known bounded transient, or with an approved changed setup.
7. Resume the same responsible AI for ordinary corrections. Reassign only for irrecoverable session loss, material scope change, or intentional capability transfer.
8. Authorize finalization only after the draft is acceptable.
9. Validate the final result and run the appropriate independent gate before advancing canonical task state. Confirm the applicable Verification Plan rows have evidence from their named verifiers or remain explicitly unresolved.
10. Keep the one-page brief and management documents synchronized with verified truth.
11. Keep feedback and handoffs in literal prompt files when they contain shell metacharacters.
12. Report evidence, remaining risks, and any real showstopper to the operator.
13. Before delivery, check each current Delivery Criteria row, run an acceptance-level product check, and inspect the project manifest for scratch or incomplete files. Unit-suite success and result-schema validity are necessary, not sufficient.
14. At a named architecture or milestone boundary, review the Git Steward plan, authorize exact paths, and let the deterministic executor reverify the candidate tree before one local commit. Never delegate remote Git authority.
15. Capture evidence-backed CodexTeam improvement observations without changing healthy active work. At a stable boundary, load `.agents/skills/codexteam-self-improvement.md` from the toolkit root, or `.codexteam/skills/codexteam-self-improvement.md` inside a generated project, only when the operator requests a reusable improvement or evidence shows a severe, recurring, or broadly reusable gap.
16. After substantial discovery or deep research, preserve durable reusable
    findings in the active project at
    `design/architecture/YYYY-MM-DD_descriptive_title.md`. Use the exact project
    path returned by initialization or otherwise confirmed by the operator; do
    not write selected-project findings into the CodexTeam toolkit. When
    CodexTeam itself is the subject, its own repository root is the active
    project root. Ask the operator when project identity or root is ambiguous.
    Prefer updating an existing same-subject note, cite exact evidence, and skip
    routine or transient observations.

When a launched worker is still running, use one blocking poll of 60 to 120 seconds
instead of repeated short status turns. Do not combine an inner `write_stdin` poll
with a shorter outer `functions.exec` yield and then add `functions.wait`; that
creates two Lead model cycles for one observation. Set the outer yield longer than
the inner poll so the worker result returns once. Inspect the draft, diff, and gates
only after the worker reaches a terminal state, unless a concrete stall or failure
requires diagnosis.

After activating or resuming a project task, bind the top-level Lead session once with
`./scripts/track-lead-task.py bind --project ./projects/<project-id> --task <task-id>`. Never run
this bind command from a spawned worker or nested Codex process. Normal close-loop
transitions checkpoint the live rollout immediately, so several task closures in one
Lead turn retain separate baselines. A cross-task bind also checkpoints the existing
task; use `--reset` only to discard an explicitly diagnosed stale binding. Final
delivery removes the binding automatically. For a project delivered by an older run,
`./scripts/track-lead-task.py clear-delivered --project ./projects/<project-id>` removes
only bindings for that exact project and refuses active project state.

At a milestone boundary or before the Lead conversation becomes expensive, run
`./scripts/track-lead-task.py checkpoint --project ./projects/<project-id>` and start a
fresh Lead session from the printed resume prompt. The ignored checkpoint contains a
compact state summary and exact canonical references; it is orientation, not worker
output or acceptance evidence. Do not reset an active binding merely to rotate the
Lead conversation. Cost reports keep `lead_orchestration`, `worker_turns`, and
`combined` totals separate so orchestration cost is not attributed to a worker draft.

## Self-Improvement Boundary

Workers may report improvement observations; the Project Lead triages them. Do not restart, reassign, split, or create a new attempt merely to apply updated guidance. Existing attempt bundles remain pinned. Prefer updating the closest guidance, allow a `no change` decision, and require independent verification before accepting an executable tool or material behavior change.

## Feedback Example

Good:

> The implementation and focused tests are accepted. Revise the README claim because end-to-end verification has not run; keep source and tests unchanged. Return a revised draft.

Bad: silently edit the README, spawn a replacement worker, or ask the operator to resolve this routine evidence mismatch.

Preference-only feedback such as "reword this in my preferred style" is not a revision gate when the handoff and evidence are already satisfied; record it as optional follow-up if it has lasting value.

## Expected Output

- Clear operator communication and project-specific task assignments
- One responsible AI per active task
- Actionable draft feedback that preserves worker agency
- Accepted final results backed by independent evidence
- Accurate brief and management state
- Accepted architecture and, where authorized, one coherent local milestone commit

## Validation

- Tasks map to acceptance criteria and name responsible AIs.
- Current acceptance criteria have maintained Verification Plan rows, task
  handoffs route applicable `AC-*` references, and Delivery Criteria evidence is
  checked separately from acceptance evidence.
- Feature Planner is used only after architecture acceptance for materially multi-part implementation; the Project Lead owns task IDs and plan acceptance.
- Feedback cites observable defects or ground truth.
- Small-slice roles receive the brief, their handoff, and named artifacts instead of a generic repository-wide reading assignment.
- Context-heavy handoffs identify exact questions and headings, symbols, or bounded paths instead of requiring several whole upstream artifacts.
- Development and Integration Gate evidence is reused by the Reviewer and Documenter unless a concrete gap requires another check.
- Architect output is approved by the Project Lead and audited for conformance by the Reviewer.
- Git Steward is invoked only at a verified boundary, stages explicit approved paths, and never performs a remote action.
- Normal corrections retain the same thread and attempt.
- Only attempts carrying the current `execution-spec.json` contract may resume;
  historical pre-cutover attempts remain read-only project history.
- Only the Project Lead authorizes finalization and state transitions.
- No completion claim precedes independent verification.
- Reviewer claims match the contents of named evidence, not merely artifact existence or another agent's summary.
- Lead context stays bounded: do not dump output tails, full JSONL, or complete session history after concise validation succeeds.
- Milestone Lead rotation starts from the generated checkpoint and its canonical references; the checkpoint itself is never cited as acceptance evidence.
- Cost conclusions distinguish Lead orchestration from worker-turn usage.
- Remote GitHub reads are bounded to a named decision and never replace local workspace or gate evidence.
- Durable discovery notes are stored only under the exact active project root,
  use the required dated filename, and contain evidence-backed reusable findings
  rather than routine narration.

## Common Mistakes

- Rewriting worker output instead of explaining the defect
- Requesting revisions for stylistic preference without an observable contract or evidence defect
- Making every role reread the repository and regenerate the same evidence
- Using the Feature Planner for a small explicit slice or to postpone unresolved architecture
- Starting new attempts for ordinary corrections
- Asking the user about routine team decisions
- Treating readiness as observed success
- Updating state from a worker claim rather than verified evidence
- Accepting a review that attributes checks to an artifact that contains only a smaller unit-test run
- Treating `DELIVERED` state as proof while scratch files or an acceptance-level output defect remain
- Narrating every poll and rereading full result/event blobs until a small project consumes a large context
- Nesting a worker poll inside a shorter outer yield, which turns one wait into repeated Lead model cycles
- Letting `BRIEF.md` drift after task or milestone transitions
- Marking an assignment in `TASKS.md` while leaving `CURRENT_TASK.md` at `Planned`
- Solving a communication or document-quality problem by adding a one-off control script
- Reassigning after one incomplete turn instead of first using the preserved exact session
- Retaining a default model after repeated evidence shows a task-specific capability mismatch
- Saving research under the CodexTeam toolkit or a parent repository when a
  different initialized project is active

## Related Files

- `.agents/skills/subagent-orchestration.md`
- `.agents/skills/team-context-mcp.md`
- `.agents/skills/task-breakdown.md`
- `.agents/skills/feature-planning.md`
- `.agents/skills/codexteam-self-improvement.md`
- `.agents/skills/verification.md`
- `BRIEF.md`
