#!/usr/bin/env python3
"""
update-tasks.py — Safely update TASKS.md table rows (replaces fragile sed commands)

Usage:
    update-tasks.py <TASKS_FILE> --task T002 --status Completed --owner "Developer" --verification "7/7 tests pass" --evidence "results/t002.json" [--history "T002 completed at 15:36"]

Reads the markdown table, finds the row for the task ID, updates all columns in place.
If --add-history is given, appends a line to the Task History section.

Examples:
    update-tasks.py TASKS.md --task T002 --status Completed --verification "pytest passed"
    update-tasks.py TASKS.md --task T003 --history "T003: Tester verified 7 TCs"
"""
import argparse, re, sys

def read_tasks(path: str) -> tuple[str, str]:
    """Parse TASKS.md into table content and history section."""
    with open(path) as f:
        text = f.read()
    
    # Split on Task History header if present
    history_split = text.split("## Task History", 1)
    table_content = history_split[0]
    history_section = history_split[1] if len(history_split) > 1 else ""
    
    return table_content, history_section

def update_row(table: str, task_id: str, updates: dict[str, str]) -> str:
    """Find and update a markdown table row for the given task ID."""
    lines = table.split('\n')
    updated = False
    
    for i, line in enumerate(lines):
        if re.match(r"\|\s*" + re.escape(task_id) + r"\s*\|", line):
            # Parse current columns
            cols = [c.strip() for c in line.split('|')[1:-1]]  # Remove outer pipes
            
            # Column positions: 0=TaskID, 1=Description, 2=Status, 3=Owner, 4=Verification, 5=Evidence
            if "status" in updates:
                cols[2] = updates["status"]
            if "owner" in updates:
                cols[3] = updates["owner"]
            if "verification" in updates:  
                cols[4] = updates["verification"]
            if "evidence" in updates:
                cols[5] = updates["evidence"]
            
            # Reconstruct line
            lines[i] = "|" + "|".join(f" {c} " for c in cols) + "|"
            updated = True
            break
    
    if not updated:
        print(f"⚠️ Task {task_id} not found in table", file=sys.stderr)
    
    return '\n'.join(lines)

def add_history(history: str, message: str) -> str:
    """Append a bullet point to Task History section."""
    # Add blank line separator if needed
    if history and not history.endswith('\n'):
        history += '\n'
    history += f"- {message}\n"
    return history

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="Path to TASKS.md file")
    parser.add_argument("--task", required=True, help="Task ID to update (e.g., T002)")
    parser.add_argument("--status", default=None, help="New status value")
    parser.add_argument("--owner", default=None, help="Owner name")  
    parser.add_argument("--verification", default=None, help="Verification notes")
    parser.add_argument("--evidence", default=None, help="Evidence path")
    parser.add_argument("--history", default=None, help="History line to append (format: T002 completed at 15:36)")
    args = parser.parse_args()
    
    table_content, history = read_tasks(args.file)
    
    # Build updates dict from provided args
    updates = {}
    for key in ["status", "owner", "verification", "evidence"]:
        val = getattr(args, key)
        if val:
            updates[key] = val
    
    if not updates and not args.history:
        print("⚠️ No update values provided (use --status, --owner, --verification, --evidence)", file=sys.stderr)
        sys.exit(1)
    
    # Update table row
    if updates:
        table_content = update_row(table_content, args.task, updates)
    
    # Add history line
    if args.history:
        history = add_history(history, args.history)
    
    # Write back
    final_text = table_content + "\n\n## Task History\n" + history
    with open(args.file, 'w') as f:
        f.write(final_text)
    
    print(f"✅ Updated TASKS.md")

if __name__ == "__main__":
    main()
