# Subagent Orchestration Skill

## Purpose

Delegate one bounded task to a responsible AI, continue ordinary corrections in the same Codex session and logical attempt, persist one accepted `result-v1`, and close state only after independent verification.

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

Each role starts from `BRIEF.md`, its active handoff, and the exact files or upstream artifacts named there. Recommend medium reasoning effort for routine fast-lane turns. Increase it only for observed complexity or risk. Preserve the full workflow for larger projects, multiple independent slices, migrations, security-sensitive work, or parallel Developer ownership.

## Default Routing, Not Role Ownership

| Role | Default Profile | Guidance |
|------|-----------------|----------|
| Architect | `qwen36-27b` | architecture design |
| Feature Planner (`feature_planner`) | `gpt54-mini` | post-architecture implementation decomposition; `qwen36-27b` is the explicit local override |
| UX Designer (`ux_designer`) | `qwen36-27b` | UX/UI design and design QA |
| Developer | `qwen36-27b` | implementation, development testing |
| Test Engineer (`tester`) | `qwen36-27b` | integration testing, verification |
| Reviewer | `qwen36-27b` | verification, coding standards |
| Documenter | `qwen36-27b` | document editing |
| Local Git Steward (`git_steward`) | `qwen36-27b` | Git inspection and commit planning; deterministic executor mutates Git |
| Leader | `qwen36-27b` | project lead and orchestration |

The responsible role owns the task. A model profile is a capability choice; changing it intentionally creates a new attempt and requires a concise handoff.
`gemma4-26b` remains available for a bounded secondary perspective, but the live E2E evidence does not support it as the default owner for tool-using audit or document-editing tasks.

`gpt54-mini` is an installed, E2E-verified cloud canary profile. The 2026-07-16 controlled Fibonacci fast-lane run completed all five roles without ownership transfer. Qwen remains the default for the established execution roles; the Feature Planner deliberately defaults to `gpt54-mini` for detailed decomposition and may be launched with `--profile qwen36-27b` when local-only processing is required.

Inject the smallest role-specific guidance bundle that covers the task. Large generic bundles increase local-model context cost and can obscure the active contract. Use one consolidated feedback message per review round.

## Instruction Layers and Role Policies

Every worker reads the project's common `AGENTS.md`, but workers do not share one role prompt. The launcher selects exactly one strict manifest from `roles/` and injects its role-specific Architect, Feature Planner (`feature_planner`), UX Designer (`ux_designer`), Developer, Test Engineer (`tester` protocol role), Reviewer, Documenter, Local Git Steward (`git_steward`), or Leader instructions. That policy also chooses the default profile, reasoning effort, sandbox mode, guidance bundle, mechanical change patterns, and permitted evidence types.

Precedence is: explicit Project Lead CLI override, pinned role-policy default, then profile configuration for settings not fixed above. `--profile` is optional for a new draft because the role supplies a default. Keep explicit overrides stable across an attempt.

The first draft stores `role-policy.json`, each selected skill, and `guidance-manifest.json` beside the private session. Feedback and final turns load this complete pinned bundle, not newly edited defaults. Policy and guidance digests must agree across handoff, session, turn state, and result processing.

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

1. Read `BRIEF.md`, the active handoff, and the exact requirement sections, files, and upstream artifacts named by that handoff. Read broader management or source context only when planning, closing state, or resolving an observable conflict; do not require repo-wide rediscovery from every role.
2. Confirm dependencies and approvals, then assign exactly one responsible AI, profile, and attempt ID.
   Reuse the exact initializer project path and ID; do not manually reconstruct them. Confirm the project contract and selected handoff exist before previewing a spawn.
3. Preview and start the draft turn:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --profile qwen36-27b --team <team-id> \
  --task T003 --attempt att-001 --role developer \
  --workspace <project-root> --prompt-file <handoff> --dry-run
```

Run again without `--dry-run`. The launcher stores the exact Codex thread under `.codexteam/runtime/`; it must never resume with `--last`.

During execution, inspect project-local state with `./scripts/subagent-status.py <project-root>`. A stale status means the persisted running observation exceeded its timeout and grace period; inspect its named diagnostics and session before deciding on recovery. The status command never retries or terminates work.

After each process returns, the launcher writes one private `<turn>.metrics.json` beside the JSONL. Use the WebUI for per-turn token deltas, tool/failure counts, output volume, repeats, largest-command previews, and the ten most expensive completed drafts. For historical sessions, preview `./scripts/backfill-turn-metrics.py <project-root>` before adding `--write`; do not overwrite existing sidecars unless explicitly repairing the metrics schema.

Before the first live draft, test the Ollama endpoint from the same execution surface; `--dry-run` validates only the command and session paths. If Ollama is reachable inside a Codex `workspace-write` Project Lead, select a local profile and add `--trust-parent-sandbox` to draft and every resumed turn. If it is reachable only from the host, run the launcher from an approved host-level surface and omit that flag on every turn so the worker keeps its normal sandbox. Authenticated OpenAI workers also require the host-level route because their source Codex home is outside the parent writable boundary. MCP is not required. Follow `.agents/playbooks/nested-worker-sandbox.md` for diagnostics and attempt rules.

For an authenticated OpenAI profile, the launcher reuses the source Codex home for authentication and keeps attempt-specific SQLite state private. It must not copy `auth.json` into the project runtime.

Use `--prompt-file` when instructions contain Markdown backticks, dollar signs, or shell metacharacters. Inline double-quoted prompts can be altered by the calling shell before the worker sees them.

Use one stable ignored prompt path per attempt, for example `<project-root>/.codexteam/lead-prompt-T003-att-001.md`. Update that file with the editing interface and pass the same literal path to feedback and final turns. This avoids near-identical temporary filenames becoming a new pathing failure.

Do not use shell redirection, `tee`, heredocs, or command substitution to create evidence. The launcher and close-loop commands persist execution evidence; use the file-editing tool for planned prompt or project files.

4. Inspect the worker's draft and the changed files independently. A draft has this conversational shape:

```text
DRAFT T003/att-001

Outcome:
Evidence:
Uncertainties or conflicts:
Proposed disposition:
```

For implementation work, require the configured Development Gate before accepting the Developer draft. Then start the Test Engineer against that draft before Developer finalization. The Test Engineer may add or modify handoff-scoped integration/regression tests and controlled expectations but never production source or Developer-owned unit/smoke tests. Return classified product defects to the same Developer session, rerun the Development Gate after correction, then resume the same Test Engineer session for affected checks and the final Integration Gate. Do not finalize either role from evidence produced before the last source revision.

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
  --phase feedback --profile qwen36-27b --team <team-id> \
  --task T003 --attempt att-001 --role developer \
  --workspace <project-root> --prompt-file <feedback-file>
```

Explain the defect and relevant truth without rewriting the worker's solution. Revision feedback must cite an observable defect such as a failed acceptance criterion, contradictory command output, missing required artifact, invalid envelope field, or unsupported status claim. Do not create a feedback round for stylistic preference or speculative improvement when the handoff is satisfied. The revised draft must state how the feedback was addressed.

If a turn returns no final message or fails, inspect the persisted `.stderr.txt` and `.jsonl` files. Resume the same exact thread when `session.json` exists; one incomplete turn is not a reason to abandon the attempt.

Read only those named diagnostics. Do not search global Codex sessions, inspect launcher implementation, add `/tmp`, or mirror the workspace. A pre-thread failure is result-free; one new attempt is justified only when the playbook changes the execution configuration materially.

6. When the draft is accepted, send:

```text
FEEDBACK: ACCEPT

Finalize result-v1 using this attempt's actual work and evidence.
```

Run the same command with `--phase final`. This is the only normal phase that writes `results/T003-att-001.json`.

Before finalization, remind the responsible AI that:

- OpenAI-backed profiles receive `schemas/result-v1.json` as the final-turn output schema, while local providers receive the compact required-field contract without an unsupported schema claim;
- `team_id`, `task_id`, `attempt_id`, and `agent_role` exactly match the handoff and launcher arguments;
- the summary, status, limitations, file changes, and evidence describe observed work rather than intent;
- every declared created or modified path and every evidence `artifact_ref` names an actual project-relative artifact; and
- commands belong in evidence metadata, never in `artifact_ref`.

The launcher fills only its stable result ID, process output, an omitted empty follow-up list for completed work, and string-normalizes message-bearing error/warning/limitation objects. It validates the returned contract, scope identity, role policy, changed paths, and evidence paths before sealing the result. A schema or boundary failure remains `correction_needed` and resumable in the same thread. Do not repeat the complete schema or a generic example object in the final prompt; task-specific truth is the useful context.

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
- Emitting local-offset timestamps or commands as evidence artifact paths in result-v1
- Reconstructing a similar-looking feedback filename instead of reusing the stable prompt path
- Printing complete result output tails after the validator already returned a concise success
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
- `schemas/handoff-v1.json`
- `schemas/result-v1.json`
