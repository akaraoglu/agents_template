# Neo OpenAI OAuth Agent Plan

This document designs `Neo`, a broader host-backed assistant that plugs into
the V3 Zulip gateway and runs through an OpenAI OAuth OpenClaw runtime instead
of the local Docker-backed runtime.

## Template Variables

Replace these values for each deployment:
- `YOUR_NEO_WORKSPACE`
- `YOUR_NEO_BOT_EMAIL`
- `YOUR_OPENAI_OAUTH_PROFILE`

Use this plan when:
- OpenClaw is already signed in with your OpenAI OAuth account
- the agent should run against a writable host workspace
- the agent should be stronger and broader than `AgentSmith`
- the agent should still fit the V3 Zulip/gateway model cleanly

## Goal

`Neo` should be a high-capability, general-purpose operator that can:
- answer directly in DMs
- inspect and edit files in the workspace
- run project commands and tests
- complete many tasks end to end without involving the full team
- still hand work to `Yoda`, `Niaobe`, `Architect`, `Morpheus`, or `Oracle`
  when specialization is the better move

`Neo` is not just another front door. He is a direct-execution assistant.

## Position In The Role System

Recommended role split:
- `AgentSmith`: front door, intake, routing, short discussion
- `Neo`: broader senior operator and direct executor
- `Yoda`: second opinion, critique, reframing
- `Niaobe`: project manager
- `Architect`: planner
- `Morpheus`: software team manager
- `Oracle`: validation

Best rule:
- `Smith` stays the lightweight router
- `Neo` is the heavy-duty assistant who can often do the work himself

## Runtime Model

`Neo` should not run in Docker.

Recommended runtime shape:
- host-backed OpenClaw OAuth login
- writable workspace rooted at `YOUR_NEO_WORKSPACE`
- no Docker sandbox for Neo
- wrapper entrypoint at `.agents/run_neo.sh`
- runtime helper at `.agents/scripts/run_openai_oauth_host_runtime.sh`

This means:
- host-backed writable workspace
- no Docker sandbox for Neo
- uses the existing OpenClaw OAuth login state
- can edit files directly in the workspace folder

## Neo’s Role

Recommended identity:
- pragmatic
- technically deep
- direct
- execution-oriented
- capable of planning, coding, review, and debugging

He should feel:
- broader than `AgentSmith`
- more hands-on than `Niaobe`
- less specialized than `Architect`, `Morpheus`, or `Oracle`

## What Neo Should Do

Default responsibilities:
- code inspection
- code changes
- debugging
- implementation planning
- test execution
- code review
- documentation updates
- repo-level task execution inside the workspace
- status reporting and visible handoffs in Zulip

Good examples:
- "Inspect this bug and fix it."
- "Refactor this module safely."
- "Review this PR-sized change."
- "Trace why this workflow breaks."
- "Implement this feature directly."

## What Neo Should Not Do

Default exclusions:
- hidden project-manager loops
- silent multi-agent orchestration
- destructive git actions by default
- system-wide admin work outside the workspace
- credential rotation or bot/user management
- acceptance authority that belongs to `Oracle`

If a task is clearly better owned by another role:
- hand off visibly
- do not pretend to have done the handoff internally

## Capability Design

Recommended handoff targets:
- `yoda`
- `niaobe`
- `architect`
- `morpheus`
- `oracle`

Recommended callers:
- `human`
- `agentsmith`
- optionally `niaobe`

## Zulip Design

`Neo` should be fully DM-able.

Recommended bot:
- `neo-bot`

Recommended streams:
- `assistant`
- `projects`
- `software`
- optional `ops`

Recommended reply mode:
- `dm_or_mention`

Recommended mention triggers:
- `neo`

Recommended behavior:
- in DMs, Neo can work directly
- in shared streams, Neo should answer when mentioned, handed work, or already
  active in the exchange

## Prompt Design

Neo’s prompt should emphasize:
- do the work directly when the request is clear
- be technically rigorous
- prefer narrow, correct edits over vague summaries
- explain decisions concisely
- hand off only when specialization is clearly better
- operate only within the workspace boundary

Suggested personality:
- calm
- highly competent
- low-drama
- not theatrical
- less managerial than Smith
- more operator-like than Smith

## Wrapper Design

Recommended wrapper:
- `.agents/run_neo.sh`

Recommended prompt:
- `.agents/prompts/neo.txt`

Recommended runtime adapter:
- `.agents/scripts/run_openai_oauth_host_runtime.sh`

That wrapper should:
1. select the `neo` role
2. use the OpenAI OAuth host runtime
3. mount or target `YOUR_NEO_WORKSPACE`
4. preserve the active project selection env vars

## Required Wiring

To add Neo to a deployment:
1. add `.agents/prompts/neo.txt`
2. add `.agents/run_neo.sh`
3. keep `.agents/scripts/run_openai_oauth_host_runtime.sh`
4. add `neo` to `.agents/openclaw.template.json` if needed by the local config
5. add `neo-bot` to `zulip_gateway_v3/agent_registry.example.json`
6. allow `AgentSmith` to hand off to `Neo` if desired
7. store `neo-bot` credentials in the gateway `private/` directory

### Gateway Entry

```json
{
  "neo": {
    "display_name": "Neo",
    "zuliprc_path": "./private/neo-bot.zuliprc",
    "run_command": ["bash", ".agents/run_neo.sh"],
    "workspace": "YOUR_NEO_WORKSPACE",
    "allow_dm": true,
    "allowed_streams": ["assistant", "projects", "software"],
    "reply_mode": "dm_or_mention",
    "mention_triggers": ["neo"],
    "loops": ["discussion", "execution", "review"],
    "skills": ["inspect", "edit", "run", "review", "handoff"],
    "can_handoff_to": ["yoda", "niaobe", "architect", "morpheus", "oracle"],
    "description": "Broad OpenAI-backed operator assistant for direct execution in the host workspace."
  }
}
```

## Guardrails

To keep Neo useful without turning him into a dangerous shell:
- workspace writes allowed only under `YOUR_NEO_WORKSPACE`
- no implicit `sudo`
- no destructive git commands by default
- no bot account management
- no secret material dumping
- no silent orchestration loops
- explicit visible handoff when another role should continue

## Best Usage Model

Good default usage:
- you DM `Neo` directly when you want real work done
- `Smith` sends work to `Neo` when the task is broader than triage and narrower
  than a full project loop
- `Neo` sends project coordination to `Niaobe`
- `Neo` sends specialized planning to `Architect`
- `Neo` sends big implementation batches to `Morpheus`
- `Neo` sends final truth-checking to `Oracle`
- `Neo` asks `Yoda` for second opinions or strategy critique

## Rollout Plan

### Phase 1
- create `neo-bot`
- add `neo-bot.zuliprc`
- add `.agents/prompts/neo.txt`
- add `.agents/run_neo.sh`
- keep `.agents/scripts/run_openai_oauth_host_runtime.sh`

### Phase 2
- add `neo` to the V3 gateway registry
- add `neo` to Smith’s allowed handoff targets

### Phase 3
- verify Neo can edit files in `YOUR_NEO_WORKSPACE`
- verify a DM to Neo completes a real task end to end

### Phase 4
- tune prompt and guardrails based on real usage
- decide whether Neo should stay advisory-plus-execution or become the default
  primary assistant

## Recommendation

Do not try to make Neo a replacement for every other role.

Best design:
- `Smith` remains the lightweight visible router
- `Neo` becomes the strong direct-execution assistant
- the specialist roles remain available when they are actually better

That gives you a wider, stronger assistant without collapsing the whole system
into one all-powerful bot.
