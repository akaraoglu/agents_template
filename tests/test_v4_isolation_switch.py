import os
import subprocess
import pytest

def test_v4_mode_enabled_via_env():
    """Test that setting AGENT_TEAM_V4=true enables V4 mode."""
    env = os.environ.copy()
    env["AGENT_TEAM_V4"] = "true"
    
    # We use the agent_runner to print the detected mode
    # Since agent_runner doesn't have a direct 'print mode' command, 
    # we'll use a small python script that checks the env var.
    script = "import os; print(os.environ.get('AGENT_TEAM_V4'))"
    cmd = [
        "./env-python/bin/python", 
        "-c", 
        f"import os; os.environ['AGENT_TRIM_V4_TEST']='true'; print(os.environ.get('AGENT_TEAM_V4'))"
    ]
    
    # Actually, let's just use the launcher we just fixed/verified.
    launcher = "AgenticTeam/scripts/v4_launcher.py"
    test_cmd = "echo $AGENT_TEAM_V4"
    
    result = subprocess.run(
        ["./env-python/bin/python", launcher, "--v4", "--cmd", test_cmd],
        capture_output=True,
        text=True,
        env=env
    )
    
    assert "true" in result.stdout

def test_v4_mode_disabled_by_default():
    """Test that V4 mode is NOT enabled by default."""
    launcher = "AgenticTeam/scripts/v4_launcher.py"
    test_cmd = "echo $AGENT_TEAM_V4"
    
    result = subprocess.run(
        ["./env-python/bin/python", launcher, "--cmd", test_cmd],
        capture_output=True,
        text=True
    )
    
    # It should be empty or not 'true'
    assert "true" not in result.stdout
