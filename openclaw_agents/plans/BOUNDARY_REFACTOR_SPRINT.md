# Boundary Refactor Sprint

## Goal

Move agent behavior out of the Zulip gateway and into runtime agents with explicit
memory classes, policy access, mutation services, and projection events.

## Scope

- transport-only Zulip gateway
- runtime agent registry
- separated conversational, project, and working memory
- first-class projection event model
- runtime agents for `neo`, `agent_smith`, and `niaobe`
- preservation of current foundation demo path

## Sprint Backlog

- `[done]` Define boundary refactor scope and registry shape.
- `[done]` Add sprint plan and backlog artifact.
- `[done]` Add agent registry fields for runtime access and memory policy.
- `[done]` Add separated conversation and working memory services.
- `[done]` Add projection event persistence service and event taxonomy.
- `[in_progress]` Refactor gateway to dispatch to runtime agents instead of owning behavior.
- `[pending]` Add broader agent runtime integration beyond the current heuristic bootstrap.
- `[pending]` Add explicit policy engine profiles per agent.
- `[pending]` Add live model/tool runner behind the runtime contracts.

## Cut Line

This sprint does not implement the final LLM-backed free-form agent runtime.
It establishes the correct architecture and migrates the current foundation
behavior to that architecture.
