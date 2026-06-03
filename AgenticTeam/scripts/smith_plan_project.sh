#!/usr/bin/env bash
# Usage: bash smith_plan_project.sh <prepare|autoplan|read|complete|block> ...

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/smith_plan_project.py" "$@"
