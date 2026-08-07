---
name: git-delivery
description: Safely prepare and perform Git delivery operations such as staging, committing, branching, pushing, and opening pull requests. Use only when the user requests or authorizes the relevant operation.
---

# Git Delivery

## Purpose

Deliver only the intended work while preserving unrelated changes and repository
history.

## Inputs

- Exact authorized Git operation and target
- Repository status, diff, branch, remotes, and recent history
- Repository commit, branch, hook, and pull-request conventions
- Verification evidence for the change set

## Workflow

1. Confirm authorization for each remote or history-changing operation.
2. Inspect status, complete diff, untracked files, current branch and upstream,
   and recent commit style.
3. Identify the exact intended change set. Exclude unrelated user changes,
   credentials, generated local state, and temporary artifacts.
4. Run or confirm required verification and hooks. Fix failures rather than
   bypassing hooks unless the user explicitly authorizes a documented exception.
5. Stage only intended paths or hunks using non-interactive commands.
6. Compose a message that follows repository conventions. If none exist:
   - use imperative mood
   - state the outcome or motivation in the subject
   - explain root cause and resolution for non-obvious fixes
   - include issue references when supplied
7. Reinspect staged diff before committing.
8. Perform only the requested commit, branch, push, or PR operation.
9. Verify resulting local and remote state and report identifiers or URLs.

## Expected Output

A coherent, verified Git change set delivered through exactly the operations the
user authorized.

## Validation

- Staged and committed files match the intended task.
- Commit or PR content matches the final diff and verification evidence.
- Branch and remote targets are correct.
- Working-tree state after delivery is understood and reported when relevant.

## Cautions

- Do not commit, amend, push, merge, rebase, cherry-pick, tag, or open a PR
  without explicit authorization.
- Do not use force push, destructive reset, skipped hooks, or history rewriting
  unless explicitly approved for the specific operation.
- Do not stage the entire repository when unrelated changes exist.
- Do not assume Conventional Commits unless repository history or policy uses it.
- Review all commits included in a PR, not only the latest local change.

## Related Guidance

- `.agents/skills/verification/SKILL.md`
- `.agents/skills/code-review/SKILL.md`
- `.agents/skills/releases/SKILL.md`
- `.agents/capabilities/boundaries.md`
