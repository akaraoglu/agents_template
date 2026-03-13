#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="/workspace"
VENV_DIR="$WORKSPACE_DIR/env-python"
WHEEL_DIR="/opt/openclaw/wheels"
REQUIREMENTS_FILE="$WORKSPACE_DIR/.agents/docker/pytorch-shared-venv/requirements-extra.txt"
VENV_CFG="$VENV_DIR/pyvenv.cfg"

needs_recreate="false"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  needs_recreate="true"
elif [[ ! -f "$VENV_CFG" ]]; then
  needs_recreate="true"
elif ! grep -Eq '^include-system-site-packages *= *true$' "$VENV_CFG"; then
  needs_recreate="true"
fi

if [[ "$needs_recreate" == "true" ]]; then
  rm -rf "$VENV_DIR"
  python3 -m venv --system-site-packages "$VENV_DIR"
fi

if [[ -s "$REQUIREMENTS_FILE" ]]; then
  "$VENV_DIR/bin/python" -m pip install --no-index --find-links="$WHEEL_DIR" -r "$REQUIREMENTS_FILE"
fi
