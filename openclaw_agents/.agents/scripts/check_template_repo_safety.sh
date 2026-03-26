#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILURES=0

report_failure() {
  echo "FAIL: $1" >&2
  FAILURES=1
}

report_success() {
  echo "OK: $1"
}

check_absent_path() {
  local target="$1"
  if [[ -e "$target" ]]; then
    report_failure "Unexpected generated or local-only path present: $target"
  else
    report_success "Absent as expected: $target"
  fi
}

check_dir_only_gitkeep() {
  local target="$1"
  local extra
  extra="$(find "$target" -mindepth 1 ! -name '.gitkeep' -print -quit)"
  if [[ -n "$extra" ]]; then
    report_failure "Unexpected runtime residue under $target"
  else
    report_success "No runtime residue under $target"
  fi
}

check_absent_path "$ROOT_DIR/.agents/openclaw.json"
check_absent_path "$ROOT_DIR/software_bridge_v1/config.json"
check_absent_path "$ROOT_DIR/software_bridge_v1/__pycache__"
check_absent_path "$ROOT_DIR/persona_bridge_v1/config.json"
check_absent_path "$ROOT_DIR/persona_bridge_v1/persona_registry.json"
check_absent_path "$ROOT_DIR/persona_bridge_v1/__pycache__"
check_dir_only_gitkeep "$ROOT_DIR/.agents/state"
check_dir_only_gitkeep "$ROOT_DIR/.agents/sandboxes"
check_dir_only_gitkeep "$ROOT_DIR/software_bridge_v1/private"
check_dir_only_gitkeep "$ROOT_DIR/software_bridge_v1/state"
check_dir_only_gitkeep "$ROOT_DIR/persona_bridge_v1/private"
check_dir_only_gitkeep "$ROOT_DIR/persona_bridge_v1/state"

PATTERN='(/home/|localhost\.localdomain|claw_software_workspace|software-manager-bot@localhost\.localdomain|akaraoglu@gmail\.com)'
MATCHES="$(rg -n "$PATTERN" "$ROOT_DIR" \
  -g '!software_bridge_v1/private/**' \
  -g '!software_bridge_v1/state/**' \
  -g '!persona_bridge_v1/private/**' \
  -g '!persona_bridge_v1/state/**' \
  -g '!**/.gitkeep' || true)"
if [[ -n "$MATCHES" ]]; then
  echo "$MATCHES" >&2
  report_failure "Found local-machine specific values in committed template files."
else
  report_success "No local-machine specific values found in committed template files"
fi

if [[ "$FAILURES" -ne 0 ]]; then
  exit 1
fi

echo "Template repo safety checks passed."
