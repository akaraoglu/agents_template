from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "gemma4:26b"
DEFAULT_OLLAMA_NUM_CTX = 262144


def _positive_int(value: Any, *, source: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} must be an integer, got {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{source} must be positive, got {parsed}")
    return parsed


def _ollama_model_name(model_id: str) -> str:
    return model_id.removeprefix("ollama/")


def _openclaw_config_path() -> Path:
    configured = os.environ.get("OPENCLAW_CONFIG_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "config" / "openclaw.json"


def load_ollama_runtime_config() -> tuple[str, int]:
    model_id = os.environ.get("OPENCLAW_OLLAMA_MODEL")
    num_ctx: int | None = None
    env_num_ctx = os.environ.get("OPENCLAW_OLLAMA_NUM_CTX")
    if env_num_ctx is not None:
        num_ctx = _positive_int(env_num_ctx, source="OPENCLAW_OLLAMA_NUM_CTX")

    config_path = _openclaw_config_path()
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        defaults = config.get("agents", {}).get("defaults", {})
        primary = defaults.get("model", {}).get("primary")
        configured_model = model_id or primary
        if configured_model:
            model_id = str(configured_model)
        if num_ctx is None and model_id:
            model_settings = defaults.get("models", {}).get(model_id, {})
            params = model_settings.get("params", {})
            configured_num_ctx = params.get("num_ctx")
            if configured_num_ctx is not None:
                num_ctx = _positive_int(configured_num_ctx, source=f"{config_path}:num_ctx")

    return _ollama_model_name(model_id or DEFAULT_OLLAMA_MODEL), num_ctx or DEFAULT_OLLAMA_NUM_CTX


def extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return None
