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
        ("codex", "gpt54-mini"),
        ("opencode", "qwen36-27b"),
        ("opencode", "ornith35b"),
    }


def test_profile_identity_is_backend_scoped():
    registry = load_execution_registry()
    codex = registry.resolve("codex", "qwen36-27b", "medium")
    opencode = registry.resolve("opencode", "qwen36-27b", "provider_default")
    assert codex.canonical_profile == "codex/qwen36-27b"
    assert opencode.canonical_profile == "opencode/qwen36-27b"
    assert codex.provider_locator != opencode.provider_locator


def test_unknown_profile_and_unsupported_reasoning_fail():
    registry = load_execution_registry()
    with pytest.raises(ExecutionRegistryError, match="unsupported execution profile"):
        registry.resolve("codex", "installed-but-unknown", "medium")
    with pytest.raises(ExecutionRegistryError, match="unsupported by"):
        registry.resolve("opencode", "qwen36-27b", "high")


def test_query_cli_is_read_only_and_reports_support(tmp_path: Path, capsys):
    before = Path("execution_registry.toml").read_bytes()
    assert main([
        "resolve", "--backend", "opencode", "--profile", "qwen36-27b",
        "--role", "developer", "--reasoning", "provider_default", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"]["id"] == "opencode/qwen36-27b"
    assert payload["reasoning"]["support_status"] == "provider_default"
    assert payload["supported"] is True
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
