#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENT_ID="${OPENCLAW_HOST_AGENT_ID:-neo}"
ROLE_NAME="${OPENCLAW_HOST_ROLE_NAME:-Neo}"
PROMPT_FILE="${OPENCLAW_HOST_PROMPT_FILE:-$ROOT_DIR/.agents/prompts/neo.txt}"
TASK=""
PROJECT_ROOT_ARG="${OPENCLAW_PROJECT_ROOT:-}"
PROJECT_SLUG_ARG="${OPENCLAW_PROJECT_SLUG:-}"

usage() {
  cat >&2 <<'EOF'
Usage: run_openai_oauth_host_runtime.sh [options] [task...]

Options:
  --agent <id>         OpenClaw isolated agent id (default: neo)
  --role <name>        Role label for status/context sections
  --prompt-file <path> Prompt file to prepend to the task
  --project-root <p>   Active project root on the host
  --project-slug <s>   Active project slug under projects/<slug>
  --task <text>        Explicit task text
EOF
}

resolve_project_root() {
  local requested_root="$1"
  local requested_slug="$2"
  local project_root="$ROOT_DIR"

  if [[ -n "$requested_root" ]]; then
    if [[ "$requested_root" != /* ]]; then
      requested_root="$ROOT_DIR/$requested_root"
    fi
    project_root="$(cd "$requested_root" && pwd)"
  elif [[ -n "$requested_slug" ]]; then
    project_root="$(cd "$ROOT_DIR/projects/$requested_slug" && pwd)"
  fi

  if [[ "$project_root" != "$ROOT_DIR" && "$project_root" != "$ROOT_DIR"/projects/* ]]; then
    echo "Active project root must be $ROOT_DIR or a child of $ROOT_DIR/projects." >&2
    exit 1
  fi

  printf '%s' "$project_root"
}

append_section() {
  local section_text="$1"
  if [[ -z "$section_text" ]]; then
    return
  fi
  if [[ -n "$MESSAGE" ]]; then
    MESSAGE+=$'\n\n'
  fi
  MESSAGE+="$section_text"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)
      AGENT_ID="${2:-}"
      shift 2
      ;;
    --role)
      ROLE_NAME="${2:-}"
      shift 2
      ;;
    --prompt-file)
      PROMPT_FILE="${2:-}"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT_ARG="${2:-}"
      shift 2
      ;;
    --project-slug)
      PROJECT_SLUG_ARG="${2:-}"
      shift 2
      ;;
    --task)
      TASK="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      TASK="${*:-$TASK}"
      break
      ;;
    *)
      if [[ -n "$TASK" ]]; then
        TASK+=" "
      fi
      TASK+="$1"
      shift
      ;;
  esac
done

ACTIVE_PROJECT_ROOT="$(resolve_project_root "$PROJECT_ROOT_ARG" "$PROJECT_SLUG_ARG")"
PROJECT_FILE="$ACTIVE_PROJECT_ROOT/PROJECT.md"
PROJECT_MANAGEMENT_DIR="$ACTIVE_PROJECT_ROOT/management"
if [[ "$ACTIVE_PROJECT_ROOT" == "$ROOT_DIR" ]]; then
  ACTIVE_PROJECT_SLUG="workspace-root"
else
  ACTIVE_PROJECT_SLUG="$(basename "$ACTIVE_PROJECT_ROOT")"
fi
if [[ -d "$PROJECT_MANAGEMENT_DIR" ]]; then
  PROJECT_MANAGEMENT_DISPLAY="$PROJECT_MANAGEMENT_DIR"
else
  PROJECT_MANAGEMENT_DISPLAY="NONE"
fi

if [[ ! -f "$PROJECT_FILE" ]]; then
  echo "Missing PROJECT.md. Update $PROJECT_FILE before running $ROLE_NAME." >&2
  exit 1
fi

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "Missing prompt file: $PROMPT_FILE" >&2
  exit 1
fi

if [[ -z "$TASK" ]]; then
  echo "No task provided for $ROLE_NAME." >&2
  exit 1
fi

PROMPT_TEXT="$(<"$PROMPT_FILE")"
PROJECT_TEXT="$(<"$PROJECT_FILE")"
MESSAGE=""

append_section "$PROMPT_TEXT"
append_section "PROJECT_SELECTION:
- Active project slug: $ACTIVE_PROJECT_SLUG
- Active project workspace root: $ACTIVE_PROJECT_ROOT
- Active project management directory: $PROJECT_MANAGEMENT_DISPLAY
- Use the active project's PROJECT.md as the source of truth for this run.
- If the active project management directory is not NONE, use that project's management files as the planning source of truth too.
- Do not read from or write to another $ROOT_DIR/projects/<other> path unless the task explicitly requires it."
append_section "HOST_WORKSPACE_CONTEXT:
- You are running on the host through the OpenClaw gateway, not inside the Docker sandbox.
- The workspace root for this role is $ROOT_DIR.
- The active project workspace root is $ACTIVE_PROJECT_ROOT.
- Prefer repo-relative paths in replies when possible.
- Do not edit outside $ROOT_DIR."
append_section "PROJECT_CONTEXT:
$PROJECT_TEXT"
append_section "TASK:
$TASK"

RAW_OUTPUT="$(openclaw agent --agent "$AGENT_ID" --message "$MESSAGE" --json)"

printf '%s' "$RAW_OUTPUT" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
texts = []
for item in payload.get("result", {}).get("payloads", []):
    text = (item or {}).get("text")
    if text:
        stripped = text.strip()
        if stripped:
            texts.append(stripped)

if texts:
    print("\n\n".join(texts))
else:
    print(payload.get("summary") or "Neo returned no text payload.")
'
