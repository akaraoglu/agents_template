from pathlib import Path

import pytest

from codexteam_tools.project_guidance import sync_project_guidance
from codexteam_tools.project_init import initialize_project
from codexteam_tools.roles import RolePolicyError


def test_project_guidance_sync_is_current_after_initialization(tmp_path: Path):
    plan = initialize_project("Example", "Goal", root=tmp_path, project_id="example")
    assert sync_project_guidance(plan.project_dir) == ()


def test_project_guidance_sync_previews_and_refreshes_managed_file(tmp_path: Path):
    plan = initialize_project("Example", "Goal", root=tmp_path, project_id="example")
    target = plan.project_dir / ".codexteam" / "roles" / "tester.toml"
    target.write_text(target.read_text() + "# stale\n")

    changes = sync_project_guidance(plan.project_dir)
    assert changes == ("update .codexteam/roles/tester.toml",)
    assert target.read_text().endswith("# stale\n")

    sync_project_guidance(plan.project_dir, apply=True)
    assert not target.read_text().endswith("# stale\n")


def test_project_guidance_sync_refuses_unmanaged_collision(tmp_path: Path):
    plan = initialize_project("Example", "Goal", root=tmp_path, project_id="example")
    target = plan.project_dir / ".codexteam" / "roles" / "reviewer.toml"
    target.write_text('role = "personal"\n')
    with pytest.raises(RolePolicyError, match="unmanaged"):
        sync_project_guidance(plan.project_dir, apply=True)
