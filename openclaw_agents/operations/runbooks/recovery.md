# Recovery

Use this runbook when a project cannot resume cleanly after pause, force interrupt, lease expiry, or workspace inconsistency.

## Typical Triggers

- `missing_snapshot`
- `missing_workspace_ref`
- `missing_workspace_state`
- `workspace_path_missing`
- `repo_root_missing`
- `workspace_outside_repo_root`
- `workspace_git_root_mismatch`
- `workspace_branch_or_worktree_mismatch`
- `workspace_dirty_tracked_files`
- `workspace_has_untracked_files`
- `workspace_checkpoint_reference_missing`
- `workspace_marked_inconsistent`
- `missing_workspace_checkpoint`
- `active_orchestrator_lease_present`
- `active_task_attempts_present`
- `active_agent_runs_present`

## 1. Inspect The Current State

```bash
python3 - <<'PY'
from openclaw_agents.database.store import ControlPlaneStore

store = ControlPlaneStore()
project_id = "replace_me"
print("project:", store.get_project(project_id))
print("schedule:", store.get_scheduling_record(project_id))
print("snapshot:", store.get_latest_snapshot(project_id))
print("niobe lease:", store.get_lease("niobe"))
print("morpheus lease:", store.get_lease("morpheus"))
PY
```

## 2. Run Resume Assessment

```bash
python3 - <<'PY'
from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.scheduler.recovery_manager import RecoveryManager

store = ControlPlaneStore()
project_id = "replace_me"
print(RecoveryManager(store).assess_resume(project_id, orchestrator_id="niobe"))
PY
```

If this returns `ok=False`, the project should stay blocked until the reported issues are fixed.

## 3. Validate The Workspace Directly

```bash
python3 - <<'PY'
from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.scheduler.workspace_validator import WorkspaceValidator

store = ControlPlaneStore()
project_id = "replace_me"
print(WorkspaceValidator(store).validate_project(project_id))
PY
```

## 4. Common Repairs

- If `repo_root_missing` or `workspace_path_missing`, recreate the workspace or fix the stored path before resuming.
- If `workspace_outside_repo_root` or `workspace_git_root_mismatch`, fix the stored `repo_root` and `workspace_ref` pair so they point at the real git workspace.
- If `workspace_branch_or_worktree_mismatch`, switch back to the recorded branch or correct `workspace_states.branch_or_worktree_id` if the workspace was intentionally moved.
- If `workspace_dirty_tracked_files`, inspect `git status`, either commit or discard the partial mutation, and rerun validation before resuming.
- If `workspace_has_untracked_files`, either move the files into tracked/generated paths or clean them up before resuming.
- If `workspace_checkpoint_reference_missing`, replace `workspace_states.last_clean_commit_or_checkpoint` with a real commit, branch, or other valid checkpoint identifier.
- If `missing_workspace_checkpoint`, update `workspace_states.last_clean_commit_or_checkpoint` with a real commit or named checkpoint.
- If `workspace_marked_inconsistent`, repair the workspace first. That may mean checkout, worktree rebuild, patch replay, or sandbox rebuild.
- If the latest snapshot is missing, do not resume the project normally. Create a new safe snapshot only after you understand the current project state.
- If `active_orchestrator_lease_present`, `active_task_attempts_present`, or `active_agent_runs_present`, confirm the old run is truly dead before releasing leases or resuming work.

## 5. Stale Or Broken Lease Handling

Only release or expire a lease after confirming no real run still owns the project.

```bash
python3 - <<'PY'
from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.scheduler.lease_manager import LeaseManager

store = ControlPlaneStore()
lease_manager = LeaseManager(store)
print(lease_manager.expire_stale_leases())
PY
```

If you must release a known stale lease manually:

```bash
python3 - <<'PY'
from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.scheduler.lease_manager import LeaseManager

store = ControlPlaneStore()
lease_manager = LeaseManager(store)
print(lease_manager.release("niobe", release_reason="operator-recovery"))
PY
```

Use manual release sparingly. It is safer to expire only genuinely stale leases than to free an active project accidentally.

## 6. Re-Validate Before Resume

After repairs, rerun:

- workspace validation
- recovery assessment
- scheduler queue inspection

The project should not be resumed until all three are clean.
