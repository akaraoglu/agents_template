#!/usr/bin/env bash
# crash_monitor.sh — Tails openclaw logs and notifies Neo on fatal agent crashes.

set -euo pipefail

SEND_SCRIPT="/home/alik/workspace/clawspace/bin/send_envelope.sh"
LOG_CMD="openclaw logs --plain --follow"

echo "Starting crash monitor..."

# Avoid triggering multiple times for the same crash within a cooldown window
declare -A LAST_TRIGGERED

$LOG_CMD | while read -r line; do
  # Match: error diagnostic {"subsystem":"diagnostic"} lane task error: lane=nested:agent:smith:main durationMs=61996 error="Error: Cannot continue..."
  if [[ "$line" =~ lane\ task\ error:\ lane=[^:]*:agent:([^:]+).*error=\"([^\"]+)\" ]]; then
    AGENT="${BASH_REMATCH[1]}"
    ERROR_MSG="${BASH_REMATCH[2]}"
    
    NOW=$(date +%s)
    LAST=${LAST_TRIGGERED["$AGENT"]:-0}
    
    # 60 second cooldown per agent
    if (( NOW - LAST > 60 )); then
      LAST_TRIGGERED["$AGENT"]=$NOW
      
      echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Detected crash for $AGENT. Triggering Neo..."
      
      PAYLOAD=$(cat <<EOF
{
  "project_id": "SYSTEM",
  "from": "smith",
  "to": "neo",
  "phase": "BLOCKED",
  "instructions": "CRITICAL ALERT: Agent '$AGENT' just crashed with error: '$ERROR_MSG'. Please investigate using openclaw status and openclaw logs, then report to Master."
}
EOF
)
      # Trigger Neo in the background so we don't block the log reader
      bash "$SEND_SCRIPT" neo "$PAYLOAD" &
    fi
  fi
done
