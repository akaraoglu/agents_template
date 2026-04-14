"""Render human-readable workspace management files from control-plane state."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.runtime.artifact_parsers import ArtifactParser

NON_TERMINAL_TASK_STATUSES = {"PENDING", "RUNNING"}
TERMINAL_TASK_STATUSES = {"SUCCESS", "BLOCKED", "FAILED", "CANCELLED", "NEEDS_CLARIFICATION"}


class WorkspaceManagementWriter:
    """Project management projection for a single workspace."""

    _PROJECT_ARTIFACT_TYPES = (
        "project_charter",
        "project_delivery_plan",
        "architecture_spec",
        "software_task_plan",
        "code_change",
        "test_execution_report",
        "software_delivery_package",
        "verification_report",
        "project_status_report",
        "project_closure_report",
        "escalation_packet",
    )

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        artifact_parser: ArtifactParser | None = None,
        template_root: str | Path | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        self.artifact_parser = artifact_parser or ArtifactParser(self.store)
        base = Path(__file__).resolve().parents[1]
        self.template_root = Path(template_root or (base / "templates" / "project_workspace")).resolve()

    @staticmethod
    def _compact(value: Any, *, limit: int = 120) -> str:
        text = str(value or "").replace("\n", " ").strip()
        text = " ".join(text.split())
        if not text:
            return "[none]"
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3]}..."

    @staticmethod
    def _short_id(value: str | None) -> str:
        if not value:
            return "[none]"
        if len(value) <= 18:
            return value
        return value[:18]

    @staticmethod
    def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
        if not rows:
            rows = [["[none]" for _ in headers]]
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join("---" for _ in headers) + " |"
        body_rows = ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join([header_row, separator_row, *body_rows])

    @staticmethod
    def _bullet_lines(items: list[str], *, placeholder: str = "[none]") -> str:
        if not items:
            return f"- `{placeholder}`"
        return "\n".join(f"- {item}" for item in items)

    def _ensure_scaffold(self, workspace_path: Path) -> None:
        workspace_path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template_root, workspace_path, dirs_exist_ok=True)

    def _latest_artifact(
        self,
        artifact_records: list[dict[str, Any]],
        *,
        artifact_type: str,
    ) -> tuple[dict[str, Any] | None, Any]:
        for record in reversed(artifact_records):
            if record.get("artifact_type") != artifact_type:
                continue
            try:
                payload = self.artifact_parser.parse_record(record)
            except FileNotFoundError:
                continue
            return record, payload
        return None, None

    def _artifact_name(self, record: dict[str, Any] | None) -> str:
        if not record:
            return "[none]"
        ref = str(record.get("ref") or "")
        if ref.startswith("inline://"):
            return self._short_id(record.get("artifact_id"))
        return Path(ref).name

    def _collect(self, project_id: str) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if not project or not project.get("workspace_ref"):
            raise ValueError(f"project {project_id} has no workspace_ref")
        workspace_ref = str(project["workspace_ref"])
        tasks = self.store.list_tasks_for_project(project_id)
        artifacts = self.store.list_project_artifacts(project_id)
        control_events = self.store.list_control_events(project_id)
        workspace_state = self.store.get_workspace_state(workspace_ref) or {}
        scheduling = self.store.get_scheduling_record(project_id) or {}
        feedback_thread = self.store.get_project_feedback_thread(project_id)
        latest: dict[str, tuple[dict[str, Any] | None, Any]] = {}
        for artifact_type in self._PROJECT_ARTIFACT_TYPES:
            latest[artifact_type] = self._latest_artifact(artifacts, artifact_type=artifact_type)
        return {
            "project": project,
            "workspace_ref": workspace_ref,
            "workspace_state": workspace_state,
            "scheduling": scheduling,
            "tasks": tasks,
            "artifacts": artifacts,
            "control_events": control_events,
            "feedback_thread": feedback_thread,
            "latest": latest,
        }

    def _delivery_plan_payload(self, state: dict[str, Any]) -> dict[str, Any] | None:
        _record, payload = state["latest"].get("project_delivery_plan", (None, None))
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _flatten_work_items(delivery_plan: dict[str, Any]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for milestone in delivery_plan.get("milestones") or []:
            for work_item in milestone.get("work_items") or []:
                flattened.append(
                    {
                        "milestone_id": milestone.get("milestone_id"),
                        "milestone_title": milestone.get("title"),
                        "work_item_id": work_item.get("work_item_id"),
                        "work_item_title": work_item.get("title"),
                        "goal": work_item.get("goal") or work_item.get("title"),
                        "requirements": list(work_item.get("requirements") or []),
                        "acceptance_criteria": list(work_item.get("acceptance_criteria") or []),
                    }
                )
        return flattened

    def _latest_verification_for_work_item(
        self,
        state: dict[str, Any],
        *,
        work_item_id: str,
    ) -> tuple[dict[str, Any] | None, Any]:
        for record in reversed(state["artifacts"]):
            if record.get("artifact_type") != "verification_report":
                continue
            try:
                payload = self.artifact_parser.parse_record(record)
            except FileNotFoundError:
                continue
            if isinstance(payload, dict) and payload.get("work_item_id") == work_item_id:
                return record, payload
        return None, None

    def _latest_test_for_work_item(
        self,
        state: dict[str, Any],
        *,
        work_item_id: str,
    ) -> tuple[dict[str, Any] | None, Any]:
        for record in reversed(state["artifacts"]):
            if record.get("artifact_type") != "test_execution_report":
                continue
            try:
                payload = self.artifact_parser.parse_record(record)
            except FileNotFoundError:
                continue
            if isinstance(payload, dict) and payload.get("work_item_id") == work_item_id:
                return record, payload
        return None, None

    def _tasks_for_work_item(self, state: dict[str, Any], *, work_item_id: str) -> list[dict[str, Any]]:
        return [
            task
            for task in state["tasks"]
            if (task.get("context_json") or {}).get("work_item_id") == work_item_id
        ]

    def _work_item_status(self, state: dict[str, Any], work_item: dict[str, Any]) -> tuple[str, str, str]:
        tasks = self._tasks_for_work_item(state, work_item_id=str(work_item["work_item_id"]))
        verification_record, verification_payload = self._latest_verification_for_work_item(
            state,
            work_item_id=str(work_item["work_item_id"]),
        )
        if isinstance(verification_payload, dict) and verification_payload.get("result") == "PASS":
            return "DONE", self._artifact_name(verification_record), self._compact(verification_payload.get("summary") or "verified")
        if isinstance(verification_payload, dict) and verification_payload.get("result") and verification_payload.get("result") != "PASS":
            return str(verification_payload.get("result")), self._artifact_name(verification_record), self._compact(verification_payload.get("summary") or "verification did not pass")
        blocked = next((task for task in tasks if task["status"] in {"BLOCKED", "FAILED", "NEEDS_CLARIFICATION"}), None)
        if blocked:
            return blocked["status"], self._short_id(blocked["task_id"]), self._compact(blocked["goal"])
        active = next((task for task in reversed(tasks) if task["status"] in NON_TERMINAL_TASK_STATUSES), None)
        if active:
            return "IN_PROGRESS", self._short_id(active["task_id"]), self._compact(active["goal"])
        completed = next((task for task in reversed(tasks) if task["status"] == "SUCCESS"), None)
        if completed:
            return "DELIVERED", self._short_id(completed["task_id"]), self._compact(completed["goal"])
        return "PENDING", "[none]", self._compact(work_item.get("goal"))

    def _status_summary(self, project: dict[str, Any], scheduling: dict[str, Any]) -> tuple[str, str]:
        if project["project_status"] == "DONE":
            return "no action", "Project is complete."
        if project["project_status"] == "CANCELLED":
            return "no action", "Project is cancelled."
        if scheduling.get("waiting_reason"):
            return "operator review", f"Scheduling state is waiting on `{scheduling['waiting_reason']}`."
        if project["runtime_status"] == "PAUSED":
            return "resume when ready", "Project is paused at a persisted boundary."
        if project["runtime_status"] == "WAITING_EXTERNAL":
            owner = project.get("current_owner_agent") or "[unknown]"
            return "no action", f"System is waiting on `{owner}`."
        return "no action", "Project is active in the control-plane loop."

    def _render_project_md(self, state: dict[str, Any]) -> str:
        project = state["project"]
        workspace_state = state["workspace_state"]
        feedback_thread = state["feedback_thread"]
        delivery_plan = self._delivery_plan_payload(state)
        charter_record, charter_payload = state["latest"]["project_charter"]
        architecture_record, architecture_payload = state["latest"]["architecture_spec"]
        goal = charter_payload.get("problem_statement") if isinstance(charter_payload, dict) else project["goal"]
        goals = (charter_payload.get("goals") or [project["goal"]]) if isinstance(charter_payload, dict) else [project["goal"]]
        non_goals = (charter_payload.get("non_goals") or []) if isinstance(charter_payload, dict) else []
        acceptance = (charter_payload.get("acceptance_criteria") or []) if isinstance(charter_payload, dict) else []
        constraints = []
        if isinstance(charter_payload, dict):
            constraints.extend(str(item) for item in charter_payload.get("constraints") or [])
        if isinstance(architecture_payload, dict):
            constraints.extend(str(item) for item in architecture_payload.get("constraints") or [])
        unique_constraints = list(dict.fromkeys(constraints))
        thread_text = (
            f"`{feedback_thread[0]} > {feedback_thread[1]}`"
            if feedback_thread
            else "`[not linked yet]`"
        )
        architecture_summary = (
            self._compact(architecture_payload.get("summary") or architecture_payload.get("system_shape"))
            if isinstance(architecture_payload, dict)
            else "[none yet]"
        )
        open_questions = (charter_payload.get("open_questions") or []) if isinstance(charter_payload, dict) else []
        milestone_summary = (
            f"{len(delivery_plan.get('milestones') or [])} milestone(s), {len(self._flatten_work_items(delivery_plan))} work item(s)"
            if delivery_plan
            else "[not planned yet]"
        )
        return (
            "# PROJECT\n\n"
            "This file is the workspace-level project charter and delivery contract projected from the control plane.\n\n"
            "## Identity\n\n"
            f"- Project ID: `{project['project_id']}`\n"
            f"- Priority: `{project['priority']}`\n"
            f"- Project status: `{project['project_status']}`\n"
            f"- Runtime status: `{project['runtime_status']}`\n"
            f"- Current phase: `{project['current_phase']}`\n"
            f"- Current owner agent: `{project.get('current_owner_agent') or '[none]'}`\n"
            f"- Workspace ref: `{project['workspace_ref']}`\n"
            f"- Repo root: `{workspace_state.get('repo_root') or project['workspace_ref']}`\n"
            f"- Branch or worktree id: `{workspace_state.get('branch_or_worktree_id') or Path(project['workspace_ref']).name}`\n"
            f"- Last clean commit or checkpoint: `{workspace_state.get('last_clean_commit_or_checkpoint') or '[unknown]'}`\n"
            f"- Canonical Zulip thread: {thread_text}\n\n"
            "## Summary\n\n"
            f"{goal}\n\n"
            "## Goals\n\n"
            f"{self._bullet_lines([self._compact(item, limit=160) for item in goals], placeholder='[to be framed]')}\n\n"
            "## Non-Goals\n\n"
            f"{self._bullet_lines([self._compact(item, limit=160) for item in non_goals], placeholder='[none recorded]')}\n\n"
            "## Acceptance Criteria\n\n"
            f"{self._bullet_lines([self._compact(item, limit=160) for item in acceptance], placeholder='[none recorded]')}\n\n"
            "## Constraints\n\n"
            f"{self._bullet_lines([self._compact(item, limit=160) for item in unique_constraints], placeholder='[none recorded]')}\n\n"
            "## Current Delivery Plan\n\n"
            f"- Latest charter artifact: `{self._artifact_name(charter_record)}`\n"
            f"- Latest architecture artifact: `{self._artifact_name(architecture_record)}`\n"
            f"- Delivery plan: `{milestone_summary}`\n"
            f"- Architecture summary: `{architecture_summary}`\n"
            f"- Next action: `{self._compact((project.get('next_action_json') or {}).get('type'))}`\n"
            f"- Next action reason: `{self._compact((project.get('next_action_json') or {}).get('reason'))}`\n\n"
            "## Open Questions\n\n"
            f"{self._bullet_lines([self._compact(item, limit=160) for item in open_questions], placeholder='[none recorded]')}\n"
        )

    def _render_status_md(self, state: dict[str, Any]) -> str:
        project = state["project"]
        scheduling = state["scheduling"]
        tasks = state["tasks"]
        artifacts = state["artifacts"]
        delivery_plan = self._delivery_plan_payload(state)
        next_action = project.get("next_action_json") or {}
        active_tasks = [task for task in tasks if task["status"] in NON_TERMINAL_TASK_STATUSES]
        blocked_tasks = [task for task in tasks if task["status"] in {"BLOCKED", "NEEDS_CLARIFICATION", "FAILED"}]
        recent_artifacts = list(reversed(artifacts[-5:]))
        action, reason = self._status_summary(project, scheduling)
        safe_to_pause = "yes" if scheduling.get("current_safe_boundary_type") or project["runtime_status"] in {"WAITING_EXTERNAL", "PAUSED", "BLOCKED"} else "no"
        current_work_item = None
        if delivery_plan:
            for work_item in self._flatten_work_items(delivery_plan):
                status, _evidence, _notes = self._work_item_status(state, work_item)
                if status != "DONE":
                    current_work_item = work_item
                    break
        open_task_rows = [
            [
                f"`{self._short_id(task['task_id'])}`",
                f"`{task.get('current_owner_agent') or task.get('to_agent') or '[none]'}`",
                f"`{task['task_type']}`",
                f"`{task['status']}`",
                f"`{task['return_to']}`",
                self._compact(task["goal"], limit=60),
            ]
            for task in active_tasks
        ]
        artifact_rows = [
            [
                f"`{record['artifact_type']}`",
                f"`{self._short_id(record['artifact_id'])}`",
                f"`{record.get('produced_by_agent') or '[unknown]'}`",
                f"`{self._artifact_name(record)}`",
                self._compact(record.get("ref"), limit=48),
            ]
            for record in recent_artifacts
        ]
        blocker_lines: list[str] = []
        if scheduling.get("waiting_reason"):
            blocker_lines.append(f"`waiting_reason={scheduling['waiting_reason']}`")
        for task in blocked_tasks:
            blocker_lines.append(
                f"`{task['task_type']}` by `{task.get('current_owner_agent') or task.get('to_agent')}` is `{task['status']}`"
            )
        if not blocker_lines and project["runtime_status"] == "WAITING_EXTERNAL":
            blocker_lines.append(f"Waiting on `{project.get('current_owner_agent') or '[unknown]'}`.")
        return (
            "# STATUS\n\n"
            "This file is the current operator-facing snapshot projected from the control-plane state.\n\n"
            "## Current Snapshot\n\n"
            f"- Updated at: `{utc_now()}`\n"
            f"- Project ID: `{project['project_id']}`\n"
            f"- Project status: `{project['project_status']}`\n"
            f"- Runtime status: `{project['runtime_status']}`\n"
            f"- Priority: `{project['priority']}`\n"
            f"- Current phase: `{project['current_phase']}`\n"
            f"- Current owner agent: `{project.get('current_owner_agent') or '[none]'}`\n"
            f"- Current milestone: `{current_work_item.get('milestone_id') if current_work_item else '[complete]'}`\n"
            f"- Current work item: `{current_work_item.get('work_item_title') if current_work_item else '[complete]'}`\n"
            f"- Next action: `{self._compact(next_action.get('type'))}`\n"
            f"- Next action reason: `{self._compact(next_action.get('reason'))}`\n"
            f"- Safe to pause or switch: `{safe_to_pause}`\n"
            f"- Last safe boundary type: `{scheduling.get('current_safe_boundary_type') or '[none yet]'}`\n"
            f"- Last snapshot id: `{project.get('last_snapshot_id') or '[none yet]'}`\n"
            f"- Workspace ref: `{project['workspace_ref']}`\n\n"
            "## Current Objective\n\n"
            f"{self._compact(next_action.get('reason') or project['goal'], limit=220)}\n\n"
            "## Open Tasks\n\n"
            f"{self._markdown_table(['Task ID', 'Owner', 'Task Type', 'Status', 'Return To', 'Notes'], open_task_rows)}\n\n"
            "## Recent Accepted Artifacts\n\n"
            f"{self._markdown_table(['Artifact Type', 'Artifact ID', 'Produced By', 'Location', 'Ref'], artifact_rows)}\n\n"
            "## Blockers And Waiting Reasons\n\n"
            f"{self._bullet_lines(blocker_lines, placeholder='none')}\n\n"
            "## Recommended Operator Action\n\n"
            f"- `{action}`\n"
            f"- Reason: `{reason}`\n"
        )

    def _render_backlog_md(self, state: dict[str, Any]) -> str:
        delivery_plan = self._delivery_plan_payload(state)
        if delivery_plan:
            sections: list[str] = [
                "# BACKLOG",
                "",
                "This file is the project backlog projected from the delivery plan and the live task graph.",
                "",
            ]
            for milestone in delivery_plan.get("milestones") or []:
                rows: list[list[str]] = []
                for work_item in milestone.get("work_items") or []:
                    flattened = {
                        "milestone_id": milestone.get("milestone_id"),
                        "milestone_title": milestone.get("title"),
                        "work_item_id": work_item.get("work_item_id"),
                        "work_item_title": work_item.get("title"),
                        "goal": work_item.get("goal") or work_item.get("title"),
                    }
                    status, evidence, notes = self._work_item_status(state, flattened)
                    rows.append(
                        [
                            f"`{work_item.get('work_item_id')}`",
                            f"`{status}`",
                            self._compact(work_item.get("title"), limit=48),
                            f"`{evidence}`",
                            notes,
                        ]
                    )
                sections.extend(
                    [
                        f"## {milestone.get('milestone_id')} {milestone.get('title')}",
                        "",
                        self._markdown_table(["Work Item", "Status", "Title", "Latest Evidence", "Notes"], rows),
                        "",
                    ]
                )
            return "\n".join(sections).rstrip() + "\n"
        tasks = state["tasks"]
        active = [task for task in tasks if task["status"] in NON_TERMINAL_TASK_STATUSES]
        blocked = [task for task in tasks if task["status"] in {"BLOCKED", "NEEDS_CLARIFICATION", "FAILED"}]
        completed = [task for task in tasks if task["status"] in {"SUCCESS", "CANCELLED"}][-10:]
        def _task_rows(rows: list[dict[str, Any]]) -> list[list[str]]:
            return [
                [
                    f"`{self._short_id(task['task_id'])}`",
                    f"`{self._short_id(task.get('parent_task_id'))}`",
                    f"`{task['task_type']}`",
                    f"`{task.get('current_owner_agent') or task.get('to_agent')}`",
                    f"`{task['status']}`",
                    f"`{task['opened_at']}`",
                    self._compact(task["goal"], limit=80),
                ]
                for task in rows
            ]
        return (
            "# BACKLOG\n\n"
            "This file is the project task backlog projected from the control-plane task graph.\n\n"
            "## Active Work\n\n"
            f"{self._markdown_table(['Task ID', 'Parent', 'Task Type', 'Owner', 'Status', 'Opened At', 'Goal'], _task_rows(active))}\n\n"
            "## Blocked Or Clarification Items\n\n"
            f"{self._markdown_table(['Task ID', 'Parent', 'Task Type', 'Owner', 'Status', 'Opened At', 'Goal'], _task_rows(blocked))}\n\n"
            "## Recently Completed\n\n"
            f"{self._markdown_table(['Task ID', 'Parent', 'Task Type', 'Owner', 'Status', 'Opened At', 'Goal'], _task_rows(list(reversed(completed))))}\n"
        )

    def _render_milestones_md(self, state: dict[str, Any]) -> str:
        delivery_plan = self._delivery_plan_payload(state)
        if delivery_plan:
            rows: list[list[str]] = []
            for milestone in delivery_plan.get("milestones") or []:
                work_items = [
                    {
                        "milestone_id": milestone.get("milestone_id"),
                        "milestone_title": milestone.get("title"),
                        "work_item_id": work_item.get("work_item_id"),
                        "work_item_title": work_item.get("title"),
                        "goal": work_item.get("goal") or work_item.get("title"),
                    }
                    for work_item in milestone.get("work_items") or []
                ]
                statuses = [self._work_item_status(state, work_item) for work_item in work_items]
                status_labels = [status for status, _evidence, _notes in statuses]
                if work_items and all(status == "DONE" for status in status_labels):
                    milestone_status = "DONE"
                elif any(status in {"BLOCKED", "FAILED", "NEEDS_CLARIFICATION", "FAIL"} for status in status_labels):
                    milestone_status = "BLOCKED"
                elif any(status in {"IN_PROGRESS", "DELIVERED"} for status in status_labels):
                    milestone_status = "IN_PROGRESS"
                else:
                    milestone_status = "PENDING"
                latest_evidence = next((evidence for _status, evidence, _notes in reversed(statuses) if evidence != "[none]"), "[none]")
                progress = f"{sum(1 for status in status_labels if status == 'DONE')}/{len(status_labels) or 1} work items done"
                rows.append(
                    [
                        f"`{milestone.get('milestone_id')}`",
                        self._compact(milestone.get("title"), limit=48),
                        f"`{milestone_status}`",
                        progress,
                        f"`{latest_evidence}`",
                    ]
                )
            return (
                "# MILESTONES\n\n"
                "This file tracks project milestones projected from the delivery plan and verified work-item state.\n\n"
                f"{self._markdown_table(['Milestone', 'Title', 'Status', 'Progress', 'Latest Evidence'], rows)}\n"
            )
        project = state["project"]
        tasks = state["tasks"]
        latest = state["latest"]
        milestone_specs = [
            ("Project Framing", "project_charter", {"FRAME_PROJECT"}),
            ("Architecture", "architecture_spec", {"DESIGN_ARCHITECTURE"}),
            ("Software Delivery", "software_delivery_package", {"ORCHESTRATE_SOFTWARE", "PLAN_SOFTWARE_TASK", "IMPLEMENT_SOFTWARE_TASK", "TEST_SOFTWARE_TASK"}),
            ("Verification", "verification_report", {"VERIFY_PROJECT"}),
            ("Closure", "project_closure_report", {"CLOSE_PROJECT"}),
        ]
        rows: list[list[str]] = []
        for label, artifact_type, task_types in milestone_specs:
            record, payload = latest[artifact_type]
            relevant_tasks = [task for task in tasks if task["task_type"] in task_types]
            active = any(task["status"] in NON_TERMINAL_TASK_STATUSES for task in relevant_tasks)
            blocked = next((task for task in relevant_tasks if task["status"] in {"BLOCKED", "FAILED", "NEEDS_CLARIFICATION"}), None)
            if label == "Closure" and project["project_status"] == "DONE":
                status = "DONE"
            elif record is not None:
                status = "DONE"
            elif blocked is not None:
                status = blocked["status"]
            elif active:
                status = "IN_PROGRESS"
            else:
                status = "PENDING"
            note = "[none]"
            if isinstance(payload, dict):
                note = self._compact(payload.get("summary") or payload.get("result") or payload.get("system_shape"))
            elif blocked is not None:
                note = self._compact(blocked["goal"])
            rows.append(
                [
                    label,
                    f"`{status}`",
                    f"`{self._artifact_name(record)}`",
                    note,
                ]
            )
        return (
            "# MILESTONES\n\n"
            "This file tracks the major project milestones reflected by accepted artifacts and task state.\n\n"
            f"{self._markdown_table(['Milestone', 'Status', 'Latest Evidence', 'Notes'], rows)}\n"
        )

    def _render_decisions_md(self, state: dict[str, Any]) -> str:
        latest = state["latest"]
        control_events = state["control_events"]
        architecture_record, architecture_payload = latest["architecture_spec"]
        verification_record, verification_payload = latest["verification_report"]
        decision_lines: list[str] = []
        if isinstance(architecture_payload, dict):
            if architecture_payload.get("system_shape"):
                decision_lines.append(
                    f"`Architecture` `{self._artifact_name(architecture_record)}`: {self._compact(architecture_payload['system_shape'], limit=200)}"
                )
            for item in architecture_payload.get("constraints") or []:
                decision_lines.append(f"`Constraint`: {self._compact(item, limit=200)}")
        for event in control_events:
            if event.get("status") != "APPLIED":
                continue
            decision_lines.append(
                f"`{event['requested_at']}` `{event['command']}` by `{event['requested_by']}`: {self._compact(event.get('result_summary'), limit=200)}"
            )
        if isinstance(verification_payload, dict) and verification_payload.get("result") == "FAIL":
            decision_lines.append(
                f"`Verification` `{self._artifact_name(verification_record)}`: defect category `{verification_payload.get('defect_category') or '[unknown]'}`"
            )
        return (
            "# DECISIONS\n\n"
            "This file records durable project decisions accepted by the control-plane workflow.\n\n"
            f"{self._bullet_lines(decision_lines, placeholder='none recorded')}\n"
        )

    def _render_test_report_md(self, state: dict[str, Any]) -> str:
        latest = state["latest"]
        delivery_plan = self._delivery_plan_payload(state)
        test_record, test_payload = latest["test_execution_report"]
        verification_record, verification_payload = latest["verification_report"]
        code_record, code_payload = latest["code_change"]
        test_lines: list[str] = [
            f"- Updated at: `{utc_now()}`",
            f"- Latest code change: `{self._artifact_name(code_record)}`",
            f"- Latest tester report: `{self._artifact_name(test_record)}`",
            f"- Latest verification report: `{self._artifact_name(verification_record)}`",
        ]
        if isinstance(code_payload, dict) and code_payload.get("changed_files"):
            test_lines.append(
                f"- Changed files: `{', '.join(str(item) for item in code_payload.get('changed_files') or [])}`"
            )
        if isinstance(test_payload, dict):
            test_lines.extend(
                [
                    f"- Tester result: `{test_payload.get('result') or '[unknown]'}`",
                    f"- Tester summary: `{self._compact(test_payload.get('summary'), limit=200)}`",
                    f"- Commands run: `{', '.join(str(item) for item in test_payload.get('commands_run') or []) or '[none]'}`",
                    f"- Failures: `{'; '.join(str(item) for item in test_payload.get('failures') or []) or '[none]'}`",
                ]
            )
        if isinstance(verification_payload, dict):
            test_lines.extend(
                [
                    f"- Oracle result: `{verification_payload.get('result') or '[unknown]'}`",
                    f"- Oracle summary: `{self._compact(verification_payload.get('summary'), limit=200)}`",
                    f"- Oracle evidence: `{'; '.join(str(item) for item in verification_payload.get('evidence') or []) or '[none]'}`",
                    f"- Oracle findings: `{'; '.join(str(item) for item in verification_payload.get('findings') or []) or '[none]'}`",
                ]
            )
        if delivery_plan:
            work_item_rows: list[list[str]] = []
            for work_item in self._flatten_work_items(delivery_plan):
                verification_item_record, verification_item_payload = self._latest_verification_for_work_item(
                    state,
                    work_item_id=str(work_item["work_item_id"]),
                )
                test_item_record, test_item_payload = self._latest_test_for_work_item(
                    state,
                    work_item_id=str(work_item["work_item_id"]),
                )
                work_item_rows.append(
                    [
                        f"`{work_item['work_item_id']}`",
                        self._compact(work_item["work_item_title"], limit=36),
                        f"`{(test_item_payload or {}).get('result') if isinstance(test_item_payload, dict) else '[none]'}`",
                        f"`{(verification_item_payload or {}).get('result') if isinstance(verification_item_payload, dict) else '[none]'}`",
                        f"`{self._artifact_name(test_item_record)}`",
                        f"`{self._artifact_name(verification_item_record)}`",
                    ]
                )
            test_lines.extend(
                [
                    "",
                    "## Work Item Verification",
                    "",
                    self._markdown_table(
                        ["Work Item", "Title", "Tester Result", "Oracle Result", "Tester Evidence", "Oracle Evidence"],
                        work_item_rows,
                    ),
                ]
            )
        return (
            "# TEST REPORT\n\n"
            "This file is the latest testing and verification summary projected from tester and Oracle artifacts.\n\n"
            + "\n".join(test_lines)
            + "\n"
        )

    def sync_project(self, project_id: str) -> dict[str, Any] | None:
        state = self._collect(project_id)
        workspace_path = Path(state["workspace_ref"]).resolve()
        self._ensure_scaffold(workspace_path)
        rendered = {
            "PROJECT.md": self._render_project_md(state),
            "management/STATUS.md": self._render_status_md(state),
            "management/BACKLOG.md": self._render_backlog_md(state),
            "management/MILESTONES.md": self._render_milestones_md(state),
            "management/DECISIONS.md": self._render_decisions_md(state),
            "management/TEST_REPORT.md": self._render_test_report_md(state),
        }
        for relative_path, content in rendered.items():
            target = workspace_path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return {
            "project_id": project_id,
            "workspace_ref": str(workspace_path),
            "written_files": sorted(rendered.keys()),
        }
