#!/usr/bin/env python3
"""Atomic tools for the ReAct AgenticTeam architecture."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def read_file(project_path: str | Path, relative_path: str) -> str:
    """Reads a file from the project directory.
    
    Args:
        project_path: Root directory of the project.
        relative_path: Path of the file relative to project root.
    """
    path = Path(project_path) / relative_path
    if not path.is_file():
        return f"Error: File does not exist at {relative_path}"
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error: Failed to read file: {exc}"


def write_file(project_path: str | Path, relative_path: str, content: str) -> str:
    """Writes content to a file in the project directory, creating parent directories if needed.
    
    Args:
        project_path: Root directory of the project.
        relative_path: Path of the file relative to project root.
        content: String content to write.
    """
    path = Path(project_path) / relative_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Success: File written successfully to {relative_path}"
    except Exception as exc:
        return f"Error: Failed to write file: {exc}"


def exec_command(project_path: str | Path, command: str) -> str:
    """Executes a shell command in the project directory and returns the output.
    
    Args:
        project_path: Directory to run the command in.
        command: Command string to execute.
    """
    try:
        # Run with a 120 second timeout to prevent hanging forever
        res = subprocess.run(
            command,
            shell=True,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=120
        )
        stdout = res.stdout or ""
        stderr = res.stderr or ""
        output = []
        if stdout.strip():
            output.append(f"STDOUT:\n{stdout}")
        if stderr.strip():
            output.append(f"STDERR:\n{stderr}")
        
        result_str = "\n".join(output) if output else "Command completed with no output."
        return f"Command returned exit code {res.returncode}\n{result_str}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 120 seconds."
    except Exception as exc:
        return f"Error: Failed to execute command: {exc}"


def ask_user(question: str, options: str | None = None) -> str:
    """Prompts the user interactively in the terminal and returns their response.
    
    Args:
        question: Question to ask the user.
        options: Comma-separated list of choices.
    """
    script_path = Path(__file__).resolve().parent / "ask_user.py"
    cmd = [sys.executable, str(script_path), "--question", question]
    if options:
        cmd.extend(["--options", options])
        
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        # Parse the decision printed in the last line of stdout
        lines = res.stdout.strip().splitlines()
        if lines:
            return lines[-1]
        return "No answer received."
    except subprocess.CalledProcessError as exc:
        return f"Error: ask_user execution failed: {exc.stderr}"
    except Exception as exc:
        return f"Error: {exc}"


def handoff_to_agent(
    run_dir: str | Path,
    target_agent: str,
    summary: str,
    artifacts: str
) -> str:
    """Commits changes to git, updates the manifest, and transitions task ownership to the next agent.
    
    Args:
        run_dir: Path to the active run directory.
        target_agent: Target agent role (e.g., 'oracle', 'niaobe').
        summary: Summary of the work completed.
        artifacts: Comma-separated relative paths of created/modified files.
    """
    script_path = Path(__file__).resolve().parent / "handoff.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--run-dir", str(run_dir),
        "--target", target_agent,
        "--summary", summary,
        "--artifacts", artifacts
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return f"Success: Handoff initiated. Output:\n{res.stdout}"
    except subprocess.CalledProcessError as exc:
        return f"Error: Handoff failed:\n{exc.stderr}\n{exc.stdout}"
    except Exception as exc:
        return f"Error: Handoff failed: {exc}"
