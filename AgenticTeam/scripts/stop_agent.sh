#!/usr/bin/env bash
# Stop a stuck named agent session via OpenClaw
# Usage: bash stop_agent.sh <agent-name>
# Agent names: smith niaobe architect morpheus oracle

AGENT="${1:-}"

if [ -z "$AGENT" ]; then
  echo "Usage: stop_agent.sh <agent-name>"
  echo "Agents: smith niaobe architect morpheus oracle"
  exit 1
fi

echo "Stopping session: agent:${AGENT}:main"

# Send REPLY_SKIP — causes the agent to abandon its current turn immediately
openclaw agent --agent "$AGENT" --message "REPLY_SKIP" 2>/dev/null \
  && echo "OK: REPLY_SKIP sent to ${AGENT} — current turn will end" \
  || echo "WARN: Could not reach ${AGENT} (may already be idle)"

# Show any running subagent runs for this agent
python3 - "$AGENT" << 'PYEOF'
import json, os, sys
agent = sys.argv[1]
path = os.path.expanduser('~/.openclaw/subagents/runs.json')
if not os.path.exists(path):
    print("  No subagent run records found")
    raise SystemExit(0)
with open(path) as f:
    d = json.load(f)
runs = d.get('runs', {})
active = [
    (rid, r) for rid, r in runs.items()
    if agent in r.get('controllerSessionKey', '')
    and r.get('status') not in ('done', 'failed', 'cancelled', 'killed')
]
if not active:
    print(f"  No active subagent runs found for {agent}")
else:
    for rid, r in active:
        print(f"  Active: {rid[:24]}  child={r.get('childSessionKey','?')[:44]}")
PYEOF

echo ""
echo "Done. Re-delegate work to ${AGENT} when ready."
