# SKILLS.md - Niaobe
- **Post to #projects**: `bash .../scripts/mm_post.sh niaobe "<message>"`
- **Update STATE.md**: write_file with full absolute path — always update at every phase change
- **Delegate to Architect**:
  ```json
  {
    "sessionKey": "agent:architect:main",
    "message": "Project folder: <full-path>\nRead: <path>/PROJECT.md and <path>/SPEC.md\nWrite your design to: <path>/design/SPEC_DETAILED.md\nInclude: system overview, components, interfaces, data models, file structure, key decisions, open questions.\nSend DONE or BLOCKED via sessions_send to agent:niaobe:main when finished.",
    "timeoutSeconds": 0
  }
  ```
- **Delegate to Morpheus**:
  ```json
  {
    "sessionKey": "agent:morpheus:main",
    "message": "Project folder: <full-path>\nRead: PROJECT.md, SPEC.md, design/SPEC_DETAILED.md\nImplement per the design. Code → implementation/. Tests → tests/.\nSend DONE or BLOCKED via sessions_send to agent:niaobe:main when finished.",
    "timeoutSeconds": 0
  }
  ```
- **Delegate to Oracle**:
  ```json
  {
    "sessionKey": "agent:oracle:main",
    "message": "Project folder: <full-path>\nRead: PROJECT.md (acceptance criteria), SPEC.md, design/SPEC_DETAILED.md, implementation/, tests/\nRun pytest. Validate every acceptance criterion. Write VALIDATION.md.\nSend DONE (PASS or FAIL) via sessions_send to agent:niaobe:main.",
    "timeoutSeconds": 0
  }
  ```
- **Report to Smith**:
  ```json
  {
    "sessionKey": "agent:smith:main",
    "message": "## DONE — Niaobe\n- status: pass\n- project_id: <id>\n- folder: <path>\n- cycles: N\n- validation: <path>/VALIDATION.md\n- summary: <one line>",
    "timeoutSeconds": 0
  }
  ```
