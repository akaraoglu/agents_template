#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"
PYTHON="$REPO_ROOT/env-python/bin/python"
RUNNER="$REPO_ROOT/AgenticTeam/scripts/run_v4_team.py"

background=false
project_root=""
project_id=""
args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --background)
      background=true
      shift
      ;;
    --project-root)
      project_root="${2:-}"
      args+=("$1" "$2")
      shift 2
      ;;
    --project-id)
      project_id="${2:-}"
      args+=("$1" "$2")
      shift 2
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

if [[ "$background" != "true" ]]; then
  exec "$PYTHON" "$RUNNER" "${args[@]}"
fi

if [[ -z "$project_root" || -z "$project_id" ]]; then
  echo "ERROR: --background requires --project-root and --project-id" >&2
  exit 2
fi

log_root="/home/alik/workspace/clawspace/logs/v4-team"
mkdir -p "$log_root"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log_file="$log_root/${project_id}-${stamp}.log"

setsid env PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 "$PYTHON" "$RUNNER" "${args[@]}" >"$log_file" 2>&1 < /dev/null &
pid="$!"

echo "V4_TEAM_STARTED=1"
echo "PROJECT_ID=$project_id"
echo "EXPECTED_PROJECT_PATH=${project_root%/}/$project_id"
echo "V4_TEAM_PID=$pid"
echo "V4_TEAM_LOG=$log_file"
