#!/usr/bin/env bash
# Usage: bash architect_run_task.sh <prepare|read|complete|block> ...

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/architect_run_task.py" "$@"
