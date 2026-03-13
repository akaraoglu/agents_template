---
name: local-openclaw-agent-generator
description: Create, recreate, or refactor the local OpenClaw + Ollama team template for this workspace. Use when the user wants a local team config, local agent files under .agents, a Docker sandbox image, or a project-specific OpenClaw setup that must stay inside this repository.
---

# Local OpenClaw Agent Generator

Use this skill when the user wants the local OpenClaw team scaffold created or changed.

## Current template rules

- Keep agent config templates, prompts, scripts, sandboxes, and runtime state under `.agents/`.
- Keep project-specific context in `PROJECT.md`.
- Do not write OpenClaw config or runtime state into any global location.
- The local team roles are:
  - `local-ollama-qwen-manager`
  - `local-ollama-qwen-planner`
  - `local-ollama-qwen-coder`
  - `local-ollama-qwen-tester`
- The manager is the logical orchestrator.
- The current local team wrapper coordinates manager, planner, coder, and tester externally because embedded local mode may not expose direct in-agent delegation tools consistently.

## Current template shape

- Project context: `PROJECT.md`
- Config template: `.agents/openclaw.template.json`
- Generated config: `.agents/openclaw.json`
- Generic wrapper: `.agents/run_agent.sh`
- Manager wrapper: `.agents/run_manager.sh`
- Team wrapper: `.agents/run_team.sh`
- Role wrappers:
  - `.agents/run_coder.sh`
  - `.agents/run_planner.sh`
  - `.agents/run_tester.sh`
- Prompt folder: `.agents/prompts/`
- Docker build context: `.agents/docker/pytorch-shared-venv/`
- Config renderer: `.agents/scripts/render_openclaw_config.sh`
- Setup helper: `.agents/scripts/setup_local_team.sh`
- Sandbox bootstrap: `.agents/scripts/setup_env_python.sh`
- Runtime state: `.agents/state/`
- Sandbox workspace root: `.agents/sandboxes/`
- Model: `ollama/qwen3.5:35b`
- Docker image: `openclaw-sandbox:pytorch-shared-venv`
- Extra sandbox packages: `.agents/docker/pytorch-shared-venv/requirements-extra.txt`

## Workflow

1. Update `PROJECT.md` when the project context changes.
2. Update `.agents/openclaw.template.json` when model, Docker image, workspace behavior, or role ids change.
3. Keep `.agents/AGENTS.md`, `.agents/SKILLS.md`, prompts, wrappers, and skills aligned with the current team behavior.
4. If the sandbox image or extra package list changes, rebuild the local Docker image before trusting runtime checks.
5. Keep the sandbox bootstrap aligned with the package list in `.agents/docker/pytorch-shared-venv/requirements-extra.txt`.
6. Keep prompts and guidance aligned so agents use the configured runtime environment rather than hardcoded system interpreter paths.
7. Keep the manager orchestration format and wrapper parsing logic aligned.
8. Render the local config from the template instead of editing generated config directly.

## Minimal validation

- `bash .agents/scripts/setup_local_team.sh`
- `OPENCLAW_CONFIG_PATH=.agents/openclaw.json OPENCLAW_STATE_DIR=.agents/state openclaw agents list`
- `OPENCLAW_CONFIG_PATH=.agents/openclaw.json OPENCLAW_STATE_DIR=.agents/state openclaw sandbox explain --agent local-ollama-qwen-manager`

Update this skill whenever the local team layout, assumptions, or behavior rules change.
