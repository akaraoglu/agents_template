# Decisions Log

Record durable repo or process decisions here, especially behavior or tooling updates that should remain true over time.

## Entry Template
- Date:
- Decision:
- Context:
- Consequences:
- Status:

## Entries

- Date: 2026-04-13
- Decision: Human-facing project feedback should default to one canonical Zulip thread per project, and Morpheus internal software substeps should be surfaced there as Morpheus-owned phase updates rather than as separate child-agent topics.
- Context: The earlier routing split visible feedback across intake, design, software, verification, and escalation topics, which made project tracking noisy and forced operators to hunt across threads. The software loop also hid too much progress between visible dispatch and visible completion.
- Consequences: The first inbound human project message defines the canonical feedback thread for that project. Visible task assignments, visible results, control events, and Morpheus planning, implementation, and testing progress summaries all mirror into that thread. Internal planner, implementer, and tester task chatter remains hidden.
- Status: Accepted

- Date: 2026-04-13
- Decision: When the local OpenClaw deployment is pinned to one mandated Ollama model, the runtime should not keep permissive fallbacks to older local models, and the workspace executor must reconcile backend-agent drift before reuse.
- Context: A live implementer run for `P_2e39de70701447a591d27700665faff2` was provisioned on `ollama/gemma4:31b` but still reported `qwen3:8b` in runtime metadata, then returned `status=ok` with no visible payloads. The OpenClaw defaults still allowed qwen fallback, and the executor reused backend agents blindly.
- Consequences: The deployment should keep Gemma as the only active local fallback path when the operator requests a single-model policy, and `openclaw_workspace_executor.py` now deletes and recreates backend agents when their stored model or workspace no longer matches the requested configuration. Empty-payload OpenClaw runs are also allowed one session-harvest recovery pass before being treated as blocked runtime failures.
- Status: Accepted

- Date: 2026-04-13
- Decision: The repo-local Zulip credential directory must be self-contained. `openclaw_agents/state/zuliprc` should contain local regular files, not symlinks into older bridge or gateway repos.
- Context: After the legacy V3 gateway was removed, the last remaining carryover was that the new repo-specific gateway still loaded bot credentials through symlinks pointing at `/home/alik/workspace/zulip/assistant_bridge` and `/home/alik/workspace/zulip/software_bridge`. That kept the new system operationally dependent on older repos even though the runtime logic had been migrated.
- Consequences: The local `.zuliprc` files under `openclaw_agents/state/zuliprc` were replaced with regular files and the repo-specific gateway was restarted successfully against those local files. Future cleanup and deployment work should treat the local credential directory as the authoritative runtime input for this scaffold.
- Status: Accepted

- Date: 2026-04-13
- Decision: New chat-created projects must auto-provision an isolated workspace and register `workspace_states` immediately during intake instead of requiring manual seeding before the first software loop.
- Context: The new Zulip intake path successfully created and framed human-requested projects, but fresh projects still blocked in `Morpheus` because `workspace_ref` only existed in the manual bootstrap flow. That meant chat ordering worked only for pre-seeded projects, which violated the intended operator experience.
- Consequences: `zulip_gateway.py` now provisions a project workspace through `scheduler/workspace_provisioner.py` when a new project is created or when an older project is still missing `workspace_ref`. The provisioner copies the committed workspace template, writes initial `PROJECT.md` and `STATUS.md`, records `workspace_states`, and marks the project schedulable for the live software loop.
- Status: Accepted

- Date: 2026-04-13
- Decision: Zulip sender classification must trust sender email over display name; if a message has an email that is not one of the managed bot emails, it is a human even if the full name matches an agent id such as `master`.
- Context: The real local human account is named `master`, which collided with the deferred `MASTER` agent id. The original gateway service classified that human user as a bot based on display name alone, so real human chat messages were ignored instead of entering `AgentSmith`.
- Consequences: `zulip_gateway_service.py` now treats any non-bot sender email as human and only falls back to name-based bot detection when no sender email is available. Live human chat messages from the local `master` account now enter the control-plane intake path correctly.
- Status: Accepted

- Date: 2026-04-13
- Decision: The `openclaw_workspace` runtime must use a reduced execution context, a longer worker budget than the internal OpenClaw agent timeout, and session-result harvesting as a recovery path when the CLI transport returns late.
- Context: The first live software smoke showed that the control plane, gateway, and worker path were healthy, but the workspace-backed OpenClaw transport could outlive the worker budget and still finish successfully in its own session files. The full serialized task context also pushed unnecessary bulk into the model prompt.
- Consequences: `openclaw_workspace_executor.py` now trims artifact and task context before invoking the model, passes an explicit OpenClaw timeout below the worker ceiling, kills the process tree on timeout, and can recover a finished response from the session files when the CLI transport lags. Future changes to this backend should preserve that timeout layering and session-harvest fallback.
- Status: Accepted

- Date: 2026-04-13
- Decision: `Morpheus` must refuse to dispatch `IMPLEMENT_SOFTWARE_TASK` when the project has no `workspace_ref`.
- Context: Before this change, a project without a workspace could still enter the live software loop and only fail once the `implementer` worker reached the workspace-backed executor. That put an orchestration precondition failure in the wrong layer and produced poor operator feedback.
- Consequences: The Morpheus rule loop now blocks immediately with an escalation packet when no workspace is attached, and the worker-side missing-workspace path is treated as a blocked runtime issue rather than an implementation failure.
- Status: Accepted

- Date: 2026-04-13
- Decision: Local template bring-up should use repo-local env files and transient user services under `openclaw_agents/state/` until a packaged installer or host-level deployment wrapper exists.
- Context: The current repository ships runnable service entrypoints and systemd units, but this environment does not yet have a finalized host installation path or managed `/etc` deployment bundle. The user wanted the stack brought up immediately in the repo workspace rather than only documented.
- Consequences: Local bring-up now uses `openclaw_agents/state/openclaw-zulip-gateway.env`, `openclaw_agents/state/openclaw-runtime-workers.env`, repo-local state directories, and transient `systemd --user` services. The committed `.gitignore` now excludes `openclaw_agents/state/`, and operators should treat this as the default local smoke/development path until a packaged deployment flow is added.
- Status: Accepted

- Date: 2026-04-13
- Decision: `Neo` and `MASTER` must remain disabled in the live gateway subscriptions and worker fleet until their execution logic is intentionally implemented.
- Context: The user explicitly deferred `Neo` and `MASTER` execution logic to the end. During live bring-up, enabling their visible identities or workers would have created routable but unsupported runtime paths.
- Consequences: The live gateway config subscribes only the supported visible agents, and the live worker config keeps `neo` and `master` disabled. Future deployment changes should not enable those two roles until their execution path, routing behavior, and operational semantics are implemented and tested.
- Status: Accepted

- Date: 2026-04-13
- Decision: Prompt files in `openclaw_agents/prompts/` must remain contract-driven role instructions derived from the registry, routing rules, and orchestrator state machines rather than becoming a second independent workflow spec.
- Context: The new control plane now has explicit authority boundaries, scheduling rules, and state-machine behavior in dedicated config files. Leaving prompts as placeholders was not viable, but letting prompts redefine routing or ownership would create drift between implementation and documentation.
- Consequences: Future behavior changes should be made in the authoritative spec, registry, routing, and state-machine files first, then reflected in prompts as execution guidance. Prompt edits should not silently expand a role's authority beyond the contracts already encoded elsewhere.
- Status: Accepted

- Date: 2026-04-13
- Decision: Operations docs must only reference runnable entrypoints that exist in the repository; when a deployment wrapper is still missing, the runbook must call out that gap explicitly instead of inventing a command or service.
- Context: The repository now includes the gateway normalization and dispatch-planning logic but does not yet include a production Zulip polling daemon or service entrypoint. Leaving the runbooks as placeholders was not acceptable, but documenting imaginary commands would create operator confusion and drift.
- Consequences: The Zulip bootstrap runbook now documents the current boundary honestly, the systemd unit remains a deployment placeholder until a real daemon exists, and future operational docs should distinguish between implemented code paths and intended next wrappers.
- Status: Superseded

- Date: 2026-04-13
- Decision: The shared Zulip gateway service should manage one Zulip rc file per visible bot identity inside one process, and it must normalize rendered Zulip HTML back into fenced-text form before schema validation.
- Context: The integrated spec requires one gateway service to manage visible bot identities rather than per-agent clients, and Zulip event payloads arrive as rendered content instead of the raw markdown that the schema-aware gateway parser expects.
- Consequences: The daemon now loads `<agent_id>.zuliprc` files from one configured directory, polls all visible bot queues in one service, and converts rendered code blocks back into triple-fenced text so authoritative YAML payloads survive transport and can be validated deterministically.
- Status: Accepted

- Date: 2026-04-13
- Decision: The default runtime execution backend should be a queue-backed packet contract: dispatch creates a validated task envelope, persists `task_attempts` and `agent_runs`, writes the packet into the workspace or state queue, and completion returns through a validated response-envelope callback.
- Context: The control plane now had routing and gateway behavior but still lacked a concrete runtime handoff model. Hardcoding live LLM or sandbox launch commands at this stage would have created environment-specific drift, while a queue-backed packet contract gives a stable integration point for external runners and future executors.
- Consequences: `RuntimeDispatcher` now serves as the canonical handoff surface, runtime packets land in `artifacts/incoming/` when a workspace exists, and response callbacks are responsible for closing attempts, updating runs, persisting artifacts, and capturing safe-boundary snapshots back into the authoritative store.
- Status: Accepted

- Date: 2026-04-13
- Decision: Worker execution should remain disabled by default in committed config, with opt-in `mock` and `subprocess` executors, and completed runtime results should still be mirrored only through the shared gateway service.
- Context: The template needs a real worker path now, but auto-running queued tasks by default would be unsafe in a reusable repo. At the same time, letting workers post to Zulip directly would break the single-gateway transport model.
- Consequences: `runtime/worker_config.yaml` now defaults every agent to `disabled`, local smoke tests can opt into `mock` explicitly, real deployments can opt into `subprocess` per agent, and the shared gateway remains the only component that mirrors authoritative task results back into Zulip.
- Status: Accepted

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

- Date: 2026-04-02
- Decision: `openclaw_agents/complete_agentic_software_workflow_with_zulip.md` is now the primary handoff and planning source for the next architecture migration, superseding the earlier split `agentic_workflow.md`, `zulip_communication_spec.md`, and `SOFTWARE_WORKSPACE_README.md` documents when they conflict.
- Context: The integrated handoff document combines the workflow model, Zulip communication contract, workspace contract, persistence requirements, implementation order, and builder output list into one authoritative spec, which removes ambiguity that remained when planning from several partially overlapping files.
- Consequences: Future migration planning should start from the integrated handoff first, the new repo layout should match its builder output structure and two-loop control-plane design, and the older split docs should be treated as supporting references or removed/replaced during the structural migration.
- Status: Accepted

- Date: 2026-04-02
- Decision: The active `openclaw_agents/` template layout should now be organized by implementation boundary (`specs`, `config`, `schemas`, `orchestrators`, `prompts`, `communication`, `runtime`, `database`, `evaluation`, `operations`, `templates`) rather than by the old V3 wrapper and gateway folders (`.agents`, `zulip_gateway_v3`, `project_template`, `systemd`).
- Context: The integrated handoff defines a control-plane-first system with explicit builder outputs and clean boundaries between specs, state machines, communication, runtime, persistence, and workspace templates. The earlier V3 layout encoded a chat-first wrapper system and no longer matched the target architecture.
- Consequences: New implementation work should land in the new boundary-based directories, supporting legacy docs should live under `specs/supporting/`, and removed V3 wrapper or bridge paths should not be recreated unless the architecture direction changes again.
- Status: Accepted

- Date: 2026-04-02
- Decision: The next implementation phase must add a first-class `scheduler/` layer and scheduling-related schemas before gateway, runtime, or prompt implementation proceeds.
- Context: `project_scheduling_and_context_switching.md` introduces central scheduling, active-project leases for singleton orchestrators, safe-boundary switching, project snapshots, workspace isolation, control-plane commands, and recovery rules. The current scaffold created from the integrated handoff alone does not yet include those modules or schemas.
- Consequences: The repo layout should grow a `scheduler/` package plus `control_event`, `project_snapshot`, `orchestrator_lease`, and `project_schedule_record` schemas; the database schema must include scheduling and snapshot entities; and implementation order should prioritize scheduling contracts before higher-level execution code.
- Status: Accepted

- Date: 2026-04-13
- Decision: Scheduler lease acquisition may create a minimal control-plane `agent_runs` record when no explicit runtime-run record exists yet, so lease persistence remains referentially valid before the gateway and runtime layers are fully implemented.
- Context: The database schema intentionally ties `orchestrator_leases.lease_owner_run_id` to `agent_runs.run_id`, but the first scheduler implementation acquires leases before the gateway or runtime has created any concrete agent run rows. The initial smoke test failed on that foreign key.
- Consequences: The lease manager now ensures a lightweight `agent_runs` row exists for scheduler-owned work before persisting the lease. Later gateway and runtime code can replace or enrich those rows, but the control plane no longer depends on hand-created run records just to schedule a project.
- Status: Accepted

- Date: 2026-04-13
- Decision: Snapshot-requiring control commands such as `PAUSE_PROJECT`, `STATUS_SNAPSHOT`, and safe `SWITCH_PROJECT` must reject cleanly when a project does not yet have a persisted `workspace_ref`, rather than creating partial snapshot state or throwing an unhandled exception.
- Context: The first gateway smoke test tried to pause a project created from a free-form human intake message before any workspace had been assigned. The snapshot store correctly refused to persist a snapshot without `workspace_ref`, but the control-command path initially let that bubble up as an exception.
- Consequences: The control-command layer now returns explicit rejected control-event results for snapshot-dependent commands when workspace state is still incomplete. This keeps the gateway deterministic and preserves the scheduling rule that safe boundaries require persisted state and artifact references.
- Status: Accepted

- Date: 2026-04-13
- Decision: The first built-in execution backend should be an opt-in deterministic executor for `morpheus`, `planner`, `implementer`, and `tester`, while the committed worker config remains conservative and disabled by default.
- Context: The control plane needed a real end-to-end software loop before external model or subprocess integrations were ready. A deterministic built-in backend can validate task lifecycles, parent-child orchestration, artifact persistence, and bounded retries without depending on external runtimes.
- Consequences: `runtime/worker_runner.py` now accepts `--default-executor builtin`, `runtime/role_executor.py` implements the local execution behavior for the first software-loop roles, and operators can use the builtin path for local smoke tests without changing the default safety posture of `runtime/worker_config.yaml`.
- Status: Accepted

- Date: 2026-04-13
- Decision: Internal-only `planner`, `implementer`, and `tester` task results should not be mirrored back to Zulip as standalone authoritative result messages.
- Context: Once Morpheus advances its own child-task loop automatically, mirroring every internal child result would flood the visible Zulip streams and leak internal-only stages that the registry marks as non-visible.
- Consequences: Result mirroring now excludes internal software-loop child agents, while the visible parent Morpheus task still mirrors the authoritative software-loop outcome back to Zulip.
- Status: Accepted

- Date: 2026-04-13
- Decision: The builtin deterministic execution path should cover the first full visible project loop (`AgentSmith -> Niaobe -> Architect -> Morpheus -> Oracle`) in addition to the nested Morpheus software loop.
- Context: After the software-loop engine landed, the largest remaining control-plane gap was project orchestration. Without a visible-loop builtin path, the system could not validate intake handoff, project routing, Oracle feedback handling, or project closure without an external runtime.
- Consequences: `runtime/role_executor.py` now supports the visible project roles, `orchestrators/niobe_engine.py` owns the builtin project-loop logic, successful `FRAME_PROJECT` results automatically materialize real `ORCHESTRATE_PROJECT` tasks, and Niaobe is requeued explicitly at persisted child-task boundaries after Architect, Morpheus, and Oracle complete.
- Status: Accepted

- Date: 2026-04-13
- Decision: `project_status_report` and `project_closure_report` artifacts produced by Niaobe should map to the explicit `PROJECT_STATUS_SNAPSHOT_PERSISTED` safe-boundary type during response recording.
- Context: Once Niaobe started producing persisted status and closure artifacts as part of the builtin project loop, treating them as generic task-result boundaries lost the project-specific safe-boundary semantics required by the scheduling spec.
- Consequences: Snapshot capture for Niaobe status-bearing responses now records the project-status boundary type explicitly, which keeps pause/resume/switch reasoning aligned with the control-plane contracts.
- Status: Accepted

- Date: 2026-04-13
- Decision: The first real external execution contract should be a prompt-aware subprocess adapter that builds a structured execution context from the prompt files, state store, workspace metadata, and artifact inputs before invoking the backend.
- Context: The builtin deterministic executor is useful for control-plane validation, but it does not exercise the real boundary where an external runtime consumes prompt text and project state. The older raw `subprocess` path passed only packet-level environment variables and left too much context reconstruction to the child process.
- Consequences: `runtime/external_executor.py` now writes a JSON execution-context file and exports `OPENCLAW_EXECUTION_CONTEXT` plus prompt and model metadata to `prompt_subprocess` backends. The builtin executor remains available as a fallback, while real integrations can target the richer adapter without coupling themselves to the DB layout.
- Status: Accepted

- Date: 2026-04-13
- Decision: The committed regression suite should use the Python standard library `unittest` runner instead of assuming `pytest` is available in every local control-plane environment.
- Context: This repo currently has no committed Python environment bootstrap, and the target machine for this change did not have `pytest` installed. Leaving the new coverage as `pytest`-only would have shipped tests that could not be executed in the repo's actual current environment.
- Consequences: The first committed automated suite under `tests/` is implemented with `unittest`, and the runbook documents `python3 -m unittest discover -s tests -v` as the supported local command.
- Status: Accepted

- Date: 2026-04-13
- Decision: The default local Ollama model for the scaffold should be pinned explicitly to `gemma4:31b`, and `prompt_subprocess` should fall back to a built-in Ollama runner when no explicit command is configured.
- Context: The previous model map still used abstract local model hints, so the new prompt-aware runtime contract existed without a concrete backend path. The installed local model on this machine is `gemma4:31b`, and the next unfinished control-plane gap was the lack of a ready-made local runtime behind `prompt_subprocess`.
- Consequences: `openclaw_agents/config/model_map.yaml` now resolves all local profiles to `gemma4:31b`, `openclaw_agents/runtime/ollama_prompt_runner.py` provides a concrete local backend for the prompt-aware execution context, the runner uses the local Ollama HTTP API by default for clean structured output and retains a CLI fallback for explicit override or test use, and `runtime/worker_runner.py` can execute `prompt_subprocess` jobs with no custom command as long as the model hint resolves to a valid local Ollama model.
- Status: Accepted

- Date: 2026-04-13
- Decision: The default deployment pattern for runtime workers should be one shared worker-supervisor service that runs one child worker process per enabled agent, with a templated single-agent systemd unit kept only for explicit pinning or debugging.
- Context: The runtime layer already had queue consumers, but no explicit operational model for long-running worker processes. Running every role through one multiplexing worker process would hide agent-specific failures and block concurrent role execution, while managing many ad hoc commands manually would not be operationally stable.
- Consequences: `openclaw_agents/runtime/worker_supervisor.py` now validates `worker_config.yaml`, supervises one `worker_runner` child per enabled agent, and supports a `--check` mode for service preflight. The systemd folder now includes `openclaw-worker-supervisor.service` as the recommended default and `openclaw-worker@.service` as the optional single-agent template.
- Status: Accepted

- Date: 2026-04-13
- Decision: The first real code-executing software backend should use workspace-scoped OpenClaw agents for `implementer` and `tester`, with one dedicated OpenClaw agent id derived from the project workspace and role.
- Context: The control plane needed a real backend that can mutate the actual project workspace and execute validation commands, but the generic Ollama prompt runner only produces structured responses and cannot safely edit a repo by itself. The local OpenClaw runtime is already installed and supports isolated agents with explicit workspace bindings.
- Consequences: `openclaw_agents/runtime/openclaw_workspace_executor.py` now provisions per-project OpenClaw agents on demand, binds them to the project workspace, invokes them through `openclaw agent --json`, and normalizes their visible structured reply into `code_change` or `test_execution_report` artifacts. `implementer` and `tester` can now be deployed with `executor: openclaw_workspace` once the operator enables them in `worker_config.yaml`.
- Status: Accepted

- Date: 2026-04-13
- Decision: Pre-deployment resume validation must combine persisted control-plane state with live git/worktree inspection, and generated runtime paths must not be treated as recovery blockers by themselves.
- Context: The original recovery layer only checked stored workspace metadata and path existence. That was not enough to detect the actual unsafe states called out in the scheduling spec, such as dirty tracked files, branch drift, stale active leases, or interrupted runs that still looked alive. At the same time, the runtime legitimately writes untracked packets and reports under `artifacts/` and optional `.agents/`.
- Consequences: `workspace_validator.py` now checks git root, branch or worktree identity, dirty tracked files, untracked non-generated files, and checkpoint-reference validity when the workspace is a git repo. `recovery_manager.py` now blocks resume on active leases, active task attempts, or active agent runs and persists richer details into `recovery_events`. Generated runtime paths under `artifacts/` and `.agents/` are ignored for resume safety unless they correspond to tracked-file mutations elsewhere.
- Status: Accepted

- Date: 2026-04-13
- Decision: The first live deployment on this machine should run the repo-specific gateway and worker supervisor as user-level transient systemd units backed by repo-local env files and a repo-local Zulip rc compatibility directory, while `master` and `neo` stay out of the live Zulip subscription surface.
- Context: The committed unit files assume `/etc` env files and a system-level deployment, but the local OpenClaw workspace backend needs to run as `alik`, and this machine already has the relevant Zulip bot credentials under legacy filenames in sibling repos. The same deployment also intentionally defers `Neo` and `MASTER` runtime logic, so loading their Zulip identities into the live gateway would add unimplemented surface area.
- Consequences: Live bring-up now uses repo-local env files under `openclaw_agents/state/`, a repo-local `zuliprc/` compatibility directory that maps the old bot filenames onto the new agent ids, and transient user services named `openclaw-agent-template-zulip-gateway.service` and `openclaw-agent-template-worker-supervisor.service`. The gateway uses `--insecure` on this machine because the local Zulip deployment presents a self-signed certificate, and `master` plus `neo` have empty live subscriptions until their runtime logic exists.
- Status: Accepted

- Date: 2026-04-13
- Decision: `agent_template` must remain template-only, and all live OpenClaw state for this system must live under `/home/alik/workspace/claw_software_workspace`.
- Context: The earlier bring-up used repo-local state under `openclaw_agents/state/` for convenience, but that polluted the template repository with the live SQLite DB, Zulip credentials, runtime queues, and generated project workspaces. The requested target boundary is a reusable template repo plus an external live workspace.
- Consequences: The committed docs and examples now point runtime state at `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/` and `/home/alik/workspace/claw_software_workspace/projects/`; `ProjectWorkspaceProvisioner` no longer falls back into the template repo; the live services now read env files from the external workspace; and the template repo should not contain `openclaw_agents/state/` in normal operation.
- Status: Accepted

- Date: 2026-04-13
- Decision: The committed OpenClaw systemd unit templates should be user services that read env files from `claw_software_workspace`, and any shell variable used inside `ExecStart` or `ExecStartPre` must be escaped as `$$...`.
- Context: The cleaned deployment now runs as user services rather than root-level system services, and the first attempt to start the committed worker-supervisor unit failed because systemd expanded `$cmd[@]` and other shell variables before `bash` received them.
- Consequences: `zulip-gateway.service`, `openclaw-worker-supervisor.service`, and `openclaw-worker@.service` now target `default.target`, read env files from `%h/workspace/claw_software_workspace/.agents/state/openclaw_agents/env/`, and escape shell variables correctly so the array-based startup commands execute under `bash` as intended.
- Status: Accepted

- Date: 2026-04-13
- Decision: Human-facing feedback for a project should default to one canonical Zulip thread derived from the first inbound project message, while phase-specific topics remain secondary routing detail rather than the primary operator surface.
- Context: The original integrated spec exposed intake, design, software, verification, and escalation topics, and the first implementation mirrored visible results back to those task-specific destinations. That made the audit trail technically consistent but produced a poor operator experience because one project appeared fragmented across many topics.
- Consequences: `store.get_project_feedback_thread()` now resolves the canonical operator thread from persisted inbound Zulip links; visible dispatches, visible task results, and control-event mirrors now prefer that thread; and the human-readable summaries for those mirrors now explicitly describe the step, owner, and next step so operators can follow progress in one place.
- Status: Accepted

- Date: 2026-04-14
- Decision: When the operator mandates one model, the live OpenClaw runtime must remove fallback models entirely, and workspace-backed `implementer` or `tester` runs must use isolated backend-agent identities per run instead of reusing one agent per project-role.
- Context: The blocked Fibonacci project showed two coupled failure modes: OpenClaw session state could drift from the requested Gemma configuration back onto an older `qwen3:8b` session, and per-project-role backend agent reuse let stale session history survive into later retries even after the visible control-plane task changed.
- Consequences: The live OpenClaw config now keeps only `ollama/gemma4:31b` active for the default deployment, and `openclaw_workspace_executor.py` now derives backend agent ids from the runtime run identity so each workspace-backed execution gets a fresh OpenClaw session boundary. This reduces cross-run contamination and makes a strict single-model deployment enforceable in practice.
- Status: Accepted

- Date: 2026-04-14
- Decision: Non-terminal task queries in the control plane must treat only `PENDING` and `RUNNING` tasks as active; `BLOCKED`, `NEEDS_CLARIFICATION`, `FAILED`, `SUCCESS`, and `CANCELLED` are all terminal for orchestration wait logic.
- Context: Niaobe stayed stuck in `WAIT_FOR_EXTERNAL` on a completed Morpheus retry because the store-layer child-task query still surfaced an older blocked Morpheus child as “active”, so Niaobe never advanced to Oracle even though a newer software-delivery task had already succeeded.
- Consequences: `ControlPlaneStore.list_open_tasks()` and `ControlPlaneStore.list_child_tasks(..., include_terminal=False)` now filter to `PENDING` and `RUNNING` only. Niaobe and Morpheus therefore wait only on truly active child tasks and can correctly ignore earlier blocked retries when a later child has already delivered the required artifact.
- Status: Accepted

- Date: 2026-04-14
- Decision: Runtime execution context must be built through exactly two generic builders: `build_project_context(...)` for workspace-root and project-scope roles, and `build_task_context(...)` for task-scope roles.
- Context: The earlier external and workspace executors had started to diverge in how they assembled prompt context, which risked leaking broader state back into the software roles and made the system harder to extend when new roles are added. The requested policy is intentionally simple: `master`/`neo`/`agent_smith` get workspace-root scope, `niaobe`/`architect`/`oracle` get project scope, and `morpheus` plus the internal software team get task scope.
- Consequences: `ExecutionContextBuilder` in `openclaw_agents/runtime/external_executor.py` now owns scope selection and routes all runtime packets through only `build_project_context(...)` or `build_task_context(...)`. `openclaw_workspace_executor.py` and `ollama_prompt_runner.py` now consume the normalized `context_payload` directly rather than reconstructing their own broader prompt context. Software roles therefore stay bounded to project-folder task context, while future visible roles can reuse the same generic scope model without another builder explosion.
- Status: Accepted

- Date: 2026-04-14
- Decision: A response envelope with task `status` of `PENDING` or `RUNNING` keeps the parent task open, but it still finalizes the specific task attempt and agent run that produced the response.
- Context: Orchestration roles such as `Niaobe` and `Morpheus` legitimately emit `status=\"RUNNING\"` when they hand work off to a child and leave the parent task in `WAITING_EXTERNAL`. The earlier dispatcher persisted that same `RUNNING` state onto `task_attempts` and `agent_runs` even while also setting `finished_at` / `ended_at`, which created ghost live rows and distorted queue introspection.
- Consequences: `RuntimeDispatcher.record_response()` now maps handoff responses (`PENDING` / `RUNNING`) to terminal lifecycle status `SUCCESS` for `task_attempts` and `agent_runs`, while preserving the parent task’s own `status` as `PENDING` or `RUNNING`. Queue and recovery logic can therefore trust open attempts/runs as truly active instead of historical handoff records.
- Status: Accepted

- Date: 2026-04-14
- Decision: Workspace management files are now a control-plane projection maintained by the system, not passive template files or ad hoc prompt output.
- Context: The integrated design expected `PROJECT.md` and `management/` to be the human-readable source of truth inside each project workspace, but the implementation only provisioned placeholders and then kept authoritative progress in SQLite plus artifacts. That left live project workspaces without current `STATUS.md`, `BACKLOG.md`, `MILESTONES.md`, `DECISIONS.md`, or `TEST_REPORT.md`.
- Consequences: `WorkspaceManagementWriter` now repairs missing workspace scaffolds and renders `PROJECT.md` and `management/*.md` directly from project state, task graph state, accepted artifacts, workspace state, and control events. The writer is triggered during provisioning, task dispatch, accepted responses, and control-command recording so the management layer tracks the live project loop automatically.
- Status: Accepted

- Date: 2026-04-14
- Decision: The `openclaw_agents.runtime` package must use lazy exports instead of eager package-level imports.
- Context: Adding the management writer introduced a valid control-command path that imports `artifact_parsers` without needing the rest of the runtime stack. The previous eager `runtime/__init__.py` imported `dispatcher`, which imported `zulip_gateway`, which imported `control_commands`, creating a circular import during live control-command execution.
- Consequences: `openclaw_agents/runtime/__init__.py` now resolves exports lazily through `__getattr__`, which preserves package-level convenience imports without forcing dispatcher/gateway/control-command cycles during unrelated imports.
- Status: Accepted

- Date: 2026-04-14
- Decision: Workspace-backed OpenClaw agent state should live outside the visible project root, even when the agent is bound to that project workspace for code execution.
- Context: The current `openclaw_workspace` executor provisions backend agents with `openclaw agents add --workspace <project-root>` and no explicit `--agent-dir`. In live runs, that causes OpenClaw bootstrap/persona files such as `BOOTSTRAP.md`, `SOUL.md`, and `IDENTITY.md` to appear in the project root, which conflicts with the intended project workspace contract.
- Consequences: `openclaw_workspace_executor.py` now treats each project's hidden `.agents/` tree as the OpenClaw runtime boundary: backend agents use `--workspace <project-root>/.agents/openclaw/workspace`, `--agent-dir <project-root>/.agents/openclaw/agents/<backend-agent-id>/agent`, and a `project` symlink inside the hidden workspace points back to the visible project root for real code edits. Runtime packets and worker response logs also live under `.agents/runtime/`.
- Status: Accepted

- Date: 2026-04-14
- Decision: Phase 2 persistence is split into a shared scheduler registry plus per-project databases under `project/.agents/project.db`.
- Context: Phase 1 moved runtime packets, response logs, and OpenClaw workspace state under each project's hidden `.agents/` tree, but authoritative task/artifact/history state still lived in one global SQLite file. That kept project history mixed across projects and prevented a project from being self-contained.
- Consequences: `ControlPlaneStore` now routes `tasks`, `task_attempts`, `agent_runs`, `artifacts`, `decisions`, `escalations`, `zulip_message_links`, `project_snapshots`, `control_events`, `workspace_states`, and `recovery_events` into each project's `.agents/project.db`. The shared DB continues to own `projects` as the scheduler registry summary plus `scheduling_records` and `orchestrator_leases`. Project-facing modules keep using the same store facade rather than talking to multiple databases directly.
- Status: Accepted

- Date: 2026-04-14
- Decision: After live migration, the shared control-plane DB should be treated as scheduler-summary-only and should not retain project-local history rows.
- Context: The Phase 3 migration moved legacy workspace-backed projects from the shared SQLite database into per-project `.agents/project.db` files. Live verification after the migration showed the shared DB can operate with zero rows in project-local tables while still retaining `projects` summary rows and running the gateway/worker services normally.
- Consequences: Operational checks should now expect `tasks`, `task_attempts`, `agent_runs`, `artifacts`, `decisions`, `escalations`, `control_events`, `project_snapshots`, `zulip_message_links`, `workspace_states`, and `recovery_events` to live only in project-local DBs. The shared DB remains the scheduler registry and lease store, not a fallback archive for completed project history.
- Status: Accepted

- Date: 2026-04-14
- Decision: The project orchestrator is canonically named `Niaobe`, and runtime-facing compatibility aliases for the previous spelling should be removed once live credentials are renamed.
- Context: The first rename pass needed a temporary bridge because the live Zulip credential filename still used the older spelling, but that bridge should not remain in the steady-state runtime.
- Consequences: Active runtime/config/schema paths use `niaobe` as the project orchestrator id and `Niaobe` as the display name. The live credential file is now `niaobe.zuliprc`, and the gateway no longer carries a runtime fallback for the previous spelling.
- Status: Accepted

- Date: 2026-04-14
- Decision: Large structured projects should be represented as a `project_delivery_plan` and executed by Niaobe one work item at a time.
- Context: The previous project loop treated software delivery as one monolithic `ORCHESTRATE_SOFTWARE` step, which could not express milestone gating, milestone-specific backlog tracking, or sequential verification before advancing to the next requested task.
- Consequences: AgentSmith framing now emits a `delivery_plan_seed` when milestone structure is present in the intake. Niaobe materializes that into a `project_delivery_plan`, dispatches one work item at a time to Morpheus, requires Oracle verification for each work item before advancing, and management files project milestone/backlog status from that plan plus the live task/report state.
- Status: Accepted

- Date: 2026-04-14
- Decision: `ControlPlaneStore` startup must self-migrate legacy `niobe` database schema/value state to `niaobe`.
- Context: The canonical rename in code/config was not enough for the live gateway because existing shared SQLite files still had `orchestrator_leases`, `projects`, `control_events`, and `recovery_events` schemas constrained to `niobe`, which caused the repo-specific Zulip gateway to crash during startup lease initialization.
- Consequences: Store initialization now rebuilds legacy constrained tables and rewrites persisted structured values so both the shared scheduler DB and older project-local DBs can boot against the canonical `niaobe` runtime identity without manual database cleanup.
- Status: Accepted
