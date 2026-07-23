# Milestone Commit Playbook

Use only after the Project Lead marks a milestone commit-ready.

1. Confirm the exact standalone repository root, branch, and HEAD.
2. Confirm the accepted task set and current gate or architecture-review record.
3. Inspect all status categories and reject unexplained staged changes.
4. Have the read-only Git Steward return one exact `commit-plan-v1` JSON draft with staging paths, exclusions, commit message, and PR summary.
5. Wait for Project Lead approval, then persist that unchanged JSON under ignored `.codexteam/runtime/git-steward/<boundary>/plan.json`.
6. Preview and explicitly apply authorization for the exact plan digest.
7. Let the deterministic Git Steward executor verify the candidate tree and create one local commit only after commit preview and explicit apply.
8. Confirm the commit SHA, committed paths, and intentionally uncommitted paths.

Never push, open a remote pull request, merge, tag, release, publish, rewrite history, or delete unrelated files.
