# CodexTeam Scripts

Operator commands are thin wrappers around `src/codexteam_tools/`.

- `init-project.py`: preview or create a complete project workspace.
- `update-tasks.py`: update one validated task row atomically.
- `verify-result.py`: validate the result contract and expected scope.
- `inspect-role-policies.py`: validate and display canonical role identity, defaults, and digests.
- `inspect-execution-catalog.py`: query curated supported and host-available execution options.
- `manage-native-agents.py`: preview, check, generate, or safely install namespaced native Codex agent projections.
- `subagent-status.py`: report running, stale, interrupted, draft-ready, and finalized project-local attempts.
- `sync-project-guidance.py`: preview, check, or refresh managed role references in an initialized project.
- `run-test-gate.py`: dry-run, execute, or validate the project Development and Integration Gates from TOML argument arrays.
- `git-steward.py`: inspect a verified Git boundary, pin authorization, and create one exact local commit after explicit `--apply`.
- `local-docs-index.py`: preview, atomically update, or verify the deterministic offline documentation index.
- `local-docs-mcp.py`: serve the fixed three-tool offline read-only documentation MCP over STDIO.
- `benchmark-team-context-mcp.py`: compare bounded context tools with broad and focused local reads, including the selected role's filtered tool-schema cost.
- `close-loop.sh`: independently verify and close one task.
- `run-e2e-fibonacci-test.sh`: run or preview the historical five-role Fibonacci Tree CLI compatibility canary.
- `../.agents/scripts/spawn-subagent.sh`: run one `draft`, `feedback`, or `final` turn in a persistent local Codex session.

All commands provide `--help`. File-mutating commands support dry-run or preview where meaningful. No command uses external Python dependencies or evaluates shell text. Git Steward has no remote operations.

Preview the live canary before spending model time:

```bash
./scripts/run-e2e-fibonacci-test.sh --dry-run \
  --profile gpt54-mini --reasoning-effort medium
```

The canary creates a unique project, uses ten persistent-session turns across five accountable roles, stops at the first failure, and never retries or changes models automatically. Use `--product-only <project>` to rerun deterministic product checks without an agent call.
