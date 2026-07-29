from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import time
from pathlib import Path
from typing import Any

from .paths import PathValidationError, contained_path
from .team_context import TeamContextError, TeamContextReader

REPOSITORY_SEARCH_MODES = ("fixed", "regex")
REPOSITORY_SEARCH_SCOPES = ("all", "source", "tests", "config")
CHANGE_DETAIL_LEVELS = ("summary", "diff")
MAX_REPOSITORY_RESULTS = 20
MAX_CHANGE_PATHS = 100
MAX_MATCH_CHARS = 400
MAX_DIFF_CHARS = 4_000
COMMAND_TIMEOUT_SECONDS = 10

_SEARCH_GLOBS = {
    "all": (
        "!results/**",
        "!.playwright-cli/**",
        "!dist/**",
        "!build/**",
        "!node_modules/**",
    ),
    "source": (
        "!results/**",
        "!.playwright-cli/**",
        "!dist/**",
        "!build/**",
        "!node_modules/**",
        "!tests/**",
        "!test/**",
        "!**/*_test.*",
        "!**/*.test.*",
        "!**/*.spec.*",
        "**/*.py",
        "**/*.js",
        "**/*.mjs",
        "**/*.cjs",
        "**/*.ts",
        "**/*.tsx",
        "**/*.jsx",
        "**/*.go",
        "**/*.rs",
        "**/*.c",
        "**/*.cc",
        "**/*.cpp",
        "**/*.h",
        "**/*.hpp",
        "**/*.java",
        "**/*.kt",
        "**/*.swift",
        "**/*.rb",
        "**/*.php",
        "**/*.sh",
        "**/*.css",
        "**/*.html",
        "**/*.vue",
        "**/*.svelte",
        "!results/**",
        "!.playwright-cli/**",
        "!dist/**",
        "!build/**",
        "!node_modules/**",
        "!tests/**",
        "!test/**",
        "!**/*_test.*",
        "!**/*.test.*",
        "!**/*.spec.*",
    ),
    "tests": (
        "!results/**",
        "!.playwright-cli/**",
        "!node_modules/**",
        "tests/**",
        "test/**",
        "**/*_test.*",
        "**/*.test.*",
        "**/*.spec.*",
        "!results/**",
        "!.playwright-cli/**",
        "!node_modules/**",
    ),
    "config": (
        "!results/**",
        "!.playwright-cli/**",
        "!node_modules/**",
        "*.toml",
        "*.json",
        "*.yaml",
        "*.yml",
        "*.ini",
        "*.cfg",
        "*.conf",
        "Makefile",
        "Dockerfile",
        "!results/**",
        "!.playwright-cli/**",
        "!node_modules/**",
    ),
}
_SUSPICIOUS_PATTERNS = (
    re.compile(
        r"(^|/)(__pycache__|\.pytest_cache|\.playwright-cli|node_modules)(/|$)"
    ),
    re.compile(r"\.(pyc|pyo|log|tmp|swp)$", re.IGNORECASE),
    re.compile(r"(^|/)(coverage|dist|build)(/|$)", re.IGNORECASE),
)


class RepositoryContextReader:
    def __init__(self, context: TeamContextReader) -> None:
        self.context = context

    def search_repository(
        self,
        project: str,
        query: str,
        *,
        mode: str = "fixed",
        scope: str = "all",
        case_sensitive: bool = False,
        path: str | None = None,
        file_glob: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        root = self.context.project_root(project)
        clean_query = query.strip()
        if not clean_query or len(clean_query) > 200:
            raise TeamContextError("query must contain 1-200 characters")
        if mode not in REPOSITORY_SEARCH_MODES:
            raise TeamContextError(
                f"mode must be one of: {', '.join(REPOSITORY_SEARCH_MODES)}"
            )
        if scope not in REPOSITORY_SEARCH_SCOPES:
            raise TeamContextError(
                f"scope must be one of: {', '.join(REPOSITORY_SEARCH_SCOPES)}"
            )
        if not isinstance(case_sensitive, bool):
            raise TeamContextError("case_sensitive must be a boolean")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_REPOSITORY_RESULTS
        ):
            raise TeamContextError(
                f"limit must be between 1 and {MAX_REPOSITORY_RESULTS}"
            )
        target = root
        target_argument = "."
        if path is not None:
            target = contained_path(root, path, label="repository search path")
            if target.is_symlink() or not target.exists():
                raise TeamContextError(
                    f"repository search path is missing or unsafe: {path}"
                )
            target_argument = target.relative_to(root).as_posix()
        if file_glob is not None:
            _validate_glob(file_glob)

        command = [
            "rg",
            "--json",
            "--line-number",
            "--column",
            "--color",
            "never",
            "--max-columns",
            "1000",
            "--max-columns-preview",
        ]
        if mode == "fixed":
            command.append("--fixed-strings")
        if not case_sensitive:
            command.append("--ignore-case")
        for pattern in _SEARCH_GLOBS[scope]:
            command.extend(("--glob", pattern))
        if file_glob is not None:
            command.extend(("--glob", file_glob))
        command.extend(("--", clean_query, target_argument))

        scan_limit = min(MAX_REPOSITORY_RESULTS * 4, max(limit * 4, limit))
        candidates: list[dict[str, Any]] = []
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_command_environment(),
        )
        assert process.stdout is not None
        terminated = False
        deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, COMMAND_TIMEOUT_SECONDS)
                ready = selector.select(timeout=remaining)
                if not ready:
                    raise subprocess.TimeoutExpired(command, COMMAND_TIMEOUT_SECONDS)
                raw_line = process.stdout.readline()
                if not raw_line:
                    break
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "match":
                    continue
                match = _search_match(event.get("data"), clean_query)
                if match is None:
                    continue
                candidates.append(match)
                if len(candidates) >= scan_limit:
                    process.terminate()
                    terminated = True
                    break
            _, stderr = process.communicate(timeout=COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise TeamContextError("repository search timed out") from exc
        except OSError as exc:
            process.kill()
            process.communicate()
            raise TeamContextError(f"repository search failed: {exc}") from exc
        finally:
            selector.close()
        if not terminated and process.returncode not in {0, 1}:
            raise TeamContextError(
                f"repository search failed: {stderr.strip() or process.returncode}"
            )

        candidates.sort(
            key=lambda item: (
                -item.pop("_score"),
                item["path"],
                item["line"],
                item["column"],
            )
        )
        matches = candidates[:limit]
        source_paths = sorted({match["path"] for match in matches})
        sources = [
            self.context.source(root, contained_path(root, relative))
            for relative in source_paths
        ]
        return {
            "project": project,
            "query": clean_query,
            "mode": mode,
            "scope": scope,
            "case_sensitive": case_sensitive,
            "path": path,
            "file_glob": file_glob,
            "matches": matches,
            "matches_considered": len(candidates),
            "truncated": terminated or len(candidates) > limit,
            "sources": sources,
        }

    def get_change_summary(
        self,
        project: str,
        *,
        detail: str = "summary",
        limit: int = 40,
    ) -> dict[str, Any]:
        root = self.context.project_root(project)
        if detail not in CHANGE_DETAIL_LEVELS:
            raise TeamContextError(
                f"detail must be one of: {', '.join(CHANGE_DETAIL_LEVELS)}"
            )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_CHANGE_PATHS
        ):
            raise TeamContextError(f"limit must be between 1 and {MAX_CHANGE_PATHS}")
        git_dir = root / ".git"
        if git_dir.is_symlink() or not git_dir.exists():
            raise TeamContextError("project is not a Git repository")

        status_output = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        changes = _parse_porcelain(status_output)
        changes.sort(key=lambda item: (item["path"], item["index"], item["worktree"]))
        branch = _git_text(
            root,
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            allow_failure=True,
        )
        head = _git_text(
            root,
            "rev-parse",
            "--verify",
            "HEAD",
            allow_failure=True,
        )
        staged_stat = _git_text(
            root,
            "diff",
            "--cached",
            "--shortstat",
            allow_failure=True,
        )
        unstaged_stat = _git_text(
            root,
            "diff",
            "--shortstat",
            allow_failure=True,
        )
        suspicious = [
            change["path"]
            for change in changes
            if _suspicious_path(change["path"])
        ]
        result: dict[str, Any] = {
            "project": project,
            "branch": branch or None,
            "head": head or None,
            "clean": not changes,
            "counts": {
                "changed": len(changes),
                "staged": sum(change["index"] not in {" ", "?"} for change in changes),
                "unstaged": sum(change["worktree"] not in {" ", "?"} for change in changes),
                "untracked": sum(
                    change["index"] == "?" and change["worktree"] == "?"
                    for change in changes
                ),
                "suspicious": len(suspicious),
            },
            "staged_stat": staged_stat or None,
            "unstaged_stat": unstaged_stat or None,
            "changes": changes[:limit],
            "suspicious_paths": suspicious[:limit],
            "truncated": len(changes) > limit or len(suspicious) > limit,
            "sources": [],
        }
        if detail == "diff":
            unstaged_diff = _git_text(
                root,
                "diff",
                "--no-ext-diff",
                "--unified=1",
                allow_failure=True,
            )
            staged_diff = _git_text(
                root,
                "diff",
                "--cached",
                "--no-ext-diff",
                "--unified=1",
                allow_failure=True,
            )
            result["diff_excerpt"] = {
                "unstaged": _truncate(unstaged_diff, MAX_DIFF_CHARS // 2),
                "staged": _truncate(staged_diff, MAX_DIFF_CHARS // 2),
                "bounded_chars": MAX_DIFF_CHARS,
            }
        return result

    def project_git_state(self, project: str) -> dict[str, Any]:
        try:
            summary = self.get_change_summary(project, limit=10)
        except TeamContextError as exc:
            return {"available": False, "error": str(exc)}
        return {
            "available": True,
            "branch": summary["branch"],
            "head": summary["head"],
            "clean": summary["clean"],
            "counts": summary["counts"],
            "suspicious_paths": summary["suspicious_paths"],
        }


def _search_match(data: Any, query: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    path_data = data.get("path")
    lines = data.get("lines")
    submatches = data.get("submatches")
    if not isinstance(path_data, dict) or not isinstance(lines, dict):
        return None
    path = path_data.get("text")
    text = lines.get("text")
    line_number = data.get("line_number")
    if (
        not isinstance(path, str)
        or not isinstance(text, str)
        or not isinstance(line_number, int)
    ):
        return None
    first = submatches[0] if isinstance(submatches, list) and submatches else {}
    column = first.get("start", 0) + 1 if isinstance(first, dict) else 1
    clean_text = text.rstrip("\r\n")
    lowered = clean_text.lower()
    query_lower = query.lower()
    score = 1
    if query in clean_text:
        score += 5
    if query_lower in lowered:
        score += 3
    if query_lower in Path(path).name.lower():
        score += 2
    return {
        "path": Path(path).as_posix(),
        "line": line_number,
        "column": column,
        "text": _truncate(clean_text.strip(), MAX_MATCH_CHARS),
        "_score": score,
    }


def _validate_glob(value: str) -> None:
    if (
        not value
        or len(value) > 120
        or value.startswith(("/", "\\"))
        or "\\" in value
        or ".." in value.split("/")
    ):
        raise PathValidationError(f"unsafe file_glob: {value!r}")


def _parse_porcelain(value: bytes) -> list[dict[str, str]]:
    fields = value.split(b"\0")
    changes: list[dict[str, str]] = []
    index = 0
    while index < len(fields):
        raw = fields[index]
        index += 1
        if not raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        if len(text) < 4 or text[2] != " ":
            continue
        xy = text[:2]
        item = {
            "path": text[3:],
            "index": xy[0],
            "worktree": xy[1],
        }
        if "R" in xy or "C" in xy:
            if index < len(fields) and fields[index]:
                item["original_path"] = fields[index].decode(
                    "utf-8",
                    errors="replace",
                )
                index += 1
        changes.append(item)
    return changes


def _suspicious_path(path: str) -> bool:
    return any(pattern.search(path) is not None for pattern in _SUSPICIOUS_PATTERNS)


def _command_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["LC_ALL"] = "C.UTF-8"
    return environment


def _git(root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            env=_command_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TeamContextError(f"Git inspection failed: {exc}") from exc
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise TeamContextError(f"Git inspection failed: {error or completed.returncode}")
    return completed.stdout


def _git_text(
    root: Path,
    *arguments: str,
    allow_failure: bool = False,
) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            env=_command_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TeamContextError(f"Git inspection failed: {exc}") from exc
    if completed.returncode != 0:
        if allow_failure:
            return ""
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise TeamContextError(f"Git inspection failed: {error or completed.returncode}")
    return completed.stdout.decode("utf-8", errors="replace").strip()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
