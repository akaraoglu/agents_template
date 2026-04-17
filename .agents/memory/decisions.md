# Decisions Log

Record durable behavior and tooling decisions here.

## 2026-04-16
- Decision: Project-level `handoff_status` must track the authoritative handoff record whenever a handoff status changes.
- Rationale: Live execution validation showed that stale copied handoff status in project state becomes misleading once Niaobe advances or blocks a handoff.
- Constraint: Keep handoff status updates in the authoritative state layer and mirror them into project state during `update_handoff`, rather than relying on one-time persistence at handoff creation.

## 2026-04-17
- Decision: The long-term workspace root for the system is `~/workspace/clawspace`, and project execution agents should be sandboxed to their assigned project directory inside that root.
- Rationale: User wants a single bounded system workspace plus per-project isolation to reduce context bleed and keep each execution agent focused on one project surface.
- Constraint: Keep system-level services and shared state under the bounded `clawspace` root, place all project workspaces beneath it, and ensure Niaobe/internal worker agents execute against project-scoped paths rather than the full multi-project tree.

- Decision: `openclaw_agents/` must remain only the agent/team-system codebase; no project workspaces, runtime project artifacts, or project state should live under it. Use Option A for the migration.
- Rationale: User wants a clean separation between the agent-system implementation repo and the operational/project data managed by that system.
- Constraint: Keep source code in this repo, but relocate runtime roots, state, logs, mappings, artifacts, and all project directories to `~/workspace/clawspace`.

- Decision: Morpheus and the internal Planner/Implementer/Tester agents run on a control surface below Zulip, while Niaobe remains the visible execution surface for approved handoffs.
- Rationale: The internal software loop needed to be added without expanding the Zulip transport boundary or turning internal worker chatter into visible bot traffic.
- Constraint: Keep internal stage state durable outside Zulip, project any human-visible execution changes through formal projection events, and route blockers back out through Niaobe to AgentSmith.

- Decision: Neo web research must degrade to source-bearing search snippets when page fetches fail, rather than failing the whole research turn.
- Rationale: Live Zulip research needs to stay conversationally useful and source-grounded even when a subset of outbound fetches hit transient network or DNS errors.
- Constraint: Retry transient fetch failures first, record failures for diagnostics, and preserve normalized source metadata from search results when full-page retrieval is unavailable.

- Decision: The live Zulip runtime ignores bot-originated inbound messages; live smoke validation must use a human-originated sender path.
- Rationale: The runtime drops bot senders to avoid bot loops, so bot-to-bot DMs do not exercise the intended human-visible flow.
- Constraint: For live Zulip smoke checks, use a real human account or a server-side human-originated message injection path.

- Decision: Niaobe execution-state transitions are persisted as authoritative records outside Zulip and use durable statuses such as `IN_PROGRESS`, `BLOCKED`, and `VERIFICATION_REPORTED`.
- Rationale: Sprint 4 and Sprint 7 needed execution progress, blocker handling, restart recovery, and diagnostics to work without depending on chat history.
- Constraint: Advance execution only from persisted handoffs, and derive project-thread visibility from projection events rather than Zulip message state.

- Decision: Zulip `stream_topic` transport events are normalized to the logical `project_topic` surface before policy checks.
- Rationale: The bridge/runtime boundary uses transport event names that differ from the registry/policy vocabulary, and matching them directly incorrectly denies valid topic execution flows.
- Constraint: Keep transport naming and policy surface naming separate; normalize before evaluating surface access.

- Decision: Policy enforcement now lives in explicit per-agent policy profiles that evaluate both tool calls and structured action intents.
- Rationale: Sprint 3 required side-effect safety to move out of shallow text classification and into a durable runtime boundary that does not narrow free-form conversation.
- Constraint: Keep the gateway transport-only; apply allow/confirm/deny/escalate decisions inside runtime/services.

- Decision: Niaobe consumes persisted execution handoffs through background runtime work, creates durable execution-state records, and uses projection events plus escalation messages to expose execution progress and blockers.
- Rationale: Sprint 4 required Niaobe to become a real bounded execution agent without turning the gateway into an orchestrator.
- Constraint: Start execution only from persisted handoffs and execution state; do not treat human chat as execution truth.

- Decision: Projection rendering is event-specific and derived from first-class projection events rather than generic summary posting.
- Rationale: Sprint 5 required canonical project-thread behavior to be durable and type-aware across kickoff, change, execution, verification, and closeout flows.
- Constraint: Add new projection behavior by introducing or extending event types, not by adding ad hoc gateway message branches.

- Decision: Conversational memory, working memory, and execution-state memory are separate runtime surfaces with profile-based access and retention handling.
- Rationale: Sprint 6 required bounded agents such as Niaobe to stay isolated from human conversational context while preserving continuity for Neo and AgentSmith.
- Constraint: Never load conversational memory for profiles that declare `conversational_memory: none`.

- Decision: Direct execution and mutation paths must emit audit records and pass command guardrails before running.
- Rationale: Sprint 7 required Neo's executive power to be paired with stronger observability and safer execution boundaries.
- Constraint: Keep destructive command patterns blocked inside the command runner and preserve audit history outside Zulip.

- Decision: Limit all implementation changes to `openclaw_agents/` for this repository context.
- Rationale: User-provided scope boundary for where feature and fix work should be placed.
- Constraint: Do not edit outside `/home/alik/workspace/agent_template`.

- Decision: The Zulip bridge for this system is implemented and run only from `openclaw_agents/communication/`; legacy bridge code under `/home/alik/workspace/zulip` is reference-only and not a runtime dependency.
- Rationale: User required a fresh bridge implementation for the foundation instead of carrying forward old bridge code or runtime paths.
- Constraint: New Zulip runtime work must preserve the current foundation contracts and avoid coupling to the legacy bridge folder.

- Decision: Skills are capability surfaces, not conversational restrictions; Neo and AgentSmith must remain free-form agents, and safety must come from policy gating on side effects rather than scripted conversation handlers.
- Rationale: User clarified that the current hardcoded Neo behavior is too narrow and that future design must preserve broad discussion, research, and tool use.
- Constraint: Do not encode Neo or AgentSmith as keyword routers in the gateway layer.

- Decision: The gateway owns transport mechanics only. It must not decide agent behavior, workflow behavior, handoff semantics, or project-management logic for any agent.
- Rationale: User clarified that Zulip is only the communication surface and that agent freedom, project handoff, and workflow logic belong outside the gateway.
- Constraint: Keep the gateway limited to message normalization, delivery, mapping, queue/retry/recovery, and projection of already-decided outputs.

- Decision: Treat memory as three separate classes: conversational memory (short-lived DM/thread context), project memory (durable authoritative project state/history), and agent working memory (temporary scratch/draft state that is not user-authoritative by default).
- Rationale: User clarified that lumping these together makes Neo/AgentSmith unpredictable and contaminates bounded agents such as Niaobe with chat context they should not own.
- Constraint: Do not share conversational memory with Niaobe as if it were project truth.

- Decision: Projection is a first-class event model, not ad hoc summary posting.
- Rationale: User explicitly defined durable projection event types so project-thread behavior remains generic, inspectable, and renderable independently of Zulip transport.
- Constraint: Gateway renders and sends projection events; it does not invent projection semantics.

- Decision: Introduce an explicit agent registry for runtime behavior and access control.
- Rationale: Once behavior moves out of the gateway, the system needs a single authoritative definition of agent role, allowed surfaces, capabilities, service access, policy profile, workspace access, visibility, and escalation targets.
- Constraint: Do not let agent behavior sprawl across modules without registry-backed boundaries.

- Decision: Niaobe is a bounded runtime agent, not a free-form conversational agent like Neo or AgentSmith.
- Rationale: User clarified that Niaobe's freedom should come from structured execution-state access and orchestration powers, not open-ended conversational breadth.
- Constraint: Bound Niaobe through prompt, runtime inputs, and policy; never through gateway behavior.

- Decision: Use `gemma4:31b` as the shared local Ollama runtime model for Neo, AgentSmith, and Niaobe in Sprint 2, with Gemma thinking enabled via `<|think|>` at the start of runtime system prompts.
- Rationale: User explicitly chose `gemma4:31b`, and the official Ollama model page recommends `temperature=1.0`, `top_p=0.95`, `top_k=64`, plus `<|think|>` for thinking mode with standard `system`/`user`/`assistant` roles.
- Constraint: Keep prior assistant thoughts out of multi-turn history, and make the runtime tolerant of Gemma thought blocks when extracting structured JSON outputs.

- Decision: Neo is now an executive runtime agent rather than an advisory-only one.
- Rationale: User explicitly asked Neo to gain direct execution, general-purpose research, and direct project/workspace mutation authority instead of acting only as a middleman.
- Constraint: Keep all execution and mutation inside the repository/workspace boundary, continue representing visible project-thread changes as formal projection events, and keep AgentSmith/Niaobe role boundaries intact.

- Decision: Neo research answers should be source-grounded and citation-friendly when research tools provide sources.
- Rationale: The next improvement focus after executive capability was Neo research depth, with explicit demand for better web-backed discussion rather than unsupported claims.
- Constraint: When research tool outputs include sources/citations, Neo should cite them inline and the runtime should preserve normalized source metadata for answer synthesis.

- Decision: Neo and AgentSmith use a prompt-driven runtime loop with structured tool calls and action intents, while approval, mutation, and projection execution remain separate service actions.
- Rationale: Sprint 2 needed to remove the remaining heuristic agent stubs without collapsing safety back into transport or hardcoded chat branches.
- Constraint: Keep the gateway transport-only, keep project mutations gated by policy/service execution, and treat tools as capabilities available through the registry rather than user-facing command restrictions.

- Decision: Execution handoff persistence must not overwrite confirmed project-management state such as AgentSmith-authored next actions unless no next actions exist yet.
- Rationale: Sprint 2 introduced richer confirmed planning updates, and clobbering those on handoff creation would erase approved PM state immediately after it is applied.
- Constraint: Preserve confirmed next actions in durable project memory; store handoff status separately and only seed a default execution next action when the project has none.

- Decision: Runtime credentials, authoritative state, logs, mappings, memories, and project workspaces resolve from `OPENCLAW_ROOT`, defaulting to `~/workspace/clawspace`, while `openclaw_agents/` remains code only.
- Rationale: The user explicitly separated the agent/team system source tree from operational/project data and required execution agents to stay inside a bounded workspace root rather than the repo.
- Constraint: Keep code/config templates in the repo, but read and write live runtime data under `OPENCLAW_ROOT/system/...` and `OPENCLAW_ROOT/projects/...`; do not reintroduce project/runtime state under `openclaw_agents/`.
