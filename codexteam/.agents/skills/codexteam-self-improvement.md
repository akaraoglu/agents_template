# CodexTeam Self-Improvement Skill

## Purpose

Turn observed team friction into the smallest verified reusable improvement without disrupting active delivery or growing an unmaintainable skill and tool library.

## When To Use

Use when the operator explicitly requests a reusable CodexTeam improvement, a severe failure exposes a durable gap, the same failure pattern recurs, existing guidance conflicts with evidence, or a repeated manual operation is risky and deterministic enough to become a tool.

Capture observations during execution, but evaluate and promote them only at a stable task or project boundary. Do not use this workflow to redesign a healthy active task, replace a persistent attempt, or compensate for weak task reasoning with an automatic control script.

## Inputs Needed

- The exact failure, delay, correction, or repeated manual operation
- Named traces, reports, commands, diffs, or verification artifacts
- The current skill, playbook, tool, or memory entry closest to the problem
- The intended roles and model profiles
- A baseline and an observable success measure
- Current project scope, attempt state, and publication authority

Use this observation shape when useful:

```text
CodexTeam improvement observation:
- Observed friction:
- Evidence:
- Severity:
- Recurring or likely to recur:
- Suggested skill, playbook, tool, or memory:
- Current task remains unchanged:
```

## Workflow

1. Preserve active execution.
   - Record the observation immediately.
   - Do not interrupt a healthy worker or change its task, owner, profile, attempt, or pinned guidance.
   - Treat an urgent safety, security, data-loss, or delivery showstopper through the existing recovery and operator-approval rules.

2. Triage the evidence.
   - Consider severity, recurrence, cross-project reuse, objective verifiability, expected time or token benefit, and maintenance cost.
   - Permit a severe and reusable one-time failure to qualify.
   - Permit `no change` when evidence or expected reuse is weak.

3. Classify the smallest durable response.

| Finding | Response |
|---|---|
| One-off fact, correction, or decision | Memory entry |
| Reusable judgment, checklist, or workflow | Update the closest skill |
| Narrow recovery or incident procedure | Update the closest playbook |
| Repeated deterministic and error-prone operation | Update or create a tool |
| Project-specific behavior | Keep it inside that project |
| Model struggles with a broad assignment | Improve future task design |
| Existing guidance already covers the case | Clarify it or take no action |

4. Search before creating.
   - Inspect the smallest relevant paths under `.agents/skills/`, `.agents/playbooks/`, `.agents/memory/`, and existing scripts.
   - Prefer a concise update over a new artifact.
   - Reject duplicate or overlapping skills and tools.

5. Prepare a candidate, not an automatic replacement.
   - Keep the change narrow and reviewable.
   - Record its originating evidence, intended trigger, affected roles or models, baseline, validation plan, and rollback.
   - Use the lifecycle `observed -> proposed -> candidate -> verified -> accepted`; record rejected candidates honestly. Later merge, deprecate, or retire accepted guidance when evidence changes.

6. Keep judgment and verification separate.
   - The Project Lead may directly make a small Markdown correction.
   - Delegate executable tools or material agent-behavior changes to a Developer and independent Test Engineer when project scope permits.
   - The proposer must not be the only verifier of a material change.
   - Use the existing Local Git Steward boundary for any authorized local commit; never infer remote publication authority.

7. Evaluate the candidate against:
   - The originating case
   - A second representative case when the claim is reusable
   - A negative case where the skill or tool should not activate
   - Existing repository regressions
   - The intended local model profile when behavior is model-dependent
   - Time, turns, tokens, or corrections when performance is the claimed benefit

8. Promote only supported claims.
   - Keep the evaluation criteria fixed during one experiment.
   - Accept only when quality remains intact and the claimed measure improves or the durable defect is removed.
   - Update the closest memory entry and user-facing guidance.
   - Do not claim that accepted guidance applies retroactively to pinned attempts.

9. Maintain library hygiene.
   - Give each skill a precise trigger, inputs, outputs, validation, failure modes, and related files.
   - Keep skills progressively disclosed instead of loading the entire library.
   - Review overlapping, stale, unused, or conflicting entries and merge, deprecate, or retire them.

## Commands To Run

Search for the closest existing artifact:

```bash
rg --files .agents scripts src tests | sort
rg -n "<problem or workflow term>" .agents scripts src tests
```

Run the smallest focused validation first, followed by the repository suite when code or shared guidance changes:

```bash
PYTHONDONTWRITEBYTECODE=1 ../env-python/bin/python -m pytest -p no:cacheprovider -q <focused-tests>
PYTHONDONTWRITEBYTECODE=1 ../env-python/bin/python -m pytest -p no:cacheprovider -q tests
git diff --check -- .
```

Use the relevant existing help, dry-run, product canary, or test-gate command when the candidate affects those surfaces. Do not introduce a new validation framework for one improvement.

## Expected Output

- An evidence-backed classification, including `no change` when appropriate
- The smallest candidate diff
- Named baseline and validation evidence
- An accept, reject, revise, deprecate, or retire decision
- A concise memory or changelog entry for an accepted durable change
- A visible final summary of guidance changes and tests

## Validation

For a skill or playbook:

- Its trigger distinguishes relevant and irrelevant work.
- It contains purpose, inputs, workflow, expected output, validation, common failures, and related files.
- A fresh lead can find it through the existing router or related-skill link.
- It does not conflict with active-session pinning, role boundaries, or operator approval gates.

For a tool:

- It has one clear purpose, safe defaults, input validation, helpful errors, `--help`, and a dry-run when it mutates state.
- It uses an existing runtime and has focused tests plus usage documentation in the related skill or playbook.
- It performs no hidden network, credential, retry, ownership, task, or publication action.

For every accepted improvement:

- The original defect or inefficiency is reproducibly addressed.
- Representative and negative cases do not expose overfitting or an over-broad trigger.
- Existing tests remain green.
- The intended model and workflow benefit is measured when the claim depends on them.
- The change can be reverted without losing project evidence.

## Common Mistakes Or Failure Modes

- Treating every observation as a permanent skill
- Using recurrence count as the only decision rule
- Letting the same agent propose, implement, verify, and approve a material change
- Publishing a skill because it sounds useful without testing its trigger
- Growing the library without merging or retiring overlapping entries
- Loading all skills into every agent and causing selection ambiguity
- Building an automatic task splitter to compensate for poor planning
- Changing evaluation criteria after seeing candidate results
- Applying new guidance retroactively to a pinned attempt
- Mixing active product delivery with parent-toolkit development
- Adding dependencies, MCP servers, databases, or frameworks without a demonstrated need

## Related Files

- `.agents/skills/project-lead.md`
- `.agents/skills/task-breakdown.md`
- `.agents/skills/subagent-orchestration.md`
- `.agents/skills/skill-template.md`
- `.agents/memory/changelog.md`
- `.agents/memory/corrections.md`
- `.agents/memory/decisions.md`
