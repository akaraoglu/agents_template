# SKILLS.md - Neo

- **Create the canonical project**:
  `bash /home/alik/workspace/clawspace/bin/new_project.sh "<Project Title>"`
- **Seed rooted project files**:
  - `write /home/alik/workspace/clawspace/workspaces/neo/draft_PROJECT.md`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "PROJECT.md" --source-file "/home/alik/workspace/clawspace/workspaces/neo/draft_PROJECT.md" --action neo_project_write`
- **Verify seeded files**:
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"`
- **Post handoff notice**:
  `bash /home/alik/workspace/clawspace/bin/mm_post.sh neo "<message>"`
- **Prepare Smith handoff**:
  `bash /home/alik/workspace/clawspace/bin/handoff.sh neo smith "<PROJECT_ID>" "Read PROJECT.md and start sequential planning." HANDOFF`
- **Delegate to Smith**:
  use `sessions_send` with sessionKey `agent:smith:main` and the exact
  `ENVELOPE:` value returned by `handoff.sh`
- **Diagnose agent team status and stalls**:
  - `openclaw status`
  - `openclaw logs --plain --limit 200`
  - `bash /home/alik/workspace/agent_template_new/AgenticTeam/scripts/team_status.sh`
- **Run local Python diagnosis when needed**:
  `bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --module unittest -- tests/test_main.py`
  uses `/home/alik/workspace/clawspace/venv-claw` without shell activation; it
  is not final project evidence.
