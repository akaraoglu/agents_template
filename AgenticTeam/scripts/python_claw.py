#!/usr/bin/env python3
"""Structured Python runner for OpenClaw agents.

The live helper wrapper stays in /home/alik/workspace/clawspace/bin, but this
adapter remains in the repository like the other role helpers. It executes the
canonical clawspace virtualenv without requiring agents to activate it or build
raw shell commands.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_VENV_ROOT = Path("/home/alik/workspace/clawspace/venv-claw")
DEFAULT_ALLOWED_ROOTS = (Path("/home/alik/workspace/clawspace"),)
DEFAULT_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 4000
MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class PythonClawUsageError(ValueError):
    """Raised for invalid python_claw requests."""


class PythonClawArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PythonClawUsageError(message)


def is_test_mode() -> bool:
    return os.environ.get("PYTHON_CLAW_TEST_MODE") == "1"


def venv_root() -> Path:
    if is_test_mode() and os.environ.get("PYTHON_CLAW_VENV"):
        return Path(os.environ["PYTHON_CLAW_VENV"]).expanduser()
    return DEFAULT_VENV_ROOT


def venv_python() -> Path:
    root = venv_root().resolve()
    candidate = root / "bin" / "python"
    if candidate.is_file():
        return candidate
    raise PythonClawUsageError(f"missing Python interpreter at {candidate}")


def allowed_roots() -> tuple[Path, ...]:
    if is_test_mode() and os.environ.get("PYTHON_CLAW_ALLOWED_ROOTS"):
        return tuple(
            Path(item).expanduser().resolve()
            for item in os.environ["PYTHON_CLAW_ALLOWED_ROOTS"].split(os.pathsep)
            if item
        )
    return tuple(root.resolve() for root in DEFAULT_ALLOWED_ROOTS)


def ensure_inside(path: Path, roots: tuple[Path, ...], *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    roots_text = ", ".join(str(root) for root in roots)
    raise PythonClawUsageError(f"{label} is outside allowed roots: {roots_text}")


def resolve_cwd(raw_cwd: str | None) -> Path:
    if not raw_cwd:
        raise PythonClawUsageError("--cwd is required for Python execution")
    cwd = Path(raw_cwd).expanduser()
    if not cwd.is_absolute():
        raise PythonClawUsageError("--cwd must be an absolute directory")
    resolved = ensure_inside(cwd, allowed_roots(), label="cwd")
    if not resolved.is_dir():
        raise PythonClawUsageError(f"cwd does not exist or is not a directory: {resolved}")
    return resolved


def resolve_relative_target(cwd: Path, raw_target: str, *, label: str, require_file: bool = True) -> Path:
    target = Path(raw_target)
    if target.is_absolute():
        raise PythonClawUsageError(f"{label} must be relative to cwd")
    resolved = (cwd / target).resolve()
    if not (resolved == cwd or resolved.is_relative_to(cwd)):
        raise PythonClawUsageError(f"{label} escapes cwd")
    if require_file and not resolved.is_file():
        raise PythonClawUsageError(f"{label} does not exist or is not a file: {raw_target}")
    return resolved


def build_parser() -> PythonClawArgumentParser:
    parser = PythonClawArgumentParser(description="Run Python through the clawspace venv with structured arguments.")
    parser.add_argument("--cwd", help="Existing execution directory under an allowed clawspace root.")
    parser.add_argument("--module", help="Run a Python module, equivalent to python -m <module>.")
    parser.add_argument("--script", help="Run a cwd-relative Python script.")
    parser.add_argument("--syntax-check", help="Compile-check a cwd-relative Python file.")
    parser.add_argument("--version", action="store_true", help="Print the clawspace Python version.")
    return parser


def normalize_extra_args(extra_args: list[str]) -> list[str]:
    if extra_args and extra_args[0] == "--":
        return extra_args[1:]
    return extra_args


def command_from_args(args: argparse.Namespace, extra_args: list[str]) -> tuple[list[str], Path | None, str]:
    py = venv_python()
    selected = [
        bool(args.module),
        bool(args.script),
        bool(args.syntax_check),
        bool(args.version),
    ]
    if sum(selected) != 1:
        raise PythonClawUsageError("choose exactly one of --module, --script, --syntax-check, or --version")

    passthrough = normalize_extra_args(extra_args)
    if args.version:
        if passthrough:
            raise PythonClawUsageError("--version does not accept extra arguments")
        return [str(py), "--version"], None, "version"

    cwd = resolve_cwd(args.cwd)
    if args.module:
        if not MODULE_RE.match(args.module):
            raise PythonClawUsageError("--module must be a dotted Python module name")
        return [str(py), "-m", args.module, *passthrough], cwd, "module"

    if args.script:
        script = resolve_relative_target(cwd, args.script, label="script")
        relative_script = script.relative_to(cwd).as_posix()
        return [str(py), relative_script, *passthrough], cwd, "script"

    target = resolve_relative_target(cwd, args.syntax_check, label="syntax target")
    relative_target = target.relative_to(cwd).as_posix()
    if passthrough:
        raise PythonClawUsageError("--syntax-check does not accept extra arguments")
    return [str(py), "-m", "py_compile", relative_target], cwd, "syntax_check"


def excerpt(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n...<truncated>"


def emit_failure(code: str, message: str, *, exit_code: int = 2) -> int:
    payload = {
        "status": "invalid_request" if code in {"invalid_request", "missing_venv"} else code,
        "code": code,
        "message": message,
    }
    print(f"PYTHON_CLAW_FAILED[{code}]: {message}")
    print("PYTHON_CLAW_JSON=" + json.dumps(payload, sort_keys=True))
    return exit_code


def emit_result(
    *,
    status: str,
    code: str,
    kind: str,
    command: list[str],
    cwd: Path | None,
    returncode: int | None,
    stdout: str,
    stderr: str,
    duration_ms: int,
    message: str,
) -> int:
    payload: dict[str, Any] = {
        "status": status,
        "code": code,
        "kind": kind,
        "cwd": str(cwd) if cwd else None,
        "python": command[0],
        "returncode": returncode,
        "duration_ms": duration_ms,
        "stdout_excerpt": excerpt(stdout),
        "stderr_excerpt": excerpt(stderr),
        "message": message,
    }
    print(f"PYTHON_CLAW_RESULT={status}")
    if status != "pass":
        print(f"PYTHON_CLAW_FAILED[{code}]: {message}")
    print("PYTHON_CLAW_JSON=" + json.dumps(payload, sort_keys=True))
    if stdout:
        print("STDOUT_BEGIN")
        print(excerpt(stdout).rstrip())
        print("STDOUT_END")
    if stderr:
        print("STDERR_BEGIN")
        print(excerpt(stderr).rstrip())
        print("STDERR_END")
    return 0 if status == "pass" else 10


def run(argv: list[str]) -> int:
    parser = build_parser()
    try:
        args, extra_args = parser.parse_known_args(argv)
        command, cwd, kind = command_from_args(args, extra_args)
    except PythonClawUsageError as exc:
        code = "missing_venv" if "missing Python interpreter" in str(exc) else "invalid_request"
        return emit_failure(code, str(exc), exit_code=2)

    start = time.monotonic()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return emit_result(
            status="timeout",
            code="timeout",
            kind=kind,
            command=command,
            cwd=cwd,
            returncode=None,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            duration_ms=duration_ms,
            message=f"Python command timed out after {DEFAULT_TIMEOUT_SECONDS} seconds.",
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    status = "pass" if result.returncode == 0 else "fail"
    code = "ok" if status == "pass" else "failed"
    message = "Python command passed." if status == "pass" else "Python command failed."
    return emit_result(
        status=status,
        code=code,
        kind=kind,
        command=command,
        cwd=cwd,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        duration_ms=duration_ms,
        message=message,
    )


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
