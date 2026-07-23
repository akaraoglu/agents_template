from pathlib import Path

import pytest

from codexteam_tools.paths import (
    DEFAULT_PROJECTS_ROOT,
    PathValidationError,
    contained_path,
    normalize_task_id,
    safe_relative_path,
    slugify_project_name,
    validate_profile,
)


def test_default_projects_root_is_the_current_codexteam_workspace():
    assert DEFAULT_PROJECTS_ROOT == Path(
        "/home/alik/workspace/agent_template/codexteam/projects"
    )


def test_canonical_identifiers():
    assert normalize_task_id("t001") == "T001"
    assert validate_profile("qwen36-27b") == "qwen36-27b"
    assert slugify_project_name("My Useful Project") == "my-useful-project"


@pytest.mark.parametrize("value", ["../outside", "/absolute", "a/../../b", "a\\b", "./file"])
def test_relative_paths_reject_escape(value):
    with pytest.raises(PathValidationError):
        safe_relative_path(value)


def test_contained_path_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathValidationError):
        contained_path(root, "link/result.json")


@pytest.mark.parametrize("value", ["bad/name", "../bad", "", ".."])
def test_project_names_reject_path_input(value):
    with pytest.raises(PathValidationError):
        slugify_project_name(value)
