#!/usr/bin/env bash
# Usage: bash python_claw.sh --cwd "<absolute cwd>" (--module <module>|--script <relative.py>|--syntax-check <relative.py>|--version) [-- args...]

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/python_claw.py" "$@"
