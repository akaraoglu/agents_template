from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = REPO_ROOT / "AgenticTeam" / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import agent_tools
import python_claw


class PythonClawTests(unittest.TestCase):
    def _env(self, allowed_root: Path) -> dict[str, str]:
        return {
            "PYTHON_CLAW_TEST_MODE": "1",
            "PYTHON_CLAW_VENV": str(REPO_ROOT / "env-python"),
            "PYTHON_CLAW_ALLOWED_ROOTS": str(allowed_root),
        }

    def _run(self, argv: list[str], *, allowed_root: Path) -> tuple[int, str]:
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, self._env(allowed_root), clear=False):
            with contextlib.redirect_stdout(stdout):
                rc = python_claw.run(argv)
        return rc, stdout.getvalue()

    def test_module_unittest_passes_without_shell_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_sample.py").write_text(
                "import unittest\n\n"
                "class SampleTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertEqual(1 + 1, 2)\n",
                encoding="utf-8",
            )

            rc, output = self._run(
                ["--cwd", str(root), "--module", "unittest", "--", "discover", "-s", "tests"],
                allowed_root=root,
            )

        self.assertEqual(rc, 0)
        self.assertIn("PYTHON_CLAW_RESULT=pass", output)
        self.assertIn('"kind": "module"', output)

    def test_syntax_check_failure_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            (root / "bad.py").write_text("def broken(:\n", encoding="utf-8")

            rc, output = self._run(
                ["--cwd", str(root), "--syntax-check", "bad.py"],
                allowed_root=root,
            )

        self.assertEqual(rc, 10)
        self.assertIn("PYTHON_CLAW_RESULT=fail", output)
        self.assertIn("PYTHON_CLAW_FAILED[failed]", output)
        self.assertIn("SyntaxError", output)

    def test_relative_target_cannot_escape_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            cwd = root / "draft"
            cwd.mkdir()
            (root / "outside.py").write_text("print('no')\n", encoding="utf-8")

            rc, output = self._run(
                ["--cwd", str(cwd), "--syntax-check", "../outside.py"],
                allowed_root=root,
            )

        self.assertEqual(rc, 2)
        self.assertIn("PYTHON_CLAW_FAILED[invalid_request]", output)
        self.assertIn("escapes cwd", output)

    def test_agent_tools_python_claw_uses_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            (root / "ok.py").write_text("value = 1\n", encoding="utf-8")
            with mock.patch.dict(os.environ, self._env(root), clear=False):
                output = agent_tools.python_claw(root, "syntax_check", "ok.py")

        self.assertIn("PYTHON_CLAW_RESULT=pass", output)


if __name__ == "__main__":
    unittest.main()
