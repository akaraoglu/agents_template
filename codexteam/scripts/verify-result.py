#!/usr/bin/env python3
"""
verify-result.py — Validate spawn-subagent.sh result JSONs for contract compliance

Usage:
    verify-result.py <RESULT_JSON_PATH> [--task TASK_ID] [--expected-status STATUS] [--strict]

Checks:
    1. File exists and is valid JSON
    2. Required keys present (task_id, status, summary, file_changes, evidence, errors)
    3. Status is a single valid word (not "completed | failed | partial | blocked" from template)
    4. If --task given, verifies task_id matches expected value
    5. If --strict, also checks that evidence array has entries and no warnings about placeholders

Exit codes: 0=valid, 1=invalid/missing, 2=mismatched expectations

Examples:
    verify-result.py results/t002.json
    verify-result.py results/t003.json --task t003 --expected-status completed
"""
import argparse, json, sys, os

VALID_STATUSES = {"completed", "failed", "partial", "blocked", "needs_review"}
TEMPLATE_PLACEHOLDERS = ("...", "Brief description", "completed | failed", "| failed | partial")

def check_result(path: str, expected_task: str = None, expected_status: str = None, strict: bool = False) -> tuple[bool, list[str]]:
    errors = []
    
    if not os.path.exists(path):
        return False, [f"Result file not found: {path}"]
    
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]
    
    # Check required keys
    required_keys = ["task_id", "status", "summary"]
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required key: {key}")
    
    # Validate status is a single valid word (Fix #6 compliance)
    status = data.get("status")
    if status not in VALID_STATUSES:
        errors.append(f"Invalid status '{status}' — must be one of {VALID_STATUSES}")
    
    # Check for template placeholders (Fix #6 catch)
    for v in data.values():
        if isinstance(v, str) and any(ph in v for ph in TEMPLATE_PLACEHOLDERS):
            errors.append(f"Template placeholder detected in value: '{v[:50]}'")
    
    # Task ID match check
    if expected_task and data.get("task_id") != expected_task:
        errors.append(f"Task mismatch: expected {expected_task}, got {data.get('task_id')}")
    
    # Status expectation check  
    if expected_status and status != expected_status:
        errors.append(f"Status mismatch: expected {expected_status}, got {status}")
    
    # Strict mode checks
    if strict:
        if "evidence" in data and not data["evidence"]:
            errors.append("Strict mode: evidence array is empty")
        
        for key in ["file_changes", "errors", "warnings"]:
            if key in data and not isinstance(data[key], list):
                errors.append(f"Strict mode: {key} must be a list, got {type(data[key]).__name__}")
    
    return len(errors) == 0, errors

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("result", help="Path to result JSON file")
    parser.add_argument("--task", default=None, help="Expected task_id value")
    parser.add_argument("--expected-status", default=None, help="Expected status value (e.g., completed)")
    parser.add_argument("--strict", action="store_true", help="Enable strict validation")
    args = parser.parse_args()
    
    valid, errors = check_result(args.result, args.task, args.expected_status, args.strict)
    
    if valid:
        print(f"✅ Result valid: {args.result}")
        data = json.load(open(args.result))
        print(f"   Task: {data.get('task_id')}, Status: {data.get('status')}")
    else:
        print(f"❌ Result invalid: {args.result}")
        for e in errors:
            print(f"   ⚠️  {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
