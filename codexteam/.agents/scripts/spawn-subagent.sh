#!/usr/bin/env bash
# spawn-subagent.sh — spawn a local codex subagent and capture a JSON result.
#
# Runs `codex exec --profile <PROFILE>` against a workspace, feeds the task via
# stdin, enforces a timeout, and writes a contract-shaped JSON result under
# <workspace>/<result-dir>/.
#
# Usage:
#   spawn-subagent.sh --profile PROFILE --task TASK_ID --workspace WORKSPACE \
#       [--add-dir DIR] [--timeout SECONDS] [--prompt-file FILE | --prompt "text"]

set -euo pipefail

# ─── Defaults ────────────────────────────────────────────────────────────────
PROFILE=""
TASK_ID=""
WORKSPACE=""
PROMPT_FILE=""
PROMPT_TEXT=""
TIMEOUT=600           # 10 minutes (increased from 300)
RESULT_DIR="results"
ADD_DIRS=()
DRY_RUN=false

# ─── Ensure a writable CODEX_HOME ────────────────────────────────────────────
# codex writes session state under CODEX_HOME. If the default (~/.codex) is not
# writable (e.g. a read-only HOME mount), redirect to a temp dir AND seed it with
# the real config + profiles + catalogs so --profile still resolves instead of
# falling back to the default cloud provider.
SRC_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
if ! mkdir -p "$SRC_CODEX_HOME" 2>/dev/null \
   || ! { touch "$SRC_CODEX_HOME/.write-test-$$" 2>/dev/null && rm -f "$SRC_CODEX_HOME/.write-test-$$"; }; then
    NEW_CODEX_HOME="/tmp/codex-spawn-home-$$"
    mkdir -p "$NEW_CODEX_HOME"
    if [[ -d "$SRC_CODEX_HOME" ]]; then
        cp -a "$SRC_CODEX_HOME"/config.toml    "$NEW_CODEX_HOME"/ 2>/dev/null || true
        cp -a "$SRC_CODEX_HOME"/*.config.toml  "$NEW_CODEX_HOME"/ 2>/dev/null || true
        cp -a "$SRC_CODEX_HOME"/model_catalogs "$NEW_CODEX_HOME"/ 2>/dev/null || true
    fi
    export CODEX_HOME="$NEW_CODEX_HOME"
fi

# ─── Argument Parsing ────────────────────────────────────────────────────────
usage() {
    cat <<USAGE
Usage: $(basename "$0") [OPTIONS]

Required:
  --profile PROFILE       Model profile (e.g., qwen36-27b, gemma4-26b)
  --task TASK_ID          Task identifier (e.g., t001, t002)
  --workspace WORKSPACE   Project workspace root directory

Prompt:
  --prompt-file FILE      Path to JSON/text prompt file
  --prompt "TEXT"         Inline prompt text

Options:
  --add-dir DIR           Additional writable directory (repeatable)
  --timeout SECONDS       Max runtime in seconds (default: 600)
  --result-dir DIR        Directory for output JSON (default: results/)
  --dry-run               Show what would be executed without running
  -h, --help              Show this help

Output:
  Writes result to <WORKSPACE>/<RESULT_DIR>/<TASK_ID>-<TIMESTAMP>.json
  Exit code: 0=success, 1=subagent failed, 2=validation error, 3=timeout

Profiles (must exist as ~/.codex/<name>.config.toml):
  qwen36-27b              Ollama local qwen3.6-27b
  gemma4-26b              Ollama local gemma4-26b
USAGE
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)     PROFILE="$2";       shift 2 ;;
        --task)        TASK_ID="$2";       shift 2 ;;
        --workspace)   WORKSPACE="$2";     shift 2 ;;
        --prompt-file) PROMPT_FILE="$2";   shift 2 ;;
        --prompt)      PROMPT_TEXT="$2";   shift 2 ;;
        --add-dir)     ADD_DIRS+=("$2");   shift 2 ;;
        --timeout)     TIMEOUT="$2";       shift 2 ;;
        --result-dir)  RESULT_DIR="$2";    shift 2 ;;
        --dry-run)     DRY_RUN=true;       shift   ;;
        -h|--help)     usage 0 ;;
        *)             echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

# ─── Validation ──────────────────────────────────────────────────────────────
validate() {
    if [[ -z "$PROFILE" ]]; then
        echo "ERROR: --profile is required (e.g., qwen36-27b, gemma4-26b)" >&2
        return 1
    fi
    if [[ -z "$TASK_ID" ]]; then
        echo "ERROR: --task is required (e.g., t002)" >&2
        return 1
    fi
    if [[ -z "$WORKSPACE" ]]; then
        echo "ERROR: --workspace is required (project root path)" >&2
        return 1
    fi
    if [[ ! -d "$WORKSPACE" ]]; then
        echo "ERROR: Workspace does not exist: $WORKSPACE" >&2
        return 1
    fi
    if [[ -z "$PROMPT_FILE" && -z "$PROMPT_TEXT" ]]; then
        echo "ERROR: --prompt-file or --prompt is required" >&2
        return 1
    fi
    if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]] || (( TIMEOUT < 1 )); then
        echo "ERROR: --timeout must be a positive integer (seconds)" >&2
        return 1
    fi
}

validate

# ─── Build Prompt ──────────────────────────────────────────────────────────────
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RESULT_PATH="${WORKSPACE}/${RESULT_DIR}/${TASK_ID}-${TIMESTAMP}.json"

# Get task content from file or inline
if [[ -n "$PROMPT_FILE" ]]; then
    if [[ ! -f "$PROMPT_FILE" ]]; then
        echo "ERROR: Prompt file does not exist: $PROMPT_FILE" >&2
        exit 2
    fi
    TASK_CONTENT=$(cat "$PROMPT_FILE")
else
    TASK_CONTENT="$PROMPT_TEXT"
fi

# Write the full prompt to a temp file (avoids bash quoting issues); fed via stdin.
PROMPT_TMPFILE=$(mktemp /tmp/subagent-prompt-${TASK_ID}-XXXXXX.txt)
TIMESTAMP_UTC=$(date -u +%Y-%m-%dT%H:%M:%S%z)

cat > "$PROMPT_TMPFILE" <<PROMPT_INNER_EOF
[ORCHESTRATION CONTRACT]
You are a subagent in a multi-agent team. Your task is: ${TASK_ID}

RESPONSE RULES:
1. Complete the assigned work in the workspace: ${WORKSPACE}
2. At the END of your response, output a single JSON block (no markdown wrapping) with this structure:
{
  "task_id": "${TASK_ID}",
  "status": "completed | failed | partial | blocked",
  "summary": "Brief description of what was done",
  "file_changes": [{"path": "...", "action": "created|modified|deleted"}],
  "evidence": [{"type": "test_output|artifact", "ref": "...", "summary": "..."}],
  "errors": [],
  "warnings": [],
  "completed_at": "${TIMESTAMP_UTC}"
}
3. If work failed, set status to "failed" and populate "errors" array.
4. All file paths should be relative to workspace root.

--- TASK DETAILS ---
${TASK_CONTENT}
PROMPT_INNER_EOF

# ─── Construct Command (arg array + stdin pipe) ──────────────────────────────
CMD_ARGS=(codex exec --profile "${PROFILE}")

for dir in "${ADD_DIRS[@]+"${ADD_DIRS[@]}"}"; do
    if [[ ! -d "$dir" ]]; then
        echo "WARNING: --add-dir does not exist: $dir" >&2
        continue
    fi
    CMD_ARGS+=("--add-dir" "$dir")
done

CMD_ARGS+=("-s" "workspace-write")
CMD_ARGS+=("-C" "${WORKSPACE}")
CMD_ARGS+=("--skip-git-repo-check")
CMD_ARGS+=("--ephemeral")
CMD_ARGS+=(-)   # Read prompt from stdin

# ─── Dry-Run Mode ────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] Would execute:"
    printf '  %q\n' "${CMD_ARGS[@]}" < /dev/null
    echo ""
    echo "[DRY-RUN] Prompt file: ${PROMPT_TMPFILE}"
    head -25 "$PROMPT_TMPFILE"
    echo "..."
    echo ""
    echo "[DRY-RUN] Result would be saved to: $RESULT_PATH"
    echo "[DRY-RUN] CODEX_HOME: ${CODEX_HOME:-$HOME/.codex}"
    rm -f "$PROMPT_TMPFILE"
    exit 0
fi

# ─── Execute with Timeout ──────────────────────────────────────────────────
echo "[SPAWN] Starting subagent for task ${TASK_ID} (profile: ${PROFILE}, timeout: ${TIMEOUT}s)" >&2
echo "[SPAWN] Workspace: ${WORKSPACE}" >&2
if [[ -n "${ADD_DIRS[*]+"${ADD_DIRS[*]}"}" ]]; then
    echo "[SPAWN] Writable dirs: ${ADD_DIRS[*]}" >&2
fi
echo "[SPAWN] CODEX_HOME: ${CODEX_HOME:-$HOME/.codex}" >&2

mkdir -p "${WORKSPACE}/${RESULT_DIR}"

RAW_OUTPUT=$(mktemp "/tmp/subagent_output_${TASK_ID}_XXXXXX.txt")
EXIT_CODE=0
START_TIME=$(date +%s)

if command -v timeout &> /dev/null; then
    timeout "${TIMEOUT}s" bash -c 'exec "$@"' _ "${CMD_ARGS[@]}" \
        < "$PROMPT_TMPFILE" > "$RAW_OUTPUT" 2>&1 || EXIT_CODE=$?
else
    bash -c 'exec "$@"' _ "${CMD_ARGS[@]}" \
        < "$PROMPT_TMPFILE" > "$RAW_OUTPUT" 2>&1 &
    PID=$!
    ELAPSED=0
    while kill -0 $PID 2>/dev/null; do
        sleep 1
        ((ELAPSED++))
        if (( ELAPSED >= TIMEOUT )); then
            echo "[TIMEOUT] Killing subagent after ${TIMEOUT}s" >&2
            kill -9 $PID 2>/dev/null || true
            EXIT_CODE=124
            break
        fi
    done
    wait $PID 2>/dev/null || EXIT_CODE=$?
fi

END_TIME=$(date +%s)
DURATION=$(( END_TIME - START_TIME ))
rm -f "$PROMPT_TMPFILE"

# ─── Robust Python-based JSON Extraction ─────────────────────────────────────

python3 << PYEXTRACT_EOF
import json, sys, os

raw_file = "${RAW_OUTPUT}"
result_path = "${RESULT_PATH}"
task_id = "${TASK_ID}"
exit_code = ${EXIT_CODE}
duration = ${DURATION}
timestamp_utc = "${TIMESTAMP_UTC}"

def write_result(data):
    with open(result_path, 'w') as f:
        json.dump(data, f, indent=2)

VALID_STATUSES = {"completed", "failed", "partial", "blocked", "needs_review"}
TEMPLATE_PLACEHOLDERS = ("...", "Brief description", "completed | failed", "| failed | partial")

def _is_template_placeholder(d):
    """Reject dicts that look like the prompt example template rather than a real result."""
    for v in d.values():
        if isinstance(v, str) and any(ph in v for ph in TEMPLATE_PLACEHOLDERS):
            return True
    return False

def find_best_json(text):
    """Find the best JSON dict from output.
    Prefers dicts matching the result contract (task_id + valid status).
    Scans bottom-up to prefer model's final output over prompt examples.
    """
    lines = text.split('\n')
    best_contract_match = None
    best_large_dict = None

    # Scan bottom-up: prefer JSON at the END of output (model result) over prompt examples
    for start_idx in range(len(lines) - 1, -1, -1):
        if '{' not in lines[start_idx]:
            continue
        max_end = min(start_idx + 300, len(lines))
        for end_idx in range(max_end, start_idx + 1, -1):
            chunk = '\n'.join(lines[start_idx:end_idx])
            try:
                parsed = json.loads(chunk)
                if not isinstance(parsed, dict):
                    continue
                status = parsed.get('status')
                # Only accept contract-matching dicts with valid single-word status
                if 'task_id' in parsed and isinstance(status, str) and status in VALID_STATUSES:
                    if not _is_template_placeholder(parsed):
                        best_contract_match = parsed
                else:
                    if best_large_dict is None or len(parsed) > len(best_large_dict):
                        best_large_dict = parsed
            except (json.JSONDecodeError, ValueError):
                continue

    return best_contract_match or best_large_dict

# Handle timeout
if exit_code == 124:
    write_result({
        "task_id": task_id,
        "status": "blocked",
        "summary": f"Subagent timed out after {duration}s",
        "duration_seconds": duration,
        "errors": ["Process killed due to timeout"],
        "completed_at": timestamp_utc
    })
    sys.exit(0)

# Handle process failure
if exit_code != 0:
    stderr_tail = ""
    try:
        with open(raw_file) as f:
            lines = f.readlines()
            stderr_tail = ''.join(lines[-5:]).strip()[:500]
    except:
        pass
    write_result({
        "task_id": task_id,
        "status": "failed",
        "summary": f"Subagent process failed with exit code {exit_code}",
        "exit_code": exit_code,
        "duration_seconds": duration,
        "stderr_tail": stderr_tail,
        "errors": [f"Subagent exited with code {exit_code}"],
        "completed_at": timestamp_utc
    })
    sys.exit(0)

# Normal execution: try to extract JSON from output
text = ""
try:
    with open(raw_file) as f:
        text = f.read()
except Exception as e:
    write_result({
        "task_id": task_id,
        "status": "partial",
        "summary": "Cannot read subagent output",
        "errors": [str(e)],
        "completed_at": timestamp_utc
    })
    sys.exit(0)

result = find_best_json(text)
if result is not None:
    write_result(result)
else:
    tail = text[-1000:] if len(text) > 1000 else text
    write_result({
        "task_id": task_id,
        "status": "partial",
        "summary": "Subagent completed but no structured JSON result captured",
        "duration_seconds": duration,
        "warnings": ["No JSON result block found in subagent output"],
        "stdout_tail": tail,
        "completed_at": timestamp_utc
    })
PYEXTRACT_EOF

# Report the saved status
if [[ -f "$RESULT_PATH" ]]; then
    STATUS=$(python3 -c "import json; print(json.load(open('${RESULT_PATH}')).get('status','unknown'))" 2>/dev/null || echo "unknown")
else
    STATUS="unknown (result file not created)"
fi
echo "[RESULT] Task ${TASK_ID}: ${STATUS}" >&2
echo "[RESULT] Saved to: ${RESULT_PATH}" >&2

# Cleanup temp output after delay
sleep 10 && rm -f "$RAW_OUTPUT" 2>/dev/null &

exit 0
