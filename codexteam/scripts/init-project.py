#!/usr/bin/env python3
"""
init-project.py — Create a standard CodexTeam project workspace

Usage:
    init-project.py <PROJECT_NAME> [--tasks T001,...] [--template TEMPLATE_FILE]

Creates:
    /home/alik/workspace/codexspace/projects/<PROJECT_NAME>/
    ├── PROJECT.md       ← Functional/non-functional requirements table
    ├── TASKS.md         ← Task tracking table with status columns  
    ├── results/         ← For spawn result JSONs
    ├── src/             ← Source code directory
    └── tests/           ← Test suite directory

Examples:
    init-project.py fibonacci-e2e-test
    init-project.py my-app-2026 --tasks T001,T002,T003
"""
import argparse, sys, os, pathlib
from datetime import datetime

PROJECTS_ROOT = "/home/alik/workspace/codexspace/projects"

def create_workspace(name: str, tasks: list[str], template_path: str = None) -> str:
    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_dir = pathlib.Path(PROJECTS_ROOT) / f"{name}-{now}"
    
    # Create directory structure
    (project_dir / "results").mkdir(parents=True, exist_ok=True)
    (project_dir / "src").mkdir(exist_ok=True)
    (project_dir / "tests").mkdir(exist_ok=True)
    
    # Write PROJECT.md from template or default
    if template_path and os.path.exists(template_path):
        with open(template_path) as f:
            project_md = f.read()
    else:
        project_md = _default_project_md(name)
    
    (project_dir / "PROJECT.md").write_text(project_md)
    
    # Write TASKS.md
    tasks_md = _default_tasks_md(tasks, name)
    (project_dir / "TASKS.md").write_text(tasks_md)
    
    return str(project_dir)

def _default_project_md(name: str) -> str:
    return f"""# {name}

## 1. Overview
[Project description to be filled]

## 2. Functional Requirements  
| ID | Requirement | Priority |
|----|-------------|----------|
| [Add requirements here]

## 3. Non-Functional Requirements
| ID | Requirement | Target |
|----|-------------|--------|
| NFR1 | Python standard library only | Hard constraint |

## 4. Test Cases
| TC | Input | Expected Output | Exit Code |
|----|-------|-----------------|-----------|
| [Add test cases here]
"""

def _default_tasks_md(tasks: list[str], name: str) -> str:
    task_rows = ""
    owners = ["Writer", "Developer", "Tester"]
    for i, tid in enumerate(tasks):
        owner = owners[i % len(owners)] if i < len(tasks) else "Leader"
        task_rows += f"| {tid} | [description] | Pending | {owner} | TBD | `results/{tid.lower()}.json` |\n"
    
    return f"""# TASKS.md: {name}

| Task ID | Description | Status | Owner | Verification | Evidence |
|---------|-------------|--------|-------|--------------|----------|
{task_rows.rstrip()}

## Task History
- Awaiting execution...
"""

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="Project name (timestamp appended automatically)")
    parser.add_argument("--tasks", default="T001,T002,T003", help="Comma-separated task IDs")
    parser.add_argument("--template", help="Path to custom PROJECT.md template file")
    args = parser.parse_args()
    
    try:
        project_dir = create_workspace(args.name, [t.strip().upper() for t in args.tasks.split(",")], args.template)
        print(f"✅ Project created: {project_dir}")
        print(f"   Files: PROJECT.md, TASKS.md")
        print(f"   Dirs:  results/, src/, tests/")
    except Exception as e:
        print(f"❌ Failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
