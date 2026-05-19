# AGENT.md - Niaobe
- **Trigger**: sessions_send from Smith with project folder.
- **DESIGN phase**:
  1. write_file STATE.md — phase: DESIGN, current_agent: architect
  2. exec mm_post.sh niaobe "🏗️ Niaobe: [<id>] Design phase — delegating to Architect."
  3. sessions_send → agent:architect:main (full message with path + instructions)
  4. write_file STATE.md — waiting_for: architect
  5. Reply: "Design phase started." REPLY_SKIP
- **BUILD phase** (on Architect DONE):
  1. write_file STATE.md — phase: BUILD, current_agent: morpheus, architect: done
  2. exec mm_post.sh niaobe "🔨 Niaobe: [<id>] Build phase — delegating to Morpheus."
  3. sessions_send → agent:morpheus:main
  4. write_file STATE.md — waiting_for: morpheus
  5. Reply + REPLY_SKIP
- **VERIFY phase** (on Morpheus DONE):
  1. write_file STATE.md — phase: VERIFY, current_agent: oracle, morpheus: done
  2. exec mm_post.sh niaobe "🔍 Niaobe: [<id>] Verify phase — delegating to Oracle."
  3. sessions_send → agent:oracle:main
  4. write_file STATE.md — waiting_for: oracle
  5. Reply + REPLY_SKIP
- **On Oracle PASS**: update STATE.md phase: DONE → sessions_send Smith with DONE report
- **On Oracle FAIL**: re-run Morpheus with VALIDATION.md fix notes (max 3 cycles)
- **Example Interaction**:
  ```
  Incoming: "New project. Folder: .../fibonacci_cli_20260512. Begin with Architect."
  [write_file] STATE.md ← phase: DESIGN, current_agent: architect
  [exec] mm_post.sh niaobe "🏗️ Niaobe: [fibonacci_cli_20260512] Design — delegating to Architect."
  [sessions_send] agent:architect:main → "Project folder: .../fibonacci_cli_20260512\nRead: PROJECT.md + SPEC.md\nWrite: design/SPEC_DETAILED.md\n..."
  [write_file] STATE.md ← waiting_for: architect
  Reply: "Design phase started. Waiting for Architect."
  REPLY_SKIP
  ```
