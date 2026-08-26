# CodexTeam Context MCP Skill

## Purpose

Give the Project Lead and selected worker roles bounded, structured, read-only
CodexTeam context without repeated repository scans, full result dumps, or
large shell-output cycles.

## When To Use

Use when the Project Lead needs current state from an initialized project:
orientation, task selection, handoff preparation, attempt review, gate review,
result validation, cost diagnosis, memory lookup, repository search, or change
triage. Developer, Test Engineer, Reviewer, and Git Steward use only the
server-specific tool subset pinned by their role policy.

Do not load this skill for an uninitialized new-project proposal. Do not use the
MCP tools to infer that a mutation, test, or acceptance check occurred.

## Inputs Needed

- Exact control directory name under `/home/alik/workspace/codexspace/projects`
  for an unbound Project Lead call;
  worker servers are already bound and do not accept this argument
- The decision being made
- Task ID, attempt ID, role, query, or filter only when required
- Canonical artifact path when a returned summary identifies evidence to inspect

## Workflow

1. The Project Lead discovers `codexteam-context` once when its tools are not
   already visible. A worker uses its launcher-provided subset directly.
2. Call the smallest tool that answers the current question:

| Need | Tool |
|---|---|
| Current focus and active attempts | `get_active_task` |
| Progress, attention items, gates, and Git state | `get_project_overview` |
| Bounded filtered ledger rows | `list_tasks` |
| One canonical handoff | `get_task_handoff` |
| Handoff, dependencies, role boundary, concurrent work, and gates | `get_task_context` |
| Attempt state, bounded turns, token deltas, and result fields | `get_attempt_summary` |
| Development and Integration Gate configuration and freshness | `get_gate_status` |
| Result identity, contract, and referenced evidence | `validate_result_record` |
| Expensive turns and tool-cycle indicators | `get_cost_hotspots` |
| Control-root discoveries, project decisions, and configured team memory | `search_team_memory` (`scope=discoveries|project|team|all`) |
| Ranked bounded source matches | `search_repository` |
| Git status, diff statistics, suspicious paths, and bounded excerpts | `get_change_summary` |

Worker routing is narrower:

| Role | Tools |
|---|---|
| Developer | `get_task_context`, `search_repository`, `get_gate_status`, `get_change_summary` |
| Test Engineer | `get_task_context`, `get_change_summary`, `get_gate_status` |
| Reviewer | `get_task_context`, `get_attempt_summary`, `validate_result_record`, `get_gate_status`, `get_change_summary` |
| Git Steward | `get_task_context`, `get_change_summary`, `get_gate_status` |

The launcher derives each new worker attempt's project from the exact workspace,
binds the MCP process to it, and removes `project` from every worker tool schema.
Do not discover, guess, or supply a project value in a worker call. The Project
Lead remains unbound so it can inspect more than one initialized project.

Before substantial source investigation, the Lead calls `search_team_memory`
with `scope=discoveries` and task-specific terms. Discovery notes are advisory
control research, distinct from accepted `ARCHITECTURE.md`/`docs/architecture/`
and source-owned product architecture. In split-root work, workers receive a
bounded excerpt and exact verification targets through the handoff.

For workers, context is heavy when a handoff points to multiple upstream
artifacts, leaves dependencies or paths uncertain, needs shared-worktree
triage, or requires repository-wide symbol discovery. Use one routed MCP call
in those cases. A list of filenames is not sufficient precision when the
worker would still read several complete artifacts. Skip MCP when the handoff
names sufficient exact headings, symbols, or short source ranges for a smaller
direct read. After a sufficient response, inspect returned exact paths rather
than repeating the same discovery with broad shell output.

3. Chain another MCP call only when the first result exposes a specific missing
   dependency. Do not call the full tool set as a routine preflight.
4. Respect truncation, freshness, and `query_stats`. Open only a named source or
   artifact when the Lead must inspect exact content.
5. Use canonical CodexTeam commands for every mutation and for captured
   verification evidence. A read-only MCP response is context, not proof that a
   gate or product check passed.
6. If a tool is unavailable or returns an error, retry once only when input or
   relevant state changed. Otherwise use the narrow existing command or file
   read and record the fallback reason.
7. Reuse the resulting facts in worker handoffs and review. Do not make a worker
   rediscover accepted context.
8. Read cost hotspot `usage_totals` by scope. `worker_turns` comes from worker
   sidecars, `lead_orchestration` comes from Lead rollout metrics, and `combined` is
   their sum; do not attribute the combined number to either layer alone.

## Commands To Run

MCP calls use the Codex tool interface and require no shell command. When tool
discovery fails, diagnose registration once:

```bash
codex mcp get codexteam-context
```

The registered server entry point is `scripts/team-context-mcp.py`. Do not start
a second server manually during a normal Lead turn.

## Expected Output

- Bounded structured fields tied to the exact project, task, or attempt
- Source paths or evidence references when deeper inspection is needed
- `query_stats` describing duration, returned bytes, source bytes, and cache use
- No repository mutation

## Validation

- Returned identity matches the requested project, task, attempt, and role. For a
  worker, the bound project matches the launcher handoff without a call argument.
- Truncation or stale evidence is visible before a decision is made.
- No role claims tests, acceptance, closure, or Git authorization from context alone.
- A sufficient MCP result is not followed by a broad duplicate shell scan.
- Failures use one narrow fallback rather than repeated unchanged calls.

## Common Mistakes Or Failure Modes

- Calling every context tool at each phase boundary
- Repeating MCP results with `find`, broad `rg`, full JSONL, or full result dumps
- Treating a summary or fresh-looking gate record as independent verification
- Using repository search when the handoff already names a sufficient exact section or symbol
- Treating several named whole files as bounded context
- Searching for role guidance already injected into the attempt bundle
- Retrying an unchanged failed call
- Passing an absolute workspace path or any `project` argument to a bound worker tool
- Expecting an already-running Codex process to reload newly registered servers
- Asking a worker to repeat context already accepted by the Project Lead

## Related Files

- `.agents/skills/project-lead.md`
- `.agents/skills/subagent-orchestration.md`
- `.agents/skills/verification.md`
- `scripts/team-context-mcp.py`
- `src/codexteam_tools/context_mcp.py`
