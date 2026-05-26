#!/usr/bin/env bash
# Usage: bash run_e2e_fibonacci_test.sh [options]

set -euo pipefail

REPO_ROOT="/home/alik/workspace/agent_template_new"
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$REPO_ROOT/env-python/bin/python" "$BIN_DIR/run_e2e_fibonacci_test.py" "$@"
