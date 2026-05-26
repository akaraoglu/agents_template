#!/usr/bin/env python3
"""Deterministic fixture content for OpenClaw canaries."""

from __future__ import annotations

from textwrap import dedent


def smith_plan_draft() -> str:
    return dedent(
        """\
        # Plan: Single File Markdown Counter

        ## Overview
        Build a deterministic Python CLI that counts lines, words, and characters from one markdown file.

        ## Phases
        1. **T001: Core Counter Logic**
           - Implement deterministic counting helpers.
           - Define the data returned to the CLI.
        """
    )


def smith_backlog_draft() -> str:
    return dedent(
        """\
        # Backlog: Single File Markdown Counter

        - T001 READY
        """
    )


def task_t001_markdown_counter() -> str:
    return dedent(
        """\
        # Task T001: Core Counter Logic

        ## Goal
        Implement a minimal markdown counter CLI using Python standard library only.

        ## Required Outputs
        - README.md
        - src/main.py
        - tests/test_main.py

        ## Acceptance Criteria
        - The tool counts lines, words, and characters.
        - Tests cover the deterministic counting behavior.
        """
    )


def current_task_t001() -> str:
    return dedent(
        """\
        # Current Task: T001

        ## Task ID: T001
        ## Task Name: Core Counter Logic

        ## Instructions
        Read `management/tasks/T001.md` and implement the deterministic CLI defined there.
        """
    )


def architecture_t001_markdown_counter() -> str:
    return dedent(
        """\
        # T001 Architecture

        ## Overview
        Implement one small Python CLI in `src/main.py` with helpers for line, word, and character counts.

        ## Approach
        Keep the CLI deterministic and standard-library only.

        ## File Changes
        - `README.md`
        - `src/main.py`
        - `tests/test_main.py`

        ## Interfaces
        - `count_text(text: str) -> tuple[int, int, int]`
        - `main(argv: list[str] | None = None) -> int`
        - `main(argv)` treats `argv` as the CLI argument list excluding the program name.

        ## Risks
        - Incorrect word splitting.

        ## Implementation Notes
        - Prefer `pathlib.Path` for file reading.
        - Keep stdout stable and human-readable.
        - CLI smoke tests should call `main([tmp_path])`, not `main(["prog", tmp_path])`.

        ## Test Strategy
        - Add deterministic unit tests for `count_text`.
        - Add a CLI smoke test with a temporary markdown file.
        """
    )


def seeded_readme() -> str:
    return dedent(
        """\
        # Single File Markdown Counter

        Run:

        ```bash
        python -m src.main sample.md
        ```
        """
    )


def seeded_main_py() -> str:
    return dedent(
        """\
        from __future__ import annotations

        import sys
        from pathlib import Path


        def count_text(text: str) -> tuple[int, int, int]:
            line_count = 0 if not text else text.count("\\n") + (0 if text.endswith("\\n") else 1)
            word_count = len(text.split())
            char_count = len(text)
            return line_count, word_count, char_count


        def main(argv: list[str] | None = None) -> int:
            argv = list(sys.argv[1:] if argv is None else argv)
            if len(argv) != 1:
                print("usage: python -m src.main <path>")
                return 2
            text = Path(argv[0]).read_text(encoding="utf-8")
            lines, words, chars = count_text(text)
            print(f"lines={lines} words={words} chars={chars}")
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        """
    )


def seeded_test_main_py() -> str:
    return dedent(
        """\
        from __future__ import annotations

        import tempfile
        import unittest
        from pathlib import Path

        from src.main import count_text, main


        class CounterTests(unittest.TestCase):
            def test_count_text(self) -> None:
                self.assertEqual(count_text("one\\ntwo\\n"), (2, 2, 8))

            def test_main_reads_file(self) -> None:
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "sample.md"
                    path.write_text("one two\\nthree", encoding="utf-8")
                    self.assertEqual(main([str(path)]), 0)


        if __name__ == "__main__":
            unittest.main()
        """
    )
