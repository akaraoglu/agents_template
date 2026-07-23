import tomllib
from pathlib import Path

import pytest

from codexteam_tools.native_agents import (
    GENERATED_MARKER,
    expected_native_agents,
    sync_native_agents,
)
from codexteam_tools.roles import RolePolicyError


def test_native_agent_projection_is_valid_and_namespaced():
    generated = expected_native_agents()
    assert len(generated) == 8
    for name, content in generated.items():
        assert name.startswith("codexteam_")
        assert content.startswith(GENERATED_MARKER)
        parsed = tomllib.loads(content)
        assert parsed["name"] == name.removesuffix(".toml")
        assert parsed["developer_instructions"]
        assert parsed["model_reasoning_effort"] in {"low", "medium", "high"}


def test_native_agent_sync_previews_applies_and_becomes_current(tmp_path: Path):
    changes = sync_native_agents(tmp_path)
    assert len(changes) == 8
    assert list(tmp_path.iterdir()) == []

    assert len(sync_native_agents(tmp_path, apply=True)) == 8
    assert sync_native_agents(tmp_path) == ()


def test_native_agent_sync_refuses_unmanaged_overwrite(tmp_path: Path):
    target = tmp_path / "codexteam_developer.toml"
    target.write_text('name = "personal_agent"\n')
    with pytest.raises(RolePolicyError, match="unmanaged"):
        sync_native_agents(tmp_path, apply=True)
