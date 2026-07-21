#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON="${ROOT_DIR}/env-python/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
    PYTHON="python3"
fi

export PYTHONPATH="${ROOT_DIR}/codexteam/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON}" -m codexteam_tools.spawn "$@"
