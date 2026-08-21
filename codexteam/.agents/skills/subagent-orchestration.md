# Subagent Orchestration Skill

## Purpose

Delegate one bounded task to a responsible AI, continue ordinary corrections in the same Codex session and logical attempt, persist one accepted `result`, and close state only after independent verification.

## When To Use

Use after the project specification is approved and the active task has a complete handoff contract.

## Inputs Needed

- Team ID and canonical task ID such as `T002`
- Logical attempt ID and responsible AI role
- Installed model profile
- Existing project workspace and task handoff
- Project Lead feedback or acceptance decision
- Independent verification command

## Small-Project Role Flow

For one coherent thin slice, keep the core identities proportional:

- Project Lead: scope, handoffs, feedback, acceptance, and state closure.
- Architect: requirement-traceable code and project structure without implementation or self-approval.
- Feature Planner (`feature_planner`): optional post-architecture decomposition for materially multi-part implementation, without implementation, canonical task creation, or self-approval.
- UX Designer (`ux_designer`): optional implementation-ready interface design and focused design QA without production implementation or product acceptance.
- One functional Developer: the entire slice, algorithm/unit and smoke tests, and the Development Gate.
- Test Engineer (`tester` protocol role): integration/regression test engineering, the CI-equivalent Integration Gate, classified defects, and reusable evidence without production repairs.
- Reviewer: acceptance analysis using both gate artifacts and the Test Engineer's named evidence, with additional inspection only for a concrete gap.
- Documenter: optional delivery text based on accepted evidence and review disposition, without repo-wide rediscovery or gratuitous test reruns.
- Local Git Steward (`git_steward`): read-only commit planning at a verified boundary; the deterministic executor alone creates one local commit.

Each role starts from its active handoff and exact context targets. The Lead and
roles that own planning or lifecycle state receive broader canonical context
only when their assignment needs it. A context-heavy handoff provides two to
five question-oriented targets with an exact file, heading, symbol, selector,
or test name and intended use; it does not assign whole upstream artifacts,
directory globs, or generic filename lists for rediscovery. Developer work
includes source and focused-test targets unless it creates them. A worker may
expand beyond named targets only after a concrete missing dependency,
contradiction, or failing verification identifies the need, and reports that
reason. Recommend medium reasoning effort for routine fast-lane turns. Increase
it only for observed complexity or risk. Preserve the full workflow for larger
projects, multiple independent slices, migrations, security-sensitive work, or
parallel Developer ownership.

## Default Routing, Not Role Ownership

| Role | Default Profile | Guidance |
|------|-----------------|----------|
| Architect | `qwen38-27b` | architecture design |
| Feature Planner (`feature_planner`) | `qwen38-27b` | post-architecture implementation decomposition |
| UX Designer (`ux_designer`) | `qwen38-27b` | UX/UI design and design QA |
| Developer | `qwen38-27b` | implementation, development testing |
| Test Engineer (`tester`) | `qwen38-27b` | integration testing and verification |
| Reviewer | `qwen38-27b` | verification and coding standards |
| Documenter | `qwen38-27b` | document editing |
| Local Git Steward (`git_steward`) | `qwen38-27b` | Git inspection and commit planning; deterministic executor mutates Git |
| Leader | `qwen38-27b` | project lead and orchestration |

The responsible role owns the task. Backend-scoped profile and reasoning are
explicit Lead selections; changing them requires a new attempt. Only curated
profiles reported by `inspect-execution-catalog.py` are supported.

Codex is the only enabled execution backend. Drafts use a supported Codex
profile and reasoning request from the execution catalog; feedback/final omit
execution selectors and reuse the pinned ExecutionSpec. OpenCode implementation
and historical records remain available for inspection, but execution is disabled.

Handoffs classify execution as `small` or `complex`. Small work defaults to 600
seconds; complex work defaults to 1200 seconds. An explicit `--timeout` overrides
the default and the effective timeout is pinned for continuation turns.

Complex Developers return `checkpoint: source_focused_tests` before running the
Development Gate. After Lead acceptance, the same session returns
`checkpoint: development_gate`. Complex Test Engineers return
`checkpoint: integration_evidence` with browser/integration evidence and their
completed report. Other complex roles return `checkpoint: final_report`. Do not
start a new attempt for these stage boundaries.

Role and AgentSpec selection never selects backend, profile, model, or reasoning.

Inject the smallest role-specific guidance bundle that covers the task. Large generic bundles increase local-model context cost and can obscure the active contract. Use one consolidated feedback message per review round.

The Task Capsule pilot is not part of the default Developer bundle. For an
explicitly approved `TASK CAPSULE PILOT`, follow
`.agents/playbooks/task-capsule-pilot.md` and inject its complete file set as
documented there. Do not expose capsule checkpoint instructions to ordinary or
Planned Lane attempts.

## Instruction Layers and Role Policies

Every worker reads the project's common `AGENTS.md`, but workers do not share one role prompt. The launcher selects exactly one strict manifest from `roles/` for responsibility, sandbox, guidance, change boundaries, evidence, and MCP ceilings. RolePolicy contains no execution defaults.

Draft backend, backend-scoped profile, and reasoning are mandatory Lead
selections from the curated execution registry.

The first draft stores `role-policy.json`, each selected skill, and `guidance-manifest.json` beside the private session. Feedback and final turns load this complete pinned bundle, not newly edited defaults. Policy and guidance digests must agree across handoff, session, turn state, and result processing. Existing attempts therefore do not acquire a newly allowed MCP server or tool mid-session.

For every worker process, the launcher explicitly disables each configured MCP server that the pinned role policy does not allow and applies any server-specific `enabled_tools` subset from that policy. Allowed and effective servers and tool subsets are reported in dry-run, session, and turn state. A named but unconfigured server is reported instead of being silently enabled. Developer, Test Engineer, Reviewer, and Git Steward receive only their bounded `codexteam-context` subsets; the browser pilot remains limited to the Test Engineer, Architect and Developer retain `local-docs`, and authenticated GitHub stays Leader-only.

For a new non-Leader attempt with `codexteam-context`, the launcher derives the
project identifier from the exact workspace and configured projects root, binds the
server process to that project, removes `project` from its exposed tool schemas, and
pins the binding in session and turn state. It fails closed when the workspace is not
a direct, symlink-free child of that root. Lead access remains unbound. A continuation
created before project binding stays unbound so a live attempt is not changed midway.

Role change patterns are a broad mechanical backstop. The handoff's Allowed Paths may be narrower and remains authoritative for assignment review. A post-turn forbidden write leaves the attempt `correction_needed`; it does not silently accept or revert the file.

## Conditional Planned Lane Pilot

Keep the Fast Lane for small tasks whose behavior, files, dependencies, and checks are explicit. Add the literal marker `PLANNED LANE` to the stable Developer prompt only when acceptance behavior is ambiguous, UI/browser behavior changes, multiple contracts are involved, dependencies or coverage are uncertain, or the change is architectural, security-sensitive, migratory, or data-integrity-sensitive.

For that lane:

1. Start the normal Developer draft in the normal writable sandbox and same logical attempt. The first response must be `PLAN <task>/<attempt>`, not an implementation `DRAFT`.
2. Inspect `turn-state.json` and the handoff-scoped diff. Reject the checkpoint if production or test files changed. The writable sandbox is retained only because the same pinned session must later implement.
3. Return one consolidated `PLAN REVISION REQUIRED` when the plan hides a dependency, broadens scope, lacks an exact Development Gate, or assigns integration ownership to the Developer.
4. When acceptable, resume the exact session with `--phase feedback` and an exact `PLAN ACCEPTED` followed by the bounded implementation instruction. This is execution authorization, not preference-only revision feedback.
5. Treat the next `DRAFT` as the implementation draft. Only then require the Development Gate and start the Test Engineer.

Do not add a new task type, agent, result schema, launcher phase, or planning document for this pilot. It remains the same-session checkpoint for one Developer assignment; the separate Feature Planner role is used earlier only when accepted design must become multiple implementation tasks. Preserve the checkpoint plan in the existing private turn history. Measure planning and implementation turns separately with their metrics sidecars; do not impose hard command or token limits during the pilot.

## Workflow

1. Read `BRIEF.md`, the active handoff, and its exact requirement sections,
   source symbols, bounded paths, and upstream evidence targets. For
   context-heavy work, route the first unresolved question through the role's
   smallest allowed context tool. Read broader management or source context
   only when planning, closing state, or resolving an observable conflict; do
   not require repo-wide rediscovery from every role.
2. Confirm dependencies and approvals, then assign exactly one responsible AI, profile, and attempt ID.
   Reuse the exact initializer project path and ID; do not manually reconstruct them. Confirm the project contract and selected handoff exist before previewing a spawn.
3. Preview and start the draft turn:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --backend codex --profile qwen36-27b --reasoning-effort medium \
  --team <team-id> \
  --task T003 --attempt att-001 --role developer \
  --workspace <project-root> --prompt-file <handoff> --dry-run
```

Run again without `--dry-run`. The launcher stores the exact Codex thread under `.codexteam/runtime/`; it must never resume with `--last`.

During execution, inspect project-local state with `./scripts/subagent-status.py <project-root>`. A stale status means the persisted running observation exceeded its timeout and grace period; inspect its named diagnostics and session before deciding on recovery. The status command never retries or terminates work.

OpenCode turns default to `--debug-stream activity`, a metadata-only ledger of
tool names, statuses, safe targets or commands,
duration, result size, truncation, model steps, and final process status. Activity
never prints file contents, command output, write/edit text, or patch bodies.
Use `--debug-stream assistant` to additionally show provider-emitted assistant
text live, or `--debug-stream off` to disable streaming. Streaming writes to the
launcher's stderr and may still
disclose project names, paths, commands, queries, or assistant text. They do not
expose private reasoning that the provider does not emit and do not replace the
complete private JSONL turn record. The option is invocation-scoped; omit it
to use the backend-aware default. Non-OpenCode backends default to off.

After each process returns, the launcher writes one private `<turn>.metrics.json` beside the JSONL. Use the WebUI for per-turn token deltas, tool/failure counts, output volume, repeats, largest-command previews, and the ten most expensive completed drafts. For historical sessions, preview `./scripts/backfill-turn-metrics.py <project-root>` before adding `--write`; do not overwrite existing sidecars unless explicitly repairing the metrics schema.

Use the opt-in `--run-guard` when a failure loop or unbounded discovery is a material
risk. It interrupts after three consecutive identical failed command results, after a
single command result exceeds 32 KiB, or when broad repository discovery follows a
successful `codexteam-context` call. Full event output remains in the private turn
JSONL; the interruption preserves a captured thread for same-attempt feedback. Resume
with a scoped command or a concrete `CONTEXT GAP`. It is not a token, time, tool-count,
or general retry limit; do not enable it merely because a task is difficult.

Before the first live draft, test the Ollama endpoint from the same execution surface; `--dry-run` validates only the command and session paths. For the default Codex backend, a reachable `workspace-write` Project Lead may add `--trust-parent-sandbox`; otherwise launch at the approved host level without it and retain the normal Codex worker sandbox. OpenCode attempts always use the approved host-level route and reject `--trust-parent-sandbox`; they have no equivalent OS sandbox. Authenticated OpenAI Codex workers also require the host-level route because their source Codex home is outside the parent writable boundary. MCP is not required. Follow `.agents/playbooks/nested-worker-sandbox.md` for Codex diagnostics and attempt rules.

For an authenticated OpenAI profile, the launcher reuses the source Codex home for authentication and keeps attempt-specific SQLite state private. It must not copy `auth.json` into the project runtime.

Use `--prompt-file` when instructions contain Markdown backticks, dollar signs, or shell metacharacters. Inline double-quoted prompts can be altered by the calling shell before the worker sees them.

Use one stable ignored prompt path per attempt, for example `<project-root>/.codexteam/lead-prompt-T003-att-001.md`. Update that file with the editing interface and pass the same literal path to feedback and final turns. This avoids near-identical temporary filenames becoming a new pathing failure.

Do not use shell redirection, `tee`, heredocs, or command substitution to create evidence. The launcher and close-loop commands persist execution evidence; use the file-editing tool for planned prompt or project files.

4. Inspect changed files and `results/reports/<TASK>-<attempt>.json`. The artifact
contains `version: 1`, summary, evidence path strings, and limitations; unknown
fields are ignored. Terminal output is diagnostic. Identity, status, changes,
process output, and timestamps are launcher-owned.

For `Context Mode: direct`, the canonical handoff must additionally declare:

```markdown
## Result Report

- `results/<task-report>/REPORT.md`

## Direct Context

- `relative/source.ext:10-80`

## Verification Commands

- `["tool", "arg"]`
```

The launcher validates and injects at most five ranges and 64 KiB, denies worker
read/search/bash tools, permits only literal role-allowed write paths, runs only
configured gate commands in a networkless read-only bubblewrap boundary, and
derives digest-pinned evidence from a report containing exactly one
`Disposition: ready_for_review` line. The Lead names
targets and checks but does not summarize source or parse command output.

Ordinary feedback is delta-only and does not replay MCP, handoff, guidance, or
direct context. Use `--feedback-mode format-only` only to repair the artifact
JSON; that mode has no tools and may modify only the derived report path.

For implementation work, require the configured Development Gate before accepting the Developer draft. Then start the Test Engineer against that draft before Developer finalization. The Test Engineer may add or modify handoff-scoped integration/regression tests and controlled expectations but never production source or Developer-owned unit/smoke tests. Return classified product defects to the same Developer session, rerun the Development Gate after correction, then resume the same Test Engineer session for affected checks and the final Integration Gate. Do not finalize either role from evidence produced before the last source revision. Finalization fails unless the latest worker turn and complete change manifest are the accepted checkpoint.

5. Return one consolidated review decision. For revision:

```text
FEEDBACK: REVISE

Accepted:
Correction required:
Reason or ground truth:
Keep unchanged:
Return: revised draft, not a final result.
```

Resume the exact session:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase feedback --team <team-id> \
  --task T003 --attempt att-001 --role developer \
  --workspace <project-root> --prompt-file <feedback-file>
```

Explain the defect and relevant truth without rewriting the worker's solution. Revision feedback must cite an observable defect such as a failed acceptance criterion, contradictory command output, missing required artifact, invalid envelope field, or unsupported status claim. Do not create a feedback round for stylistic preference or speculative improvement when the handoff is satisfied. The revised draft must state how the feedback was addressed.

If a turn returns no final message or fails, inspect the persisted `.stderr.txt` and `.jsonl` files. Resume the same exact thread when `session.json` exists; one incomplete turn is not a reason to abandon the attempt.

Read only those named diagnostics. Do not search global Codex sessions, inspect launcher implementation, add `/tmp`, or mirror the workspace. A pre-thread failure is result-free; one new attempt is justified only when the playbook changes the execution configuration materially.

6. When the draft is accepted, send:

```text
FEEDBACK: ACCEPT

Finalize the result using this attempt's actual work and evidence.
```

Run the same command with `--phase final`. For new semantic attempts this makes
no provider call: the launcher seals the accepted payload and checkpoint into
`results/T003-att-001.json`, assigning identity, `completed` status, file
changes, process metadata, and timestamp deterministically. Use
`--result-status blocked|failed|partial|needs_review` only for an intentional
non-completed closure. Historical conversational and compact-JSON attempts keep
their pinned provider final turn.

7. Validate the final result, inspect declared artifacts, and close the task with independent verification:

```bash
./scripts/verify-result.py \
  <project-root>/results/T003-att-001.json \
  --task T003 --team <team-id> --attempt att-001 --role developer \
  --expected-status completed

./scripts/close-loop.sh <project-root> --task T003 \
  --result results/T003-att-001.json -- <verification-command> <arg> ...
```

Use `jq '{status, summary, file_changes, evidence, errors, warnings, limitations}' <result>` for the concise inspection. Do not print `output.stdout_tail`, `output.stderr_tail`, the whole result, or the JSONL unless a named diagnostic requires it.

8. Confirm `BRIEF.md`, `TASKS.md`, `PROJECT_STATE.md`, `CURRENT_TASK.md`, and `RESULT.md` agree before the next assignment.

Pass evidence forward instead of recreating it: the Architect records requirement-linked design; an optional Feature Planner records accepted decomposition boundaries; the Developer records Development Gate evidence; the Test Engineer records test changes, exact Integration Gate commands, observations, classifications, and artifact paths; the Reviewer evaluates architecture, source, test changes, both gates, and expectation integrity; the optional Documenter cites accepted evidence and review disposition. A downstream role runs another command only when independence requires it or an observable evidence gap exists.

Honor the gate `execution_surface` from the handoff. Workers run only `worker` gates.
When Integration is `lead_host`, the Test Engineer prepares and classifies the checks
but requests the Project Lead to run the exact configured gate. At acceptance, create
the content-addressed gate snapshot with `--snapshot-task` and `--snapshot-attempt`;
downstream roles cite that immutable path instead of the rolling gate file.

After canonical closure, invoke Local Git Steward only when the Project Lead has named an important-task or milestone boundary. Inspect first, review an explicit commit-plan JSON, authorize that exact digest and path set, then let the deterministic executor re-run the Integration Gate against the candidate tree and create one local commit. The role and executor have no push, merge, tag, release, publication, or remote-PR authority.

Evidence reuse does not permit evidence inflation. If an artifact contains only a seven-test unit run, the Reviewer may claim only that seven-test run passed. Determinism, exact rendering, error streams, or range coverage require those observations in the artifact or a focused additional check. Artifact existence is not content verification.

## Session and Attempt Rules

- Draft, feedback, interruption recovery, and finalization normally share one thread ID and attempt ID.
- Draft and feedback turns never create result files.
- Draft evidence must not use the reserved launcher path `results/<TASK>-<attempt>.json` or leader closure path `results/<TASK>-verification.txt`; use descriptive evidence names instead.
- An invalid final response leaves the session resumable; provide contract feedback and finalize again.
- If a draft creates the reserved result path, resume with feedback so the responsible AI can move or remove it. Finalization remains blocked until the path is clear.
- Start a new attempt only after irrecoverable session loss, intentional ownership or model transfer, material scope change, or explicit abandonment.
- Use an intentional capability transfer only after focused feedback repeatedly exposes the same material mismatch. Record the old attempt as result-free, update the responsible AI and expected result path, and give the new owner a concise factual handoff.
- Ordinary test failures, review corrections, and documentation fixes are feedback, not new attempts.
- A Test Engineer product defect found before Developer finalization returns to the same Developer session. After correction, resume the same Test Engineer session and rerun affected checks plus the Integration Gate.
- A terminal blocked or failed attempt may have a final result record when the Project Lead intentionally ends it.
- Workers escalate routine uncertainty to the Project Lead. Only a genuine showstopper reaches the operator.

## Expected Output

- One persistent session per logical task attempt
- Reviewable drafts and precise feedback turns
- One schema-valid final result after acceptance
- Independently verified project state

## Validation

- Session metadata keeps the same team, task, attempt, role, profile, workspace, and exact thread ID.
- Declared changed files and evidence exist inside the workspace.
- Worker context is limited to the brief, handoff, and named files or evidence unless a concrete gap justifies expansion.
- Development and Integration Gate evidence is reused by the Reviewer and Documenter without weakening independent acceptance.
- Test Engineer changes to assertions, fixtures, or golden values cite an approved requirement, decision, or confirmed test defect.
- Independent verification passes before state advances.
- Conversation, JSONL, and stderr artifacts remain under ignored runtime storage. Handoff-scoped project edits may occur during draft and feedback, but no deterministic task result may appear before finalization.
- No write occurs outside approved roots.

## Common Mistakes

- Creating a new session for ordinary feedback
- Using `--last` when multiple agents may run
- Producing one result per conversation turn
- Using reserved final-result or leader-verification paths for draft evidence
- Treating a draft or worker `completed` claim as task closure
- Silently repairing the worker's work instead of returning actionable feedback
- Returning revision feedback for preferences that do not violate the handoff, evidence, or result contract
- Sending every role through repo-wide discovery or making it regenerate already sufficient evidence
- Changing model profile while pretending the original responsible AI continued
- Asking the operator to resolve a routine evidence mismatch
- Embedding Markdown backticks in an inline shell prompt instead of using `--prompt-file`
- Letting a worker create one-off scripts, patch files, or scratch files to work around an ordinary edit or review correction
- Advancing canonical state while the brief, milestone, or implementation-plan narrative remains stale
- Emitting local-offset timestamps or commands as evidence artifact paths in the result
- Reconstructing a similar-looking feedback filename instead of reusing the stable prompt path
- Printing complete result output tails after the validator already returned a concise success
- Running a `lead_host` gate inside a worker, or citing the rolling gate file as immutable acceptance evidence
- Repeating broad `rg --files`, `find .`, or unscoped Git discovery after a successful context MCP response
- Claiming checks that are described in a draft but absent from the accepted evidence artifact
- Finalizing a Developer before resolving a Test Engineer product defect, or accepting integration evidence produced before the last Developer revision
- Weakening an assertion or golden expectation solely to make current implementation output pass

## Related Files

- `.agents/scripts/spawn-subagent.sh`
- `roles/*.toml`
- `scripts/inspect-role-policies.py`
- `scripts/subagent-status.py`
- `scripts/manage-native-agents.py`
- `scripts/sync-project-guidance.py`
- `.agents/skills/project-lead.md`
- `.agents/skills/development-testing.md`
- `.agents/skills/integration-testing.md`
- `scripts/verify-result.py`
- `scripts/close-loop.sh`
- `schemas/handoff.json`
- `schemas/result.json`
