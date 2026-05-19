# SKILLS.md - Oracle
- **Read all project files**:
  - read_file PROJECT.md — extract every acceptance criterion
  - read_file SPEC.md, design/SPEC_DETAILED.md — intended architecture
  - read_file all files in implementation/ — code exists and matches design
  - read_file all files in tests/ — tests exist and cover requirements
- **Run tests**:
  ```bash
  /home/alik/workspace/clawspace/venv-claw/bin/python3 -m pytest <full-path>/tests/ -v 2>&1
  ```
- **Write VALIDATION.md**: write_file `<path>/VALIDATION.md`
  ```
  ## Validation — <project-id>
  - overall: pass | fail | partial
  - criteria_checked: N/N
  - test_run: pass | fail, N/N tests

  ## Criterion Results
  - [PASS/FAIL] <criterion>: <evidence>

  ## Issues
  <each failure: file, line, specific problem>

  ## Recommendations
  <what Morpheus should fix>
  ```
- **Post to #projects**: `bash .../scripts/mm_post.sh oracle "<message>"`
- **Report to Niaobe**: sessions_send → agent:niaobe:main
  ```json
  {
    "sessionKey": "agent:niaobe:main",
    "message": "## DONE — Oracle\n- status: pass|fail|partial\n- output: <path>/VALIDATION.md\n- criteria: N/N passed\n- test_run: pass|fail, N/N tests\n- summary: <one line>\n- failing_criteria: <list or none>",
    "timeoutSeconds": 0
  }
  ```
