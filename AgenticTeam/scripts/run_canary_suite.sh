#!/usr/bin/env bash
# Usage: bash run_canary_suite.sh

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"
PHASE_RUNNER="$REPO_ROOT/AgenticTeam/scripts/run_openclaw_phase_canary.sh"
E2E_RUNNER="$REPO_ROOT/AgenticTeam/scripts/run_e2e_fibonacci_test.sh"
PREFLIGHT_ONLY=0
SKIP_E2E=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preflight-only)
      PREFLIGHT_ONLY=1
      shift
      ;;
    --skip-e2e)
      SKIP_E2E=1
      shift
      ;;
    *)
      break
      ;;
  esac
done

REPORT_DIR="${1:-$HOME/.copilot/session-state/27757261-2eab-44e0-a711-3a33df12c25c/files/canary-suite}"

mkdir -p "$REPORT_DIR"
SUMMARY_ROWS="$REPORT_DIR/.summary_rows.jsonl"
: > "$SUMMARY_ROWS"

phases=(
  neo_project_create
  smith_langgraph_autoplan_required_plan
  smith_planning
  smith_niaobe_handoff
  architect_worker_runtime
  architect_missing_draft_repair
  morpheus_direct_implementation
  oracle_verification
)

overall=0

run_suite_preflight() {
  "$REPO_ROOT/env-python/bin/python" - "$REPORT_DIR" <<'PY'
import json
import sys
from pathlib import Path

report_dir = Path(sys.argv[1])
report_dir.mkdir(parents=True, exist_ok=True)
repo_root = Path("/home/alik/workspace/agent_template_new")
script_root = repo_root / "AgenticTeam" / "scripts"
if str(script_root) not in sys.path:
    sys.path.insert(0, str(script_root))

from canaries.common import detect_sync_drift, gateway_is_listening, ollama_preflight, session_freshness, wait_for_session_quiescence

agents = ["neo", "smith", "niaobe", "architect", "morpheus", "oracle"]
sync = detect_sync_drift(agents)
sessions = {}
status = "PASS"
failures = []
warnings = []
for agent in agents:
    freshness = session_freshness(agent)
    quiescence = wait_for_session_quiescence(agent, timeout_seconds=8, poll_seconds=2, stable_polls=2)
    sessions[agent] = {"session_freshness": freshness, "quiescence": quiescence}
    if quiescence["outcome"] == "no_session":
        status = "FAIL"
        failures.append(f"{agent}: main session missing")
    if freshness == "stale":
        warnings.append(f"{agent}: stale session")
    if quiescence["outcome"] not in {"already_quiescent"}:
        status = "FAIL"
        failures.append(f"{agent}: preflight drain outcome={quiescence['outcome']}")
if sync["sync_drift"] != "no":
    status = "FAIL"
    failures.append(f"sync_drift={sync['sync_drift']}")
if not gateway_is_listening():
    status = "FAIL"
    failures.append("gateway is not listening")
payload = {
    "status": status,
    "sync": sync,
    "gateway_listening": "yes" if gateway_is_listening() else "no",
    "ollama": ollama_preflight(),
    "sessions": sessions,
    "failures": failures,
    "warnings": warnings,
}
(report_dir / "preflight.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
lines = [
    "# Canary Suite Preflight",
    "",
    f"- **status**: `{status}`",
    f"- **gateway_listening**: `{payload['gateway_listening']}`",
    f"- **sync_drift**: `{sync['sync_drift']}`",
    "",
    "## Failures",
    "",
]
if failures:
    lines.extend(f"- {item}" for item in failures)
else:
    lines.append("- none")
lines.extend(["", "## Warnings", ""])
if warnings:
    lines.extend(f"- {item}" for item in warnings)
else:
    lines.append("- none")
lines.extend(
    [
        "",
        "## Sessions",
        "",
        "```json",
        json.dumps(sessions, indent=2, sort_keys=True),
        "```",
    ]
)
(report_dir / "preflight.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
raise SystemExit(0 if status == "PASS" else 1)
PY
}

read_status() {
  local report_file="$1"
  local command_status="$2"
  "$REPO_ROOT/env-python/bin/python" - "$report_file" "$command_status" <<'PY'
import json
import re
import sys
from pathlib import Path

report_file = Path(sys.argv[1])
command_status = int(sys.argv[2])
json_path = report_file.with_suffix(".json")
if json_path.exists():
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    print(payload.get("status", "FAIL"))
else:
    print("PASS" if command_status == 0 else "FAIL")
PY
}

append_summary_row() {
  local label="$1"
  local report_file="$2"
  local command_status="$3"
  "$REPO_ROOT/env-python/bin/python" - "$label" "$report_file" "$command_status" "$SUMMARY_ROWS" <<'PY'
import json
import re
import sys
from pathlib import Path

label = sys.argv[1]
report_file = Path(sys.argv[2])
command_status = int(sys.argv[3])
summary_rows = Path(sys.argv[4])
row = {
    "canary": label,
    "status": "PASS" if command_status == 0 else "FAIL",
    "first_failed": None,
    "fault_layer": "unknown",
    "project_id": "unknown",
    "report_file": str(report_file),
}
json_path = report_file.with_suffix(".json")
if json_path.exists():
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    first_failed = payload.get("first_failed_invariant") or {}
    row.update(
        {
            "status": payload.get("status", row["status"]),
            "first_failed": first_failed.get("detail"),
            "fault_layer": payload.get("suggested_fault_layer", "unknown"),
            "project_id": payload.get("project_id", "unknown"),
        }
    )
elif report_file.exists():
    text = report_file.read_text(encoding="utf-8")
    match = re.search(r"\*\*project_id\*\*: `([^`]+)`", text)
    if match:
        row["project_id"] = match.group(1)
    finding = re.search(r"^\d+\.\s+(.+)$", text, re.MULTILINE)
    if finding:
        row["first_failed"] = finding.group(1)
with summary_rows.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(row, sort_keys=True) + "\n")
PY
}

write_suite_summary() {
  "$REPO_ROOT/env-python/bin/python" - "$SUMMARY_ROWS" "$REPORT_DIR" <<'PY'
import json
import sys
from pathlib import Path

rows_path = Path(sys.argv[1])
report_dir = Path(sys.argv[2])
rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
(report_dir / "summary.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
lines = [
    "# Canary Suite Summary",
    "",
    "| canary | status | first_failed | fault_layer | project_id | report_file |",
    "| :--- | :--- | :--- | :--- | :--- | :--- |",
]
for row in rows:
    first_failed = (row.get("first_failed") or "none").replace("|", "/")
    lines.append(
        f"| {row['canary']} | {row['status']} | {first_failed} | {row.get('fault_layer', 'unknown')} | {row.get('project_id', 'unknown')} | {Path(row['report_file']).name} |"
    )
(report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

drain_suite_sessions() {
  local label="$1"
  "$REPO_ROOT/env-python/bin/python" - "$REPORT_DIR" "$label" <<'PY'
import json
import sys
from pathlib import Path

report_dir = Path(sys.argv[1])
label = sys.argv[2]
repo_root = Path("/home/alik/workspace/agent_template_new")
script_root = repo_root / "AgenticTeam" / "scripts"
if str(script_root) not in sys.path:
    sys.path.insert(0, str(script_root))

import subprocess

from canaries.common import wait_for_session_quiescence

agents = ["neo", "smith", "niaobe", "architect", "morpheus", "oracle"]
results = {
    agent: wait_for_session_quiescence(agent, timeout_seconds=12, poll_seconds=2, stable_polls=1)
    for agent in agents
}
needs_skip = [
    agent
    for agent, payload in results.items()
    if agent != "neo"
    if payload["outcome"] not in {"no_session", "already_quiescent", "drained"}
]
for agent in needs_skip:
    try:
        subprocess.run(
            ["openclaw", "agent", "--agent", agent, "--message", "REPLY_SKIP"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=12,
        )
    except subprocess.TimeoutExpired:
        pass
if needs_skip:
    results = {
        agent: wait_for_session_quiescence(agent, timeout_seconds=24, poll_seconds=2, stable_polls=2)
        for agent in agents
    }
(report_dir / f"session-drain-{label}.json").write_text(
    json.dumps(results, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
bad = {
    agent: payload
    for agent, payload in results.items()
    if payload["outcome"] not in {"no_session", "already_quiescent", "drained"}
    and not (payload["outcome"] == "timeout" and payload["line_count_delta"] == 0 and payload["status"] in {"done", "timeout"})
}
if bad:
    print(json.dumps(bad, indent=2, sort_keys=True))
    raise SystemExit(1)
PY
}

run_phase() {
  local label="$1"
  local report_file="$2"
  shift
  shift
  local command_status=0
  drain_suite_sessions "before-$label" || true
  if "$@" > /tmp/openclaw-canary-suite-step.txt 2>&1; then
    command_status=0
  else
    command_status=$?
  fi
  drain_suite_sessions "after-$label" || true
  local status
  status="$(read_status "$report_file" "$command_status")"
  printf "%s: %s\n" "$label" "$status"
  append_summary_row "$label" "$report_file" "$command_status"
  if [[ "$status" == "FAIL" ]]; then
    overall=1
  fi
}

if [[ "$PREFLIGHT_ONLY" == "1" ]]; then
  run_suite_preflight
  exit $?
fi

for phase in "${phases[@]}"; do
  run_phase "$phase" "$REPORT_DIR/$phase.md" bash "$PHASE_RUNNER" --phase "$phase" --report-file "$REPORT_DIR/$phase.md"
done

if [[ "$SKIP_E2E" != "1" ]]; then
  run_phase "fibonacci_e2e" "$REPORT_DIR/fibonacci_e2e.md" bash "$E2E_RUNNER" --report-file "$REPORT_DIR/fibonacci_e2e.md"
fi

write_suite_summary

exit "$overall"
