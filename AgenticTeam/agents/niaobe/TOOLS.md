# Tools - Niaobe

## Receipt, reads, and state updates

```text
exec: bash /home/alik/workspace/clawspace/bin/ack_handoff.sh niaobe "<PROJECT_ID>" "TASK_HANDOFF" RECEIVED "Smith task handoff accepted."
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT_STATE.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "architect" --actor niaobe --expect-owner smith --set-owner niaobe --active-task "<TASK_ID>" --task-phase "DESIGN" --task-status "IN_PROGRESS" --note "<note>"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "morpheus" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "IMPLEMENT" --task-status "IN_PROGRESS" --note "<note>"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "oracle" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "VERIFY" --task-status "IN_PROGRESS" --note "<note>"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "IN_PROGRESS" "smith" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "TASK_DONE" --task-status "PASS" --note "<note>"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "BLOCKED" "smith" --actor niaobe --expect-owner niaobe --active-task "<TASK_ID>" --task-phase "TASK_BLOCKED" --task-status "BLOCKED" --increment-blocked --blocked-reason "<exact reason>" --note "<note>"
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" DESIGN "management/architecture/<TASK_ID>.md" --action niaobe-design-check --contains "<TASK_ID>"
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" IMPLEMENT "<artifact path reported by Morpheus>" --action niaobe-implement-check
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action niaobe-verify-check --contains "<TASK_ID>"
```

## Delegation helpers

```text
exec: bash /home/alik/workspace/clawspace/bin/handoff.sh niaobe architect "<PROJECT_ID>" "Read PROJECT.md, CURRENT_TASK.md, and management/tasks/<TASK_ID>.md. Write management/architecture/<TASK_ID>.md and report DONE or BLOCKED." DESIGN "<TASK_ID>"
exec: bash /home/alik/workspace/clawspace/bin/handoff.sh niaobe morpheus "<PROJECT_ID>" "Implement only task <TASK_ID> using CURRENT_TASK.md, management/tasks/<TASK_ID>.md, and management/architecture/<TASK_ID>.md. Report DONE or BLOCKED with exact artifact paths and test summary." IMPLEMENT "<TASK_ID>"
exec: bash /home/alik/workspace/clawspace/bin/handoff.sh niaobe oracle "<PROJECT_ID>" "Verify only task <TASK_ID>, write management/validation/<TASK_ID>_REPORT.md, and report PASS or FAIL." VERIFY "<TASK_ID>"
```

Use the exact `ENVELOPE:` value returned by `handoff.sh` for
`sessions_send` to Architect, Morpheus, or Oracle.

## sessions_send to Smith

```json
{
  "sessionKey": "agent:smith:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"task_id\":\"<TASK_ID>\",\"from\":\"niaobe\",\"to\":\"smith\",\"phase\":\"TASK_DONE|TASK_BLOCKED\",\"instructions\":\"<exact outcome>\"}"
}
```
