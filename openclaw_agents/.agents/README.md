# Local OpenClaw Team Template

This folder contains the current reusable OpenClaw runtime template for the
V3 Zulip-first agent system.

Workspace-level coordination belongs in the root `PROJECT.md`. Project-specific
context belongs in `project_template/`-based folders such as
`projects/<slug>/PROJECT.md` and `projects/<slug>/management/`. Local agent
config, prompts, wrappers, generated state, and Docker assets live under
`.agents/`.

## Team Roles

Visible roles:
- `assistant` / `AgentSmith`: intake, discussion, and visible routing
- `neo`: CTO-style direct-execution assistant backed by an OpenAI OAuth host runtime
- `yoda`: advisory role for critique, reframing, and second opinions
- `projectmanager` / `Niaobe`: project loop, project decisions, and coordination
- `architect`: planning, milestones, stories, and acceptance criteria
- `morpheus`: visible software execution entrypoint backed by `run_team.sh`
- `oracle`: independent validation and QA voice

Internal software-team roles:
- `manager`: internal orchestrator for the software team
- `planner`: implementation planning and risk discovery
- `coder`: code changes
- `tester`: validation and regression checks

## Runtime Model

- Docker-backed local OpenClaw runtime for the main team roles
- Shared sandbox image: `openclaw-sandbox:pytorch-shared-venv`
- Generated config: `.agents/openclaw.json` from `.agents/openclaw.template.json`
- Local runtime artifacts: `.agents/state/` and `.agents/sandboxes/`
- Host-backed OpenAI OAuth runtime wrapper for `Neo`:
  `.agents/scripts/run_openai_oauth_host_runtime.sh`

## Key Files

- `PROJECT.md`: workspace-level coordination and project-selection guidance
- `SETUP_BLUEPRINT.md`: canonical instructions for recreating the current setup
- `AGENT_SYSTEM_V3.md`: current DM-first architecture
- `ZULIP_SETUP_GUIDE.md`: Zulip installation and organization setup
- `ZULIP_V3_GATEWAY_SETUP.md`: current gateway deployment guide
- `SYSTEMD_BRIDGES.md`: systemd setup for the V3 gateway
- `ZULIP_PLAN.md`: current Zulip architecture summary and rollout outline
- `ZULIP_PROJECT_WORKFLOW.md`: visible project-loop conventions
- `AGENT_CREATION_GUIDE.md`: how to add or update roles in this template
- `NEO_OPENAI_AGENT_PLAN.md`: design and setup guidance for Neo
- `AGENTIC_SOFTWARE_DEVELOPMENT_PLAN_TEMPLATE.md`: optional project SDP template
- `project_template/README.md`: reusable per-project scaffold
- `.agents/project_registry.example.json`: multi-project registry example
- `.agents/COMMUNICATION_CONTRACT.md`: visible handoff, status, result, and decision format
- `zulip_gateway_v3/README.md`: multi-bot Zulip gateway runtime
- `.agents/openclaw.template.json`: portable OpenClaw config template
- `.agents/prompts/`: role prompts
- `.agents/scripts/render_openclaw_config.sh`: renders `.agents/openclaw.json`
- `.agents/scripts/setup_local_team.sh`: prepares the local runtime
- `.agents/scripts/project_registry.py`: validates the project registry
- `.agents/scripts/check_template_repo_safety.sh`: template safety checks
- `.agents/run_assistant.sh`, `.agents/run_neo.sh`, `.agents/run_yoda.sh`,
  `.agents/run_projectmanager.sh`, `.agents/run_architect.sh`,
  `.agents/run_morpheus.sh`, `.agents/run_oracle.sh`: visible-role wrappers
- `.agents/run_manager.sh`, `.agents/run_planner.sh`, `.agents/run_coder.sh`,
  `.agents/run_tester.sh`, `.agents/run_team.sh`: internal software-team wrappers

## Quick Start

```bash
bash .agents/scripts/setup_local_team.sh
bash .agents/run_assistant.sh "Review PROJECT.md and tell me the next best move."
bash .agents/run_neo.sh "Inspect this issue, make the fix, and summarize the result."
bash .agents/run_yoda.sh "Challenge the current direction and point out hidden risks."
bash .agents/run_projectmanager.sh "Take ownership of the current milestone."
bash .agents/run_morpheus.sh "Implement the requested change and validate it."
bash .agents/run_team.sh "Implement the requested change and validate it."
```

## Notes

- Use `project_template/` for real project work. Keep the shared runtime generic.
- Keep project-specific planning under `projects/<slug>/management/`, not under
  a shared root-level `management/` folder.
- Use `zulip_gateway_v3/` for all visible DM-able roles.
- Use visible `HANDOFF`, `STATUS`, `RESULT`, and `DECISION` blocks for
  cross-role work instead of hidden nested spawning.
- Keep extra sandbox packages in
  `.agents/docker/pytorch-shared-venv/requirements-extra.txt`.
- Do not edit the generated `.agents/openclaw.json` directly; update the
  template or rendering script instead.
- Template maintainers should run
  `bash .agents/scripts/check_template_repo_safety.sh` before committing.
