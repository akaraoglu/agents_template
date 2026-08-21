#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEXTEAM_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPOSITORY_ROOT="$(cd "${CODEXTEAM_ROOT}/.." && pwd)"
FIXTURE_ROOT="${CODEXTEAM_ROOT}/tests/e2e/fibonacci-tree-cli"
PYTHON="${REPOSITORY_ROOT}/env-python/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
    PYTHON="python3"
fi

INIT_PROJECT="${SCRIPT_DIR}/init-project.py"
SPAWN="${CODEXTEAM_ROOT}/.agents/scripts/spawn-subagent.sh"
VERIFY_RESULT="${SCRIPT_DIR}/verify-result.py"
CLOSE_LOOP="${SCRIPT_DIR}/close-loop.sh"
PRODUCT_ACCEPTANCE="${FIXTURE_ROOT}/assert_product_acceptance.py"

PROFILE=""
REASONING_EFFORT=""
TIMEOUT_SECONDS=300
BUDGET_SECONDS=1800
ENFORCE_BUDGET=0
PROJECTS_ROOT="${CODEXTEAM_PROJECTS_ROOT:-${CODEXTEAM_ROOT}/projects}"
PROJECT_ID=""
REPORT_FILE=""
DRY_RUN=0
PRODUCT_ONLY_PROJECT=""

STARTED_EPOCH=0
STARTED_AT=""
FINISHED_AT=""
ELAPSED_SECONDS=0
AGENT_TURNS=0
EXPECTED_AGENT_TURNS=5
RUN_STATUS="NOT_STARTED"
BUDGET_STATUS="NOT_RUN"
LIFECYCLE_VERDICT="NOT_RUN"
PRODUCT_VERDICT="NOT_RUN"
EVIDENCE_VERDICT="NOT_RUN"
MANAGEMENT_VERDICT="NOT_RUN"
MANIFEST_VERDICT="NOT_RUN"
PERFORMANCE_VERDICT="NOT_RUN"
CORRECTION_CEILING_STATUS="NOT_RUN"
LEAD_TOKEN_CEILING_STATUS="NOT_APPLICABLE"
LEAD_DURATION_SECONDS=""
LEAD_INPUT_TOKENS=""
LEAD_CACHED_INPUT_TOKENS=""
LEAD_UNCACHED_INPUT_TOKENS=""
LEAD_OUTPUT_TOKENS=""
CURRENT_STAGE="argument validation"
CURRENT_TASK="none"
CURRENT_PHASE="none"
CURRENT_ROLE="none"
PROJECT=""
LAST_ERROR=""
REPORT_WRITTEN=0

usage() {
    cat <<'EOF'
Usage:
  run-e2e-fibonacci-test.sh --profile PROFILE --reasoning-effort LEVEL [options]
  run-e2e-fibonacci-test.sh --product-only PROJECT [options]

Runs the controlled five-task Fibonacci Tree CLI canary. The live workflow uses
exactly one provider draft per task followed by provider-free deterministic
final sealing, with deterministic gates and no automatic retry or model transfer.

Options:
  --profile PROFILE          Codex profile for every responsible AI (required live)
  --reasoning-effort LEVEL   low, medium, high, or xhigh (required live)
  --timeout-seconds N        Timeout for each agent turn (default: 300)
  --budget-seconds N         Elapsed-time budget reported at exit (default: 1800)
  --enforce-budget           Exit nonzero when a functional run exceeds the budget
  --projects-root PATH       Generated-project parent directory
  --project-id ID            Explicit unique project ID; never overwrites an existing path
  --report-file PATH         Unique Markdown report path (default: /tmp/<project>-report.md)
  --lead-duration-seconds N  Codex-reported Project Lead duration, when available
  --lead-input-tokens N      Codex-reported Project Lead input tokens
  --lead-cached-tokens N     Codex-reported Project Lead cached input tokens
  --lead-output-tokens N     Codex-reported Project Lead output tokens
  --dry-run                  Validate and print the plan without creating a project or agent session
  --product-only PROJECT     Run deterministic product checks against an existing project
  -h, --help                 Show this help
EOF
}

fail() {
    LAST_ERROR="$1"
    printf 'ERROR: %s\n' "$1" >&2
    return 1
}

require_positive_integer() {
    local label="$1"
    local value="$2"
    [[ "${value}" =~ ^[1-9][0-9]*$ ]] || fail "${label} must be a positive integer"
}

require_nonnegative_integer() {
    local label="$1"
    local value="$2"
    [[ "${value}" =~ ^[0-9]+$ ]] || fail "${label} must be a non-negative integer"
}

evaluate_lead_usage() {
    local reported=0
    local value

    for value in \
        "${LEAD_INPUT_TOKENS}" \
        "${LEAD_CACHED_INPUT_TOKENS}" \
        "${LEAD_OUTPUT_TOKENS}"; do
        [[ -n "${value}" ]] && ((reported += 1))
    done
    if (( reported != 0 && reported != 3 )); then
        fail "lead token reporting requires input, cached-input, and output values together"
    fi
    if (( reported == 0 )); then
        return 0
    fi

    require_nonnegative_integer "--lead-input-tokens" "${LEAD_INPUT_TOKENS}"
    require_nonnegative_integer "--lead-cached-tokens" "${LEAD_CACHED_INPUT_TOKENS}"
    require_nonnegative_integer "--lead-output-tokens" "${LEAD_OUTPUT_TOKENS}"
    (( LEAD_CACHED_INPUT_TOKENS <= LEAD_INPUT_TOKENS )) \
        || fail "--lead-cached-tokens cannot exceed --lead-input-tokens"
    LEAD_UNCACHED_INPUT_TOKENS=$(( LEAD_INPUT_TOKENS - LEAD_CACHED_INPUT_TOKENS ))
    if (( LEAD_UNCACHED_INPUT_TOKENS <= 1000000 && LEAD_OUTPUT_TOKENS <= 50000 )); then
        LEAD_TOKEN_CEILING_STATUS="PASS"
    else
        LEAD_TOKEN_CEILING_STATUS="FAIL"
    fi
}

print_command() {
    printf '  '
    printf '%q ' "$@"
    printf '\n'
}

run_command() {
    print_command "$@"
    "$@"
}

session_value() {
    local path="$1"
    local field="$2"
    sed -n "s/.*\"${field}\": \"\([^\"]*\)\".*/\1/p" "${path}"
}

assert_file_contains() {
    local path="$1"
    local text="$2"
    [[ -f "${path}" ]] || fail "missing required file: ${path}"
    grep -Fq -- "${text}" "${path}" || fail "${path} does not contain expected text: ${text}"
}

product_checks() {
    local project="$1"
    local cli="${project}/src/fibonacci_tree_cli.py"
    local tests="${project}/tests/test_fibonacci_tree_cli.py"

    CURRENT_STAGE="product verification"
    PRODUCT_VERDICT="FAIL"
    [[ -f "${cli}" ]] || fail "missing product CLI: ${cli}"
    [[ -f "${tests}" ]] || fail "missing product tests: ${tests}"
    [[ -f "${project}/README.md" ]] || fail "missing product README: ${project}/README.md"

    (cd "${project}" && run_command python3 -B -m unittest discover -s tests -v)
    run_command "${PYTHON}" "${PRODUCT_ACCEPTANCE}" "${project}" --product-only
    PRODUCT_VERDICT="PASS"
}

manifest_checks() {
    local project="$1"

    CURRENT_STAGE="delivery-manifest verification"
    MANIFEST_VERDICT="FAIL"
    run_command "${PYTHON}" "${PRODUCT_ACCEPTANCE}" "${project}" --manifest-only
    MANIFEST_VERDICT="PASS"
}

input_four_check() {
    local project="$1"
    local cli="${project}/src/fibonacci_tree_cli.py"
    local expected actual

    expected="$(<"${FIXTURE_ROOT}/golden/fib-4.txt")"
    actual="$(python3 "${cli}" 4)"
    [[ "${actual}" == "${expected}" ]] || fail "input 4 does not match golden/fib-4.txt"
}

reviewer_spot_checks() {
    local project="$1"
    local cli="${project}/src/fibonacci_tree_cli.py"
    local error_output

    input_four_check "${project}"
    if error_output="$(python3 "${cli}" abc 2>&1)"; then
        fail "reviewer spot check found non-integer input unexpectedly succeeded"
    fi
    [[ "${error_output}" != *"Traceback"* ]] || fail "reviewer spot check found an invalid-input traceback"
}

draft_gate() {
    local task="$1"

    case "${task}" in
        T001)
            assert_file_contains "${PROJECT}/results/t001-fixture-validation.txt" "PASS"
            ;;
        T002)
            assert_file_contains "${PROJECT}/results/t002-development.txt" "unittest"
            product_checks "${PROJECT}"
            ;;
        T003)
            assert_file_contains "${PROJECT}/results/t003-acceptance.txt" "AC"
            product_checks "${PROJECT}"
            ;;
        T004)
            assert_file_contains "${PROJECT}/results/t004-evidence-audit.md" "T003"
            [[ -s "${PROJECT}/results/t003-acceptance.txt" ]] || fail "reviewer cannot reuse missing tester evidence"
            (cd "${PROJECT}" && reviewer_spot_checks "${PROJECT}")
            ;;
        T005)
            assert_file_contains "${PROJECT}/results/t005-delivery-review.md" "README"
            [[ -s "${PROJECT}/results/t003-acceptance.txt" ]] || fail "documenter cannot reuse missing tester evidence"
            [[ -s "${PROJECT}/results/t004-evidence-audit.md" ]] || fail "documenter cannot reuse missing reviewer evidence"
            [[ -s "${PROJECT}/README.md" ]] || fail "documenter cannot validate a missing README"
            ;;
        *)
            fail "unsupported canary task: ${task}"
            ;;
    esac
}

close_task() {
    local task="$1"
    local result="results/${task}-att-001.json"

    if [[ "${task}" == "T001" ]]; then
        run_command "${CLOSE_LOOP}" "${PROJECT}" --task "${task}" --result "${result}" \
            --timeout "${TIMEOUT_SECONDS}" -- test -s results/t001-fixture-validation.txt
    elif [[ "${task}" == "T004" ]]; then
        run_command "${CLOSE_LOOP}" "${PROJECT}" --task "${task}" --result "${result}" \
            --timeout "${TIMEOUT_SECONDS}" -- python3 src/fibonacci_tree_cli.py 4
    elif [[ "${task}" == "T005" ]]; then
        run_command "${CLOSE_LOOP}" "${PROJECT}" --task "${task}" --result "${result}" \
            --timeout "${TIMEOUT_SECONDS}" -- test -s results/t005-delivery-review.md
    else
        run_command "${CLOSE_LOOP}" "${PROJECT}" --task "${task}" --result "${result}" \
            --timeout "${TIMEOUT_SECONDS}" -- python3 -B -m unittest discover -s tests -v
    fi
}

run_task() {
    local task="$1"
    local role="$2"
    local attempt="att-001"
    local handoff="${PROJECT}/management/tasks/${task}.md"
    local final_prompt="${FIXTURE_ROOT}/prompts/${task}-final.md"
    local result="${PROJECT}/results/${task}-${attempt}.json"
    local session="${PROJECT}/.codexteam/runtime/sessions/${PROJECT_ID}/${task}/${attempt}/session.json"
    local draft_thread final_thread
    local -a identity=(
        --team "${PROJECT_ID}"
        --task "${task}"
        --attempt "${attempt}"
        --role "${role}"
        --workspace "${PROJECT}"
        --timeout "${TIMEOUT_SECONDS}"
    )

    CURRENT_TASK="${task}"
    CURRENT_ROLE="${role}"
    CURRENT_PHASE="draft"
    CURRENT_STAGE="${task} draft turn"
    ((AGENT_TURNS += 1))
    run_command "${SPAWN}" --phase draft --backend codex --profile "${PROFILE}" \
        --reasoning-effort "${REASONING_EFFORT}" "${identity[@]}" --prompt-file "${handoff}"

    [[ -s "${session}" ]] || fail "draft did not persist session metadata: ${session}"
    [[ ! -e "${result}" ]] || fail "draft created the reserved final result: ${result}"
    draft_thread="$(session_value "${session}" thread_id)"
    [[ -n "${draft_thread}" ]] || fail "draft session has no thread_id: ${session}"
    assert_file_contains "${session}" "\"last_phase\": \"draft\""
    assert_file_contains "${PROJECT}/.codexteam/runtime/sessions/${PROJECT_ID}/${task}/${attempt}/execution-spec.json" \
        "\"requested\": \"${REASONING_EFFORT}\""

    CURRENT_STAGE="${task} deterministic draft gate"
    draft_gate "${task}"

    CURRENT_PHASE="final"
    CURRENT_STAGE="${task} final turn"
    run_command "${SPAWN}" --phase final "${identity[@]}" --prompt-file "${final_prompt}"

    [[ -s "${result}" ]] || fail "final turn did not persist the expected result: ${result}"
    final_thread="$(session_value "${session}" thread_id)"
    [[ "${final_thread}" == "${draft_thread}" ]] || fail "${task} final turn changed the persistent thread ID"
    assert_file_contains "${session}" "\"last_phase\": \"final\""
    assert_file_contains "${session}" "\"final_result_path\": \"results/${task}-${attempt}.json\""

    CURRENT_STAGE="${task} result validation"
    run_command "${PYTHON}" "${VERIFY_RESULT}" "${result}" \
        --task "${task}" --team "${PROJECT_ID}" --attempt "${attempt}" \
        --role "${role}" --expected-status completed

    CURRENT_STAGE="${task} independent closure"
    close_task "${task}"
}

verify_final_management_state() {
    local -a final_results=()
    local task session evidence verification

    CURRENT_STAGE="final management-state verification"
    MANAGEMENT_VERDICT="FAIL"
    assert_file_contains "${PROJECT}/PROJECT_STATE.md" "- Status: DELIVERED"
    assert_file_contains "${PROJECT}/PROJECT_STATE.md" "- Active Task: None"
    assert_file_contains "${PROJECT}/CURRENT_TASK.md" "- Task ID: None"
    assert_file_contains "${PROJECT}/DONE_REPORT.md" "- Status: Delivered"
    assert_file_contains "${PROJECT}/DELIVERY.md" "- Status: DELIVERED"
    assert_file_contains "${PROJECT}/BRIEF.md" "No automatic retry, model transfer, or hidden repair is allowed."
    assert_file_contains "${PROJECT}/BRIEF.md" "- Phase: delivery complete"
    assert_file_contains "${PROJECT}/BRIEF.md" "- Active task: None"
    assert_file_contains "${PROJECT}/BRIEF.md" "- Next handoff: None;"
    assert_file_contains "${PROJECT}/BRIEF.md" "results/T005-att-001.json"
    assert_file_contains "${PROJECT}/BRIEF.md" "results/T005-verification.txt"

    [[ "$(grep -Ec '^\| T00[1-5] \|.*\| Completed \|' "${PROJECT}/TASKS.md")" -eq 5 ]] \
        || fail "TASKS.md does not contain five completed canary tasks"
    MANAGEMENT_VERDICT="PASS"

    CURRENT_STAGE="final evidence verification"
    EVIDENCE_VERDICT="FAIL"
    shopt -s nullglob
    final_results=("${PROJECT}"/results/T00[1-5]-att-001.json)
    shopt -u nullglob
    [[ "${#final_results[@]}" -eq 5 ]] || fail "expected five deterministic final result files; found ${#final_results[@]}"
    for evidence in \
        t001-fixture-validation.txt \
        t002-development.txt \
        t003-acceptance.txt \
        t004-evidence-audit.md \
        t005-delivery-review.md; do
        [[ -s "${PROJECT}/results/${evidence}" ]] || fail "missing final evidence: results/${evidence}"
    done
    for task in T001 T002 T003 T004 T005; do
        verification="${PROJECT}/results/${task}-verification.txt"
        [[ -s "${verification}" ]] || fail "missing independent verification: ${verification}"
    done
    EVIDENCE_VERDICT="PASS"

    CURRENT_STAGE="final lifecycle verification"
    LIFECYCLE_VERDICT="FAIL"
    [[ "${AGENT_TURNS}" -eq "${EXPECTED_AGENT_TURNS}" ]] \
        || fail "clean run used ${AGENT_TURNS} agent turns; expected ${EXPECTED_AGENT_TURNS}"

    for task in T001 T002 T003 T004 T005; do
        session="${PROJECT}/.codexteam/runtime/sessions/${PROJECT_ID}/${task}/att-001/session.json"
        assert_file_contains "${session}" '"turn_count": 2'
        assert_file_contains "${session}" '"last_phase": "final"'
    done
    LIFECYCLE_VERDICT="PASS"

    product_checks "${PROJECT}"
    manifest_checks "${PROJECT}"
}

print_dry_run_plan() {
    local task role
    local -a tasks=(T001 T002 T003 T004 T005)
    local -a roles=(leader developer tester reviewer documenter)

    printf '\nControlled Fibonacci E2E plan\n'
    printf 'Project: %s\n' "${PROJECT}"
    printf 'Profile: %s\nReasoning effort: %s\n' "${PROFILE}" "${REASONING_EFFORT}"
    printf 'Per-turn timeout: %s seconds\nElapsed budget: %s seconds\n' "${TIMEOUT_SECONDS}" "${BUDGET_SECONDS}"
    printf 'Expected clean turns: %s\n\n' "${EXPECTED_AGENT_TURNS}"

    run_command "${PYTHON}" "${INIT_PROJECT}" "Fibonacci Tree CLI" \
        --goal "Deliver and verify a deterministic recursive-call-tree CLI end to end." \
        --project-id "${PROJECT_ID}" --projects-root "${PROJECTS_ROOT}" \
        --template-root "${FIXTURE_ROOT}/template" --tasks T001,T002,T003,T004,T005 \
        --dry-run --json

    for index in "${!tasks[@]}"; do
        task="${tasks[index]}"
        role="${roles[index]}"
        printf '\n%s (%s):\n' "${task}" "${role}"
        print_command "${SPAWN}" --phase draft --backend codex --profile "${PROFILE}" \
            --reasoning-effort "${REASONING_EFFORT}" --team "${PROJECT_ID}" \
            --task "${task}" --attempt att-001 --role "${role}" \
            --workspace "${PROJECT}" --timeout "${TIMEOUT_SECONDS}" \
            --prompt-file "${PROJECT}/management/tasks/${task}.md"
        printf '  [deterministic draft gate]\n'
        print_command "${SPAWN}" --phase final --team "${PROJECT_ID}" \
            --task "${task}" --attempt att-001 --role "${role}" \
            --workspace "${PROJECT}" --timeout "${TIMEOUT_SECONDS}" \
            --prompt-file "${FIXTURE_ROOT}/prompts/${task}-final.md"
        print_command "${PYTHON}" "${VERIFY_RESULT}" "${PROJECT}/results/${task}-att-001.json" \
            --task "${task}" --team "${PROJECT_ID}" --attempt att-001 \
            --role "${role}" --expected-status completed
        printf '  [independent close-loop verification]\n'
    done
}

print_recovery_guidance() {
    local feedback_file
    [[ -n "${PROJECT}" && "${CURRENT_TASK}" != "none" ]] || return 0

    feedback_file="/tmp/${PROJECT_ID}-${CURRENT_TASK}-feedback.md"

    cat >&2 <<EOF

The project and persistent session were preserved. No retry or model transfer was attempted.
Inspect:
  ${PROJECT}/.codexteam/runtime/sessions/${PROJECT_ID}/${CURRENT_TASK}/att-001/session.json
  ${PROJECT}/.codexteam/runtime/sessions/${PROJECT_ID}/${CURRENT_TASK}/att-001/turns/

Resume the same responsible AI only after reviewing the diagnostics. Use the same project ID,
task, attempt, role, profile, reasoning effort, and workspace. Send consolidated correction with
--phase feedback, then use --phase final only after accepting the revised draft. Do not create a
new attempt unless the recorded session is irrecoverable or ownership intentionally changes.
EOF
    printf 'Create a focused feedback prompt at %s, then run:\n  ' "${feedback_file}" >&2
    printf '%q ' "${SPAWN}" --phase feedback --team "${PROJECT_ID}" \
        --task "${CURRENT_TASK}" --attempt att-001 --role "${CURRENT_ROLE}" \
        --workspace "${PROJECT}" --timeout "${TIMEOUT_SECONDS}" --prompt-file "${feedback_file}" >&2
    printf '\n' >&2
}

write_report() {
    local exit_code="$1"
    local report_parent

    [[ -n "${REPORT_FILE}" ]] || return 0
    report_parent="$(dirname "${REPORT_FILE}")"
    mkdir -p "${report_parent}"

    {
        printf '# Fibonacci Tree CLI E2E Report\n\n'
        printf -- '- Status: %s\n' "${RUN_STATUS}"
        printf -- '- Exit code: %s\n' "${exit_code}"
        printf -- '- Project ID: `%s`\n' "${PROJECT_ID:-not-created}"
        printf -- '- Project: `%s`\n' "${PROJECT:-not-created}"
        printf -- '- Profile: `%s`\n' "${PROFILE:-product-only}"
        printf -- '- Reasoning effort: `%s`\n' "${REASONING_EFFORT:-product-only}"
        printf -- '- Per-turn timeout seconds: %s\n' "${TIMEOUT_SECONDS}"
        printf -- '- Budget seconds: %s\n' "${BUDGET_SECONDS}"
        printf -- '- Budget status: %s\n' "${BUDGET_STATUS}"
        printf -- '- Budget enforced: %s\n' "${ENFORCE_BUDGET}"
        printf -- '- Lifecycle verdict: %s\n' "${LIFECYCLE_VERDICT}"
        printf -- '- Product verdict: %s\n' "${PRODUCT_VERDICT}"
        printf -- '- Evidence verdict: %s\n' "${EVIDENCE_VERDICT}"
        printf -- '- Management verdict: %s\n' "${MANAGEMENT_VERDICT}"
        printf -- '- Manifest verdict: %s\n' "${MANIFEST_VERDICT}"
        printf -- '- Performance verdict: %s\n' "${PERFORMANCE_VERDICT}"
        printf -- '- Correction ceiling status: %s\n' "${CORRECTION_CEILING_STATUS}"
        printf -- '- Lead-token ceiling status: %s\n' "${LEAD_TOKEN_CEILING_STATUS}"
        if [[ -n "${LEAD_INPUT_TOKENS}" ]]; then
            printf -- '- Lead input tokens: %s\n' "${LEAD_INPUT_TOKENS}"
            printf -- '- Lead cached input tokens: %s\n' "${LEAD_CACHED_INPUT_TOKENS}"
            printf -- '- Lead uncached input tokens: %s\n' "${LEAD_UNCACHED_INPUT_TOKENS}"
            printf -- '- Lead output tokens: %s\n' "${LEAD_OUTPUT_TOKENS}"
        fi
        if [[ -n "${LEAD_DURATION_SECONDS}" ]]; then
            printf -- '- Lead duration seconds: %s\n' "${LEAD_DURATION_SECONDS}"
        fi
        printf -- '- Started: %s\n' "${STARTED_AT}"
        printf -- '- Finished: %s\n' "${FINISHED_AT}"
        printf -- '- Elapsed seconds: %s\n' "${ELAPSED_SECONDS}"
        printf -- '- Agent turns: %s\n' "${AGENT_TURNS}"
        printf -- '- Clean-path expected turns: %s\n' "${EXPECTED_AGENT_TURNS}"
        printf -- '- Last task: `%s`\n' "${CURRENT_TASK}"
        printf -- '- Last phase: `%s`\n' "${CURRENT_PHASE}"
        printf -- '- Last stage: %s\n' "${CURRENT_STAGE}"
        if [[ -n "${LAST_ERROR}" ]]; then
            printf -- '- Error: %s\n' "${LAST_ERROR}"
        fi
        printf '\nThe runner never retries or changes ownership automatically. A failed project and its session remain available for same-session recovery.\n'
    } >"${REPORT_FILE}"
    REPORT_WRITTEN=1
}

finish() {
    local exit_code="$1"
    local final_code="${exit_code}"

    trap - EXIT
    FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    ELAPSED_SECONDS=$(( $(date +%s) - STARTED_EPOCH ))
    if (( ELAPSED_SECONDS > BUDGET_SECONDS )); then
        BUDGET_STATUS="EXCEEDED"
        if (( ENFORCE_BUDGET == 1 && final_code == 0 )); then
            final_code=4
            RUN_STATUS="BUDGET_EXCEEDED"
            LAST_ERROR="functional checks passed but elapsed-time budget was exceeded"
        fi
    else
        BUDGET_STATUS="PASS"
    fi
    if [[ "${PERFORMANCE_VERDICT}" != "NOT_APPLICABLE" ]]; then
        if (( ELAPSED_SECONDS > BUDGET_SECONDS || AGENT_TURNS > 12 )) \
            || [[ "${LEAD_TOKEN_CEILING_STATUS}" == "FAIL" ]] \
            || { (( final_code == 3 )) && [[ "${CURRENT_STAGE}" == *"turn" ]]; }; then
            PERFORMANCE_VERDICT="FAIL"
        else
            PERFORMANCE_VERDICT="PASS"
        fi
    fi

    if (( final_code != 0 )) && [[ "${RUN_STATUS}" != "BUDGET_EXCEEDED" ]]; then
        RUN_STATUS="FAILED"
    fi
    write_report "${final_code}"

    if (( final_code != 0 )); then
        print_recovery_guidance
    fi
    if (( REPORT_WRITTEN == 1 )); then
        printf 'E2E report: %s\n' "${REPORT_FILE}"
    fi
    if [[ -d "${PROJECT}" ]]; then
        printf 'Project preserved at: %s\n' "${PROJECT}"
    fi
    exit "${final_code}"
}

on_error() {
    local exit_code="$1"
    local line="$2"
    local command="$3"
    LAST_ERROR="stage '${CURRENT_STAGE}' failed at line ${line}: ${command}"
    return 0
}

parse_arguments() {
    while (( $# > 0 )); do
        case "$1" in
            --profile)
                [[ $# -ge 2 ]] || fail "--profile requires a value"
                PROFILE="$2"
                shift 2
                ;;
            --reasoning-effort)
                [[ $# -ge 2 ]] || fail "--reasoning-effort requires a value"
                REASONING_EFFORT="$2"
                shift 2
                ;;
            --timeout-seconds)
                [[ $# -ge 2 ]] || fail "--timeout-seconds requires a value"
                TIMEOUT_SECONDS="$2"
                shift 2
                ;;
            --budget-seconds)
                [[ $# -ge 2 ]] || fail "--budget-seconds requires a value"
                BUDGET_SECONDS="$2"
                shift 2
                ;;
            --enforce-budget)
                ENFORCE_BUDGET=1
                shift
                ;;
            --projects-root)
                [[ $# -ge 2 ]] || fail "--projects-root requires a value"
                PROJECTS_ROOT="$2"
                shift 2
                ;;
            --project-id)
                [[ $# -ge 2 ]] || fail "--project-id requires a value"
                PROJECT_ID="$2"
                shift 2
                ;;
            --report-file)
                [[ $# -ge 2 ]] || fail "--report-file requires a value"
                REPORT_FILE="$2"
                shift 2
                ;;
            --lead-duration-seconds)
                [[ $# -ge 2 ]] || fail "--lead-duration-seconds requires a value"
                LEAD_DURATION_SECONDS="$2"
                shift 2
                ;;
            --lead-input-tokens)
                [[ $# -ge 2 ]] || fail "--lead-input-tokens requires a value"
                LEAD_INPUT_TOKENS="$2"
                shift 2
                ;;
            --lead-cached-tokens)
                [[ $# -ge 2 ]] || fail "--lead-cached-tokens requires a value"
                LEAD_CACHED_INPUT_TOKENS="$2"
                shift 2
                ;;
            --lead-output-tokens)
                [[ $# -ge 2 ]] || fail "--lead-output-tokens requires a value"
                LEAD_OUTPUT_TOKENS="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            --product-only)
                [[ $# -ge 2 ]] || fail "--product-only requires a project path"
                PRODUCT_ONLY_PROJECT="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                fail "unknown option: $1"
                ;;
        esac
    done
}

main() {
    local stamp source_codex_home

    parse_arguments "$@"
    require_positive_integer "--timeout-seconds" "${TIMEOUT_SECONDS}"
    require_positive_integer "--budget-seconds" "${BUDGET_SECONDS}"
    if [[ -n "${LEAD_DURATION_SECONDS}" ]]; then
        require_nonnegative_integer "--lead-duration-seconds" "${LEAD_DURATION_SECONDS}"
    fi
    evaluate_lead_usage
    case "${REASONING_EFFORT}" in
        ""|low|medium|high|xhigh) ;;
        *) fail "unsupported --reasoning-effort: ${REASONING_EFFORT}" ;;
    esac

    STARTED_EPOCH="$(date +%s)"
    STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if [[ -n "${PRODUCT_ONLY_PROJECT}" ]]; then
        [[ "${DRY_RUN}" -eq 0 ]] || fail "--dry-run and --product-only cannot be combined"
        PROJECT="$(cd "${PRODUCT_ONLY_PROJECT}" && pwd)"
        PROJECT_ID="$(basename "${PROJECT}")"
        REPORT_FILE="${REPORT_FILE:-/tmp/${PROJECT_ID}-product-report-$$.md}"
        [[ ! -e "${REPORT_FILE}" ]] || fail "report file already exists: ${REPORT_FILE}"
        trap 'on_error $? ${LINENO} "${BASH_COMMAND}"' ERR
        trap 'finish $?' EXIT
        RUN_STATUS="RUNNING"
        LIFECYCLE_VERDICT="NOT_APPLICABLE"
        EVIDENCE_VERDICT="NOT_APPLICABLE"
        MANAGEMENT_VERDICT="NOT_APPLICABLE"
        MANIFEST_VERDICT="NOT_APPLICABLE"
        PERFORMANCE_VERDICT="NOT_APPLICABLE"
        CORRECTION_CEILING_STATUS="NOT_APPLICABLE"
        CURRENT_STAGE="product-only verification"
        product_checks "${PROJECT}"
        RUN_STATUS="PASS"
        CURRENT_STAGE="complete"
        return 0
    fi

    [[ -n "${PROFILE}" ]] || fail "--profile is required for the live or dry-run canary"
    [[ -n "${REASONING_EFFORT}" ]] || fail "--reasoning-effort is required for the live or dry-run canary"
    [[ "${PROJECT_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] \
        || {
            if [[ -n "${PROJECT_ID}" ]]; then
                fail "invalid --project-id: ${PROJECT_ID}"
            fi
        }
    if [[ -z "${PROJECT_ID}" ]]; then
        stamp="$(date -u +%Y%m%d-%H%M%S)"
        PROJECT_ID="fibonacci-tree-cli-e2e-${stamp}-$$"
    fi

    PROJECTS_ROOT="$(cd "${PROJECTS_ROOT}" && pwd)"
    PROJECT="${PROJECTS_ROOT}/${PROJECT_ID}"
    REPORT_FILE="${REPORT_FILE:-/tmp/${PROJECT_ID}-report.md}"
    [[ ! -e "${PROJECT}" ]] || fail "project already exists; refusing to overwrite: ${PROJECT}"
    if (( DRY_RUN == 0 )); then
        [[ ! -e "${REPORT_FILE}" ]] || fail "report file already exists; refusing to overwrite: ${REPORT_FILE}"
    fi

    RUN_STATUS="RUNNING"
    CORRECTION_CEILING_STATUS="PASS"
    if (( DRY_RUN == 1 )); then
        CURRENT_STAGE="dry-run plan"
        print_dry_run_plan
        RUN_STATUS="DRY_RUN"
        CURRENT_STAGE="complete"
        return 0
    fi

    trap 'on_error $? ${LINENO} "${BASH_COMMAND}"' ERR
    trap 'finish $?' EXIT

    CURRENT_STAGE="live preflight"
    command -v codex >/dev/null || fail "codex executable is not available"
    [[ -x "${PYTHON}" || "${PYTHON}" == "python3" ]] || fail "Python interpreter is not executable: ${PYTHON}"
    [[ -x "${INIT_PROJECT}" ]] || fail "initializer is not executable: ${INIT_PROJECT}"
    [[ -x "${SPAWN}" ]] || fail "spawn wrapper is not executable: ${SPAWN}"
    [[ -x "${VERIFY_RESULT}" ]] || fail "result verifier is not executable: ${VERIFY_RESULT}"
    [[ -x "${CLOSE_LOOP}" ]] || fail "close-loop wrapper is not executable: ${CLOSE_LOOP}"
    [[ -r "${PRODUCT_ACCEPTANCE}" ]] || fail "product acceptance harness is missing: ${PRODUCT_ACCEPTANCE}"
    source_codex_home="${CODEX_HOME:-${HOME}/.codex}"
    [[ -f "${source_codex_home}/${PROFILE}.config.toml" ]] \
        || fail "Codex profile config is missing: ${source_codex_home}/${PROFILE}.config.toml"

    CURRENT_STAGE="project initialization"
    run_command "${PYTHON}" "${INIT_PROJECT}" "Fibonacci Tree CLI" \
        --goal "Deliver and verify a deterministic recursive-call-tree CLI end to end." \
        --project-id "${PROJECT_ID}" --projects-root "${PROJECTS_ROOT}" \
        --template-root "${FIXTURE_ROOT}/template" --tasks T001,T002,T003,T004,T005

    run_task T001 leader
    run_task T002 developer
    run_task T003 tester
    run_task T004 reviewer
    run_task T005 documenter
    verify_final_management_state

    RUN_STATUS="PASS"
    CURRENT_TASK="none"
    CURRENT_PHASE="none"
    CURRENT_STAGE="complete"
}

main "$@"
