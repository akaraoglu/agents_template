# OpenClaw Agents

Template scaffold for the new integrated agentic workflow implementation.

Repository boundary:

- keep committed system definition here: code, prompts, schemas, templates, tests, runbooks, and unit templates
- keep live runtime state outside this repository, under `/home/alik/workspace/claw_software_workspace`
- do not store the control-plane database, Zulip credentials, gateway state, worker state, or live project workspaces under `openclaw_agents/`

Current implementation surface:

- control-plane contracts in `config/`, `schemas/`, `orchestrators/`, and `database/`
- scheduler and recovery logic in `scheduler/`
- gateway normalization plus a long-running multi-bot Zulip daemon in `communication/`
- runtime dispatch, worker execution, worker supervision, and response-ingestion adapters in `runtime/`
- prompt-aware external execution adapter for subprocess backends in `runtime/external_executor.py`
- a built-in local Ollama prompt runner in `runtime/ollama_prompt_runner.py`, with the repo's Ollama profiles pinned to `gemma4:31b` in `config/model_map.yaml`
- a workspace-backed OpenClaw executor for real `implementer` and `tester` runs in `runtime/openclaw_workspace_executor.py`
- builtin local execution for the first project loop path (`agent_smith -> niaobe -> architect -> morpheus -> oracle`) and the nested software loop (`morpheus -> planner -> implementer -> tester`) in `runtime/role_executor.py`, `orchestrators/niaobe_engine.py`, and `orchestrators/morpheus_engine.py`
- automated regression coverage under `tests/`
- workspace templates and operator runbooks in `templates/` and `operations/`

Recommended live state layout:

- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/env/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/db/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/runtime/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/zulip_gateway/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/zuliprc/`
- `/home/alik/workspace/claw_software_workspace/projects/`

The committed environment examples live in `operations/examples/`.
