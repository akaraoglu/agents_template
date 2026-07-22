# CodexTeam Tool Reference

## Initialize

```bash
./scripts/init-project.py "Project Name" \
  --goal "Concrete project goal." --projects-root ./projects --dry-run
```

Important options: `--project-id`, `--projects-root`, `--template-root`, `--tasks`, `--json`.

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
  --task T002 --team example --attempt att-001 --role developer \
  --expected-status completed
```

Exit `1` means invalid JSON/contract. Exit `2` means the result is valid but does not match the expected scope or status.

## Spawn a Subagent

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --profile qwen36-27b --team example --task T002 --attempt att-001 \
  --role developer --workspace <project> --prompt-file <handoff> --dry-run
```

Remove `--dry-run` only after inspecting the command, session location, and final result location. Continue with `--phase feedback` for revisions and `--phase final` after acceptance, keeping the same scope identity.

## Close a Task

```bash
./scripts/close-loop.sh <project> --task T002 \
  --result results/T002-att-001.json -- \
  python3 -m pytest -q
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

The server binds only to `127.0.0.1:5000`. It reads existing project, session, JSONL, and `results/e2e-report.md` artifacts directly and provides project list, project detail, and two-run comparison views. Missing durations, tokens, or verdicts display as `unknown`. There are no mutation routes or recovery actions.
