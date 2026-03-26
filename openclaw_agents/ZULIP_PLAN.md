# Zulip Integration Plan

This document defines the target architecture for using Zulip as the human UI
and discussion layer for the local agent teams in `openclaw_agents/`.

## Template Variables

Replace these values for each deployment:
- `YOUR_ZULIP_WORKDIR`: host directory used for the Zulip deployment workspace
- `YOUR_PROJECT_WORKSPACE`: host path to the mounted software project workspace
- `YOUR_SOFTWARE_STREAM_NAME`: Zulip stream used for software requests
- `YOUR_SOFTWARE_MANAGER_BOT_NAME`: visible manager bot display name

Recommended defaults for this template:
- `YOUR_SOFTWARE_STREAM_NAME`: `software`
- `YOUR_SOFTWARE_MANAGER_BOT_NAME`: `software-manager-bot`

Use this plan together with:
- `ZULIP_SETUP_GUIDE.md`
- `ZULIP_V1_SOFTWARE_TEAM.md`
- `PROJECT.md`

## Purpose

The goal is to add a human-visible collaboration surface where:
- humans can watch research and software discussions
- humans can intervene before the agents drift
- research and software teams can hand work to each other
- the repository remains the durable source of truth for project artifacts

This plan separates:
- Zulip as the conversation surface
- persona and team bridges as the integration layer
- the research and software teams as execution backends

## Goals

- Run Zulip locally or privately with Docker Compose.
- Keep Zulip operationally separate from the OpenClaw sandbox runtime.
- Add bridge services that are the only components talking to both Zulip and the agent runtimes.
- Support human-in-the-loop checkpoints and intervention.
- Preserve durable artifacts in repository files instead of relying on chat history alone.
- Start with a narrow and stable V1, then expand.

## Current Chosen V1

The first implementation is intentionally narrow.

Chosen V1:
- one Zulip software stream
- one visible manager bot
- one mounted project workspace
- one internal software team:
  `manager`, `planner`, `coder`, `tester`

Deferred beyond V1:
- research team
- multi-team iteration loop
- visible worker bots

See `ZULIP_V1_SOFTWARE_TEAM.md` for the concrete V1 design.

## Non-Goals

- Do not embed Zulip inside the OpenClaw sandbox image.
- Do not let every agent connect directly to Zulip in V1.
- Do not make Zulip the only place where important project state exists.

## Target Architecture

The target system has four major parts:

1. Zulip stack
- self-hosted Zulip server running with Docker Compose
- persistent data, admin UI, streams, topics, bot accounts, and human accounts

2. Persona bridge
- one shared multi-bot service for human-facing personas
- handles DMs, group DMs, selected streams, status, and stop control

3. Team bridge
- one service that listens to Zulip and calls the execution teams
- responsible for run state, message routing, checkpoints, and posting results

4. Research team
- `research-manager`
- `explorer`
- `skeptic`
- `feasibility`

5. Software team
- `manager`
- `planner`
- `coder`
- `tester`

## System Boundaries

Zulip is responsible for:
- visible discussion
- human participation
- bot identities
- reviewable conversation history

The persona bridge is responsible for:
- reading Zulip events for discussion personas
- routing DMs and stream discussions to the correct persona runtime
- posting persona replies under the correct bot identity
- enforcing stream-level invocation rules

The team bridge is responsible for:
- reading Zulip events
- deciding whether a message starts, continues, redirects, or stops a run
- turning chat messages into agent tasks
- posting structured agent outputs back into Zulip
- enforcing human checkpoints

The repository is responsible for:
- project context in `PROJECT.md`
- durable work artifacts
- implementation outputs
- planning and operating documentation

The agent runtimes are responsible for:
- reasoning
- planning
- coding
- testing
- producing summaries and artifacts

## Container Layout

Recommended deployment shape:
- one Zulip Compose project
- one agent/orchestrator environment
- one persona bridge service
- one team bridge service
- one shared Docker network when needed

Important constraint:
- Zulip should not be baked into the same Docker image used as the OpenClaw sandbox image

## Communication Model

Communication should happen through bridge services, not directly from every
agent.

Recommended flow:
- Zulip -> persona bridge for DM-able and room-visible discussion personas
- Zulip -> team bridge for manager-led execution teams
- bridge -> persona or team runtime via local wrappers or API
- runtime output -> bridge
- bridge -> Zulip via bot message API

## Human-in-the-Loop Model

Humans should be able to:
- read every visible round
- intervene in the same topic
- redirect the team
- stop a run
- approve a handoff
- send work back to research or software

Human intervention should happen at explicit checkpoints:
- after each research round
- before sending an implementation brief to software
- after software delivers a result
- before starting another iteration

## Zulip Workspace Model

Recommended initial streams:
- `research`
- `software`
- `human-feedback`
- `ops`

Recommended topic naming:
- `idea: <name>`
- `brief: <name>`
- `review: <name>`
- `redirect: <name>`

Recommended human accounts:
- one owner or admin account
- one backup admin account if available

Recommended bot accounts:
- `research-manager-bot`
- `explorer-bot`
- `skeptic-bot`
- `feasibility-bot`
- `software-manager-bot`

Recommended persona bots:
- `agentsmith-bot`
- `yoda-bot`
- `architect-bot`

Optional later:
- `planner-bot`
- `coder-bot`
- `tester-bot`

## Durable Artifacts

The bridge and teams should treat the repository as the durable source of truth.

Recommended artifacts:
- `PROJECT.md`
- `IDEA.md`
- `IMPLEMENTATION_BRIEF.md`
- `IMPLEMENTATION_RESULT.md`
- `RESEARCH_LOG.md`

## Security and Operational Rules

- Keep Zulip and the agent runtime separated by service boundary.
- Give Zulip credentials only to the bridge, not to every agent.
- Keep bot API keys outside git.
- Keep human admins separate from bot identities.
- Prefer secure defaults in committed examples.
- Keep local-development overrides, such as self-signed TLS exceptions, out of the template defaults where possible.

## Rollout Phases

### Phase 1
- install Zulip with Docker Compose
- create the first organization
- create the first human admin
- create the initial streams
- create the first bot accounts

### Phase 2
- prepare the bridge runtime
- connect one software stream to the software manager
- verify one task end-to-end

### Phase 3
- add checkpoints and clearer operator controls
- expand to research-team workflows if needed
