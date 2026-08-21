from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from codexteam_tools.execution_catalog_cli import main
from codexteam_tools.execution_registry import (
    ExecutionRegistry,
    ExecutionRegistryError,
    load_execution_registry,
)


def test_registry_contains_only_curated_backends_and_profiles():
    registry = load_execution_registry()
    assert set(registry.backends) == {"codex", "opencode"}
    assert set(registry.profiles) == {
        ("codex", "qwen36-27b"),
        ("codex", "qwen38-27b"),
        ("codex", "muse-glimmer"),
        ("codex", "gemma4-26b"),
        ("codex", "gpt54-mini"),
        ("opencode", "qwen36-27b"),
        ("opencode", "qwen38-27b"),
        ("opencode", "qwen38-27b-context"),
        ("opencode", "muse-glimmer"),
        ("opencode", "ornith35b"),
    }


def test_profile_identity_is_backend_scoped():
    registry = load_execution_registry()
    codex = registry.resolve("codex", "qwen36-27b", "medium")
    opencode = registry.resolve("opencode", "qwen36-27b", "provider_default")
    assert codex.canonical_profile == "codex/qwen36-27b"
    assert opencode.canonical_profile == "opencode/qwen36-27b"
    assert codex.provider_locator != opencode.provider_locator


def test_default_muse_profile_uses_tuned_in_place_tag():
    profile = load_execution_registry().resolve(
        "opencode", "muse-glimmer", "provider_default"
    )
    assert profile.provider_locator == "ollama/muse-glimmer:30b"
    assert profile.model["context_limit"] == 131072
    assert profile.canonical_profile == "opencode/muse-glimmer"


def test_opencode_qwen38_profile_uses_tuned_large_context_alias():
    profile = load_execution_registry().resolve(
        "opencode", "qwen38-27b-context", "medium"
    )
    assert profile.provider_locator == "ollama/qwen3.8-27b:latest"
    assert profile.model["context_limit"] == 262144
    assert profile.model["output_limit"] == 32768
    assert profile.canonical_profile == "opencode/qwen38-27b-context"
    assert profile.effective_reasoning == "medium"
    assert profile.reasoning_support_status == "applied"


@pytest.mark.parametrize(
    ("profile_id", "locator", "context"),
    [
        ("qwen38-27b", "qwen3.8-27b", 262144),
        ("muse-glimmer", "muse-glimmer:30b", 131072),
        ("gemma4-26b", "gemma4-26b", 32768),
    ],
)
def test_new_codex_local_profiles_are_curated(profile_id, locator, context):
    profile = load_execution_registry().resolve("codex", profile_id, "medium")
    assert profile.provider == "ollama_local"
    assert profile.provider_locator == locator
    assert profile.model["context_limit"] == context
    assert profile.canonical_profile == f"codex/{profile_id}"


def test_ornith_runtime_context_matches_tuned_alias():
    profile = load_execution_registry().resolve(
        "opencode", "ornith35b", "provider_default"
    )
    assert profile.model["context_limit"] == 262144


def test_unknown_profile_and_unsupported_reasoning_fail():
    registry = load_execution_registry()
    with pytest.raises(ExecutionRegistryError, match="unsupported execution profile"):
        registry.resolve("codex", "installed-but-unknown", "medium")
    with pytest.raises(ExecutionRegistryError, match="unsupported by"):
        registry.resolve("opencode", "qwen36-27b", "high")
    with pytest.raises(ExecutionRegistryError, match="unsupported by"):
        registry.resolve("opencode", "qwen38-27b-context", "provider_default")


def test_query_cli_preserves_disabled_opencode_profiles_without_resolving_them(
    tmp_path: Path, capsys
):
    before = Path("execution_registry.toml").read_bytes()
    assert main([
        "profiles", "--backend", "opencode", "--json",
    ]) == 0
    profiles = json.loads(capsys.readouterr().out)
    assert profiles
    assert all(profile["execution_enabled"] is False for profile in profiles)
    assert all(profile["supported"] is False for profile in profiles)
    assert all(profile["host_available"] is False for profile in profiles)
    assert main([
        "resolve", "--backend", "opencode", "--profile", "qwen36-27b",
        "--role", "developer", "--reasoning", "provider_default", "--json",
    ]) == 2
    assert "opencode execution is disabled" in capsys.readouterr().out
    assert Path("execution_registry.toml").read_bytes() == before


def test_registry_rejects_duplicate_ids_and_escaping_evidence(tmp_path: Path):
    source = Path("execution_registry.toml")
    data = tomllib.loads(source.read_text())
    duplicate = {**data, "backends": [*data["backends"], data["backends"][0]]}
    with pytest.raises(ExecutionRegistryError, match="duplicate backend_id"):
        ExecutionRegistry(duplicate, source_path=source.resolve())

    escaping = {**data, "qualifications": [dict(item) for item in data["qualifications"]]}
    escaping["qualifications"][0]["evidence_ref"] = "../AGENTS.md"
    with pytest.raises(ExecutionRegistryError, match="escapes registry root"):
        ExecutionRegistry(escaping, source_path=source.resolve())

    invalid_reasoning = {**data, "profiles": [dict(item) for item in data["profiles"]]}
    invalid_reasoning["profiles"][0]["reasoning_mappings"] = {"medium": "nonsense"}
    invalid_reasoning["profiles"][0]["supported_reasoning_requests"] = ["medium"]
    with pytest.raises(ExecutionRegistryError, match="invalid reasoning mapping"):
        ExecutionRegistry(invalid_reasoning, source_path=source.resolve())


def test_query_cli_rejects_unknown_role(capsys):
    assert main([
        "resolve", "--backend", "codex", "--profile", "qwen36-27b",
        "--role", "unknown", "--reasoning", "medium", "--json",
    ]) == 2
    assert "unsupported agent role" in capsys.readouterr().out
