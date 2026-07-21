# CodexTeam Scripts

Operator commands are thin wrappers around `src/codexteam_tools/`.

- `init-project.py`: preview or create a complete project workspace.
- `update-tasks.py`: update one validated task row atomically.
- `verify-result.py`: validate result contract v1 and expected scope.
- `close-loop.sh`: independently verify and close one task.
- `run-e2e-fibonacci-test.sh`: run or preview the controlled five-role Fibonacci Tree CLI canary.
- `../.agents/scripts/spawn-subagent.sh`: run one `draft`, `feedback`, or `final` turn in a persistent local Codex session.

All commands provide `--help`. File-mutating commands support dry-run where a preview is meaningful. No command uses external Python dependencies or evaluates shell text.

Preview the live canary before spending model time:

```bash
./scripts/run-e2e-fibonacci-test.sh --dry-run \
  --profile gpt54-mini --reasoning-effort medium
```

The canary creates a unique project, uses ten persistent-session turns across five accountable roles, stops at the first failure, and never retries or changes models automatically. Use `--product-only <project>` to rerun deterministic product checks without an agent call.
