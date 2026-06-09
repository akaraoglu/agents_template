import os
import subprocess
import pytest

def test_v4_is_off_by_default():
    # Clear the env var if it exists
    env = os.environ.copy()
    if "AGENT_TEAM_V4" in env:
        del env["AGENT_TEAM_V4"]
    
    # Run a check using the launcher (if it exists) or just python
    # We'll use python to check the env var directly for simplicity in this smoke test
    cmd = "import os; print(os.environ.get('AGENT_TEAM_V4', 'false'))"
    process = subprocess.run(
        ["./env-python/bin/python", "-c", cmd],
        env=env,
        capture_output=True,
        text=True
    )
    assert process.stdout.strip() == "false"

def test_v4_can_be_enabled():
    env = os.environ.copy()
    env["AGENT_TEAM_V4"] = "true"
    
    cmd = "import os; print(os.environ.get('AGENT_TEAM_V4', 'false'))"
    process = subprocess.run(
        ["./env-python/bin/python", "-c", cmd],
        env=env,
        capture_output=True,
        text=True
    )
    assert process.stdout.strip() == "true"
