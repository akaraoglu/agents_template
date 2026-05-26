## 2026-05-22
- For this repository, Python commands should run inside `./env-python`.
  When running repo-local Python scripts, tests, sync tools, or wrappers from the
  repository root, activate `./env-python/bin/activate` first. This is a
  repository-specific execution rule, not a general default for other repos.

## 2026-05-22
- OpenClaw stabilization should use phase canaries before the full Fibonacci E2E rerun.
  The default baseline order is now: `neo_project_create`, `smith_planning`, `smith_niaobe_handoff`, `architect_worker_runtime`, `morpheus_direct_implementation`, `oracle_verification`, then `run_e2e_fibonacci_test`. Phase canaries must stay diagnostic-only, emit structured reports, and surface preflight, delivery, session, and fault-layer evidence before prompting any fix.

## 2026-05-25
- Canary baseline hygiene now requires **fresh, quiescent main sessions**, not just "no sync drift". `run_canary_suite.sh --preflight-only` should fail if any canary agent main session is missing, stale, or still draining. After live prompt sync, rotate affected main sessions, warm them with a minimal READY check, and only trust phase canaries once preflight reports `sync_drift=no` and `already_quiescent` across the target agents.

## 2026-05-22
- For this project, fix proposals must be approved before implementation.
  When investigating a failure, the default flow is: run the canary or reproduction, identify the failing boundary, prepare a fix plan, and ask the user for explicit permission before changing code, prompts, configs, or live runtime files. Do not implement the fix immediately after diagnosis unless the user explicitly says to proceed.

## 2026-05-22
- OpenClaw workflow stabilization should use a fixed E2E canary loop before any broader redesign or prompt tweaking.
  The default loop is: run `AgenticTeam/scripts/run_e2e_fibonacci_test.sh`, capture the report, classify the fault by layer (helper/guard, prompt contract, policy/allowlist, or runtime validator/state-machine), make the smallest relevant fix in that layer, and rerun the same canary. The Fibonacci canary is the baseline reproduction surface for AgenticTeam work, while prompt wording remains secondary to helper support, explicit workflow contracts, and tool/allowlist correctness.

## 2026-05-20
- Shared project control remains in `STATE.md` for now, but ownership is now explicit and guarded.
  The incremental hardening sprint keeps the existing markdown state file instead of introducing a new control-plane store, but `STATE.md` is now treated as guarded shared control rather than a free-form note. Smith records only the pre-ack handoff state, Niaobe becomes the sole control owner on its first acknowledged transition, and `write_state.sh` rejects stale writes or worker-authored control updates through actor/owner checks.

## 2026-05-20
- `ack_handoff.sh` accepts the shorthand form that omits an explicit phase and defaults it to `HANDOFF`.
  A fresh real-path smoke showed that Niaobe often calls `ack_handoff.sh niaobe <project_id> RECEIVED "<note>"` instead of the longer `<phase> RECEIVED "<note>"` shape. The helper now treats that shorthand as a valid `HANDOFF` receipt so the control path remains deterministic without depending on a fragile prompt argument order.

## 2026-05-20
- For the stabilization pass, Smith and Oracle must prioritize the core completion chain over optional narrative/status behavior.
  The synthetic canary showed two live empty-turn failure modes: Smith stopping after a Mattermost post before completing the Niaobe handoff, and Oracle stopping after a passing `project_exec.sh` result before writing `VALIDATION.md`. The canonical prompts now treat `handoff.sh -> sessions_send -> write_state.sh` as Smith's primary sequence and treat `project_exec.sh` as only evidence, not Oracle task completion.

## 2026-05-19
- Smith's completion contract is `STATE.md` plus `VALIDATION.md`, not a new `DONE.md` write.
  During the rooted-contract migration, Smith was intentionally kept off `project_write.sh` to avoid broadening its write authority just to generate a summary file. The canonical completion signal is now: Niaobe reports `DONE`, Smith verifies `VALIDATION.md`, and Smith moves `STATE.md` to `DONE` before reporting the final result to Neo.

## 2026-05-19
- Canonical prompt compatibility is now validated during the live sync path.
  `AgenticTeam/scripts/sync_live_openclaw.py` now validates that workspace docs and agentDir prompts reference the same helper scripts, that allowlist agents only reference allowlisted helper scripts, and that legacy path-contract tokens are absent from the canonical prompt set. The check runs by default and can be bypassed only with the explicit `--skip-compat-check` escape hatch during stabilization.

## 2026-05-19
- The dedicated live `project_write` contract is `project_write.sh --source-file <workspace_file>`.
  The stabilization sprint replaces role-specific write wrappers as the primary contract with one generic helper that reads content from a validated file under `/home/alik/workspace/clawspace/workspaces/` and atomically writes into the canonical project root. Writer-agent prompts should standardize on that one helper shape, while legacy stdin support remains temporary compatibility only.

## 2026-05-19
- Live OpenClaw config must be merged from AgenticTeam-managed keys, not file-copied.
  The live `~/.openclaw/openclaw.json` contains user/runtime state and secrets that should survive stabilization changes. AgenticTeam now owns only the managed control-plane keys through a structured overlay, while the sync path preserves unmanaged live keys and treats `exec-approvals.json` as an additive baseline merge instead of an overwrite.

## 2026-05-19
- The live OpenClaw sync path is manifest-driven and dry-run first.
  `AgenticTeam/config/live_openclaw_sync_manifest.json` is now the machine-readable inventory for canonical source files, live destinations, deprecated source paths, and managed/unmanaged agentDir content. The sync tool should default to dry-run and only write on explicit `--apply`, so control-plane drift is visible before it is deployed.

## 2026-05-19
- AgenticTeam is the canonical source for the live OpenClaw control plane during stabilization.
  For the stabilization sprint, `AgenticTeam/` owns live agent prompts/docs and live tool-policy/config artifacts. The live OpenClaw files should be synced/generated from `AgenticTeam/`, and direct edits in the consumed live files should be treated as generated-output drift rather than the normal source of truth.

## 2026-05-19
- Live project writes should converge on one dedicated runtime `project_write` contract.
  The workspace-draft import helpers were useful for proving that stdin-over-`exec` was the wrong interface, but they are not the desired steady-state contract. The stabilization sprint should standardize on one dedicated runtime `project_write` tool shape and align prompts, allowlists, and canary checks to that single write contract.

## 2026-05-19
- Project file content should not travel through OpenClaw exec stdin.
  The live runtime gives agents one shell-command string for `exec`, so stdin-only project file helpers force models toward heredocs or pipes that the allowlist reject. The workspace-draft import helper was a valid transitional workaround to prove the failure mode, but it is now superseded as the target steady-state by the dedicated runtime `project_write` decision above.

## 2026-05-19
- Fresh live sessions are required after prompt/approval contract changes.
  For the live clawspace, patching `AGENTS.md`, `TOOLS.md`, or `exec-approvals.json` is not enough by itself when long-lived OpenClaw session files already exist. Architect, Niaobe, and Morpheus can continue replaying stale pre-migration behavior until their persisted session files are archived and new main sessions are created.

## 2026-05-19
- Rooted project helpers are now the live first-class path boundary.
  The initial live rooted-tool surface is `project_read.sh`, `project_write.sh`, `project_mkdir.sh`, and `project_exec.sh`, all keyed by `project_id` plus relative path/command context and backed by canonical `project_root` resolution. Architect, Morpheus, and Oracle docs were updated to prefer these helpers over raw shell file creation and absolute project paths, while `verify_artifact.sh` remains the parent-side verification gate for progress/DONE claims.

## 2026-05-19
- Prefer project-scoped relative-path tools before full sandboxing.
  The near-term runtime direction is to build project-rooted file and exec APIs first, because they directly address the current allowlist, path-drift, and false-success problems with less infrastructure work. Full per-project sandboxing remains the desired phase-2 isolation model and should be designed on top of the project-scoped API layer rather than replacing it.

## 2026-05-19
- All live agents should adopt the rooted tool surface, but with role-scoped authority.
  Every agent may use project resolution plus rooted read/list/exists operations. Coordinator roles (Neo, Smith, Niaobe, Morpheus main) should stay mostly read/verify oriented, while Architect, Planner, Implementer, Tester, and Oracle get only the rooted write/exec capabilities required by their roles. The sprint will migrate prompts/config to this model before sandboxing work begins.

## 2026-05-18
- New project initialization now creates `src/` instead of `implementation/`.
  This keeps newly created clawspace projects aligned with the Morpheus team workflow and the detailed design examples that already assume source files live under `src/`.

## 2026-05-18
- The live clawspace failure policy now starts with shared helpers, not per-agent prose.
  A first shared execution-outcome slice exists in `clawspace/bin/`: `outcome_schema.py` defines the canonical `OK|BLOCKED|FAILED` schema, `verify_artifact.sh` performs helper-based artifact verification with semantic assertions, and `write_state.sh` performs locked `STATE.md` updates with immediate semantic verification. Niaobe and Morpheus were updated to call these helpers instead of relying on raw prompt-authored recovery logic.

## 2026-05-18
- Morpheus is an orchestrator-only BUILD coordinator in the live chain.
  The main Morpheus session resolves `PROJECT_PATH` with `resolve_project.sh`, reads project inputs and child outputs, spawns Planner / Implementer / Tester workers, and reports PROGRESS / DONE / BLOCKED to Niaobe. The main Morpheus session does not install packages, write project files, or run tests directly, and missing dependencies must escalate as explicit BLOCKED outcomes instead of silent failure.

## 2026-05-18
- Live subteam agents must resolve projects through `resolve_project.sh`, not by reconstructing paths from `project_id` or by manually reading `registry.json`.
  Architect and Oracle now treat the resolver output as the only valid `PROJECT_PATH`, and their prompts explicitly forbid string-concatenated project paths. This avoids malformed paths like `/home/alik/wave/...` or `fibonacci/tree-...` that can appear when long-lived sessions guess from stale context.

## 2026-05-18
- All live subteam return messages back to Niaobe must use JSON envelopes keyed by `project_id`.
  Architect must return `phase: "DESIGN"` DONE/BLOCKED envelopes, and Oracle must return `phase: "VERIFY"` PASS/FAIL envelopes. Plain-text return messages and absolute path references are invalid because Niaobe's orchestration contract accepts only JSON `project_id` envelopes.

## 2026-05-18
- Live OpenClaw helper execution must be gated by narrow script allowlists rather than broad shell discovery.
  Smith may use `list_projects.sh`, `resolve_project.sh`, and `handoff.sh` for project watchdog work; Niaobe may use `resolve_project.sh`, `ack_handoff.sh`, and `handoff.sh` for validated receipt and downstream delegation. Both should keep `askFallback: deny`, and heartbeat/docs must not instruct raw `ls`/`find` scans or workspace-local `STATE.md` reads.
- Live OpenClaw web tools remain disabled until their plugin surface is intentionally enabled.
  `tools.alsoAllow` should not contain stale `ollama_web_fetch` or `ollama_web_search` entries when `tools.web.fetch.enabled` and `tools.web.search.enabled` are false.

## 2026-05-15
- Pulse visibility should use a semantic `pulse.emit` runtime tool rather than direct agent-authored Mattermost posts.
  Pulse events are persisted in the project event ledger, queued for async delivery, and mirrored into one shared Mattermost `#projects` channel using one thread per project.
  Mattermost is a projection surface, not the source of truth, and delivery failure must not block agent execution.

## 2026-05-05
- Human-origin workflow routing is agent-declared, not keyword-classified.
  Runtime intake should put human requests into `agent_decides` mode, provide project context when available, and wait for the agent JSON response to declare `intent` and `visibility`.
  Runtime validation should happen after the declaration and should validate hard contracts only: advisory intents cannot carry writes/delegations/project-visible extra messages, handoff intent must carry delegations, workflow/execute/handoff intents require concrete project-bearing action payloads, and invalid combinations are rejected instead of guessed.

## 2026-04-20
- The V0 implementation runs as a standalone bridge and runner inside this repository and treats `/home/alik/workspace/zulip` as an external running Zulip service.
- All three agents use the same local inference backend: `ollama` with model `gemma4:26b`.
- Agent and runner policy has since been simplified: normal project writes do not require a confirmation gate, and Niaobe may proceed from a clear Smith-owned execution package without a separate approval step in the current loop design.

## 2026-04-21
- Prefer prompts, skills, and file conventions over new project-specific Python functions. Add a new project-specific Python helper only when the system cannot work without it.
- Architecture rule: skills own behavior, files own truth, and tiny glue code owns only transport and lookup.
- Simplified runtime contract: the runner owns only transport, strict project lookup, generic file writes under allowed roots, and minimal pending confirmation memory.
- Project resolution rule: use the project topic name in `projects`, or an explicit `project:<slug>` reference in DM. Do not guess from fuzzy text.
- Project mutations are now generic repo-relative writes under `projects/`; workflow meaning stays in prompts, skills, and file conventions rather than Python actions.
- Updated role policy: Neo is a full project/team assistant and may read or write project files when appropriate; Smith remains the project owner for execution handoff; Niaobe remains execution-only.
- Revised role policy:
  Neo is the strategic assistant. Neo owns analysis, redesign, scope shaping, portfolio review, and escalation.
  AgentSmith is the operational assistant. Smith owns authoritative operationalization for execution, including preparing execution-ready tasks and handing them to execution once the package is clear.
  Niaobe is execution-only and owns execution output.
- Revised file ownership:
  Neo writes planning truth such as `PROJECT.md`, `SPEC.md`, and `BACKLOG.md`.
  AgentSmith writes operational execution intent, especially `CURRENT_TASK.md`, and may update operational parts of `STATUS.md`.
  Niaobe writes execution output, especially `RESULT.md`, and execution-status parts of `STATUS.md`.
- Revised escalation policy:
  Neo may escalate a project to Smith, but that escalation is a recommendation or prepared handoff for operationalization, not a direct execution start.
  Only Smith may hand work to Niaobe.
- Revised confirmation policy:
  No confirmation is required for analysis, review, or draft planning work.
  The current loop sprint does not require a separate human-approval gate before Smith hands execution to Niaobe.
  Use confirmation only if the human explicitly asks to review a proposal before writes are applied.
- Handoff policy:
  Neo may escalate to Smith using a visible recommendation or operational handoff message.
  Smith may accept Neo escalations, operationalize them, and hand execution to Niaobe once the execution package is clear.
  Niaobe accepts execution only from Smith-owned handoff context and reports back visibly with DONE or BLOCKED.
- Preferred visible handoff formats:
  `ESCALATION to AgentSmith: project:<slug> | reason: ... | requested action: ...`
  `HANDOFF to Niaobe: project:<slug> | task: ... | scope: ... | expected result: ...`
  `DONE: ...` or `BLOCKED: ...`
- Revised loop implementation direction:
  Build a small generic run engine with autonomous continuation, stream-aware routing, and operator commands.
  Defer generic termination-condition logic for now.
  Do not implement a human-approval gate before Niaobe handoff in this loop sprint.
- Revised low-risk loop plan:
  Phase the work.
  Start with stable transport, minimal run state, and only `/status`, `/stop`, `/pause`, `/resume`.
  Use a minimal loop outcome contract (`continue`, `wait`, `done`, `blocked`, `stopped`) instead of a broad action framework at first.
  Keep run state mechanical and avoid storing project semantics in runtime state.
  Narrow stream-aware routing to active work messages rather than all topic traffic.
- Loop implementation notes:
  The first slice adds mechanical run state, `next_state`, and `/status` `/stop` `/pause` `/resume`.
  Active runs in a stream topic are allowed to continue processing topic messages without repeated mentions.
  The local environment does not currently have the Zulip Python package installed, so transport remains on the existing raw API bridge for now.
- Current loop rule:
  `next_state=continue` is valid only when the turn made concrete progress through file writes or visible follow-up messages.
  The runner should not allow no-op continuation loops that only narrate future intent.
- Current handoff prompt policy:
  Do not require human approval in the prompts or shared handoff guidance before Smith hands work to Niaobe.
- Runtime architecture update:
  The current runner now uses a filesystem-backed queue with separate intake and worker services.
  Zulip intake enqueues run work and updates run-control state; worker execution consumes queued jobs and may re-enqueue autonomous continuation.
  The legacy `runtime/agent_runner.py` entrypoint now delegates to `runtime/runner_service.py`.
- Transport architecture update:
  The current runner now uses a small Zulip runtime plugin and gateway layer instead of direct raw polling logic in intake.
  Queue-expired Zulip events are normalized and recovered through the gateway, while intake consumes normalized message events only.
- Observability and recovery update:
  Worker state is persisted separately from project truth and includes heartbeat, active job, active run, and note fields.
  `/status` should expose run state, queue counts, and worker state together.
  Active queue jobs may be re-queued automatically when worker heartbeat is stale beyond the configured threshold.
- Project-thread routing rule:
  All project-visible Zulip coordination belongs in stream `projects` using topic `<project-slug>`.
  When Neo or AgentSmith starts a new project, they should create that visible project thread with the first stream message there and keep subsequent project-visible steps in that topic.
- Delegation runtime rule:
  Real agent-to-agent transfer should use a structured runtime delegation contract rather than prose-only handoff text.
  The model now uses `delegations` for delivery and `handoff_status` for acceptance or completion state.
  The runtime persists a tiny handoff record, posts the visible handoff message into stream `projects` topic `<slug>`, creates active stream runs for the sender and receiver, and directly enqueues the receiving agent so the transfer does not depend on mention-based Zulip intake.
- Stream containment rule:
  For project-topic follow-up traffic, active stream runs are no longer enough to make every bot consume later messages.
  Unmentioned project-stream messages should be processed only by the handoff record’s `expected_next_actor`.
  Late unmentioned stream messages that hit a terminal run should be ignored quietly instead of producing visible `I did not continue...` noise in the project topic.
- Repo workspace skill rule:
  This repository may define a local skill that treats all files under `~/workspace/agent_template_new` as in-scope for inspection and task-relevant edits.
  That skill widens working scope inside the repo but does not override sandbox permissions, writable-root limits, or the repo safety boundaries.
- `claw_agents_team` boundary rule:
  The live crew implementation now lives under `claw_agents_team/`.
  `.agents/` remains Codex-only for repo guidance, memory, playbooks, templates, and local Codex skills.
- `claw_agents_team` runtime-data rule:
  Tracked crew code, prompts, docs, and config templates live under `claw_agents_team/`.
  Runtime logs, queue data, run state, handoff records, temp files, and local overrides belong under `claw_agents_team/var/` or ignored local config files and should not be committed.
- `clawspace` data-root rule:
  `claw_agents_team/` remains the code and prompt root.
  Live local data now belongs under `/home/alik/workspace/clawspace/`, split into `projects/` and `system/`.
- External runtime-state rule:
  Local runtime config lives at `/home/alik/workspace/clawspace/system/config/runtime.local.yaml`.
  Operational runtime mechanics such as queue state, worker state, run snapshots, handoff transport state, logs, and temp files live under `/home/alik/workspace/clawspace/system/`.
- Project-history ownership rule:
  Semantic project history should live inside each project folder under `/home/alik/workspace/clawspace/projects/active/<slug>/`, especially in `.openclaw/` and project markdown files.
  Archive is a folder move from `projects/active/<slug>` to `projects/archive/<slug>`.
- Project control-file rule:
  For new-style projects, `PROJECT_STATE.md` replaces separate top-level `STATUS.md`, `PROCESS.md`, and `HANDOFF.md`.
  Legacy projects may continue using `STATUS.md` until intentionally migrated.
- Project-id handoff rule:
  Cross-agent project handoff should use `project_id` as the only legal inter-agent project identifier.
  The registry at `/home/alik/workspace/clawspace/projects/registry.json` is keyed by `project_id` and maps ids to canonical active-project paths plus project metadata.
  Agent-to-agent `sessions_send` messages should use a JSON envelope carrying `project_id`, `from`, `to`, `phase`, and `instructions`.
  Agents should reject handoffs that omit `project_id` or include `project_path`.
  `.current_project.json` files are not part of the control plane and should not be read or written by agents.
- Transitional projects-path rule:
  The repo-local `projects` path is currently a symlink to `/home/alik/workspace/clawspace/projects/active` so existing agent write conventions continue to work while the new external data root is in use.
- Project-local runtime-trace rule:
  Project-scoped run snapshots belong in `projects/active/<slug>/.openclaw/runs/` and project-scoped handoff records belong in `projects/active/<slug>/.openclaw/handoffs/`.
  `system/runtime/runs` and `system/runtime/handoffs` should contain only non-project operational records.
- DM history isolation rule:
  Private conversation keys now include `:project:<slug>` when the incoming DM explicitly names a project.
  This prevents one project's DM history from leaking into another project's later DM thread.
- Global operational-log rule:
  `system/logs/ops.log` and queue `done/failed` files should contain operational metadata only, not project file paths, project summaries, or semantic execution history.
- Versioned template rule:
  Project templates now live under `claw_agents_team/templates/project/` in Git, and the live runtime should read template context from that tracked repo path instead of external `clawspace/system/templates`.
- Strong SDD artifact rule:
  Every new-style project must carry the full base artifact set (`PROJECT.md`, `PROJECT_STATE.md`, `CURRENT_TASK.md`, `RESULT.md`, `management/SPEC.md`, `PLAN.md`, `BACKLOG.md`, `DECISIONS.md`, `MILESTONES.md`, `TEST_REPORT.md`), with executable tasks represented as `management/tasks/Txxx.md`.
- Shared guidance prompt rule:
  Shared crew guidance under `claw_agents_team/shared/*.md` is part of the runtime prompt context, not just human-facing documentation.
- Execution-readiness gate rule:
  AgentSmith -> Niaobe delegation is blocked unless the active task is aligned across `PROJECT_STATE.md`, `CURRENT_TASK.md`, `BACKLOG.md`, `SPEC.md`, `PLAN.md`, and the referenced task file.
- Structured-response repair rule:
  Ollama JSON responses now attempt direct decode, JSON candidate extraction, and one repair pass before the runtime gives up on the turn.
- Execution-authority rule:
  Neo owns whether a project is initialization-only or explicitly authorized to start execution.
  AgentSmith must not start execution from a Neo takeover alone unless Neo or the human explicitly authorizes execution.
- Sequential-task ownership rule:
  AgentSmith reviews Niaobe's completed task, marks it done, and only then creates and promotes the next task.
  Future execution task files should stay minimal and should not be pre-created unless there is a strong reason.
- Policy-driven runtime rule:
  Agent roles, artifact permissions, and delegation authorities should live in tracked policy/config under `claw_agents_team/policy/`, while Python enforcement stays generic and reads that policy instead of hardcoding bot names where practical.
- Delegation-authority rule:
  Delegations should carry explicit authority such as `takeover`, `start_execution`, `task_execution`, or `review_result`, and handoff records should persist that authority for downstream validation.
- Start-execution packaging rule:
  Under `start_execution`, AgentSmith's first execution turn should assemble one complete execution package before any handoff: `CURRENT_TASK.md`, exactly one active task file, and aligned `PROJECT_STATE.md` and `BACKLOG.md`.
- Neo smoke-initialization rule:
  Requests described as `minimal`, `small`, `quick`, or `smoke` still require Neo to create the full base planning artifact set before handing a project to AgentSmith.
  Those modifiers reduce planning depth, not the number of required base files.
- Manager review-closure rule:
  Manager-role review after `review_result` is a lifecycle/report-consistency step, not a technical validation step.
  Runtime validation should allow either zero active tasks when the current task is being closed or exactly one active task only when the manager is promoting the next task in the same turn.
- Executor completion rule:
  Smith should trust executor-reported outputs and should not perform file/work validation beyond lifecycle/report consistency.
  Before an executor reports a task `done`, the executor side must ensure the task outputs exist and `management/TEST_REPORT.md` contains an entry for that completed task.
- Executor signal contract rule:
  Delegated task execution now uses an explicit executor return contract with `event_kind=task_execution` and `event_status` values `accepted`, `completed`, `failed`, or `rejected`.
  `accepted` is non-terminal; only `completed`, `failed`, and `rejected` may wake manager review/progression.
  `failed` and `rejected` must carry a structured reason with `code` and `summary`.
- Runtime handoff identity rule:
  Delegated work now carries generic runtime identity fields `work_id`, `attempt_id`, and `action_type`.
  `work_id` identifies the stable work item, `attempt_id` identifies one concrete attempt of that work, and `action_type` distinguishes flows such as `delegation`, `task_execution`, and `review_result`.
  Review handoffs should stay bound to the same `work_id` and `attempt_id` as the originating execution attempt.
- Stale autonomous task-attempt rule:
  When an autonomous `task_execution` continuation job is still queued for a recipient scope but a newer active task-execution attempt has already been delegated to that same recipient scope, the stale older autonomous job should be ignored instead of continuing under the old `handoff_key`.
- Event-based handoff visibility rule:
  Handoff lifecycle changes should be recorded as project-local JSONL events in `projects/<slug>/.openclaw/events.jsonl` and mirrored into Zulip as deterministic `EVENT <action_type> <STATUS>` messages in `#projects > <slug>`.
  Queue payloads, handoff records, response tracking, and review-result jobs must carry the same generic identity tuple (`work_id`, `attempt_id`, `action_type`, `authority`) so future teams can reuse the protocol without adding agent-specific code.
- Workflow-contract boundary rule:
  `claw_agents_team/workflows/default/workflow_contract.yaml` is the source of truth for role mapping, artifact permissions, delegation authorities, visible event policy, runtime-owned actions, terminal routing, stall policy, and valid status transitions.
  Runtime code should stay generic and enforce the communication contract; agents and workflow Markdown decide project behavior and sequencing.
- Action-lineage rule:
  Handoff records and project events must carry `action_id`, `parent_action_id`, and `workflow_version` so a delegated action, its terminal return, and any manager review can be traced without relying on visible prose or latest-message lookup.
- Runtime-owned review rule:
  `review_result` is runtime-owned. Executors should return terminal task statuses, and the runtime should route the terminal result back to the sender instead of relying on agents to create separate review delegations.
- Manager review-transition rule:
  After a terminal executor return, a manager must choose exactly one transition mode: close or pause with active task `none` and no execution delegation, promote exactly one next `in_progress` task and delegate it, or escalate with no execution delegation.
  A task in `draft` or `ready` state is not executable until it is promoted as the single active `in_progress` task across `PROJECT_STATE.md`, `CURRENT_TASK.md`, `management/BACKLOG.md`, and the task file.
- SQLite ActionStore authority rule:
  Runtime action identity, active-work idempotency, terminal immutability, lifecycle event ordering, and worker leases should be owned by the stdlib `sqlite3` ActionStore at `system/runtime/openclaw_runtime.sqlite3`.
  Project-local handoff JSON and `events.jsonl` files are compatibility/human projections, not the source of truth when the SQLite store is configured.
- Worker-exception terminalization rule:
  If a worker crashes or raises while processing a queued handoff job, the runtime must terminalize the active handoff as `failed` and emit a failed action event instead of leaving it active/delivered for later stall detection.
- Deterministic action-continuation rule:
  Handoff actions must be created in the SQLite ActionStore before visible Zulip handoff prose is sent, and lifecycle events must be persisted before they are mirrored to Zulip.
  Reused active actions must not repost duplicate handoff prose.
  Sender agents must wait after creating or reusing a delegation.
  The first executor `accepted` for a task-execution action queues one runtime-owned continuation.
- Non-terminal acceptance rule:
  `accepted` is an executor ownership/progress signal, not a completion signal.
  Repeated `accepted` for an already accepted task-execution action is redundant and must not wake manager review or terminalize the task as failed.
  Manager review wakes only from executor terminal statuses: `completed`, `failed`, or `rejected`.
- Role-owned correction rule:
  Runtime should route recoverable manager/executor contract feedback to the owning role without fixed retry budgets.
  If a role can solve a detail without changing project goal, scope, authority, or acceptance criteria, it may solve it.
  If a correction requires a major project decision, the responsible role should consult the human.
- Role-policy feedback rule:
  Runtime write-policy enforcement should stay generic and role-based.
  A recoverable role/artifact permission violation should be fed back to the same role within the normal run-loop budget so the agent can revise its output without changing project scope or relying on a hardcoded special case.
  Path-safety failures and exhausted run-loop feedback still remain hard stops.
- Handoff-return communication rule:
  Runtime should not suppress agent-authored `extra_messages` during active handoff returns.
  Deterministic `EVENT ...` messages still represent the contract state, while agents may send project-visible explanation/status messages.
  Delivery order should remain `extra_messages` before any new delegation handoff in the same turn so manager status can appear before the next task handoff.
- Executor terminal-decision guidance rule:
  Executors should choose a terminal task-execution status once evidence is available.
  `completed` requires declared outputs plus a current `management/TEST_REPORT.md` entry.
  `failed` is the correct terminal result when checks, imports, outputs, or report updates do not satisfy the task.
  Returning `failed` with evidence is preferred over indefinite `continue`, repeated `accepted`, or leaving a handoff to stall.
- Handoff feedback routing rule:
  Failed, rejected, or stalled child handoffs should remain terminal and visible, then route a runtime-owned `handoff_feedback` action to the original sender/owner.
  The feedback receiver decides whether to repair locally, delegate a role-correct repair, retry with a new action, or escalate to the human/master.
  `handoff_feedback` itself must not recursively create more feedback if it fails.
- Non-silent active-handoff exhaustion rule:
  If an active handoff exhausts the autonomous run-loop without a terminal `completed`, `failed`, or `rejected` status, the runtime should mark that handoff `stalled`, emit a visible handoff event, and route runtime-owned `handoff_feedback` to the original sender.
  The runtime should not convert active delegated work into a quiet `wait`.
- Tool-result gateway rule:
  Agents may request real tool or command execution through structured `tool_requests`.
  Runtime tool results belong in the project folder under `.openclaw/tool_runs.jsonl`.
  Missing or unavailable tools should be returned as structured `ok=false` results with an `error_type` such as `missing_capability`, and executors should terminalize blocked execution as `failed` instead of silently continuing.
- Write-result feedback rule:
  When an active task-execution handoff applies direct `writes` and does not return a terminal execution status, the runtime should queue a runtime-owned write-result continuation to the same executor.
  The continuation lists the applied files as execution evidence and asks the executor to complete, continue with remaining report/output writes, or fail with a clear reason.
  This is a lower-risk bridge before introducing file-write tools, and direct writes remain supported.
- Critical-thinking response rule:
  For non-trivial design, architecture, workflow, runtime, and implementation requests, Codex should briefly discuss the idea before executing: state the goal, pros, cons/risks, and a recommended path.
  If the user's proposed approach is weaker than another option, say so directly and explain the better option.
  If Codex proposes an approach, also call out its own weaknesses before implementation.
  Keep this lightweight for obvious low-risk edits so critique does not block momentum.
- Manager terminal-closure rule:
  When a manager closes a project after a terminal executor result, `PROJECT_STATE.md` must explicitly move to `Status: CLOSED`, `Stage: completed`, `Active Task ID: none`, and `Next Step: none`.
  `RESULT.md` must not list manager closure as pending work after the closure event is emitted.
- Copied-project intake rule:
  Neo and AgentSmith should not infer copied-project state from chat history alone.
  They should use bounded project-scoped tools (`project.inventory`, `file.tree`, `file.read`, `file.search`, `dependency.detect`, `test.detect`, `code.symbols`, `code.entrypoints`) and then write SDD/task plans from durable project files and tool evidence.
- Tool permission and audit rule:
  Runtime tools should be added behind explicit permission tiers: `read`, `write`, `execute`, and `unsafe`.
  Tool results should keep backward-compatible fields while adding schema version, status, permission context, previews, artifacts, file hashes, file changes, and context-budget metadata.
  Subprocess tools should run with sensitive environment variables filtered and should reject obviously destructive shell commands unless the runtime is explicitly configured for unsafe execution.
- OpenClaw-compatible tool layering rule:
  The crew should reuse OpenClaw service/tool/skill concepts through a local compatibility layer instead of replacing the deterministic runtime.
  Tool access should be configured through registry metadata, groups, profiles, allow lists, deny lists, and permission tiers.
  External OpenClaw-backed tools should enter later through adapters that preserve the local ToolResult envelope and project-local audit trail.
- Capability-first human request rule:
  The runtime should not infer the human's meaning from request wording or block useful work through advisory/workflow modes.
  Agents decide whether to answer, inspect, write, message, hand off, clarify, or refuse.
  Runtime enforcement happens only at concrete side-effect boundaries: tool gateway permission/project checks, write policy, message visibility, delegation authority/readiness, event transitions, and reply-surface routing.
  Writing planning or report artifacts is not execution by itself; a handoff occurs only through a concrete `delegations` payload.
- Best-effort pulse visibility rule:
  Project progress pulses should use `extra_messages` with `delivery_mode=best_effort` and optional `dedupe_key` rather than inline delivery-recovery messaging.
  The runtime should queue those sends as standalone `send_message` jobs so milestone visibility stays fire-and-forget and delivery failures do not reopen or block the agent turn.
- AgenticTeam runtime-owned tail rule:
  For OpenClaw phase workers, prose prompts are not trusted to complete tail protocol steps.
  Smith deterministic planning can route through runtime-owned `autoplan`; Niaobe child results route through `niaobe_run_task.sh child`; Morpheus completion enforces project Required Outputs before import/test; Oracle verification routes through `oracle_run_task.sh verify`.
  Agent models provide judgment/content where needed, while runtime owns import, verification, project execution, report writing, state transitions, and deterministic PASS/DONE/BLOCKED envelopes.
- Morpheus LangGraph pilot rule:
  LangGraph adoption starts as an optional Morpheus-only completion engine behind `MORPHEUS_RUNTIME_ENGINE=langgraph`.
  The graph must not replace OpenClaw envelopes, project helper scripts, Niaobe ownership, or the classic runtime by default.
  Initial graph nodes stay deterministic and do not call the LLM; they only make the existing runtime tail explicit and testable.
- Morpheus LangGraph default rule:
  As of 2026-05-26, Morpheus' wrapper defaults to `MORPHEUS_RUNTIME_ENGINE=langgraph`.
  The classic runtime remains available by explicitly setting `MORPHEUS_RUNTIME_ENGINE=classic`.
  Future Morpheus repair work should extend the graph instead of adding more ad hoc completion branching.
- Morpheus implementation-only repair rule:
  After a LangGraph-owned `test_failed` completion attempt, Morpheus must run the runtime `repair` subcommand before the next `complete`.
  The repair window is implementation-only: tests, docs, and manifests remain locked unless explicitly listed in `ALLOWED_REPAIR_PATHS`.
  The graph should block test weakening and non-allowed artifact changes before re-running verification.
- Morpheus repair validation rule:
  Repair-loop changes should be validated with the dedicated `morpheus_forced_repair` phase canary before broader phase-suite or Fibonacci E2E runs.
  A normal `morpheus_direct_implementation` PASS is not enough repair evidence because the model may pass on the first completion attempt.
