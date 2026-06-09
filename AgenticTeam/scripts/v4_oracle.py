import json
import os
import sys
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional

from AgenticTeam.scripts.v4_contracts import LeaseV4, OracleResultV4
from AgenticTeam.scripts.v4_tools import V4ToolError, V4Tools

scripts_dir = str(Path(__file__).resolve().parent)
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from AgenticTeam.scripts.agent_runner import OLLAMA_URL, extract_json, load_ollama_runtime_config

class V4OracleRunner:
    def __init__(self, workspace_root: str, lease: LeaseV4, actor: str = "oracle"):
        self.workspace_root = workspace_root
        self.lease = lease
        self.actor = actor
        self.project_id = lease.metadata.get("project_id", "none")
        self.tools = V4Tools(workspace_root)
        
    def _compile_system_prompt(self) -> str:
        role = self.actor
        agents_dir = Path(__file__).resolve().parent.parent / "agents" / "v4" / role
        parts = []
        for name in ["IDENTITY.md", "SOUL.md", "AGENT.md", "SKILLS.md"]:
            path = agents_dir / name
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8"))
        
        base_prompt = "\n\n".join(parts) if parts else f"You are the {role.upper()} oracle agent."
        
        react_instructions = f"""
You are executing in a tool-driven ReAct loop. You MUST interact ONLY using JSON objects formatted exactly as follows:

{{
  "thought": "Your step-by-step reasoning explaining why you are performing this action.",
  "tool": "fs_read" | "fs_list" | "tests_discover" | "tests_run" | "oracle_report",
  "parameters": {{
     // Tool-specific arguments (do not pass lease_id, project_id, actor - the runner supplies them automatically!)
  }}
}}

The available tools and parameters are:

1. fs_read:
   - Parameters: {{"relative_path": "project-relative path to read"}}
2. fs_list:
   - Parameters: {{"relative_path": "project-relative path"}}
3. tests_discover:
   - Parameters: {{}}
4. tests_run:
   - Parameters: {{"test_path": "relative path to test file"}}
5. oracle_report:
   - Parameters: {{"status": "PASS" | "FAIL", "summary": "detailed verification summary", "evidence_paths": ["list of paths checked"]}}

Rules:
- Output ONLY the raw JSON object. Do not wrap it in markdown code blocks or add any other text outside the JSON.
- Do not stop until you have called "oracle_report".
- Ensure Oracle does not attempt to mutate or write any files. You do not have write permissions or write tools.
"""
        return f"{base_prompt}\n\n{react_instructions}"

    def run(self, max_turns: int = 15) -> str:
        system_prompt = self._compile_system_prompt()
        
        user_msg = f"""You have been assigned to verify the project.

Project ID: {self.project_id}
Workspace Root: {self.workspace_root}

Please verify the project using the provided tools and submit your final report.
"""
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
                messages.append({"role": "user", "content": "Error: Your response was not valid JSON. Please respond with a valid JSON action object."})
                continue
                
            tool_name = action.get("tool")
            params = action.get("parameters", {})
            print(f"[Turn {turn}] Executing tool {tool_name} with params {params}", flush=True)
            
            try:
                result = self._execute_tool(tool_name, params)
                print(f"[Turn {turn}] Tool result: {result}", flush=True)
                messages.append({"role": "user", "content": f"Tool Result: {result}"})
                
                if tool_name == "oracle_report":
                    return result
            except V4ToolError as te:
                messages.append({"role": "user", "content": f"Tool Error [{te.error_code}]: {te.message}"})
            except Exception as e:
                messages.append({"role": "user", "content": f"System Error executing tool: {e}"})
                
        return "Max turns reached without submission."

    def _execute_tool(self, name: str, params: Dict[str, Any]) -> str:
        lease_id = self.lease.lease_id
        actor = self.actor
        
        if name == "fs_read":
            return self.tools.fs_read(params["relative_path"])
        elif name == "fs_list":
            return json.dumps(self.tools.fs_list(params.get("relative_path", ".")))
        elif name == "tests_discover":
            return json.dumps(self.tools.tests_discover())
        elif name == "tests_run":
            # For Oracle, attempt_id is 'oracle-attempt'
            return self.tools.tests_run(params["test_path"], lease_id, "none", actor, "oracle-attempt")
        elif name == "oracle_report":
            or_res = OracleResultV4(
                project_id=self.project_id,
                task_id="none",
                status=params.get("status", "FAIL"),
                evidence_paths=params.get("evidence_paths", []),
                summary=params.get("summary", "")
            )
            return self.tools.oracle_report(or_res, lease_id, actor)
        else:
            raise V4ToolError("missing_capability", f"Unknown tool: {name}")
