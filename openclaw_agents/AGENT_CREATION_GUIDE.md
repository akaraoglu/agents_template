# OpenClaw Agent and Team Creation Guide

## Overview

This guide describes how to create or update roles in the current OpenClaw
template:
- Docker-backed local roles for the main team
- one host-backed OpenAI OAuth role for `Neo`
- one V3 Zulip gateway for all visible roles
- `project_template/` for real project state

The canonical template in this repository is `openclaw_agents/`.

Related guides:
- `SETUP_BLUEPRINT.md`
- `AGENT_SYSTEM_V3.md`
- `ZULIP_SETUP_GUIDE.md`
- `ZULIP_V3_GATEWAY_SETUP.md`
- `project_template/README.md`
- `.agents/project_registry.example.json`
- `.agents/scripts/project_registry.py`
- `.agents/scripts/check_template_repo_safety.sh`

## Template Variables

Committed docs and examples should use placeholders instead of local-machine
values.

Use these variables consistently:
- `YOUR_PROJECT_WORKSPACE`
- `YOUR_PROJECT_REGISTRY`
- `YOUR_ZULIP_WORKDIR`
- `YOUR_DOCKER_ZULIP_DIR`
- `YOUR_ZULIP_EXTERNAL_HOST`
- `YOUR_ZULIP_SITE_URL`
- `YOUR_ZULIP_ADMIN_EMAIL`
- `YOUR_NEO_WORKSPACE`
- `YOUR_OPENAI_OAUTH_PROFILE`

## Core Principles

- Keep real project context in `project_template/`-based project folders.
- Keep reusable agent assets under `.agents/`.
- Generate local `openclaw.json` from a template instead of committing
  machine-specific paths.
- Keep runtime state and sandbox artifacts out of version control.
- Use `run_team.sh` for internal software-team orchestration.
- Use `zulip_gateway_v3/` for all visible DM-able roles.

## Template Layout

```text
openclaw_agents/
├── PROJECT.md
├── project_template/
├── zulip_gateway_v3/
└── .agents/
    ├── AGENTS.md
    ├── README.md
    ├── SKILLS.md
    ├── COMMUNICATION_CONTRACT.md
    ├── openclaw.template.json
    ├── project_registry.example.json
    ├── prompts/
    ├── docker/
    ├── scripts/
    ├── run_agent.sh
    ├── run_assistant.sh
    ├── run_neo.sh
    ├── run_yoda.sh
    ├── run_projectmanager.sh
    ├── run_architect.sh
    ├── run_morpheus.sh
    ├── run_oracle.sh
    ├── run_manager.sh
    ├── run_planner.sh
    ├── run_coder.sh
    ├── run_tester.sh
    └── run_team.sh
```

## Current Role Model

Visible roles:
- `AgentSmith`: intake, clarification, and visible routing
- `Neo`: CTO-style direct execution in a host-backed OAuth runtime
- `Yoda`: critique and reframing
- `Niaobe`: project loop and project decisions
- `Architect`: planning, milestones, stories, and acceptance criteria
- `Morpheus`: visible software execution entrypoint backed by `run_team.sh`
- `Oracle`: visible validation and QA role

Internal software team:
- `manager`
- `planner`
- `coder`
- `tester`

## Project Context Contract

For the current model, the root `PROJECT.md` is workspace-level only.
Real project context belongs in `project_template/`-based folders.

Each project should provide:
- project summary
- scope and constraints
- success criteria
- architecture notes
- key files
- setup, test, lint, typecheck, and run commands
- current risks and open questions

## Config Generation Model

Do not commit a machine-specific `openclaw.json`.

Use this pattern:
1. Commit `.agents/openclaw.template.json` with placeholders.
2. Render `.agents/openclaw.json` locally.
3. Ignore the generated config in version control.

## Runtime Model

Default local roles use the Docker-backed OpenClaw runtime.

Recommended pattern:
- build the derived image from `.agents/docker/pytorch-shared-venv/`
- create the shared sandbox environment during sandbox setup
- keep extra Python packages in `requirements-extra.txt`
- keep runtime state and sandboxes under `.agents/`

Neo is the exception:
- he uses `.agents/scripts/run_openai_oauth_host_runtime.sh`
- he runs against a writable host workspace
- he uses the existing local OpenClaw OAuth login state

## Orchestration Model

The canonical local software flow uses external orchestration:
- `run_manager.sh` runs the manager directly
- `run_team.sh` runs planner if needed
- `run_team.sh` runs coder
- `run_team.sh` runs tester
- `run_team.sh` asks the manager to synthesize the final answer

This is preferred because embedded local mode does not always expose direct
in-agent delegation reliably.

## Zulip Integration Model

Recommended default:
- `zulip_gateway_v3/` for all visible DM-able roles
- visible wrappers:
  `run_assistant.sh`, `run_neo.sh`, `run_yoda.sh`,
  `run_projectmanager.sh`, `run_architect.sh`,
  `run_morpheus.sh`, `run_oracle.sh`

## Creating a New Role

When adding a new role:
1. Add the role prompt under `.agents/prompts/`.
2. Add the role entry to `.agents/openclaw.template.json` if it is OpenClaw-backed.
3. Add the role wrapper under `.agents/`.
4. If the role should be visible in Zulip, add it to
   `zulip_gateway_v3/agent_registry.example.json`.
5. Update `.agents/README.md`, `.agents/AGENTS.md`, and `.agents/SKILLS.md`.
6. Update any wrapper or setup guide that owns the role’s runtime path.

## Quick Start

From the template root:

```bash
bash .agents/scripts/setup_local_team.sh
bash .agents/run_assistant.sh "Review PROJECT.md and tell me the next best move."
bash .agents/run_neo.sh "Inspect this issue and tell me the result."
bash .agents/run_projectmanager.sh "Take ownership of the current project and choose the next role."
bash .agents/run_morpheus.sh "Implement the requested change and validate it."
bash .agents/run_team.sh "Implement the requested change and validate it."
```

Optional:

```bash
bash .agents/scripts/setup_local_team.sh --build-image
bash .agents/scripts/setup_local_team.sh --validate
```

## Validation Checklist

- `.agents/openclaw.json` is rendered from `.agents/openclaw.template.json`
- `openclaw agents list` works with the local config env vars
- the main visible wrappers work
- `zulip_gateway_v3/run_gateway.sh --check` succeeds
- runtime state is ignored and not committed

## Adapting the Template to a New Project

1. Copy `openclaw_agents/` into the project.
2. Create real projects from `project_template/`.
3. Create a local `.agents/project_registry.json` if multiple projects are needed.
4. Adjust `requirements-extra.txt` if the sandbox needs more Python packages.
5. Run the setup script to render local config.
6. Build the Docker image if needed.
7. Validate the team registration and gateway configuration.

## Maintenance Rules

- Update the guide, local rules, and skill files together.
- Keep the template aligned with the current V3-only path.
