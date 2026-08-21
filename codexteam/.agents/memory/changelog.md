# Changelog Memory

## Entries

- 2026-08-21: Disabled OpenCode draft and feedback execution while preserving its implementation, curated registry entries, historical attempts, and provider-free finalization path. New project templates now use `codex/qwen38-27b`; live drafts require canonical `management/tasks/T*.md` handoffs, and Codex workers receive an explicit environment allowlist instead of the full launcher environment.
- 2026-08-21: Added explicit low/medium/high reasoning and artifact-backed tool-result context projection for new `opencode/qwen38-27b-context` attempts. One source-digest-pinned attempt-private plugin archives full outputs with mode `0600`, records byte/digest provenance, and supplies bounded tool-specific summaries or UTF-8-safe head/tail excerpts only to model-bound history. A matched three-task harness kept strict correctness at 6/6 while reducing prompt tokens 89.2%, model-visible tool bytes 96.4%, and model time 42.7%; a live OpenCode 1.18.20 exact-session canary archived the provider full-output artifact, resumed corrections, and sealed deterministically. The original provider-default profile and existing attempts remain unchanged.
- 2026-08-20: Added optional `opencode/qwen38-27b` for tuned local alias `qwen3.8-27b:latest`. The alias preserves Qwen 3.8's native renderer/parser and published sampling while pinning 262K context; runtime inspection showed 100% GPU residency with q8 KV and flash attention. Disposable OpenCode exact-file, same-session correction, artifact JSON, native tool-call, and clean-stop canaries passed. A real Developer recovery completed T321 and corrected a Lead-found Parent-trail defect, but its first broad turn timed out after implementation; a T322 Test Engineer trial then exceeded bounded scope across two long oracle-building turns and produced no project evidence. Keep Qwen 3.8 opt-in; default role routing remains unchanged.
- 2026-08-17: Promoted tuned `opencode/muse-glimmer` (`muse-glimmer:30b`, `num_ctx=131072`, temperature `0.6`, top-k `20`, top-p `0.95`) for implementation-oriented spawned roles after five fresh bounded canaries and a real Developer task passed. Real-project Tester and Reviewer canaries then exceeded bounded scope (125/51 model steps) and timed out, so Qwen remains the default for independent evidence roles and capability transfer.
- 2026-08-07: Added the OpenCode-only `qwen36-27b` alias for tuned local `ollama/qwen3.6-27b:latest` without changing the Codex profile or default backend. A matched three-run deterministic Reviewer comparison held guidance constant: Qwen produced two strict clean passes versus Ornith's zero, with lower median input/output and tool calls. Qwen is the preferred OpenCode Reviewer candidate for further bounded testing, while role manifests and default routing remain unchanged. Qwen then returned `StructuredOutputError` in all three exact-session SDK JSON-schema trials and once with the normal tool-capable agent, so SDK finalization remains disabled.
- 2026-08-06: Added an opt-in OpenCode worker backend for `ornith35b` beside the unchanged default Codex backend. The launcher now pins private OpenCode configuration and sessions, parses JSONL metrics, tracks baseline-derived net changes, and externally validates exact result declarations. OpenCode-only profiling records model-step growth, tool text-output bytes, and labeled local context bytes while preserving prior Codex output shapes. OpenCode 1.18.14 with `ornith:35b` failed the SDK JSON-schema capability gate with `StructuredOutputError`. A three-run Reviewer guidance experiment improved medians with one skill but retained poor draft reliability and a 166K-token outlier, so role defaults, SDK finalization, MCP, LSP, plugins, OS sandbox parity, and any default-backend migration remain unchanged.
- 2026-07-15: Rebuilt the cleaned CodexTeam system as a local workflow toolkit. Added enforced current schemas, shared safe Python tooling, complete template-backed project initialization, strict task/result handling, bounded subagent execution, independently verified close-loop state management, deterministic tests, and current-system documentation.
- 2026-07-15: The Fibonacci Tree CLI end-to-end run exposed ambiguous close-loop result selection when timestamped and worker-named attempt files coexist. Added explicit `--result` selection, regression coverage, and orchestration guidance so failed attempts remain preserved while leaders close only the accepted result.
- 2026-07-15: The same end-to-end run exposed a temporary Codex plugin-cache cleanup race that could replace completed spawn output with `Directory not empty: plugins`. Spawn homes now ignore cleanup-only errors after worker exit, with regression coverage ensuring completed results remain reportable.
- 2026-07-15: Reworked orchestration around persistent per-attempt Codex sessions, exact thread resume, compact role guidance, a one-page team brief, and draft → consolidated feedback → final result conversations. Added private JSONL/message/stderr turn records and deterministic final-result gating.
- 2026-07-15: A fresh six-task Fibonacci Tree CLI E2E run reached DELIVERED with 31 passing tests and six validated results. The run proved same-session correction on T002–T004, schema rejection without result leakage, and intentional result-free capability transfers for evidence review and document editing.
- 2026-07-15: Live resume failures showed that exact thread IDs alone are insufficient when global defaults change. Resume now replays model/provider/catalog/reasoning/verbosity, and completed turns tolerate recovered transient error events. Guidance now requires literal prompt files, direct edits instead of one-off helpers, full-root cleanup after failed editing turns, and final narrative-state synchronization. Repeated Gemma audit/editing failures moved default tool-using review and documentation routing to Qwen while retaining Gemma as an optional secondary perspective.
- 2026-07-16: Added authenticated OpenAI-profile support without copying credentials into project runtime, installed the `gpt54-mini` canary profile, and completed a six-task Fibonacci Tree CLI E2E with one persistent attempt per role and no ownership transfer. The run exposed reserved evidence-path deadlock, assignment-state drift, and result-envelope mistakes. Feedback can now resume past a stray reserved result path, while guidance makes path ownership, UTC/result enums, cloud authentication, and assignment synchronization explicit. Verification passed with 67 toolkit tests, 8 product tests, and six valid final results.
- 2026-07-16: Added a proportional five-role fast lane and a discoverable Bash-controlled Fibonacci Tree CLI E2E canary with dry-run, product-only verification, time budgets, failure preservation, and exact-session recovery instructions. A clean live path delivered five tasks in 10 turns and 926 seconds; its only nonzero post-check was a corrected Bash nullglob false positive. A fresh recovery run then delivered in five persistent attempts and 14 turns, proving same-thread correction of two malformed final envelopes. Finalization now rejects nonexistent declared artifacts before sealing a session, and focused final prompts include complete evidence-object examples. Verification passed with 81 toolkit tests and 5 product tests before the final memory update.
- 2026-07-17: Added a cold-start Project Lead bootstrap for the guaranteed `/home/alik/workspace/agent_template/codexteam` base folder. Root `AGENTS.md` now assigns the lead identity, routes phases by exact guidance path, preserves initialization/planning/execution approval gates, and uses `./projects`. Added `.agents/LEAD_BOOT.md`, corrected root-facing commands, and defined E2E-000 for fresh-lead discovery. Two raw read-only Gemma starts discovered the role without an injected lead prompt; progressive disclosure reduced reported input usage from 32,891 to 8,101 tokens while preserving the correct no-write proposal and approval behavior.
- 2026-07-17: Ran a fresh GPT-led, local-worker Fibonacci cold-start team canary through T001-T005. Team discovery, approval gates, exact project-path continuity, persistent attempts, and nested-sandbox recovery worked, but the clean E2E verdict failed: an untested right-subtree indentation defect survived, Reviewer claims exceeded the content of their named artifact, three scratch files remained, one feedback filename was mistyped, local result envelopes needed repeated corrections, and execution took about 49 minutes/24 persisted worker turns while the lead reported 25.6M input/92K output tokens. Added stable lead-prompt paths, complete result-object examples, concise result inspection, claim-to-artifact review discipline, scratch-free determinism guidance, product/manifest delivery audits, performance targets, and a durable canary report.
- 2026-07-21: Corrected nested local-worker routing after live diagnosis showed that `--trust-parent-sandbox` avoids redundant `bwrap` but cannot restore host Ollama loopback hidden by the parent sandbox. Cold-start guidance now requires a same-surface endpoint preflight, uses trusted-parent mode only when reachable, falls back to approved host-level launching with the normal worker sandbox, treats route changes as material attempt changes, and clarifies that dry runs and global MCP state are not connectivity proof.
- 2026-07-22: Added strict role-policy current manifests for Developer, Tester, Reviewer, Documenter, and Leader; distinct instruction bundles and defaults; per-attempt policy snapshots; role change/evidence enforcement; optional namespaced native Codex agent projections; safe current-project guidance sync; and project-local running/stale status inspection. New initialization includes managed role references, while the persistent external launcher remains authoritative and historical archives remain excluded.
- 2026-07-22: Split testing into a Developer-owned Development Gate for algorithm/unit plus smoke evidence and a Test Engineer-owned Integration Gate for CI-equivalent integration/regression evidence. The tester protocol role now acts as Test Engineer, may modify scoped tests with expectation-integrity justification, cannot modify production or Developer-owned test areas, and returns product defects to the same Developer session before finalization. New projects scaffold both skills, gate configuration, and separate test directories.
- 2026-07-22: Added Architect and Local Git Steward identities, expanding role-policy and result/handoff enums to seven roles. New projects now scaffold T002 architecture, T003 development, T004 integration testing, T005 review, optional T006 documentation, `ARCHITECTURE.md`, ADR storage, a local Git policy, and exact standalone Git initialization. Attempts pin complete role and skill bundles. Shell-free TOML Development/Integration Gates produce freshness-checked records. The deterministic Git executor validates an explicit plan and authorization, re-tests the candidate tree, stages only approved paths, and creates one local commit with no remote operations. The read-only Web UI exposes verified milestone commit records.
- 2026-07-23: Added one post-turn metrics sidecar per Codex process with cumulative and delta tokens, cached and uncached input, tool and failure counts, repeated commands, output byte volume, and redacted previews of the three largest commands. The read-only WebUI now exposes per-turn cycles and the ten most expensive completed drafts; a preview-first backfill covers historical sessions without adding model calls.
- 2026-07-23: Added a guidance-only `PLANNED LANE` pilot for ambiguous, browser-dependent, or cross-contract Developer work. New pilot attempts use one read-only planning checkpoint inside the normal persistent writable session, require explicit Lead acceptance before edits, keep targeted browser smoke in the Development Gate, and leave broad Chromium regression with the Test Engineer. No task, result, launcher, or state schema changed.
- 2026-07-24: Rebuilt the read-only WebUI as a responsive project command center with mutually exclusive activity groups, compact Current Focus, deterministic six-lane Kanban projection, ten-card older-task disclosures, human agent labels, collapsed diagnostics, and System/Light/Dark themes. Milestone IDs are now presentation-only grouping metadata while canonical task IDs lead titles consistently across portfolio focus, Kanban, Task details, and Agent activity. Final verification passed 45 focused WebUI tests and 185 repository tests.
- 2026-07-24: Ran the first measured replacement.1 finalization experiment with Qwen. OpenAI final turns now use the existing output schema while local turns use a compact contract; the launcher normalizes only deterministic result bookkeeping, the E2E report accepts optional lead usage, and Python workers suppress bytecode artifacts. A fresh Qwen canary closed T001 on its first pass and reduced T002 command output from 145,932 to 15,719 bytes, but T002 still timed out while repeatedly rewriting the renderer. The next isolated experiment is smaller project-specific developer tasks, not a longer timeout or added control infrastructure. Repository verification passed 190 tests.
- 2026-07-24: Added a progressively disclosed CodexTeam self-improvement skill for Project Leads after reviewing current self-evolving-agent research. Workers capture evidence without changing healthy active attempts; leads classify the smallest durable response; material candidates require independent verification, representative and negative cases, fixed evaluation criteria, lifecycle status, rollback, and skill-library hygiene. New projects receive the skill, while leader turns do not load it unless the root router or Project Lead trigger selects it.
- 2026-07-27: A Git GUI presentation task changed a shared rename projection and
  omitted its inherited focused contract test, so the independent Integration
  Gate caught the regression after Developer checks passed. Task-breakdown
  guidance now requires shared-helper consumers and inherited contract tests in
  task verification while preserving test ownership; presentation-only changes
  stay at the rendering seam instead of weakening accepted domain projections.
- 2026-07-27: Added an optional Feature Planner role for accepted features that
  need multiple implementation assignments. The planner produces a bounded
  advisory artifact under `results/`; the Project Lead retains plan acceptance,
  canonical task creation, worker spawning, and lifecycle authority. Small
  explicit slices still go directly to one Developer, unresolved structure
  returns to the Architect, and all existing timeout policy remains unchanged.
- 2026-07-29: Added an opt-in Run Guard feasibility pilot. Guarded turns stream
  private JSONL and stderr, interrupt only after three consecutive identical
  failed command results, redact the diagnostic preview, and preserve a captured
  thread for ordinary same-attempt feedback. Normal turns keep the existing
  buffered path, and no result or lifecycle state was added.
- 2026-07-29: Routed existing-project inspection through the registered
  `codexteam-context` read-only MCP tools. Project Lead guidance now selects the
  smallest relevant structured query, avoids duplicate broad shell scans,
  preserves canonical mutation and verification commands, and uses one narrow
  fallback when MCP context is unavailable or insufficient.
- 2026-07-29: Added backward-compatible role MCP allowlists and per-process
  enforcement, plus MCP response-volume and repeated-tool telemetry. Registered
  Playwright MCP 0.0.78 as a disabled-by-default, six-tool Test Engineer
  inspection pilot and moved its artifacts to `/tmp`; a real Git GUI canary
  completed in two calls and 15.9 seconds. Registered GitHub MCP Server current.7.0
  by verified image digest with server-enforced read-only mode and an eight-tool
  host allowlist, but kept it unavailable to roles because the local GitHub
  credential is invalid.
- 2026-07-30: Enabled the authenticated, server-enforced `github-readonly` MCP
  server for new Leader attempts only. Other roles retain their narrow MCP
  boundaries, and remote reads do not replace local workspace or gate evidence.
- 2026-07-30: Required new Lead-created task handoffs to include a concise
  human-facing Type, Summary, and Outcome. The WebUI renders these fields
  explicitly while preserving legacy What/Goal, Objective, and ledger fallbacks
  for older tasks.
- 2026-07-30: Added a local, offline documentation MCP with exactly three
  read-only tools for source discovery, bounded search, and locator reads.
  A separate preview-first indexer deterministically indexes explicit local
  text roots and installed Python-package docstrings into a read-only SQLite
  FTS database. Architect and Developer roles may use it for narrow reference
  lookup; all writes, index refreshes, and verification remain deterministic
  commands outside MCP.
- 2026-07-30: A two-task matched A/B pilot showed that guided `local-docs`
  retrieval reduced tool calls from six to two, latency from 71.1 to 37.1
  seconds, input from 177,975 to 97,276 tokens, and output from 3,817 to 1,453
  tokens while preserving correct Flask and pytest answers. An unguided turn
  ignored the registered MCP, and a guessed source ID caused retries. Server,
  Architect, and Developer guidance now requires one focused search, no guessed
  source IDs, a first limit of at most five, and source discovery only when an
  exact filter is necessary.
- 2026-07-30: A two-task read-only Git GUI replay tested 2–4 KB digest-bound
  task capsules without a new MCP. Capsules reduced tool calls from 18 to 13,
  input from 726,423 to 332,124 tokens, uncached input from 123,799 to 83,292,
  and command output from 351 KB to 108 KB while retaining dependency and test
  completeness; latency improved only 6%. Added an opt-in two-live-task capsule
  pilot and soft checkpoint. Deferred the source-context MCP because capsule-only
  discovery already passed the tool-call threshold and no repeated missing
  source query was proven.
- 2026-07-30: Prepared the two-live-task capsule continuation without adding a
  new schema or metrics tool. Capsules use the private
  `.codexteam/runtime/task-capsules/Txxx.md` path, are SHA-pinned in the
  canonical handoff, and have a three-call Lead authoring budget. Existing Lead
  task metrics and Developer turn sidecars provide combined-cost evidence.
- 2026-07-31: Replaced Stop-only Lead task transitions with immediate,
  exact-session rollout checkpoints. Chained task closures now receive separate
  token baselines, cross-task bind preserves the prior task or requires an
  explicit reset, and delivered-project cleanup removes only exact-project stale
  bindings. Added a metadata-only closure rule for lifecycle files written after
  a Local Git Steward milestone commit.
- 2026-07-31: Added pinned per-server MCP tool subsets to role-policy current and rolled
  bounded `codexteam-context` access to Developer, Test Engineer, Reviewer, and Git
  Steward. The launcher now applies `enabled_tools` on every turn and records allowed
  and effective subsets. Four deterministic Git GUI benchmarks showed 58-77% lower
  tool-schema size, 99.4% less output for repository search, 97.6% less output for
  attempt summaries, and about 60% less output for change summaries; focused gate and
  result commands remain preferable when they are already smaller.
- 2026-07-31: Fixed live `local-docs` provenance after atomic index replacement.
  Every list, search, and read now obtains the current digest from the same read-only
  connection as its content and rejects a replaced symlink or invalid index metadata.
- 2026-07-31: Reviewed completed Git GUI task T191 as the first Developer rollout
  candidate. Its session received the intended context server and three-tool subset
  but made zero MCP calls, then accumulated 7.1 million input tokens across 62 shell
  commands, including several early 19-39 KB discovery reads. Tightened context-heavy
  routing, added question-oriented handoff targets and a soft six-call pre-edit
  checkpoint, stopped redundant guidance searches, and added bounded
  `get_change_summary` access to future Developer attempts. A fresh isolated
  `gpt54-mini` Developer canary selected that tool exactly once with no shell call and
  returned five paths from a 487-change worktree in 696 bytes and 17.3 ms.
- 2026-07-31: Corrected MCP routing after Git GUI T193 guessed an absolute workspace
  as the `project` argument, received one failed context call, and fell back to 31 shell
  commands. New worker attempts now receive a launcher-derived, session-pinned project
  binding and schemas that omit `project`; Lead and legacy attempts remain unbound.
  Hard discovery interruption remains deferred until three bound tasks are measured.
- 2026-07-31: Measured Git GUI T195 as the first bound-routing task. Its project-bound
  `get_task_context` call succeeded without a project argument in 33 ms, but a broad
  Context reading list and missing source/test locators still led to 150 KB of planning
  command output; the Planned Lane agent also used the unrelated capsule checkpoint.
  Removed capsule instructions from the default Developer bundle, isolated them in an
  opt-in playbook, standardized ordinary discovery on `CONTEXT GAP`, and required exact
  question/file/locator/use Context Targets. MCP structured targets remain deferred
  until T196 and T197 are measured.
- 2026-08-03: Added compact Lead milestone checkpoints and separated Lead, worker,
  and combined usage totals. Final turns now pin a role-specific schema, preserve the
  exact Lead prompt, and normalize launcher-owned identity fields. Gate configuration
  now declares worker or host execution, with content-addressed accepted snapshots.
  The opt-in Run Guard also stops a result over 32 KiB and broad discovery after a
  successful context call while preserving full private diagnostics and resumability.
