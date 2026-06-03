from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "AgenticTeam" / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from agent_runner import load_ollama_runtime_config


class AgentRunnerConfigTests(unittest.TestCase):
    def test_load_ollama_runtime_config_uses_openclaw_primary_model_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "openclaw.json"
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

            with mock.patch.dict(
                os.environ,
                {"OPENCLAW_CONFIG_PATH": str(config_path)},
                clear=True,
            ):
                self.assertEqual(load_ollama_runtime_config(), ("gemma4:26b", 262144))

    def test_load_ollama_runtime_config_allows_explicit_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "openclaw.json"
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

            with mock.patch.dict(
                os.environ,
                {
                    "OPENCLAW_CONFIG_PATH": str(config_path),
                    "OPENCLAW_OLLAMA_MODEL": "ollama/qwen3.5:35b",
                    "OPENCLAW_OLLAMA_NUM_CTX": "131072",
                },
                clear=True,
            ):
                self.assertEqual(load_ollama_runtime_config(), ("qwen3.5:35b", 131072))

    def test_load_ollama_runtime_config_rejects_invalid_context_window(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "OPENCLAW_CONFIG_PATH": "/path/that/does/not/exist.json",
                "OPENCLAW_OLLAMA_NUM_CTX": "0",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                load_ollama_runtime_config()


if __name__ == "__main__":
    unittest.main()
