# Zulip Bootstrap

Use this runbook to prepare Zulip for the single-gateway pattern and run the shared gateway daemon that now exists in this repository.

Treat this repository as template-only. Keep live Zulip credentials, gateway state, and env files under `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/`, not under `openclaw_agents/`.

Committed env example:

- [openclaw-zulip-gateway.env.example](/home/alik/workspace/agent_template/openclaw_agents/operations/examples/openclaw-zulip-gateway.env.example)

## Required Streams

Create these streams:

- `exec`
- `projects`
- `software`
- `verification`
- `escalations`

Do not expose `Planner`, `Implementer`, or `Tester` as normal visible bots unless you are intentionally expanding the MVP boundary.

## Visible Agent Identities

Provision credentials for:

- `MASTER`
- `Neo`
- `AgentSmith`
- `Niaobe`
- `Morpheus`
- `Architect`
- `Oracle`

Store credentials in the secret mechanism your deployment uses. The simplest supported MVP shape is one Zulip rc file per visible bot under `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/zuliprc/`, with filenames:

- `master.zuliprc`
- `neo.zuliprc`
- `agent_smith.zuliprc`
- `niaobe.zuliprc`
- `morpheus.zuliprc`
- `architect.zuliprc`
- `oracle.zuliprc`

## Required Subscription Shape

Match `openclaw_agents/communication/zulip_gateway_config.yaml`:

- `MASTER`: `exec`, `projects`, `verification`, `escalations`
- `Neo`: `exec`, `projects`, `verification`, `escalations`
- `AgentSmith`: `exec`, `projects`, `escalations`
- `Niaobe`: `projects`, `software`, `verification`, `escalations`
- `Morpheus`: `projects`, `software`, `escalations`
- `Architect`: `projects`, `software`
- `Oracle`: `verification`, `projects`, `escalations`

## Topic Conventions

Keep topics aligned with the gateway config:

- `project/{project_id}/intake`
- `project/{project_id}`
- `project/{project_id}/decisions`
- `project/{project_id}/design`
- `project/{project_id}/software`
- `project/{project_id}/software/{task_id}`
- `project/{project_id}/verify/{task_id}`
- `project/{project_id}/escalate/{task_id}`

## Message Shape

Authoritative messages must have:

- a short human-readable summary
- a fenced YAML block that validates against the committed schema

Pure discussion without a valid schema block is non-authoritative by design.

## Offline Validation

Initialize the control-plane DB first, then validate the gateway contract locally:

```bash
python3 - <<'PY'
from openclaw_agents.communication.zulip_gateway import GatewayEvent, ZulipGateway

gateway = ZulipGateway()
event = GatewayEvent(
    message_id="zulip-smoke-1",
    sender_name="Niaobe",
    sender_type="bot",
    stream_name="projects",
    topic_name="project/demo",
    content="""Assigned architecture work.
```yaml
kind: task_assignment
task_id: task_demo_1
project_id: demo
from_agent: niaobe
to_agent: architect
task_type: DESIGN_ARCHITECTURE
title: Draft the initial architecture
goal: Produce an implementable architecture spec
priority: HIGH
return_to: niaobe
context:
  charter_ref: artifact_demo_charter
expected_output:
  artifact_type: architecture_spec
decision_bounds:
  may_change_scope: false
```
""",
)
result = gateway.handle_inbound_event(event)
print(result.status)
print(result.dispatch_plan)
PY
```

## Gateway Service Check

Set these environment variables first:

- `OPENCLAW_REPO_ROOT`
- `OPENCLAW_GATEWAY_CONFIG`
- `OPENCLAW_ZULIPRC_DIR`
- `OPENCLAW_ZULIP_GATEWAY_STATE_DIR`
- `OPENCLAW_DB_PATH`
- `ZULIP_SERVER_URL`
- `OPENCLAW_ZULIP_INSECURE=1` when your Zulip deployment uses a self-signed local certificate

Then validate the service wiring:

```bash
python3 -m openclaw_agents.communication.zulip_gateway_service --config openclaw_agents/communication/zulip_gateway_config.yaml --check
```

Process one non-blocking poll cycle:

```bash
python3 -m openclaw_agents.communication.zulip_gateway_service --config openclaw_agents/communication/zulip_gateway_config.yaml --once
```

Once worker callbacks are wired in, the same shared gateway service also mirrors completed task results back into Zulip from authoritative state. Workers do not need their own Zulip clients.

## systemd

The committed gateway unit file is [zulip-gateway.service](/home/alik/workspace/agent_template/openclaw_agents/operations/systemd/zulip-gateway.service). The live env file should live at `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/env/openclaw-zulip-gateway.env`, based on the committed [openclaw-zulip-gateway.env.example](/home/alik/workspace/agent_template/openclaw_agents/operations/examples/openclaw-zulip-gateway.env.example).

That env file should define at least:

- `OPENCLAW_REPO_ROOT`
- `OPENCLAW_GATEWAY_CONFIG`
- `OPENCLAW_ZULIPRC_DIR`
- `OPENCLAW_ZULIP_GATEWAY_STATE_DIR`
- `OPENCLAW_DB_PATH`
- `ZULIP_SERVER_URL`

Do not deploy per-agent Zulip clients. The intended pattern remains one shared gateway service managing all visible bot identities.

The committed worker service units are:

- [openclaw-worker-supervisor.service](/home/alik/workspace/agent_template/openclaw_agents/operations/systemd/openclaw-worker-supervisor.service)
- [openclaw-worker@.service](/home/alik/workspace/agent_template/openclaw_agents/operations/systemd/openclaw-worker@.service)

The worker env file should live at `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/env/openclaw-runtime-workers.env`.

That env file should define at least:

- `OPENCLAW_REPO_ROOT`
- `OPENCLAW_WORKER_CONFIG`
- `OPENCLAW_DB_PATH`

Add `OPENCLAW_RUNTIME_STATE_DIR`, `OLLAMA_HOST`, or `OPENCLAW_OLLAMA_TRANSPORT` when your deployment needs them.

Recommended deployment shape:

1. run one shared `zulip-gateway.service`
2. run one shared `openclaw-worker-supervisor.service`
3. use `openclaw-worker@agent_id.service` only for explicit pinning or debugging
