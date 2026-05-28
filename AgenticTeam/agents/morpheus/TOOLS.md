# Tools - Morpheus

You have standard tools (`read`, `write`, `exec`) to manipulate the workspace and run CLI scripts.

## 1. Workspace Preparation
To set up state and extract variables, run:
```text
exec: bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh prepare '<ENVELOPE_JSON>'
```
Extract and copy the printed paths exactly:
- `DRAFT_WRITE_ROOT`: Base directory where drafts must be written.
- `MANIFEST_WRITE_FILE`: Target path for writing `manifest.json`.
- `RUN_DIR`: Path to the active run state folder.

## 2. Writing Artifacts
Write all implementation draft files under `<DRAFT_WRITE_ROOT>/<relative_path>`.
Write `manifest.json` inside `<DRAFT_WRITE_ROOT>/manifest.json` containing:
```json
{
  "artifacts": [
    {"path": "README.md"},
    {"path": "src/main.py"},
    {"path": "tests/test_main.py"}
  ],
  "test_command": ["python3", "-m", "unittest", "tests/test_main.py"]
}
```

## 3. Local Test Verification
Use the `exec` tool to run the project tests locally:
```text
exec: python3 -m unittest tests/test_main.py
```
Observe the traceback. If there are failures, edit your files under `<DRAFT_WRITE_ROOT>` and rerun tests until they pass.

## 4. Git-Driven Handoff
Once tests are green, commit your milestone and transition the project by running:
```text
exec: python3 /home/alik/workspace/agent_template_new/AgenticTeam/scripts/handoff.py --run-dir "<RUN_DIR>" --target oracle --summary "<natural language summary>" --artifacts "README.md,src/main.py,tests/test_main.py"
```

## 5. Human Clarification Escalation
If you need user feedback on a design decision or requirement, run:
```text
exec: python3 /home/alik/workspace/agent_template_new/AgenticTeam/scripts/ask_user.py --question "<your question>" --options "Option A, Option B"
```
The console output will display the user's choice or custom answer.

## 6. Project Blocking
If the task is completely blocked by invalid/missing inputs, run the printed `BLOCK_COMMAND` exactly.
