# Zulip V1 Software Team Design

This document defines the first chat-driven software-team integration for the
OpenClaw template.

## Template Variables

Replace these values for each deployment:
- `YOUR_PROJECT_WORKSPACE`: host path to the project workspace
- `YOUR_SOFTWARE_STREAM_NAME`: Zulip stream used for software requests
- `YOUR_SOFTWARE_MANAGER_BOT_NAME`: visible manager bot display name

Recommended defaults for the current template:
- `YOUR_SOFTWARE_STREAM_NAME`: `software`
- `YOUR_SOFTWARE_MANAGER_BOT_NAME`: `software-manager-bot`

Use this document together with:
- `ZULIP_SETUP_GUIDE.md`
- `ZULIP_PLAN.md`
- `ZULIP_SPRINT_1.md`
- `MULTI_PROJECT_PLAN.md`
- `project_template/README.md`
- `software_bridge_v1/README.md`

## V1 Summary

The chosen V1 model is:
- one Zulip software stream
- one visible manager bot
- one mounted project workspace in single-project mode
- or one shared project registry in multi-project mode
- one internal software team:
  `manager`, `planner`, `coder`, `tester`

The human-visible conversation happens only in Zulip. The internal
planner/coder/tester flow stays behind the software manager.

## Purpose

V1 is designed to prove one clean loop:

1. a human requests software work in Zulip
2. the software manager receives the request
3. the internal software team works on the mounted project workspace
4. the software manager reports status and results back to Zulip

## Chosen Scope

Included in V1:
- Zulip as the human UI
- one software stream
- one topic per task
- one visible manager bot
- one project workspace or one shared project registry
- one internal software team
- human request -> implementation -> result loop
- explicit per-topic `/project` commands for multi-project selection

Out of scope for V1:
- research team
- multi-team iteration loops
- visible planner/coder/tester bots
- fully autonomous cross-team orchestration
- automatic project discovery without an explicit registry

## Components

### Zulip

Zulip provides:
- the software stream
- task topics
- human participation
- visible manager updates
- the bot identity used by the bridge

### Bridge

The bridge should:
- read messages from the software stream
- decide whether a message starts or continues a task
- invoke the software manager
- map a Zulip topic to a software-team run
- post manager summaries back into the same topic
- handle human feedback and follow-up messages

The bridge is the only component that should talk to both:
- Zulip
- the software team runtime

### Project Workspace

`YOUR_PROJECT_WORKSPACE` is the host-side working tree for the software team.

It should contain:
- the actual project files
- a project-specific `PROJECT.md`
- the local `.agents/` team assets if you instantiate the team there

Important distinction:
- the host folder is the project workspace
- it is not the sandbox itself
- the sandbox is the Docker runtime that mounts this workspace as `/workspace`

### Software Team

The internal software team is:
- `manager`
- `planner`
- `coder`
- `tester`

Only the manager bot is visible in Zulip. The other roles remain internal.

## Workspace and Sandbox Model

The intended runtime model is:
- host project folder: `YOUR_PROJECT_WORKSPACE`
- mounted into the OpenClaw runtime as `/workspace`
- read-write access inside that mounted project workspace

This means the team can:
- read project files
- edit project files
- run project commands inside the sandbox

This does not mean:
- unrestricted access to arbitrary host directories
- a fully hardened security boundary for hostile inputs

For V1, this is a trusted local development model.

### Project Registry

In multi-project mode, the bridge can use a shared project registry instead of a
single fixed workspace.

The registry maps:
- project slug
- display name
- workspace path
- optional description

Each Zulip topic can then choose its active project with:
- `/project list`
- `/project use <slug>`
- `/project status`
- `/project clear`

## Zulip Model

### Stream Model

Use one software stream.

Recommended default:
- `YOUR_SOFTWARE_STREAM_NAME`: `software`

### Topic Model

Use one topic per software request.

Recommended topic format:
- `task: <short task name>`
- `bug: <short bug name>`
- `feature: <short feature name>`

### Visible Bot Model

Use one visible manager bot.

Recommended default:
- `YOUR_SOFTWARE_MANAGER_BOT_NAME`: `software-manager-bot`

This keeps the chat surface clean while preserving the internal team structure.

## Message Flow

1. Human posts a request in the software stream.
2. The bridge identifies the task run for that topic.
3. The bridge passes the task to the software manager.
4. In multi-project mode, the topic resolves its active project from the registry.
5. The software manager decides whether planner input is needed.
6. The internal software flow runs against the selected project workspace.
7. The software manager posts a summary back into the same topic.

## Human Interaction Model

The human should interact directly in the same Zulip topic.

Supported V1 interaction types:
- new request
- clarification
- redirect
- approval
- follow-up task
- stop or pause
- per-topic project selection

The bridge should interpret human replies conservatively.

## Project Workspace Requirements

The mounted project workspace should contain at minimum:
- the software project itself
- `PROJECT.md`

Recommended additional local files:
- `.agents/`
- `management/`
- task output or notes folders if needed

`PROJECT.md` should include:
- project summary
- current goal
- constraints
- acceptance criteria
- architecture notes
- key files
- setup/test/lint/typecheck/run commands
- risks and open questions

For the multi-project direction after V1:
- keep the shared runtime generic
- create one project folder from `project_template/` per project
- move `PROJECT.md` and `management/` into that project folder
- add project selection logic in the bridge or control plane

## Exit Condition for V1

V1 is successful when:
- a human can post a task in the software stream
- the bridge can invoke the software team
- the software team can update the mounted project workspace
- the manager bot can post a usable result back into the same Zulip topic
