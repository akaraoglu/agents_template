# Tools and Environment

Use repo-native tooling first. Inspect local scripts, config files, and existing
commands before inventing new ones.

## Environment
- The guaranteed CodexTeam base folder is `/home/alik/workspace/agent_template/codexteam`.
- The toolkit virtual environment is `../env-python/`; it is not inside the CodexTeam base folder.
- Public scripts under `./scripts/` are executable wrappers and may be run directly.
- Treat `../env-python/` as generated local state, not source guidance.

## Python Commands
- Use the toolkit interpreter for repository validation:
  `../env-python/bin/python`
- Standard CodexTeam test command:
  `PYTHONDONTWRITEBYTECODE=1 ../env-python/bin/python -m pytest -q tests`
  Target `tests/` explicitly so pytest does not collect independent generated projects beneath `./projects`.
- Project initialization preview:
  `./scripts/init-project.py "Name" --goal "Goal" --projects-root ./projects --dry-run`
- Test gates:
  `./scripts/run-test-gate.py <project> --gate development --execution-surface worker`
  or the Integration Gate with its configured `worker`/`lead_host` surface; commands
  are argument arrays and integration always includes development. At acceptance, add
  `--snapshot-task <task> --snapshot-attempt <attempt>`.
- Local milestone Git:
  `./scripts/git-steward.py inspect <project> --boundary <id> --tasks <ids>`; authorization and commit preview by default and require `--apply` to write. The tool requires the project to be the exact Git root and implements no remote action.
- Subagent preview:
  `./.agents/scripts/spawn-subagent.sh --phase draft ... --dry-run`
- Execution backend:
  use only supported Codex profiles reported by `./scripts/inspect-execution-catalog.py profiles --backend codex`. OpenCode implementation and historical records are retained, but draft and feedback execution are disabled.
- Subagent continuation:
  use `--phase feedback` for revision and `--phase final` only after Project Lead acceptance; keep team, task, attempt, role, and workspace unchanged, omit all creation-time selectors, and resume only attempts carrying the current `execution-spec.json` contract.
- Role-policy inspection:
  `./scripts/inspect-role-policies.py`; each draft selects one validated role manifest and pins the full role plus skill instruction bundle and digest for the attempt.
- Subagent status:
  `./scripts/subagent-status.py <project>`; use `--active-only` for running and stale turns instead of searching global Codex sessions.
- Native-agent projection:
  `./scripts/manage-native-agents.py --check`; installation previews with `--install` and writes only with `--install --apply`.
- Existing-project guidance:
  `./scripts/sync-project-guidance.py <project>` previews managed role references; add `--apply` only after reviewing the paths.
- Prompt safety:
  prefer `--prompt-file` for Markdown or text containing backticks, dollar signs, or other shell metacharacters.
- Evidence-file safety:
  do not use shell redirection, `tee`, heredocs, or command substitution to create project evidence. Use the file-editing tool for planned files; worker turns and `close-loop.sh` capture their own diagnostics and verification output.
- Project-path continuity:
  reuse the exact initializer `Created:` path; never reconstruct a generated project ID from memory. Confirm `PROJECT.md` and the selected handoff exist before spawning.
- Nested worker boundary:
  preflight `http://127.0.0.1:11434/api/version` from the same execution surface. If reachable inside a Codex `workspace-write` Project Lead, pass `--trust-parent-sandbox` with a local profile on every turn. If host Ollama is hidden from that sandbox, launch from an approved host-level surface without the flag so the normal worker sandbox remains active. `--dry-run` does not test model connectivity, and MCP is not required; see `.agents/playbooks/nested-worker-sandbox.md`.
- Turn diagnostics:
  inspect the persisted `.stderr.txt`, `.jsonl`, and `session.json` files before deciding a failed turn needs a new attempt.
- Result verification:
  `./scripts/verify-result.py <result> --task T001 ...`
- Concise result inspection:
  `jq '{status, summary, file_changes, evidence, errors, warnings, limitations}' <result>`; do not dump captured process tails or full JSONL during routine success handling.
- Task closure:
  `./scripts/close-loop.sh <project> --task T001 -- <verification-command>`
- Lead rotation:
  `./scripts/track-lead-task.py checkpoint --project <project>` emits one compact,
  ignored resume checkpoint; it is context, not acceptance evidence.

## Working Rules
- Prefer `rg` and `rg --files` for search.
- Run the smallest relevant command first.
- Inspect real command output before making follow-up changes.
- If a quality gate cannot be run, record what was tried and why it failed.
