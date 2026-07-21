# Runtime Layout

The default projects root for a cold-start Project Lead is `/home/alik/workspace/agent_template/codexteam/projects`.

```text
/home/alik/workspace/agent_template/codexteam/projects/<project-id>/
  AGENTS.md
  PROJECT.md
  BRIEF.md
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
  .codexteam/runtime/          # ignored persistent sessions and conversation turns
  management/
    PLAN.md
    BACKLOG.md
    tasks/T001.md ... T004.md
  src/
  tests/
  results/
```

Each logical task attempt stores a private Codex home, exact thread ID, replayable model settings, and turn artifacts under `.codexteam/runtime/sessions/<team>/<task>/<attempt>/`. Every turn persists `<turn>.jsonl`, `<turn>.txt`, and `<turn>.stderr.txt`; `session.json` records the stable scope and turn count. The generated `.gitignore` excludes this directory. Final results remain under `results/`.

Set `CODEXTEAM_PROJECTS_ROOT` or pass `--projects-root` to use another approved location. Cold-start leads pass `--projects-root ./projects`; generated project directories and their session runtime remain ignored and must not be committed.
