# SKILLS.md - Smith

- **Post to #projects**: `bash /home/alik/workspace/agent_template_new/AgenticTeam/scripts/mm_post.sh smith "<message>"`
- **Read project files**: read_file with full absolute paths only
- **Write management files**: write_file STATE.md, BRIEF.md, project notes — never code

- **Delegate to Niaobe** — use sessions_send exactly as shown:
  ```json
  {
    "sessionKey": "agent:niaobe:main",
    "message": "New project. Folder: /home/alik/workspace/clawspace/projects/active/<id>. Read PROJECT.md + SPEC.md + STATE.md. Begin with Architect for design. Send me a DONE or BLOCKED report when the full cycle is complete.",
    "timeoutSeconds": 0
  }
  ```

- **Report DONE to Neo** — use sessions_send exactly as shown:
  ```json
  {
    "sessionKey": "agent:neo:main",
    "message": "Project <id> complete. DONE.md at /home/alik/workspace/clawspace/projects/active/<id>/DONE.md.",
    "timeoutSeconds": 0
  }
  ```

- **Escalate BLOCKED to Neo** — use sessions_send exactly as shown:
  ```json
  {
    "sessionKey": "agent:neo:main",
    "message": "Project <id> BLOCKED after 2 Niaobe failures. Reason: <reason>. Needs: <what is needed>.",
    "timeoutSeconds": 0
  }
  ```

## Session Keys
| Direction | Agent | sessionKey |
|---|---|---|
| Report up to | Neo | `agent:neo:main` |
| Delegate to | Niaobe | `agent:niaobe:main` |

## NEVER use sessions_spawn
sessions_spawn creates a throwaway anonymous agent. Niaobe is a named persistent agent.
Always use sessions_send with sessionKey `agent:niaobe:main`.
