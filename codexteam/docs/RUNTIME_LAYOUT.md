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

Each logical task attempt stores a private Codex home, exact thread ID, replayable
model settings, pinned `role-policy.json`, role-specific `result-schema.json`, pinned
`guidance/` files, `guidance-manifest.json`, and turn artifacts under
`.codexteam/runtime/sessions/<team>/<task>/<attempt>/`. Every turn persists the exact
raw `<turn>.lead-prompt.md` plus `<turn>.jsonl`, `<turn>.txt`, `<turn>.stderr.txt`, and
`<turn>.metrics.json`. Guarded turns flush JSONL and stderr while the process runs;
ordinary turns keep the buffered path. Metrics are generated once after return and
record cumulative and delta usage, tool/failure counts, command-output volume,
repeats, MCP response volume, and redacted previews of the three largest commands.
They do not store command output, MCP arguments, or MCP response content.
`session.json` and `turn-state.json` record pinned MCP policy and effective subsets.
New bound worker attempts also record `mcp_context_project`; legacy sessions remain
unbound. Run Guard preserves a captured thread and full private JSONL when it
interrupts. Ignored `.codexteam/runtime/lead-checkpoint.json` holds a compact Lead
rotation checkpoint and is not acceptance evidence. Rolling gates remain under
`results/gates/`; immutable accepted snapshots live under `results/gates/accepted/`.

Git Steward authorization, commit records, and generated PR summaries live under ignored `.codexteam/runtime/git-steward/<boundary>/`. The Web UI reads completed commit records but cannot create or authorize them.

Set `CODEXTEAM_PROJECTS_ROOT` or pass `--projects-root` to use another approved location. Each initialized project is an exact standalone Git root by default; `--no-git` is an explicit exception. Session and Git Steward runtime remain ignored and must not be committed.
