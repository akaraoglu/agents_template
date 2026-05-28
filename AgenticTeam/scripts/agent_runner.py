#!/usr/bin/env python3
"""Unified generic ReAct agent runner for Morpheus and Architect roles."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

from worker_runtime import load_state, update_state
from project_manifest import load_manifest
import agent_tools

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME = "gemma4:26b"


def extract_json(text: str) -> dict[str, Any] | None:
    """Extracts a JSON object from text, supporting various markdown or raw formats."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None


def load_agent_prompts(role: str) -> str:
    """Loads and compiles system prompts for the given agent role."""
    agents_dir = Path(__file__).resolve().parent.parent / "agents" / role
    
    parts = []
    for name in ["IDENTITY.md", "SOUL.md", "AGENT.md", "SKILLS.md"]:
        path = agents_dir / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
            
    return "\n\n".join(parts)


def run_react_loop(role: str, run_dir: Path) -> dict[str, Any]:
    """Runs a tool-calling ReAct loop for the specified role in the given run directory."""
    state = load_state(run_dir)
    project_path = Path(state["project_path"])
    
    # 1. Compile System Prompt
    base_prompt = load_agent_prompts(role)
    
    react_instructions = """
You are executing in a tool-driven ReAct loop. You MUST interact ONLY using JSON objects formatted exactly as follows:

{
  "thought": "Your step-by-step reasoning explaining why you are performing this action.",
  "tool": "read_project_file" | "write_project_file" | "exec_command" | "ask_user" | "handoff_to_agent",
  "parameters": {
     // Tool-specific arguments
  }
}

The available tools and parameters are:

1. read_project_file:
   - Parameters: {"path": "project-relative path to read"}
2. write_project_file:
   - Parameters: {"path": "project-relative path", "content": "file content"}
3. exec_command:
   - Parameters: {"command": "shell command to run at project root"}
   - Use this tool to run tests and verify implementation.
4. ask_user:
   - Parameters: {"question": "question to ask user", "options": "optional comma-separated options"}
5. handoff_to_agent:
   - Parameters: {"target_agent": "oracle" or "morpheus" or "niaobe", "summary": "summary of work completed", "artifacts": "comma-separated project-relative paths created or modified"}

Rules:
- Output ONLY the raw JSON object. Do not wrap it in markdown code blocks or add any other text outside the JSON.
- Never use forbidden tokens like "read_file" or "write_file" as direct string values in your prompts or output. Use "read_project_file" and "write_project_file" instead.
- Do not stop until you have called "handoff_to_agent" or "ask_user" (if blocked).
"""
    
    system_prompt = f"{base_prompt}\n\n{react_instructions}"
    
    # 2. Compile Inbound Task Context
    task_id = state.get("task_id", "T001")
    manifest = load_manifest(project_path)
    task_manifest = manifest.get("tasks", {}).get(task_id, {})
    
    required_outputs = state.get("required_output_paths") or task_manifest.get("required_outputs") or []
    test_command = state.get("team_test_command") or state.get("test_command") or task_manifest.get("test_command") or ["python3", "-m", "unittest"]
    test_command_str = " ".join(test_command) if isinstance(test_command, list) else str(test_command)
    
    user_message = f"""You have been assigned a new task to complete.

Task ID: {task_id}
Project Path: {project_path}
Phase: {state.get('phase', 'WORK')}

Instructions:
{state.get('instructions')}

Required Outputs:
{required_outputs}

Test Command to run:
{test_command_str}
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    print(f"--- Starting ReAct Loop for {role.upper()} ---")
    print(f"Task ID: {task_id}")
    print(f"Project Path: {project_path}")
    print(f"Required Outputs: {required_outputs}")
    
    max_turns = 15
    for turn in range(1, max_turns + 1):
        print(f"\n[Turn {turn}/{max_turns}] Querying Ollama ({MODEL_NAME})...")
        try:
            payload = {
                "model": MODEL_NAME,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_ctx": 32768,
                    "temperature": 0.0
                }
            }
            res = requests.post(OLLAMA_URL, json=payload, timeout=300)
            res.raise_for_status()
            response_json = res.json()
            response_content = response_json["message"]["content"]
        except Exception as exc:
            error_msg = f"Ollama connection failed: {exc}"
            print(f"Error: {error_msg}")
            state = update_state(run_dir, last_error={"code": "ollama_failed", "message": error_msg})
            return state

        print(f"Raw response:\n{response_content}")
        
        parsed = extract_json(response_content)
        if not parsed:
            error_msg = "Your response could not be parsed as a valid JSON object. You MUST respond ONLY with a single valid JSON object."
            print(f"Parser error: {error_msg}")
            messages.append({"role": "assistant", "content": response_content})
            messages.append({"role": "user", "content": f"Error: {error_msg}"})
            continue
            
        thought = parsed.get("thought", "No thought provided.")
        tool = parsed.get("tool")
        parameters = parsed.get("parameters", {})
        
        print(f"Thought: {thought}")
        print(f"Tool Call: {tool} with parameters {parameters}")
        
        # Append assistant's turn
        messages.append({"role": "assistant", "content": json.dumps(parsed)})
        
        if not tool:
            error_msg = "No tool specified. You must call a valid tool to proceed."
            messages.append({"role": "user", "content": f"Error: {error_msg}"})
            continue
            
        # Tool Execution
        tool_result = ""
        if tool == "read_project_file":
            path = parameters.get("path")
            if not path:
                tool_result = "Error: Missing parameter 'path'."
            else:
                tool_result = agent_tools.read_file(project_path, path)
        elif tool == "write_project_file":
            path = parameters.get("path")
            content = parameters.get("content")
            if not path or content is None:
                tool_result = "Error: Missing parameter 'path' or 'content'."
            else:
                tool_result = agent_tools.write_file(project_path, path, content)
        elif tool == "exec_command":
            cmd = parameters.get("command")
            if not cmd:
                tool_result = "Error: Missing parameter 'command'."
            else:
                tool_result = agent_tools.exec_command(project_path, cmd)
        elif tool == "ask_user":
            question = parameters.get("question")
            options = parameters.get("options")
            if not question:
                tool_result = "Error: Missing parameter 'question'."
            else:
                tool_result = agent_tools.ask_user(question, options)
        elif tool == "handoff_to_agent":
            target = parameters.get("target_agent")
            summary = parameters.get("summary")
            artifacts = parameters.get("artifacts")
            if not target or not summary or not artifacts:
                tool_result = "Error: Missing required parameters for handoff ('target_agent', 'summary', 'artifacts')."
            else:
                tool_result = agent_tools.handoff_to_agent(run_dir, target, summary, artifacts)
                print(f"\nHandoff initiated: {tool_result}")
                state = update_state(run_dir, status="sent")
                return state
        else:
            tool_result = f"Error: Unknown tool '{tool}'."
            
        print(f"Tool Result:\n{tool_result}")
        messages.append({"role": "user", "content": tool_result})
        
    error_msg = f"Execution reached max turns ({max_turns}) without completing handoff."
    print(f"Error: {error_msg}")
    state = update_state(run_dir, last_error={"code": "max_turns_reached", "message": error_msg})
    return state


def complete_artifact_run_graph(contract: Any, run_dir: Path) -> dict[str, Any]:
    """Compatible entrypoint for Morpheus task execution."""
    return run_react_loop("morpheus", run_dir)


def complete_run_graph(contract: Any, run_dir: Path) -> dict[str, Any]:
    """Compatible entrypoint for Architect task execution."""
    return run_react_loop("architect", run_dir)


def print_repair_brief(contract: Any, run_dir: Path) -> None:
    """Mock/legacy helper to print repair brief."""
    print(f"Legacy repair brief called for {contract.role} under {run_dir}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Unified Agent ReAct Loop Runner")
    parser.add_argument("--role", required=True, help="Agent role (morpheus or architect)")
    parser.add_argument("--run-dir", required=True, help="Active worker run directory")
    args = parser.parse_args()
    
    run_react_loop(args.role, Path(args.run_dir))
