# Runtime Layout

The default projects root is `/home/alik/workspace/codexspace/projects`.

```text
/home/alik/workspace/codexspace/projects/<project-id>/
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
  discoveries/
  docs/architecture/
  docs/decisions/
  results/
```

Split-root controls contain no product source or product test trees. Product
source, tests, build configuration, and product architecture live in the
registered source repository. Legacy single-root projects may still colocate
those paths when explicitly initialized with `--with-product-scaffold`.

Each logical task attempt stores a private Codex home, exact thread ID, replayable
model settings, pinned `role-policy.json`, role-specific `result-schema.json`, pinned
`guidance/` files, `guidance-manifest.json`, immutable `draft-format.json`, immutable
`execution-spec.json`, and turn artifacts under
`.codexteam/runtime/sessions/<team>/<task>/<attempt>/`. Every turn persists the exact
raw `<turn>.lead-prompt.md` plus `<turn>.jsonl`, `<turn>.txt`, `<turn>.stderr.txt`, and
`<turn>.metrics.json`. Every turn flushes JSONL and stderr while the process runs.
Metrics are generated once after return and
record cumulative and delta usage, tool/failure counts, command-output volume,
repeats, MCP response volume, and redacted previews of the three largest commands.
They do not store command output, MCP arguments, or MCP response content.

Attempts use the pinned `artifact-report-v1` contract. Workers write the derived
JSON report under `results/reports/`; after Project Lead acceptance, the launcher
seals identity, status, accepted file changes, process metadata, and timestamps
without another provider turn.

Direct attempts also pin `handoff-contract.json`, containing only validated
report path, bounded context ranges with digests, and fixed verification argv.
Launcher-owned focused records live under `results/checks/`; gate records remain
under `results/gates/`. Both are excluded from the worker-owned accepted change
manifest, are digest-pinned at acceptance, and become deterministic result evidence.
`session.json` and `turn-state.json` record the effective draft format plus pinned
MCP policy and effective subsets. The format sidecar is written before backend
setup so even a pre-thread failed attempt retains its contract identity.
The execution specification records only resolved identities, digests,
permissions, backend/model/reasoning facts, and gate routing. It stores no raw
prompt or secret content and does not replace the handoff, session, result,
gates, close-loop, or Project Lead authority.
Specialized attempts also store `agent-spec.json`, a complete immutable snapshot of
the selected technical overlay. An omitted AgentSpec remains null; specialist
guidance is appended to the role guidance bundle and all effective permissions
remain bounded by the canonical RolePolicy.

Mutable session state stores lifecycle progress and
an ExecutionSpec reference rather than duplicating backend, profile, model,
reasoning, AgentSpec, or permission identity. Pre-cutover active attempts are
drained or abandoned, never backfilled.
Bound worker attempts record the context project in ExecutionSpec permissions.
Run Guard preserves a captured thread and full private JSONL when it
interrupts. Ignored `.codexteam/runtime/lead-checkpoint.json` holds a compact Lead
rotation checkpoint and is not acceptance evidence. Rolling gates remain under
`results/gates/`; immutable accepted snapshots live under `results/gates/accepted/`.

Git Steward authorization, commit records, and generated PR summaries live under ignored `.codexteam/runtime/git-steward/<boundary>/`. The Web UI reads completed commit records but cannot create or authorize them.

Set `CODEXTEAM_PROJECTS_ROOT` or pass `--projects-root` to use another approved location. Each initialized project is an exact standalone Git root by default; `--no-git` is an explicit exception. Session and Git Steward runtime remain ignored and must not be committed.
