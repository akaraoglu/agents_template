# CodexTeam Tool Reference

## Initialize

```bash
./scripts/init-project.py "Project Name" \
  --goal "Concrete project goal." --projects-root ./projects --dry-run
```

Important options: `--project-id`, `--projects-root`, `--template-root`, `--tasks`, `--no-git`, `--json`. New projects are standalone Git roots by default; initialization does not create a commit.

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
  --phase draft --profile qwen36-27b --team example --task T003 --attempt att-001 \
  --role developer --workspace <project> --prompt-file <handoff> --dry-run
```

Remove `--dry-run` only after inspecting the command, session location, and final result location. Continue with `--phase feedback` for revisions and `--phase final` after acceptance, keeping the same scope identity.

`--profile` is an explicit override. When omitted, the selected role policy supplies its default profile. The precedence is lead CLI override, pinned role-policy default, then profile configuration for values the policy does not set. The first draft snapshots the full policy and selected skill contents under the attempt runtime directory; resumes use that exact instruction bundle.

Finalization passes the strict `schemas/result-v1-openai.json` projection to OpenAI-backed profiles with `--output-schema`; persisted records remain validated against the backward-compatible result-v1 contract. Local providers receive the same compact required-field instructions without being told to search for an unavailable schema. Contract validation and project-boundary checks run before either result is persisted.

## Run Test Gates

```bash
./scripts/run-test-gate.py <project> --gate development --dry-run
./scripts/run-test-gate.py <project> --gate development
./scripts/run-test-gate.py <project> --gate integration
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
  --result results/T003-att-001.json -- \
  ../../scripts/run-test-gate.py . --gate integration
```

Use `--result` whenever a task has more than one attempt so closure validates the exact accepted result instead of relying on filename ordering.

Arguments after `--` are executed directly from the project root without a shell.

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
  --product-only ./projects/<project-id> \
  --report-file /tmp/<project-id>-product-check.md
```

The product-only gate runs the unittest suite and the repository-owned black-box acceptance harness. It checks all Fibonacci values from 0 through 15, exact base cases, raw-byte input-4 golden output, right-subtree indentation, repeated-output determinism, help, invalid-input streams and nonzero statuses, and the input-15 node count. A full live completion also runs the clean delivery-manifest gate. Reports keep lifecycle, product, evidence, management, manifest, and performance verdicts independent.

## Read-only WebUI

```bash
../env-python/bin/python scripts/run-webui.py
```

The server binds only to `127.0.0.1:5000`. It reads existing project, session, JSONL, per-turn metrics, gate, milestone-commit, and `results/e2e-report.md` artifacts directly. Projects appear once in Needs attention, Active, or Recently completed. The project view uses a deterministic six-lane Kanban, shows the ten newest tasks in each lane before an older-task disclosure, and expands into attempts, turns, token deltas, tool-cycle counts, errors, diagnostics, and verified local commits. Milestone IDs are grouping metadata and canonical task IDs lead task titles. It also ranks the ten completed drafts with the largest input deltas. The theme menu defaults to System Default and stores an explicit Light or Dark preference in browser-local storage. Missing compact metrics and all-missing verdict groups are omitted. There are no mutation routes or recovery actions.

## Turn Metrics Backfill

Preview sidecars for existing sessions:

```bash
./scripts/backfill-turn-metrics.py ./projects/<project-id>
```

Write only the missing sidecars after reviewing the preview:

```bash
./scripts/backfill-turn-metrics.py ./projects/<project-id> --write
```

The default is read-only. Existing valid sidecars are preserved; replacing them requires both `--write --overwrite`. Add `--json` for machine-readable path/action records. Sidecars contain counts, byte sizes, token totals and deltas, command fingerprints, and redacted command previews, never command output content.
