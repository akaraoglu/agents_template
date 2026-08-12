from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from codexteam_tools.v2 import (
    AcceptanceCriterion,
    ActorRef,
    Assignment,
    EvidenceType,
    EffectivePermissionRequest,
    PermissionResource,
    PipelineRevision,
    RecordRef,
    RoleInstance,
    WorkItem,
    build_role_instance,
    canonical_sha256,
    compile_pipeline,
    evaluate_effective_permission,
    load_catalog,
)

ROOT = Path(__file__).parents[2]
CATALOG_ROOT = ROOT / "v2"
NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)
AGENT_SPEC_IDS = {
    "ct2.analysis.discovery",
    "ct2.design.architecture",
    "ct2.design.ux",
    "ct2.implementation.developer",
    "ct2.verification.test-engineer",
    "ct2.assurance.auditor",
    "ct2.review.acceptance",
}


def copied_catalog(tmp_path: Path) -> Path:
    target = tmp_path / "v2"
    shutil.copytree(CATALOG_ROOT, target)
    return target


def replace(path: Path, old: str, new: str) -> None:
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def work_item() -> WorkItem:
    return WorkItem(
        schema_version="2.0",
        kind="work_item",
        work_item_id="canary-1",
        title="Canary",
        objective="Exercise the v2 compiler",
        acceptance_criteria=(
            AcceptanceCriterion(
                id="criterion-1",
                statement="The deterministic canary passes",
                required_evidence_types=(EvidenceType.TEST_OUTPUT,),
            ),
        ),
        approved_scope=(
            "project/src/**",
            "project/tests/**",
            "project/docs/**",
            "project/management/**",
        ),
    )


def lead() -> ActorRef:
    return ActorRef(actor_id="lead-1", kind="project_lead")


def revision(compiled, revision_id: str = "revision-1") -> PipelineRevision:
    return PipelineRevision(
        schema_version="2.0",
        kind="pipeline_revision",
        revision_id=revision_id,
        plan=compiled.refs.plan,
        revision_number=1,
        stages=compiled.plan.stages,
        frozen_stage_ids=(),
        frozen_stage_digests=(),
        parent_stage_digests=(),
        applies_from_stage=compiled.plan.stages[0].stage_id,
        reason="Initial canary revision",
        approving_decision=RecordRef(record_id="decision-1", kind="lead_decision", digest="a" * 64),
        created_at=NOW,
    )


def test_real_toml_catalog_loads_and_resolves_all_agent_specs() -> None:
    catalog = load_catalog(CATALOG_ROOT)
    assert set(catalog.by_kind["agent_spec"]) == AGENT_SPEC_IDS
    assert len(catalog.by_kind["responsibility"]) == 7
    assert len(catalog.by_kind["capability"]) == 7
    for agent_spec_id in sorted(AGENT_SPEC_IDS):
        resolved = catalog.resolve_agent_spec(agent_spec_id)
        assert resolved.agent_spec.agent_spec_id == agent_spec_id
        assert resolved.backend.provider == "opencode"
        assert resolved.guidance_modules
        assert resolved.model_profile.backend == catalog.ref("backend_definition", resolved.backend.backend_id)
        assert resolved.model_profile.profile_id == "muse-glimmer-opencode"
        assert resolved.model_profile.model == "ollama/muse-glimmer:30b"
        assert resolved.responsibility.permission_ceiling == catalog.ref(
            "permission_policy", resolved.responsibility_permission_ceiling.policy_id
        )
    assert catalog.get("backend_definition", "opencode").limitations == ("no_os_sandbox", "no_mcp")
    assert all(
        catalog.resolve_agent_spec(agent_spec_id).backend.backend_id == "opencode"
        for agent_spec_id in AGENT_SPEC_IDS
    )
    assert not any(
        catalog.resolve_agent_spec(agent_spec_id).backend.backend_id == "codex"
        for agent_spec_id in AGENT_SPEC_IDS
    )
    assert {catalog.get("model_profile", profile_id).model for profile_id in catalog.ids("model_profile")} == {
        "ollama/muse-glimmer:30b",
        "ollama/qwen3.6-27b:latest",
        "qwen3.6-27b",
    }
    assert not any(
        "qwen" in catalog.resolve_agent_spec(agent_spec_id).model_profile.profile_id
        for agent_spec_id in AGENT_SPEC_IDS
    )


def test_definition_digests_and_lock_are_deterministic_and_caller_digests_are_absent() -> None:
    first = load_catalog(CATALOG_ROOT)
    second = load_catalog(CATALOG_ROOT)
    assert first.catalog_lock() == second.catalog_lock()
    assert [item["definition_id"] for item in first.catalog_lock()["definitions"]] == [
        item["definition_id"] for item in second.catalog_lock()["definitions"]
    ]
    for key, definition in first.definitions.items():
        assert first.refs[key].digest == canonical_sha256(definition)
    assert "digest" not in (CATALOG_ROOT / "catalog/agent_specs/developer.toml").read_text()
    assert "digest" not in (CATALOG_ROOT / "catalog/guidance_bundles/implementation.toml").read_text()


@pytest.mark.parametrize(
    ("relative", "old", "new", "message"),
    (
        (
            "catalog/agent_specs/developer.toml",
            'definition_id = "implementer"',
            'definition_id = "missing"',
            "missing reference",
        ),
        (
            "catalog/agent_specs/developer.toml",
            'kind = "responsibility", definition_version',
            'kind = "capability", definition_version',
            "must reference definition kind",
        ),
        (
            "catalog/agent_specs/developer.toml",
            'agent_spec_id = "ct2.implementation.developer"',
            'agent_spec_id = "ct2.analysis.discovery"',
            "duplicate catalog identity",
        ),
        (
            "catalog/agent_specs/developer.toml",
            'model_profile = { definition_id = "muse-glimmer-opencode"',
            'model_profile = { definition_id = "muse-glimmer-opencode", digest = "' + "a" * 64 + '"',
            "reference must contain only",
        ),
    ),
)
def test_catalog_rejects_missing_wrong_duplicate_and_digest_assertion_refs(
    tmp_path: Path, relative: str, old: str, new: str, message: str
) -> None:
    root = copied_catalog(tmp_path)
    replace(root / relative, old, new)
    with pytest.raises(ValueError, match=message):
        load_catalog(root)


def test_catalog_rejects_unknown_files_fields_and_cycles(tmp_path: Path) -> None:
    root = copied_catalog(tmp_path)
    (root / "catalog/capabilities/unknown.txt").write_text("unknown", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown catalog file"):
        load_catalog(root)
    root = copied_catalog(tmp_path / "field")
    with (root / "catalog/capabilities/repository_discovery.toml").open("a", encoding="utf-8") as stream:
        stream.write('\nunknown = "field"\n')
    with pytest.raises(ValidationError, match="Extra inputs"):
        load_catalog(root)
    root = copied_catalog(tmp_path / "cycle")
    replace(
        root / "catalog/responsibilities/analyst.toml",
        'permission_ceiling = { definition_id = "repository_readonly", kind = "permission_policy"',
        'permission_ceiling = { definition_id = "analyst", kind = "responsibility"',
    )
    with pytest.raises(ValueError, match="catalog reference cycle"):
        load_catalog(root)


def test_catalog_refuses_symlinks_and_guidance_escape(tmp_path: Path) -> None:
    root = copied_catalog(tmp_path)
    (root / "catalog/capabilities/link.toml").symlink_to(root / "catalog/capabilities/implementation.toml")
    with pytest.raises(ValueError, match="symlinks are forbidden"):
        load_catalog(root)
    root = copied_catalog(tmp_path / "escape")
    replace(root / "catalog/guidance_modules/discovery.toml", 'path = "guidance/discovery.md"', 'path = "../outside.md"')
    with pytest.raises((ValueError, ValidationError)):
        load_catalog(root)

    root = copied_catalog(tmp_path / "root-link")
    moved = root / "catalog-real"
    (root / "catalog").rename(moved)
    (root / "catalog").symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be symlinks"):
        load_catalog(root)


def test_guidance_tampering_and_unlisted_guidance_are_rejected(tmp_path: Path) -> None:
    root = copied_catalog(tmp_path)
    with (root / "guidance/discovery.md").open("a", encoding="utf-8") as stream:
        stream.write("tampered\n")
    with pytest.raises(ValueError, match="guidance content hash mismatch"):
        load_catalog(root)
    root = copied_catalog(tmp_path / "extra")
    (root / "guidance/extra.md").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="unreferenced guidance"):
        load_catalog(root)


def test_permission_broadening_and_unsupported_backend_requirements_fail(tmp_path: Path) -> None:
    root = copied_catalog(tmp_path)
    replace(
        root / "catalog/agent_specs/developer.toml",
        'definition_id = "developer_writer", kind = "permission_policy"',
        'definition_id = "project_lead", kind = "permission_policy"',
    )
    with pytest.raises(ValueError, match="broadens responsibility ceiling"):
        load_catalog(root)
    root = copied_catalog(tmp_path / "backend")
    replace(root / "catalog/backends/opencode.toml", ', "process"]', "]")
    with pytest.raises(ValueError, match="does not support capability"):
        load_catalog(root)


def test_unsupported_backend_model_pair_fails(tmp_path: Path) -> None:
    root = copied_catalog(tmp_path)
    replace(root / "catalog/model_profiles/muse-glimmer-opencode.toml", 'model = "ollama/muse-glimmer:30b"', 'model = "other/model"')
    with pytest.raises(ValueError, match="unsupported backend/model pair"):
        load_catalog(root)


@pytest.mark.parametrize(
    ("optional", "expected"),
    (
        ((), ("discovery", "implementation", "verification", "assurance", "review")),
        (("architecture",), ("discovery", "architecture", "implementation", "verification", "assurance", "review")),
        (("ux",), ("discovery", "ux", "implementation", "verification", "assurance", "review")),
        (("architecture", "ux"), ("discovery", "architecture", "ux", "implementation", "verification", "assurance", "review")),
    ),
)
def test_compile_pipeline_all_variants_have_exact_serial_order_and_dependencies(
    optional: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    compiled = compile_pipeline(load_catalog(CATALOG_ROOT), work_item(), optional, lead(), NOW)
    assert tuple(stage.stage_id for stage in compiled.plan.stages) == expected
    assert tuple(stage.dependencies for stage in compiled.plan.stages) == (
        (),
        *((expected[index - 1],) for index in range(1, len(expected))),
    )
    assert compiled.selection_trace == (
        f"architecture:{'selected' if 'architecture' in optional else 'omitted'}",
        f"ux:{'selected' if 'ux' in optional else 'omitted'}",
    )
    assurance = next(stage for stage in compiled.plan.stages if stage.stage == "assurance")
    assert assurance.assurance_domain.value == "security_privacy"


def test_compile_pipeline_ids_and_digests_are_deterministic() -> None:
    catalog = load_catalog(CATALOG_ROOT)
    first = compile_pipeline(catalog, work_item(), ("architecture", "ux"), lead(), NOW)
    second = compile_pipeline(catalog, work_item(), ("ux", "architecture"), lead(), NOW)
    assert first.plan == second.plan
    assert first.refs == second.refs


def test_plan_identity_excludes_approval_timestamp() -> None:
    catalog = load_catalog(CATALOG_ROOT)
    first = compile_pipeline(catalog, work_item(), (), lead(), NOW)
    later = compile_pipeline(catalog, work_item(), (), lead(), NOW.replace(hour=1))
    assert first.plan.plan_id == later.plan.plan_id
    assert canonical_sha256(first.plan) != canonical_sha256(later.plan)


def test_build_role_instance_enforces_scope_and_detects_tampering() -> None:
    catalog = load_catalog(CATALOG_ROOT)
    item = work_item()
    compiled = compile_pipeline(catalog, item, (), lead(), NOW)
    stage = next(stage for stage in compiled.plan.stages if stage.stage == "implementation")
    assignment = Assignment(
        schema_version="2.0",
        kind="assignment",
        assignment_id="assignment-1",
        work_item=compiled.refs.work_item,
        stage="implementation",
        agent_spec=stage.agent_spec,
        scope=("project/src/**", "project/tests/**"),
    )
    pipeline_revision = revision(compiled)
    role = build_role_instance(
        catalog,
        assignment=assignment,
        work_item=item,
        pipeline_revision=pipeline_revision,
        stage_spec=stage,
        attempt_id="attempt-1",
    )
    assert role.role_instance_id.startswith("role-")
    with pytest.raises(ValidationError, match="effective_policy_digest"):
        RoleInstance.model_validate({**role.model_dump(mode="python"), "attempt_id": "tampered"})
    broad = assignment.model_copy(update={"scope": ("project",)})
    with pytest.raises(ValueError, match="approved scope"):
        build_role_instance(
            catalog,
            assignment=broad,
            work_item=item,
            pipeline_revision=pipeline_revision,
            stage_spec=stage,
            attempt_id="attempt-1",
        )
    item_with_docs = item.model_copy(update={"approved_scope": (*item.approved_scope, "project/docs/design")})
    architecture = compile_pipeline(catalog, item_with_docs, ("architecture",), lead(), NOW)
    architecture_stage = architecture.plan.stages[1]
    architecture_assignment = Assignment(
        schema_version="2.0",
        kind="assignment",
        assignment_id="assignment-architecture",
        work_item=architecture.refs.work_item,
        stage="architecture",
        agent_spec=architecture_stage.agent_spec,
        scope=("project/docs/design/**",),
    )
    build_role_instance(
        catalog,
        assignment=architecture_assignment,
        work_item=item_with_docs,
        pipeline_revision=revision(architecture),
        stage_spec=architecture_stage,
        attempt_id="attempt-1",
    )


def test_all_canary_role_instances_build_and_revision_and_domain_are_bound() -> None:
    catalog = load_catalog(CATALOG_ROOT)
    item = work_item().model_copy(update={"approved_scope": ("project/**",)})
    for optional in ((), ("architecture", "ux")):
        compiled = compile_pipeline(catalog, item, optional, lead(), NOW)
        pipeline_revision = revision(compiled, f"revision-{'all' if optional else 'required'}")
        for stage_spec in compiled.plan.stages:
            assignment = Assignment(
                schema_version="2.0",
                kind="assignment",
                assignment_id=f"assignment-{stage_spec.stage_id}-{'all' if optional else 'required'}",
                work_item=compiled.refs.work_item,
                stage=stage_spec.stage,
                agent_spec=stage_spec.agent_spec,
                scope=("project/**",),
                assurance_domain=stage_spec.assurance_domain,
            )
            role = build_role_instance(
                catalog,
                assignment=assignment,
                work_item=item,
                pipeline_revision=pipeline_revision,
                stage_spec=stage_spec,
                attempt_id="attempt-1",
            )
            assert role.stage_id == stage_spec.stage_id
            resolved = catalog.resolve_agent_spec(
                stage_spec.agent_spec.definition_id, stage_spec.agent_spec.definition_version
            )
            project_policy = catalog.get("project_policy", "canary-project")
            required_operations = {
                operation for capability in resolved.capabilities for operation in capability.required_operations
            }
            required_resources = {
                resource for capability in resolved.capabilities for resource in capability.required_resources
            }
            for rule in resolved.permission_policy.rules:
                if (
                    rule.effect != "allow"
                    or rule.operation not in required_operations
                    or rule.resource not in required_resources
                ):
                    continue
                request = EffectivePermissionRequest(
                    operation=rule.operation,
                    resource=rule.resource,
                    **(
                        {"project_path": rule.resource_pattern.removesuffix("/**") + "/canary.txt"}
                        if rule.resource == PermissionResource.PROJECT_PATH
                        else {"resource_name": rule.resource_pattern}
                    ),
                )
                assert evaluate_effective_permission(
                    (resolved.responsibility_permission_ceiling, project_policy, resolved.permission_policy),
                    request,
                    assignment.scope,
                    resolved.backend.supported_operations,
                    resolved.backend.supported_resources,
                )

    compiled = compile_pipeline(catalog, item, (), lead(), NOW)
    pipeline_revision = revision(compiled)
    stage_spec = next(stage for stage in compiled.plan.stages if stage.stage == "assurance")
    assignment = Assignment(
        schema_version="2.0",
        kind="assignment",
        assignment_id="assignment-assurance",
        work_item=compiled.refs.work_item,
        stage="assurance",
        agent_spec=stage_spec.agent_spec,
        scope=("project/**",),
        assurance_domain=stage_spec.assurance_domain,
    )
    unrelated_compiled = compile_pipeline(catalog, item, ("architecture",), lead(), NOW)
    unrelated = revision(unrelated_compiled, "revision-unrelated")
    unrelated_stage = next(stage for stage in unrelated.stages if stage.stage == "assurance")
    unrelated = unrelated.model_copy(
        update={
            "stages": tuple(
                stage.model_copy(update={"agent_spec": catalog.ref("agent_spec", "ct2.review.acceptance")})
                if stage.stage == "assurance"
                else stage
                for stage in unrelated.stages
            )
        }
    )
    assert unrelated_stage != next(stage for stage in unrelated.stages if stage.stage == "assurance")
    with pytest.raises(ValueError, match="byte-identical"):
        build_role_instance(
            catalog,
            assignment=assignment,
            work_item=item,
            pipeline_revision=unrelated,
            stage_spec=stage_spec,
            attempt_id="attempt-1",
        )
    mismatched = assignment.model_copy(update={"assurance_domain": "accessibility"})
    with pytest.raises(ValueError, match="assurance_domain"):
        build_role_instance(
            catalog,
            assignment=mismatched,
            work_item=item,
            pipeline_revision=pipeline_revision,
            stage_spec=stage_spec,
            attempt_id="attempt-1",
        )


def test_catalog_versions_coexist_and_omitted_version_is_ambiguous(tmp_path: Path) -> None:
    root = copied_catalog(tmp_path)
    source = root / "catalog/capabilities/repository_discovery.toml"
    second = root / "catalog/capabilities/repository_discovery-v2.toml"
    second.write_text(source.read_text(encoding="utf-8").replace('definition_version = "1"', 'definition_version = "2"'), encoding="utf-8")
    catalog = load_catalog(root)
    assert set(catalog.by_kind_versioned["capability"]["repository_discovery"]) == {"1", "2"}
    assert catalog.by_kind["capability"]["repository_discovery"].definition_version == "2"
    with pytest.raises(ValueError, match="ambiguous"):
        catalog.get("capability", "repository_discovery")
    assert catalog.ref("capability", "repository_discovery", "1").definition_version == "1"
    assert catalog.ref("capability", "repository_discovery", "2").definition_version == "2"


def test_operator_grants_require_authorization_and_are_canonicalized() -> None:
    catalog = load_catalog(CATALOG_ROOT)
    item = work_item().model_copy(update={"approved_scope": ("project/**",)})
    compiled = compile_pipeline(catalog, item, (), lead(), NOW)
    stage_spec = next(stage for stage in compiled.plan.stages if stage.stage == "discovery")
    assignment = Assignment(
        schema_version="2.0",
        kind="assignment",
        assignment_id="assignment-grants",
        work_item=compiled.refs.work_item,
        stage="discovery",
        agent_spec=stage_spec.agent_spec,
        scope=("project/**",),
    )
    common = {
        "assignment": assignment,
        "work_item": item,
        "pipeline_revision": revision(compiled),
        "stage_spec": stage_spec,
        "attempt_id": "attempt-1",
        "role_instance_id": "role-grants",
    }
    with pytest.raises(ValueError, match="authorization"):
        build_role_instance(catalog, **common, operator_grant_ids=("repository_readonly",))
    authorization = RecordRef(record_id="decision-grants", kind="lead_decision", digest="b" * 64)
    duplicate = build_role_instance(
        catalog,
        **common,
        operator_grant_ids=("project_lead", "repository_readonly", "project_lead"),
        operator_grants_authorization=authorization,
    )
    reordered = build_role_instance(
        catalog,
        **common,
        operator_grant_ids=("repository_readonly", "project_lead"),
        operator_grants_authorization=authorization,
    )
    assert duplicate.operator_grants == reordered.operator_grants
    assert duplicate.effective_policy_digest == reordered.effective_policy_digest


def test_public_builder_pins_practical_opencode_execution_attestation() -> None:
    catalog = load_catalog(CATALOG_ROOT)
    item = work_item()
    compiled = compile_pipeline(catalog, item, (), lead(), NOW)
    stage_spec = next(stage for stage in compiled.plan.stages if stage.stage == "implementation")
    assignment = Assignment(
        schema_version="2.0",
        kind="assignment",
        assignment_id="assignment-opencode",
        work_item=compiled.refs.work_item,
        stage="implementation",
        agent_spec=stage_spec.agent_spec,
        scope=("project/src/**", "project/tests/**"),
    )
    role = build_role_instance(
        catalog,
        assignment=assignment,
        work_item=item,
        pipeline_revision=revision(compiled),
        stage_spec=stage_spec,
        attempt_id="attempt-1",
    )
    assert role.host_isolation_authorization is not None
    assert role.host_isolation_authorization.kind == "attestation"
    assert role.host_isolation_authorization.record_id == "opencode-product-audit-v1"
