#!/usr/bin/env bash
# List all active projects with status — for Neo to call
# Usage: bash list_projects.sh

PROJECTS_DIR="/home/alik/workspace/clawspace/projects/active"

if [ ! -d "$PROJECTS_DIR" ]; then
  echo "No projects directory found at $PROJECTS_DIR"
  exit 0
fi

count=0
echo "=== Active Projects ==="
echo ""

for d in "$PROJECTS_DIR"/*/; do
  [ -d "$d" ] || continue
  id=$(basename "$d")
  count=$((count + 1))

  echo "📁 $id"
  echo "   Path: $d"

  # STATE.md
  if [ -f "$d/STATE.md" ]; then
    phase=$(grep -E "^phase:|^\*\*phase\*\*:|^- phase:" "$d/STATE.md" 2>/dev/null | head -1 | sed 's/.*: *//')
    waiting=$(grep -E "^waiting_for:|^\*\*waiting_for\*\*:" "$d/STATE.md" 2>/dev/null | head -1 | sed 's/.*: *//')
    [ -n "$phase" ]   && echo "   Phase: $phase"
    [ -n "$waiting" ] && echo "   Waiting for: $waiting"
  else
    echo "   STATE.md: missing"
  fi

  # PROJECT.md goal line
  if [ -f "$d/PROJECT.md" ]; then
    goal=$(grep -A1 "^## Goal" "$d/PROJECT.md" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//' | grep -v "^$\|^#\|<!-")
    [ -n "$goal" ] && echo "   Goal: $goal"
  fi

  # VALIDATION.md result
  if [ -f "$d/VALIDATION.md" ]; then
    overall=$(grep -E "^- overall:|^overall:" "$d/VALIDATION.md" 2>/dev/null | head -1 | sed 's/.*: *//')
    [ -n "$overall" ] && echo "   Validation: $overall"
  fi

  # Last modified file
  last=$(find "$d" -maxdepth 2 -type f -newer "$d/PROJECT.md" 2>/dev/null | head -1)
  [ -n "$last" ] && echo "   Last change: $(basename $last)"

  echo ""
done

echo "Total: $count project(s)"
