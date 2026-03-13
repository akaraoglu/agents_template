#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 \"team task\"" >&2
  exit 1
fi

USER_TASK="$*"

extract_section() {
  local section_name="$1"
  python3 -c '
import re
import sys

section = sys.argv[1]
text = sys.stdin.read()
pattern = rf"{re.escape(section)}:\n(.*?)(?=\n[A-Z_]+:\n|\Z)"
match = re.search(pattern, text, flags=re.S)
if not match:
    sys.exit(1)
print(match.group(1).strip())
' "$section_name"
}

ASSIGNMENT_PROMPT="You are assigning work for the local OpenClaw team.

Return exactly in this format:
PLAN_SUMMARY:
<short summary>

PLANNER_NEEDED:
<yes or no>

PLANNER_TASK:
<concrete planner task or NONE>

CODER_TASK:
<concrete coder task>

TESTER_TASK:
<concrete tester task>

SUCCESS_CRITERIA:
<project-relevant success criteria>"

ASSIGNMENT_OUTPUT="$("$ROOT_DIR/.agents/run_manager.sh" "User task:
$USER_TASK

$ASSIGNMENT_PROMPT")"

PLAN_SUMMARY="$(printf '%s' "$ASSIGNMENT_OUTPUT" | extract_section PLAN_SUMMARY)"
PLANNER_NEEDED="$(printf '%s' "$ASSIGNMENT_OUTPUT" | extract_section PLANNER_NEEDED | tr '[:upper:]' '[:lower:]')"
PLANNER_TASK="$(printf '%s' "$ASSIGNMENT_OUTPUT" | extract_section PLANNER_TASK)"
CODER_TASK="$(printf '%s' "$ASSIGNMENT_OUTPUT" | extract_section CODER_TASK)"
TESTER_TASK="$(printf '%s' "$ASSIGNMENT_OUTPUT" | extract_section TESTER_TASK)"
SUCCESS_CRITERIA="$(printf '%s' "$ASSIGNMENT_OUTPUT" | extract_section SUCCESS_CRITERIA)"

PLANNER_OUTPUT="NONE"
if [[ "$PLANNER_NEEDED" == "yes" && "$PLANNER_TASK" != "NONE" ]]; then
  PLANNER_OUTPUT="$("$ROOT_DIR/.agents/run_planner.sh" "$PLANNER_TASK")"
fi

CODER_PROMPT="$CODER_TASK"$'\n\n'"Manager plan summary:
$PLAN_SUMMARY"$'\n\n'"Success criteria:
$SUCCESS_CRITERIA"
if [[ "$PLANNER_OUTPUT" != "NONE" ]]; then
  CODER_PROMPT+=$'\n\n'"Planner output:
$PLANNER_OUTPUT"
fi
CODER_OUTPUT="$("$ROOT_DIR/.agents/run_coder.sh" "$CODER_PROMPT")"

TESTER_PROMPT="$TESTER_TASK"$'\n\n'"Manager plan summary:
$PLAN_SUMMARY"$'\n\n'"Success criteria:
$SUCCESS_CRITERIA"
if [[ "$PLANNER_OUTPUT" != "NONE" ]]; then
  TESTER_PROMPT+=$'\n\n'"Planner output:
$PLANNER_OUTPUT"
fi
TESTER_PROMPT+=$'\n\n'"Coder output for context:
$CODER_OUTPUT"
TESTER_OUTPUT="$("$ROOT_DIR/.agents/run_tester.sh" "$TESTER_PROMPT")"

SYNTHESIS_PROMPT="User task:
$USER_TASK

Plan summary:
$PLAN_SUMMARY

Success criteria:
$SUCCESS_CRITERIA

Planner output:
$PLANNER_OUTPUT

Coder output:
$CODER_OUTPUT

Tester output:
$TESTER_OUTPUT

Return exactly in this format:
OUTCOME:
<short outcome>

PLANNER:
<short planner summary or NONE>

CODER:
<short coder summary>

TESTER:
<short tester summary>

NEXT_STEPS:
<follow-up steps or NONE>"

exec "$ROOT_DIR/.agents/run_manager.sh" "$SYNTHESIS_PROMPT"
