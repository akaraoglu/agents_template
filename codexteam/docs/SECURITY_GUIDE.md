# Security Guide

## Filesystem

- Reject absolute paths, traversal, backslashes, malformed relative paths, and symlink escapes.
- Resolve every result and deliverable beneath the assigned project root.
- Keep generated projects outside the repository by default.
- Use atomic replacement for task, state, result, and report files.

## Processes

- Construct Codex and verification commands as argument arrays.
- Never use `eval`, `shell=True`, or agent-generated shell text.
- Run subagents in a new process session and terminate the process group on timeout.
- Use a temporary `CODEX_HOME` with mode `0700` and copy only local profile/config/catalog files.
- Snapshot the workspace before and after each worker turn and reject paths outside the selected role's mechanical change boundary.
- Execute gate commands only as validated argument arrays from `management/TEST_GATES.toml`; never pass configured text through a shell.

## Models

- Require an installed, explicitly named profile.
- Use `qwen36-27b` as the default for established implementation, testing, review, and documentation roles. Feature Planner deliberately defaults to authenticated `gpt54-mini`; use the explicit `qwen36-27b` override when planning must remain local. Treat `gemma4-26b` as an optional bounded secondary perspective, not a default owner for evidence-producing or editing work.
- Model output is untrusted until result validation and independent verification pass.
- Test Engineer expectation changes are also untrusted: each changed assertion, fixture expectation, or golden value must cite approved project truth or a confirmed test defect, and the Reviewer audits the test diff.
- Treat canonical role manifests and selected skill files as validated input and pin their normalized SHA-256 snapshots per logical attempt.
- Native-agent and project-guidance installers preview by default and refuse symlinks or unmanaged file collisions.

## State

- Workers cannot complete tasks directly.
- Completed results require evidence.
- Closure fails if declared artifacts are absent or verification fails.
- Repeated closure is idempotent unless the operator explicitly uses `--force`.
- `turn-state.json` exposes running and stale observations but grants no retry, kill, or closure authority.
- External CI and leader closure use the same configured Integration Gate or an exact wrapper; a narrower ad hoc pass cannot replace it.

## Git

- Require the assigned project to be the exact Git top level; never fall back to a parent repository.
- Keep Git Steward model sessions read-only. The deterministic executor stages only authorized literal paths and blocks pre-existing staged changes, detached HEAD, stale evidence, changed HEAD, unsafe files, active hooks, and missing identity.
- Re-run the Integration Gate against the candidate tree before a code milestone commit.
- Preview authorization and commit by default; require explicit `--apply` for mutation.
- Do not implement push, fetch, merge, rebase, tag, reset, clean, restore, remote PR, release, or publication operations.
