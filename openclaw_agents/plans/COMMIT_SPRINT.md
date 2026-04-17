# Commit Sprint

## Goal
Turn the current large working tree into a small set of reviewable commits without mixing local runtime debris, secrets, or temporary setup state into the history.

## Rules
- Do not commit anything under `~/workspace/clawspace`; it is runtime state only.
- Do not commit `env-python/`.
- Do not commit `software_team_setup/zulip_bots_email_and_keys.txt`.
- Keep source changes separate from repo-cleanup and planning/docs changes.

## Commit 1: Runtime Architecture Cutover
Scope:
- `openclaw_agents/agents/`
- `openclaw_agents/services/`
- `openclaw_agents/communication/`
- `openclaw_agents/runtime_paths.py`
- `openclaw_agents/config/`
- `openclaw_agents/schemas/`
- prompt files used by the new runtime

Purpose:
- capture the new agent runtime, policy/service split, Zulip transport boundary, and projection/memory/state services

Validation:
- `env-python/bin/python -m pytest -q openclaw_agents/tests`
- `python3 -m py_compile $(find openclaw_agents -name '*.py' -print)`

Suggested message:
- `openclaw_agents: add runtime-driven agent stack and transport-only Zulip gateway`

## Commit 2: Internal Loop And Execution Flow
Scope:
- internal-loop and execution-specific services/runtime changes
- Niaobe, Morpheus, Planner, Implementer, Tester prompts/runtime logic
- execution-related tests

Purpose:
- isolate the multi-agent execution/runtime layer from the broader foundation commit

Validation:
- `env-python/bin/python -m pytest -q openclaw_agents/tests/test_internal_software_loop.py openclaw_agents/tests/test_niaobe_execution_runtime.py`

Suggested message:
- `openclaw_agents: add bounded execution loop and internal agent flow`

## Commit 3: Clawspace Runtime Root Isolation
Scope:
- `openclaw_agents/runtime_paths.py`
- `openclaw_agents/bootstrap_clawspace.py`
- path/root updates in gateway, storage, workspace, mapping, memory, and command services
- README/config updates that describe `OPENCLAW_ROOT`

Purpose:
- make the runtime-root migration and per-project sandboxing reviewable as one isolated infrastructure change

Validation:
- `env-python/bin/python -m pytest -q openclaw_agents/tests/test_operational_hardening.py`
- `OPENCLAW_ROOT=/home/alik/workspace/clawspace env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service --check`

Suggested message:
- `openclaw_agents: move runtime state and project workspaces under clawspace`

## Commit 4: Developer Setup And Test Harness
Scope:
- `openclaw_agents/requirements*.txt`
- `openclaw_agents/pytest.ini`
- `openclaw_agents/setup_local_env.sh`
- test additions under `openclaw_agents/tests/`

Purpose:
- keep environment/bootstrap ergonomics separate from core runtime behavior

Validation:
- `env-python/bin/python -m pytest -q openclaw_agents/tests`

Suggested message:
- `openclaw_agents: add local setup and regression test harness`

## Commit 5: Repo Hygiene And Planning
Scope:
- `.gitignore`
- `openclaw_agents/plans/`
- memory log updates if they must be retained in-repo
- removal of obsolete repo-local runtime/workspace data from tracking

Purpose:
- finish with non-runtime cleanup and planning artifacts instead of hiding them inside behavior commits

Validation:
- `git status --short`

Suggested message:
- `repo: clean local runtime debris and add commit sprint plan`

## Exclusions For Now
- `software_team_setup/` docs unless you explicitly want the spec pack committed
- any credential file
- any repo-local runtime snapshot or generated cache
- any commit that mixes live Zulip smoke artifacts with source code changes

## Recommended Order
1. Commit 1
2. Commit 2
3. Commit 3
4. Commit 4
5. Commit 5
