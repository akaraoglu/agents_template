# Local Skills

This template ships the current local skills for the V3 OpenClaw + Zulip
system.

Visible roles:
- `assistant`: `local-ollama-qwen-assistant`
- `neo`: host-backed OpenAI OAuth role through `.agents/run_neo.sh`
- `yoda`: `local-ollama-qwen-yoda`
- `projectmanager`: `local-ollama-qwen-projectmanager`
- `architect`: `local-ollama-qwen-architect`
- `morpheus`: wrapper around `run_team.sh`
- `oracle`: `local-ollama-qwen-oracle`

Internal software-team roles:
- `manager`: `local-ollama-qwen-manager`
- `planner`: `local-ollama-qwen-planner`
- `coder`: `local-ollama-qwen-coder`
- `tester`: `local-ollama-qwen-tester`

Canonical entrypoints:
- AgentSmith: `bash .agents/run_assistant.sh "your task"`
- Neo: `bash .agents/run_neo.sh "your task"`
- Yoda: `bash .agents/run_yoda.sh "your task"`
- Niaobe: `bash .agents/run_projectmanager.sh "your task"`
- Architect: `bash .agents/run_architect.sh "your task"`
- Morpheus: `bash .agents/run_morpheus.sh "your task"`
- Oracle: `bash .agents/run_oracle.sh "your task"`
- Manager: `bash .agents/run_manager.sh "your task"`
- Team orchestration: `bash .agents/run_team.sh "your task"`
- Direct role runs:
  `bash .agents/run_agent.sh <assistant|yoda|projectmanager|architect|manager|planner|coder|tester|oracle> "your task"`

Project context:
- `PROJECT.md` is the workspace-level guide.
- Real project context lives in `project_template/`-based project folders.
- `.agents/project_registry.json` maps project slugs to workspaces in a
  multi-project deployment.
- `.agents/openclaw.json` is generated locally from `.agents/openclaw.template.json`.

## 1. Local Agent Generator

- Use when the task is to create, recreate, or refactor the local OpenClaw
  team template for this workspace.
- Canonical skill file:
  `.agents/skills/local-openclaw-agent-generator/SKILL.md`
- Scope:
  - keep agent assets under `.agents/`
  - keep per-project context in `project_template/`-based folders
  - keep OpenClaw config and runtime state local, never global
  - keep prompts, wrappers, gateway config, and docs aligned

## 2. Local Agent Usage

- Use when the task is to run, validate, debug, or extend the existing local
  OpenClaw team.
- Canonical skill file:
  `.agents/skills/local-openclaw-agent-usage/SKILL.md`
- Scope:
  - use the current visible-role wrappers and the internal
    manager/planner/coder/tester roles
  - use the manager-led team wrapper when orchestration is needed
  - verify Docker sandbox image and local runtime when needed
  - keep project-registry driven routing aligned with the per-project document model
  - rely on the configured shared sandbox environment instead of hardcoded
    system interpreter paths
  - keep prompts, scripts, config generation, and local rules aligned

Whenever instructions change, update this file and the referenced skill files
so they stay aligned with `.agents/AGENTS.md`.
