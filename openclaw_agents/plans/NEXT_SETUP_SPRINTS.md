# Next Setup Sprints

## Goal

Complete the remaining post-foundation runtime setup in a controlled order:

1. Neo research depth
2. AgentSmith depth
3. real policy engine
4. Niaobe execution runtime
5. projection lifecycle completeness
6. memory hardening
7. operational hardening
8. Morpheus internal software loop
9. Planner / Implementer / Tester internal runtimes
10. cross-agent internal execution bring-up

## Sprint 1: Neo Research Upgrade

### Goal

Make Neo materially stronger at research, source handling, and external information retrieval.

### Scope

- better search result parsing and normalization
- fetched-page summarization
- multi-source research helper
- source-aware citation formatting
- optional external API connector surface for future integrations

### Todo

- `[done]` Upgrade `WebResearchService` result normalization and URL cleanup.
- `[done]` Add a multi-source research tool that can search and fetch in one runtime turn.
- `[done]` Add source metadata to research tool outputs.
- `[done]` Add citation-friendly reply behavior for Neo.
- `[done]` Add tests for multi-source research and source-aware answers.
- `[done]` Run a live Neo research runtime smoke probe with real Gemma + web access.
- `[pending]` Run a human-originated Zulip DM research smoke test when a non-bot sender path is available.

## Sprint 2: AgentSmith Depth

### Goal

Make AgentSmith a stronger free-form project manager instead of only a confirmation gate.

### Scope

- richer project-state editing
- planning/spec/task/milestone tools
- stronger reasoning over blockers, scope, and priorities

### Todo

- `[done]` Add project planning tools for milestones, backlog, and task surfaces.
- `[done]` Add spec/plan/task mutation helpers outside the gateway.
- `[done]` Expand AgentSmith prompt/runtime guidance for deeper PM behavior.
- `[done]` Add tests for free-form planning and project-management updates.
- `[done]` Verify project-thread projection for Smith-driven updates.

## Sprint 3: Policy Engine

### Goal

Replace shallow text classification with explicit per-agent policy profiles.

### Scope

- advisory vs executive vs bounded execution profiles
- action evaluation for research, execution, mutation, and escalation
- better enforcement of runtime boundaries

### Todo

- `[done]` Define structured policy decisions for allow / confirm / deny / escalate.
- `[done]` Implement profile-aware policy evaluation.
- `[done]` Route Neo and AgentSmith actions through the richer policy layer.
- `[done]` Add policy tests by agent profile.

## Sprint 4: Niaobe Execution Runtime

### Goal

Make Niaobe a real bounded execution agent driven by handoffs and execution state.

### Scope

- handoff consumption
- execution-state memory
- blocker handling
- execution progress projection

### Todo

- `[done]` Add execution-state memory/service for Niaobe.
- `[done]` Add handoff intake and execution-state transitions.
- `[done]` Add blocker/escalation behavior to AgentSmith.
- `[done]` Add projection events for execution start, block, and verification.
- `[done]` Add tests for handoff-to-execution flow.

## Sprint 5: Projection Lifecycle Completion

### Goal

Use the projection event model consistently across spec, plan, task, execution, and closeout flows.

### Scope

- broader event emission
- better rendering templates
- stronger canonical thread behavior

### Todo

- `[done]` Emit `spec_updated`, `tasks_updated`, `verification_reported`, and `project_closed` in real runtime flows.
- `[done]` Improve projection rendering templates by event type.
- `[done]` Add tests for event-specific projection rendering.

## Sprint 6: Memory Hardening

### Goal

Tighten memory boundaries so each agent sees the right context and no more.

### Scope

- stricter per-agent memory rules
- execution-state memory separation
- retention and cleanup behavior

### Todo

- `[done]` Add explicit memory access rules by agent/profile.
- `[done]` Keep Niaobe isolated from human conversational memory unless explicitly projected.
- `[done]` Add retention/cleanup rules for conversational and working memory.
- `[done]` Add tests for memory isolation and retention behavior.

## Sprint 7: Operational Hardening

### Goal

Make the runtime safer and easier to operate now that Neo can execute and mutate directly.

### Scope

- execution auditability
- safer execution controls
- better diagnostics and observability

### Todo

- `[done]` Add richer audit logging for execution and mutation actions.
- `[done]` Add stronger command execution guardrails.
- `[done]` Expand ops diagnostics for live runtime state.
- `[done]` Add restart and recovery validation for the expanded runtime.

## Sprint 8: Morpheus Internal Software Loop

### Goal

Make Morpheus the internal owner of the approved execution loop without changing the Zulip gateway boundary.

### Scope

- durable internal run state
- control-surface runtime dispatch
- bounded orchestration under Niaobe

### Todo

- `[done]` Add durable internal run storage outside Zulip.
- `[done]` Add Morpheus runtime profile, prompt, and model mapping.
- `[done]` Build the internal loop service and control-surface event path.
- `[done]` Keep Niaobe as the visible execution surface while Morpheus stays internal.

## Sprint 9: Planner / Implementer / Tester Internal Runtimes

### Goal

Add the first internal worker-team slice under Morpheus.

### Scope

- planner, implementer, and tester runtime agents
- workspace artifacts for internal plan / implementation / verification
- bounded escalation back through Niaobe and AgentSmith

### Todo

- `[done]` Add internal registry profiles and prompts for Planner, Implementer, and Tester.
- `[done]` Add policy profiles for internal read-only, implementation, and testing behavior.
- `[done]` Persist internal plan and implementation artifacts in the project workspace.
- `[done]` Route internal blockers back out through Niaobe to AgentSmith.
- `[done]` Add tests for the internal software loop and blocker escalation.

## Sprint 10: Cross-Agent Internal Execution Bring-Up

### Goal

Make the visible and internal runtimes work together coherently after handoff approval.

### Scope

- pending handoff intake
- internal run creation and stage advancement
- verification handoff back into execution state and projection events

### Todo

- `[done]` Start Morpheus runs from Niaobe-owned execution handoffs.
- `[done]` Advance internal stages across Morpheus, Planner, Implementer, and Tester.
- `[done]` Persist verification outcomes back into execution state outside Zulip.
- `[done]` Extend diagnostics and tests to cover internal run state.

## Recommended Execution Order

- Sprint 1: Neo Research Upgrade
- Sprint 2: AgentSmith Depth
- Sprint 3: Policy Engine
- Sprint 4: Niaobe Execution Runtime
- Sprint 5: Projection Lifecycle Completion
- Sprint 6: Memory Hardening
- Sprint 7: Operational Hardening
- Sprint 8: Morpheus Internal Software Loop
- Sprint 9: Planner / Implementer / Tester Internal Runtimes
- Sprint 10: Cross-Agent Internal Execution Bring-Up
