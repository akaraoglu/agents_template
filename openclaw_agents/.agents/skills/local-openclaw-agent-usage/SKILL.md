---
name: local-openclaw-agent-usage
description: Use, validate, debug, or maintain the existing local OpenClaw + Ollama team in this workspace. Use when the user wants to run the local team, pass prompts to it, inspect its Docker sandbox, or verify the local model and runtime.
---

# Local OpenClaw Agent Usage

Use this skill when the local team already exists and the task is to run it or troubleshoot it.

## Default entrypoints

- Prefer `bash .agents/run_manager.sh "your task"` for orchestration or synthesis requests.
- Use `bash .agents/run_team.sh "your task"` for manager-led team execution.
- Use `bash .agents/run_agent.sh <manager|planner|coder|tester> "your task"` for direct role runs.
- The generic wrapper preserves the role prompt, injects `PROJECT.md`, and renders local config before invoking OpenClaw.

## Current runtime assumptions

- Agent ids:
  - `local-ollama-qwen-manager`
  - `local-ollama-qwen-planner`
  - `local-ollama-qwen-coder`
  - `local-ollama-qwen-tester`
- Model: `ollama/qwen3.5:35b`
- Docker sandbox image: `pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime`
- Derived sandbox image: `openclaw-sandbox:pytorch-shared-venv`
- Project context source: `PROJECT.md`
- Generated config path: `.agents/openclaw.json`
- Runtime state path: `.agents/state`
- Current team mode: manager-led external coordinator wrapper

## Common usage

- Prepare config and optional validation:
  - `bash .agents/scripts/setup_local_team.sh`
  - `bash .agents/scripts/setup_local_team.sh --build-image`
  - `bash .agents/scripts/setup_local_team.sh --validate`
- Generic role entrypoint:
  - `bash .agents/run_agent.sh manager "Summarize the current project state"`
  - `bash .agents/run_agent.sh planner "Plan the next feature slice"`
  - `bash .agents/run_agent.sh coder "Implement the requested change"`
  - `bash .agents/run_agent.sh tester "Validate the patch and report regressions"`
- Role-specific wrappers:
  - `bash .agents/run_manager.sh "Summarize the next best step"`
  - `bash .agents/run_coder.sh "Implement the requested change"`
  - `bash .agents/run_planner.sh "Plan the work"`
  - `bash .agents/run_tester.sh "Validate the change"`
- Team wrapper:
  - `bash .agents/run_team.sh "Implement the requested change and validate it"`
- Direct OpenClaw run:
  - `OPENCLAW_CONFIG_PATH=.agents/openclaw.json OPENCLAW_STATE_DIR=.agents/state OLLAMA_API_KEY=ollama-local openclaw agent --local --agent local-ollama-qwen-coder --message "..."`

## Validation and debugging

1. Confirm the local config is rendered by running `bash .agents/scripts/setup_local_team.sh`.
2. Confirm the local team is registered with `OPENCLAW_CONFIG_PATH=.agents/openclaw.json OPENCLAW_STATE_DIR=.agents/state openclaw agents list`.
3. Confirm the effective sandbox with `OPENCLAW_CONFIG_PATH=.agents/openclaw.json OPENCLAW_STATE_DIR=.agents/state openclaw sandbox explain --agent local-ollama-qwen-manager`.
4. If Docker image drift appears, rebuild the derived image and recreate stale sandbox containers before retrying.
5. If runtime checks matter, inspect the live sandbox container and verify the expected Python toolchain and packages inside it directly.
6. For team runs, use `run_team.sh`, which asks the manager to assign work, runs planner if needed, runs coder and tester, then asks the manager to synthesize the result.
7. Keep project file changes inside the repository root and keep agent runtime artifacts inside `.agents/`.

## Maintenance rule

When instructions change, update `.agents/AGENTS.md`, `.agents/SKILLS.md`, prompts, wrappers, and this skill so the local workflow stays self-consistent.
