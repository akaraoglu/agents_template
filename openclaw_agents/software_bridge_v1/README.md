# Zulip V1 Software Bridge

This folder contains the reusable bridge runtime for the first Zulip-driven
software team flow.

## Recommended Variables

Replace these values for each deployment:
- `YOUR_ZULIP_WORKDIR`: local directory that holds your Zulip deployment files
- `YOUR_PROJECT_WORKSPACE`: host path to a single project workspace, only for single-project mode
- `YOUR_PROJECT_REGISTRY`: local path to the shared project registry JSON for multi-project mode
- `YOUR_SOFTWARE_STREAM_NAME`: Zulip stream used for software requests
- `YOUR_SOFTWARE_MANAGER_BOT_EMAIL`: email address of the manager bot account
- `YOUR_ZULIP_SITE_URL`: full Zulip base URL, including a non-default port if needed

Recommended defaults for this template:
- `YOUR_SOFTWARE_STREAM_NAME`: `software`

## Runtime Model

The bridge connects:
- one Zulip stream
- one visible software manager bot
- either one mounted software project workspace
- or one shared project registry that lets each topic select a project

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

For multi-project mode, replace item 5 with:
- a shared project registry JSON that points to multiple prepared project
  workspaces

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
- `software_workspace`: host path to the mounted project workspace for single-project mode
- `project_registry_path`: path to the shared project registry JSON for multi-project mode
- `default_project_slug`: optional default project slug when no topic-specific project is selected
- `software_run_command`: usually `["bash", ".agents/run_team.sh"]`
- `verify_tls`: keep `true` by default; set to `false` only for temporary local self-signed setups

Use exactly one project mode:
- single-project mode: set `software_workspace` and leave `project_registry_path` null
- multi-project mode: set `project_registry_path` and leave `software_workspace` null

## Behavior

For each new human message in the configured software stream:

1. The bridge records the message under the topic state.
2. The bridge checks for `/project` commands in that topic.
3. The bridge optionally posts an acknowledgement.
4. The bridge invokes the software team against the selected project.
5. The bridge captures the manager summary.
6. The bridge posts the result back into the same Zulip topic.

The bridge ignores messages sent by the bot itself.

In multi-project mode, each topic can manage its own project selection with:
- `/project list`
- `/project use <slug>`
- `/project status`
- `/project clear`

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

Optional shared-registry validation:

```bash
python3 ../.agents/scripts/project_registry.py --registry ../.agents/project_registry.json check
python3 ../.agents/scripts/project_registry.py --registry ../.agents/project_registry.json list
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
- The selected software workspace is the mounted project tree, not the entire host.
- Keep `config.json`, `private/`, and `state/` out of version control.
