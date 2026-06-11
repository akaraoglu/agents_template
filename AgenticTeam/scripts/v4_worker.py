import json
import os
import sys
import requests
import posixpath
from pathlib import Path
from typing import List, Dict, Any, Optional

from AgenticTeam.scripts.v4_contracts import TaskPackV4, LeaseV4, WorkResultV4
from AgenticTeam.scripts.v4_tools import V4ToolError, V4Tools

scripts_dir = str(Path(__file__).resolve().parent)
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from AgenticTeam.scripts.v4_model import OLLAMA_URL, extract_json, load_ollama_runtime_config

class V4WorkerRunner:
    def __init__(self, task_pack: TaskPackV4, lease: LeaseV4, actor: str = "morpheus"):
        self.task_pack = task_pack
        self.lease = lease
        self.actor = actor
        self.tools = V4Tools(task_pack.workspace_root)
        
    def _compile_system_prompt(self) -> str:
        role = self.actor
        agents_dir = Path(__file__).resolve().parent.parent / "agents" / role
        parts = []
        for name in ["IDENTITY.md", "SOUL.md", "AGENT.md", "SKILLS.md"]:
            path = agents_dir / name
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8"))
        
        display_role = role[:1].upper() + role[1:]
        base_prompt = "\n\n".join(parts) if parts else f"You are the {display_role} worker agent."
        
        react_instructions = f"""
You are executing in a tool-driven ReAct loop. You MUST interact ONLY using JSON objects formatted exactly as follows:

{{
  "thought": "Your step-by-step reasoning explaining why you are performing this action.",
  "tool": "fs_read" | "fs_write" | "fs_patch" | "fs_mkdir" | "tests_run" | "tests_discover" | "work_submit" | "work_block" | "work_status",
  "parameters": {{
     // Tool-specific arguments (do not pass lease_id, task_id, actor, attempt_id - the runner supplies them automatically!)
  }}
}}

The available tools and parameters are:

1. fs_read:
   - Parameters: {{"relative_path": "project-relative path to read"}}
2. fs_write:
   - Parameters: {{"relative_path": "project-relative path", "content": "file content"}}
3. fs_patch:
   - Parameters: {{"relative_path": "project-relative path", "patch_content": "SEARCH:\\n...\\nREPLACE:\\n..."}}
4. fs_mkdir:
   - Parameters: {{"relative_path": "directory path to create"}}
5. tests_discover:
   - Parameters: {{}}
6. tests_run:
   - Parameters: {{"test_path": "relative path to test file"}}
7. work_submit:
   - Parameters: {{"status": "DONE", "summary": "brief summary", "output": {{"artifacts": ["list of modified files"]}}, "evidence": {{"tests_passed": true}}}}
     Note: At least one of output or evidence MUST be non-empty (do not submit empty dicts {{}}), otherwise validation fails!
8. work_block:
   - Parameters: {{"reason": "actionable block reason"}}
9. work_status:
   - Parameters: {{"task_id": "T###"}}

Rules:
- Output ONLY the raw JSON object. Do not wrap it in markdown code blocks or add any other text outside the JSON.
- If you cannot complete the task, call "work_block" with a clear reason.
- Do not stop until you have called "work_submit" or "work_block".
- Expected Artifacts are the required deliverables for this task. They are not the full write boundary.
- You may create or edit files inside Writable Paths as long as they are not Protected Paths.
- Do not modify Protected Paths such as project control files, `.openclaw`, or management task files.
- You may create or update tests under `tests/` when that helps validate implementation, even if the current Expected Artifacts only list source files.
- Before submitting DONE, make sure every Expected Artifact exists.
- TIP: If you use "fs_write" to update a file, you MUST first read the file using "fs_read" and then write the ENTIRE file content containing both the existing code and your new additions/changes. Never use "fs_write" to overwrite a file with only your new function, as this wipes out work from previous tasks! Prefer "fs_write" over "fs_patch" for small files (under 100 lines) to avoid IndentationErrors.
"""
        return f"{base_prompt}\n\n{react_instructions}"

    def run(self, max_turns: int = 15) -> str:
        system_prompt = self._compile_system_prompt()
        
        task_desc = ""
        task_desc_path = Path(self.task_pack.workspace_root) / "management" / "tasks" / f"{self.task_pack.task_id}.md"
        if task_desc_path.exists():
            try:
                task_desc = task_desc_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"Warning: could not read task description from {task_desc_path}: {e}")

        user_msg = f"""You have been assigned a task to complete.

Project ID: {self.task_pack.project_id}
Task ID: {self.task_pack.task_id}
Workspace Root: {self.task_pack.workspace_root}
Expected Artifacts: {self._expected_artifacts()}
Writable Paths: {self._writable_paths()}
Protected Paths: {self._protected_paths()}

"""
        if task_desc:
            user_msg += f"Task Description:\n```markdown\n{task_desc}\n```\n\n"
            
        user_msg += "Please complete the task using the provided tools.\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ]
        
        model_name, num_ctx = load_ollama_runtime_config()
        
        for turn in range(1, max_turns + 1):
            payload = {
                "model": model_name,
                "messages": messages,
                "options": {"num_ctx": num_ctx, "temperature": 0.0},
                "stream": False
            }
            
            try:
                response = requests.post(OLLAMA_URL, json=payload, timeout=600)
                response.raise_for_status()
                content = response.json()["message"]["content"]
                print(f"\n[Turn {turn}] Assistant content:\n{content}\n", flush=True)
            except Exception as e:
                print(f"Error querying Ollama: {e}", flush=True)
                return f"Error querying Ollama: {e}"
                
            messages.append({"role": "assistant", "content": content})
            
            action = extract_json(content)
            if not action:
                print(f"[Turn {turn}] Invalid JSON response.", flush=True)
                messages.append({
                    "role": "user",
                    "content": (
                        "Error: Your response was not valid JSON. Respond with one small valid JSON action object only. "
                        "If a large README or patch string caused escaping problems, stop trying that patch. "
                        "Use a simpler fs_write with plain text, or call work_submit if the required implementation and tests are already complete. "
                        "Do not call work_block only because JSON escaping was difficult."
                    ),
                })
                continue
                
            tool_name = action.get("tool")
            params = action.get("parameters", {})
            print(f"[Turn {turn}] Executing tool {tool_name} with params {params}", flush=True)
            
            try:
                result = self._execute_tool(tool_name, params)
                print(f"[Turn {turn}] Tool result: {result}", flush=True)
                messages.append({"role": "user", "content": f"Tool Result: {result}"})
                
                if tool_name in ("work_submit", "work_block"):
                    return result
            except V4ToolError as te:
                messages.append({"role": "user", "content": f"Tool Error [{te.error_code}]: {te.message}"})
            except Exception as e:
                messages.append({"role": "user", "content": f"System Error executing tool: {e}"})
                
        return "Max turns reached without submission."

    def _execute_tool(self, name: str, params: Dict[str, Any]) -> str:
        lease_id = self.lease.lease_id
        task_id = self.task_pack.task_id
        actor = self.actor
        attempt_id = self.lease.metadata.get("attempt_id", "none")
        
        if name == "fs_read":
            return self.tools.fs_read(params["relative_path"])
        elif name == "fs_write":
            self._ensure_writable_path(params["relative_path"])
            return self.tools.fs_write(params["relative_path"], params["content"], lease_id, task_id, actor, attempt_id)
        elif name == "fs_patch":
            self._ensure_writable_path(params["relative_path"])
            return self.tools.fs_patch(params["relative_path"], params["patch_content"], lease_id, task_id, actor, attempt_id)
        elif name == "fs_mkdir":
            self._ensure_writable_path(params["relative_path"], is_directory=True)
            return self.tools.fs_mkdir(params["relative_path"], lease_id, task_id, actor, attempt_id)
        elif name == "tests_discover":
            return json.dumps(self.tools.tests_discover())
        elif name == "tests_run":
            return self.tools.tests_run(params["test_path"], lease_id, task_id, actor, attempt_id)
        elif name == "work_status":
            return self.tools.work_status(params.get("task_id", task_id))
        elif name == "work_submit":
            wr = WorkResultV4(
                task_id=task_id,
                attempt_id=attempt_id,
                status=params.get("status", "DONE"),
                summary=params.get("summary", ""),
                output=params.get("output", {}),
                evidence=params.get("evidence", {})
            )
            if wr.status.upper() == "DONE":
                self._ensure_expected_artifacts_exist()
            return self.tools.work_submit(wr, lease_id, actor)
        elif name == "work_block":
            return self.tools.work_block(task_id, attempt_id, params["reason"], lease_id, actor)
        else:
            raise V4ToolError("missing_capability", f"Unknown tool: {name}")

    def _normalized_relative_path(self, relative_path: str) -> str:
        normalized = posixpath.normpath(relative_path.replace("\\", "/")).strip("/")
        if normalized in ("", ".") or normalized.startswith("../") or normalized == "..":
            raise V4ToolError("path_outside_workspace", f"Invalid project-relative path: {relative_path}")
        return normalized

    def _expected_artifacts(self) -> list[str]:
        return [
            self._normalized_relative_path(path)
            for path in self.task_pack.effective_expected_artifacts()
        ]

    def _writable_paths(self) -> list[str]:
        return [self._normalized_relative_path(path) for path in self.task_pack.writable_paths]

    def _protected_paths(self) -> list[str]:
        return [self._normalized_relative_path(path) for path in self.task_pack.protected_paths]

    def _matches_path_rule(self, normalized: str, rule: str) -> bool:
        if rule.endswith("/**"):
            prefix = rule[:-3].rstrip("/")
            return normalized == prefix or normalized.startswith(prefix + "/")
        return normalized == rule

    def _ensure_writable_path(self, relative_path: str, *, is_directory: bool = False) -> None:
        normalized = self._normalized_relative_path(relative_path)

        for rule in self._protected_paths():
            if self._matches_path_rule(normalized, rule):
                raise V4ToolError(
                    "path_protected",
                    f"{normalized} is a protected project path for {self.task_pack.task_id}",
                )

        writable = self._writable_paths()
        if not writable:
            return

        if any(self._matches_path_rule(normalized, rule) for rule in writable):
            return

        if is_directory:
            directory_prefix = normalized.rstrip("/") + "/"
            for rule in writable:
                if rule.endswith("/**"):
                    writable_prefix = rule[:-3].rstrip("/") + "/"
                    if writable_prefix.startswith(directory_prefix):
                        return

        raise V4ToolError(
            "path_not_writable",
            f"{normalized} is not in writable paths for {self.task_pack.task_id}: {writable}",
        )

    def _ensure_expected_artifacts_exist(self) -> None:
        missing: list[str] = []
        workspace = Path(self.task_pack.workspace_root).resolve()
        for relative_path in self._expected_artifacts():
            target = (workspace / relative_path).resolve()
            try:
                target.relative_to(workspace)
            except ValueError:
                missing.append(relative_path)
                continue
            if not target.exists():
                missing.append(relative_path)
        if missing:
            raise V4ToolError(
                "missing_expected_artifacts",
                f"Expected artifacts are missing for {self.task_pack.task_id}: {missing}",
            )
