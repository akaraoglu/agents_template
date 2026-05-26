#!/usr/bin/env bash
# Usage: bash run_openclaw_phase_canary.sh --phase <name> [options]

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"
exec "$REPO_ROOT/env-python/bin/python" "$REPO_ROOT/AgenticTeam/scripts/run_openclaw_phase_canary.py" "$@"
