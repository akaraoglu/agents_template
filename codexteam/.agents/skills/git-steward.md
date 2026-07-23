# Local Git Steward Skill

## Purpose

Prepare one coherent, verified local milestone commit without changing product content or performing remote Git operations.

## When To Use

Use only after the Project Lead marks a verified task group or milestone commit-ready. Never use after every model turn.

## Inputs Needed

- Exact standalone repository root, current branch, and expected HEAD
- Project Lead boundary authorization and approved task IDs
- Current Integration Gate or architecture-review evidence
- Repository `management/GIT_POLICY.md`
- Current status and diffs

## Workflow

1. Confirm the assigned workspace is exactly the Git top level.
2. Inspect tracked, untracked, ignored, and already staged paths.
3. Identify unrelated, generated, runtime, temporary, backup, secret-like, or oversized files.
4. Propose one explicit coherent staging group; never use an implicit all-files group.
5. Prepare a meaningful commit subject/body and a human-readable branch or PR summary.
6. Return one exact `commit-plan-v1` JSON draft for Project Lead approval without changing files, the index, refs, or HEAD.
7. The Project Lead persists the accepted JSON under ignored `.codexteam/runtime/git-steward/<boundary>/plan.json`, validates it, and explicitly authorizes its digest.
8. On final authorization, request the deterministic executor to apply exactly the approved plan.
9. Report the resulting local commit SHA and any paths intentionally left uncommitted.

## Commands To Run

Use only the repository-owned Git Steward inspection and plan commands. The deterministic executor owns staging and commit mutation. No remote command is permitted.

## Expected Output

- One exact `commit-plan-v1` JSON draft, persisted under ignored runtime only after Project Lead acceptance
- One approved local commit or a precise blocked disposition
- One `commit-record-v1` and PR summary in ignored runtime storage
- No product file modifications by the Steward

## Validation

- Repository root, branch, HEAD, authorization, and gate evidence agree.
- The committed path set exactly matches the approved plan.
- The committed tree is the verified candidate tree.
- Unrelated paths remain untouched and unstaged.
- No remote ref, tag, release, or publication action occurred.

## Common Mistakes Or Failure Modes

- Running in a parent repository instead of the assigned project repository
- Using `git add .`, `git add -A`, reset, clean, checkout, restore, or amend
- Committing stale or incomplete verification evidence
- Including runtime, secret, generated, backup, or unrelated files
- Changing the staging plan after Project Lead approval
- Writing a tracked report after the commit and leaving the boundary dirty

## Related Files

- `management/GIT_POLICY.md`
- `management/TEST_GATES.toml`
- `.agents/playbooks/milestone-commit.md`
- `scripts/git-steward.py`
