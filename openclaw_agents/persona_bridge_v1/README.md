# Persona Bridge V1

This folder contains a reusable shared multi-bot bridge for human-facing Zulip
personas such as `AgentSmith`, `Yoda`, and later `Architect`.

## Purpose

Use this bridge when a persona should feel like a real Zulip participant:
- direct-message inbox
- group DM support
- presence in selected streams
- visible replies under its own bot identity

This bridge is for discussion personas, not manager-led execution teams.

Keep it separate from:
- `software_bridge_v1/` for execution teams such as `Morpheus`
- future team bridges for research or other orchestrated groups

## Runtime Model

One bridge process manages multiple persona bot accounts.

Each persona has:
- its own Zulip bot credentials
- its own run command
- its own working directory
- its own DM and stream policy
- its own local conversation state

The bridge itself:
- registers one Zulip event queue per persona bot
- polls them concurrently in one process
- routes each message to the correct persona runtime
- keeps thread-local `/status` and `/stop`

## Required Local Inputs

Before running the bridge, you need:

1. A running Zulip server.
2. One Zulip bot account per persona.
3. A private `zuliprc` file for each persona bot.
4. A local persona registry that maps each bot to its command and workspace.
5. The local workspaces and run commands for those personas.

## Files

- `config.example.json`: shared bridge config
- `persona_registry.example.json`: example multi-persona registry
- `zuliprc.example`: template for each private persona bot credential file
- `persona_bridge.py`: shared multi-bot bridge runtime
- `run_bridge.sh`: bridge entrypoint

## Config

Copy:

```bash
cp config.example.json config.json
cp persona_registry.example.json persona_registry.json
```

Then replace the local values in `persona_registry.json`.

Important shared config fields:
- `persona_registry_path`: local path to the persona registry
- `state_dir`: local bridge state directory
- `verify_tls`: keep `true` by default; set to `false` only for temporary local self-signed setups

## Persona Registry

Each persona entry defines:
- `display_name`
- `zuliprc_path`
- `run_command`
- `workspace`
- `allow_dm`
- `allowed_streams`
- `reply_mode`
- optional `mention_triggers`
- optional `description`

### Reply Modes

- `dm_only`: respond only in DMs
- `dm_or_mention`: respond in DMs and in allowed streams when explicitly mentioned or summoned
- `mention_only`: respond only in allowed streams when explicitly mentioned or summoned
- `always`: respond to every message in allowed streams, plus DMs if `allow_dm` is true

Recommended default for most personas:
- `dm_or_mention`

Use `always` only for dedicated persona-owned streams, otherwise you will get
noise and drift.

## Stream Invocation

In allowed streams, personas can be triggered by:
- an explicit mention that matches their configured triggers
- `/summon <persona-slug> ...`
- `/ask <persona-slug> ...`

Examples:
- `@**Yoda** what do you think?`
- `/summon yoda Challenge this idea.`
- `/ask architect Turn this into milestones.`

## Commands

Inside a persona DM or a persona-owned stream thread:
- `/help`
- `/status`
- `/stop`

These are thread-local:
- `/status` checks the current persona run in that DM or topic
- `/stop` stops the current persona run in that DM or topic

## Rooms And Streams

To make a persona available in a room:
1. create or choose the Zulip stream
2. subscribe the persona bot to that stream
3. add the stream to `allowed_streams`
4. choose the right `reply_mode`

That makes the persona visible in the stream, but the bot should still be
invoked conservatively unless the stream is truly persona-owned.

## Running

```bash
cd YOUR_ZULIP_WORKDIR/persona_bridge
cp config.example.json config.json
cp persona_registry.example.json persona_registry.json
bash run_bridge.sh --check
bash run_bridge.sh
```

## Validation

Useful checks:

```bash
bash run_bridge.sh --check
python3 -m py_compile persona_bridge.py
bash -n run_bridge.sh
```

## Notes

- A Zulip channel or stream alone does not connect a bot account to an agent.
  The bridge is what makes the bot behave like a participant.
- Agent creation and bot creation are not enough; the persona must also be added
  to the registry and the bridge must be restarted or reloaded.
- This bridge is the right place for `AgentSmith`, `Yoda`, and `Architect`.
- Team personas such as `Morpheus` belong behind a team bridge, not here.
