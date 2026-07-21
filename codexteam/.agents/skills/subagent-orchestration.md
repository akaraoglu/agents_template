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

## Small-Project Fast Lane

For one coherent thin slice, keep the five roles proportional:

- Project Lead: scope, handoffs, feedback, acceptance, and state closure.
- One functional Developer: the entire slice and focused developer checks.
- Tester: independent execution and reusable evidence.
- Reviewer: acceptance analysis using the Tester's named evidence, with additional inspection only for a concrete gap.
- Documenter: delivery text based on accepted evidence and review disposition, without repo-wide rediscovery or gratuitous test reruns.

Each role starts from `BRIEF.md`, its active handoff, and the exact files or upstream artifacts named there. Recommend medium reasoning effort for routine fast-lane turns. Increase it only for observed complexity or risk. Preserve the full workflow for larger projects, multiple independent slices, migrations, security-sensitive work, or parallel Developer ownership.

## Default Routing, Not Role Ownership

| Role | Default Profile | Guidance |
|------|-----------------|----------|
| Developer | `qwen36-27b` | implementation, testing |
| Tester | `qwen36-27b` | testing, verification |
| Reviewer | `qwen36-27b` | verification, coding standards |
| Documenter | `qwen36-27b` | document editing |

The responsible role owns the task. A model profile is a capability choice; changing it intentionally creates a new attempt and requires a concise handoff.
`gemma4-26b` remains available for a bounded secondary perspective, but the live E2E evidence does not support it as the default owner for tool-using audit or document-editing tasks.

`gpt54-mini` is an installed, E2E-verified cloud canary profile. The 2026-07-16 controlled Fibonacci fast-lane run completed all five roles without ownership transfer. Keep Qwen as the documented default until the operator explicitly changes routing; use the canary profile when cloud cost and data handling are acceptable.

Inject the smallest role-specific guidance bundle that covers the task. Large generic bundles increase local-model context cost and can obscure the active contract. Use one consolidated feedback message per review round.

## Workflow

1. Read `BRIEF.md`, the active handoff, and the exact requirement sections, files, and upstream artifacts named by that handoff. Read broader management or source context only when planning, closing state, or resolving an observable conflict; do not require repo-wide rediscovery from every role.
2. Confirm dependencies and approvals, then assign exactly one responsible AI, profile, and attempt ID.
   Reuse the exact initializer project path and ID; do not manually reconstruct them. Confirm the project contract and selected handoff exist before previewing a spawn.
3. Preview and start the draft turn:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --profile qwen36-27b --team <team-id> \
  --task T002 --attempt att-001 --role developer \
  --workspace <project-root> --prompt-file <handoff> --dry-run
```

Run again without `--dry-run`. The launcher stores the exact Codex thread under `.codexteam/runtime/`; it must never resume with `--last`.

Before the first live draft, test the Ollama endpoint from the same execution surface; `--dry-run` validates only the command and session paths. If Ollama is reachable inside a Codex `workspace-write` Project Lead, select a local profile and add `--trust-parent-sandbox` to draft and every resumed turn. If it is reachable only from the host, run the launcher from an approved host-level surface and omit that flag on every turn so the worker keeps its normal sandbox. Authenticated OpenAI workers also require the host-level route because their source Codex home is outside the parent writable boundary. MCP is not required. Follow `.agents/playbooks/nested-worker-sandbox.md` for diagnostics and attempt rules.

For an authenticated OpenAI profile, the launcher reuses the source Codex home for authentication and keeps attempt-specific SQLite state private. It must not copy `auth.json` into the project runtime.

Use `--prompt-file` when instructions contain Markdown backticks, dollar signs, or shell metacharacters. Inline double-quoted prompts can be altered by the calling shell before the worker sees them.

Use one stable ignored prompt path per attempt, for example `<project-root>/.codexteam/lead-prompt-T002-att-001.md`. Update that file with the editing interface and pass the same literal path to feedback and final turns. This avoids near-identical temporary filenames becoming a new pathing failure.

Do not use shell redirection, `tee`, heredocs, or command substitution to create evidence. The launcher and close-loop commands persist execution evidence; use the file-editing tool for planned prompt or project files.

4. Inspect the worker's draft and the changed files independently. A draft has this conversational shape:

```text
DRAFT T002/att-001

Outcome:
Evidence:
Uncertainties or conflicts:
Proposed disposition:
```

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
  --task T002 --attempt att-001 --role developer \
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

Run the same command with `--phase final`. This is the only normal phase that writes `results/T002-att-001.json`.

Before finalization, remind the responsible AI that:

- every required top-level field is present: `schema_version`, `result_id`, `team_id`, `task_id`, `agent_role`, `attempt_id`, `status`, `summary`, `output`, `file_changes`, `evidence`, `requested_followups`, `errors`, `warnings`, `limitations`, and `produced_at`;
- `schema_version` is exactly `"1.0"`, and `team_id`, `task_id`, `attempt_id`, and `agent_role` exactly match the handoff and launcher arguments;
- `result_id` is a non-empty stable identifier for this result and `summary` states the actual outcome rather than intent;
- `status` is one of `completed`, `failed`, `partial`, `blocked`, or `needs_review`;
- `output` includes `exit_code`, `stdout_tail`, `stderr_tail`, and non-negative `duration_seconds`;
- `file_changes`, `evidence`, `requested_followups`, `errors`, `warnings`, and `limitations` are present even when empty;
- file actions are exactly `created`, `modified`, or `deleted`;
- evidence types are exactly `test_output`, `artifact`, `file_manifest`, `cli_invocation`, `spec_compliance`, or `code_review`;
- `artifact_ref` values are safe project-relative paths, never command strings; and
- `produced_at` is actual UTC ending in `Z`.

Give the worker one task-specific evidence-object example with all required keys. Enum reminders alone are not enough for a reliable final envelope. The launcher must also verify that every declared created or modified path and every evidence `artifact_ref` exists before it seals the result and finalizes the session. A boundary-validation failure remains `correction_needed` and resumable in the same thread.

The launcher supplies a shape example containing both object forms. A completed result must follow these shapes with actual project-relative values:

```json
{
  "file_changes": [{"path": "docs/DELIVERY.md", "action": "modified"}],
  "evidence": [{
    "type": "artifact",
    "artifact_ref": "results/t005-delivery-audit.txt",
    "summary": "The delivery audit matches verified artifacts and limitations.",
    "metadata": {}
  }]
}
```

Use `[]` when there were no file changes. Never rename `action`, `stderr_tail`, or an evidence key, and never copy an example path that was not produced by the task.

7. Validate the final result, inspect declared artifacts, and close the task with independent verification:

```bash
./scripts/verify-result.py \
  <project-root>/results/T002-att-001.json \
  --task T002 --team <team-id> --attempt att-001 --role developer \
  --expected-status completed

./scripts/close-loop.sh <project-root> --task T002 \
  --result results/T002-att-001.json -- <verification-command> <arg> ...
```

Use `jq '{status, summary, file_changes, evidence, errors, warnings, limitations}' <result>` for the concise inspection. Do not print `output.stdout_tail`, `output.stderr_tail`, the whole result, or the JSONL unless a named diagnostic requires it.

8. Confirm `BRIEF.md`, `TASKS.md`, `PROJECT_STATE.md`, `CURRENT_TASK.md`, and `RESULT.md` agree before the next assignment.

For the fast lane, pass evidence forward instead of recreating it: the Tester records exact commands, observations, and artifact paths; the Reviewer evaluates those artifacts against the approved criteria; the Documenter cites the accepted evidence and review disposition. A downstream role runs another command only when independence requires it or an observable evidence gap exists.

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
- Tester evidence is reused by the Reviewer and Documenter without weakening independent acceptance.
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

## Related Files

- `.agents/scripts/spawn-subagent.sh`
- `.agents/skills/project-lead.md`
- `scripts/verify-result.py`
- `scripts/close-loop.sh`
- `schemas/handoff-v1.json`
- `schemas/result-v1.json`
