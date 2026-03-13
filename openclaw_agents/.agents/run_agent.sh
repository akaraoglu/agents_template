#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROLE="${1:-manager}"
PROJECT_FILE="$ROOT_DIR/PROJECT.md"
RENDER_SCRIPT="$ROOT_DIR/.agents/scripts/render_openclaw_config.sh"

if [[ $# -gt 0 ]]; then
  shift
fi

case "$ROLE" in
  manager)
    AGENT_ID="local-ollama-qwen-manager"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/manager.txt"
    ;;
  planner)
    AGENT_ID="local-ollama-qwen-planner"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/planner.txt"
    ;;
  coder)
    AGENT_ID="local-ollama-qwen-coder"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/coder.txt"
    ;;
  tester)
    AGENT_ID="local-ollama-qwen-tester"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/tester.txt"
    ;;
  *)
    AGENT_ID="$ROLE"
    PROMPT_FILE=""
    ;;
esac

if [[ ! -x "$RENDER_SCRIPT" ]]; then
  echo "Missing config render script: $RENDER_SCRIPT" >&2
  exit 1
fi

if [[ ! -f "$PROJECT_FILE" ]]; then
  echo "Missing PROJECT.md. Update $PROJECT_FILE before running the local team." >&2
  exit 1
fi

"$RENDER_SCRIPT" >/dev/null

export OPENCLAW_CONFIG_PATH="$ROOT_DIR/.agents/openclaw.json"
export OPENCLAW_STATE_DIR="$ROOT_DIR/.agents/state"
export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"

PROMPT_TEXT=""
if [[ -n "$PROMPT_FILE" && -f "$PROMPT_FILE" ]]; then
  PROMPT_TEXT="$(<"$PROMPT_FILE")"
fi

PROJECT_TEXT="$(<"$PROJECT_FILE")"
MESSAGE=""

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

append_section "$PROMPT_TEXT"
append_section "PROJECT_CONTEXT:
$PROJECT_TEXT"

if [[ $# -gt 0 ]]; then
  append_section "TASK:
$*"
elif [[ -z "$PROMPT_TEXT" ]]; then
  echo "No prompt provided for role '$ROLE'." >&2
  exit 1
fi

exec openclaw agent --local --agent "$AGENT_ID" --message "$MESSAGE"
