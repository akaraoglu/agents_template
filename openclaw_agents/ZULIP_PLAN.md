# Zulip Integration Plan

This document defines the target architecture for using Zulip as the human UI
and discussion layer for the local agent teams in `openclaw_agents/`.

Use this plan together with:
- `ZULIP_SETUP_GUIDE.md` for server installation, account creation, and human UI usage
- `PROJECT.md` for project-specific goals, constraints, and commands

## Purpose

The goal is to add a human-visible collaboration surface where:
- humans can watch research and software discussions
- humans can intervene before the agents drift
- research and software teams can hand work to each other
- the repository remains the durable source of truth for project artifacts

This plan separates:
- Zulip as the conversation surface
- a bridge service as the integration layer
- the research and software teams as execution backends

## Goals

- Run Zulip locally on the same machine with Docker Compose.
- Keep Zulip operationally separate from the OpenClaw sandbox runtime.
- Add a bridge service that is the only component talking to both Zulip and the agent teams.
- Support human-in-the-loop checkpoints and intervention.
- Preserve durable artifacts in repository files instead of relying on chat history alone.
- Start with a narrow and stable v1, then expand.

## Non-Goals

- Do not embed Zulip inside the OpenClaw sandbox image.
- Do not let every agent connect directly to Zulip in v1.
- Do not attempt a fully autonomous multi-agent research loop in the first phase.
- Do not make Zulip the only place where important project state exists.

## Target Architecture

The target system has four major parts:

1. Zulip stack
- self-hosted Zulip server running with Docker Compose
- persistent data, admin UI, channels, topics, bot accounts, and human accounts

2. Bridge service
- one service that listens to Zulip and calls the agent teams
- responsible for run state, message routing, checkpoints, and posting results

3. Research team
- `research-manager`
- `explorer`
- `skeptic`
- `feasibility`

4. Software team
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

The bridge is responsible for:
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

The recommended local deployment shape is:

- one Zulip Compose project
- one agent/orchestrator environment
- one bridge service
- one shared Docker network

Recommended network:
- `agentnet`

Recommended service grouping:
- `zulip` stack
- `zulip-bridge`
- local agent runtime and wrappers

### Important Constraint

Zulip should not be baked into the same Docker image used as the OpenClaw
sandbox image. The OpenClaw sandbox image is a task execution environment. Zulip
is a long-running web application with different operational needs.

## Communication Model

Communication should happen through a single bridge service.

Recommended flow:
- Zulip -> bridge via Zulip bot/event API
- bridge -> research or software manager via local wrappers or API
- manager/team output -> bridge
- bridge -> Zulip via bot message API

This keeps the integration controllable and avoids giving every agent direct
network credentials.

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

Recommended initial channels:
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
- one owner or admin account for you
- one backup admin account if available

Recommended bot accounts:
- `research-manager-bot`
- `explorer-bot`
- `skeptic-bot`
- `feasibility-bot`
- `software-manager-bot`

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

Zulip should reflect those artifacts, not replace them.

## Message Routing Model

### Research flow

1. Human posts an idea in `research`.
2. Bridge decides whether this starts a new run or continues an existing one.
3. Bridge sends the task to `research-manager`.
4. `research-manager` coordinates a round across `explorer`, `skeptic`, and `feasibility`.
5. Bridge posts visible round output into the same Zulip topic.
6. Bridge pauses for human feedback at the configured checkpoint.
7. If approved, bridge asks the research team for an `IMPLEMENTATION_BRIEF`.
8. Bridge hands the brief to the software team.

### Software flow

1. Bridge posts the brief in `software`.
2. Bridge invokes the software manager.
3. Software manager runs planner, coder, and tester as needed.
4. Bridge posts progress summaries or final result into the Zulip topic.
5. Bridge stores or updates `IMPLEMENTATION_RESULT`.
6. Bridge sends the result back to the research side for review.

## Control Model

The bridge should interpret human messages conservatively.

Recommended control actions:
- approve
- redirect
- clarify
- stop
- send to software
- send back to research

Recommended v1 rule:
- only explicit control phrases or clearly directed replies should alter run state

## Security and Operational Rules

- Keep Zulip and agent runtime separated by service boundary.
- Give Zulip credentials only to the bridge, not to every agent.
- Keep bot API keys outside git.
- Keep human admins separate from bot identities.
- Keep TLS simple for the first local boot, then harden later.
- Keep the v1 deployment local and trusted.

## Rollout Phases

### Phase 1: Zulip installation and workspace foundation
- install Zulip with Docker Compose
- create the first organization
- create the first human admin
- create the initial channels
- create the first bot accounts
- confirm basic browser and bot access

### Phase 2: Single-bot bridge prototype
- add a bridge service
- connect one bot account
- read one Zulip topic
- post one response back
- test a single manager loop

### Phase 3: Research team integration
- expose the research manager through the bridge
- add round-based research discussion
- add human checkpoints after each round
- add brief generation and storage

### Phase 4: Software team handoff
- connect the software manager
- route implementation briefs to software
- collect result summaries
- post software results back to Zulip

### Phase 5: Multi-team iteration loop
- add research review of software results
- add redirect and stop controls
- add run tracking and recoverable state
- harden the bridge and operator workflow

## Phase 1 Sprint Plan

This sprint turns the plan into a working local Zulip foundation.

### Sprint goal

Bring up a local Zulip server on this machine with Docker Compose, create the
first human and bot accounts, establish the initial channel structure, and
confirm that the environment is ready for bridge work in the next sprint.

### Sprint outcome

At the end of Phase 1, you should be able to:
- open Zulip in a browser
- log in as the human admin user
- create or review channels and topics
- see the starting workspace structure
- manage bot accounts for the upcoming bridge integration

### In scope

- local Docker Compose based Zulip deployment
- config and secret setup
- first boot and organization creation
- human admin access
- channel creation
- bot account creation
- a minimal operating checklist for manual verification

### Out of scope

- bridge service implementation
- real-time event consumption
- software team integration
- research team integration
- SMTP, SSO, reverse proxy, and production hardening

### Sprint stories

#### SP1-1: Prepare the local deployment
- confirm target host and deployment directory
- clone the official `docker-zulip` repository
- create `zulip-settings.env`
- create `.env` with secrets
- create `compose.override.yaml`

#### SP1-2: Bring up Zulip successfully
- pull the required images
- run `app:init`
- start Zulip
- confirm the containers are healthy
- confirm the login URL is reachable

#### SP1-3: Establish human access
- generate the organization creation link
- create the first organization
- create the first human admin user
- verify login and basic navigation

#### SP1-4: Establish initial workspace structure
- create `research`
- create `software`
- create `human-feedback`
- create `ops`
- define the first topic naming convention

#### SP1-5: Establish bot identities
- create the initial agent-facing bot accounts
- document which bot is reserved for which team role
- capture and securely store the bot credentials

#### SP1-6: Validate readiness for Phase 2
- verify browser access
- verify admin access
- verify the channels exist
- verify the bots exist
- verify the deployment can be restarted cleanly

### Work breakdown

#### Workstream A: Deployment
- select deployment root on this machine
- install configuration files
- initialize and boot the Compose stack
- capture the commands used in a local runbook

#### Workstream B: Access and administration
- create the organization
- create the first human admin
- document the manual login and navigation path
- verify the admin can manage users and bots

#### Workstream C: Workspace conventions
- create the initial channels
- document the intended topic naming format
- define the initial human intervention pattern

#### Workstream D: Bot preparation
- create the first bot accounts
- assign intended usage to each bot
- store secrets in a safe local place

### Deliverables

- running local Zulip Compose deployment
- local configuration files for Zulip
- one admin user
- initial channels
- initial bot accounts
- updated repo documentation for setup and planning

### Validation checklist

- `docker compose run --rm zulip app:init` succeeds
- `docker compose up zulip --wait` succeeds
- the organization creation link is generated successfully
- the admin user can log in through the browser
- the admin user can access organization settings
- the initial channels exist
- the bot accounts exist
- the deployment can be stopped and started again without losing state

### Risks

- local hostname and TLS confusion during the first boot
- incomplete secret configuration
- bot creation permissions not set as intended
- over-designing channels before the bridge exists

### Mitigations

- use a simple local-first hostname for v1
- keep TLS simple for the first local boot
- keep the first workspace small
- create only the minimum set of bots needed for the next phase

### Exit criteria

Phase 1 is complete when:
- Zulip is running locally in Docker
- you can log in as the admin user
- the initial channels are present
- the initial bot accounts are created
- the deployment is stable enough for Phase 2 bridge work

## Proposed Phase 1 Task Order

1. Choose the local deployment directory and hostname.
2. Clone `docker-zulip`.
3. Create `zulip-settings.env`, `.env`, and `compose.override.yaml`.
4. Run initialization and bring the stack up.
5. Generate the organization creation link.
6. Create the first organization and admin user.
7. Create channels and bot accounts.
8. Perform the Phase 1 validation checklist.

## Phase 1 Open Questions

- What hostname do you want to use for the first local install?
- Where should the Zulip deployment directory live on this machine?
- Do you want only one human admin initially, or two?
- Do you want visible bot identities for every role in v1, or only manager-facing bots?

## Next Planning Artifact

After Phase 1 is complete, the next document should define the v1 bridge design:
- service layout
- runtime environment
- Zulip event handling
- message schemas
- topic-to-run mapping
- pause, resume, and redirect rules
