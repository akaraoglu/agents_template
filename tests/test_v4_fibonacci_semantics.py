import json
from pathlib import Path

from AgenticTeam.scripts.run_e2e_fibonacci_v4_test import (
    latest_oracle_report,
    latest_oracle_repair_task_id,
    validate_fibonacci_visualizer_project,
)
from AgenticTeam.scripts.run_v4_team import validate_fibonacci_fixture_artifacts
from AgenticTeam.scripts.v4_contracts import EventV4


VALID_MAIN = """
def fibonacci(n):
    if n <= 0:
        return 0
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def generate_fibonacci_tree(depth, scale=1.0, angle=30.0, thickness=1):
    return [
        {
            "level": level,
            "fibonacci": fibonacci(level),
            "branches": fibonacci(level),
            "span": max(1, int(round(fibonacci(level) * scale))),
            "angle": angle,
            "thickness": thickness,
        }
        for level in range(1, max(0, depth) + 1)
    ]


def render_tree(layers, thickness=None):
    lines = []
    total = len(layers)
    for layer in layers:
        span = layer["span"]
        trunk = "|" * int(thickness or layer["thickness"])
        lines.append(" " * (total - layer["level"]) + "/" * span + trunk + chr(92) * span)
    return "\\n".join(lines) + "\\n"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("depth", type=int)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--angle", type=float, default=30.0)
    parser.add_argument("--thickness", type=int, default=1)
    args = parser.parse_args()
    print(render_tree(generate_fibonacci_tree(args.depth, args.scale, args.angle, args.thickness), args.thickness), end="")
"""


NUMERIC_ONLY_MAIN = """
def fibonacci(n):
    if n <= 0:
        return 0
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def generate_fibonacci_tree(depth, scale=1.0, angle=30.0, thickness=1):
    return fibonacci(depth)


def render_tree(tree, thickness=None):
    return str(tree) + "\\n"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("depth", type=int)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--angle", type=float, default=30.0)
    parser.add_argument("--thickness", type=int, default=1)
    args = parser.parse_args()
    print(render_tree(generate_fibonacci_tree(args.depth, args.scale, args.angle, args.thickness)), end="")
"""


HELPER_LEAK_MAIN = VALID_MAIN + """

def nonempty_lines(text):
    return [line for line in text.splitlines() if line.strip()]
"""


def write_project(tmp_path: Path, main_py: str) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(main_py, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text(
        "from src.main import generate_fibonacci_tree, render_tree\n\n"
        "def nonempty_lines(text):\n"
        "    return [line for line in text.splitlines() if line.strip()]\n",
        encoding="utf-8",
    )
    (tmp_path / ".openclaw").mkdir()
    (tmp_path / ".openclaw" / "state.json").write_text(
        json.dumps({"phase": "DONE", "waiting_for": "none"}),
        encoding="utf-8",
    )
    (tmp_path / "PROJECT_STATE.md").write_text(
        "# Project State\n\n- **phase**: DONE\n- **waiting_for**: none\n",
        encoding="utf-8",
    )
    return tmp_path


def test_fibonacci_semantic_gate_accepts_branch_drawing_project(tmp_path):
    workspace = write_project(tmp_path, VALID_MAIN)

    assert validate_fibonacci_visualizer_project(workspace) == []


def test_fibonacci_semantic_gate_rejects_numeric_only_project(tmp_path):
    workspace = write_project(tmp_path, NUMERIC_ONLY_MAIN)

    errors = validate_fibonacci_visualizer_project(workspace)

    assert errors
    assert any("numeric-only" in error or "semantic probe failed" in error for error in errors)


def test_runtime_fibonacci_fixture_gate_rejects_missing_public_fibonacci(tmp_path):
    workspace = write_project(tmp_path, VALID_MAIN.replace("def fibonacci(", "def fib_simple(").replace("fibonacci(level)", "fib_simple(level)"))

    errors = validate_fibonacci_fixture_artifacts(workspace)

    assert any("defines fibonacci 0 times" in error for error in errors)
    assert any("must import and test the public fibonacci function" in error for error in errors)


def test_fibonacci_semantic_gate_rejects_test_helper_in_src(tmp_path):
    workspace = write_project(tmp_path, HELPER_LEAK_MAIN)

    errors = validate_fibonacci_visualizer_project(workspace)

    assert any("nonempty_lines leaked" in error for error in errors)


def test_fibonacci_semantic_gate_rejects_importing_test_helper_from_src(tmp_path):
    workspace = write_project(tmp_path, VALID_MAIN)
    (workspace / "tests" / "test_main.py").write_text(
        "from src.main import generate_fibonacci_tree, render_tree, nonempty_lines\n",
        encoding="utf-8",
    )

    errors = validate_fibonacci_visualizer_project(workspace)

    assert any("must not import nonempty_lines" in error for error in errors)


def test_latest_oracle_repair_task_id_returns_newest_repair_task():
    events = [
        EventV4(event_type="task_planned", payload={"task_id": "T001", "title": "Implement thing"}, actor="smith"),
        EventV4(
            event_type="task_planned",
            payload={"task_id": "T002", "title": "Repair project based on Oracle failure: bad output"},
            actor="smith",
        ),
        EventV4(
            event_type="task_planned",
            payload={"task_id": "T003", "title": "Repair project based on Oracle failure: still bad"},
            actor="smith",
        ),
    ]

    assert latest_oracle_repair_task_id(events) == "T003"


def test_latest_oracle_report_can_be_scoped_to_current_dispatch():
    old_events = [
        EventV4(event_type="oracle_failed", payload={"summary": "old failure"}, actor="oracle"),
        EventV4(event_type="oracle_dispatched", payload={"lease_id": "new"}, actor="smith"),
    ]

    assert latest_oracle_report(old_events[1:]) is None
