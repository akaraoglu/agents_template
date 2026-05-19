# SKILLS.md - Morpheus
- **Read design**: read_file PROJECT.md, SPEC.md, design/SPEC_DETAILED.md
- **Post to #projects**: `bash .../scripts/mm_post.sh morpheus "<message>"`
- **Spawn Planner** (sessions_spawn):
  ```
  Read <path>/design/SPEC_DETAILED.md.
  Write a detailed coding task list to <path>/implementation/TASKS.md.
  List every file to create and every function to implement, with signatures.
  Report back when done.
  ```
- **Spawn Implementer** (sessions_spawn):
  ```
  Read <path>/design/SPEC_DETAILED.md and <path>/implementation/TASKS.md.
  Implement all tasks. Write all code files to <path>/implementation/ using full absolute paths.
  Python binary: /home/alik/workspace/clawspace/venv-claw/bin/python3
  Report back with a list of every file created.
  ```
- **Spawn Tester** (sessions_spawn):
  ```
  Write tests to <path>/tests/ based on acceptance criteria in PROJECT.md.
  Run: /home/alik/workspace/clawspace/venv-claw/bin/python3 -m pytest <path>/tests/ -v 2>&1
  Report full test output and pass/fail status.
  ```
- **Report DONE to Niaobe**: sessions_send → agent:niaobe:main
  ```
  ## DONE — Morpheus
  - status: pass
  - files_created: [full paths list]
  - test_result: pass, N/N tests
  - cycles: N
  - notes: <anything Oracle should know>
  ```
