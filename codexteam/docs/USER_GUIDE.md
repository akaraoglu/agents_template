# CodexTeam User Guide

CodexTeam is a local-first orchestration package for coordinating local Codex workers.

## Basic Validation

Run all tests:

```bash
./env-python/bin/python codexteam/scripts/run_codexteam_tests.py --phase all
```

Run the local worker smoke:

```bash
./env-python/bin/python codexteam/tests/smoke/run_phase9_local_worker_smoke.py --expect OK
```

The smoke writes runtime state under `/home/alik/workspace/codexspace`.

## Project Initialization Template

Leader project setup uses `initialize_project_management_docs`, which copies UTF-8 text files from the default V4-style test-project template:

```text
codexteam/templates/project_user/
```

To use another mounted template directory, set:

```bash
CODEXTEAM_PROJECT_TEMPLATE=/path/to/template_user ./env-python/bin/python codexteam/scripts/talk_to_leader.py --ask "Initialize project management docs in the active project."
```

The initializer renders `{{PROJECT_NAME}}`, `{{PROJECT_ID}}`, `{{TEAM_ID}}`, `{{PROJECT_DESCRIPTION}}`, and `{{PROJECT_ROOT}}`, then writes files through controller-backed project file operations. The default template creates root project state/report files plus `management/PLAN.md`, `management/BACKLOG.md`, and `management/tasks/T001..T004.md`.

## Real-Life MVP E2E

Run the scaffold end-to-end acceptance path:

```bash
./env-python/bin/python codexteam/tests/e2e/run_real_life_project_e2e.py
```

The scaffold verifies that the leader clarifies project details, waits for approval before initiating the project, waits again before implementation, completes T001 through T004, writes the generated project under `/home/alik/workspace/codexspace/projects/`, runs the generated project tests, and creates delivery artifacts. It is useful for controller regression testing, but it synthesizes implementation output and must not be treated as proof that real workers implemented the project.

Run the real-worker E2E:

```bash
./env-python/bin/python codexteam/tests/e2e/run_real_worker_project_e2e.py
```

This path invokes local model workers, then records evidence, reviews, approvals, tests, board state, and delivery after actual worker-produced file artifacts.

The current default provider is `ollama-files`, not `codex-exec`, because the local Codex exec editing path failed in this environment with an unsupported tool call. `ollama-files` still uses the local model for worker output: the model generates target file contents, and CodexTeam validates/applies them through controller-backed project file writes.

## Flexible Project Edits

The leader can edit normal project files through one scoped proposal flow. For example, the operator can ask to change the project description, rewrite a task file, or update project docs. The leader proposes full-file replacements with `propose_project_edit`, asks for confirmation, and the runtime applies the stored proposal through controller-backed project writes.

Run the edit E2E:

```bash
./env-python/bin/python codexteam/tests/e2e/run_project_edit_e2e.py
```

## Safety Model

- Plans require approval before workers run.
- Worker output becomes evidence, not accepted state.
- Merge and cleanup are approval requests, not automatic actions.
- Local Codex execution uses structured command arguments.
- HTTP and MCP are deferred optional wrappers around core operations.
