# Public Contracts

## Compatibility Policy

- Task IDs are uppercase `T` plus 3-6 digits.
- Contract version `1.0` fields cannot be removed or renamed without a version change.
- Optional fields may be added only when existing consumers remain valid.
- CLI exit codes and dry-run behavior are public operator contracts.

## Handoff V1

Machine-readable schema: `schemas/handoff-v1.json`.

Required scope includes handoff ID, team ID, task ID, attempt ID, role, profile, workspace, task context, constraints, and completion criteria.

`role_policy` is an optional backward-compatible v1 object containing a namespaced policy name, schema version, and lowercase SHA-256 digest. New launcher handoffs always include it; legacy handoffs remain valid.

`instruction_bundle` is an optional backward-compatible v1 object containing the SHA-256 digest and ordered filenames for the complete role/skill bundle. New drafts snapshot that bundle; continuations reject missing, altered, or mismatched pinned guidance.

## Role Policy V1

Machine-readable schema: `schemas/role-policy-v1.json`. Canonical TOML manifests live under `roles/` and reject unknown fields. The optional `mcp_servers` array is a role-specific allowlist; omission means no MCP access and remains digest-compatible with older v1 snapshots. The launcher pins the normalized policy plus digest per attempt, explicitly disables configured servers outside that allowlist for each worker process, and reports allowed, effective, and missing names. Policy defaults may change for a future draft but cannot change an existing continuation.

Canonical wire roles are `architect`, `developer`, `documenter`, `feature_planner`, `git_steward`, `leader`, `reviewer`, `tester`, and `ux_designer`. Feature Planner uses `feature_planner`; the user-facing Test Engineer retains `tester` for result compatibility, Local Git Steward uses `git_steward`, and UX Designer uses `ux_designer`.

## Gate Record V1

Machine-readable schema: `schemas/gate-record-v1.json`. The shell-free gate runner records command results, verification-path manifests, workspace digest, and timestamps under `results/gates/`. Integration always runs Development first.

## Local Commit Contracts V1

Machine-readable schemas are `schemas/commit-plan-v1.json`, `schemas/commit-authorization-v1.json`, and `schemas/commit-record-v1.json`. Plans and authorization pin the exact Git root, named branch, expected HEAD, approved literal paths, task IDs, and current evidence. Commit records describe one completed local commit. No contract grants remote authority.

## Result V1

Machine-readable schema: `schemas/result-v1.json`.

The Python validator performs additional semantic checks for canonical IDs, UTC timestamps, bounded summaries, relative paths, evidence requirements, and copied template content.

## Command Exit Codes

- `local-docs-index.py`: `0` valid preview/update/current verification; `1` index content is stale; `2` invalid manifest, source, index, or unsafe path.
- `init-project.py`: `0` success; `2` invalid input or unsafe path.
- `update-tasks.py`: `0` success/no change; `2` invalid ledger or update.
- `verify-result.py`: `0` valid; `1` invalid JSON/contract; `2` expectation mismatch.
- `inspect-role-policies.py`: `0` valid; `2` missing or invalid role policy.
- `manage-native-agents.py`: `0` current/preview/applied; `1` stale with `--check`; `2` invalid policy or unsafe collision.
- `subagent-status.py`: `0` status read; `2` invalid project path.
- `sync-project-guidance.py`: `0` current/preview/applied; `1` stale with `--check`; `2` invalid project or unsafe collision.
- `run-test-gate.py`: `0` passed/current or valid dry run; `1` configured command failed; `2` invalid configuration, stale record, or unsafe path.
- `git-steward.py`: `0` valid inspection/preview/applied boundary; `2` invalid plan, stale evidence, repository mismatch, unsafe Git state, or failed commit verification.
- `spawn-subagent.sh`: `0` draft ready or valid final result; `1` failed/correction needed; `2` invalid invocation or session scope; `3` interrupted by timeout or opt-in Run Guard with session retained when possible.
- `close-loop.sh`: `0` closed/already closed; `1` invalid result/artifact/state; `2` independent verification failure.

## Local Documentation MCP

`local-docs` exposes exactly `list_doc_sources`, `search_docs`, and `read_doc`.
All three are read-only, idempotent, offline, and bounded. Search results return
only indexed excerpts plus exact source IDs and locators; `read_doc` accepts no
filesystem path. The manifest and ignored SQLite index use schema version `1`.
Index updates remain a separate preview-first CLI operation and are not MCP
tools.

## Mutation Rule

Workers may write handoff-scoped project files during draft and feedback turns. Their conversation artifacts remain under ignored session storage, and those phases never write `results/<task>-<attempt>.json`. An accepted final turn writes that one deterministic result. Only the leader closure command updates task completion and delivery state.

Git Steward model turns are read-only. `authorize` and `commit` preview unless `--apply` is explicit. The deterministic executor may write ignored authorization/runtime records, stage only approved literal paths, and create one local commit; it cannot push, merge, tag, release, publish, or open a remote PR.
