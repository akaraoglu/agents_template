#!/usr/bin/env bash
# Usage: bash morpheus_run_task.sh <prepare|read|complete|block> ...

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

export MORPHEUS_RUNTIME_ENGINE="${MORPHEUS_RUNTIME_ENGINE:-langgraph}"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/morpheus_run_task.py" "$@"
