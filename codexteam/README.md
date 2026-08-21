# CodexTeam

CodexTeam is a local workflow toolkit for coordinating bounded AI subagents around a specification-driven software project. It provides project guidance, task handoffs, strict result contracts, local-model spawning, independent verification, and deterministic project-state closure. Codex is the only enabled execution backend; OpenCode implementation and historical records are retained but execution is disabled.

CodexTeam has one project execution system. It preserves the Project Lead and
the draft, feedback, final, gate, review, close-loop, and Git Steward lifecycle.
Codex is the only enabled execution backend. Historical OpenCode profiles remain
in the curated registry for attempt readability, but new draft and feedback
execution is rejected. AgentSpecs provide optional specialization.
No alternate execution system exists.

It is not an application server, controller service, board, HTTP API, or MCP implementation. Historical archives are not source inputs for this system.

## Subagent Instructions

Every worker receives three instruction layers:

1. Project `AGENTS.md` and the selected handoff provide common project rules and task scope.
2. One validated manifest under `roles/` provides the selected Architect, optional Feature Planner (`feature_planner`), optional UX Designer (`ux_designer`), Developer, Test Engineer (`tester` protocol role), Reviewer, Documenter, Local Git Steward (`git_steward`), or Leader identity, defaults, guidance bundle, change boundary, and allowed evidence types.
3. The launcher pins the complete role policy and every selected skill under `.codexteam/runtime/` when the draft starts, so feedback and finalization cannot drift when repository defaults change.

The nine roles do not share one role prompt. They share common project rules, then receive distinct role instructions. Feature Planner is optional after accepted architecture for materially multi-part implementation, and UX Designer is optional for new or materially redesigned interfaces; the default project task scaffold is unchanged. Generated native Codex custom-agent projections under `generated/native-agents/` are optional; the existing `spawn-subagent.sh` process remains the authoritative CodexTeam execution path.

## Test Gates

Every initialized project contains authoritative `management/TEST_GATES.toml`, its explanatory `management/TEST_GATES.md`, Developer-owned `tests/unit/` plus `tests/smoke/`, and Test Engineer-owned `tests/integration/`. T001 replaces both empty command arrays before implementation approval.

- The **Development Gate** proves changed algorithms/components and one basic smoke path. A pass is not integration acceptance.
- The **Integration Gate** is the local CI-equivalent command. It invokes the Development Gate first, then applicable integration, regression, system, security, browser, environment, and manifest checks.

The Test Engineer may add or modify handoff-scoped integration/regression tests, fixtures, test data, and golden expectations. Every changed expectation requires approved requirement, decision, or confirmed test-defect justification. Product defects return to the same Developer session before finalization; external CI and leader closure run the same Integration Gate.

## Workflow

1. Clarify the goal and initialize an exact standalone Git project workspace.
2. Approve the project specification and Architect-owned design; when needed, accept one Feature Planner advisory decomposition before creating multiple implementation tasks.
3. Assign each task attempt or evidence stage to one responsible AI and start a persistent draft session.
4. Review the draft and return consolidated feedback in the same session and attempt.
5. Accept the draft and persist one final result using the result contract.
6. Run the Development Gate, independent Integration Gate, and Reviewer audit as applicable.
7. Close canonical task state only after verification passes.
8. At a named milestone, explicitly authorize the Local Git Steward to create one verified local commit; remote actions remain human-only.

## Runtime

The cold-start Project Lead creates projects under:

```text
./projects/<project-id>/
```

The guaranteed Project Lead base folder is `/home/alik/workspace/agent_template/codexteam`. Start a fresh Codex session there; root `AGENTS.md` establishes the lead role immediately and routes approved initialization through `.agents/LEAD_BOOT.md`.

## Fresh Codex Startup

When the operator asks for a new project, the root agent acts as Project Lead. It clarifies material requirements, proposes the project description and management plan, waits for initialization approval, creates structure under `./projects`, prepares project-specific milestones and responsible-AI tasks, and waits for `GO` before spawning workers.

The operator should not need to restate the orchestration protocol. See `.agents/LEAD_BOOT.md` for the one-page cold-start contract.

After initialization, the lead carries the exact `Created:` path forward instead of retyping a generated directory name. An instruction such as “handle it yourself end to end” tells the lead to manage the team autonomously; it does not collapse responsible-AI roles into solo lead work. Only an explicit “do not spawn agents” instruction selects solo execution.

For a cloud-enabled cold start, `gpt54-mini` at medium reasoning is the recommended Project Lead. Before it starts a local subprocess worker, it checks whether the same execution surface can reach host Ollama. A reachable nested route may use `--trust-parent-sandbox`; an isolated route launches at the approved host level without that flag and retains the worker's normal sandbox. MCP is not required for either route.

## Execution Profiles

Profiles are curated per backend and identified as `backend/profile`. Use
`./scripts/inspect-execution-catalog.py profiles --backend <backend>` to inspect
supported and host-available options. Installation alone does not imply support.

Curated optional Codex local profiles include `qwen38-27b`, `muse-glimmer`, and
`gemma4-26b` in addition to the existing profiles. `ornith35b`, `gpt56-luna`,
and `gpt56-terra` remain installed but uncurated because their live qualification
did not pass or could not run.

## Commands

`./.agents/scripts/spawn-subagent.sh` is the supported worker entry point.

Initialize a project without writing:

```bash
./scripts/init-project.py "Example Project" \
  --goal "Deliver a verified example." --projects-root ./projects --dry-run
```

Start a developer draft:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --backend codex --profile qwen38-27b --reasoning-effort medium \
  --team example --task T003 --attempt att-001 \
  --role developer --workspace ./projects/example \
  --prompt-file ./projects/example/management/tasks/T003.md
```

Every attempt uses `artifact-report-v1`. The worker writes
`results/reports/<TASK>-<attempt>.json` with `version`, `summary`, evidence path
strings, and limitations; unknown fields are ignored. Terminal output is
diagnostic only. The launcher owns identity, status, file changes, output
metadata, timestamps, and provider-free finalization.

Every new attempt also receives an immutable `execution-spec.json` under its
existing session directory. It records resolved role, handoff digest,
backend/model/reasoning, guidance, permissions, and gate routing without storing
raw prompts or secrets. Session and result paths and lifecycle semantics remain
stable.

Select one technical specialization on a new attempt with `--agent-spec`, for
example `--agent-spec cpp-embedded-developer`. Omission means no specialization.
Role, AgentSpec, and execution profile remain
separate; feedback/final reuse the pin and reject selection overrides. See
`docs/AGENT_SPECS.md`.

OpenCode profiles, implementation, qualification evidence, and historical
attempt readers remain in the repository. Supported commands mark those profiles
disabled and reject new OpenCode drafts and feedback. Existing finalized records
remain readable; provider-free finalization code is retained for an already
accepted historical attempt.

New handoffs explicitly classify execution as `small` or `complex`. Small work
defaults to 600 seconds; complex work defaults to 1200 seconds; explicit
`--timeout` values override and are pinned for continuation turns. Complex
Developers return source/focused-test evidence before the Development Gate, then
return the gate in the same session. Complex Test Engineers return their final
browser/integration evidence and report before finalization. The catalog never
silently falls back between models.

Review the draft, then continue the exact session with `--phase feedback` while
omitting backend, profile, reasoning, and AgentSpec selectors. Final does the
same and loads the pinned ExecutionSpec. Draft and feedback may edit
handoff-scoped project files, but they never write the deterministic result.

Add `--run-guard` when live protection from an unchanged failure loop or unbounded
discovery is warranted. It interrupts an exact three-failure repeat, a command result
over 32 KiB, or broad repository discovery after successful context MCP routing. The
private JSONL keeps the full event and a captured thread remains resumable. It is not
a token, time, tool-count, or general retry limit.

For OpenAI-backed profiles, each final turn receives a session-pinned role-specific
output schema. The launcher owns and normalizes result identity, UTC timestamp, and
Git Steward's empty change set before validation. Every turn also preserves the exact
raw Lead prompt beside its private transcript. Local providers receive the compact
contract instructions because their structured-output support is not assumed.

Inspect current and stale project-local workers:

```bash
./scripts/subagent-status.py ./projects/example
```

Validate role manifests and generated native projections:

```bash
./scripts/inspect-role-policies.py
./scripts/manage-native-agents.py --check
```

Preview installation into `$CODEX_HOME/agents`, then explicitly apply it:

```bash
./scripts/manage-native-agents.py --install
./scripts/manage-native-agents.py --install --apply
```

Refresh managed role references in an existing initialized project with `./scripts/sync-project-guidance.py <project> --apply`. The command previews by default and refuses unmanaged collisions.

Validate its result:

```bash
./scripts/verify-result.py \
  ./projects/example/results/T003-att-001.json \
  --task T003 --team example --attempt att-001 --role developer \
  --expected-status completed
```

Close the task after independent verification:

```bash
./scripts/close-loop.sh ./projects/example \
  --task T003 -- ../../scripts/run-test-gate.py . --gate integration \
  --execution-surface worker --snapshot-task T003 --snapshot-attempt att-001
```

Run the configured gates and preview a milestone boundary:

```bash
./scripts/run-test-gate.py ./projects/example --gate development --execution-surface worker
./scripts/run-test-gate.py ./projects/example --gate integration --execution-surface worker
./scripts/git-steward.py inspect ./projects/example \
  --boundary milestone-001 --tasks T003,T004,T005 --json
```

Git authorization and commit commands preview by default and mutate only with `--apply`. See `.agents/playbooks/milestone-commit.md`; no Git Steward command performs a remote action.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 ../env-python/bin/python -m pytest -q tests
```

## Read-only WebUI

Start the local status UI with:

```bash
../env-python/bin/python projects/codexteam-project-management-web-ui/scripts/run-webui.py
```

Open `http://127.0.0.1:5000`. The Web UI is owned by the standalone
`projects/codexteam-project-management-web-ui` repository and reads the shared
`./projects` artifacts through the parent `codexteam_tools` readers. It provides a
newest-first project status table, compact Current Focus, a deterministic six-lane
Kanban with ten-card older-task disclosures, human-readable Agent activity,
expandable task/attempt/turn details, and verified milestone commits. Milestones
appear as grouping metadata while canonical task IDs lead task titles. Each returned
turn gets a private metrics sidecar with token deltas, tool and failure counts,
command-output volume, repeats, and redacted previews of the three largest commands.
OpenCode sidecars additionally report bounded model-step token growth, tool counts and
UTF-8 text-output bytes by tool, plus labeled local context-component bytes. These are
observations, not a reconstruction or token estimate of the complete provider prompt.
The theme menu defaults to the operating-system theme and remembers an explicit Light
or Dark choice in the browser. The UI exposes GET views only and cannot start workers,
retry tasks, edit project state, or modify Git.

Preview historical sidecar generation with `./scripts/backfill-turn-metrics.py ./projects/<project-id>`. Add `--write` only after reviewing the count; existing sidecars are not replaced by default.

Preview the controlled end-to-end team canary with:

```bash
./scripts/run-e2e-fibonacci-test.sh --dry-run \
  --profile gpt54-mini --reasoning-effort medium
```

See `scripts/TOOLS-README.md` for live-run budgeting, reports, product-only verification, and same-session failure recovery. The cold-start-through-team acceptance definition, including product-audit and proportional-performance gates, is in `docs/E2E_ACCEPTANCE_PLAN.md`.

Start with `docs/USER_GUIDE.md`, `.agents/skills/project-lead.md`, and `.agents/skills/subagent-orchestration.md`.
