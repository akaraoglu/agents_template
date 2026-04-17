# OpenClaw Agents Foundation

This directory contains the Zulip/plugin/skills foundation slice for the agentic software-development system.

## Local setup (fresh clone)

From repository root:

```bash
python3 -m venv env-python
env-python/bin/python -m pip install --upgrade pip
env-python/bin/python -m pip install -r openclaw_agents/requirements-dev.txt
```

## Run tests

```bash
env-python/bin/python -m pytest -q openclaw_agents/tests
```

## Run the Zulip bridge

Visible agents use a local Ollama runtime backed by `gemma4:31b`.

Bootstrap the runtime root first:

```bash
env-python/bin/python -m openclaw_agents.bootstrap_clawspace
```

Check that the model is present:

```bash
ollama list
```

If it is missing, install it before starting the bridge:

```bash
ollama pull gemma4:31b
```

Validate bot credentials and queue registration:

```bash
env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service --check
```

Start the fresh foundation bridge:

```bash
env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service
```

By default the runtime root is:

```bash
~/workspace/clawspace
```

Override it if needed:

```bash
OPENCLAW_ROOT=/some/other/root env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service
```

This bridge uses the foundation config in `openclaw_agents/communication/zulip_gateway_config.yaml`
and reads local bot credentials from `OPENCLAW_ROOT/system/config/zulip_bots_email_and_keys.txt`
unless the configured env vars override them.

## Notes

- Foundation code uses standard library only; `pytest` is required for test execution.
- The live Zulip bridge additionally requires `PyYAML` for local config loading.
- Sprint 2 config uses `gemma4:31b` for Neo, AgentSmith, and Niaobe.
- Gemma thinking mode is enabled by prefixing runtime system prompts with `<|think|>`.
- Sampling is aligned with the official Ollama `gemma4:31b` best-practice guidance: `temperature=1.0`, `top_p=0.95`, `top_k=64`.
- `openclaw_agents/` is source code only; runtime state and project workspaces live under `OPENCLAW_ROOT`.
- Authoritative runtime state is persisted under `OPENCLAW_ROOT/system/state/`.
- Project workspaces live under `OPENCLAW_ROOT/projects/<project_id>/`.
- Niaobe and the internal worker agents are expected to execute inside a single project workspace rather than the whole multi-project tree.
