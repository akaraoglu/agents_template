#!/bin/bash
# Post a message to the #projects channel as a named agent
# Usage: mm_post.sh <agent_name> "<message>"
# Agent names: neo, smith, niaobe, architect, morpheus, oracle

AGENT="${1,,}"   # lowercase
MESSAGE="$2"
PROJECTS_CHAN="juey9jeq1tr6dnj8fm57k739ay"
MM_URL="http://localhost:8065"
ENV_FILE="/home/alik/workspace/agent_template_new/AgenticTeam/.env"

TOKEN=$(grep -i "^MM_${AGENT}_TOKEN" "$ENV_FILE" | cut -d= -f2 | tr -d '"' | tr -d ' ')
if [ -z "$TOKEN" ]; then
  echo "ERROR: No token for agent '$AGENT' in $ENV_FILE" >&2
  exit 1
fi

JSON=$(python3 -c "import json,sys; print(json.dumps({'channel_id':'$PROJECTS_CHAN','message':sys.stdin.read().strip()}))" <<< "$MESSAGE")
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$JSON" \
  "$MM_URL/api/v4/posts"
echo " — posted to #projects as @$AGENT"
