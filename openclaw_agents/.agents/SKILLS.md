# Local Skills

This template defines two local skills for the OpenClaw + Ollama team in `.agents/`.

Current local team:
- manager: `local-ollama-qwen-manager`
- planner: `local-ollama-qwen-planner`
- coder: `local-ollama-qwen-coder`
- tester: `local-ollama-qwen-tester`

Canonical entrypoints:
- Manager: `bash .agents/run_manager.sh "your task"`
- Team orchestration: `bash .agents/run_team.sh "your task"`
- Direct role runs: `bash .agents/run_agent.sh <manager|planner|coder|tester> "your task"`

Project context:
- `PROJECT.md` is the single project-specific source of truth for goals, constraints, architecture notes, and commands.
- For the multi-project direction, `project_template/` provides the per-project
  documents and `.agents/project_registry.json` maps project slugs to workspaces.
- `.agents/openclaw.json` is generated locally from `.agents/openclaw.template.json`.

## 1. Local Agent Generator

- Use when the task is to create, recreate, or refactor the local OpenClaw team template for this workspace.
- Canonical skill file: `.agents/skills/local-openclaw-agent-generator/SKILL.md`
- Scope:
  - keep agent assets under `.agents/`
  - keep single-project context in `PROJECT.md`, or per-project context in
    `project_template/`-based folders for multi-project setups
  - keep OpenClaw config and runtime state local, never global
  - keep the manager-led team model aligned across config, prompts, wrappers, and docs

## 2. Local Agent Usage

- Use when the task is to run, validate, debug, or extend the existing local OpenClaw team.
- Canonical skill file: `.agents/skills/local-openclaw-agent-usage/SKILL.md`
- Scope:
  - use the current manager/planner/coder/tester roles and wrappers
  - use the manager-led team wrapper when orchestration is needed
  - verify Docker sandbox image and local runtime when needed
  - keep project-registry driven multi-project routing aligned with the bridge
    and the per-project document model
  - rely on the configured shared sandbox environment instead of hardcoded system interpreter paths
  - keep prompts, scripts, config generation, and local rules aligned

Whenever instructions change, update this file and the referenced skill files so they stay aligned with `.agents/AGENTS.md`.
