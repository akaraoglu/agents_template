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

  state_file="$d/PROJECT_STATE.md"
  [ -f "$state_file" ] || state_file="$d/STATE.md"

  if [ -f "$state_file" ]; then
    owner=$(grep -E "^owner:|^- \*\*owner\*\*:" "$state_file" 2>/dev/null | head -1 | sed 's/.*: *//')
    phase=$(grep -E "^phase:|^- \*\*phase\*\*:" "$state_file" 2>/dev/null | head -1 | sed 's/.*: *//')
    task=$(grep -E "^active_task:|^- \*\*active_task\*\*:" "$state_file" 2>/dev/null | head -1 | sed 's/.*: *//')
    task_phase=$(grep -E "^task_phase:|^- \*\*task_phase\*\*:" "$state_file" 2>/dev/null | head -1 | sed 's/.*: *//')
    waiting=$(grep -E "^waiting_for:|^- \*\*waiting_for\*\*:" "$state_file" 2>/dev/null | head -1 | sed 's/.*: *//')
    [ -n "$owner" ]   && echo "   Owner: $owner"
    [ -n "$phase" ]   && echo "   Phase: $phase"
    [ -n "$task" ]    && [ "$task" != "none" ] && echo "   Active task: $task"
    [ -n "$task_phase" ] && [ "$task_phase" != "none" ] && echo "   Task phase: $task_phase"
    [ -n "$waiting" ] && echo "   Waiting for: $waiting"
  else
    echo "   PROJECT_STATE.md: missing"
  fi

  # PROJECT.md goal line
  if [ -f "$d/PROJECT.md" ]; then
    goal=$(grep -A1 "^## Goal" "$d/PROJECT.md" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//' | grep -v "^$\|^#\|<!-")
    [ -n "$goal" ] && echo "   Goal: $goal"
  fi

  if [ -f "$d/RESULT.md" ]; then
    overall=$(grep -E "^- status:|^\*\*status\*\*:|^status:" "$d/RESULT.md" 2>/dev/null | head -1 | sed 's/.*: *//')
    [ -n "$overall" ] && echo "   Result: $overall"
  fi

  # Last modified file
  last=$(find "$d" -maxdepth 2 -type f -newer "$d/PROJECT.md" 2>/dev/null | head -1)
  [ -n "$last" ] && echo "   Last change: $(basename $last)"

  echo ""
done

echo "Total: $count project(s)"
