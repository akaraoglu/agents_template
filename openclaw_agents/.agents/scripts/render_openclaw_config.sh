#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE_PATH="$ROOT_DIR/.agents/openclaw.template.json"
OUTPUT_PATH="$ROOT_DIR/.agents/openclaw.json"
STATE_DIR="$ROOT_DIR/.agents/state"
SANDBOX_DIR="$ROOT_DIR/.agents/sandboxes"

mkdir -p "$STATE_DIR" "$SANDBOX_DIR"

python3 - "$ROOT_DIR" "$TEMPLATE_PATH" "$OUTPUT_PATH" <<'PY'
import json
import pathlib
import sys

root_dir = pathlib.Path(sys.argv[1]).resolve()
template_path = pathlib.Path(sys.argv[2])
output_path = pathlib.Path(sys.argv[3])

root_text = json.dumps(str(root_dir))[1:-1]
rendered = template_path.read_text().replace("__ROOT_DIR__", root_text)
output_path.write_text(rendered)
PY
