# Zulip Gateway V3

This folder contains the simpler V3 multi-bot Zulip gateway for the current
DM-first use case.

Use this gateway when you want:
- all main visible roles DM-able
- one shared host-side process for those visible roles
- cross-agent handoffs to stay visible in Zulip
- no nested in-sandbox spawning
- only light thread coordination instead of strict topic ownership

## Purpose

The gateway treats Zulip as the communication bus and the host as the execution
layer.

It:
- listens to multiple Zulip bot accounts in one process
- runs the configured local wrapper for the addressed role
- stores one shared transcript per thread across all visible roles
- tracks only minimal thread state
- parses visible `HANDOFF` blocks and routes them to the next role

This is the recommended runtime model for the V3 architecture in
`../AGENT_SYSTEM_V3.md`.

## Required Local Inputs

Before running the gateway, you need:

1. A running Zulip server.
2. One Zulip bot account per visible role.
3. A private `zuliprc` file for each bot.
4. A local `agent_registry.json` that maps each role to its command and
   workspace.
5. Working local wrappers for those roles.

The template now ships these visible-role wrappers under `.agents/`:
- `run_assistant.sh`
- `run_neo.sh`
- `run_yoda.sh`
- `run_projectmanager.sh`
- `run_architect.sh`
- `run_morpheus.sh`
- `run_oracle.sh`

## Files

- `config.example.json`: shared gateway config
- `agent_registry.example.json`: example multi-role gateway registry
- `zuliprc.example`: template for each private bot credential file
- `gateway.py`: shared V3 multi-bot gateway runtime
- `run_gateway.sh`: gateway entrypoint

For the end-to-end installation and cutover steps, use
`../ZULIP_V3_GATEWAY_SETUP.md`.

## Config

Copy:

```bash
cp config.example.json config.json
cp agent_registry.example.json agent_registry.json
```

Important config fields:
- `agent_registry_path`: local path to the agent registry
- `state_dir`: local gateway state directory
- `verify_tls`: keep `true` by default
- `send_acknowledgement`: whether each role posts an initial "starting" status
- `send_status_updates`: keep `false` by default unless you intentionally want
  extra visible progress posts

## Agent Registry

Each agent entry defines:
- `display_name`
- `zuliprc_path`
- `run_command`
- `workspace`
- `allow_dm`
- `allowed_streams`
- `reply_mode`
- `loops`
- `skills`
- `can_handoff_to`
- optional `mention_triggers`
- optional `description`

### Reply Modes

- `dm_only`
- `dm_or_mention`
- `mention_only`
- `always`

Recommended default:
- `dm_or_mention`

## Shared Thread State

V3 keeps only light per-thread state:
- `active_run_id`
- `current_speaker`
- `awaiting_from`
- `participants`
- `mode`

This is stored under `state/threads/` together with the shared transcript.

## Handoff Format

Visible roles may request another role by emitting a visible block like this:

```text
TYPE: HANDOFF
FROM: AgentSmith
TO: Niaobe
PROJECT: denoising-jbu
SUMMARY: Take ownership of Phase 2 planning.
NEXT: Review the current docs and decide whether Architect or Morpheus should run next.
```

If the target is valid and allowed by `can_handoff_to`, the gateway launches
the target role on the host and keeps the same Zulip thread.

## Behavior

For each human-triggered message:

1. The gateway routes the DM or stream message to the addressed role.
2. The shared thread transcript is updated.
3. The role's local wrapper is executed on the host.
4. The visible reply is posted back as that role.
5. If the reply contains an authorized `HANDOFF`, the gateway starts the next
   role in the same thread.

Current intentional simplification:
- stream messages sent by bots are not used as general-purpose triggers
- visible cross-agent progression is driven by gateway-routed handoffs
- this avoids duplicate bot loops while keeping the main orchestration visible

## Commands

Each visible role supports thread-local:
- `/help`
- `/status`
- `/stop`

## Running

```bash
cd YOUR_ZULIP_WORKDIR/zulip_gateway_v3
cp config.example.json config.json
cp agent_registry.example.json agent_registry.json
bash run_gateway.sh --check
bash run_gateway.sh
```

## Validation

Useful checks:

```bash
bash run_gateway.sh --check
python3 -m py_compile gateway.py
bash -n run_gateway.sh
```

## Notes

- This gateway is the current default runtime for visible chat roles.
- It is the right place for `AgentSmith`, `Neo`, `Yoda`, `Niaobe`,
  `Architect`, `Morpheus`, and `Oracle` when you want them all directly DM-able.
- It keeps visible coordination in Zulip and keeps execution on the host.
