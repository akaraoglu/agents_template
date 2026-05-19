#!/usr/bin/env bash
# Show team agent session status — for Neo to call
# Usage: bash team_status.sh

MM_URL="http://localhost:8065"
ENV_FILE="/home/alik/workspace/agent_template_new/AgenticTeam/.env"
PROJECTS_DIR="/home/alik/workspace/clawspace/projects/active"

get_token() {
  grep -i "^MM_${1^^}_TOKEN" "$ENV_FILE" | cut -d= -f2 | tr -d '"' | tr -d ' '
}

echo "=== AgenticTeam Status — $(date '+%Y-%m-%d %H:%M') ==="
echo ""

# Agent last-seen via Mattermost (last post timestamp)
for agent in neo smith niaobe architect morpheus oracle; do
  token=$(get_token "$agent")
  [ -z "$token" ] && continue

  # Get user info
  user_info=$(curl -sf -H "Authorization: Bearer $token" "$MM_URL/api/v4/users/me" 2>/dev/null)
  user_id=$(echo "$user_info" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id','?'))" 2>/dev/null)

  # Get most recent post by this agent via search
  recent=$(curl -sf -H "Authorization: Bearer $token" \
    "$MM_URL/api/v4/posts/search" \
    -X POST -H "Content-Type: application/json" \
    -d "{\"terms\":\"from:$agent\",\"is_or_search\":false,\"per_page\":1}" 2>/dev/null | \
    python3 -c "
import sys,json,datetime
try:
  d=json.load(sys.stdin)
  posts=d.get('posts',{})
  order=d.get('order',[])
  if order and order[0] in posts:
    p=posts[order[0]]
    ts=datetime.datetime.fromtimestamp(p['create_at']/1000)
    diff=int((datetime.datetime.now()-ts).total_seconds()//60)
    snippet=p['message'][:50].replace('\n',' ')
    print(f'{diff}m ago — {snippet}')
  else:
    print('no posts yet')
except: print('unknown')
" 2>/dev/null)

  printf "  %-12s last post: %s\n" "@$agent" "${recent:-unknown}"
done

echo ""
echo "=== Active Projects ==="
echo ""

python3 - "$PROJECTS_DIR" "/home/alik/workspace/clawspace/projects/registry.json" <<'PYEOF'
import json
import pathlib
import re
import sys
from datetime import UTC, datetime

projects_dir = pathlib.Path(sys.argv[1])
registry_path = pathlib.Path(sys.argv[2])

try:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
except Exception:
    registry = {"projects": {}}

project_entries = dict(registry.get("projects") or {})

def extract_state_field(state_text: str, names: tuple[str, ...]) -> str:
    for raw_line in state_text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        for name in names:
            if lowered.startswith(f"{name.lower()}:"):
                return line.split(":", 1)[1].strip()
            match = re.match(rf"^- \*\*{re.escape(name.lower())}\*\*: (.+)$", lowered)
            if match:
                return raw_line.split(":", 1)[1].strip()
    return ""

for project_dir in sorted([p for p in projects_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
    project_id = project_dir.name
    phase = "unknown"
    waiting = ""
    state_file = project_dir / "STATE.md"
    if state_file.exists():
        state_text = state_file.read_text(encoding="utf-8")
        phase = extract_state_field(state_text, ("phase",)) or "unknown"
        waiting = extract_state_field(state_text, ("waiting_for",))

    extras = []
    entry = dict(project_entries.get(project_id) or {})
    pending = entry.get("pending_receipt") or {}
    if str(pending.get("status", "")).strip().lower() == "pending" and pending.get("sent_at"):
        try:
            sent_at = datetime.fromisoformat(str(pending["sent_at"]).replace("Z", "+00:00"))
            age_minutes = int((datetime.now(UTC) - sent_at).total_seconds() // 60)
        except Exception:
            age_minutes = -1
        label = "OVERDUE" if age_minutes >= 5 else "pending"
        target = str(pending.get("to", "?")).strip()
        if age_minutes >= 0:
            extras.append(f"receipt={label}:{target}({age_minutes}m)")
        else:
            extras.append(f"receipt={label}:{target}")

    suffix = f" {' '.join(extras)}" if extras else ""
    if waiting:
        print(f"  📁 {project_id:<35} phase={phase:<15} waiting={waiting}{suffix}")
    else:
        print(f"  📁 {project_id:<35} phase={phase}{suffix}")
PYEOF

echo ""
# Show openclaw subagent runs
RUNS_FILE="$HOME/.openclaw/subagents/runs.json"
if [ -f "$RUNS_FILE" ]; then
  python3 - << 'PYEOF'
import json, os, datetime
with open(os.path.expanduser('~/.openclaw/subagents/runs.json')) as f:
    d = json.load(f)
runs = d.get('runs', {})
active = [(rid, r) for rid, r in runs.items() if r.get('status') not in ('done','failed','cancelled','killed')]
print(f"Sub-agent runs: {len(runs)} total, {len(active)} active")
for rid, r in list(runs.items())[-3:]:
    req = r.get('request', {})
    print(f"  {rid[:16]}  agent={req.get('agent','?')}  status={r.get('status','?')}")
PYEOF
fi
