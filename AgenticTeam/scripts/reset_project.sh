#!/usr/bin/env bash
# Reset a project's STATE.md and optionally wipe implementation artifacts
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

# Reset STATE.md
if [ -f "$TEMPLATES/STATE.md" ]; then
  sed "s/{{PROJECT_ID}}/$PROJECT_ID/g; s/{{TITLE}}/$TITLE/g; s/{{DATE}}/$DATE/g" \
    "$TEMPLATES/STATE.md" > "$PROJECT_DIR/STATE.md"
  echo "   ✅ STATE.md reset"
else
  cat > "$PROJECT_DIR/STATE.md" << HEREDOC
# State: $PROJECT_ID
phase: RESET
reset_at: $DATE
waiting_for: smith
HEREDOC
  echo "   ✅ STATE.md reset (no template)"
fi

if [ "$HARD" = "--hard" ]; then
  echo "   🗑️  Hard reset: removing artifacts..."
  rm -rf "$PROJECT_DIR/implementation" "$PROJECT_DIR/tests" \
         "$PROJECT_DIR/design" "$PROJECT_DIR/VALIDATION.md" \
         "$PROJECT_DIR/DONE.md"
  mkdir -p "$PROJECT_DIR"/{design,implementation,tests}
  echo "   ✅ implementation/, tests/, design/ cleared"
fi

echo ""
echo "✅ Reset complete: $PROJECT_DIR"
echo "   Next: re-delegate to Smith via sessions_send agent:smith:main"
