# Decisions Memory

## Entries

- Codex is the only enabled execution backend. OpenCode remains implemented and historically readable but cannot start or resume model execution. Live drafts must use canonical task handoffs, and Codex workers receive only an explicit runtime environment allowlist.
- CodexTeam is a local specification-driven workflow toolkit, not an application server, controller, board, HTTP API, or MCP service.
- Historical archives are obsolete and are never merged into the current system.
- Generated cold-start controls default to `/home/alik/workspace/codexspace/projects`; control-only layout is the initializer default and product source is registered separately.
- Task IDs use canonical uppercase form; the default initialized sequence is `T001` requirements, `T002` architecture, `T003` development, `T004` integration testing, and `T005` review. `T006` documentation reconciliation is optional.
- Handoff and result current shapes are machine-readable and enforced by Python.
- Superseded: OpenCode `qwen38-27b-context` was the default before OpenCode execution was disabled; existing records retain that historical pin.
- Worker completion is a claim. Only independent verification and leader-owned closure complete a task.
- Process commands use structured argument arrays; raw shell evaluation is prohibited.
- Each logical attempt owns a private persistent SQLite/session state and exact thread ID. Local profiles use a private Codex home. Authenticated OpenAI profiles reuse the source Codex home so credentials are not copied into project runtime; resume still replays model, provider, catalog, reasoning effort, and verbosity.
- Draft, feedback, and final are conversation phases, not separate attempts. Only intentional capability/ownership transfer, irrecoverable session loss, material scope change, or explicit abandonment creates a new attempt.
- Role defaults are routing hints. Evidence of repeated task-specific capability failure justifies a recorded profile transfer without involving the operator.
- The shared brief is a one-page orientation layer and must be synchronized by the Project Lead after every closure; canonical close-loop state alone cannot update project-specific milestone prose.
- `gpt54-mini` is an installed and verified cloud candidate, not yet the repository default. The 2026-07-16 six-task canary completed with one attempt per task and no capability transfer; operator choice still governs any default-routing change.
- Small coherent projects use a proportional seven-identity baseline: Project Lead, Architect, one functional Developer owning the Development Gate, an independent Test Engineer using the wire-compatible tester role and owning the Integration Gate, Reviewer, optional Documenter, and boundary-only Local Git Steward. Add the optional UX Designer only for new or materially redesigned interfaces, and the optional Feature Planner only after architecture acceptance when implementation is materially multi-part. The controlled Fibonacci canary remains a historical five-role compatibility workflow.
- The controlled Fibonacci E2E uses medium reasoning, a 300-second per-turn timeout, a 1,800-second reported budget, no automatic retry or profile transfer, and exact same-session recovery after an observable failure. Its historical Qwen selection does not override the current Muse default; `gpt54-mini` is selected explicitly for that canary.
- `/home/alik/workspace/agent_template/codexteam` is the guaranteed cold-start base folder. The root Codex session is the Project Lead, controls are initialized beneath `/home/alik/workspace/codexspace/projects`, and root `AGENTS.md` is the mandatory low-token phase router.
- A new-project request follows separate approvals for proposal, initialization, planning, and execution. Initializer task files are scaffolding until the Project Lead replaces generic wording with project-specific responsible-AI handoffs and the operator authorizes execution.
- Cold-start context uses progressive disclosure: the first proposal relies on root `AGENTS.md`; `.agents/LEAD_BOOT.md` is read before initialization; detailed project-init, planning, orchestration, verification, recovery, and delivery guidance loads only for its active phase.
- Generated cold-start controls use `/home/alik/workspace/codexspace/projects`; the former in-toolkit `./projects` default is obsolete.
- A clean Fibonacci-class cold-start canary has four independent verdict dimensions: lifecycle, product, evidence integrity, and proportional performance. Canonical delivery alone cannot pass the canary.
- The cold-start performance target is at most 30 minutes, 12 worker turns, one correction round per role, one million uncached lead-input tokens, and 50,000 lead-output tokens when usage is available. Exceeding a target must be reported rather than hidden by eventual delivery.
- Stable lead-authored feedback lives at `<project>/.codexteam/lead-prompt-<task>-<attempt>.md`; the Project Lead reuses the exact path across feedback and finalization.
- CodexTeam role-policy current is the single source for nine identities: Architect, Feature Planner (`feature_planner`), UX Designer (`ux_designer`), Developer, Test Engineer (`tester` protocol role), Reviewer, Documenter, Local Git Steward (`git_steward`), and Leader. Project `AGENTS.md` is common guidance; the launcher injects one role policy and pins the complete role and skill instruction bundle for the logical attempt.
- Feature Planner is an optional post-architecture advisor for materially multi-part implementation. It uses the default `qwen38-27b-context` spawned profile unless an explicit supported override is selected, writes only advisory artifacts under `results/`, and never implements, assigns canonical task IDs, changes lifecycle state, spawns workers, or approves its own plan.
- UX Designer owns implementation-ready interface design, disposable design prototypes, and focused design QA. It never owns production code, product acceptance, or canonical lifecycle state, and it is not part of the default non-UI task scaffold.
- The persistent external `spawn-subagent.sh` launcher remains authoritative. Namespaced native Codex agent files are deterministic optional projections installed only by explicit operator action.
- Role change patterns and evidence types are mechanically checked after each turn and at final result validation. Task handoff paths may be narrower and remain the review authority.
- Developers own algorithm/unit and smoke tests plus a fast Development Gate. Test Engineers may engineer and modify scoped integration/regression tests and controlled expectations but never production source; every changed expectation cites approved truth or a confirmed test defect. The CI-equivalent Integration Gate invokes the Development Gate first and is reused by external CI and leader closure.
- Test Engineer product defects found against a Developer draft return to the same Developer session before finalization. After correction, both gates rerun against the final source revision.
- Architects own requirement-traceable code, component, dependency, data-flow, repository, security, and test architecture in `ARCHITECTURE.md` plus material ADRs. They do not implement source or approve their own proposal.
- `management/TEST_GATES.toml` is the machine-readable gate authority. Commands are argument arrays; Integration always includes Development; passing records pin the configured verification-path manifest and digest.
- New projects are exact standalone Git repositories by default. Initialization creates no commit and invents no Git identity.
- Local Git Steward runs only at a Project Lead-authorized important-task or milestone boundary. The model is read-only; a deterministic executor validates an exact plan and authorization, re-verifies the candidate tree, stages literal approved paths, and creates one local commit.
- Local Git Steward has no remote authority. Push, fetch, merge, rebase, tag, release, publication, and remote PR creation remain human actions.
- Run Guard is opt-in per worker turn. It interrupts three consecutive identical
  failed command results, a command result over 32 KiB, or broad repository discovery
  after a successful `codexteam-context` call. It preserves full private diagnostics
  and the exact-thread resume path, and is not a token, time, tool-count, or general
  retry limit.
- Lead milestone rotation uses one ignored compact checkpoint with canonical
  references. Lead, worker, and combined usage remain distinct metrics scopes.
- Gate execution ownership is explicit in `TEST_GATES.toml`. Workers cannot run a
  `lead_host` gate; accepted task-attempt evidence is a content-addressed immutable
  snapshot, while rolling gate files remain current-state views.
- The launcher preserves each raw Lead prompt and pins a role-specific final result
  schema. Result identity, UTC production time, and Git Steward's empty change set are
  launcher-owned fields.
- Lead task metrics checkpoint cumulative rollout counters at each canonical task
  transition instead of relying only on the final Stop hook. Cross-task binds preserve
  the previous task when possible, explicit reset is required to discard stale state,
  and delivered-project cleanup is exact-project and canonical-state gated.
- A terminal Local Git Steward task may produce tracked lifecycle changes after its
  milestone commit. Those changes require a separately authorized metadata-only
  closure commit; the committed HEAD must not be described as fully delivered while
  its lifecycle files still show the Steward task active.
- Role-policy current may pin a non-empty `mcp_tools` subset for an allowed server.
  Developer, Test Engineer, Reviewer, and Git Steward receive bounded
  `codexteam-context` subsets on future attempts; existing attempts keep their pinned
  server and tool policy. Context tools orient discovery, while exact source reads,
  test gates, result checks, and deterministic Git verification remain authoritative.
- Developer context is considered heavy when it requires several upstream artifacts,
  repository-wide symbol discovery, dependency or gate resolution, or shared-worktree
  triage. Heavy discovery starts with one routed context call; exact headings and
  symbols may still use a smaller direct read. Developers receive
  `get_change_summary` for bounded dirty-worktree inspection, and pre-edit discovery
  uses a soft six-call checkpoint rather than a hard task limit.
- New non-Leader attempts using `codexteam-context` are bound by the launcher to the
  exact direct-child workspace project. Worker schemas omit `project`; Lead remains
  unbound for multi-project orchestration, and legacy attempts remain unbound. Measure
  three tasks before considering any separate hard discovery-interruption behavior.
- Ordinary Developer attempts use one discovery protocol and one `CONTEXT GAP`
  checkpoint. The Task Capsule checkpoint is isolated in an explicitly injected
  playbook and must not appear in Planned Lane or ordinary attempt guidance.
- Context-heavy handoffs use two to five exact Context Targets. Each target states a
  question, file, narrow locator, and intended implementation use; Developer work also
  names a source and focused-test target unless it creates them. Broad Context reading
  lists, directory globs, and whole result trees are not bounded handoffs.
## 2026-08-20 - Qwen 3.8 is the default OpenCode profile

Superseded on 2026-08-21: OpenCode execution is disabled. The prior
`qwen38-27b-context` routing remains historical evidence only. Existing attempts
retain their pinned profile. Small work defaults to
600 seconds; complex work defaults to 1200 seconds and uses same-session staged
returns before finalization.
