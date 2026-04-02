# Agent System V3

This document defines the current multi-agent model for this template.

Use V3 when you want:
- all visible agents DM-able
- direct user access to any visible role
- cross-agent coordination to stay visible in Zulip
- future multi-agent group discussions in chat
- no nested agent spawning inside agent sandboxes

Runtime reference:
- `zulip_gateway_v3/README.md`

## Core Principles

### Zulip Is The Communication Bus

Agents communicate through Zulip messages:
- DMs
- stream topics
- structured handoffs
- status updates
- results
- decisions

Do not treat in-sandbox spawning as the primary communication mechanism.

### The Host Gateway Is The Execution Layer

The host-side Zulip gateway should:
- map Zulip bots to roles
- receive DMs, mentions, and structured handoffs
- launch the right local wrapper on the host
- post results back as the correct bot
- keep only light thread coordination state

The gateway should not depend on one agent sandbox being able to launch
another sandbox.

### Roles Are Defaults, Not Cages

Roles define default behavior, not hard restrictions.

Examples:
- `Architect` defaults to planning and docs
- `Morpheus` defaults to software execution
- `Oracle` defaults to validation

But each visible role may still answer a direct human DM in its own voice and
then either handle the task or hand it off.

### All Visible Roles Are DM-able

Recommended DM-able roles:
- `AgentSmith`
- `Neo`
- `Yoda`
- `Niaobe`
- `Architect`
- `Morpheus`
- `Oracle`

Each of these should be able to:
- receive direct tasks from the human
- reply directly
- emit a structured handoff if another role should continue

### Use Light Thread Coordination, Not Strict Topic Ownership

V3 does not require strict topic ownership.

Instead, keep only minimal per-thread state:
- `active_run_id`
- `current_speaker`
- `awaiting_from`
- `participants`
- `mode`

This is enough to keep conversations readable without turning the system into a
heavy workflow engine.

## Visible Roles

### AgentSmith

Default behavior:
- intake
- discussion
- clarification
- routing and handoff
- general operator assistant

### Neo

Default behavior:
- direct technical execution
- debugging and implementation
- code review and refactoring
- broad assistant work without needing the full team

### Niaobe

Default behavior:
- project management
- project planning coordination
- project-level decisions
- deciding whether to call `Architect`, `Morpheus`, or `Oracle`

### Yoda

Default behavior:
- strategic advice
- critique
- reframing
- second opinion
- calm challenge to hasty or fear-driven thinking

### Architect

Default behavior:
- planning
- milestones
- stories
- tasks
- acceptance criteria
- project document updates

### Morpheus

Default behavior:
- software execution
- internal team orchestration
- progress reporting

### Oracle

Default behavior:
- validation
- QA review
- evidence-driven acceptance or rejection

## Communication Model

### Direct DMs

Any visible role may receive work directly from:
- the human
- another agent through a handoff

### Shared Topics

In shared topics, an agent should reply only when:
- directly mentioned
- directly handed work
- already in an active exchange

This keeps shared discussions readable and avoids bot pile-ons.

### Group Discussions

Multi-agent discussion topics are valid, but they should be deliberate:
- create a topic for the discussion
- mention or invite the needed roles
- let the gateway coordinate replies using the light thread state

Do not let every visible bot auto-reply to every shared topic by default.

## Minimal Message Contract

V3 only needs four visible message types:
- `HANDOFF`
- `STATUS`
- `RESULT`
- `DECISION`

Minimum useful fields:
- `TYPE`
- `FROM`
- `TO`
- `PROJECT`
- `SUMMARY`
- `NEXT`

Example:

```text
TYPE: HANDOFF
FROM: AgentSmith
TO: Niaobe
PROJECT: denoising-jbu
SUMMARY: Take ownership of Phase 2 planning and decide whether software work should start.
NEXT: Review the current docs and decide whether Architect or Morpheus should run next.
```
