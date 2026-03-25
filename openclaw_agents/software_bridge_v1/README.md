# Zulip V1 Software Bridge

This folder contains the reusable bridge runtime for the first Zulip-driven
software team flow.

## Recommended Variables

Replace these values for each deployment:
- `YOUR_ZULIP_WORKDIR`: local directory that holds your Zulip deployment files
- `YOUR_PROJECT_WORKSPACE`: host path to the project workspace mounted into the software team
- `YOUR_SOFTWARE_STREAM_NAME`: Zulip stream used for software requests
- `YOUR_SOFTWARE_MANAGER_BOT_EMAIL`: email address of the manager bot account
- `YOUR_ZULIP_SITE_URL`: full Zulip base URL, including a non-default port if needed

Recommended defaults for this template:
- `YOUR_SOFTWARE_STREAM_NAME`: `software`

## Runtime Model

The bridge connects:
- one Zulip stream
- one visible software manager bot
- one mounted software project workspace

The bridge itself runs on the host. It:
- reads Zulip events through the bot API
- watches the configured software stream
- treats each topic as a software task thread
- invokes the OpenClaw software team in the mounted project workspace
- posts manager summaries back into the same Zulip topic

The software team itself runs in the mounted project workspace. Inside the
OpenClaw sandbox, that workspace is visible as `/workspace`.

## Required Local Inputs

Before running the bridge, you need:

1. A running Zulip server.
2. A configured software stream, such as `software`.
3. A generic manager bot subscribed to that stream.
4. A private Zulip credential file in `zuliprc` format.
5. A prepared software project workspace that includes `PROJECT.md` and `.agents/`.

## Recommended Layout

Example layout under `YOUR_ZULIP_WORKDIR`:

```text
YOUR_ZULIP_WORKDIR/
├── docker-zulip/
└── software_bridge/
    ├── config.json
    ├── run_bridge.sh
    ├── software_manager_bridge.py
    ├── zuliprc.example
    ├── private/
    │   └── YOUR_SOFTWARE_MANAGER_BOT.zuliprc
    └── state/
```

## Config

Copy `config.example.json` to `config.json` and replace every `YOUR_...` value.

Copy `zuliprc.example` to a private local file such as:
- `private/YOUR_SOFTWARE_MANAGER_BOT.zuliprc`

Then fill in:
- `email`
- `key`
- `site`

Important fields:
- `zuliprc_path`: path to the private bot credentials file
- `stream_name`: software stream name, typically `software`
- `software_workspace`: host path to the mounted project workspace
- `software_run_command`: usually `["bash", ".agents/run_team.sh"]`
- `verify_tls`: keep `true` by default; set to `false` only for temporary local self-signed setups

## Behavior

For each new human message in the configured software stream:

1. The bridge records the message under the topic state.
2. The bridge optionally posts an acknowledgement.
3. The bridge invokes the software team.
4. The bridge captures the manager summary.
5. The bridge posts the result back into the same Zulip topic.

The bridge ignores messages sent by the bot itself.

The bridge is intentionally serial for V1:
- one process
- one event loop
- one topic message handled at a time

## Running

```bash
cd YOUR_ZULIP_WORKDIR/software_bridge
cp config.example.json config.json
bash run_bridge.sh --check
bash run_bridge.sh
```

## Validation

Useful checks:

```bash
bash run_bridge.sh --check
python3 -m py_compile software_manager_bridge.py
bash -n run_bridge.sh
```

## Notes

- The bridge is not the sandbox. It is the orchestrator between Zulip and the
  software team.
- The software workspace is the mounted project tree, not the entire host.
- Keep `config.json`, `private/`, and `state/` out of version control.
