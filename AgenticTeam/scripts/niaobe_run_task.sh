#!/usr/bin/env bash
# Usage: bash niaobe_run_task.sh accept '<JSON envelope>'

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/niaobe_run_task.py" "$@"
