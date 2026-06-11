import os
import json
import subprocess
import datetime
from pathlib import Path
from typing import List, Optional, Any, Dict

from AgenticTeam.scripts.v4_contracts import (
    EventV4,
    WorkResultV4,
    OracleResultV4,
    TaskPackV4,
    validate_work_result_v4,
    validate_oracle_result_v4
)
from AgenticTeam.scripts.v4_events import append_event_v4
from AgenticTeam.scripts.v4_leases import validate_lease


def augment_test_feedback(output: str) -> str:
    """Add compact repair hints for common test failures without hiding raw output."""
    text = output or ""
    lowered = text.lower()
    is_import_time_cli_parse = (
        "argparse" in lowered
        and "parse_args" in lowered
        and (
            "systemexit: 2" in lowered
            or "unrecognized arguments" in lowered
            or "invalid int value" in lowered
        )
    )
    if not is_import_time_cli_parse or "ACTIONABLE_TEST_FAILURE[import_time_cli_parse]" in text:
        return text

    hint = (
        "ACTIONABLE_TEST_FAILURE[import_time_cli_parse]: pytest is importing project modules during "
        "test collection, but project code is parsing CLI arguments at import time. Fix the source "
        "module, not the tests: keep importable functions side-effect free, move ArgumentParser setup, "
        "parse_args(), and printing into main(argv=None) or under if __name__ == \"__main__\", then rerun tests."
    )
    return f"{hint}\n\n--- Original test output ---\n{text}"


def process_test_output(process: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part for part in (process.stdout, process.stderr) if part)
    if process.returncode != 0:
        return augment_test_feedback(output)
    return output


class V4ToolError(Exception):
    """Base exception for V4 tool errors."""
    def __init__(self, error_code: str, message: str = ""):
        super().__init__(f"Tool Error [{error_code}]: {message}")
        self.error_code = error_code
        self.message = message

class V4Tools:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()

    def _log_event(self, event_type: str, payload: Dict[str, Any], actor: str = "v4_tools"):
        event = EventV4(
            event_type=event_type,
            payload=payload,
            actor=actor
        )
        append_event_v4(event)

    def _validate_path(self, relative_path: str) -> Path:
        """Ensures the path is inside the project workspace."""
        # Simple prevention of empty paths leading to root resolving
        if not relative_path.strip():
            raise V4ToolError("path_outside_workspace", "Path cannot be empty")
        
        # Resolve absolute path
        target_path = (self.project_root / relative_path).resolve()
        
        # Ensure it starts with project root path
        try:
            target_path.relative_to(self.project_root)
        except ValueError:
            raise V4ToolError("path_outside_workspace", f"Path {relative_path} is outside workspace root {self.project_root}")
            
        return target_path

    def _check_lease(self, lease_id: str, task_id: str, actor: str, attempt_id: str):
        """Verifies that the lease is currently active for mutation."""
        if not validate_lease(str(self.project_root), lease_id, task_id, actor, attempt_id):
            raise V4ToolError("stale_lease", "The active lease has expired or is invalid.")

    # --- Read & Discovery Tools ---

    def workspace_inspect(self) -> Dict[str, Any]:
        """Inspect workspace metadata."""
        self._log_event("workspace_inspect", {"status": "success"})
        return {
            "workspace_root": str(self.project_root),
            "exists": self.project_root.exists(),
            "is_dir": self.project_root.is_dir()
        }

    def repo_map(self) -> List[str]:
        """Returns a list of all files under the project root."""
        self._log_event("repo_map", {"status": "success"})
        file_list = []
        for root, dirs, files in os.walk(self.project_root):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                full_path = Path(root) / f
                rel_path = full_path.relative_to(self.project_root)
                file_list.append(str(rel_path))
        return file_list

    def repo_search(self, query: str) -> List[str]:
        """Search for a string query inside workspace files."""
        self._log_event("repo_search", {"query": query, "status": "success"})
        matches = []
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                file_path = Path(root) / f
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if query in content:
                        matches.append(str(file_path.relative_to(self.project_root)))
                except Exception:
                    continue
        return matches

    def fs_list(self, relative_path: str = ".") -> List[str]:
        """Lists directory contents."""
        target_path = self._validate_path(relative_path)
        if not target_path.exists() or not target_path.is_dir():
            raise V4ToolError("path_not_allowed", f"Directory {relative_path} does not exist or is not a directory")
            
        self._log_event("fs_list", {"path": relative_path, "status": "success"})
        return [str(p.relative_to(self.project_root)) for p in target_path.iterdir()]

    def fs_read(self, relative_path: str) -> str:
        """Reads the content of a file."""
        target_path = self._validate_path(relative_path)
        if not target_path.exists() or not target_path.is_file():
            raise V4ToolError("path_not_allowed", f"File {relative_path} does not exist or is not a file")
            
        try:
            content = target_path.read_text(encoding="utf-8")
            self._log_event("fs_read", {"path": relative_path, "status": "success"})
            return content
        except Exception as e:
            raise V4ToolError("invalid_payload", f"Failed to read file: {e}")

    # --- Safe Mutation Tools ---

    def fs_mkdir(self, relative_path: str, lease_id: str, task_id: str, actor: str, attempt_id: str) -> str:
        """Creates a directory under the active lease."""
        self._check_lease(lease_id, task_id, actor, attempt_id)
        target_path = self._validate_path(relative_path)
        
        try:
            target_path.mkdir(parents=True, exist_ok=True)
            self._log_event("fs_mkdir", {"path": relative_path, "status": "success"}, actor=actor)
            return "Success: Directory created."
        except Exception as e:
            raise V4ToolError("invalid_payload", f"Failed to create directory: {e}")

    def fs_write(self, relative_path: str, content: str, lease_id: str, task_id: str, actor: str, attempt_id: str) -> str:
        """Writes content to a file under the active lease."""
        self._check_lease(lease_id, task_id, actor, attempt_id)
        target_path = self._validate_path(relative_path)
        
        # Enforce content size limit (e.g. 1MB)
        if len(content.encode("utf-8")) > 1024 * 1024:
            raise V4ToolError("content_too_large", "Content exceeds 1MB limit")
            
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            self._log_event("fs_write", {"path": relative_path, "status": "success"}, actor=actor)
            return "Success: File written."
        except Exception as e:
            raise V4ToolError("invalid_payload", f"Failed to write file: {e}")

    def fs_patch(self, relative_path: str, patch_content: str, lease_id: str, task_id: str, actor: str, attempt_id: str) -> str:
        """Applies a patch to a file under the active lease."""
        self._check_lease(lease_id, task_id, actor, attempt_id)
        target_path = self._validate_path(relative_path)
        
        if not target_path.exists():
            raise V4ToolError("path_not_allowed", f"File does not exist: {relative_path}")
            
        try:
            original_content = target_path.read_text(encoding="utf-8")
            
            # Simple SEARCH/REPLACE parser
            lines = patch_content.splitlines()
            search_str = ""
            replace_str = ""
            
            in_search = False
            in_replace = False
            search_lines = []
            replace_lines = []
            
            for line in lines:
                if line.startswith("SEARCH:"):
                    in_search = True
                    in_replace = False
                    search_lines.append(line[len("SEARCH:"):])
                elif line.startswith("REPLACE:"):
                    in_search = False
                    in_replace = True
                    replace_lines.append(line[len("REPLACE:"):])
                else:
                    if in_search:
                        search_lines.append(line)
                    elif in_replace:
                        replace_lines.append(line)
                        
            search_str = "\n".join(search_lines).strip()
            replace_str = "\n".join(replace_lines).strip()
            
            if not search_str:
                raise V4ToolError("invalid_payload", "Patch must contain SEARCH: block")
                
            if search_str in original_content:
                new_content = original_content.replace(search_str, replace_str)
                target_path.write_text(new_content, encoding="utf-8")
                self._log_event("fs_patch", {"path": relative_path, "status": "success"}, actor=actor)
                return "Success: Patch applied."
            else:
                raise V4ToolError("invalid_payload", "Search string not found in file")
        except V4ToolError:
            raise
        except Exception as e:
            raise V4ToolError("invalid_payload", f"Failed to apply patch: {e}")

    # --- Execution & Evidence Tools ---

    def tests_discover(self) -> List[str]:
        """Discovers tests in the workspace."""
        self._log_event("tests_discover", {"status": "success"})
        test_files = []
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.startswith("test_") and f.endswith(".py"):
                    full_path = Path(root) / f
                    test_files.append(str(full_path.relative_to(self.project_root)))
        return test_files

    def tests_run(self, test_path: str, lease_id: str, task_id: str, actor: str, attempt_id: str) -> str:
        """Runs pytest for the given test path."""
        self._check_lease(lease_id, task_id, actor, attempt_id)
        target_path = self._validate_path(test_path)
        
        import sys
        python_exe = "./env-python/bin/python"
        if not (self.project_root / python_exe).exists():
            python_exe = sys.executable
            
        import os
        env = os.environ.copy()
        proj_root_str = str(self.project_root)
        env["PYTHONPATH"] = f"{proj_root_str}:{proj_root_str}/src:" + env.get("PYTHONPATH", "")
        
        cmd = f"PYTHONDONTWRITEBYTECODE=1 {python_exe} -m pytest -q {target_path}"
        try:
            process = subprocess.run(
                cmd,
                shell=True,
                cwd=self.project_root,
                env=env,
                capture_output=True,
                text=True
            )
            status = "success" if process.returncode == 0 else "failure"
            self._log_event("tests_run", {
                "test_path": test_path,
                "status": status,
                "exit_code": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr
            }, actor=actor)
            return process_test_output(process)
        except Exception as e:
            raise V4ToolError("invalid_payload", f"Failed to execute tests: {e}")

    def cmd_preflight(self, command: str) -> bool:
        """Validates that a command is allowlisted."""
        allowed_prefixes = [
            "PYTHONDONTWRITEBYTECODE=1 ./env-python/bin/python -m pytest",
            "pytest"
        ]
        return any(command.strip().startswith(prefix) for prefix in allowed_prefixes)

    def cmd_run(self, command: str, lease_id: str, task_id: str, actor: str, attempt_id: str) -> str:
        """Runs an approved command."""
        self._check_lease(lease_id, task_id, actor, attempt_id)
        if not self.cmd_preflight(command):
            raise V4ToolError("path_not_allowed", "Command is not allowlisted")
            
        try:
            process = subprocess.run(
                command,
                shell=True,
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            status = "success" if process.returncode == 0 else "failure"
            self._log_event("cmd_run", {
                "command": command,
                "status": status,
                "exit_code": process.returncode
            }, actor=actor)
            return process.stdout or process.stderr
        except Exception as e:
            raise V4ToolError("invalid_payload", f"Failed to execute command: {e}")

    # --- Work & Oracle Submission Tools ---

    def work_submit(self, work_result: WorkResultV4, lease_id: str, actor: str) -> str:
        """Submits task work result."""
        self._check_lease(lease_id, work_result.task_id, actor, work_result.attempt_id)
        if not validate_work_result_v4(work_result):
            raise V4ToolError("invalid_payload", "WorkResultV4 validation failed (missing output/evidence/task_id/attempt_id)")
            
        self._log_event("work_submitted", {
            "task_id": work_result.task_id,
            "attempt_id": work_result.attempt_id,
            "status": work_result.status,
            "summary": work_result.summary,
            "output": work_result.output,
            "evidence": work_result.evidence
        }, actor=actor)
        return "Success"

    def work_block(self, task_id: str, attempt_id: str, reason: str, lease_id: str, actor: str) -> str:
        """Blocks task execution."""
        self._check_lease(lease_id, task_id, actor, attempt_id)
        if not reason.strip():
            raise V4ToolError("invalid_payload", "Block reason cannot be empty")
            
        self._log_event("work_blocked", {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "reason": reason
        }, actor=actor)
        return "Success"

    def work_status(self, task_id: str) -> str:
        """Gets task status from event store."""
        from AgenticTeam.scripts.v4_events import read_events_v4
        events = read_events_v4()
        from AgenticTeam.scripts.v4_state import project_state_from_events
        state = project_state_from_events(events)
        if task_id in state.tasks:
            return state.tasks[task_id]["status"]
        return "PENDING"

    def oracle_report(self, oracle_result: OracleResultV4, lease_id: str, actor: str) -> str:
        """Submits Oracle verification report."""
        # For Oracle, the leased resource is typically the project_id or task_id.
        # Let's validate lease with resource_id = oracle_result.task_id (or project_id if task_id is 'none')
        resource_id = oracle_result.task_id
        self._check_lease(lease_id, resource_id, actor, "oracle-attempt")
        
        if not validate_oracle_result_v4(oracle_result):
            raise V4ToolError("invalid_payload", "OracleResultV4 must contain evidence paths")
            
        event_type = "oracle_passed" if oracle_result.status.upper() == "PASS" else "oracle_failed"
        self._log_event(event_type, {
            "project_id": oracle_result.project_id,
            "task_id": oracle_result.task_id,
            "status": oracle_result.status,
            "evidence_paths": oracle_result.evidence_paths,
            "summary": oracle_result.summary
        }, actor=actor)
        return "Success"

    # --- Mattermost Tools ---

    def mm_send_message(self, message: str, target: str, actor: str, reply_to: Optional[str] = None) -> str:
        """Sends a message via Mattermost by calling the OpenClaw CLI."""
        if not message.strip():
            raise V4ToolError("invalid_payload", "Message body cannot be empty")
        if not target.strip():
            raise V4ToolError("invalid_payload", "Target channel/user cannot be empty")

        cmd = [
            "openclaw", "message", "send",
            "--account", actor,
            "--channel", "mattermost",
            "--target", target,
            "--message", message
        ]
        if reply_to:
            cmd.extend(["--reply-to", reply_to])

        self._log_event("mm_message_sent", {
            "target": target,
            "message": message,
            "reply_to": reply_to
        }, actor=actor)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            stdout = res.stdout.strip()
            return f"Success: {stdout}"
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() or e.stdout.strip()
            raise V4ToolError("mm_delivery_failed", f"Failed to send message: {err}")

    def mm_read_messages(self, target: str, actor: str, limit: int = 10) -> str:
        """Reads recent messages from a channel via Mattermost by calling the OpenClaw CLI."""
        if not target.strip():
            raise V4ToolError("invalid_payload", "Target channel/user cannot be empty")

        cmd = [
            "openclaw", "message", "read",
            "--account", actor,
            "--channel", "mattermost",
            "--target", target,
            "--limit", str(limit),
            "--json"
        ]

        self._log_event("mm_messages_read", {
            "target": target,
            "limit": limit
        }, actor=actor)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return res.stdout.strip()
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() or e.stdout.strip()
            raise V4ToolError("mm_read_failed", f"Failed to read messages: {err}")

    # --- System Diagnostic Tools ---

    def sys_diagnose(self, actor: str) -> str:
        """Runs diagnostics on the OpenClaw agent team."""
        try:
            status_cmd = ["openclaw", "status"]
            status_res = subprocess.run(status_cmd, capture_output=True, text=True, check=False)
            status_out = status_res.stdout.strip()

            logs_cmd = ["openclaw", "logs", "--plain", "--limit", "200"]
            logs_res = subprocess.run(logs_cmd, capture_output=True, text=True, check=False)
            logs_out = logs_res.stdout.strip()

            team_status_cmd = ["bash", str(self.project_root / "AgenticTeam" / "scripts" / "team_status.sh")]
            team_status_res = subprocess.run(team_status_cmd, capture_output=True, text=True, check=False)
            team_status_out = team_status_res.stdout.strip()

            self._log_event("sys_diagnose_run", {}, actor=actor)

            return (
                f"=== OpenClaw Status ===\n{status_out}\n\n"
                f"=== Team Status Script ===\n{team_status_out}\n\n"
                f"=== Recent Logs ===\n{logs_out}"
            )
        except Exception as e:
            raise V4ToolError("sys_diagnose_failed", f"Failed to run diagnostics: {e}")

    def sys_run_tests(self, test_path: str, actor: str) -> str:
        """Runs tests locally for diagnostics without requiring a lease."""
        target_path = self._validate_path(test_path)

        import sys
        python_exe = "./env-python/bin/python"
        if not (self.project_root / python_exe).exists():
            python_exe = sys.executable

        import os
        env = os.environ.copy()
        proj_root_str = str(self.project_root)
        env["PYTHONPATH"] = f"{proj_root_str}:{proj_root_str}/src:" + env.get("PYTHONPATH", "")

        cmd = f"PYTHONDONTWRITEBYTECODE=1 {python_exe} -m pytest -q {target_path}"
        try:
            process = subprocess.run(
                cmd,
                shell=True,
                cwd=self.project_root,
                env=env,
                capture_output=True,
                text=True
            )
            self._log_event("sys_run_tests", {"test_path": test_path}, actor=actor)
            return process_test_output(process)
        except Exception as e:
            raise V4ToolError("sys_run_tests_failed", f"Failed to run diagnostic tests: {e}")
