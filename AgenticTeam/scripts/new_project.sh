#!/usr/bin/env bash
# Usage: bash new_project.sh "<project-title>"
# Creates a new task-oriented project folder in clawspace/projects/active/
# Called by Neo when a new project is ready to hand off to Smith.

set -euo pipefail

TITLE="${1:-unnamed}"
DATE=$(date +%Y%m%d-%H%M)
SLUG=$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | cut -c1-40)
PROJECT_ID="${SLUG}-${DATE}"
BASE="/home/alik/workspace/clawspace/projects/active/${PROJECT_ID}"
TEMPLATES="/home/alik/workspace/agent_template_new/AgenticTeam/templates"

mkdir -p \
  "$BASE"/management/{tasks,architecture,validation,DECISIONS,wayback} \
  "$BASE"/{src,tests}

# PROJECT.md — Neo fills this with goal, requirements, acceptance criteria
cat > "$BASE/PROJECT.md" << HEREDOC
# Project: ${TITLE}
**project_id**: ${PROJECT_ID}
**created**: ${DATE}
**created_by**: neo

## Goal
<!-- What are we building and why? -->

## Requirements
<!-- What must be true for this to be done? -->
-

## Acceptance Criteria
<!-- Verifiable conditions Oracle will check -->
-

## Out of Scope
-

## Tech Stack
- Python 3.12 / venv-claw: /home/alik/workspace/clawspace/venv-claw/bin/python3
-

## Notes from Master
<!-- Any extra context -->
HEREDOC

# PROJECT_STATE.md — canonical shared machine state
sed "s/{{PROJECT_ID}}/${PROJECT_ID}/g; s/{{TITLE}}/${TITLE}/g; s/{{DATE}}/${DATE}/g" \
  "$TEMPLATES/PROJECT_STATE.md" > "$BASE/PROJECT_STATE.md"

# CURRENT_TASK.md — active human-readable work order
sed "s/{{PROJECT_ID}}/${PROJECT_ID}/g; s/{{TITLE}}/${TITLE}/g; s/{{DATE}}/${DATE}/g" \
  "$TEMPLATES/CURRENT_TASK.md" > "$BASE/CURRENT_TASK.md"

# BRIEF.md — short human-readable project brief
sed "s/{{PROJECT_ID}}/${PROJECT_ID}/g; s/{{ONE_PARAGRAPH_DESCRIPTION}}/${TITLE}/g" \
  "$TEMPLATES/BRIEF.md" > "$BASE/BRIEF.md"

# RESULT.md — final summary placeholder
sed "s/{{PROJECT_ID}}/${PROJECT_ID}/g; s/{{TITLE}}/${TITLE}/g; s/{{DATE}}/${DATE}/g" \
  "$TEMPLATES/RESULT.md" > "$BASE/RESULT.md"

# Planning scaffolding owned by Smith
cat > "$BASE/management/PLAN.md" << HEREDOC
# Plan: ${TITLE}
**project_id**: ${PROJECT_ID}

## Roadmap
<!-- Smith turns the project into sequential tasks T001, T002, ... -->

| Task | Title | Status | Notes |
| :--- | :---- | :----- | :---- |
HEREDOC

cat > "$BASE/management/BACKLOG.md" << HEREDOC
# Backlog: ${TITLE}
**project_id**: ${PROJECT_ID}

## Ready Queue
<!-- Smith lists unstarted tasks here in sequence order -->

- none
HEREDOC

REGISTRY="/home/alik/workspace/clawspace/projects/registry.json"
CONTEXT="$BASE/CONTEXT.json"
NEO_ANCHOR="/home/alik/workspace/clawspace/workspaces/neo/.current_project.json"
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if python3 - "$PROJECT_ID" "$BASE" "$TITLE" "$NOW" "$REGISTRY" "$CONTEXT" "$NEO_ANCHOR" <<'PY'
import json
import pathlib
import sys

project_id, base, title, now, registry_path, context_path, neo_anchor_path = sys.argv[1:]
registry_file = pathlib.Path(registry_path)

if registry_file.exists():
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        registry = {"version": 1, "projects": {}}
else:
    registry = {"version": 1, "projects": {}}

projects = dict(registry.get("projects") or {})
legacy = registry.get("active_project")
if legacy and legacy.get("id") and legacy.get("path"):
    projects.setdefault(
        legacy["id"],
        {
            "path": legacy["path"],
            "name": legacy.get("name", legacy["id"]),
            "status": "active",
            "created_at": legacy.get("started_at", now),
            "last_updated": registry.get("last_updated", now),
        },
    )

projects[project_id] = {
    "path": base,
    "project_root": base,
    "name": title,
    "status": "active",
    "created_at": now,
    "last_updated": now,
}

registry_payload = {
    "version": 1,
    "projects": projects,
    "latest_project_id": project_id,
    "last_updated": now,
}

anchor_payload = {
    "version": 1,
    "project": {
        "id": project_id,
        "path": base,
        "name": title,
        "started_at": now,
    },
    "assigned_by": "new_project.sh",
    "assigned_to": "neo",
    "phase": "INIT",
    "last_updated": now,
}

for target, payload in (
    (registry_file, registry_payload),
    (context_path, anchor_payload),
    (neo_anchor_path, anchor_payload),
):
    path = pathlib.Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
then
  echo "✅ Registry updated: $REGISTRY"
  echo "✅ Context anchors updated: $CONTEXT, $NEO_ANCHOR"
else
  echo "⚠️  Registry/context update failed (project still created)"
fi

echo "✅ Project ID: $PROJECT_ID"
echo "✅ Project created: $BASE"
echo "   Files: PROJECT.md, PROJECT_STATE.md, BRIEF.md, CURRENT_TASK.md, RESULT.md, CONTEXT.json"
echo ""
echo "Next steps for Neo:"
echo "  1. Fill in $BASE/PROJECT.md (requirements, acceptance criteria)"
echo "  2. Run handoff.sh and use the printed ENVELOPE for sessions_send to Smith"
echo "  3. Smith will create PLAN.md, BACKLOG.md, and task files"
echo "  4. Post to #projects: '🚀 Project ${PROJECT_ID} started. Handing to Smith.'"
echo "  5. Go idle — do not follow up."
