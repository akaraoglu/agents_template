# Decisions Log

Record durable repo or process decisions here, especially behavior or tooling updates that should remain true over time.

## Entry Template
- Date:
- Decision:
- Context:
- Consequences:
- Status:

## Entries

- Date: 2026-03-30
- Decision: The next-generation multi-agent template should standardize dispatch through a shared role registry, a shared communication contract, and an explicit `AgentSmith` dispatcher skill instead of relying on prompt-only spawning conventions.
- Context: The existing bridges and wrappers already standardize connection layers reasonably well, but visible handoffs between `AgentSmith`, `Niaobe`, `Architect`, `Morpheus`, and `Oracle` remained too ad hoc, which made new-role expansion and deterministic orchestration harder than necessary.
- Consequences: Future role additions should derive from `.agents/role_registry.example.json`, visible status and result messages should follow `.agents/COMMUNICATION_CONTRACT.md`, and `AgentSmith` should evolve into a deterministic dispatcher that routes work through a registry-backed contract rather than improvising new spawn behaviors per role.
- Status: Accepted

- Date: 2026-03-30
- Decision: Spawn rights should be modeled as grantable capabilities in the role registry, with a generic `role-dispatcher` skill that can be assigned to `AgentSmith`, `Niaobe`, or future coordinators.
- Context: A role hierarchy alone does not answer who is allowed to launch whom; the user wants the same dispatch mechanism reusable across multiple agents instead of hardcoding special-case orchestration into AgentSmith only.
- Consequences: The registry should record `granted_skills` and `can_spawn_roles`, visible handoffs should record `DISPATCHED_BY` and `AUTHORIZED_VIA`, and specialized dispatcher skills such as `agentsmith-dispatcher` should build on top of the generic capability instead of replacing it.
- Status: Accepted

- Date: 2026-03-30
- Decision: Roles and runtimes must remain separate, with backend selection controlled through local runtime profiles rather than hardcoded directly into role definitions.
- Context: The future system needs to support both Docker-backed local OpenClaw agents and non-Docker OpenAI OAuth-backed agents on a host workspace, while preserving the same role hierarchy, dispatch model, and project loop.
- Consequences: Role definitions should point to `runtime_profile` and `entry_role`, deployments should keep a local `.agents/runtime_profiles.json`, and future backend adapters should be implemented behind shared runtime-dispatch interfaces instead of cloning the whole role and bridge stack per provider.
- Status: Accepted

- Date: 2026-03-30
- Decision: Phase 1 of the V2 control plane uses dedicated script-based validators for role, runtime-profile, and workflow registries, and template example files may keep placeholders while local deployment files must resolve them.
- Context: The V2 design needed a real validation layer before adding dispatchers or runtime adapters, but the committed template examples still need portable placeholder values that should not fail the template itself.
- Consequences: `.agents/scripts/dispatch_registry.py`, `.agents/scripts/runtime_registry.py`, and `.agents/scripts/workflow_registry.py` are now the canonical validation entrypoints, and validators should treat `.example.*` files as placeholder-tolerant while treating local runtime files as concrete configuration.
- Status: Accepted

- Date: 2026-03-30
- Decision: The Phase 2 runtime adapter layer should resolve a role through its explicit `run_command` first and only fall back to the runtime profile's `default_entrypoint` plus `entry_role` when a role-specific wrapper is not available.
- Context: The current local OpenClaw template already has working wrapper entrypoints such as `run_team.sh` and `run_agent.sh`; replacing them immediately would risk drift, while the future backend architecture still needs one common runtime-resolution layer.
- Consequences: The local `openclaw_local` adapter preserves current behavior for executable roles like `morpheus`, `planner`, `coder`, and `tester`, while still allowing future roles to resolve through `entry_role`-based fallback paths. The `openai_claw_host` adapter remains plan-only until its real backend launcher exists.
- Status: Accepted

- Date: 2026-03-30
- Decision: The Phase 3 dispatcher should remain thin: it authorizes a route, creates a standard handoff envelope, augments the runtime launch plan with dispatch metadata, and defers actual workflow state transitions to later phases.
- Context: The system needs a deterministic dispatcher now, but mixing workflow-engine logic into the dispatcher would recreate the same ad hoc orchestration problem the V2 control plane is meant to remove.
- Consequences: `dispatch_request.py` should validate `from_role -> to_role` authorization, require project selection for project-aware roles, build the communication-contract envelope, and then hand off execution to the runtime adapter layer. Project-loop state ownership remains a Phase 4 concern.
- Status: Accepted

- Date: 2026-03-12
- Decision: Keep `AGENTS.md` short and store detailed operating guidance under `.agents/`.
- Context: The older `AGENTS.md` combined workflow, environment, style, and logging rules in one file.
- Consequences: Repo-wide guidance is easier to maintain and each topic has a single clear home.
- Status: Accepted

- Date: 2026-03-12
- Decision: Use `.agents/memory/decisions.md` for durable behavior and tooling updates instead of a separate `AGENTS_update.md`.
- Context: The previous workflow proposed a second top-level file for ongoing agent updates.
- Consequences: Persistent updates stay inside the existing memory structure and avoid duplicate sources of truth.
- Status: Accepted

- Date: 2026-03-13
- Decision: The OpenClaw template will use `PROJECT.md` as the single project-specific context file and will generate `openclaw.json` locally from `openclaw.template.json`.
- Context: The previous OpenClaw folder contained machine-specific paths, committed runtime state, and project-specific assumptions that made it unsuitable as a reusable template.
- Consequences: The OpenClaw template is now portable across projects while still supporting local Docker-backed execution that needs absolute config paths at runtime.
- Status: Accepted

- Date: 2026-03-13
- Decision: The local OpenClaw team will use a `manager` role as the orchestrator, with `run_team.sh` coordinating manager, planner, coder, and tester externally.
- Context: The desired team shape includes a dedicated orchestrator, but embedded local mode may not expose direct in-agent delegation tools consistently.
- Consequences: The template has a stable manager-led workflow now, while remaining compatible with current local execution limits.
- Status: Accepted

- Date: 2026-03-27
- Decision: `AgentSmith` should hand off project ownership once, `Niaobe` should own `projects > project: <slug>`, `Morpheus` should own execution in `software`, and `Oracle` should report validation back to `Niaobe` rather than acting as Morpheus's subordinate.
- Context: The earlier Zulip flow kept `AgentSmith` and `Morpheus` too central, which made project ownership, acceptance, and QA reporting ambiguous.
- Consequences: The project loop now has a clear hierarchy: intake through `AgentSmith`, planning and acceptance through `Niaobe`, execution through `Morpheus`, and independent validation through `Oracle`.
- Status: Accepted

- Date: 2026-03-27
- Decision: `/manage` must require an explicit project slug, and project-manager / architect work must stay inside the selected project's own `PROJECT.md` and `management/` files.
- Context: The earlier multi-project flow still loaded the workspace-root `PROJECT.md` and shared `management/`, which caused Niaobe and Architect to leak planning across projects and reference the wrong paths.
- Consequences: Project-manager and architect runs now need an explicit `projects/<slug>` selection, shared root management is no longer a valid target for project-specific planning, and foreign-project path references must be rejected instead of silently accepted.
- Status: Accepted

- Date: 2026-03-27
- Decision: The live workspace root `PROJECT.md` should be a workspace-level coordination document, and the old root `management/` tree should be archived instead of remaining active.
- Context: Even after explicit project selection was added, the old root `management/` tree and single-project root `PROJECT.md` still existed and could confuse humans or agents into using the obsolete workspace-wide planning path.
- Consequences: Active project planning now belongs only under `projects/<slug>/management/`; the root document now describes workspace coordination and project selection, while the previous root planning files remain preserved only as archived history.
- Status: Accepted

- Date: 2026-03-30
- Decision: When Zulip is configured with an IP address as `SETTING_EXTERNAL_HOST`, the deployment must also set a valid domain name in `SETTING_FAKE_EMAIL_DOMAIN`.
- Context: Switching the live Zulip host from `localhost.localdomain` to the raw IP `10.80.11.167` caused the web app to throw `InvalidFakeEmailDomainError` while generating the fake bot-email domain for the home page.
- Consequences: IP-based Zulip access now requires a valid fake email domain such as `bots.localdomain`; otherwise the site may appear healthy at the container level while returning an internal server error at `/`.
- Status: Accepted

- Date: 2026-03-30
- Decision: After changing Zulip `SETTING_EXTERNAL_HOST`, persisted self-signed certificates must be regenerated if they were created for a different hostname.
- Context: The live Zulip deployment kept reusing a persisted `localhost.localdomain` self-signed certificate even after the host was switched to `10.80.11.167`, which left the site with a hostname mismatch warning.
- Consequences: For IP-based self-signed Zulip access, changing the host now also requires backing up/removing the old files in `/data/certs/self-signed` and restarting the service so the entrypoint regenerates a certificate whose CN and SAN match the new host.
- Status: Accepted

- Date: 2026-03-30
- Decision: When the live Zulip endpoint changes, all bridge bot `.zuliprc` files must be updated to the new `site=` value before restarting the bridges.
- Context: The assistant and software bridges continued to point at `https://localhost.localdomain:8443` after Zulip was moved to `https://10.80.11.167`, which caused both bridges to crash on startup with connection-refused errors.
- Consequences: Future Zulip host changes now require a paired bridge-credential update; otherwise the bot processes may be down even though the Zulip server itself is healthy.
- Status: Accepted

- Date: 2026-03-30
- Decision: If the live Docker Zulip publishing must remain untouched and client machines can already reach Apache on port `80`, Apache should be used as the intranet front door for Zulip instead of continuing to rely on the Docker-published `443` path.
- Context: The Windows client can reach the host on `80` but times out on direct `443`, while the user does not want to risk the current Docker networking layout by reworking the container-published HTTPS port.
- Consequences: The preferred near-term access model is Apache-on-`80` proxying to the existing Zulip backend, with Docker left unchanged and bridge URLs updated only if the externally visible Zulip hostname or scheme changes.
- Status: Accepted

- Date: 2026-03-30
- Decision: Once live Zulip `SETTING_EXTERNAL_HOST` is changed to `zulip.localnet`, the bridges must use `site=https://zulip.localnet` until a working Apache-on-`80` Zulip front door is actually live.
- Context: The bridges failed on `http://zulip.localnet` because the planned HTTP front door was not yet serving Zulip, and they failed on `https://10.80.11.167` because Zulip now rejects the old host with `400 Bad Request`.
- Consequences: Bridge configs must track the current live Zulip hostname exactly; do not preemptively switch them to a planned hostname or scheme before that path is actually working.
- Status: Accepted

- Date: 2026-03-30
- Decision: When the live Zulip host changes, every role bot `.zuliprc` and validation bot `.zuliprc` must be updated alongside the main bridge bot before the bridges are considered healthy.
- Context: AgentSmith’s main bot was corrected to `https://zulip.localnet`, but Niaobe, Architect, Planner, Coder, and Oracle still had stale endpoint configs, which broke `/manage`; later, the software-side Oracle bot also still pointed at the old host even though Morpheus’s main bot was correct.
- Consequences: Future Zulip endpoint migrations must update all assistant-bridge and software-bridge bot credentials, not just `assistant-bot` and `software-manager-bot`, and the affected bridge processes should be restarted afterward.
- Status: Accepted

- Date: 2026-03-30
- Decision: When Docker owns public `443` and Apache is only meant to front Zulip on `80`, Apache's own `Listen 443` entries must be removed or disabled before the service can start cleanly.
- Context: The host-side Zulip-on-`80` cutover stalled even though the `zulip.localnet` vhost was enabled, because `apache2.service` failed with `Address already in use` on `0.0.0.0:443` and `[::]:443` while Docker already owned that port.
- Consequences: The safe no-Docker-change pattern is Apache on `80` only, proxying to the existing Zulip backend, with Apache not attempting to bind `443` at all.
- Status: Accepted

- Date: 2026-03-30
- Decision: Plain HTTP is not a viable authenticated front door for this Zulip deployment; the externally used Zulip hostname still needs a working HTTPS path.
- Context: The `http://zulip.localnet/` proxy path served the login page, but the app still issued `Secure` `__Host-*` cookies, which browsers will not send over HTTP, causing login and bot-authentication flows to fail with missing-credentials / Referer-style errors.
- Consequences: Future intranet access plans must preserve HTTPS for the actual Zulip hostname, even if Apache is used as the front door. HTTP can only be a staging page or redirect, not the final authenticated endpoint.
- Status: Accepted

- Date: 2026-03-30
- Decision: Now that client access to `https://zulip.localnet` over `443` works, the experimental Apache Zulip workarounds on `80`, `3838`, and `8888` should be removed and the live setup should return to the single HTTPS endpoint.
- Context: The alternate Apache vhosts were only introduced to work around earlier client reachability problems on `443`; keeping them now only adds duplicate entrypoints and operational confusion.
- Consequences: The supported live Zulip URL remains `https://zulip.localnet`, bridge configs should stay on that hostname, and Apache should no longer proxy Zulip on the experimental ports.
- Status: Accepted

- Date: 2026-03-30
- Decision: The live OpenClaw shell runners must parse both markdown-decorated section headers and inline `KEY: value` responses from model outputs.
- Context: Morpheus emitted `**PLAN_SUMMARY:**`-style headers and Oracle returned `ORACLE_DECISION: accepted` on a single line; the previous parsers only recognized plain multiline `SECTION:` blocks, which caused the Niaobe execution loop to stall or to lose Oracle’s explicit decision.
- Consequences: Shared shell runners such as `run_team.sh` and `run_assistant_spawn.sh` should use tolerant section parsing so formatting variation from the models does not break orchestration.
- Status: Accepted

- Date: 2026-03-30
- Decision: The full project-manager execution path is `Niaobe -> Architect (if needed) -> Morpheus -> Oracle -> Niaobe`, while Zulip `/manage` remains a `prepare_only` orchestration handoff owned by the bridge.
- Context: Direct project-manager runs need to complete the full management and execution loop for verification and automation, but the Zulip bridge already owns the visible software-stream handoff and should not double-run Morpheus.
- Consequences: `run_assistant_spawn.sh --role projectmanager` may execute the full loop locally, while the assistant bridge should continue setting `OPENCLAW_PROJECTMANAGER_MODE=prepare_only` for `/manage` and related routed project-manager requests.
- Status: Accepted

- Date: 2026-03-30
- Decision: The shared dispatcher must prefer the most specific granted spawn skill, and project-facing roles must default to project-thread visibility.
- Context: The initial Phase 3 dispatcher reported `AUTHORIZED_VIA=role-dispatcher` for AgentSmith even when the specialized `agentsmith-dispatcher` skill was present, and it routed `Architect` and `Oracle` to the generic assistant topic even though both roles are meant to report in project context.
- Consequences: Dispatch authorization now uses a fixed priority order (`spawn-any`, `agentsmith-dispatcher`, `role-dispatcher`, `execution-manager`) instead of raw registry order, and `niaobe`, `architect`, and `oracle` all default to `projects > project: <slug>` visibility.
- Status: Accepted

- Date: 2026-03-30
- Decision: The Phase 4 workflow engine must separate the persistent project owner from the current active role.
- Context: A simple state-owner model let the workflow advance, but it blurred the crucial hierarchy the user wants: Niaobe should own the project for its full lifetime even while Architect, Morpheus, and Oracle temporarily become the active worker on the next handoff.
- Consequences: The workflow engine now keeps `project_owner=niaobe` for the whole run, rotates `active_role` per handoff, returns control to Niaobe when results are reported, and models the software-project workflow as Niaobe-owned execution and validation phases instead of transferring ownership into Morpheus or Oracle.
- Status: Accepted

- Date: 2026-03-30
- Decision: The live Zulip bridges should be supervised by system-wide `systemd` services instead of ad hoc terminal sessions.
- Context: The assistant and software bridges have repeatedly gone down when they were started from interactive shells or detached PTY sessions, even though Zulip itself remained healthy.
- Consequences: The recommended live supervision model is now one system-wide unit per bridge with `Restart=always`, `After=network-online.target docker.service`, and the existing bridge launchers as `ExecStart`.
- Status: Accepted

- Date: 2026-03-30
- Decision: Phase 5 should keep workflow state as the source of truth and layer supervisor metadata on top of it rather than duplicating the project state machine.
- Context: The new Phase 4 workflow engine already persists authoritative project-loop state, so adding a second independent run model in the supervisor would create drift between `/status`, `/stop`, and the actual project lifecycle.
- Consequences: The supervisor now stores persistent run metadata, desired actions, and event logs while reading and syncing the real state from the workflow run file. This makes bridge restarts survivable without splitting the control plane into two conflicting sources of truth.
- Status: Accepted

- Date: 2026-03-30
- Decision: On the live bridge, AgentSmith `/manage` should stay in intake/prepare mode, but Niaobe-owned project-thread runs must execute the full projectmanager loop.
- Context: The live assistant bridge was still forcing every `projectmanager` spawn into `OPENCLAW_PROJECTMANAGER_MODE=prepare_only`, which prevented Niaobe from actually owning and advancing the project loop even after Smith handed work to the `projects` stream.
- Consequences: The live bridge now keeps `prepare_only` only for Smith's `/manage` intake handoff, while direct Niaobe/project-thread projectmanager runs use `execute` mode so Niaobe can run the Architect -> Morpheus -> Oracle -> Niaobe loop after she becomes the owner.
- Status: Accepted

- Date: 2026-03-30
- Decision: The live OpenClaw sandbox extras baseline should include the full image-processing and reporting set `pytest`, `scipy`, `opencv-python-headless`, `Pillow`, `scikit-image`, `pyyaml`, `requests`, `tqdm`, and `rich`.
- Context: The active workspace projects and validation scripts already depend on `cv2`, `PIL`, numerical filters, and human-readable CLI/reporting output, while the previous sandbox extras contained only `pytest`.
- Consequences: New sandbox image builds should treat this package list as the default extras baseline until a project-specific profile system exists, and rebuild failures must be treated separately from the package decision itself.
- Status: Accepted

- Date: 2026-03-30
- Decision: The live OpenClaw sandbox build path should use Docker host networking by default, overridable via `OPENCLAW_DOCKER_BUILD_NETWORK`.
- Context: The `openclaw-sandbox:pytorch-shared-venv` rebuild consistently hung in `apt-get update` on Docker's default bridge network, while the same base image succeeded immediately when run with `--network host`.
- Consequences: `.agents/scripts/setup_local_team.sh --build-image` now builds with `docker build --network "$OPENCLAW_DOCKER_BUILD_NETWORK"` and defaults that variable to `host`, which makes the image rebuild reliable without hardcoding a single network mode forever.
- Status: Accepted

- Date: 2026-03-31
- Decision: V3 should drop nested in-sandbox agent spawning and use Zulip as the primary inter-agent communication bus.
- Context: The live system proved that `openclaw` running inside one agent sandbox trying to start another sandbox is fragile and hard to reason about, while the user needs direct-DM-able agents, visible project orchestration, and later multi-agent group discussions.
- Consequences: Cross-agent requests should become structured handoff messages emitted in Zulip and executed by a host-side gateway, visible roles should stay DM-able, and shared topics should use light thread coordination instead of strict topic ownership.
- Status: Accepted

- Date: 2026-03-31
- Decision: In V3, roles are defaults rather than hard restrictions, and shared-topic participation should be governed by mentions, handoffs, and minimal thread state.
- Context: The user wants any main visible agent to be directly usable in DMs while still allowing role-specific project, software, and validation loops plus future multi-agent group discussions.
- Consequences: The template should treat `AgentSmith`, `Niaobe`, `Architect`, `Morpheus`, and `Oracle` as DM-able visible roles, shared topics should reply only on mention, handoff, or active exchange, and the gateway should track only `active_run_id`, `current_speaker`, `awaiting_from`, `participants`, and `mode`.
- Status: Accepted

- Date: 2026-03-31
- Decision: The first V3 runtime should reuse the existing multi-bot bridge pattern, but centralize thread transcripts and thread state so visible handoffs can be routed by one shared gateway.
- Context: `persona_bridge_v1` already solves multi-bot Zulip polling and host-side role execution well enough, but V3 needs shared thread context across `AgentSmith`, `Niaobe`, `Architect`, `Morpheus`, and `Oracle` instead of isolated per-bot transcripts.
- Consequences: `zulip_gateway_v3/gateway.py` should keep one process with one listener per visible bot, one shared thread transcript per DM/topic, minimal state (`active_run_id`, `current_speaker`, `awaiting_from`, `participants`, `mode`), and visible `HANDOFF` routing without introducing nested in-sandbox spawning.
- Status: Accepted

- Date: 2026-03-31
- Decision: In V3, direct-message threads must be scoped per bot, and bot-to-bot handoffs in DMs must copy thread context into the target bot's DM state instead of sharing one global DM thread.
- Context: A naive shared-thread implementation keyed DMs only by the human participant, which would have caused unrelated DMs with different bots to bleed into the same transcript while still failing to model Zulip's separate bot-specific DM conversations correctly.
- Consequences: The V3 gateway now keys private threads as `dm:<agent-slug>`, and a DM handoff creates or updates the target bot's DM thread state by merging transcript context and the latest handoff record before launching the target role.
- Status: Accepted

- Date: 2026-03-31
- Decision: For new setups, the single `zulip_gateway_v3` service is the default Zulip integration path, while `persona_bridge_v1` and `software_bridge_v1` are legacy fallback paths only.
- Context: The repository had reached a confusing half-migrated state where V3 was the recommended architecture in some docs, but the setup/runbook material still defaulted heavily to the older split-bridge model.
- Consequences: Setup and rollout docs should point new deployments to `ZULIP_V3_GATEWAY_SETUP.md`, `SYSTEMD_BRIDGES.md` should prefer `zulip-gateway-v3.service`, and the legacy bridge READMEs should remain available but clearly marked as fallback guidance.
- Status: Accepted

- Date: 2026-03-31
- Decision: The template must ship the visible-role wrappers, prompts, and agent definitions that the V3 gateway examples reference.
- Context: The first V3 gateway examples pointed at `run_assistant.sh`, `run_projectmanager.sh`, `run_architect.sh`, and related role files that did not actually exist in the generic template, which made the published V3 path inconsistent and harder to adopt.
- Consequences: `openclaw_agents/.agents/` should include concrete wrappers and prompt files for the documented visible roles, `openclaw.template.json` should include their agent definitions, and gateway examples should point only at files the template actually ships.
- Status: Accepted

- Date: 2026-03-31
- Decision: In V3, Yoda should be modeled as an optional advisory visible role, not as another project or execution manager.
- Context: The user wants Yoda to behave recognizably like the Star Wars character and to be callable by AgentSmith, but the current V3 role set already assigns project ownership to Niaobe, execution to Morpheus, and validation to Oracle.
- Consequences: Yoda should be DM-able, optimized for critique, reframing, strategic advice, and second opinions, and wired so Smith can hand off to Yoda while Yoda primarily hands back to Smith, Niaobe, or Architect instead of directly owning project or software loops.
- Status: Accepted

- Date: 2026-03-31
- Decision: Neo should be designed as a host-backed OpenAI OAuth execution assistant, broader than Smith but not a replacement for the specialist roles.
- Context: The user wants a stronger assistant than Smith that can work directly in the writable workspace without Docker, while still fitting the V3 Zulip/gateway model and preserving Niaobe, Morpheus, Oracle, and Yoda as useful specialized roles.
- Consequences: Neo should use a host-workspace OpenAI OAuth runtime profile, be fully DM-able, be optimized for direct execution, code inspection, edits, and review, and hand off to Yoda/Niaobe/Architect/Morpheus/Oracle when specialization is clearly better instead of becoming a hidden all-purpose orchestrator.
- Status: Accepted

- Date: 2026-03-31
- Decision: Neo should run as a separate isolated OpenClaw host agent through the normal OpenClaw gateway, not through the local Docker-backed `run_agent.sh` path.
- Context: The embedded `openclaw agent --local` path is tied to shell-provided model credentials and the Docker-backed team runtime, while the desired Neo role should reuse the user's existing OpenAI Codex OAuth login and operate directly in the writable host workspace.
- Consequences: The Neo wrapper should call `openclaw agent --agent neo --json` through the repaired OpenClaw gateway, Neo should have its own isolated agent state and copied OAuth auth profiles, and the V3 gateway should treat Neo as another host-run visible role rather than trying to squeeze it into the Docker-only agent template.
- Status: Accepted

- Date: 2026-04-01
- Decision: The V3 Zulip gateway should post only one lightweight acknowledgement line before an agent's final visible reply.
- Context: The prior behavior emitted one acknowledgement plus three phase-status chat messages (`reading context`, `analyzing`, `drafting`) for every visible-agent run, which made normal DM usage noisy and distracting.
- Consequences: For new runs, direct messages should post `<Agent> received your message and is thinking.` and handoffs should post `<Agent> received the handoff from <Source> and is thinking.`. Detailed run phases remain internal for `/status`, but should not be broadcast as separate chat messages by default.
- Status: Accepted

- Date: 2026-04-01
- Decision: For this agent company setup, the preferred planning document is a lightweight agentic Software Development Plan rather than a full classic RUP plan.
- Context: The RUP example is useful for structure, milestones, roles, risks, and deliverables, but it is too heavy for the current chat-first, loop-based agent workflow where detailed day-to-day execution already lives in backlog files and Zulip threads.
- Consequences: Planning docs should keep the useful top-level structure from RUP while adapting it to visible agent roles, direct DMs, handoffs, milestone gates, loops, and lightweight reporting. Detailed execution remains in `BACKLOG.md`, `MILESTONES.md`, task files, and Zulip threads rather than in a giant monolithic plan.
- Status: Accepted

- Date: 2026-04-01
- Decision: The default project planning model should use a stronger project-local `PROJECT.md` as the charter and operating model, while `MILESTONES.md`, `BACKLOG.md`, `STATUS.md`, `DECISIONS.md`, and `RISKS.md` stay separate under `management/`; a standalone SDP is optional rather than the default.
- Context: Using both a full SDP and the existing project management files by default would duplicate scope, goals, roles, milestone intent, and operating rules, while the repository already has a natural split between stable project truth and frequently changing execution documents.
- Consequences: The workspace-level `PROJECT.md` should stay short and only describe workspace coordination, each project template should strengthen `PROJECT.md` to hold purpose/scope/success/roles/loops/quality gates, and the management files should continue to own milestones, backlog, live status, decisions, and risks without duplication.
- Status: Accepted

- Date: 2026-04-01
- Decision: In shared Zulip threads, explicit `@` mentions should be the activation signal for visible agents, and plain-name references should not be treated as equally strong routing cues.
- Context: The user wants mentions to use `@` before names so the system is not confused by ordinary narrative references to agents in the same message.
- Consequences: Shared-thread routing should prefer explicit `@` mentions, smoke tests should use `@**AgentName**` forms when talking to one visible role, and template guidance should assume mention-based activation instead of relying on plain-name matching.
- Status: Accepted

- Date: 2026-04-01
- Decision: Legacy split-bridge service units should live under `systemd/legacy/`, while the top-level `systemd/` directory should default to the V3 gateway service only.
- Context: Keeping `zulip-assistant-bridge.service` and `zulip-software-bridge.service` beside `zulip-gateway-v3.service` made the template feel mixed and encouraged accidental use of the older system.
- Consequences: New deployments should see `systemd/zulip-gateway-v3.service` as the primary service file, while older split-bridge units remain available but clearly isolated under `systemd/legacy/`.
- Status: Accepted

- Date: 2026-04-02
- Decision: Visible-role OpenClaw launches in the Zulip V3 gateway must use explicit per-thread session ids instead of relying on the default local session for each agent.
- Context: The live Oracle role replayed stale `ORACLE_LOCAL_OK` content from an earlier local sanity check because `openclaw agent --local` reused prior local context when the gateway did not pass an explicit session id.
- Consequences: The gateway now derives a deterministic `OPENCLAW_SESSION_ID` from the visible agent slug and Zulip thread run key, `.agents/run_agent.sh` passes that through to `openclaw agent --local --session-id ...`, and `.agents/run_team.sh` derives separate internal session ids for manager/planner/coder/tester stages. Visible runs no longer leak state across unrelated threads.
- Status: Accepted

- Date: 2026-04-02
- Decision: In shared Zulip threads, a human message with multiple explicit `@**Agent**` mentions should invoke only the first explicit mentioned visible agent; downstream roles must be activated by visible handoffs instead of by every mention embedded in the initial instruction text.
- Context: A smoke test message to `@AgentSmith` that referenced `@Niaobe`, `@Architect`, `@Morpheus`, and `@Oracle` in the body woke Niaobe immediately and blocked Smith's handoff, even though only Smith was the intended first responder.
- Consequences: The V3 gateway mention parser now treats the first explicit mention as the invocation target for human stream messages. Other agent mentions inside the same message remain useful as references or handoff instructions but no longer start parallel visible runs automatically.
- Status: Accepted

- Date: 2026-04-02
- Decision: Internal tester output from the Morpheus software loop must never be presented as visible Oracle approval, and Niaobe must require a real visible Oracle reply before closing a project phase that needs external validation.
- Context: The live software loop was completing Phase 2 and claiming `Oracle validation passed` even though only the internal tester had run; Niaobe then closed the phase without a visible Oracle step.
- Consequences: The Morpheus manager/team prompts now state explicitly that the internal tester is not the visible Oracle role, Morpheus summaries call out `internal tester` validation only, and Niaobe’s prompt explicitly refuses to close a project when Morpheus merely claims Oracle approval without a visible Oracle reply in the thread.
- Status: Accepted

- Date: 2026-04-02
- Decision: The template repository should ship only the current V3 gateway-based architecture and should not keep retired V1/V2 bridge, dispatcher, runtime, workflow, or supervisor artifacts in the main template tree.
- Context: The repository had accumulated multiple generations of design and runtime material, which made the default path ambiguous and left setup docs mixed between the current gateway model and older abandoned control-plane and split-bridge designs.
- Consequences: The shipped template now keeps only the V3 gateway path, current wrappers, current project template, and current docs. Future experiments should either replace the current path cleanly or live outside the default template tree until they become the new supported model.
- Status: Accepted
