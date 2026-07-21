# CodexTeam Architecture Review

## Status

The current architecture is a small workflow-tool package plus repository-local agent guidance.

## Components

- `.agents/`: reusable leader, worker, verification, and delivery guidance.
- `src/codexteam_tools/`: deterministic path, contract, task, spawn, and closure logic.
- `scripts/`: operator-facing compatibility entrypoints.
- `schemas/`: machine-readable handoff and result contracts.
- `templates/project/`: complete project initialization template.
- `tests/`: model-free unit, integration, and security validation.

## Boundaries

- Project work is isolated under `/home/alik/workspace/codexspace/projects` by default.
- Workers may write only inside the assigned workspace and explicit additional roots.
- Worker results are untrusted until schema validation and independent verification pass.
- Shell text is never evaluated. Verification and Codex commands use structured argument arrays.
- The leader owns state closure; a worker result cannot update task or delivery state directly.

## Known External Dependencies

- Python 3.12+
- Bash for thin compatibility wrappers
- Codex CLI for live subagent execution
- Local Ollama-backed profiles `qwen36-27b` and `gemma4-26b`

No live model is required for deterministic tests.
