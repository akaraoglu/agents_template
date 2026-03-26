# OpenClaw and Zulip Setup Blueprint

Use this file as the canonical handoff when you want another agent to recreate
the same OpenClaw and Zulip architecture from this template.

This blueprint defines:
- what kinds of agents exist
- which Zulip bots belong to which bridge
- how to create a new persona
- how to create a new execution team
- what files must be updated
- how to validate the result

## Goal

The target architecture is:
- one reusable OpenClaw runtime template
- one or more project workspaces created from `project_template/`
- one shared persona bridge for DM-able, human-facing bots
- one shared team bridge per team type
- one Zulip server as the visible human interface

Use the current template to build:
- discussion personas such as `AgentSmith`, `Yoda`, and `Architect`
- execution teams such as the `Morpheus` software team
- additional teams later without rewriting the whole control plane

## System Layers

### 1. Shared Runtime Layer

The shared runtime lives in `openclaw_agents/.agents/`.

It owns:
- `openclaw.template.json`
- prompts
- wrappers such as `run_agent.sh` and `run_team.sh`
- Docker sandbox setup
- helper scripts
- bridge runtimes

This layer is generic. It should not contain project-specific goals, stories,
or task details.

### 2. Project Layer

Each real project should be created from `project_template/`.

Each project owns:
- `PROJECT.md`
- `management/STATUS.md`
- `management/MILESTONES.md`
- `management/BACKLOG.md`
- `management/DECISIONS.md`
- `management/RISKS.md`
- `management/stories/`
- `management/tasks/`
- the actual project code

Use one project folder per project. Do not overload the shared runtime with one
global `PROJECT.md` if you plan to support multiple projects.

### 3. Zulip Layer

Zulip is the human-visible chat surface.

Use it for:
- DMs with personas
- stream discussions
- visible team requests
- intervention and status checks

Do not treat Zulip alone as the runtime. A bot becomes "alive" only when it is
connected to an agent through a bridge.

## Agent Categories

There are three categories of agents in this setup.

### Discussion Persona

Examples:
- `AgentSmith`
- `Yoda`
- `Architect`

Use a discussion persona when the agent should:
- feel like a real chat participant
- accept DMs
- join selected streams
- discuss ideas
- ask questions
- optionally hand work off to a team

Discussion personas belong behind `persona_bridge_v1/`.

### Team Manager

Examples:
- `Morpheus`
- future `research-manager`

Use a team manager when the agent should:
- front a whole execution team
- own a request stream
- orchestrate internal workers
- summarize execution results

Team managers belong behind a team bridge such as `software_bridge_v1/`.

### Internal Team Role

Examples:
- `planner`
- `coder`
- `tester`
- `Oracle` when used as an internal validator

Use an internal team role when the agent should:
- work under a manager
- not be the main DM target
- stay mostly inside the orchestration flow

Internal roles usually do not need their own DM-capable bridge.

## Bot And Bridge Rules

Use these rules consistently.

### Persona Bot Rules

A persona bot:
- has its own Zulip bot account
- has its own `zuliprc` file
- is listed in `persona_registry.json`
- has a `run_command`
- may allow DMs
- may allow selected streams

Typical personas:
- `AgentSmith`
- `Yoda`
- `Architect`

Default bridge:
- `persona_bridge_v1/`

Default reply mode:
- `dm_or_mention`

### Team Bot Rules

A team bot:
- is usually the manager bot for one team
- fronts a stream such as `software`
- is wired through a team bridge
- should not be treated like a generic chat persona

Typical team bots:
- `morpheus-bot`
- future `research-manager-bot`

Default bridge:
- `software_bridge_v1/` or another team bridge

Typical interaction:
- one stream
- one topic per task
- no generic DM workflow unless intentionally added later

### Internal Role Bot Rules

Internal roles should stay internal unless there is a clear reason to expose
them.

Recommended default:
- no standalone bot
- no direct DM inbox
- communicate through the team manager

Optional visible role mode:
- the team bridge may post role output under a separate bot identity
- this is best used for `Oracle`-style validation or audit visibility

Do not give every worker its own always-on public bot by default. That creates
noise and makes coordination harder.

## Default Architecture

Recommended first architecture:
- `AgentSmith`: persona bridge, DM + selected streams
- `Yoda`: persona bridge, DM + selected streams
- `Architect`: persona bridge, DM + selected streams
- `Morpheus`: software team bridge, visible in `software`
- `planner`: internal worker
- `coder`: internal worker
- `tester`: internal worker
- `Oracle`: optional visible validation bot or internal tester identity

## When To Use Which Bridge

Use `persona_bridge_v1/` when:
- the agent should be DM-able
- the agent should feel like a human-like chat participant
- the agent should join multiple discussion streams

Use `software_bridge_v1/` or another team bridge when:
- the bot fronts a manager-led team
- the request should turn into orchestrated execution
- the main unit of work is a stream topic

Do not put discussion personas and execution teams behind the same bridge.

## Canonical Creation Workflow

Follow this order.

### 1. Prepare the Shared Runtime

1. Copy `openclaw_agents/` into the target environment.
2. Run the local setup scripts to render `openclaw.json`.
3. Build the Docker sandbox image if required.
4. Confirm the base runtime works before adding more personas or teams.

### 2. Prepare Zulip

1. Install Zulip using `ZULIP_SETUP_GUIDE.md`.
2. Create the required streams.
3. Create the required bot accounts.
4. Store each bot's `zuliprc` file under a local ignored `private/` folder.

### 3. Prepare Projects

1. Create each project from `project_template/`.
2. Fill in `PROJECT.md` and the management files.
3. If using multi-project mode, create a local project registry JSON from
   `.agents/project_registry.example.json`.

### 4. Add Personas

For each persona:
1. Create or update the prompt under `.agents/prompts/` if the persona lives in
   the shared runtime, or in the chosen workspace if it is project-scoped.
2. Add the agent entry to `.agents/openclaw.template.json`.
3. Add a direct wrapper such as `.agents/run_yoda.sh`.
4. Add or update the skill documentation in `.agents/SKILLS.md` and related
   docs.
5. Create the Zulip bot account.
6. Create the private `zuliprc` file.
7. Add the persona entry to `persona_registry.json`.
8. Add the persona to the required streams.
9. Run the persona bridge validation and then start the bridge.

### 5. Add Teams

For each team:
1. Define the manager role and the worker roles.
2. Add or update prompts under `.agents/prompts/`.
3. Add or update `.agents/openclaw.template.json`.
4. Add or update wrappers such as `run_team.sh`, `run_manager.sh`, or
   role-specific wrappers.
5. Create the team manager bot account.
6. Create the team bridge config.
7. Point the team bridge at either a single project workspace or the shared
   project registry.
8. Validate the team bridge and then start it.

## Persona Creation Checklist

Use this checklist every time you create a new discussion persona.

### Required Runtime Files

- prompt file under `.agents/prompts/`
- agent definition in `.agents/openclaw.template.json`
- direct wrapper such as `.agents/run_<persona>.sh`
- any optional helper wrappers
- skill or README updates if the persona exposes new behavior

### Required Zulip Files

- one Zulip bot account
- one private `zuliprc` file
- one persona registry entry

### Required Registry Fields

Each persona registry entry should define:
- `display_name`
- `zuliprc_path`
- `run_command`
- `workspace`
- `allow_dm`
- `allowed_streams`
- `reply_mode`
- optional `mention_triggers`
- optional `description`

### Recommended Defaults

- `allow_dm`: `true`
- `reply_mode`: `dm_or_mention`
- `allowed_streams`: only streams where the persona is intentionally useful

## Team Creation Checklist

Use this checklist every time you create a new execution team.

### Required Runtime Files

- manager prompt
- worker prompts
- agent definitions in `.agents/openclaw.template.json`
- team wrapper
- manager wrapper
- project-aware docs or handoff rules

### Required Zulip Files

- one manager bot account
- one private `zuliprc` file
- one team bridge config

### Recommended Defaults

- one stream per team type
- one topic per task or request
- only the manager bot visible by default
- worker bots exposed only when there is a clear observability need

## What Another Agent Should Modify

When asked to recreate this setup, another agent should update these files and
areas only.

### Shared Runtime Changes

- `openclaw_agents/.agents/openclaw.template.json`
- `openclaw_agents/.agents/prompts/`
- `openclaw_agents/.agents/run_*.sh`
- `openclaw_agents/persona_bridge_v1/`
- `openclaw_agents/software_bridge_v1/`
- `openclaw_agents/.agents/scripts/`

### Project Changes

- project folders created from `project_template/`
- local project registry JSON derived from the example template

### Local-Only Files

These files must stay local and ignored:
- generated `.agents/openclaw.json`
- bridge `config.json`
- private `zuliprc` files
- bridge `state/`
- OpenClaw runtime `state/`
- OpenClaw sandbox residue

## Validation Sequence

Run this sequence after creating or changing the setup.

### Shared Template Checks

```bash
bash .agents/scripts/check_template_repo_safety.sh
```

### Persona Bridge Checks

```bash
cd YOUR_ZULIP_WORKDIR/persona_bridge
bash run_bridge.sh --check
python3 -m py_compile persona_bridge.py
bash -n run_bridge.sh
```

### Team Bridge Checks

```bash
cd YOUR_ZULIP_WORKDIR/software_bridge
bash run_bridge.sh --check
python3 -m py_compile software_manager_bridge.py
bash -n run_bridge.sh
```

### Project Registry Checks

```bash
python3 .agents/scripts/project_registry.py --registry YOUR_PROJECT_REGISTRY check
python3 .agents/scripts/project_registry.py --registry YOUR_PROJECT_REGISTRY list
```

### OpenClaw Checks

```bash
openclaw agents list
openclaw sandbox explain --agent YOUR_MANAGER_AGENT_NAME
```

## Practical Rules

- Keep one clear front door. `AgentSmith` is the preferred main inbox.
- Keep `Architect` focused on docs, scope, milestones, and management
  validation.
- Keep `Morpheus` focused on execution orchestration.
- Keep internal workers internal by default.
- Do not let every bot auto-reply in the same stream.
- Use DMs for private idea shaping and streams for visible group discussion.
- Use the project template instead of inventing a new project doc structure per
  repo.
- Use explicit placeholders in committed template files. Do not commit local
  paths, local hostnames, or live credentials.

## Recommended First Deployment

If you want the smallest useful version of this architecture, start with:
- one Zulip server
- one `software` stream
- one `assistant` or `council` stream
- `AgentSmith` on the persona bridge
- `Yoda` on the persona bridge
- `Architect` on the persona bridge
- `Morpheus` on the software bridge
- one project created from `project_template/`

Then expand only after that works cleanly.
