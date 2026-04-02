# Zulip Gateway V3 Setup

Use this runbook for the current recommended Zulip integration:
- all visible roles DM-able
- one host-side gateway process
- Zulip as the communication bus
- visible `HANDOFF`, `STATUS`, `RESULT`, and `DECISION` messages
- no nested in-sandbox spawning

This is the setup path for:
- `AgentSmith`
- `Neo`
- `Yoda`
- `Niaobe`
- `Architect`
- `Morpheus`
- `Oracle`

Use this together with:
- `AGENT_SYSTEM_V3.md`
- `ZULIP_SETUP_GUIDE.md`
- `zulip_gateway_v3/README.md`
- `SYSTEMD_BRIDGES.md`

## 1. Prepare The Local Runtime

From the project workspace:

```bash
bash .agents/scripts/setup_local_team.sh
bash .agents/run_assistant.sh "Read PROJECT.md and summarize the next best step."
bash .agents/run_neo.sh "Inspect the workspace and report the current technical state."
bash .agents/run_projectmanager.sh "Take ownership of the current project and identify the next role."
bash .agents/run_morpheus.sh "Summarize the current software loop."
```

The template ships these visible-role wrappers:
- `.agents/run_assistant.sh`
- `.agents/run_neo.sh`
- `.agents/run_yoda.sh`
- `.agents/run_projectmanager.sh`
- `.agents/run_architect.sh`
- `.agents/run_morpheus.sh`
- `.agents/run_oracle.sh`

## 2. Prepare Zulip

Install and initialize Zulip using `ZULIP_SETUP_GUIDE.md`.

Recommended minimum streams:
- `assistant`
- `projects`
- `software`

Optional later:
- `ops`
- `council`
- `validation`

## 3. Create Bot Accounts

Create one Generic bot per visible role:
- `agentsmith-bot`
- `neo-bot`
- `yoda-bot`
- `niaobe-bot`
- `architect-bot`
- `morpheus-bot`
- `oracle-bot`

Store each bot credential file under a local ignored `private/` directory.

## 4. Create The Gateway Workspace

Example layout:

```text
YOUR_ZULIP_WORKDIR/
└── zulip_gateway_v3/
    ├── config.json
    ├── agent_registry.json
    ├── gateway.py
    ├── run_gateway.sh
    ├── private/
    └── state/
```

Copy the template files:

```bash
cp /path/to/openclaw_agents/zulip_gateway_v3/config.example.json config.json
cp /path/to/openclaw_agents/zulip_gateway_v3/agent_registry.example.json agent_registry.json
```

## 5. Fill In `config.json`

Recommended first values:

```json
{
  "agent_registry_path": "./agent_registry.json",
  "state_dir": "./state",
  "verify_tls": true,
  "poll_timeout_seconds": 15,
  "history_entry_limit": 20,
  "send_acknowledgement": true,
  "send_status_updates": false
}
```

If you are temporarily using self-signed local TLS, set `verify_tls` to
`false` only for that environment.

## 6. Fill In `agent_registry.json`

For each role, set:
- `zuliprc_path`
- `run_command`
- `workspace`
- `allowed_streams`

Recommended run commands from this template:
- `AgentSmith`: `["bash", ".agents/run_assistant.sh"]`
- `Neo`: `["bash", ".agents/run_neo.sh"]`
- `Yoda`: `["bash", ".agents/run_yoda.sh"]`
- `Niaobe`: `["bash", ".agents/run_projectmanager.sh"]`
- `Architect`: `["bash", ".agents/run_architect.sh"]`
- `Morpheus`: `["bash", ".agents/run_morpheus.sh"]`
- `Oracle`: `["bash", ".agents/run_oracle.sh"]`

Point every `workspace` value at the prepared OpenClaw workspace that contains
`.agents/` and the project files.

## 7. Validate The Gateway

From the gateway directory:

```bash
bash run_gateway.sh --check
python3 -m py_compile gateway.py
bash -n run_gateway.sh
```

Do not start the gateway until `--check` passes.

## 8. Start The Gateway

Manual start:

```bash
bash run_gateway.sh
```

Recommended long-running mode:
- install `systemd/zulip-gateway-v3.service`
- use `SYSTEMD_BRIDGES.md`

## 9. Install The Service

```bash
sudo cp /path/to/openclaw_agents/systemd/zulip-gateway-v3.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable zulip-gateway-v3.service
sudo systemctl restart zulip-gateway-v3.service
```

## 10. Smoke Test

Test all visible roles:
- DM `AgentSmith`
- DM `Neo`
- DM `Yoda`
- DM `Niaobe`
- DM `Architect`
- DM `Morpheus`
- DM `Oracle`

Then test one visible handoff:
1. DM `AgentSmith`
2. ask for project help
3. confirm `AgentSmith` emits a `HANDOFF` to `Niaobe`
4. confirm `Niaobe` replies in the same Zulip thread

## Notes

- V3 uses light thread coordination, not strict topic ownership.
- Roles are defaults, not cages. Any visible role may answer a direct human DM.
- Cross-agent work should stay visible through gateway-managed handoffs.
- The default live-chat behavior is one short acknowledgement line plus the
  final reply, not multi-step status chatter.
