from __future__ import annotations

import json

import pytest

from AgenticTeam.scripts.v4_model import load_ollama_runtime_config


def test_load_ollama_runtime_config_uses_openclaw_primary_model_params(tmp_path, monkeypatch):
    config_path = tmp_path / "openclaw.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "model": {"primary": "ollama/gemma4:26b"},
                        "models": {
                            "ollama/gemma4:26b": {
                                "params": {"num_ctx": 262144}
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("OPENCLAW_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OPENCLAW_OLLAMA_NUM_CTX", raising=False)

    assert load_ollama_runtime_config() == ("gemma4:26b", 262144)


def test_load_ollama_runtime_config_allows_explicit_env_override(tmp_path, monkeypatch):
    config_path = tmp_path / "openclaw.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "model": {"primary": "ollama/gemma4:26b"},
                        "models": {
                            "ollama/gemma4:26b": {
                                "params": {"num_ctx": 262144}
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("OPENCLAW_OLLAMA_MODEL", "ollama/qwen3.5:35b")
    monkeypatch.setenv("OPENCLAW_OLLAMA_NUM_CTX", "131072")

    assert load_ollama_runtime_config() == ("qwen3.5:35b", 131072)


def test_load_ollama_runtime_config_rejects_invalid_context_window(monkeypatch):
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", "/path/that/does/not/exist.json")
    monkeypatch.delenv("OPENCLAW_OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("OPENCLAW_OLLAMA_NUM_CTX", "0")

    with pytest.raises(ValueError):
        load_ollama_runtime_config()
