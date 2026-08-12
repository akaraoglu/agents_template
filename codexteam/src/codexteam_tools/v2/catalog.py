from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, cast

from .canonical import canonical_sha256
from .models import (
    AgentSpec,
    BackendDefinition,
    Capability,
    DefinitionRef,
    GuidanceBundle,
    GuidanceModule,
    ModelProfile,
    PermissionPolicy,
    PipelineDefinition,
    ProjectPolicy,
    Responsibility,
    ReusableDefinition,
    project_path_pattern_matches,
    validate_wire,
)

DefinitionKey = tuple[str, str, str]

_CATEGORIES: Mapping[str, tuple[str, type[ReusableDefinition], str]] = {
    "responsibilities": ("responsibility", Responsibility, "responsibility_id"),
    "capabilities": ("capability", Capability, "capability_id"),
    "permission_policies": ("permission_policy", PermissionPolicy, "policy_id"),
    "project_policies": ("project_policy", ProjectPolicy, "project_policy_id"),
    "guidance_modules": ("guidance_module", GuidanceModule, "module_id"),
    "guidance_bundles": ("guidance_bundle", GuidanceBundle, "bundle_id"),
    "backends": ("backend_definition", BackendDefinition, "backend_id"),
    "model_profiles": ("model_profile", ModelProfile, "profile_id"),
    "agent_specs": ("agent_spec", AgentSpec, "agent_spec_id"),
    "pipelines": ("pipeline_definition", PipelineDefinition, "pipeline_id"),
}

_SUPPORTED_MODELS = {
    "codex": frozenset({"qwen3.6-27b"}),
    "opencode": frozenset({
        "ollama/muse-glimmer:30b",
        "ollama/qwen3.6-27b:latest",
    }),
}


@dataclass(frozen=True)
class CatalogFile:
    path: str
    digest: str


@dataclass(frozen=True)
class ResolvedAgentSpec:
    agent_spec: AgentSpec
    responsibility: Responsibility
    responsibility_permission_ceiling: PermissionPolicy
    capabilities: tuple[Capability, ...]
    permission_policy: PermissionPolicy
    guidance_bundle: GuidanceBundle
    guidance_modules: tuple[GuidanceModule, ...]
    model_profile: ModelProfile
    backend: BackendDefinition


@dataclass(frozen=True)
class Catalog:
    root: Path
    definitions: Mapping[DefinitionKey, ReusableDefinition]
    refs: Mapping[DefinitionKey, DefinitionRef]
    by_kind_versioned: Mapping[str, Mapping[str, Mapping[str, ReusableDefinition]]]
    # Convenience view of the lexically latest version; by_kind_versioned preserves all versions.
    by_kind: Mapping[str, Mapping[str, ReusableDefinition]]
    files: tuple[CatalogFile, ...]

    def get(self, kind: str, definition_id: str, definition_version: str | None = None) -> ReusableDefinition:
        try:
            versions = self.by_kind_versioned[kind][definition_id]
        except KeyError as exc:
            raise ValueError(f"missing {kind} definition {definition_id!r}") from exc
        if definition_version is None:
            if len(versions) != 1:
                raise ValueError(f"ambiguous {kind} definition {definition_id!r}; specify definition_version")
            return next(iter(versions.values()))
        try:
            return versions[definition_version]
        except KeyError as exc:
            raise ValueError(
                f"missing {kind} definition {definition_id!r} version {definition_version!r}"
            ) from exc

    def ref(self, kind: str, definition_id: str, definition_version: str | None = None) -> DefinitionRef:
        definition = self.get(kind, definition_id, definition_version)
        return self.refs[(kind, definition_id, definition.definition_version)]

    def ids(self, kind: str) -> tuple[str, ...]:
        return tuple(self.by_kind_versioned.get(kind, {}))

    def resolve_agent_spec(self, agent_spec_id: str, definition_version: str | None = None) -> ResolvedAgentSpec:
        return _resolve_agent_spec(self, agent_spec_id, definition_version)

    def catalog_lock(self) -> dict[str, Any]:
        definitions = [
            self.refs[key].model_dump(mode="json")
            for key in sorted(self.refs)
        ]
        files = [{"path": item.path, "digest": item.digest} for item in self.files]
        payload: dict[str, Any] = {
            "schema_version": "2.0",
            "definitions": definitions,
            "files": files,
        }
        payload["catalog_digest"] = canonical_sha256(payload)
        return payload


@dataclass(frozen=True)
class _Descriptor:
    key: DefinitionKey
    model_type: type[ReusableDefinition]
    identity_field: str
    path: Path
    data: Mapping[str, Any]


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _walk_files(directory: Path, suffix: str) -> tuple[Path, ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"catalog directory is missing or unsafe: {directory}")
    files: list[Path] = []
    with os.scandir(directory) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            path = Path(entry.path)
            if entry.is_symlink():
                raise ValueError(f"symlinks are forbidden in the catalog: {path}")
            if entry.is_dir(follow_symlinks=False):
                files.extend(_walk_files(path, suffix))
            elif entry.is_file(follow_symlinks=False):
                if path.suffix != suffix:
                    raise ValueError(f"unknown catalog file: {path}")
                files.append(path)
            else:
                raise ValueError(f"unsupported catalog entry: {path}")
    return tuple(files)


def _layout(root: Path) -> tuple[Path, Path, Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"catalog root is missing or unsafe: {root}")
    catalog = root / "catalog"
    guidance = root / "guidance"
    if catalog.is_dir():
        if catalog.is_symlink() or guidance.is_symlink():
            raise ValueError("catalog and guidance roots must not be symlinks")
        return root, catalog, guidance
    if root.name == "catalog":
        return root.parent, root, root.parent / "guidance"
    raise ValueError("catalog root must be a v2 root or its catalog directory")


def _descriptor_ref(value: Any, expected_kind: str, field_name: str) -> DefinitionKey:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a catalog reference descriptor")
    expected_fields = {"definition_id", "kind", "definition_version"}
    if set(value) != expected_fields:
        raise ValueError(f"{field_name} reference must contain only {sorted(expected_fields)}")
    if value["kind"] != expected_kind:
        raise ValueError(f"{field_name} must reference definition kind {expected_kind!r}")
    if not all(isinstance(value[name], str) and value[name] for name in expected_fields):
        raise ValueError(f"{field_name} reference fields must be nonempty strings")
    return value["kind"], value["definition_id"], value["definition_version"]


def _pattern_contains(container: str, candidate: str) -> bool:
    return project_path_pattern_matches(container, candidate, candidate_is_pattern=True)


def _policy_is_subset(policy: PermissionPolicy, ceiling: PermissionPolicy) -> bool:
    ceiling_allows = tuple(rule for rule in ceiling.rules if rule.effect == "allow")
    return all(
        any(
            upper.operation == rule.operation
            and upper.resource == rule.resource
            and (
                _pattern_contains(upper.resource_pattern, rule.resource_pattern)
                if rule.resource.value == "project_path"
                else upper.resource_pattern == rule.resource_pattern
            )
            for upper in ceiling_allows
        )
        for rule in policy.rules
        if rule.effect == "allow"
    )


def _policy_supports_capability(policy: PermissionPolicy, capability: Capability) -> bool:
    allows = tuple(rule for rule in policy.rules if rule.effect == "allow")
    for operation in capability.required_operations:
        if not any(rule.operation == operation for rule in allows):
            return False
    for resource in capability.required_resources:
        if not any(rule.resource == resource for rule in allows):
            return False
    return True


def _check_backend_model(profile: ModelProfile, backend: BackendDefinition) -> None:
    supported = _SUPPORTED_MODELS.get(backend.provider)
    if supported is None or profile.model not in supported:
        raise ValueError(
            f"unsupported backend/model pair: {backend.provider!r} with {profile.model!r}"
        )


def _lookup_ref(catalog: Catalog, reference: DefinitionRef, expected_kind: str, field_name: str) -> ReusableDefinition:
    if reference.kind != expected_kind:
        raise ValueError(f"{field_name} must reference definition kind {expected_kind!r}")
    key = (reference.kind, reference.definition_id, reference.definition_version)
    try:
        definition = catalog.definitions[key]
    except KeyError as exc:
        raise ValueError(f"missing reference for {field_name}: {key}") from exc
    if canonical_sha256(definition) != reference.digest:
        raise ValueError(f"digest/reference mismatch for {field_name}: {key}")
    return definition


def _resolve_agent_spec(
    catalog: Catalog, agent_spec_id: str, definition_version: str | None = None
) -> ResolvedAgentSpec:
    spec = catalog.get("agent_spec", agent_spec_id, definition_version)
    if not isinstance(spec, AgentSpec):
        raise ValueError(f"definition {agent_spec_id!r} is not an AgentSpec")
    responsibility = _lookup_ref(catalog, spec.responsibility, "responsibility", "responsibility")
    capabilities = tuple(
        _lookup_ref(catalog, reference, "capability", "capabilities") for reference in spec.capabilities
    )
    policy = _lookup_ref(catalog, spec.permission_policy, "permission_policy", "permission_policy")
    bundle = _lookup_ref(catalog, spec.guidance_bundle, "guidance_bundle", "guidance_bundle")
    profile = _lookup_ref(catalog, spec.model_profile, "model_profile", "model_profile")
    responsibility = cast(Responsibility, responsibility)
    capabilities = cast(tuple[Capability, ...], capabilities)
    policy = cast(PermissionPolicy, policy)
    bundle = cast(GuidanceBundle, bundle)
    profile = cast(ModelProfile, profile)
    ceiling = _lookup_ref(catalog, responsibility.permission_ceiling, "permission_policy", "permission_ceiling")
    modules = tuple(_lookup_ref(catalog, reference, "guidance_module", "modules") for reference in bundle.modules)
    backend = _lookup_ref(catalog, profile.backend, "backend_definition", "backend")
    ceiling = cast(PermissionPolicy, ceiling)
    modules = cast(tuple[GuidanceModule, ...], modules)
    backend = cast(BackendDefinition, backend)
    if not _policy_is_subset(policy, ceiling):
        raise ValueError(f"permission policy {policy.policy_id!r} broadens responsibility ceiling")
    _check_backend_model(profile, backend)
    allowed_operations = set(backend.supported_operations)
    allowed_resources = set(backend.supported_resources)
    for capability in capabilities:
        if not _policy_supports_capability(policy, capability) or not _policy_supports_capability(ceiling, capability):
            raise ValueError(
                f"policies do not satisfy capability {capability.capability_id!r} requirements"
            )
        missing_operations = set(capability.required_operations) - allowed_operations
        missing_resources = set(capability.required_resources) - allowed_resources
        if missing_operations or missing_resources:
            raise ValueError(
                f"backend {backend.backend_id!r} does not support capability {capability.capability_id!r} requirements"
            )
    return ResolvedAgentSpec(
        agent_spec=spec,
        responsibility=responsibility,
        responsibility_permission_ceiling=ceiling,
        capabilities=capabilities,
        permission_policy=policy,
        guidance_bundle=bundle,
        guidance_modules=modules,
        model_profile=profile,
        backend=backend,
    )


def load_catalog(root: str | Path) -> Catalog:
    asset_root, catalog_root, guidance_root = _layout(Path(root))
    expected_categories = set(_CATEGORIES)
    actual_entries: set[str] = set()
    with os.scandir(catalog_root) as entries:
        for entry in entries:
            if entry.is_symlink():
                raise ValueError(f"symlinks are forbidden in the catalog: {entry.path}")
            if not entry.is_dir(follow_symlinks=False):
                raise ValueError(f"unknown catalog entry: {entry.path}")
            actual_entries.add(entry.name)
    if actual_entries != expected_categories:
        missing = sorted(expected_categories - actual_entries)
        unknown = sorted(actual_entries - expected_categories)
        raise ValueError(f"catalog categories differ from the fixed layout; missing={missing}, unknown={unknown}")

    descriptors: dict[DefinitionKey, _Descriptor] = {}
    file_digests: dict[str, str] = {}
    for category, (expected_kind, model_type, identity_field) in _CATEGORIES.items():
        for path in _walk_files(catalog_root / category, ".toml"):
            relative = path.relative_to(asset_root).as_posix()
            content = path.read_bytes()
            file_digests[relative] = _sha256_bytes(content)
            try:
                data = tomllib.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                raise ValueError(f"invalid TOML catalog definition: {relative}") from exc
            if data.get("kind") != expected_kind:
                raise ValueError(f"wrong definition kind in {relative}: expected {expected_kind!r}")
            identity = data.get(identity_field)
            version = data.get("definition_version")
            if not isinstance(identity, str) or not identity or not isinstance(version, str) or not version:
                raise ValueError(f"missing definition identity in {relative}")
            key = expected_kind, identity, version
            if key in descriptors:
                raise ValueError(f"duplicate catalog identity {key}")
            descriptors[key] = _Descriptor(key, model_type, identity_field, path, MappingProxyType(data))

    guidance_files = _walk_files(guidance_root, ".md")
    guidance_by_path = {path.relative_to(asset_root).as_posix(): path for path in guidance_files}
    for relative, path in guidance_by_path.items():
        file_digests[relative] = _sha256_bytes(path.read_bytes())

    resolved: dict[DefinitionKey, ReusableDefinition] = {}
    active: list[DefinitionKey] = []

    def reference(value: Any, expected_kind: str, field_name: str) -> DefinitionRef:
        if isinstance(value, dict) and set(value) == {"definition_id", "kind", "definition_version"}:
            possible_key = value["kind"], value["definition_id"], value["definition_version"]
            if possible_key in active:
                cycle = " -> ".join(item[1] for item in (*active, possible_key))
                raise ValueError(f"catalog reference cycle: {cycle}")
        key = _descriptor_ref(value, expected_kind, field_name)
        if key not in descriptors:
            raise ValueError(f"missing reference for {field_name}: {key}")
        target = resolve(key)
        return DefinitionRef(
            definition_id=key[1],
            kind=key[0],
            definition_version=key[2],
            digest=canonical_sha256(target),
        )

    def resolve(key: DefinitionKey) -> ReusableDefinition:
        if key in resolved:
            return resolved[key]
        if key in active:
            cycle = " -> ".join(item[1] for item in (*active, key))
            raise ValueError(f"catalog reference cycle: {cycle}")
        active.append(key)
        descriptor = descriptors[key]
        data = dict(descriptor.data)
        kind = key[0]
        if kind == "responsibility":
            data["permission_ceiling"] = reference(data.get("permission_ceiling"), "permission_policy", "permission_ceiling")
        elif kind == "guidance_bundle":
            if "digest" in data:
                raise ValueError("guidance bundle digest is compiler-derived")
            modules = data.get("modules")
            if not isinstance(modules, list):
                raise ValueError("guidance bundle modules must be a TOML array")
            data["modules"] = [reference(item, "guidance_module", "modules") for item in modules]
            data["digest"] = canonical_sha256(data["modules"])
        elif kind == "model_profile":
            data["backend"] = reference(data.get("backend"), "backend_definition", "backend")
        elif kind == "agent_spec":
            capabilities = data.get("capabilities")
            if not isinstance(capabilities, list):
                raise ValueError("agent capabilities must be a TOML array")
            data["responsibility"] = reference(data.get("responsibility"), "responsibility", "responsibility")
            data["capabilities"] = [reference(item, "capability", "capabilities") for item in capabilities]
            data["permission_policy"] = reference(data.get("permission_policy"), "permission_policy", "permission_policy")
            data["guidance_bundle"] = reference(data.get("guidance_bundle"), "guidance_bundle", "guidance_bundle")
            data["model_profile"] = reference(data.get("model_profile"), "model_profile", "model_profile")
        elif kind == "pipeline_definition":
            stages = data.get("stages")
            if not isinstance(stages, list):
                raise ValueError("pipeline stages must be TOML array tables")
            data["stages"] = [
                {**stage, "agent_spec": reference(stage.get("agent_spec"), "agent_spec", "agent_spec")}
                if isinstance(stage, dict)
                else stage
                for stage in stages
            ]
        model = validate_wire(descriptor.model_type, data)
        model = cast(ReusableDefinition, model)
        resolved[key] = model
        active.pop()
        return model

    for descriptor_key in sorted(descriptors):
        resolve(descriptor_key)

    module_paths: set[str] = set()
    for definition in resolved.values():
        if not isinstance(definition, GuidanceModule):
            continue
        if not definition.path.startswith("guidance/") or definition.path not in guidance_by_path:
            raise ValueError(f"unsafe or missing guidance path: {definition.path!r}")
        module_paths.add(definition.path)
        content = guidance_by_path[definition.path].read_bytes()
        if len(content) >= 6 * 1024:
            raise ValueError(f"guidance module exceeds 6 KiB: {definition.path}")
        if _sha256_bytes(content) != definition.digest:
            raise ValueError(f"guidance content hash mismatch: {definition.path}")
    unknown_guidance = set(guidance_by_path) - module_paths
    if unknown_guidance:
        raise ValueError(f"unreferenced guidance files: {sorted(unknown_guidance)}")

    refs = {
        key: DefinitionRef(
            definition_id=key[1],
            kind=key[0],
            definition_version=key[2],
            digest=canonical_sha256(definition),
        )
        for key, definition in resolved.items()
    }
    mutable_versioned: dict[str, dict[str, dict[str, ReusableDefinition]]] = {}
    for (kind, definition_id, version), definition in resolved.items():
        mutable_versioned.setdefault(kind, {}).setdefault(definition_id, {})[version] = definition
    by_kind_versioned = MappingProxyType(
        {
            kind: MappingProxyType(
                {
                    definition_id: MappingProxyType(dict(sorted(versions.items())))
                    for definition_id, versions in sorted(items.items())
                }
            )
            for kind, items in sorted(mutable_versioned.items())
        }
    )
    by_kind = MappingProxyType(
        {
            kind: MappingProxyType(
                {
                    definition_id: versions[max(versions)]
                    for definition_id, versions in items.items()
                }
            )
            for kind, items in by_kind_versioned.items()
        }
    )
    catalog = Catalog(
        root=asset_root,
        definitions=MappingProxyType(dict(resolved)),
        refs=MappingProxyType(refs),
        by_kind_versioned=by_kind_versioned,
        by_kind=by_kind,
        files=tuple(CatalogFile(path, file_digests[path]) for path in sorted(file_digests)),
    )
    for versions in catalog.by_kind_versioned.get("model_profile", {}).values():
        for profile in versions.values():
            profile = cast(ModelProfile, profile)
            backend = _lookup_ref(catalog, profile.backend, "backend_definition", "backend")
            backend = cast(BackendDefinition, backend)
            _check_backend_model(profile, backend)
    for agent_spec_id, versions in catalog.by_kind_versioned.get("agent_spec", {}).items():
        for version in versions:
            catalog.resolve_agent_spec(agent_spec_id, version)
    return catalog


def resolve_agent_spec(
    catalog: Catalog, agent_spec_id: str, definition_version: str | None = None
) -> ResolvedAgentSpec:
    return catalog.resolve_agent_spec(agent_spec_id, definition_version)


def catalog_lock(catalog: Catalog) -> dict[str, Any]:
    return catalog.catalog_lock()


__all__ = [
    "Catalog",
    "CatalogFile",
    "ResolvedAgentSpec",
    "catalog_lock",
    "load_catalog",
    "resolve_agent_spec",
]
