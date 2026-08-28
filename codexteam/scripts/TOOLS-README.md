# CodexTeam Tool Reference

## Local Documentation

Preview the approved offline sources before writing:

```bash
../env-python/bin/python scripts/local-docs-index.py \
  --manifest local-docs.toml
```

Build or verify the ignored mode-`0600` SQLite FTS5 index:

```bash
../env-python/bin/python scripts/local-docs-index.py \
  --manifest local-docs.toml --update
../env-python/bin/python scripts/local-docs-index.py \
  --manifest local-docs.toml --verify
```

The separately registered `local-docs` MCP server opens that index read-only
and exposes only source listing, bounded search, and exact-locator reads. It has
no network, shell, indexing, or mutation tool.

## Initialize

```bash
./scripts/init-project.py "Project Name" \
  --goal "Concrete project goal." \
  --projects-root /home/alik/workspace/codexspace/projects \
  --dry-run
```

Important options: `--project-id`, `--projects-root`, `--with-product-scaffold`,
`--template-root`, `--tasks`, `--no-git`, `--json`. New controls are standalone
Git roots by default; initialization does not create a commit.

## Update a Task

```bash
./scripts/update-tasks.py <project>/TASKS.md \
  --task T002 --status "Needs Review" --verification "Focused checks passed" \
  --evidence '`results/T002.json`' --dry-run
```

The command fails on missing tasks, malformed tables, invalid statuses, pipes, or multiline cell values.

## Verify a Result

```bash
./scripts/verify-result.py <result.json> \
  --task T003 --team example --attempt att-001 --role developer \
  --expected-status completed
```

Exit `1` means invalid JSON/contract. Exit `2` means the result is valid but does not match the expected scope or status.

## Spawn a Subagent

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --backend codex --profile qwen36-27b --reasoning-effort medium \
  --team example --task T003 --attempt att-001 \
  --role developer --workspace <project> --prompt-file <handoff> --dry-run
```

Remove `--dry-run` only after inspecting the command, session location, and final result location. Continue with `--phase feedback` for revisions and `--phase final` after acceptance, keeping the same scope identity.

OpenCode turns default to `--debug-stream activity`, which emits a metadata-only activity
ledger. Activity records show tool name, status, safe target or command details,
duration, exit code or match count when reported, result byte size, truncation,
model-step token counts, and final process status. They never print file contents,
command output, write/edit text, or patch bodies. Debug content is written to
launcher stderr and may still contain sensitive project names, paths, commands,
queries, or assistant text. Use `--debug-stream assistant` to also stream emitted
assistant text, or `--debug-stream off` to disable it. Non-OpenCode backends
default to off. These modes do not alter the
complete mode-`0600` JSONL captured under the attempt's `turns/` directory. The
flag is invocation-scoped, so repeat it on a feedback or final command only when
live debugging is still needed. OpenCode can show only events the provider emits;
private model reasoning is not available.

Draft backend, backend-scoped profile, and reasoning are explicit and resolve
through `execution_registry.toml`. Feedback/final omit them and use the pinned
ExecutionSpec. RolePolicy contains no execution defaults. Role policies may
narrow MCP access; immutable allowed/effective subsets live in the ExecutionSpec.

Finalization passes a session-pinned, role-specific projection of
Finalization is provider-free and does not use a provider output schema.
Its digest is retained in session state so later toolkit changes cannot alter an active
attempt. Persisted records remain validated against the backward-compatible result
contract. Local providers receive the same compact required-field instructions.

## Run Test Gates

```bash
./scripts/run-test-gate.py <project> --gate development --execution-surface worker --dry-run
./scripts/run-test-gate.py <project> --gate development --execution-surface worker
./scripts/run-test-gate.py <project> --gate integration --execution-surface worker
./scripts/run-test-gate.py <project> --gate integration --check-record
```

The authoritative configuration is `management/TEST_GATES.toml`. Commands are argument arrays and never pass through a shell. Integration always runs Development first. Passing records under `results/gates/` include the configured verification-path manifest and digest; `--check-record` rejects stale evidence.

## Local Git Steward

```bash
./scripts/git-steward.py inspect <project> \
  --boundary milestone-001 --tasks T003,T004,T005 --json
./scripts/git-steward.py authorize <project> --plan <plan.json>
./scripts/git-steward.py authorize <project> --plan <plan.json> --apply
./scripts/git-steward.py commit <project> \
  --plan <plan.json> --authorization <authorization.json>
./scripts/git-steward.py commit <project> \
  --plan <plan.json> --authorization <authorization.json> --apply
```

Inspection and preview are non-committing. The project must be the exact Git root, branch and HEAD must match, evidence must be current, the index must be clean, and every staged path must be explicitly authorized. Applied commit reconstructs and re-tests the candidate tree before one local commit. The tool never pushes, merges, tags, releases, publishes, or opens a remote PR.

## Milestone Retrospective V2

New rounds use a staged Lead flow:

```text
prepare -> tool-free evaluate -> deterministic accept
        -> prioritized Proposed entries -> human decide
```

These commands describe the staged v2 contract. The current CLI does not expose
historical v1 `analyze`; a branch that still lists only `analyze`/`decide` must
not use `analyze` for a new round and should wait for the v2 surfaces.

Prepare immutable evidence without a model call or backlog mutation:

```bash
./scripts/milestone-retrospective.py prepare <control-root> \
  --boundary <id> --tasks <T001,T002> --apply --json
```

Run one tool-free local evaluation over the exact applied preparation:

```bash
./scripts/milestone-retrospective.py evaluate <control-root> \
  --boundary <id> --preparation <preparation-digest> \
  --profile <curated-local-profile> --apply --json
```

Review the strict report returned by `evaluate`, then preview `accept` with its
exact evaluation digest and path. Add `--apply` only after review:

```bash
./scripts/milestone-retrospective.py accept <control-root> \
  --boundary <id> --preparation <preparation-digest> \
  --evaluation-digest <evaluation-digest> \
  --evaluation-path <evaluation-path> --json
```

Evaluation is one schema-constrained request to a curated local Ollama profile.
The Reviewer-derived AgentSpec supplies identity and guidance, but this is not a
worker task or session: it has no tools, filesystem, MCP, cloud profile, retries,
or other project context. Acceptance validates the AgentSpec identity and
digest, strict report, preparation and evidence digests, and E1/E2/E3 action
ceiling without a model call. It may retain observations or investigations in
`NO_CHANGE`; observations are not causes. A proposal is allowed rarely, at E3,
and must name a concrete mechanism. Do not judge speed against unlike work.

Applied acceptance automatically records validated proposals in the backlog as
`Proposed`. The Lead presents impact, action band, evidence strength, change
risk, change amount, reversibility, confidence, and recurrence breadth as
separate categories. Order impact high to low; then action band and evidence
strength; change risk low to high to unknown; change amount small to large to
unknown; reversibility easy to hard to unknown; recurrence breadth; and stable
ID. The Lead may conclude `No candidate recommended this round`.
Only a human may approve, reject, or defer; approval grants planning only.
Historical v1 `analyze` artifacts remain immutable and readable.

## Inspect Roles and Worker Status

```bash
./scripts/inspect-role-policies.py
./scripts/subagent-status.py <project>
./scripts/subagent-status.py <project> --active-only --json
```

The status command reads only the selected project's ignored runtime state. A `running` record older than its timeout plus a bounded grace period is shown as `stale`; it is not killed or retried automatically.

Generate or check optional native Codex custom-agent projections:

```bash
./scripts/manage-native-agents.py --check
./scripts/manage-native-agents.py --install
./scripts/manage-native-agents.py --install --apply
```

Preview or apply managed role references for an older current-system project:

```bash
./scripts/sync-project-guidance.py <project>
./scripts/sync-project-guidance.py <project> --apply
```

Both mutating commands refuse symlinks and files that do not carry the CodexTeam generated marker.

## Close a Task

```bash
./scripts/close-loop.sh <project> --task T003 \
  --result results/T003-att-001.json -- ../../scripts/run-test-gate.py . \
  --gate integration --execution-surface worker \
  --snapshot-task T003 --snapshot-attempt att-001
```

Use `--result` whenever a task has more than one attempt so closure validates the exact accepted result instead of relying on filename ordering.

Arguments after `--` are executed directly from the project root without a shell.

Gate configuration also declares `execution_surface = "worker"` or `"lead_host"`.
Pass the matching `--execution-surface`; the runner refuses a mismatch before running
commands. At an accepted boundary, create an immutable record in the same invocation:

```bash
./scripts/run-test-gate.py /home/alik/workspace/codexspace/projects/<project-id> --gate integration \
  --execution-surface lead_host --snapshot-task T003 --snapshot-attempt att-001
```

The rolling gate file remains useful for current status. Reviewer and closure evidence
should cite the returned content-addressed path under `results/gates/accepted/`.

Rotate an expensive Lead conversation at a milestone without losing canonical state:

```bash
./scripts/track-lead-task.py checkpoint --project /home/alik/workspace/codexspace/projects/<project-id>
```

The printed resume prompt points to an ignored compact checkpoint. It is context only,
not acceptance evidence. Cost hotspot output reports worker, Lead, and combined usage
separately.

## Controlled Fibonacci E2E Canary

Always preview the exact project ID, profile, reasoning effort, ten turns, and report path first:

```bash
./scripts/run-e2e-fibonacci-test.sh --dry-run \
  --profile gpt54-mini --reasoning-effort medium \
  --timeout-seconds 300 --budget-seconds 1800 \
  --report-file /tmp/fibonacci-tree-cli-e2e-preview.md
```

Run live by removing `--dry-run` and choosing a new report path. Add `--enforce-budget` when a functional run must still fail if elapsed time exceeds `--budget-seconds`.

When a supervising Codex surface reports Project Lead usage, pass all three token values together and the optional duration:

```bash
./scripts/run-e2e-fibonacci-test.sh \
  --profile qwen36-27b --reasoning-effort medium \
  --lead-input-tokens 1250000 --lead-cached-tokens 800000 \
  --lead-output-tokens 45000 --lead-duration-seconds 321
```

The report derives uncached lead input and evaluates the one-million-input and 50,000-output ceilings. A shell-only canary has no model-driven Project Lead, so these fields remain omitted and the lead-token ceiling remains `NOT_APPLICABLE`.

The controlled project has five sequential owners: leader fixture validation, one developer for the complete CLI and tests, tester acceptance evidence, reviewer evidence audit and focused spot checks, and documenter delivery readiness. Every task follows draft → deterministic gate → final → result validation → independent closure. The clean path is exactly ten turns.

Safety behavior:

- generated IDs include UTC time and the runner process ID unless `--project-id` is explicit;
- an existing project or report is never overwritten;
- no automatic retry, feedback turn, profile change, or ownership transfer occurs;
- the first failure preserves the project, session JSONL, stderr, and result state;
- failure output explains how to inspect and resume the exact session with consolidated feedback;
- `--budget-seconds` is reported as `PASS` or `EXCEEDED`; `--enforce-budget` controls whether an over-budget functional run is nonzero.

To check an existing implementation without initializing a team or calling a model:

```bash
./scripts/run-e2e-fibonacci-test.sh \
  --product-only /path/to/product-source \
  --report-file /tmp/<project-id>-product-check.md
```

The product-only gate runs the unittest suite and the repository-owned black-box acceptance harness. It checks all Fibonacci values from 0 through 15, exact base cases, raw-byte input-4 golden output, right-subtree indentation, repeated-output determinism, help, invalid-input streams and nonzero statuses, and the input-15 node count. A full live completion also runs the clean delivery-manifest gate. Reports keep lifecycle, product, evidence, management, manifest, and performance verdicts independent.

## Read-only WebUI

```bash
../env-python/bin/python \
  /home/alik/workspace/codexspace/repos/codexteam-project-management-web-ui/scripts/run-webui.py \
  --projects-root /home/alik/workspace/codexspace/projects
```

The standalone
`/home/alik/workspace/codexspace/repos/codexteam-project-management-web-ui`
repository owns the Flask application, templates, assets, launcher, and UI tests.
The server reads controls from `/home/alik/workspace/codexspace/projects` and binds
only
to `127.0.0.1:5000` and reads existing project, session, JSONL, per-turn metrics,
gate, milestone-commit, and `results/e2e-report.md` artifacts through the parent
toolkit. Projects appear once in a newest-first table with current focus, status and
attention, task progress, and update time. The project view uses a deterministic
six-lane Kanban, shows the ten newest tasks in each lane before an older-task
disclosure, and expands into attempts, turns, token deltas, tool-cycle counts, errors,
diagnostics, and verified local commits. Milestone IDs are grouping metadata and
canonical task IDs lead task titles. It also ranks the ten completed drafts with the
largest input deltas. The theme menu defaults to System Default and stores an explicit
Light or Dark preference in browser-local storage. Missing compact metrics and
all-missing verdict groups are omitted. There are no mutation routes or recovery
actions.

## Turn Metrics Backfill

Preview sidecars for existing sessions:

```bash
./scripts/backfill-turn-metrics.py /home/alik/workspace/codexspace/projects/<project-id>
```

Write only the missing sidecars after reviewing the preview:

```bash
./scripts/backfill-turn-metrics.py /home/alik/workspace/codexspace/projects/<project-id> --write
```

The default is read-only. Existing valid sidecars are preserved; replacing them requires both `--write --overwrite`. Add `--json` for machine-readable path/action records. Sidecars contain counts, byte sizes, token totals and deltas, command fingerprints, and redacted command previews, never command output content.
