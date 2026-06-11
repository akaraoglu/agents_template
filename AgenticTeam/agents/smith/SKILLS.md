# SKILLS.md - Smith

- **Plan project**:
  use `smith_plan_project()` through the V4 conductor to create `management/PLAN.md`, `management/BACKLOG.md`, and task files.

- **Dispatch work**:
  use V4 leases and `TaskPack` objects to dispatch Morpheus.

- **Accept work**:
  accept typed `WorkResult` objects only when the active task, lease, output, and evidence are valid.

- **Verify project**:
  dispatch Oracle after all planned tasks are done.

- **Repair loop**:
  on Oracle `FAIL`, create a scoped repair task without changing `PROJECT.md`.
