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

## Models

- Require an installed, explicitly named profile.
- Use `qwen36-27b` as the default tool-using profile across roles. Treat `gemma4-26b` as an optional bounded secondary perspective, not a default owner for evidence-producing or editing work.
- Model output is untrusted until result validation and independent verification pass.

## State

- Workers cannot complete tasks directly.
- Completed results require evidence.
- Closure fails if declared artifacts are absent or verification fails.
- Repeated closure is idempotent unless the operator explicitly uses `--force`.
