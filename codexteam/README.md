# CodexTeam

CodexTeam is the local-first multi-agent coordination MVP for running a bounded software-delivery team around local Codex and Ollama workers.

The core owns:

- teams, agents, tasks, runs, and attempts
- approvals, reviews, requested actions, and audit
- isolated runtime state under `/home/alik/workspace/codexspace`
- project sandboxes under `/home/alik/workspace/codexspace/projects`
- read-only board projections and operator-facing scripts

The current architecture keeps domain behavior in the core. Adapters, CLI surfaces, and future MCP or HTTP layers call the controller; they do not mutate runtime state directly.

## Current Status

Implemented and verified:

- core state store, audit, task/run/workspace primitives
- structured worker-result, requested-action, attempt, review, and workspace models
- read-only board command with stable public contract guidance
- project workspace and delivery layer
- template-backed project initialization
- local worker E2E with controller-backed file application
- real project-sandbox leader runtime using local Codex with Ollama
- front CLI routing that sends project understanding and project edits through the real runtime first, with safe fallback to the older controller-chat path

Current leader defaults:

- provider: `codex`
- leader model: `gemma4:26b`
- worker/test model: `gemma4:12b`

Historical acceptance markers retained for compatibility with the post-MVP doc checks:

- `137 passed`
- `PHASE19_SUMMARY_DONE`

## Layout

- `src/codexteam/`: core package
- `scripts/`: operator and reusable runtime helpers
- `tests/smoke/`: smoke and probe runners
- `tests/e2e/`: E2E runners
- `docs/`: architecture, contracts, runtime layout, and user guidance
- `templates/`: project initialization templates
- `tests/`: phase-scoped test coverage

## Common Commands

Run the full test suite:

```bash
./env-python/bin/python -m pytest -q codexteam/tests
```

Show the board:

```bash
./env-python/bin/python codexteam/scripts/show_board.py --team <team-id>
```

Talk to the leader:

```bash
./env-python/bin/python codexteam/scripts/talk_to_leader.py --team <team-id>
```

Operator scripts:

- `create_team.py`
- `approve_plan.py`
- `create_task.py`
- `run_worker.py`
- `show_board.py`
- `approve_review.py`
- `reject_review.py`

Run the real leader runtime smoke:

```bash
./env-python/bin/python codexteam/tests/smoke/run_real_leader_runtime_smoke.py
```

For more operational detail, start with:

- `docs/USER_GUIDE.md`
- `docs/CORE_DOMAIN_MODEL.md`
- `docs/PUBLIC_CONTRACTS.md`
- `docs/RUNTIME_LAYOUT.md`
