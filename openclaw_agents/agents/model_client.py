"""Model client adapters for prompt-driven runtime agents."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml


class ModelClientError(RuntimeError):
    """Raised when a model invocation cannot be completed."""


def _coerce_host(value: str | None) -> str:
    host = (value or "http://127.0.0.1:11434").strip()
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ModelClientError("model returned an empty response")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    candidate_starts = [index for index, char in enumerate(text) if char == "{"] or [-1]
    candidate_ends = [index for index, char in enumerate(text) if char == "}"]
    for start in candidate_starts:
        if start < 0:
            continue
        for end in reversed(candidate_ends):
            if end <= start:
                continue
            snippet = text[start : end + 1]
            try:
                parsed = json.loads(snippet)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and (
                {"reply", "tool_calls"} & set(parsed.keys()) or "action_intent" in parsed
            ):
                return parsed
    raise ModelClientError("model did not return a usable JSON object")


@dataclass(slots=True)
class ModelTarget:
    provider: str
    model: str
    options: dict[str, Any] = field(default_factory=dict)


ModelSpec = ModelTarget


class BaseModelClient:
    def generate_json(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        raise NotImplementedError


ModelClient = BaseModelClient


class ModelMapService:
    def __init__(self, path: str | Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[1]
        self.path = Path(path or (base_dir / "config" / "model_map.yaml"))
        self._raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}

    def get(self, agent_id: str) -> ModelTarget:
        default_raw = self._raw.get("default", {})
        agent_raw = (self._raw.get("agents") or {}).get(agent_id, default_raw)
        if isinstance(agent_raw, str):
            parts = [part for part in agent_raw.split("/") if part]
            provider = parts[-2] if len(parts) >= 2 else "ollama"
            model = parts[-1] if parts else agent_raw
            return ModelTarget(provider=provider, model=model)
        provider = str(agent_raw.get("provider", default_raw.get("provider", "ollama")))
        model = str(agent_raw.get("model", default_raw.get("model", "")))
        options = dict(default_raw.get("options", {}))
        options.update(agent_raw.get("options", {}))
        if not model:
            raise ValueError(f"model_map.yaml does not define a model for agent '{agent_id}'")
        return ModelTarget(provider=provider, model=model, options=options)


class OllamaModelClient(BaseModelClient):
    """Minimal Ollama chat client using the local HTTP API."""

    def __init__(self, host: str | None = None, timeout_seconds: float = 120.0) -> None:
        self.host = _coerce_host(host or os.environ.get("OLLAMA_HOST"))
        self.timeout_seconds = timeout_seconds

    def generate_json(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        payload = {
            "model": target.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if target.options:
            payload["options"] = target.options

        encoded = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self.host}/api/chat",
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:  # pragma: no cover - depends on live runtime
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelClientError(f"ollama HTTP {exc.code}: {detail}") from exc
        except (error.URLError, OSError) as exc:
            raise ModelClientError(f"unable to reach ollama at {self.host}: {exc}") from exc

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ModelClientError("ollama returned invalid JSON envelope") from exc

        content = str(((envelope.get("message") or {}).get("content")) or "")
        return _extract_json_object(content)

    def complete_json(self, *, spec: ModelSpec, messages: list[dict[str, str]]) -> dict[str, Any]:
        system_prompt = ""
        user_prompt = ""
        for message in messages:
            role = str(message.get("role") or "")
            if role == "system" and not system_prompt:
                system_prompt = str(message.get("content") or "")
            elif role == "user":
                user_prompt = str(message.get("content") or "")
        return self.generate_json(target=spec, system_prompt=system_prompt, user_prompt=user_prompt)
