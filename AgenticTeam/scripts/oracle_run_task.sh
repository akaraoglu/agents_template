#!/usr/bin/env bash
# Usage: bash oracle_run_task.sh verify '<JSON envelope>'

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/oracle_run_task.py" "$@"
