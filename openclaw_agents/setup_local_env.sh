#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/env-python"

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/openclaw_agents/requirements-dev.txt"

echo "Environment ready: ${VENV_DIR}"
echo "Run tests with:"
echo "  ${VENV_DIR}/bin/python -m pytest -q ${ROOT_DIR}/openclaw_agents/tests"

