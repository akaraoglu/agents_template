#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description="V4 Launcher")
    parser.add_argument("--v4", action="store_true", help="Set AGENT_TEAM_V4=true")
    parser.add_argument("--cmd", required=True, help="Command to run")
    args = parser.parse_args()

    env = os.environ.copy()
    if args.v4:
        env["AGENT_TEAM_V4"] = "true"
    else:
        env["AGENT_TEAM_V4"] = "false"

    # Use shell=True because the test might pass shell commands like 'echo '
    try:
        process = subprocess.run(
            args.cmd,
            env=env,
            shell=True,
            text=True,
            capture_output=False # We want the output to go to the parent's stdout
        )
        sys.exit(process.returncode)
    except Exception as e:
        print(f"Launcher error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
