# CodexTeam User Guide

## 0. Start a Fresh Project Lead

Start Codex in `/home/alik/workspace/agent_template/codexteam`. Root `AGENTS.md` assigns the Project Lead role for the first proposal and routes approved initialization through `.agents/LEAD_BOOT.md`; the operator does not need to repeat the orchestration protocol.

When cloud use is acceptable, prefer `gpt54-mini` at medium reasoning for this root Project Lead. Before launching a local worker, check the Ollama endpoint from the same execution surface. A reachable nested route can use the documented `--trust-parent-sandbox` option; if the parent cannot reach host Ollama, use an approved host-level launch without the flag so the worker keeps its normal sandbox. MCP is not required.

For a new project, the lead first clarifies material requirements and presents the project description and management plan. Initialization requires approval, and later worker execution requires a separate explicit authorization such as `GO`.

## 1. Initialize Structure

Preview first:

```bash
./scripts/init-project.py "Example" \
  --goal "Deliver a verified example." --projects-root ./projects --dry-run --json
```

Run again without `--dry-run` only after approval. Use `--project-id` when a stable directory name is required. Initialization creates canonical files, task scaffolding, and an exact standalone local Git repository. It does not create a commit or authorize implementation or worker spawning. `--no-git` is available only for an intentional exception.

Initialization also writes managed `.codexteam/roles/` and `.codexteam/native-agents/` references. Project `AGENTS.md` is common guidance; the launcher-selected role policy and skills form the worker-specific instruction layer. The live attempt pins the complete bundle under ignored runtime state.

Copy the initializer's exact project ID and absolute `Created:` path into all later commands. Do not reconstruct a generated path from memory. Confirm `PROJECT.md` and the selected task handoff exist there before starting a worker.

## 2. Specify, Plan, and Approve

Update `PROJECT.md` with the approved aim, scope, description, and observable acceptance criteria. Configure authoritative argument arrays in `management/TEST_GATES.toml` for a fast Developer-owned Development Gate and a Test Engineer-owned Integration Gate that invokes it before broader CI-equivalent checks. Then prepare project-specific milestones, architecture and commit boundaries, implementation plan, and responsible-AI assignments. Do not begin worker execution until the operator approves the plan.

After that approval, “handle it yourself” or “end to end” means the Project Lead should coordinate the assigned team without routine operator questions. It does not mean the lead should silently perform every role; solo execution requires an explicit instruction not to spawn agents.

## 3. Start a Worker Draft

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --profile qwen36-27b --team example --task T002 --attempt att-001 \
  --role architect --workspace <project-root> \
  --prompt-file <project-root>/management/tasks/T002.md
```

Use `--dry-run` to inspect the exact command, profile, guidance, session path, and final result path without starting Codex. The draft is conversational output and does not create a result.

To run a local OpenCode canary instead, add `--backend opencode` with `--profile muse-glimmer`, `--profile ornith35b`, or `--profile qwen36-27b`. Keep that backend and profile on every turn. Muse selects `ollama/muse-glimmer:30b`; Qwen selects tuned `ollama/qwen3.6-27b:latest`. OpenCode aliases do not change Codex profiles of the same names. OpenCode uses an attempt-private configuration and exact stored session ID. Do not add `--reasoning-effort`, `--trust-parent-sandbox`, or `--run-guard`; MCP and LSP are not enabled for this backend yet.

Use the opt-in `--run-guard` for turns where an unchanged command-failure loop or
unbounded discovery is a material risk. It streams private diagnostics and interrupts
after three consecutive identical failed command results, a command result over 32 KiB, or broad repository
discovery after a successful context MCP call. The full event remains in JSONL and it
preserves a captured thread for scoped same-attempt feedback. The guard is not a
token, time, tool-count, or general retry limit.

The role manifest selects the default profile and guidance bundle when `--profile` and `--skill-file` are omitted. Lead overrides are explicit. Draft snapshots the policy and skill contents; policy and instruction-bundle digests are embedded in the handoff, session, turn state, and final launcher outcome. Continuations reject a changed pinned file.

T002 uses `--role architect` to produce `ARCHITECTURE.md` and material ADRs without implementation or self-approval. After Project Lead acceptance, T003 uses `--role developer`; the Developer owns algorithm/unit tests, smoke tests, and the Development Gate. After its draft passes, T004 starts an independent Test Engineer with `--role tester`; that protocol name is retained for result compatibility. The Test Engineer may change only handoff-scoped integration/regression tests and controlled expectations, never production source or Developer-owned tests. Return classified product defects to the same Developer session before finalization, then resume the Test Engineer and rerun affected checks plus Integration Gate against the final revision. T005 uses `--role reviewer` for acceptance and architecture conformance.

Run gates through the repository-owned executor:

```bash
./scripts/run-test-gate.py <project-root> --gate development --execution-surface worker
./scripts/run-test-gate.py <project-root> --gate integration --execution-surface <worker-or-lead_host>
```

Run `curl -fsS http://127.0.0.1:11434/api/version` from the same execution surface before the live draft. For the default Codex backend, a reachable already-sandboxed route may add `--trust-parent-sandbox`; otherwise use the approved host-level launcher without it. OpenCode attempts always use the approved host-level route and reject `--trust-parent-sandbox`; they do not provide an equivalent OS sandbox. A successful `--dry-run` does not test model connectivity. See `.agents/playbooks/nested-worker-sandbox.md` for Codex app-server and `bwrap` recovery.

Prefer `--prompt-file` for handoffs and feedback. Markdown backticks, dollar signs, and shell metacharacters inside an inline `--prompt` can be interpreted by the calling shell before Codex or OpenCode receives them.

## 4. Review and Continue the Same Session

The Project Lead inspects the draft and sends one consolidated decision. Use `--phase feedback` for corrections and `--phase final` only after acceptance. Keep the same team, task, attempt, role, profile, and workspace arguments. The launcher resumes the exact stored thread ID and never relies on the most recent global session.

Ordinary corrections do not create new attempts. Start a new attempt only after irrecoverable session loss, intentional reassignment, material scope change, or explicit abandonment.

If a turn fails, is interrupted by timeout or Run Guard, or returns no final message, inspect the printed diagnostics path and the adjacent JSONL file. Resume the same attempt when its exact thread ID was captured. If repeated focused feedback demonstrates a real capability mismatch, record an intentional owner/profile transfer and continue in a new attempt; the abandoned attempt must remain result-free unless the Project Lead deliberately finalizes it as terminal.

Inspect all project-local attempts without searching global Codex history:

```bash
./scripts/subagent-status.py <project-root>
```

Use `--active-only` to show running or stale attempts and `--json` for machine-readable output. Status inspection never mutates, retries, or terminates a worker.

For existing current-system projects, preview `./scripts/sync-project-guidance.py <project-root>` and add `--apply` to install the managed role references. It does not migrate historical archives or rewrite project documents.

## 5. Validate the Final Result

```bash
./scripts/verify-result.py \
  <project-root>/results/T003-att-001.json \
  --task T003 --team example --attempt att-001 --role developer \
  --expected-status completed
```

Validation does not prove the work is correct. It proves the result envelope is usable.

## 6. Close the Task

```bash
./scripts/close-loop.sh <project-root> --task T003 -- \
  ../../scripts/run-test-gate.py . --gate integration \
  --execution-surface worker --snapshot-task T003 --snapshot-attempt att-001
```

The command validates artifacts, runs verification without a shell, records output under `results/`, updates project state, and advances to the next incomplete task. For implemented product behavior, use the configured Integration Gate or an exact wrapper as the closure command. Repeating the same successful close is idempotent.

## 7. Deliver

When the final planned task closes, CodexTeam writes `DELIVERY.md`, updates `DONE_REPORT.md`, and sets project status to `DELIVERED`.

After each closure, the Project Lead must also synchronize `BRIEF.md`, milestone checkboxes, and implementation-plan status. The closure command owns canonical task state, but it does not infer project-specific narrative updates.

## 8. Create a Verified Local Milestone Commit

Do this only after Reviewer acceptance and current Integration Gate evidence, or after accepted architecture-review evidence for an architecture-only boundary.

The read-only Git Steward returns one exact `commit-plan-v1` JSON draft. After review, the Project Lead persists that unchanged JSON at `<project-root>/.codexteam/runtime/git-steward/<boundary>/plan.json`; the commands below validate and pin its digest.

```bash
./scripts/git-steward.py inspect <project-root> \
  --boundary milestone-001 --tasks T003,T004,T005 --json
./scripts/git-steward.py authorize <project-root> --plan <project-plan.json>
./scripts/git-steward.py authorize <project-root> --plan <project-plan.json> --apply
./scripts/git-steward.py commit <project-root> \
  --plan <project-plan.json> --authorization <authorization.json>
./scripts/git-steward.py commit <project-root> \
  --plan <project-plan.json> --authorization <authorization.json> --apply
```

Preview is the default. The plan must be inside the exact Git-root project, and authorization is stored under ignored runtime. The applied executor re-verifies the candidate tree and creates one local commit. Push, merge, tag, release, publication, and remote PR creation require human action outside CodexTeam.
