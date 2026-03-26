# Local OpenClaw Team Template

This folder contains a reusable local OpenClaw team template backed by Docker.
Project-specific context belongs in `PROJECT.md` for the single-project layout,
or in `project_template/`-based per-project folders for the multi-project
direction. Local agent config, prompts, wrappers, generated state, and Docker
assets live under `.agents/`.

## Team Roles
- `manager`: orchestrates work, delegates scoped tasks, and synthesizes results
- `planner`: produces implementation plans and identifies risks
- `coder`: makes code changes
- `tester`: validates behavior and checks regressions

## Runtime Model
- Model family: `ollama/qwen3.5:35b`
- Sandbox base image: `pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime`
- Derived runtime image: `openclaw-sandbox:pytorch-shared-venv`
- Shared sandbox virtual environment: generated during sandbox setup
- Config file: generated from `.agents/openclaw.template.json` into `.agents/openclaw.json`
- Local runtime artifacts: `.agents/state/` and `.agents/sandboxes/`

## Key Files
- `PROJECT.md`: project-specific goals, constraints, commands, and acceptance criteria
- `MULTI_PROJECT_PLAN.md`: plan for splitting the shared runtime from
  per-project workspaces
- `SETUP_BLUEPRINT.md`: canonical instructions for recreating the full
  OpenClaw, project, bridge, and Zulip architecture from this template
- `project_template/README.md`: reusable scaffold for per-project documents
- `.agents/project_registry.example.json`: reusable multi-project registry example
- `ZULIP_SETUP_GUIDE.md`: human-facing Zulip installation, account creation, and UI workflow guide
- `ZULIP_PLAN.md`: Zulip architecture, rollout phases, and sprint planning guide
- `ZULIP_SPRINT_1.md`: detailed Sprint 1 execution plan for the first local Zulip deployment
- `ZULIP_V1_SOFTWARE_TEAM.md`: chosen v1 design for the software-only Zulip bridge flow
- `persona_bridge_v1/README.md`: reusable shared multi-bot bridge for DM-able
  and room-visible discussion personas such as `AgentSmith`, `Yoda`, and
  `Architect`
- `software_bridge_v1/README.md`: reusable bridge runtime for the chosen v1 design
- `SOFTWARE_WORKSPACE_README.md`: reusable starting README for the mounted software workspace
- `.agents/openclaw.template.json`: portable OpenClaw config template
- `.agents/prompts/`: role prompts
- `.agents/docker/pytorch-shared-venv/`: sandbox image build context
- `.agents/scripts/render_openclaw_config.sh`: generates local config from the template
- `.agents/scripts/setup_local_team.sh`: prepares the local template and optional validation
- `.agents/scripts/check_template_repo_safety.sh`: checks that the template repo does not include generated local config, local state, or machine-specific committed values
- `.agents/scripts/project_registry.py`: validates and inspects a shared multi-project registry
- `.agents/run_manager.sh`: direct manager entrypoint
- `.agents/run_team.sh`: manager-led orchestration wrapper

## Quick Start
```bash
bash .agents/scripts/setup_local_team.sh
bash .agents/run_manager.sh "Read PROJECT.md and summarize the next best step."
bash .agents/run_team.sh "Implement the requested change and validate it."
```

## Notes
- Edit `PROJECT.md` for single-project use, or instantiate `project_template/`
  for each project when one runtime needs to serve multiple projects.
- In multi-project mode, keep a local `.agents/project_registry.json` derived
  from `.agents/project_registry.example.json` and point the bridge at it.
- Use `persona_bridge_v1/` for visible discussion personas. Keep manager-led
  software execution behind `software_bridge_v1/`.
- Edit `.agents/docker/pytorch-shared-venv/requirements-extra.txt` when the sandbox needs additional Python packages.
- Do not edit the generated `.agents/openclaw.json` directly; update the template or rendering script instead.
- The manager is the logical orchestrator. In this local template, `run_team.sh` coordinates the manager, planner, coder, and tester externally because embedded local mode may not expose direct in-agent delegation tools consistently.
- Template maintainers should run `bash .agents/scripts/check_template_repo_safety.sh` before committing changes in this repository.
