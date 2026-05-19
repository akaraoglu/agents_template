# SKILLS.md - Neo
- **Project creation**: `bash /home/alik/workspace/agent_template_new/AgenticTeam/scripts/new_project.sh "<title>"`
  - Creates: timestamped slug folder, PROJECT.md template, SPEC.md template, STATE.md, design/, implementation/, tests/
  - Output: prints the full project path — capture this for all subsequent steps
- **Post to #projects**: `bash /home/alik/workspace/agent_template_new/AgenticTeam/scripts/mm_post.sh neo "<message>"`
- **Read files**: read PROJECT.md, SPEC.md after writing — self-check before delegating
- **Delegate to Smith**: `sessions_send` with sessionKey `agent:smith:main`
  ```json
  {
    "sessionKey": "agent:smith:main",
    "message": "New project ready. Folder: /home/alik/workspace/clawspace/projects/active/<id>. Read PROJECT.md and SPEC.md to begin.",
    "timeoutSeconds": 0
  }
  ```
- **Control tools** (only when Master asks):
  - List projects: `bash .../scripts/list_projects.sh`
  - Team status: `bash .../scripts/team_status.sh`
  - Stop stuck agent: `bash .../scripts/stop_agent.sh <agent>`
