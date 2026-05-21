# SKILLS.md - Neo

- **Create the canonical project**:
  `bash /home/alik/workspace/clawspace/bin/new_project.sh "<Project Title>"`
- **Seed rooted project files**:
  - `write /home/alik/workspace/clawspace/workspaces/neo/drafts/<PROJECT_ID>/PROJECT.md`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "PROJECT.md" --source-file "/home/alik/workspace/clawspace/workspaces/neo/drafts/<PROJECT_ID>/PROJECT.md" --action neo_project_write`
- **Verify seeded files**:
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"`
- **Post handoff notice**:
  `bash /home/alik/workspace/clawspace/bin/mm_post.sh neo "<message>"`
- **Prepare Smith handoff**:
  `bash /home/alik/workspace/clawspace/bin/handoff.sh neo smith "<PROJECT_ID>" "Read PROJECT.md and start sequential planning." HANDOFF`
- **Delegate to Smith**:
  use `sessions_send` with sessionKey `agent:smith:main` and the exact
  `ENVELOPE:` value returned by `handoff.sh`
