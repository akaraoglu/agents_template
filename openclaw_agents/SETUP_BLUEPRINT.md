# OpenClaw and Zulip Setup Blueprint

Use this file as the canonical handoff when another agent needs to recreate the
current OpenClaw + Zulip system from this template.

This blueprint defines:
- the current V3 architecture
- the runtime and project layers
- the visible roles and internal team roles
- the required files to update when adding or changing a role
- the validation path for a clean deployment

Use this together with:
- `AGENT_SYSTEM_V3.md`
- `ZULIP_SETUP_GUIDE.md`
- `ZULIP_V3_GATEWAY_SETUP.md`
- `ZULIP_PROJECT_WORKFLOW.md`
- `project_template/README.md`

## Goal

The target architecture is:
- one reusable OpenClaw runtime template under `.agents/`
- one or more real project workspaces created from `project_template/`
- one host-side `zulip_gateway_v3` process for all visible roles
- one Zulip server as the human-visible interface

## System Layers

### 1. Shared Runtime Layer

The shared runtime lives in `openclaw_agents/.agents/`.

It owns:
- `openclaw.template.json`
- prompts
- visible-role wrappers
- internal software-team wrappers
- Docker sandbox setup
- helper scripts
- local generated state

This layer stays generic. It should not contain project-specific goals,
stories, or task details.

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

### 3. Zulip Layer

Zulip is the human-visible chat surface.

Use it for:
- DMs with visible roles
- stream discussions
- visible handoffs
- status checks and interventions

The host-side gateway is what makes the bots live.

## Current Role Model

Visible roles:
- `AgentSmith`: intake, discussion, and routing
- `Neo`: CTO-style direct execution in a host-backed OpenAI OAuth runtime
- `Yoda`: critique, reframing, and second opinions
- `Niaobe`: project loop and project decisions
- `Architect`: planning and project document updates
- `Morpheus`: visible software execution entrypoint
- `Oracle`: visible validation and QA

Internal software-team roles:
- `manager`
- `planner`
- `coder`
- `tester`

## Communication Model

Use the V3 rules:
- all visible roles are DM-able
- Zulip carries human-visible `HANDOFF`, `STATUS`, `RESULT`, and `DECISION` messages
- the host-side gateway launches wrappers in response to those messages
- keep only light thread coordination state
- do not rely on nested in-sandbox spawning as the primary orchestration path

Use `.agents/COMMUNICATION_CONTRACT.md` to keep handoffs and visible status
blocks consistent.

## Canonical Creation Workflow

### 1. Prepare the Shared Runtime

1. Copy `openclaw_agents/` into the target environment.
2. Run `.agents/scripts/setup_local_team.sh`.
3. Build the Docker sandbox image if required.
4. Render `.agents/openclaw.json`.
5. Confirm the base runtime works before adding Zulip.

### 2. Prepare Project Workspaces

1. Create real projects from `project_template/`.
2. Fill in each project `PROJECT.md`.
3. Use `management/` for milestones, backlog, status, decisions, and risks.
4. In multi-project mode, create a local `.agents/project_registry.json`.

### 3. Prepare Zulip

1. Install Zulip using `ZULIP_SETUP_GUIDE.md`.
2. Create the required streams and visible bot accounts.
3. Copy `zulip_gateway_v3/config.example.json` and
   `zulip_gateway_v3/agent_registry.example.json`.
4. Point each agent entry at the correct wrapper and workspace.
5. Validate `bash run_gateway.sh --check`.

### 4. Start the Gateway

1. Install `systemd/zulip-gateway-v3.service`.
2. Start `zulip-gateway-v3.service`.
3. Verify one DM and one visible handoff end to end.

## Files To Update When Adding a Visible Role

At minimum:
- `.agents/prompts/<role>.txt`
- `.agents/openclaw.template.json`
- `.agents/run_<role>.sh`
- `.agents/run_agent.sh` if the role is OpenClaw-backed
- `zulip_gateway_v3/agent_registry.example.json`
- `.agents/README.md`
- `.agents/AGENTS.md`
- `.agents/SKILLS.md`
- `AGENT_CREATION_GUIDE.md` if the role changes the recommended setup

If the role uses a special runtime, also update the wrapper and setup guide that
owns that runtime path. Neo is the example for a host-backed OAuth role.

## Validation Checklist

- `bash .agents/scripts/setup_local_team.sh` succeeds
- `bash .agents/run_assistant.sh "..."` works
- `bash .agents/run_projectmanager.sh "..."` works
- `bash .agents/run_morpheus.sh "..."` works
- `bash zulip_gateway_v3/run_gateway.sh --check` succeeds
- `python3 -m py_compile zulip_gateway_v3/gateway.py` succeeds
- `bash -n zulip_gateway_v3/run_gateway.sh` succeeds
- project documents live under real project folders, not under the shared runtime
- no generated local config, local state, or secrets are committed

## Default Recommendation

Use the V3 stack unless you are intentionally designing something new:
- one OpenClaw runtime template
- one project-template-based project layer
- one V3 Zulip gateway
- visible handoffs in chat
- manager-led internal software execution behind Morpheus
