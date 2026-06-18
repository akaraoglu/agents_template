# Decisions Memory

## Purpose
Record durable project decisions, conventions, and tradeoffs that should influence future work.

## Entries
- CodexTeam project initialization should be template-backed. The default template lives at `codexteam/templates/project_user/`, follows the V4 test-project process surface with four sequential task envelopes, and can be replaced with a mounted external template through `CODEXTEAM_PROJECT_TEMPLATE`; the leader should use `initialize_project_management_docs` instead of generating long Markdown through model JSON.
- CodexTeam's MVP acceptance path is the real-life project E2E: leader clarification, approval-gated project initiation, approval-gated implementation start, T001-T004 task execution, generated project tests, board visibility, and delivery artifacts before MCP/HTTP work.
- Real worker proof should use `run_real_worker_project_e2e.py --worker-provider ollama-files` for now. The local model generates file artifacts and CodexTeam applies them through controller APIs; the `codex-exec` provider is not reliable in this environment due an unsupported tool-call failure.
- Project editing should use one flexible `propose_project_edit` tool with full-file replacements and stored confirmation, not many detail-specific tools. Runtime still denies unsafe paths and applies through `ProjectManager`.
- CodexTeam leader capability should move into project-local `AGENTS.md`, reusable `.codexteam/skills/*.md`, and explicit task handoff files instead of adding micro-tools for every project detail. Each task handed to the team must carry context, allowed paths, outputs, verification, evidence, and stop conditions.
- For bad Markdown/doc edits, prefer instruction-first discipline before adding structured section-editing tools. Agents should use `project-doc-map.md` and `document-editing.md`, read files before editing, preserve existing structure, and make minimal targeted changes.
- Use split model defaults: `gemma4:26b` for the conversational leader by default, `gemma4:12b` for workers and tests by default. Keep exact model tags explicit and do not rely on untagged `gemma4-26b`.
- The real leader proof path is now a project-sandbox Codex runtime, not the older JSON-loop conversational wrapper. It runs inside the active project root with `workspace-write`, follows project-local skills, and reports changed files/evidence back to the controller.
- When `talk_to_leader.py` routes a project request into the real project runtime, it should pass recent conversation turns into the runtime prompt and convert runtime failures into normal operator-facing replies instead of crashing the CLI.
- `talk_to_leader.py` should own the visible conversation transcript across both routing paths. Recent turn history must remain consistent whether a request is answered by the older controller-chat path or the real project runtime path.
- The front-CLI runtime classifier must be narrow for controller commands and broad for project understanding. Explicit board/operator commands stay on the controller path, but natural project reads like “show me the brief” should go to the real project runtime.
- When the real project runtime fails for a project-scoped request, `talk_to_leader.py` should attempt the older controller-chat path as a safe fallback before surfacing a hard failure.
