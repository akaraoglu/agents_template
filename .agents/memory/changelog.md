# Request and Change Log

Track template-level requests and changes only. Do not record local deployment
history, live credentials, or project-specific task transcripts here.

## Entry Template
- Date:
- Request:
- Action:
- Validation:
- Outcome:

## 2026-04-16
- Date: 2026-04-16
- Request: Bring the updated non-Neo runtime up live and prove the real Zulip stack can run the confirmation, handoff, Niaobe, and internal Morpheus loop path.
- Action: Restarted the live gateway, ran a real human-originated AgentSmith DM + confirmation in Zulip, confirmed project creation plus handoff projection, observed Niaobe execution intake, observed Planner and Implementer projection events from the new internal loop, and fixed an authoritative state bug so project handoff status tracks handoff updates in `StateStore.update_handoff`.
- Validation: Live Zulip messages `2991`, `2998`, `2999`, `3000`, `3001`, `3002`, `3003`, `3004`, `3005`, and `3006` showed the real path from approval through internal-loop progression and blocker projection; verified authoritative state for project `internal-loop-live-validation`; reran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `39 passed in 0.36s`.
- Outcome: The live runtime now runs AgentSmith, Niaobe, and the internal Morpheus loop together on Zulip. The fresh live project advanced through kickoff, handoff, execution start, plan update, task update, and a bounded execution blocker surfaced back out through Niaobe.

## 2026-04-17
- Date: 2026-04-17
- Request: Explain why `npm i -g @openai/codex` did not update Codex CLI and how to update the active CLI correctly.
- Action: Inspected the active `codex` binary, compared the shell-resolved path against the npm global install, confirmed the running binary is a Homebrew cask at `0.112.0` while npm installed `@openai/codex@0.121.0` separately under `/usr/lib/node_modules`, and verified the older active binary does not support the documented `--upgrade` flag.
- Validation: Ran `which codex`; `codex --version`; `npm list -g @openai/codex --depth=0`; `type -a codex`; `ls -l /home/linuxbrew/.linuxbrew/bin/codex /usr/bin/codex`; `brew list --cask --versions codex`.
- Outcome: Determined the update failed from the user's perspective because PATH prefers the Homebrew-installed Codex binary over the newer npm-installed one; the correct fix is to upgrade or remove the Homebrew cask, or change PATH to prefer the npm binary.

- Date: 2026-04-17
- Request: Confirm that no project-related data should live under `openclaw_agents/`, that this repo should stay only for the agents/team system, and adopt Option A for the `clawspace` migration.
- Action: Refined the migration direction so `openclaw_agents/` remains source/runtime code only while all project workspaces, runtime state, and operational data move under `~/workspace/clawspace`.
- Validation: Planning-only step.
- Outcome: The next implementation sprint is now explicitly scoped to an Option A runtime-root migration with a strict separation between agent-system code and project data.

- Date: 2026-04-17
- Request: Replan the system so all claws operate only inside `~/workspace/clawspace`, all projects and relevant files live there, and execution agents are sandboxed per project to reduce context.
- Action: Captured the request as a workspace-root and per-project sandboxing direction, then prepared a migration plan instead of implementing immediately.
- Validation: Planning-only step.
- Outcome: The next development focus is now workspace-root isolation and per-project agent sandboxes under `~/workspace/clawspace`.

- Date: 2026-04-17
- Request: Explain how to run the gateway.
- Action: Checked whether the live gateway process was already running and prepared the exact local start command plus an optional status check command.
- Validation: `ps -ef | rg 'openclaw_agents.communication.zulip_gateway_service|PID'` showed no running gateway process at the time of the request.
- Outcome: Provided the direct gateway start command and current status guidance.

- Date: 2026-04-16
- Request: Continue through the rest of the non-Neo setup without stopping: fix the remaining agents, add the internal loop, keep testing throughout, and bring the live runtime back up.
- Action: Added durable internal run state plus `InternalLoopService`; added internal agent profiles/prompts/model mapping for `morpheus`, `planner`, `implementer`, and `tester`; extended the runtime manager with a control-surface path and internal stage advancement under Niaobe-owned execution handoffs; added planner/implementer/tester artifact persistence, blocker escalation, verification completion, policy profiles, diagnostics, and updated sprint/backlog docs; and added/updated registry, policy, internal-loop, ops, and runtime tests.
- Validation: Ran `python3 -m py_compile $(find openclaw_agents -name '*.py' -print)`; ran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `38 passed in 0.35s`.
- Outcome: The remaining agent setup is now implemented locally: Morpheus owns a durable internal software loop, Planner/Implementer/Tester run internally on the control surface, Niaobe remains the visible execution surface, and the full local runtime suite passes.

- Date: 2026-04-16
- Request: Replan the remaining setup work with Neo deprioritized and the focus shifted to the other agents.
- Action: Produced a revised sprint order centered on AgentSmith maturity, Niaobe execution completion, internal runtime roles, cross-agent policy/memory hardening, and final live operational validation while keeping the current Neo/gateway baseline stable.
- Validation: Planning-only step.
- Outcome: The next implementation work is now sequenced around the non-Neo agents instead of further Neo capability upgrades.

- Date: 2026-04-16
- Request: Reload the live gateway on the research fix and prove Neo can answer a real human-originated research DM in Zulip.
- Action: Stopped the prior detached gateway process, started `env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service` on the updated runtime, sent a new human-originated Zulip DM to Neo through the Zulip server shell, and inspected the persisted Zulip messages to verify the exact bot reply.
- Validation: Confirmed live gateway PID `3127723`; sent human message `2988`; confirmed Neo reply `2989` from `neo-bot@bots.localdomain` with a grounded answer citing `https://ollama.com/library/gemma4`.
- Outcome: The live Neo research path now works in Zulip on the updated runtime and no longer fails the turn when outbound page fetches are partially degraded.

- Date: 2026-04-16
- Request: Continue after the live smoke by fixing Neo's web-research failure and proving the live research path works.
- Action: Hardened `openclaw_agents/services/web_research.py` with retry/backoff on transient network failures, made `research()` degrade to durable search-snippet sources when page fetches fail, added a regression test for snippet fallback, and prepared the live gateway for a restart on the new code before rerunning a human-originated Neo research DM in Zulip.
- Validation: Ran `env-python/bin/python -m pytest -q openclaw_agents/tests/test_web_research_service.py openclaw_agents/tests/test_prompt_driven_agent_runtime.py` with `11 passed in 0.10s`; ran `python3 -m py_compile openclaw_agents/services/web_research.py`; verified host-side `WebResearchService().search(...)` and `research(...)` return live results outside the sandbox.
- Outcome: Neo's research path now tolerates transient fetch failures and can still build source-grounded answers from search snippets; the remaining step is a live gateway reload and a real Zulip Neo research smoke check.

- Date: 2026-04-16
- Request: Restart the live gateway/agents and prove the fresh Zulip runtime is alive with real human-originated smoke checks.
- Action: Verified live Zulip connectivity outside the sandbox, kept the detached gateway process alive as PID `3124338`, sent human-originated Zulip DMs to Neo and AgentSmith through the Zulip server shell, confirmed AgentSmith’s approval gate, confirmed project creation plus canonical projections and handoff persistence, and confirmed Niaobe consumed the handoff into durable execution state with an execution-start projection.
- Validation: Confirmed Neo DM response message `2977`; confirmed AgentSmith approval/projection messages `2979`/`2981`/`2982`/`2983`; confirmed Niaobe execution messages `2984`/`2985`; verified authoritative project/handoff/execution-state records in `openclaw_agents/data/`; observed a separate Neo research DM reply `2987` reporting an outbound connection error on web research.
- Outcome: The live bridge is operational again and the full human -> AgentSmith -> confirm -> project -> handoff -> Niaobe smoke path works. Neo general DM works live; Neo web research still needs outbound-network follow-up.

- Date: 2026-04-16
- Request: Execute Sprint 3 through Sprint 7 in one continuous pass, keep testing throughout, and finish the remaining runtime setup after Sprint 2.
- Action: Implemented a profile-aware policy engine, added durable execution-state and audit-log services, recreated and extended the prompt-driven runtime manager source, wired Niaobe handoff intake/execution flow, added event-specific projection rendering, tightened memory scoping/cleanup, strengthened command guardrails and diagnostics, updated the agent registry/prompt metadata, refreshed the sprint/backlog trackers, and added policy/Niaobe/projection/ops tests.
- Validation: Ran targeted suites during implementation, then ran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `35 passed in 0.23s`; ran `python3 -m py_compile $(find openclaw_agents -name '*.py' -print)`; ran `env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service --check` and `--once` outside the sandbox with successful live Zulip connectivity for `neo`, `agent_smith`, and `niaobe`; started the live gateway outside the sandbox and confirmed a running process via `pgrep -af 'openclaw_agents.communication.zulip_gateway_service'` with PID `3123771`.
- Outcome: Sprints 3-7 are implemented and the fresh runtime is live again: policy is profile-driven, Niaobe consumes persisted handoffs into durable execution state, projection rendering is event-specific, memory boundaries are enforced more explicitly, and operations now have audit/guardrail/diagnostic coverage.

- Date: 2026-04-16
- Request: Execute Sprint 2 for AgentSmith depth.
- Action: Added a project-management surface tool, extended durable project state/files for backlog items, blockers, decisions, and richer plan data, taught AgentSmith runtime handling to use structured project mutation intents, expanded mutation/projection handling for spec/plan/task/closeout-style updates, preserved confirmed next actions when execution handoffs are persisted, added AgentSmith depth tests, and refreshed the sprint/backlog trackers.
- Validation: Ran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `23 passed in 0.15s`; ran `python3 -m py_compile $(find openclaw_agents -name '*.py' -print)`.
- Outcome: AgentSmith can now inspect a whole project-management surface, propose richer backlog/blocker/plan/spec updates through confirmation-gated structured mutations, and persist those updates outside Zulip with first-class projection events.

- Date: 2026-04-16
- Request: Read the files in the current folder and adopt the local context without taking team-related action yet.
- Action: Reviewed top-level files `AGENTS.md`, `.gitignore`, and `zulip_plugin_and_setup_spec.md`; inspected `openclaw_agents.zip` via archive listing and read its packaged `README.md`.
- Validation: Confirmed the current top-level file set and zip contents without modifying team setup files or runtime assets.
- Outcome: Repository context adopted for follow-up work; no implementation or team action taken.

- Date: 2026-04-16
- Request: Keep all implementation under `openclaw_agents/` and keep edits within `/home/alik/workspace/agent_template`.
- Action: Adopted the request as a standing workspace constraint and recorded it in memory for future execution.
- Validation: Confirmed current working directory is `/home/alik/workspace/agent_template` before recording.
- Outcome: Future implementation scope constrained to `openclaw_agents/` inside this repository.

- Date: 2026-04-16
- Request: Build only the Zulip/plugin/skills/foundation layer for the new agentic system, implement required config/schemas/services/tests, and validate the minimal Neo->AgentSmith->project->handoff demo path.
- Action: Read available authoritative spec files in precedence order, implemented foundation runtime/services/skills/config/schemas/prompts under `openclaw_agents/`, wired confirmation-gated project mutation and canonical projection flow, persisted execution handoffs outside Zulip, and added the six requested tests.
- Validation: Executed `python3 -m unittest discover -s openclaw_agents/tests -p 'test_*.py'` with all six tests passing; also ran `python3 -m py_compile $(find openclaw_agents -name '*.py')`.
- Outcome: Minimal foundation scope is operational with confirmation enforcement, context resolution with ambiguity follow-up, queue recovery/dedupe handling, canonical projection, and persisted handoff packets.

- Date: 2026-04-16
- Request: Install pytest into local `env-python`, create `requirements.txt`, and add setup files for future users cloning the repo.
- Action: Added dependency and setup artifacts under `openclaw_agents/` (`requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`, `README.md`, `setup_local_env.sh`), installed dependencies into `env-python`, and executed tests via the venv.
- Validation: Ran `env-python/bin/python -m pip install -r openclaw_agents/requirements-dev.txt` and `env-python/bin/python -m pytest -q openclaw_agents/tests` (6 passed).
- Outcome: Foundation now has reproducible dependency/bootstrap instructions for new clones and a verified venv-based test command path.

- Date: 2026-04-16
- Request: Create a sprint plan, implement the fresh Zulip bridge inside `openclaw_agents`, run tests, and bring Neo up in Zulip without using legacy bridge code.
- Action: Re-scoped the config surface to the current foundation agents, implemented a fresh stdlib Zulip client and shared live runtime under `openclaw_agents/communication/zulip_plugin/`, added a new `zulip_gateway_service.py` runner, wired sender-aware DM/topic publishing and queue recovery into the current gateway, added live-runtime/service unit tests, updated docs, and started the new bridge process from `openclaw_agents`.
- Validation: Installed `PyYAML` into `env-python`; ran `env-python/bin/python -m pytest -q openclaw_agents/tests` (9 passed) and `env-python/bin/python -m py_compile $(find openclaw_agents -name '*.py' -print)`; ran `env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service --check`; sent a real Zulip DM to Neo and received the reply `There are no active projects right now.` from the new bridge.
- Outcome: The fresh foundation bridge is now live from `openclaw_agents`, Neo is reachable in Zulip, and the implementation does not depend on the legacy `/home/alik/workspace/zulip` bridge code.

- Date: 2026-04-16
- Request: Produce a better design plan because Neo is too limited; Neo should be a free agent that can converse broadly, research, and use skills as capabilities rather than restrictions.
- Action: Analyzed the current foundation boundary and prepared a redesign plan focused on moving conversation/reasoning out of hardcoded gateway handlers and into an agent runtime with capability-based tools and policy-gated side effects.
- Validation: No code changes beyond request logging in this step.
- Outcome: Design-plan response prepared before any new implementation work.

- Date: 2026-04-16
- Request: Correct the architecture so the gateway does not decide behavior for any agent; Zulip/gateway should be communication-only, while Neo, AgentSmith, and the other agents remain free and the project handoff/communication system belongs outside the gateway.
- Action: Recorded the architectural correction and prepared a stricter boundary plan that removes behavior ownership from the gateway and relocates agent behavior, project handoff, and workflow decisions into the runtime/control-plane layers.
- Validation: No implementation changes in this step.
- Outcome: Updated system boundary guidance ready for the next implementation plan.

- Date: 2026-04-16
- Request: Refine the redesign to separate memory classes, formalize projection as event types, add an explicit agent registry, and keep Niaobe bounded by runtime/policy rather than by the gateway.
- Action: Recorded the architectural refinements and prepared a tighter follow-up plan centered on memory separation, first-class projection events, a runtime agent registry, and a bounded execution-agent model for Niaobe.
- Validation: No implementation changes in this step.
- Outcome: Revised implementation plan prepared with the clarified system boundaries.

- Date: 2026-04-16
- Request: Do the sprint planning, create the backlog, and start implementation for the boundary refactor.
- Action: Added sprint/backlog artifacts under `openclaw_agents/plans/`, expanded the runtime agent registry, implemented separated conversation/working memory services, implemented a first-class projection event service, added policy and project-mutation services outside the gateway, introduced runtime agent contracts and registry-backed `neo`/`agent_smith`/`niaobe` agents, and refactored `zulip_gateway.py` to dispatch into the runtime and only render/send outbound messages and projection events.
- Validation: Ran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `13 passed in 0.17s` and `env-python/bin/python -m py_compile $(find openclaw_agents -name '*.py' -print)`.
- Outcome: The first boundary-refactor slice is implemented and tested; the gateway no longer owns the current DM behavior paths, and the architecture now has explicit registry, memory, and projection-event primitives for the next sprint.

- Date: 2026-04-16
- Request: Restart the gateway and agents.
- Action: Stopped the running `openclaw_agents.communication.zulip_gateway_service` process, started a fresh gateway process from the current code, and verified a live Neo DM round-trip in Zulip after restart.
- Validation: New gateway PID `4091955` observed via `ps`; sent a DM to Neo and received the reply `There are no active projects right now.` from `neo-bot@bots.localdomain`.
- Outcome: Gateway restarted successfully; runtime agents hosted inside the gateway were restarted with it and Neo is live.

- Date: 2026-04-16
- Request: Verify whether the restarted Neo is actually free-form, since the observed behavior is still tied to projects.
- Action: Re-read the current runtime implementation and confirmed that `NeoRuntimeAgent` and `AgentSmithRuntimeAgent` still use bootstrap heuristic branches instead of a real prompt/tool runtime.
- Validation: Inspected `openclaw_agents/agents/manager.py` and confirmed the current runtime only handles project/status-style logic and generic project-management fallback replies.
- Outcome: The gateway boundary is improved, but Neo is not yet a true free agent; the remaining limitation is in the runtime agent implementation, not in Zulip transport.

- Date: 2026-04-16
- Request: Provide the sprint plan for the rest of the setup after confirming that Neo is still limited by the runtime stubs.
- Action: Prepared the next-phase sprint plan focused on replacing the heuristic runtime agents with a real prompt/tool/memory/service-driven runtime while preserving the transport-only gateway boundary.
- Validation: Planning-only step; no implementation changes made here.
- Outcome: Remaining setup work is now broken into concrete sprint slices from runtime core to live free-agent bring-up.

- Date: 2026-04-16
- Request: Do Sprint 2, then switch the runtime to `gemma4:31b`, enable thinking, and set the model up properly for better agents.
- Action: Completed the prompt-driven runtime slice under `openclaw_agents/agents/`, cleaned up the runtime contracts/helpers, switched the shared Ollama model map to `gemma4:31b`, enabled Gemma thinking mode by prefixing system prompts with `<|think|>`, hardened JSON parsing for Gemma thought-output envelopes, updated README setup notes, restarted the live Zulip gateway on the new runtime, and ran direct Neo/AgentSmith smoke checks against the Gemma-backed runtime.
- Validation: Ran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `16 passed in 0.23s`; ran `env-python/bin/python -m py_compile $(find openclaw_agents -name '*.py' -print)`; ran `env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service --check`; started the live gateway; verified direct Gemma-backed runtime replies for a general Neo architecture question and an AgentSmith project-creation request with confirmation gating.
- Outcome: Sprint 2 is now implemented with a Gemma 4 31B runtime, thinking-enabled prompts, green tests, and a live Zulip gateway process running the updated agents.

- Date: 2026-04-16
- Request: Move Neo from advisory to a more executive role by adding direct execution, general-purpose research, and direct project/workspace mutation capabilities.
- Action: Added `CommandRunnerService` and `WebResearchService`, expanded the tool registry with web search/fetch, direct workspace writes, direct workspace command execution, and direct project create/update tools, promoted Neo’s registry/prompt/policy profile to an executive runtime, extended project updates to support milestone/state file sync, wired tool-generated projection events into runtime responses, added tests for Neo web research/direct execution/direct mutation, and restarted the live Zulip gateway.
- Validation: Ran `env-python/bin/python -m py_compile $(find openclaw_agents -name '*.py' -print)`; ran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `19 passed in 0.13s`; verified a real direct Neo execution probe using `run_workspace_command`; verified a real direct Neo web research probe using `web_search`; confirmed the restarted live gateway process via `ps`.
- Outcome: Neo now has live executive runtime capabilities for direct execution, web research, writable project/workspace actions, and direct durable project mutation within the repository boundary.

- Date: 2026-04-16
- Request: Identify what is still missing after the current Neo/runtime improvements so the next setup slice can be chosen.
- Action: Re-reviewed the current backlog, runtime registry, policy layer, Niaobe prompt/runtime boundary, approval flow, and projection/event surfaces to identify the remaining concrete gaps.
- Validation: Read current planning and implementation files only; no code changes beyond this request log entry.
- Outcome: Prepared a current-state gap list covering policy depth, AgentSmith maturity, Niaobe execution runtime, richer research/browser depth, projection completeness, memory hardening, and operational hardening.

- Date: 2026-04-16
- Request: Create a sprint plan with a todo list for the remaining setup work in the agreed priority order.
- Action: Added a new ordered sprint plan at `openclaw_agents/plans/NEXT_SETUP_SPRINTS.md` and refreshed `openclaw_agents/plans/RUNTIME_BACKLOG.md` so the next execution slices are durable in-repo.
- Validation: Planning/documentation-only step.
- Outcome: The remaining setup work is now broken into seven ordered sprints with explicit todo items, starting with Neo research depth.

- Date: 2026-04-16
- Request: Execute Sprint 1 to improve Neo research depth first.
- Action: Upgraded `WebResearchService` with result normalization, DuckDuckGo redirect cleanup, fetched-page title/excerpt extraction, and a multi-source `research()` packet; added the `research_brief` runtime tool; updated Neo/runtime prompting for source-aware citation behavior; added runtime and service tests for multi-source research; restarted the live gateway; and ran a live Gemma-backed Neo research probe with real web access.
- Validation: Ran `env-python/bin/python -m py_compile $(find openclaw_agents -name '*.py' -print)`; ran `env-python/bin/python -m pytest -q openclaw_agents/tests` with `21 passed in 0.14s`; ran a live Neo probe that used `research_brief` and returned a cited answer grounded in fetched sources.
- Outcome: Neo now has materially stronger source-aware research behavior with multi-source retrieval and citation-capable replies.

- Date: 2026-04-16
- Request: Do Sprint 2.
- Action: Implemented the Sprint 2 visible-agent runtime under `openclaw_agents/agents/` by adding model selection and Ollama client plumbing, prompt loading, a bounded tool registry, structured tool/action contracts, and a prompt-driven runtime loop for Neo and AgentSmith while keeping policy, approval, mutation, and projection execution in services outside the gateway.
- Validation: Ran `python3 -m py_compile $(find openclaw_agents -name '*.py' -print)` and `env-python/bin/python -m pytest -q openclaw_agents/tests` with `16 passed in 0.26s`.
- Outcome: Neo and AgentSmith are no longer hardcoded in gateway-owned or heuristic runtime branches; the runtime now supports free-form model replies, tool use, and structured mutation intents with confirmation gating.

- Date: 2026-04-16
- Request: Bring the new Sprint 2 runtime up live after implementation.
- Action: Started `env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service` with the fresh runtime and ran the live gateway `--check` path against Zulip.
- Validation: Live check succeeded with authenticated identities for `neo`, `agent_smith`, and `niaobe`, active queue registrations, and healthy subscriptions to `projects`.
- Outcome: The live Zulip gateway is running against the Sprint 2 runtime and is ready for manual DM verification in Zulip.

- Date: 2026-04-17
- Request: Continue the `clawspace` runtime-root cutover so `openclaw_agents/` stays code-only while runtime state and project workspaces live under `~/workspace/clawspace`.
- Action: Bootstrapped `~/workspace/clawspace` with the new runtime-path helper, synchronized credentials/artifacts/projects into `system/` and `projects/`, restarted the live Zulip gateway against `OPENCLAW_ROOT=/home/alik/workspace/clawspace`, and ran a real human-originated Zulip DM smoke to Neo after the restart.
- Validation: Ran `env-python/bin/python -m openclaw_agents.bootstrap_clawspace --overwrite-credentials`; restarted `env-python/bin/python -m openclaw_agents.communication.zulip_gateway_service`; ran `--check` and confirmed `"runtime_root": "/home/alik/workspace/clawspace"` with live healthy bot queues; injected DM `3024` from `user8@localhost.localdomain` to Neo and observed reply `3025` listing the active migrated projects.
- Outcome: The live foundation now runs from `~/workspace/clawspace`, authoritative state and project workspaces are outside the repo, and the post-cutover Zulip DM path is working end to end.

- Date: 2026-04-17
- Request: Clean old repo-local runtime clutter out of `agent_template` and prepare a commit sprint plan.
- Action: Removed the stale repo-local runtime/workspace trees under `openclaw_agents/data` and `openclaw_agents/workspaces`, deleted generated Python/test caches under `openclaw_agents/`, added root ignore rules for the local virtualenv and local `software_team_setup/` reference pack, and added `openclaw_agents/plans/COMMIT_SPRINT.md` to break the remaining source diff into reviewable commit slices.
- Validation: Verified the old repo-local runtime directories and caches no longer exist under `openclaw_agents/`; checked `git status --short` to confirm the cleanup reduced repo noise without touching the current implementation diff.
- Outcome: The repo is cleaner, local runtime debris is gone, and there is now a concrete commit sequence for landing the remaining work safely.

- Date: 2026-04-17
- Request: Create all planned commits in order.
- Action: Split the large working tree into five commits covering the runtime architecture cutover, bounded execution loop coverage, clawspace runtime-root cutover, developer setup/test harness, and repo hygiene/planning.
- Validation: Ran compile checks, focused pytest slices, the clawspace gateway `--check` health probe, and representative regression tests while creating the commit sequence.
- Outcome: The implementation is now landed as an ordered commit stack instead of one monolithic diff.
