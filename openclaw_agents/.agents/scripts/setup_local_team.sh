#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RENDER_SCRIPT="$ROOT_DIR/.agents/scripts/render_openclaw_config.sh"
CONFIG_PATH="$ROOT_DIR/.agents/openclaw.json"
STATE_DIR="$ROOT_DIR/.agents/state"
BUILD_IMAGE="false"
VALIDATE="false"

for arg in "$@"; do
  case "$arg" in
    --build-image)
      BUILD_IMAGE="true"
      ;;
    --validate)
      VALIDATE="true"
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--build-image] [--validate]" >&2
      exit 1
      ;;
  esac
done

"$RENDER_SCRIPT"

if [[ "$BUILD_IMAGE" == "true" ]]; then
  docker build -t openclaw-sandbox:pytorch-shared-venv "$ROOT_DIR/.agents/docker/pytorch-shared-venv"
fi

if [[ "$VALIDATE" == "true" ]]; then
  OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" openclaw agents list
  OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" openclaw sandbox explain --agent local-ollama-qwen-manager
fi

cat <<EOF
Local OpenClaw team prepared.

- Config: $CONFIG_PATH
- State dir: $STATE_DIR

Next steps:
  1. Edit PROJECT.md for the target project.
  2. Build the sandbox image if needed:
     bash .agents/scripts/setup_local_team.sh --build-image
  3. Run the manager or full team:
     bash .agents/run_manager.sh "Summarize the current project."
     bash .agents/run_team.sh "Implement the requested change and validate it."
EOF
