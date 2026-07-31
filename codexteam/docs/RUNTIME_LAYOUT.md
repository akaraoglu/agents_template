# Runtime Layout

The default projects root for a cold-start Project Lead is `/home/alik/workspace/agent_template/codexteam/projects`.

```text
/home/alik/workspace/agent_template/codexteam/projects/<project-id>/
  AGENTS.md
  PROJECT.md
  BRIEF.md
  ARCHITECTURE.md
  IMPLEMENTATION_PLAN.md
  TASKS.md
  PROJECT_STATE.md
  CURRENT_TASK.md
  OPEN_QUESTIONS.md
  DECISIONS.md
  RESULT.md
  DONE_REPORT.md
  BLOCKED_REPORT.md
  .codexteam/skills/
  .codexteam/roles/           # managed discoverable role-policy references
  .codexteam/native-agents/   # managed optional native-agent projections
  .codexteam/runtime/          # ignored persistent sessions and conversation turns
  management/
    PLAN.md
    BACKLOG.md
    GIT_POLICY.md
    TEST_GATES.md
    TEST_GATES.toml
    tasks/T001.md ... T005.md
  docs/architecture/
  docs/decisions/
  src/
  tests/unit/                # Developer-owned algorithm and component tests
  tests/smoke/               # Developer-owned basic executable paths
  tests/integration/         # Test Engineer-owned CI-equivalent checks
  results/
```

Each logical task attempt stores a private Codex home, exact thread ID, replayable model settings, pinned `role-policy.json`, pinned `guidance/` files, `guidance-manifest.json`, and turn artifacts under `.codexteam/runtime/sessions/<team>/<task>/<attempt>/`. Every turn persists `<turn>.jsonl`, `<turn>.txt`, `<turn>.stderr.txt`, and `<turn>.metrics.json`; guarded turns flush JSONL and stderr while the process runs, while ordinary turns keep the buffered path. The metrics sidecar is generated once after the process returns and records cumulative and delta usage, tool/failure counts, command-output byte volume, repeats, MCP response volume and repeated tools, and redacted previews of the three largest commands. It does not store command output, MCP arguments, or MCP response content. `session.json` and `turn-state.json` record the pinned role's allowed MCP servers plus the configured servers that were effective or missing for that process. `session.json` also records stable scope, policy identity, instruction-bundle digest, and turn count. `turn-state.json` is written as `running` before execution and replaced with the terminal observation afterward. Run Guard reuses the existing `interrupted` state and preserves a captured thread for feedback; it adds no result or lifecycle state. The generated `.gitignore` excludes this directory. Final results and gate records remain under `results/`.

Git Steward authorization, commit records, and generated PR summaries live under ignored `.codexteam/runtime/git-steward/<boundary>/`. The Web UI reads completed commit records but cannot create or authorize them.

Set `CODEXTEAM_PROJECTS_ROOT` or pass `--projects-root` to use another approved location. Each initialized project is an exact standalone Git root by default; `--no-git` is an explicit exception. Session and Git Steward runtime remain ignored and must not be committed.
