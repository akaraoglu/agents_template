#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROLE="${1:-manager}"
RENDER_SCRIPT="$ROOT_DIR/.agents/scripts/render_openclaw_config.sh"

resolve_project_root() {
  local requested_root="${OPENCLAW_PROJECT_ROOT:-}"
  local requested_slug="${OPENCLAW_PROJECT_SLUG:-}"
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

to_sandbox_path() {
  local host_path="$1"
  local sandbox_path="${host_path//$ROOT_DIR/\/workspace}"
  printf '%s' "$sandbox_path"
}

ACTIVE_PROJECT_ROOT="$(resolve_project_root)"
PROJECT_FILE="$ACTIVE_PROJECT_ROOT/PROJECT.md"
PROJECT_MANAGEMENT_DIR="$ACTIVE_PROJECT_ROOT/management"
PROJECT_SANDBOX_ROOT="$(to_sandbox_path "$ACTIVE_PROJECT_ROOT")"
if [[ "$ACTIVE_PROJECT_ROOT" == "$ROOT_DIR" ]]; then
  ACTIVE_PROJECT_SLUG="workspace-root"
else
  ACTIVE_PROJECT_SLUG="$(basename "$ACTIVE_PROJECT_ROOT")"
fi
if [[ -d "$PROJECT_MANAGEMENT_DIR" ]]; then
  PROJECT_MANAGEMENT_SANDBOX_DIR="$(to_sandbox_path "$PROJECT_MANAGEMENT_DIR")"
else
  PROJECT_MANAGEMENT_SANDBOX_DIR="NONE"
fi

if [[ $# -gt 0 ]]; then
  shift
fi

case "$ROLE" in
  assistant|agentsmith)
    AGENT_ID="local-ollama-qwen-assistant"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/assistant.txt"
    ;;
  yoda)
    AGENT_ID="local-ollama-qwen-yoda"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/yoda.txt"
    ;;
  projectmanager|niaobe)
    AGENT_ID="local-ollama-qwen-projectmanager"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/projectmanager.txt"
    ;;
  architect)
    AGENT_ID="local-ollama-qwen-architect"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/architect.txt"
    ;;
  manager|morpheus)
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
  oracle)
    AGENT_ID="local-ollama-qwen-oracle"
    PROMPT_FILE="$ROOT_DIR/.agents/prompts/oracle.txt"
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
OPENCLAW_SESSION_ID="${OPENCLAW_SESSION_ID:-}"

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
append_section "PROJECT_SELECTION:
- Active project slug: $ACTIVE_PROJECT_SLUG
- Active project workspace root: $PROJECT_SANDBOX_ROOT
- Active project management directory: $PROJECT_MANAGEMENT_SANDBOX_DIR
- Use the active project's PROJECT.md as the source of truth for this run.
- If the active project management directory is not NONE, use that project's management files as the planning source of truth too.
- Do not read from or write to /workspace/management or another /workspace/projects/<other> path unless the task explicitly requires it."
append_section "SANDBOX_CONTEXT:
- The repository root is mounted inside the sandbox at /workspace.
- The active project workspace root is $PROJECT_SANDBOX_ROOT.
- PROJECT.md is available at $PROJECT_SANDBOX_ROOT/PROJECT.md.
- Project-specific planning files belong under $PROJECT_MANAGEMENT_SANDBOX_DIR when that value is not NONE.
- Do not use host paths like $ROOT_DIR inside the sandbox.
- Use repo-root-relative paths or /workspace/... paths only."
append_section "PROJECT_CONTEXT:
$PROJECT_TEXT"

if [[ $# -gt 0 ]]; then
  append_section "TASK:
$*"
elif [[ -z "$PROMPT_TEXT" ]]; then
  echo "No prompt provided for role '$ROLE'." >&2
  exit 1
fi

OPENCLAW_ARGS=(agent --local --agent "$AGENT_ID")
if [[ -n "$OPENCLAW_SESSION_ID" ]]; then
  OPENCLAW_ARGS+=(--session-id "$OPENCLAW_SESSION_ID")
fi
OPENCLAW_ARGS+=(--message "$MESSAGE")

exec openclaw "${OPENCLAW_ARGS[@]}"
