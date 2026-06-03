#!/usr/bin/env bash
# Usage: bash morpheus_run_task.sh <dispatch|resume|advance|prepare|read|complete|repair|block> ...

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/morpheus_run_task.py" "$@"
