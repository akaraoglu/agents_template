#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_PROMPT="$*"

extract_meta_field() {
  local key="$1"
  printf '%s\n' "$TASK_PROMPT" | awk -v key="$key" '
    /^LATEST_HANDOFF:$/ { inblock=1; next }
    inblock && /^THREAD_TRANSCRIPT:$/ { exit }
    inblock && $0 ~ "^- " key ": " {
      sub("^- " key ": ", "")
      print
      exit
    }
  '
}

extract_section() {
  local section_name="$1"
  python3 -c '
import re
import sys

section = sys.argv[1]
text = sys.stdin.read()
header_pattern = re.compile(rf"^(?:\*\*)?{re.escape(section)}:(?:\*\*)?[ \t]*(.*)$")
next_header_pattern = re.compile(r"^(?:\*\*)?[A-Z_]+:(?:\*\*)?[ \t]*(?:$)")
lines = text.splitlines()

for idx, line in enumerate(lines):
    match = header_pattern.match(line)
    if not match:
        continue
    inline_value = match.group(1).strip()
    if inline_value:
        print(inline_value)
        sys.exit(0)

    collected = []
    for next_line in lines[idx + 1:]:
        if next_header_pattern.match(next_line):
            break
        collected.append(next_line)
    print("\n".join(collected).strip())
    sys.exit(0)

sys.exit(1)
' "$section_name"
}

TEAM_OUTPUT="$("$ROOT_DIR/.agents/run_team.sh" "$TASK_PROMPT")"

HANDOFF_FROM="$(extract_meta_field from | tr '[:upper:]' '[:lower:]')"
HANDOFF_TO="$(extract_meta_field to | tr '[:upper:]' '[:lower:]')"
PROJECT_SLUG="$(extract_meta_field project)"
OUTCOME="$(printf '%s' "$TEAM_OUTPUT" | extract_section OUTCOME 2>/dev/null || true)"
NEXT_STEPS="$(printf '%s' "$TEAM_OUTPUT" | extract_section NEXT_STEPS 2>/dev/null || true)"

if [[ -z "$PROJECT_SLUG" ]]; then
  PROJECT_SLUG="n/a"
fi
if [[ -z "$OUTCOME" ]]; then
  OUTCOME="Morpheus completed the current software execution pass."
fi
if [[ -z "$NEXT_STEPS" ]]; then
  NEXT_STEPS="Review the software-team result and decide whether to accept, request rework, or continue validation."
fi

printf '%s\n' "$TEAM_OUTPUT"

if [[ "$HANDOFF_FROM" == "niaobe" && "$HANDOFF_TO" == "morpheus" ]]; then
  cat <<EOF

TYPE: HANDOFF
FROM: Morpheus
TO: Niaobe
PROJECT: $PROJECT_SLUG
SUMMARY: $OUTCOME
NEXT: Review the software execution result above and decide the next project action. Internal next steps: $NEXT_STEPS
EOF
fi
