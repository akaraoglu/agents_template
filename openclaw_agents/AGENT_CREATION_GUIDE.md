# OpenClaw Agent and Team Creation Guide

## Overview

This guide describes how to create a reusable local OpenClaw team template that:
- runs in Docker
- keeps all OpenClaw assets local to the repository
- uses a `manager` orchestrator role
- reads project-specific context from `PROJECT.md`
- generates machine-specific config from a portable template

The canonical local template in this repository is `openclaw_agents/`.

Related guide:
- `ZULIP_SETUP_GUIDE.md` for setting up a self-hosted Zulip UI for human-visible
  agent discussions, account creation, and intervention workflows
- `ZULIP_PLAN.md` for the target architecture, rollout phases, and Phase 1
  sprint plan for the Zulip and bridge integration

## Core Principles

- Keep project-specific information in `PROJECT.md`.
- Keep reusable agent assets under `.agents/`.
- Generate local `openclaw.json` from a template instead of committing machine-specific paths.
- Keep runtime state and sandbox artifacts out of version control.
- Use a `manager` role to orchestrate the rest of the team.

## Template Layout

```text
openclaw_agents/
├── PROJECT.md
└── .agents/
    ├── AGENTS.md
    ├── README.md
    ├── SKILLS.md
    ├── openclaw.template.json
    ├── prompts/
    │   ├── manager.txt
    │   ├── planner.txt
    │   ├── coder.txt
    │   └── tester.txt
    ├── docker/
    │   └── pytorch-shared-venv/
    ├── scripts/
    │   ├── render_openclaw_config.sh
    │   ├── setup_local_team.sh
    │   └── setup_env_python.sh
    ├── run_agent.sh
    ├── run_manager.sh
    ├── run_planner.sh
    ├── run_coder.sh
    ├── run_tester.sh
    └── run_team.sh
```

## Role Model

Use four roles:
- `manager`: orchestrates the group, delegates work, and synthesizes results
- `planner`: produces plans, assumptions, risks, and validation strategy
- `coder`: edits code
- `tester`: validates changes and checks regressions

### Manager Responsibilities

The manager should:
- read `PROJECT.md` first
- understand the goal, constraints, and acceptance criteria
- decide whether planner input is needed
- assign tightly scoped tasks to planner, coder, and tester
- produce a concise final summary

The manager should not be the default code editor. Its main job is orchestration.

## Project Context Contract

`PROJECT.md` is the only file expected to change per project. At minimum, include:
- project summary
- current goal
- constraints
- acceptance criteria
- architecture notes
- key files
- setup, test, lint, typecheck, and run commands
- risks and open questions

All role prompts and wrappers should either read or inject `PROJECT.md` so the team always works from the current project context.

## Config Generation Model

Do not commit a machine-specific `openclaw.json`.

Use this pattern instead:
1. Commit `.agents/openclaw.template.json` with placeholders such as `__ROOT_DIR__`.
2. Render `.agents/openclaw.json` locally using a setup script.
3. Ignore the generated config in version control.

This keeps the template portable while still allowing OpenClaw to receive absolute local paths when needed.

## Docker Runtime Model

Use a Docker sandbox image derived from a shared Python base image.

Recommended pattern:
- build the derived image from `.agents/docker/pytorch-shared-venv/`
- create a shared sandbox virtual environment during sandbox setup
- keep extra Python packages in `requirements-extra.txt`
- keep runtime state and sandboxes under `.agents/`

The current local template uses a shared sandbox environment created by `.agents/scripts/setup_env_python.sh`.

## Orchestration Model

The canonical local template uses an external wrapper for orchestration:
- `run_manager.sh` runs the manager directly
- `run_team.sh` asks the manager to assign work
- `run_team.sh` runs planner if needed
- `run_team.sh` runs coder
- `run_team.sh` runs tester with coder output as context
- `run_team.sh` asks the manager to synthesize the final answer

This model is preferred because embedded local mode may not expose direct in-agent delegation tools consistently.

## Creating a New Role

When adding a new role:
1. Add the role prompt under `.agents/prompts/`.
2. Add the role entry to `.agents/openclaw.template.json`.
3. Add a role wrapper if direct execution is useful.
4. Update `.agents/README.md`, `.agents/AGENTS.md`, and `.agents/SKILLS.md`.
5. Update any orchestration script that needs to route work to the new role.

## Quick Start

From the template root:

```bash
bash .agents/scripts/setup_local_team.sh
bash .agents/run_manager.sh "Read PROJECT.md and summarize the next best step."
bash .agents/run_team.sh "Implement the requested change and validate it."
```

Optional:

```bash
bash .agents/scripts/setup_local_team.sh --build-image
bash .agents/scripts/setup_local_team.sh --validate
```

## Validation Checklist

- `PROJECT.md` is present and up to date.
- `.agents/openclaw.json` is rendered from `.agents/openclaw.template.json`.
- `openclaw agents list` works with the local config env vars.
- `openclaw sandbox explain --agent local-ollama-qwen-manager` resolves correctly.
- The manager, planner, coder, and tester prompts all align with the same team model.
- Runtime state is ignored and not committed.

## Adapting the Template to a New Project

1. Copy `openclaw_agents/` into the project.
2. Update `PROJECT.md`.
3. Adjust `requirements-extra.txt` if the sandbox needs more Python packages.
4. Run the setup script to render local config.
5. Build the Docker image if needed.
6. Validate the team registration and sandbox configuration.

## Maintenance Rules

- Update the guide, local rules, and skills together.
- Keep role prompts and wrapper behavior aligned.
- Prefer portable relative references in committed docs and scripts.
- Keep host-specific paths out of committed files other than the locally generated config.
