from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from codexteam_tools.repository_binding import RepositoryBindingError, load_repository_binding


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def fixture(tmp_path: Path, *, subtree: bool = True) -> tuple[Path, Path, Path]:
    control = tmp_path / "control"
    git_root = tmp_path / "checkout" / "repo"
    work = git_root / "component" if subtree else git_root
    control.mkdir()
    work.mkdir(parents=True)
    git(git_root, "init", "-q")
    git(git_root, "remote", "add", "origin", "ssh://example.test/repo")
    (control / "REPOSITORIES.json").write_text(json.dumps({
        "schema_version": "1.0",
        "repositories": [{
            "id": "component",
            "work_root": str(work),
            "git_root": str(git_root),
            "git_prefix": "component" if subtree else ".",
            "remote_url": "ssh://example.test/repo",
            "write_policy": "task-owned",
        }],
    }))
    return control, work, git_root


def test_repository_binding_accepts_registered_subtree(tmp_path: Path):
    control, work, git_root = fixture(tmp_path)
    binding = load_repository_binding(control, work, "component")
    assert binding.work_root == work
    assert binding.git_root == git_root
    assert binding.git_prefix == "component"


def test_repository_binding_accepts_exact_git_root(tmp_path: Path):
    control, work, git_root = fixture(tmp_path, subtree=False)
    binding = load_repository_binding(control, work, "component")
    assert binding.work_root == binding.git_root == git_root
    assert binding.git_prefix == "."


def test_repository_binding_accepts_checkout_root_plus_path(tmp_path: Path):
    control, work, _ = fixture(tmp_path)
    registry = json.loads((control / "REPOSITORIES.json").read_text())
    entry = registry["repositories"][0]
    entry.pop("work_root")
    entry["checkout_root"] = str(work.parent.parent)
    entry["path"] = "repo/component"
    (control / "REPOSITORIES.json").write_text(json.dumps(registry))
    assert load_repository_binding(control, work, "component").work_root == work


@pytest.mark.parametrize("mutation", ("work", "git", "prefix", "remote", "repo-manifest"))
def test_repository_binding_rejects_mismatch(tmp_path: Path, mutation: str):
    control, work, git_root = fixture(tmp_path)
    registry_path = control / "REPOSITORIES.json"
    registry = json.loads(registry_path.read_text())
    entry = registry["repositories"][0]
    if mutation == "work":
        other = git_root / "decoy"
        other.mkdir()
        work = other
    elif mutation == "git":
        other = tmp_path / "other"
        other.mkdir()
        git(other, "init", "-q")
        entry["git_root"] = str(other)
    elif mutation == "prefix":
        entry["git_prefix"] = "wrong"
    elif mutation == "remote":
        entry["remote_url"] = "ssh://example.test/wrong"
    else:
        (work / ".repo").mkdir()
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(RepositoryBindingError):
        load_repository_binding(control, work, "component")


@pytest.mark.parametrize("root_name", ("control", "work", "git"))
def test_repository_binding_rejects_symlink_roots(tmp_path: Path, root_name: str):
    control, work, git_root = fixture(tmp_path)
    target = {"control": control, "work": work, "git": git_root}[root_name]
    link = tmp_path / f"{root_name}-link"
    link.symlink_to(target, target_is_directory=True)
    if root_name == "control":
        control = link
    elif root_name == "work":
        work = link
    else:
        registry = json.loads((control / "REPOSITORIES.json").read_text())
        registry["repositories"][0]["git_root"] = str(link)
        (control / "REPOSITORIES.json").write_text(json.dumps(registry))
    with pytest.raises(RepositoryBindingError, match="symlink"):
        load_repository_binding(control, work, "component")
