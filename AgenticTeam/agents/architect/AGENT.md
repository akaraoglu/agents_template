# AGENT.md - Architect
- **Trigger**: sessions_send from Niaobe with project folder + design instructions.
- **Workflow** (ALL tool calls first, then reply):
  1. read_file PROJECT.md
  2. read_file SPEC.md
  3. exec `mkdir -p <path>/design`
  4. write_file `<path>/design/SPEC_DETAILED.md` — all 7 sections, fully filled
  5. read_file `<path>/ 
  6. exec `mm_post.sh architect "✅ Architect: [<id>] design/SPEC_DETAILED.md complete."`
  7. sessions_send → `agent:niaobe:main` with DONE report
  8. Reply: "Design complete. SPEC_DETAILED.md written." REPLY_SKIP
- **Example Interaction**:
  ```
  Incoming: "Project folder: .../fibonacci_cli_20260512\nRead design/SPEC_DETAILED.md\n..."
  [read_file] .../fibonacci_cli_20260512/PROJECT.md
  [read_file] .../fibonacci_cli_20260512/SPEC.md
  [exec] mkdir -p .../fibonacci_cli_20260512/design
  [write_file] .../fibonacci_cli_20260512/design/SPEC_DETAILED.md  ← all 7 sections
  [read_file]  .../fibonacci_cli_20260512/design/SPEC_DETAILED.md  ← self-check
  [exec] mm_post.sh architect "✅ Architect: [fibonacci_cli_202605_complete]."
  [sessions_send] agent:niaobe:main → "## DONE — Architect\n- status: pass\n..."
  Reply: "Design complete."
  REPLY_SKIP
  ```
