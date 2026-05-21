#!/usr/bin/env bash
# Reset a project's state file and optionally wipe implementation artifacts
# Usage: bash reset_project.sh <project-id> [--hard]
# --hard also deletes implementation/, tests/, design/, VALIDATION.md

set -euo pipefail

PROJECT_ID="${1:-}"
HARD="${2:-}"
PROJECTS_DIR="/home/alik/workspace/clawspace/projects/active"
TEMPLATES="/home/alik/workspace/agent_template_new/AgenticTeam/templates"

if [ -z "$PROJECT_ID" ]; then
  echo "Usage: reset_project.sh <project-id> [--hard]"
  echo ""
  echo "Available projects:"
  ls "$PROJECTS_DIR" 2>/dev/null | sed 's/^/  /'
  exit 1
fi

PROJECT_DIR="$PROJECTS_DIR/$PROJECT_ID"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "❌ Project not found: $PROJECT_DIR"
  echo "Available:"
  ls "$PROJECTS_DIR" | sed 's/^/  /'
  exit 1
fi

DATE=$(date +%Y%m%d-%H%M)
TITLE=$(grep "^# Project:" "$PROJECT_DIR/PROJECT.md" 2>/dev/null | sed 's/# Project: //' || echo "$PROJECT_ID")

echo "🔄 Resetting project: $PROJECT_ID"

# Reset PROJECT_STATE.md or legacy STATE.md
STATE_TARGET="$PROJECT_DIR/PROJECT_STATE.md"
TEMPLATE_SOURCE="$TEMPLATES/PROJECT_STATE.md"
if [ -f "$PROJECT_DIR/STATE.md" ] && [ ! -f "$PROJECT_DIR/PROJECT_STATE.md" ]; then
  STATE_TARGET="$PROJECT_DIR/STATE.md"
  TEMPLATE_SOURCE="$TEMPLATES/STATE.md"
fi

if [ -f "$TEMPLATE_SOURCE" ]; then
  sed "s/{{PROJECT_ID}}/$PROJECT_ID/g; s/{{TITLE}}/$TITLE/g; s/{{DATE}}/$DATE/g" \
    "$TEMPLATE_SOURCE" > "$STATE_TARGET"
  echo "   ✅ $(basename "$STATE_TARGET") reset"
else
  cat > "$STATE_TARGET" << HEREDOC
# Project State — $PROJECT_ID
schema_version: 2
owner: smith
phase: PLANNING
active_task: none
task_phase: none
task_status: none
current_agent: smith
waiting_for: none
blocked_count: 0
blocked_reason: none
last_completed_task: none
last_task_result: none
reset_at: $DATE
HEREDOC
  echo "   ✅ $(basename "$STATE_TARGET") reset (no template)"
fi

if [ -f "$PROJECT_DIR/CURRENT_TASK.md" ] && [ -f "$TEMPLATES/CURRENT_TASK.md" ]; then
  sed "s/{{PROJECT_ID}}/$PROJECT_ID/g; s/{{TITLE}}/$TITLE/g; s/{{DATE}}/$DATE/g" \
    "$TEMPLATES/CURRENT_TASK.md" > "$PROJECT_DIR/CURRENT_TASK.md"
  echo "   ✅ CURRENT_TASK.md reset"
fi

if [ "$HARD" = "--hard" ]; then
  echo "   🗑️  Hard reset: removing artifacts..."
  rm -rf "$PROJECT_DIR/src" "$PROJECT_DIR/tests" \
         "$PROJECT_DIR/management/architecture" "$PROJECT_DIR/management/validation"
  mkdir -p "$PROJECT_DIR"/management/{architecture,validation} "$PROJECT_DIR"/{src,tests}
  echo "   ✅ src/, tests/, management/architecture, management/validation cleared"
fi

echo ""
echo "✅ Reset complete: $PROJECT_DIR"
echo "   Next: re-delegate to Smith via sessions_send agent:smith:main"
