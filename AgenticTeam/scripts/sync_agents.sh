#!/usr/bin/env bash
# sync_agents.sh — Deploy workspace files and minimal agentDir AGENT.md
# Usage: bash sync_agents.sh [agent_name]
#   No args = sync all agents
#   With arg = sync only that agent (e.g. bash sync_agents.sh neo)
#
# Architecture:
#   Workspace files (AGENTS.md, SOUL.md, TOOLS.md, USER.md, HEARTBEAT.md) are
#   auto-injected by OpenClaw on every session — managed in:
#     /home/alik/workspace/clawspace/workspaces/<agent>/
#   agentDir AGENT.md is a minimal 9-line pointer — managed in:
#     ~/.openclaw/agents/<agent>/agent/AGENT.md

set -euo pipefail

REPO="/home/alik/workspace/agent_template_new/AgenticTeam/agents"
WORKSPACE_ROOT="/home/alik/workspace/clawspace/workspaces"
LIVE="/home/alik/.openclaw/agents"

declare -A ROLES=(
  [neo]="CTO"
  [smith]="General Manager"
  [niaobe]="Project Manager"
  [architect]="System Designer"
  [morpheus]="Software Build Manager"
  [oracle]="QA Validator"
)

AGENTS=("neo" "smith" "niaobe" "architect" "morpheus" "oracle")

if [ $# -ge 1 ]; then
  AGENTS=("$1")
fi

for agent in "${AGENTS[@]}"; do
  name="${agent^}"
  role="${ROLES[$agent]}"

  # 1. Deploy workspace files from repo to live workspace dir
  WS_SRC="$REPO/$agent"
  WS_DEST="$WORKSPACE_ROOT/$agent"
  mkdir -p "$WS_DEST"

  for wsfile in AGENTS.md SOUL.md IDENTITY.md TOOLS.md USER.md HEARTBEAT.md; do
    src="$WS_SRC/$wsfile"
    if [ -f "$src" ]; then
      cp "$src" "$WS_DEST/$wsfile"
      echo "  📄 $agent/$wsfile deployed"
    fi
  done

  # 2. Write minimal agentDir AGENT.md (pointer to workspace files)
  AGENT_DEST="$LIVE/$agent/agent/AGENT.md"
  mkdir -p "$LIVE/$agent/agent"
  cat > "$AGENT_DEST" << AGENTMD
You are ${name}, ${role} at AgenticTeam.

Your complete instructions are in your workspace files — read and follow them strictly:
- **AGENTS.md**: your standing orders, trigger, execution steps, and escalation rules
- **SOUL.md**: your identity and hard limits
- **TOOLS.md**: your available tools with exact command syntax and JSON templates
- **USER.md**: your chain — who you report to and who you delegate to

**Execute-Verify-Report on every action. Do ALL tool calls before writing any reply. Never skip steps. Never skip verification.**
AGENTMD

  echo "✅ $agent synced — workspace: $(ls $WS_DEST | wc -l) files, AGENT.md: $(wc -l < $AGENT_DEST) lines"
done

echo ""
echo "Done. Gateway hot-reloads workspace files and AGENT.md — no restart needed."
