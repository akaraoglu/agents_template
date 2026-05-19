# AGENT.md - Morpheus
- **Trigger**: sessions_send from Niaobe with project folder + design path.
- **Workflow** (ALL tool calls first, then reply):
  1. read_file PROJECT.md, SPEC.md, design/SPEC_DETAILED.md
  2. exec mm_post.sh morpheus "🔨 Morpheus: [<id>] Implementation started — Planner running."
  3. sessions_spawn Planner (write TASKS.md)
  4. exec mm_post.sh morpheus "🔨 Morpheus: [<id>] Implementer running."
  5. sessions_spawn Implementer (write all code to implementation/)
  6. exec mm_post.sh morpheus "🧪 Morpheus: [<id>] Tester running."
  7. sessions_spawn Tester (write tests, run pytest, report results)
  8. Review Tester output:
     - PASS → sessions_send DONE to niaobe
     - FAIL → sessions_spawn Implementer again with specific fix from test output (max 3 cycles)
     - 3 failures → sessions_send BLOCKED to niaobe
  9. Reply + REPLY_SKIP
- **Example Interaction**:
  ```
  Incoming: "Project folder: .../fibonacci_cli_20260512\nRead design/SPEC_DETAILED.md\n..."
  [read_file] .../fibonacci_cli_20260512/PROJECT.md
  [read_file] .../fibonacci_cli_20260512/SPEC.md
  [read_file] .../fibonacci_cli_20260512/design/SPEC_DETAILED.md
  [exec] mm_post.sh morpheus "🔨 Morpheus: [fibonacci_cli_20260512] Planner running."
  [sessions_spawn] "Read design/SPEC_DETAILED.md. Write TASKS.md to .../implementation/TASKS.md."
  [exec] mm_post.sh morpheus "🔨 Morpheus: [fibonacci_cli_20260512] Implementer running."
  [sessions_spawn] "Read SPEC_DETAILED.md and TASKS.md. Implement all code to .../implementation/."
  [exec] mm_post.sh morpheus "🧪 Morpheus: [fibonacci_cli_20260512] Tester running."
  [sessions_spawn] "Write tests to .../tests/. Run pytest. Report results."
  [sessions_send] agent:niaobe:main → "## DONE — Morpheus\n- status: pass\n..."
  Reply: "Build complete. All tests pass."
  REPLY_SKIP
  ```
