#!/usr/bin/env bash
# Usage: bash smith_task_progress.sh <complete|blocked> <project-id> <task-id> [--reason "..."]

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"

exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/smith_task_progress.py" "$@"
