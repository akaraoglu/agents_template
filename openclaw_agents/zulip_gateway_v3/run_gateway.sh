#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="${GATEWAY_CONFIG_PATH:-$ROOT_DIR/config.json}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Missing gateway config: $CONFIG_PATH" >&2
  echo "Copy config.example.json to config.json and update the values first." >&2
  exit 1
fi

exec python3 "$ROOT_DIR/gateway.py" --config "$CONFIG_PATH" "$@"
