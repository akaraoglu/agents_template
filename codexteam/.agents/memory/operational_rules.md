# CodexTeam Operational Rules

## Source and Runtime

- Start the root Project Lead in `/home/alik/workspace/agent_template/codexteam`; root `AGENTS.md` supplies the cold-start role and phase router.
- Initialize managed projects beneath `./projects` from that base folder.
- Current source and guidance live under `codexteam/`.
- Historical archives are obsolete and must not be used as implementation inputs.
- Cold-start generated projects live under `/home/alik/workspace/agent_template/codexteam/projects` (`./projects` from the guaranteed base folder).
- `CODEXTEAM_PROJECTS_ROOT` may select another explicitly approved root.

## Execution

- Preview project initialization and subagent spawning before live execution.
- Use `qwen36-27b` as the default tool-using profile for implementation, testing, review, and documentation. Use `gemma4-26b` only for a bounded secondary perspective after confirming the task does not depend on unsupported editing behavior.
- Use canonical uppercase task IDs.
- Never evaluate agent-produced shell text.
- Keep ordinary draft revisions in the exact responsible AI session and logical attempt.
- Use `draft`, `feedback`, and `final` phases; only `final` normally writes a result record.
- Keep draft evidence away from reserved `results/<TASK>-<attempt>.json` and `results/<TASK>-verification.txt` paths.
- OpenAI profiles reuse the authenticated source Codex home and private attempt SQLite state; never copy `auth.json` into a project workspace.
- Use literal prompt files for Markdown-rich handoffs and feedback; do not expose prompt text to shell substitution.
- Keep guidance role-specific and compact; communicate one consolidated correction per review round.
- Do not create one-off Python writers, patch files, or scratch files to compensate for an ordinary communication or editing failure.
- Keep one stable lead prompt file per task attempt under the project's ignored runtime directory; do not reconstruct similar temporary paths.
- Use phase-boundary status communication and bounded context. Do not narrate every poll or reopen full result/event output after concise validation succeeds.

## Completion

- Worker output is untrusted.
- Validate result contract v1 and declared artifacts.
- Before final result persistence, require every declared created or modified path and evidence artifact reference to exist and every declared deleted path to be absent. Keep boundary failures resumable in the same session.
- Run independent verification.
- Advance task and project state only through `close-loop.sh`.
- Update the one-page `BRIEF.md` at task and milestone transitions so it matches verified truth.
- When assigning work, synchronize `TASKS.md` and `CURRENT_TASK.md` status before handoff.
- After final closure, synchronize project-specific milestone and implementation-plan narrative with canonical delivered state.
- Before delivery, compare nontrivial exact product output with the approved convention and inspect the file manifest for scratch or incomplete artifacts.
- A Reviewer may claim only what the content of the named accepted evidence actually records.
