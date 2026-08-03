# Task Capsule Pilot Playbook

## Purpose

Run the optional task-capsule experiment without adding its checkpoint protocol
to every Developer attempt.

## When To Use

Use only when the operator explicitly approves a `TASK CAPSULE PILOT` for one
medium Developer task. Do not combine it with `PLANNED LANE` in the same attempt.

## Inputs Needed

- Canonical task ID and exact workspace
- Accepted architecture or planning evidence
- Exact source and focused-test targets
- Private capsule path and SHA-256
- Existing Lead metric binding for the task

## Workflow

1. Bind the top-level Lead session to the canonical task before capsule preparation.
2. Reuse accepted evidence and inspect only the named targets. Capsule preparation
   has a three-tool-call budget, including one `sha256sum` call for source/test hashes.
3. Write a 2-4 KB private capsule to
   `.codexteam/runtime/task-capsules/Txxx.md`. Include repository path, HEAD, file
   hashes, behavior, non-goals, exact locators, dependency direction, related tests,
   unrun verification commands, uncertainties, and one permitted focused expansion.
4. Put the capsule path, SHA-256, and `TASK CAPSULE PILOT` in the handoff.
5. Because `--skill-file` replaces the default bundle, inject all three files on
   the first draft:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --team <team> --task <task> --attempt <attempt> \
  --role developer --workspace <project> --prompt-file <handoff> \
  --skill-file .agents/skills/implementation.md \
  --skill-file .agents/skills/development-testing.md \
  --skill-file .agents/playbooks/task-capsule-pilot.md
```

6. The Developer verifies the capsule hash and every named file hash in one
   command, then uses the capsule as a map rather than authority.
7. A missing or mismatched capsule is a handoff gap. One focused expansion is
   permitted for a stale hash, missing consumer, or conflicting source contract.
8. Before exceeding 12 tool calls, after three failed calls, before a second
   broad scan, or before repeating a command without relevant changes, return:

```text
CAPSULE CHECKPOINT

Known:
Unknown:
Why another call is required:
Next bounded action:
Stop condition:
```

9. Run the normal Development Gate. Preserve independent Integration Gate ownership.
10. Compare Lead and Developer metrics: calls, failures, latency, cached and uncached
    input, command-output bytes, correction turns, and integration defects.

## Commands To Run

Use one literal `sha256sum` invocation for the capsule and all named files. Use
the normal launcher command above and configured Development Gate commands.

## Expected Output

- One private, hash-pinned capsule
- One Developer attempt with the complete explicit guidance bundle
- Normal implementation, Development Gate, and evidence outputs
- A bounded cost and reliability comparison

## Validation

- The handoff and injected guidance both say `TASK CAPSULE PILOT`.
- The capsule and named file hashes match before implementation.
- No capsule claim replaces source inspection or verification evidence.
- Lead metrics belong only to the measured canonical task.

## Common Mistakes Or Failure Modes

- Injecting only this playbook and accidentally replacing normal Developer guidance
- Combining capsule and Planned Lane checkpoint contracts
- Treating a stale capsule as authority
- Expanding discovery without naming the missing dependency
- Concluding the capsule is cheap when Lead metrics are missing or conflated

## Related Files

- `.agents/skills/implementation.md`
- `.agents/skills/development-testing.md`
- `.agents/skills/task-breakdown.md`
- `.agents/skills/subagent-orchestration.md`
- `scripts/track-lead-task.py`
