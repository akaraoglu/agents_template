from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = CODEXTEAM_ROOT / "execution_registry.toml"
BACKENDS = {"codex", "opencode"}
REASONING_REQUESTS = {"provider_default", "low", "medium", "high", "xhigh"}


class ExecutionRegistryError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ResolvedExecutionProfile:
    backend: dict[str, Any]
    model: dict[str, Any]
    profile: dict[str, Any]
    qualification: tuple[dict[str, Any], ...]
    requested_reasoning: str
    effective_reasoning: str | None
    reasoning_support_status: str
    runtime_options: dict[str, Any]
    registry_digest: str

    @property
    def backend_id(self) -> str:
        return self.backend["backend_id"]

    @property
    def profile_id(self) -> str:
        return self.profile["profile_id"]

    @property
    def canonical_profile(self) -> str:
        return f"{self.backend_id}/{self.profile_id}"

    @property
    def provider(self) -> str:
        return self.profile["provider"]

    @property
    def provider_locator(self) -> str:
        return self.profile["provider_locator"]

    def reference(
        self,
        *,
        runtime_version: str | None,
        backend_material_digest: str,
    ) -> dict[str, Any]:
        return {
            "registry_digest": self.registry_digest,
            "backend": {
                "id": self.backend_id,
                "definition_digest": _digest(self.backend),
                "runtime_version": runtime_version,
            },
            "model": {
                "id": self.model["model_id"],
                "definition_digest": _digest(self.model),
                "provider": self.provider,
                "provider_locator": self.provider_locator,
            },
            "profile": {
                "id": self.canonical_profile,
                "definition_digest": _digest(self.profile),
            },
            "reasoning": {
                "requested": self.requested_reasoning,
                "effective": self.effective_reasoning,
                "support_status": self.reasoning_support_status,
                "runtime_options": self.runtime_options,
            },
            "backend_material_digest": backend_material_digest,
            "verbosity_supported": self.profile["verbosity_support"],
            "qualification_references": list(self.profile["qualification_references"]),
        }


class ExecutionRegistry:
    def __init__(self, data: dict[str, Any], *, source_path: Path):
        self.source_path = source_path
        self.data = data
        self.backends = {item["backend_id"]: item for item in data["backends"]}
        self.models = {item["model_id"]: item for item in data["models"]}
        self.qualifications = {item["qualification_id"]: item for item in data["qualifications"]}
        self.profiles = {
            (item["backend_id"], item["profile_id"]): item
            for item in data["profiles"]
        }
        self.digest = _digest(data)
        self._validate()

    def _validate(self) -> None:
        if self.data.get("schema_version") != "1.0":
            raise ExecutionRegistryError("execution registry schema_version must be '1.0'")
        if set(self.backends) != BACKENDS:
            raise ExecutionRegistryError("execution registry must define only codex and opencode backends")
        for field, key in (
            ("backends", "backend_id"), ("models", "model_id"),
            ("qualifications", "qualification_id"),
        ):
            values = [item.get(key) for item in self.data.get(field, [])]
            if len(values) != len(set(values)):
                raise ExecutionRegistryError(f"execution registry has duplicate {key}")
        profile_keys = [
            (item.get("backend_id"), item.get("profile_id"))
            for item in self.data.get("profiles", [])
        ]
        if len(profile_keys) != len(set(profile_keys)):
            raise ExecutionRegistryError("execution registry has duplicate backend/profile")
        for (backend, profile_id), profile in self.profiles.items():
            if backend not in self.backends or profile["model_id"] not in self.models:
                raise ExecutionRegistryError(f"profile has unknown reference: {backend}/{profile_id}")
            supported = profile.get("supported_reasoning_requests")
            mappings = profile.get("reasoning_mappings")
            if not isinstance(supported, list) or not supported or set(supported) - REASONING_REQUESTS:
                raise ExecutionRegistryError(f"profile has invalid reasoning support: {backend}/{profile_id}")
            if not isinstance(mappings, dict) or set(mappings) != set(supported):
                raise ExecutionRegistryError(f"profile reasoning mappings do not match support: {backend}/{profile_id}")
            if any(
                not isinstance(value, str)
                or value not in (REASONING_REQUESTS | {"provider_default"})
                for value in mappings.values()
            ):
                raise ExecutionRegistryError(f"profile has invalid reasoning mapping: {backend}/{profile_id}")
            refs = profile.get("qualification_references")
            if (
                not isinstance(refs, list)
                or not refs
                or any(not isinstance(ref, str) or not ref for ref in refs)
                or len(set(refs)) != len(refs)
            ):
                raise ExecutionRegistryError(f"profile lacks qualification: {backend}/{profile_id}")
            for ref in refs:
                qualification = self.qualifications.get(ref)
                if qualification is None or qualification.get("status") != "qualified":
                    raise ExecutionRegistryError(f"profile qualification is not accepted: {backend}/{profile_id}")
                if qualification.get("profile") != f"{backend}/{profile_id}":
                    raise ExecutionRegistryError(f"qualification profile mismatch: {ref}")
                evidence_ref = qualification.get("evidence_ref")
                if not isinstance(evidence_ref, str) or not evidence_ref:
                    raise ExecutionRegistryError(f"qualification lacks evidence reference: {ref}")
                evidence_root = self.source_path.parent.resolve()
                evidence_path = (evidence_root / evidence_ref).resolve(strict=False)
                try:
                    evidence_path.relative_to(evidence_root)
                except ValueError as exc:
                    raise ExecutionRegistryError(
                        f"qualification evidence escapes registry root: {ref}"
                    ) from exc
                if evidence_path.is_symlink() or not evidence_path.is_file():
                    raise ExecutionRegistryError(f"qualification evidence is missing or unsafe: {ref}")

    def resolve(self, backend: str, profile: str, reasoning: str) -> ResolvedExecutionProfile:
        if backend not in BACKENDS:
            raise ExecutionRegistryError(f"unsupported backend: {backend}")
        definition = self.profiles.get((backend, profile))
        if definition is None:
            raise ExecutionRegistryError(f"unsupported execution profile: {backend}/{profile}")
        if reasoning not in definition["supported_reasoning_requests"]:
            raise ExecutionRegistryError(
                f"reasoning request {reasoning!r} is unsupported by {backend}/{profile}"
            )
        mapped = definition["reasoning_mappings"][reasoning]
        if mapped == "provider_default":
            effective = None
            status = "provider_default"
            options: dict[str, Any] = {}
        else:
            effective = mapped
            status = "applied"
            options = {"model_reasoning_effort": mapped}
        qualifications = tuple(
            self.qualifications[ref] for ref in definition["qualification_references"]
        )
        return ResolvedExecutionProfile(
            self.backends[backend], self.models[definition["model_id"]], definition,
            qualifications, reasoning, effective, status, options, self.digest,
        )

    def profiles_for_backend(self, backend: str) -> tuple[dict[str, Any], ...]:
        if backend not in self.backends:
            raise ExecutionRegistryError(f"unsupported backend: {backend}")
        return tuple(
            self.profiles[key] for key in sorted(self.profiles) if key[0] == backend
        )


def load_execution_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> ExecutionRegistry:
    source = Path(path).expanduser().resolve(strict=True)
    if source.is_symlink() or not source.is_file():
        raise ExecutionRegistryError(f"execution registry is missing or unsafe: {source}")
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ExecutionRegistryError(f"invalid execution registry TOML: {exc}") from exc
    return ExecutionRegistry(data, source_path=source)


def host_availability(
    registry: ExecutionRegistry,
    backend: str,
    profile: str,
    *,
    codex_home: Path | None = None,
) -> dict[str, Any]:
    resolved = registry.resolve(
        backend,
        profile,
        registry.profiles[(backend, profile)]["supported_reasoning_requests"][0],
    )
    executable = resolved.backend["executable"]
    if shutil.which(executable) is None:
        return {"host_available": False, "reason_unavailable": f"missing executable: {executable}"}
    if backend == "codex":
        home = codex_home or Path.home() / ".codex"
        source_profile = resolved.profile.get("source_profile")
        path = home / f"{source_profile}.config.toml"
        if not path.is_file():
            return {"host_available": False, "reason_unavailable": f"missing curated profile material: {path}"}
        return {"host_available": True, "reason_unavailable": None}
    model_id = resolved.provider_locator.removeprefix("ollama/")
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"host_available": False, "reason_unavailable": f"Ollama unavailable: {exc}"}
    names = {item.get("name") for item in payload.get("models", []) if isinstance(item, dict)}
    if model_id not in names:
        return {"host_available": False, "reason_unavailable": f"curated model not installed: {model_id}"}
    return {"host_available": True, "reason_unavailable": None}
