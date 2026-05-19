#!/usr/bin/env bash
# Usage: ./scripts/test_mm.sh
# Tests that each bot token is valid and sends a DM via system-bot (not admin credentials).

set -euo pipefail
source "$(dirname "$0")/../.env"

MM_URL="${MATTERMOST_URL:-http://localhost:8065}"

declare -A TOKENS=(
  [neo]="$MM_NEO_TOKEN"
  [smith]="$MM_SMITH_TOKEN"
  [niaobe]="$MM_NIAOBE_TOKEN"
  [architect]="$MM_ARCHITECT_TOKEN"
  [morpheus]="$MM_MORPHEUS_TOKEN"
  [oracle]="$MM_ORACLE_TOKEN"
)

# system-bot is used for sending test DMs — no admin credentials needed
SYSTEM_TOKEN="${MM_SYSTEM_BOT_TOKEN}"
SYSTEM_ID="${MM_SYSTEM_BOT_USER_ID}"

echo "=== Mattermost Bot Token Test ==="
echo "Server: $MM_URL"
echo "Test sender: @system-bot (ID: $SYSTEM_ID)"
echo ""

# Verify system-bot token first
SYS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer ${SYSTEM_TOKEN}" "${MM_URL}/api/v4/users/me")
if [[ "$SYS_STATUS" != "200" ]]; then
  echo "❌ system-bot token invalid (HTTP $SYS_STATUS) — update MM_SYSTEM_BOT_TOKEN in .env"
  exit 1
fi
echo "✅ @system-bot — valid"
echo ""

for agent in neo smith niaobe architect morpheus oracle; do
  TOKEN="${TOKENS[$agent]}"
  RESULT=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${MM_URL}/api/v4/users/me")

  if [[ "$RESULT" == "200" ]]; then
    BOT_ID=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
      "${MM_URL}/api/v4/users/me" \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
    echo "✅ @${agent} — valid (id: ${BOT_ID})"

    # Open DM channel from system-bot to this agent, then send a ping
    CH_ID=$(curl -s -X POST \
      -H "Authorization: Bearer ${SYSTEM_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "[\"${SYSTEM_ID}\",\"${BOT_ID}\"]" \
      "${MM_URL}/api/v4/channels/direct" \
      | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

    if [[ -n "$CH_ID" ]]; then
      MSG=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "Authorization: Bearer ${SYSTEM_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"channel_id\":\"${CH_ID}\",\"message\":\"🤖 system-bot ping → @${agent} token test OK\"}" \
        "${MM_URL}/api/v4/posts")
      [[ "$MSG" == "201" ]] && echo "   📨 DM sent to @${agent}" || echo "   ⚠️  DM failed (HTTP $MSG)"
    fi
  else
    echo "❌ @${agent} — INVALID token (HTTP $RESULT)"
  fi
done

echo ""
echo "=== Done ==="
