# Corrections Log

Append one-off lessons here when a mistake is discovered, the agent is corrected, or guidance becomes outdated.

## Entry Template
- Date:
- Problem:
- Root cause:
- New rule:
- Where it was recorded:

## Entries

- Date: 2026-04-13
- Problem: The first real human Fibonacci request posted from Zulip did not enter the new intake path even after the repo-specific gateway and workers were running.
- Root cause: Two separate deployment faults overlapped: a legacy system-level `zulip-gateway-v3.service` was still consuming the same bot identities, and the new gateway service misclassified the local human user `master` as a bot because its full name matched a deferred agent id.
- New rule: Do not consider the new chat workflow cut over until legacy Zulip responders are removed or neutralized and the gateway classifies senders by email before display name. A human account may legally share a display name with an agent id; sender email is the authority.
- Where it was recorded: `openclaw_agents/communication/zulip_gateway_service.py` and `.agents/memory/changelog.md`

- Date: 2026-04-13
- Problem: The first live end-to-end smoke targeted the real `openclaw_workspace` software path directly, which made the bring-up look ambiguous when the workspace-backed executor stalled even though the gateway, scheduler, and visible worker loop were already functioning.
- Root cause: The deployment smoke conflated two different risks: control-plane bring-up and workspace-backed OpenClaw runtime health. The visible builtin path and the real software executor do not fail for the same reasons.
- New rule: For deployment bring-up, prove the live stack first with a supported visible-path smoke such as `FRAME_PROJECT` or `DESIGN_ARCHITECTURE`, then separately test the workspace-backed `implementer` and `tester` path as its own runtime dependency.
- Where it was recorded: `.agents/memory/changelog.md`

- Date: 2026-04-13
- Problem: The first attempt to initialize the fresh smoke workspace ran `git init` and `git checkout -B main` in parallel, so the branch switch raced before the nested repo existed and resolved against the outer template repo instead.
- Root cause: Repository bootstrap commands for a nested git workspace were parallelized even though they have a hard ordering dependency.
- New rule: Treat nested workspace git bootstrap as strictly sequential: create the repo first, then configure it, then switch branches, then commit the checkpoint. Do not parallelize `git` setup steps that depend on the previous command having created `.git`.
- Where it was recorded: `.agents/memory/changelog.md`

- Date: 2026-03-30
- Problem: The live Niaobe verification run for `projects/fibonacci_niobe_test` stopped after planning instead of reaching Morpheus and Oracle.
- Root cause: The live `run_assistant_spawn.sh` project-manager flow is implemented as `Niaobe initial pass -> Architect -> Niaobe review` and only emits `MORPHEUS_READY` / `MORPHEUS_TASK`; it never actually invokes `run_team.sh` or any Morpheus path. The live `projectmanager.txt` prompt is also outdated and still tells Niaobe to read `PROJECT.md` from the repository root instead of the selected project's own `PROJECT.md` and `management/`.
- New rule: Treat the current Niaobe flow as planning-only until the runner actually executes the Morpheus handoff and the Niaobe prompt is updated to project-local instructions. Do not assume `MORPHEUS_READY: yes` means the software loop has started unless a real software-topic handoff or `run_team.sh` invocation is visible.
- Where it was recorded: `.agents/memory/changelog.md`

- Date: 2026-03-30
- Problem: The first live repair of the Niaobe loop still misread some successful Oracle and Morpheus outputs, leaving fields like `ORACLE_DECISION` empty even when the agent had clearly returned a valid answer.
- Root cause: The shell parsers in `run_team.sh` and `run_assistant_spawn.sh` only recognized plain multiline `SECTION:\nvalue` blocks. They did not accept markdown-formatted headers like `**PLAN_SUMMARY:**` or inline one-line values like `ORACLE_DECISION: accepted`.
- New rule: Shell-side agent output parsing must tolerate both decorated headers and inline `KEY: value` responses, because the live models do not reliably stick to one exact formatting style even when prompted with strict schemas.
- Where it was recorded: `.agents/memory/decisions.md`
- Date: 2026-03-30
- Correction: Template `systemd` bridge unit files must not commit live `/home/alik/...` paths.
- Why it was wrong: The initial reusable service files were copied from the live host setup and caused the template safety check to fail because they embedded one machine's bridge paths and username.
- Correct guidance: Keep committed service files as placeholders or examples, and substitute the real bridge user and directories during installation on the target host.

- Date: 2026-03-31
- Problem: The first V3 planning recommendation still leaned on strict topic ownership even after the user clarified that all visible agents should be DM-able and not locked into rigid topic-bound permissions.
- Root cause: The design carried over too much of the heavier V2 ownership model instead of fully adapting to the simpler chat-first use case.
- New rule: V3 should use light thread coordination (`active_run_id`, `current_speaker`, `awaiting_from`, `participants`, `mode`) plus mention/handoff activation rules, not strict topic ownership.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-03-31
- Problem: The first V3 template pass documented visible-role wrappers and gateway examples that the generic template did not actually ship.
- Root cause: The design work moved faster than the reusable runtime skeleton, so the docs started describing a target setup that still depended on deployment-specific files.
- New rule: When a setup guide or example registry names a role wrapper, prompt, or service file, the template must either ship that artifact or mark it explicitly as deployment-local. Do not leave documented default paths pointing at missing files.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-01
- Problem: The first live Neo wrapper test failed with `JSONDecodeError` even though the underlying `openclaw agent --agent neo --json` call was healthy.
- Root cause: The shell wrapper tried to pipe the JSON into `python3 - <<'PY'`, but the heredoc consumed `stdin`, so the piped JSON never reached `json.load(sys.stdin)`.
- New rule: When parsing piped command output in shell, use `python3 -c '...'` or a temporary file. Do not combine a heredoc-fed Python script with a pipe when the pipe is supposed to provide runtime input.
- Where it was recorded: `.agents/scripts/run_openai_oauth_host_runtime.sh`

- Date: 2026-04-01
- Problem: The template still looked like it had multiple equally current Zulip runtimes because the old split-bridge service units lived beside the V3 gateway service in the main `systemd/` folder.
- Root cause: Legacy fallback material was preserved, but not isolated strongly enough from the default path.
- New rule: Keep fallback bridge configs physically separated under a `legacy/` subtree whenever the repo has a newer default system. Do not leave old service files at the same top-level path as the recommended runtime.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: A real live pipeline test woke Niaobe immediately from the user's initial `@AgentSmith ... @Niaobe ... @Architect ...` message, which caused the gateway to reject Smith's handoff with `that agent is already working on this thread`.
- Root cause: The V3 mention parser treated every explicit `@**Agent**` mention in a human stream message as an invocation target, instead of treating the initial addressed agent as the sole first responder.
- New rule: For human messages in shared Zulip threads, only the first explicit `@**Agent**` mention should trigger a visible run. Other mentions in that same message are references until a visible handoff activates them.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: Live Oracle and other visible roles could replay stale local OpenClaw content from earlier ad hoc runs, even when the current Zulip thread had completely different context.
- Root cause: The live launchers relied on OpenClaw's default local session reuse because no explicit session id was passed per visible role/thread.
- New rule: All visible Zulip-driven OpenClaw runs need explicit session ids, and team-internal manager/planner/coder/tester stages need their own derived session ids as well. Never assume the default local session is safe for multi-threaded visible agent work.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: Morpheus summaries were claiming `Oracle validation passed` even when only the internal tester had run, which let Niaobe skip the visible Oracle phase and close too early.
- Root cause: The software-team synthesis prompts and wording still blurred the line between the internal tester and the visible Oracle role.
- New rule: Internal tester output must be labeled as internal tester validation only, and any true Oracle approval must come from the visible Oracle role in-thread before Niaobe closes the phase.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: After deleting the old bridge directories from the template, the repo safety script still tried to inspect those removed paths and failed the cleanup validation.
- Root cause: The safety script had drifted with the older template layout and still encoded checks for the deleted legacy bridge directories.
- New rule: When a cleanup removes a whole supported path from the template, update the validation scripts in the same change so they only check the remaining current layout.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-13
- Problem: The first test pass for the new runtime adapter assumed `pytest` would be present, but the repo environment did not have it installed.
- Root cause: The new tests were initially written to the most convenient framework instead of matching the actual current repo environment, which has no committed Python test bootstrap yet.
- New rule: Before introducing a test framework dependency into this repo, verify it exists in the current environment or commit the bootstrap that provides it. When in doubt, prefer stdlib `unittest` for infrastructure-level coverage.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-13
- Problem: The first built-in local Ollama runner implementation used the `ollama run` CLI directly and assumed the stdout payload would be clean JSON.
- Root cause: In this environment, the Ollama CLI injects terminal-edit control sequences into stdout even when output is captured, which corrupted structured parsing for the prompt-aware runtime path.
- New rule: Use the local Ollama HTTP API as the default transport for machine-consumed prompt execution. Keep the CLI path only as an explicit fallback or test transport, and harden any parser against stray terminal control sequences.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-13
- Problem: The OpenClaw CLI `--json` mode still prints extra log lines around the JSON payload for some commands such as `agents add`.
- Root cause: The CLI emits operational status lines and auth-profile sync notices to stdout even in `--json` mode, so treating stdout as a pure JSON document is unsafe.
- New rule: For OpenClaw CLI integration, parse the first valid JSON object or array from stdout instead of assuming the whole stream is clean JSON.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-13
- Problem: The first git-backed recovery validator trimmed leading spaces from `git status --porcelain` output and then treated the persisted `is_consistent = false` flag as permanently unrecoverable.
- Root cause: The helper used `stdout.strip()`, which removed the leading status-space that porcelain output relies on, and the validator appended `workspace_marked_inconsistent` before reevaluating the current workspace state.
- New rule: Preserve leading spaces when parsing git porcelain output, and treat the persisted inconsistency flag as advisory state that can be cleared by a clean revalidation.
- Where it was recorded: `openclaw_agents/scheduler/workspace_validator.py`

- Date: 2026-04-13
- Problem: The first live software smoke through the `openclaw_workspace` executor stalled for minutes even though the gateway, scheduler, and visible worker path were already healthy.
- Root cause: The local OpenClaw workspace-agent path can block on its own session locking and model-timeout behavior under the current `openclaw-gateway` runtime. A trivial direct probe of the provisioned workspace agent also timed out, and the embedded fallback showed repeated session-lock and model-timeout failures rather than a control-plane bug.
- New rule: Treat the workspace-backed OpenClaw executor as a separate runtime dependency that needs its own live smoke before trusting it in deployment. Keep its command timeouts bounded, and do not interpret a healthy gateway or builtin-worker smoke as proof that the OpenClaw software path is healthy.
- Where it was recorded: `openclaw_agents/runtime/worker_config.yaml` and the live deployment notes in `.agents/memory/changelog.md`

- Date: 2026-04-13
- Problem: The first clean user-service cutover failed even though the env files and code were correct.
- Root cause: The committed systemd unit templates used shell arrays and `$...` variable expansions inside `ExecStart` and `ExecStartPre`, but systemd expands `$` itself unless it is escaped. That turned `cmd[@]` into an invalid environment expansion before `bash` ever ran.
- New rule: When a systemd unit shells out through `bash -lc`, escape every shell-side `$` as `$$` in the unit file. Keep environment-driven optional flags such as the Zulip `--insecure` path explicit in the unit or env file instead of depending on a hidden transient-service command line.
- Where it was recorded: `openclaw_agents/operations/systemd/zulip-gateway.service`, `openclaw_agents/operations/systemd/openclaw-worker-supervisor.service`, and `openclaw_agents/operations/systemd/openclaw-worker@.service`

- Date: 2026-04-14
- Problem: The first live retry recovery focused on the OpenClaw implementer timeout and model drift, but the project still remained stuck even after a later Morpheus retry succeeded.
- Root cause: The store-layer “active child” query treated `BLOCKED` tasks as still active, so Niaobe kept waiting on an older blocked software child instead of advancing from the newer successful Morpheus retry to Oracle verification.
- New rule: When orchestration code asks for non-terminal child tasks, filter to `PENDING` and `RUNNING` only. A blocked child is historical context, not an active dependency.
- Where it was recorded: `openclaw_agents/database/store.py` and `tests/test_builtin_loops.py`

- Date: 2026-04-14
- Problem: The live control plane could accumulate historical `task_attempts` and `agent_runs` that still showed `RUNNING` even though `finished_at` or `ended_at` was already populated, which made stale work look active and obscured the true current queue state.
- Root cause: Some orchestration-side runs finish their local attempt or agent-run record when they hand off work, but the terminal status is not always normalized away from `RUNNING` unless a later path updates it.
- New rule: Any runtime or orchestration path that sets `finished_at` or `ended_at` must also persist a terminal `status` / `result_status` immediately. Operational queries for “open” activity should not rely on timestamps to infer closure.
- Where it was recorded: Live cleanup on `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/db/control_plane.sqlite3`; a code fix is still needed in the control-plane runtime path.

- Date: 2026-04-14
- Problem: The project workspaces exposed to operators did not actually reflect the running project loop, even though the templates and specs said `PROJECT.md` and `management/` were the human-readable project source of truth.
- Root cause: The original implementation provisioned template files once, then advanced the project only through DB rows, artifacts, and Zulip messages. There was no sync layer to keep workspace management docs aligned with accepted task and artifact state.
- New rule: Any project with a `workspace_ref` must have a maintained management projection. Provisioning, dispatch, accepted responses, and control-event recording should all refresh the workspace management docs so operators can follow the project from the workspace itself.
- Where it was recorded: `openclaw_agents/scheduler/management_writer.py`, `openclaw_agents/runtime/dispatcher.py`, `openclaw_agents/scheduler/workspace_provisioner.py`, `openclaw_agents/scheduler/control_commands.py`

- Date: 2026-04-14
- Problem: The first live rollout of the management writer crashed when it hit stale historical projects whose artifact refs pointed at files that no longer existed on disk.
- Root cause: `WorkspaceManagementWriter` treated every artifact record as readable and attempted to parse missing workspace files during control-command sync.
- New rule: Management projection must be resilient to historical bad state. Missing artifact files should be skipped during projection instead of crashing live control-plane actions.
- Where it was recorded: `openclaw_agents/scheduler/management_writer.py`

- Date: 2026-04-14
- Problem: Fresh project workspaces still contain extra agent/persona markdown files such as `BOOTSTRAP.md`, `SOUL.md`, `IDENTITY.md`, `HEARTBEAT.md`, `TOOLS.md`, `USER.md`, and a second `AGENTS.md`, which makes the project root look like an agent bootstrap repo instead of a clean project workspace.
- Root cause: Those files are not coming from the committed `project_workspace` template; they are leaking in from the underlying OpenClaw workspace bootstrap/persona layer used by the real workspace executor.
- New rule: Project workspaces should expose only project-facing artifacts and management files by default. Agent/bootstrap/persona files must be suppressed, relocated under hidden runtime state, or removed from the project root.
- Where it was recorded: Live workspace `/home/alik/workspace/claw_software_workspace/projects/P_live_management_sync`

- Date: 2026-04-14
- Problem: Moving OpenClaw backend agent state into a hidden `--agent-dir` under `.openclaw/backend_agents/...` did not eliminate all root-level persona/bootstrap context from fresh live project runs.
- Root cause: The blocked live project `P_e59706da53834907bd2b861287bbefe3` was provisioned with the new hidden `agentDir`, but the OpenClaw runtime still injected root-level files such as `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, and `BOOTSTRAP.md` into the system prompt. That means there is a second leakage path tied to workspace bootstrap behavior, not only agent state placement.
- New rule: Treat hidden `agentDir` isolation as necessary but not sufficient. The real boundary fix is to stop using the visible project root as the OpenClaw `--workspace`; use a hidden project-local OpenClaw workspace under `.agents/openclaw/workspace` and expose the visible project through a symlink inside that hidden workspace instead.
- Where it was recorded: Blocked live project `/home/alik/workspace/claw_software_workspace/projects/P_e59706da53834907bd2b861287bbefe3`

- Date: 2026-04-14
- Problem: The first Phase 2 store split left project-local `projects` rows stale and broke shared lease foreign keys.
- Root cause: `projects` updates were not mirrored into each project's local DB because the routed store did not resolve `project_id` for `UPDATE projects ... WHERE project_id = ?`, and `LeaseManager` still created control-plane `agent_runs` through the routed project-local path even though shared `orchestrator_leases` keeps a foreign key to shared `agent_runs`.
- New rule: Treat `projects` as a dual-written scheduler summary row and mirror every project update into the project-local DB once `workspace_ref` exists. Shared control-plane orchestrator runs used only to satisfy lease ownership must be inserted through a shared DB transaction, and project-active run queries should merge those shared control-plane rows with project-local runtime rows when needed.
- Where it was recorded: `openclaw_agents/database/store.py`, `openclaw_agents/scheduler/lease_manager.py`

- Date: 2026-04-14
- Problem: After the Phase 3 migration work, the live stack looked like `Niaobe` was stuck even though there was no active workflow.
- Root cause: The repo-specific gateway and worker supervisor had not been restarted after the migration/purge work, so no live processes were available to consume new work even though the database was otherwise clean.
- New rule: Treat migration or purge completion as incomplete until `zulip-gateway.service` and `openclaw-worker-supervisor.service` are restarted and the corresponding repo-specific processes are verified in `ps`.
- Where it was recorded: live rollout of the Phase 3 migration on 2026-04-14

- Date: 2026-04-14
- Problem: A full mechanical rename in code/config was not sufficient to keep the live stack running on the first rollout.
- Root cause: The live Zulip credential filename still used the previous orchestrator spelling, so removing compatibility immediately would have broken bot loading even though the canonical agent id had already changed.
- New rule: For runtime identity corrections, rename the live operational credential files and then remove the temporary compatibility bridge in the code; do not leave the bridge in place after the operational rename is complete.
- Where it was recorded: `openclaw_agents/communication/zulip_gateway_service.py`

- Date: 2026-04-14
- Problem: The first orchestrator spelling-correction rollout still left the live gateway broken after restart.
- Root cause: Existing SQLite databases still carried legacy `niobe` check constraints and row values, especially in `orchestrator_leases`, so startup lease seeding crashed before the gateway could even load bots.
- New rule: Treat runtime identity renames as a data-migration problem as well as a code/config rename; verify service startup against existing live databases before considering the rollout complete.
- Where it was recorded: `openclaw_agents/database/store.py`, `tests/test_store_migrations.py`
