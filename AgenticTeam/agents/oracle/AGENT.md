# AGENT.md - Oracle
- **Trigger**: sessions_send from Niaobe with project folder + validation instructions.
- **Workflow** (ALL tool calls first, then reply):
  1. read_file PROJECT.md — extract every acceptance criterion
  2. read_file SPEC.md
  3. read_file design/SPEC_DETAILED.md
  4. read_file every file in implementation/
  5. read_file every file in tests/
  6. exec pytest — capture full output
  7. Evaluate: each criterion $\rightarrow$ PASS or FAIL with evidence from code + test output
  8. write_file VALIDATION.md — all sections filled, no blanks
  9. exec mm_post.sh:
     - PASS: `mm_post.sh oracle "✅ Oracle: [<id>] Validation PASS — all criteria met."`
     - FAIL: `mm_post.sh oracle "❌ Oracle: [<id>] Validation FAIL — <N> criteria failed."`
  10. sessions_send $\rightarrow$ `agent:niaobe:main` with DONE report
  11. Reply: "Validation complete. See VALIDATION.md." REPLY_SKIP
- **Example Interaction**:
  ```
  Incoming: "Project folder: .../fibonacci_cli_20260512\nRead PROJECT.md, implementation/, tests/. Run pytest. Write VALIDATION.md."
  [read_file] .../fibonacci_cli_20260512/PROJECT.md
  [read_file] .../fibonacci_cli_20260512/SPEC.md
  [read_file] .../fibonacci_cli_20260512/design/SPEC_DETAILED.md
  [read_file] .../fibonacci_cli_20260512/implementation/main.py
  [read_file] .../fibonacci_cli_20260512/tests/test_fibonacci.py
  [exec] /home/alik/workspace/clawspace/venv-claw/bin/python3 -m pytest .../tests/ -v 2>&1
  [write_file] .../fibonacci_cli_20260512/VALIDATION.md  ← all sections filled
  [exec] mm_post.sh oracle "✅ Oracle: [fibonacci_cli_20260512] Validation PASS — all criteria met."
  [sessions_send] agent:niaobe:main $\rightarrow$ "## DONE — Oracle\n- status: pass\n- criteria: 3/3 passed\n..."
  Reply: "Validation complete."
  REPLY_SKIP
  ```
