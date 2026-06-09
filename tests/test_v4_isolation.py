import os
import subprocess
import pytest

def test_v4_launcher_sets_v4_true():
    """Test that running with --v4 sets AGENT_TEAM_V4 to true."""
    # We use the launcher to run a command that prints the env var
    cmd = "echo $AGENT_TEAM_V4"
    # Use the python interpreter to run the launcher
    launcher_script = "AgenticTeam/scripts/v4_launcher.py"
    
    result = subprocess_run_launcher(launcher_script, ["--v4", "--cmd", cmd])
    assert "true" in result.splitlines()

def test_v4_launcher_sets_v4_false_by_default():
    """Test that running without --v4 sets AGENT_TEAM_V4 to false."""
    cmd = "echo $AGENT_TEAM_V4"
    launcher_script = "AgenticTeam/scripts/v4_launcher.py"
    
    result = subprocess_run_launcher(launcher_script, ["--cmd", cmd])
    assert "false" in result.splitlines()

def subprocess_run_launcher(launcher_script, args):
    """Helper to run the launcher and capture stdout."""
    # We need to use the local python environment to run the launcher
    python_exe = "./env-python/bin/python"
    full_cmd = [python_exe, launcher_script] + args
    
    process = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        shell=False
    )
    
    if process.returncode != 0:
        raise RuntimeError(f"Launcher failed with error: {process.stderr}")
        
    return process.stdout.strip()

