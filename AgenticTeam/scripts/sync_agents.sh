#!/usr/bin/env bash
# sync_agents.sh — sync AgenticTeam canonical files into the live OpenClaw surface
# Usage:
#   bash sync_agents.sh                # dry-run
#   bash sync_agents.sh --apply        # apply changes
#   bash sync_agents.sh --agent neo    # target one agent

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/sync_live_openclaw.py" "$@"
