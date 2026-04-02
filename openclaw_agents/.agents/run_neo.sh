#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT_DIR/.agents/scripts/run_openai_oauth_host_runtime.sh" \
  --agent neo \
  --role neo \
  --prompt-file "$ROOT_DIR/.agents/prompts/neo.txt" \
  "$@"
