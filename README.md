# V0 Zulip Agent Team

This repository contains the first working version of the local Zulip agent team.

The implementation brief lives at [claw_agents_team/docs/V0_MINIMAL_SYSTEM_IMPLEMENTATION.md](./claw_agents_team/docs/V0_MINIMAL_SYSTEM_IMPLEMENTATION.md).

## What It Includes

- live agents: `Neo`, `AgentSmith`, `Niaobe` and more.
- a local Zulip bridge that polls bot events and posts replies
- direct file-based project truth under `projects/`
- policy-driven delegation with execution-readiness gates
- visible handoffs in the `projects` stream
- local inference through `ollama` using `gemma4:26b` with a 262144-token context window

Live runtime data is expected under `/home/alik/workspace/clawspace`.

## Run

```bash
./claw_agents_team/runtime/scripts/run_agent.sh
```

## Validate

```bash
./claw_agents_team/runtime/scripts/run_agent.sh --check
python3 -m py_compile claw_agents_team/runtime/src/agent_runner.py claw_agents_team/runtime/src/zulip_bridge/client.py
pytest claw_agents_team/tests -q
```

## Layout

- `claw_agents_team/agents/`: role prompts and skills
- `claw_agents_team/shared/`: shared workflow and execution guidance
- `claw_agents_team/runtime/`: bridge, runner, config templates, and runtime code
- `claw_agents_team/workflows/`: workflow contract and role mapping
- `claw_agents_team/policy/`: crew policy and delegation authorities
- `projects/`: active project folders (symlink to the external clawspace projects root)