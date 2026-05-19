#!/usr/bin/env bash
# Usage: bash new_project.sh "<project-title>"
# Creates a new project folder in clawspace/projects/active/
# Called by NEO when a new project is ready to hand off to Smith.

set -euo pipefail

TITLE="${1:-unnamed}"
DATE=$(date +%Y%m%d-%H%M)
SLUG=$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | cut -c1-40)
PROJECT_ID="${SLUG}-${DATE}"
BASE="/home/alik/workspace/clawspace/projects/active/${PROJECT_ID}"
TEMPLATES="/home/alik/workspace/agent_template_new/AgenticTeam/templates"

mkdir -p "$BASE"/{design,implementation,tests}

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

# SPEC.md — Neo writes a draft architecture/planning document
cat > "$BASE/SPEC.md" << HEREDOC
# Spec Draft: ${TITLE}
**project_id**: ${PROJECT_ID}

## System Overview
<!-- High-level description of what gets built -->

## Components
<!-- List the main pieces -->
-

## Data / File Structure
<!-- What files/folders will be created by implementation -->

## Open Questions
<!-- Things Neo is unsure about — Smith or Architect should resolve -->
-
HEREDOC

# STATE.md — Smith will fill this in after receiving the project
sed "s/{{PROJECT_ID}}/${PROJECT_ID}/g; s/{{TITLE}}/${TITLE}/g; s/{{DATE}}/${DATE}/g" \
  "$TEMPLATES/STATE.md" > "$BASE/STATE.md"

REGISTRY="/home/alik/workspace/clawspace/projects/registry.json"
CONTEXT="$BASE/CONTEXT.json"
NEO_ANCHOR="/home/alik/workspace/clawspace/workspaces/neo/.current_project.json"
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if python3 - "$PROJECT_ID" "$BASE" "$TITLE" "$NOW" "$REGISTRY" "$CONTEXT" "$NEO_ANCHOR" <<'PY'
import json
import pathlib
import sys

project_id, base, title, now, registry_path, context_path, neo_anchor_path = sys.argv[1:]

registry_payload = {
    "version": 1,
    "active_project": {
        "id": project_id,
        "path": base,
        "name": title,
        "started_at": now,
    },
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
    (registry_path, registry_payload),
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

echo "✅ Project created: $BASE"
echo "   Files: PROJECT.md, SPEC.md, STATE.md, CONTEXT.json"
echo ""
echo "Next steps for Neo:"
echo "  1. Fill in $BASE/PROJECT.md (requirements, acceptance criteria)"
echo "  2. Fill in $BASE/SPEC.md (draft architecture)"
echo "  3. Run handoff.sh and use the printed ENVELOPE for sessions_send to Smith"
echo "  4. Post to #projects: '🚀 Project ${PROJECT_ID} started. Handing to Smith.'"
echo "  5. Go idle — do not follow up."