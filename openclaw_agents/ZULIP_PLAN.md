# Zulip Integration Plan

This document defines the current recommended Zulip architecture for
`openclaw_agents/`.

Use this together with:
- `ZULIP_SETUP_GUIDE.md`
- `ZULIP_V3_GATEWAY_SETUP.md`
- `AGENT_SYSTEM_V3.md`
- `ZULIP_PROJECT_WORKFLOW.md`
- `PROJECT.md`

## Recommended Default

The current recommended deployment is V3:
- one Zulip server
- one host-side `zulip_gateway_v3` process
- DM-able visible roles:
  `AgentSmith`, `Neo`, `Yoda`, `Niaobe`, `Architect`, `Morpheus`, `Oracle`
- one prepared OpenClaw workspace or project registry
- one internal software team behind `Morpheus`:
  `manager`, `planner`, `coder`, `tester`

## Purpose

The goal is to use Zulip as the human-visible coordination layer where:
- humans can DM any visible role directly
- cross-agent handoffs remain visible in chat
- project progress is readable without inspecting hidden gateway state
- durable artifacts still live in repository files, not only in chat history

## Architecture

### 1. Zulip Stack

Zulip provides:
- DMs
- streams and topics
- bot identities
- human intervention and chat history

### 2. V3 Gateway

The host-side V3 gateway:
- listens to multiple bot accounts in one process
- routes DMs, mentions, and visible `HANDOFF` blocks
- launches the configured local wrapper for the addressed role
- posts replies as the correct bot
- keeps light thread coordination state only

### 3. Local Role Runtime

The prepared OpenClaw workspace provides the visible-role wrappers:
- `run_assistant.sh`
- `run_neo.sh`
- `run_yoda.sh`
- `run_projectmanager.sh`
- `run_architect.sh`
- `run_morpheus.sh`
- `run_oracle.sh`

It also provides the internal software-team wrappers and prompts.

### 4. Project Workspace

The repository remains the durable source of truth:
- `PROJECT.md`
- `projects/<slug>/PROJECT.md`
- `projects/<slug>/management/...`
- implementation code and test artifacts

## Communication Model

Recommended flow:
1. Human sends a DM or stream message in Zulip.
2. The V3 gateway routes it to the addressed role.
3. The local wrapper runs on the host.
4. The role replies visibly in Zulip.
5. If the reply includes an authorized `HANDOFF`, the gateway launches the next
   role and keeps the thread visible.

Do not rely on nested in-sandbox spawning as the primary orchestration model.

## Recommended Streams

Minimum:
- `assistant`
- `projects`
- `software`

Optional later:
- `ops`
- `validation`
- `council`

## Recommended Bot Accounts

- `agentsmith-bot`
- `neo-bot`
- `yoda-bot`
- `niaobe-bot`
- `architect-bot`
- `morpheus-bot`
- `oracle-bot`

## Human-In-The-Loop Model

Humans should be able to:
- DM any visible role directly
- intervene in the same topic
- redirect the next role
- request status or stop a run
- follow visible handoffs without guessing who acted next

## Rollout Phases

### Phase 1
- install Zulip
- create the first organization
- create the streams
- create the visible bot accounts

### Phase 2
- prepare the OpenClaw workspace and visible-role wrappers
- create the V3 gateway config and agent registry
- validate `run_gateway.sh --check`

### Phase 3
- install `zulip-gateway-v3.service`
- start the gateway
- verify one DM and one visible handoff end to end
