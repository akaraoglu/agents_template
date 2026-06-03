# SKILLS.md - Niaobe

- **Acknowledge Smith handoff**:
  use `bash /home/alik/workspace/clawspace/bin/niaobe_run_task.sh accept '<JSON envelope>'`
  for Smith `TASK_HANDOFF`; the runtime owns ACK, reads, state movement, and
  Architect delegation. The lower-level receipt helper remains
  `bash /home/alik/workspace/clawspace/bin/ack_handoff.sh niaobe "<PROJECT_ID>" "TASK_HANDOFF" RECEIVED "Smith task handoff accepted."`
- **Handle worker results**:
  use `bash /home/alik/workspace/clawspace/bin/niaobe_run_task.sh child '<JSON envelope>'`
  for Architect `DESIGN`, Morpheus `IMPLEMENT`, and Oracle `VERIFY` result
  envelopes; the runtime owns artifact verification, state movement, next
  handoff, and exact `sessions_send` delivery
- **Read canonical project context**:
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT_STATE.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"`
- **Move canonical state**:
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "architect" --actor niaobe --expect-owner smith --set-owner niaobe --active-task "<TASK_ID>" --task-phase "DESIGN" --task-status "IN_PROGRESS" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "morpheus" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "IMPLEMENT" --task-status "IN_PROGRESS" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "oracle" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "VERIFY" --task-status "IN_PROGRESS" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "smith" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "TASK_DONE" --task-status "PASS" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "BLOCKED" "smith" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "TASK_BLOCKED" --task-status "BLOCKED" --increment-blocked --blocked-reason "<exact reason>" --note "<note>"`
- **Verify phase artifacts**:
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" DESIGN "management/architecture/<TASK_ID>.md" --action niaobe-design-check --contains "<TASK_ID>"`
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" IMPLEMENT "<artifact path reported by Morpheus>" --action niaobe-implement-check`
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action niaobe-verify-check --contains "<TASK_ID>"`
- **Prepare worker delegation**:
  - `bash /home/alik/workspace/clawspace/bin/handoff.sh niaobe architect "<PROJECT_ID>" "Read PROJECT.md, CURRENT_TASK.md, and management/tasks/<TASK_ID>.md. Write management/architecture/<TASK_ID>.md and report DONE or BLOCKED." DESIGN "<TASK_ID>"`
  - `bash /home/alik/workspace/clawspace/bin/handoff.sh niaobe morpheus "<PROJECT_ID>" "Implement only task <TASK_ID> using CURRENT_TASK.md, management/tasks/<TASK_ID>.md, and management/architecture/<TASK_ID>.md. Report DONE or BLOCKED with exact artifact paths and test summary." IMPLEMENT "<TASK_ID>"`
  - `bash /home/alik/workspace/clawspace/bin/handoff.sh niaobe oracle "<PROJECT_ID>" "Verify only task <TASK_ID>, write management/validation/<TASK_ID>_REPORT.md, and report PASS or FAIL." VERIFY "<TASK_ID>"`
- **Delegate to workers**:
  use `sessions_send` with the exact `ENVELOPE:` value returned by `handoff.sh`;
  never reconstruct the JSON or alter the returned `task_id`
- **Report to Smith**:
  use `sessions_send` with sessionKey `agent:smith:main` and a JSON envelope
  keyed by `project_id` and `task_id`
- **Timeout rule**:
  if a child phase goes stale, treat it like a worker BLOCKED event with the
  exact reason `timeout waiting for <agent>`
- **Run local Python diagnosis when needed**:
  `bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --module unittest -- tests/test_main.py`
  uses `/home/alik/workspace/clawspace/venv-claw` without shell activation; it
  is not final project evidence.
