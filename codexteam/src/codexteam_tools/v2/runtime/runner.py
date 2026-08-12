from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

from ..canonical import canonical_json, canonical_sha256
from ..catalog import Catalog
from ..compiler import build_role_instance
from ..evidence import EvidenceManager, StageCandidate, derive_change_set, workspace_manifest
from ..models import (
    ActorRef,
    Assignment,
    AssuranceDisposition,
    AssuranceReport,
    CandidateReport,
    ChangeSet,
    ContextItem,
    ContextPack,
    CriterionDisposition,
    EffectivePermissionRequest,
    EvidenceType,
    PermissionOperation,
    PermissionPolicy,
    PermissionResource,
    PipelineRevision,
    PipelineStageSpec,
    ProjectManifest,
    ProjectPolicy,
    RecordRef,
    ReviewDecision,
    RoleInstance,
    SemanticFinding as StoredSemanticFinding,
    StageSession,
    VerificationReceipt,
    WorkItem,
    evaluate_effective_permission,
    project_path_pattern_matches,
)
from ..pipeline_runtime import PipelineRunProjection, PipelineRuntime
from ..storage import V2ProjectStore
from .base import (
    DefectPacket,
    DraftTurn,
    ProbeResult,
    PreflightReceipt,
    RenderedContext,
    RenderedContextItem,
    RuntimeAdapter,
    RuntimeOutputError,
    RuntimePreflightError,
    SemanticAssurance,
    SemanticCandidate,
    SemanticDiscovery,
    SemanticFinding as RuntimeSemanticFinding,
    SemanticReview,
    SemanticResponse,
    StageSemantic,
    validate_stage_semantic,
    validate_runtime_value,
    opencode_execution_attestation,
)
from ..verification import receipt_is_fresh


MAX_CONTEXT_ITEMS = 20
MAX_CONTEXT_BYTES = 32 * 1024


@dataclass(frozen=True)
class PreparedStage:
    assignment: Assignment
    context_pack: ContextPack
    role_instance: RoleInstance
    base_manifest: ProjectManifest
    preflight: PreflightReceipt
    projection: PipelineRunProjection


@dataclass(frozen=True)
class StageExecution:
    prepared: PreparedStage
    session_id: str
    response: SemanticResponse
    candidate: StageCandidate | None
    semantic_candidate: StageSemantic | None
    assurance_report: AssuranceReport | None = None
    review_decision: ReviewDecision | None = None


class StageRunner:
    """Backend-neutral authoritative stage envelope around a RuntimeAdapter."""

    def __init__(
        self,
        *,
        store: V2ProjectStore,
        catalog: Catalog,
        adapter: RuntimeAdapter,
        work_item: WorkItem,
        pipeline_revision: PipelineRevision,
        stage: PipelineStageSpec,
        run_id: str,
        now: datetime | None = None,
        context_items: tuple[ContextItem, ...] = (),
        scope: tuple[str, ...] | None = None,
        producer_candidate: CandidateReport | None = None,
        verification_receipts: tuple[VerificationReceipt, ...] = (),
        assurance_report: AssuranceReport | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.adapter = adapter
        self.work_item = work_item
        self.pipeline_revision = pipeline_revision
        self.stage = stage
        self.run_id = run_id
        self.now = now or datetime.now(timezone.utc)
        self.context_items = context_items
        if scope is None:
            resolved = catalog.resolve_agent_spec(
                stage.agent_spec.definition_id, stage.agent_spec.definition_version
            )
            write_patterns = tuple(
                rule.resource_pattern
                for rule in resolved.permission_policy.rules
                if rule.effect == "allow"
                and rule.operation == PermissionOperation.WRITE
                and rule.resource == PermissionResource.PROJECT_PATH
            )
            effective_scope = {
                narrower
                for approved in work_item.approved_scope
                for allowed in write_patterns
                for broader, narrower in ((approved, allowed), (allowed, approved))
                if project_path_pattern_matches(broader, narrower, candidate_is_pattern=True)
            }
            self.scope = tuple(sorted(effective_scope)) or work_item.approved_scope
        else:
            self.scope = scope
        self.producer_candidate = producer_candidate
        self.verification_receipts = verification_receipts
        self.assurance_report = assurance_report
        self.runtime = PipelineRuntime(store, catalog=catalog)
        self._prepared: PreparedStage | None = None
        self._turn: DraftTurn | None = None
        self._candidate_number = 0
        self._feedback_used = False
        self._rendered_context: RenderedContext | None = None
        self._resume_session_id: str | None = None
        self._pending_candidate_ref: RecordRef | None = None
        self._pending_candidate: StageCandidate | None = None
        self._accepted_verification_candidate: StageCandidate | None = None
        self._audit_number = 0

    def _resolved_policies(self, role: RoleInstance) -> tuple[PermissionPolicy | ProjectPolicy, ...]:
        resolved = self.catalog.resolve_agent_spec(role.agent_spec.definition_id, role.agent_spec.definition_version)
        project = self.catalog.get("project_policy", role.project_policy.definition_id, role.project_policy.definition_version)
        grants = tuple(
            cast(PermissionPolicy, self.catalog.get("permission_policy", ref.definition_id, ref.definition_version))
            for ref in role.operator_grants
        )
        return (resolved.responsibility_permission_ceiling, cast(ProjectPolicy, project), resolved.permission_policy, *grants)

    def _context_item(
        self,
        label: str,
        category: Literal["requirement", "design", "source", "evidence", "decision", "limitation"],
        value: object,
    ) -> ContextItem:
        content = canonical_json(value)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return ContextItem(
            schema_version="2.0",
            kind="context_item",
            context_item_id=f"context-{self.stage.stage_id}-{label}-{digest}",
            category=category,
            summary=content,
            digest=digest,
        )

    def _upstream_context(self) -> tuple[ContextItem, ...]:
        if self.stage.stage not in {"assurance", "review"}:
            return ()
        if self.producer_candidate is None:
            raise RuntimePreflightError(f"{self.stage.stage} requires the implementation candidate context")
        producer_ref = self.store.reference(self.producer_candidate)
        if self.store.resolve(producer_ref) != self.producer_candidate or self.producer_candidate.stage != "implementation":
            raise RuntimePreflightError("upstream implementation candidate is not an exact stored implementation record")
        if not self.verification_receipts or any(
            not receipt.accepted
            or receipt.candidate != producer_ref
            or self.store.resolve(self.store.reference(receipt)) != receipt
            or not isinstance(change_set := self.store.resolve(receipt.change_set), ChangeSet)
            or not receipt_is_fresh(
                receipt,
                self.producer_candidate,
                change_set,
                workspace_manifest(self.store.project, created_at=self.now),
            )
            for receipt in self.verification_receipts
        ):
            raise RuntimePreflightError(f"{self.stage.stage} requires accepted stored verification receipt context")
        items = [
            self._context_item(
                "pipeline-work-item",
                "requirement",
                {
                    "pipeline_revision": self.store.reference(self.pipeline_revision),
                    "stage_id": self.stage.stage_id,
                    "work_item": self.store.reference(self.work_item),
                    "criteria": self.work_item.acceptance_criteria,
                },
            ),
            self._context_item(
                "implementation-candidate",
                "evidence",
                {
                    "candidate": producer_ref,
                    "stage": self.producer_candidate.stage,
                    "outcome": self.producer_candidate.outcome,
                    "criterion_dispositions": self.producer_candidate.criterion_dispositions,
                    "findings": self.producer_candidate.findings,
                    "limitations": self.producer_candidate.limitations,
                    "change_set": self.producer_candidate.change_set,
                    "evidence": self.producer_candidate.evidence,
                },
            ),
            *(
                self._context_item(
                    f"verification-receipt-{index}",
                    "evidence",
                    {
                        "receipt": self.store.reference(receipt),
                        "accepted": receipt.accepted,
                        "candidate": receipt.candidate,
                        "change_set": receipt.change_set,
                        "workspace_digest": receipt.workspace_digest,
                        "criterion_results": receipt.criterion_results,
                    },
                )
                for index, receipt in enumerate(self.verification_receipts)
            ),
        ]
        if self.stage.stage == "review":
            if self.assurance_report is None:
                raise RuntimePreflightError("review requires the assurance report context")
            assurance_ref = self.store.reference(self.assurance_report)
            if (
                self.store.resolve(assurance_ref) != self.assurance_report
                or self.assurance_report.candidate != producer_ref
            ):
                raise RuntimePreflightError("upstream assurance report is not exact or is bound to another candidate")
            items.append(
                self._context_item(
                    "assurance-report",
                    "decision",
                    {
                        "assurance_report": assurance_ref,
                        "candidate": self.assurance_report.candidate,
                        "dispositions": self.assurance_report.dispositions,
                    },
                )
            )
        return tuple(items)

    def _audit_changes(self, before: ProjectManifest, after: ProjectManifest, phase: str) -> tuple[ChangeSet, tuple[str, ...]]:
        self._audit_number += 1
        change = derive_change_set(
            before,
            after,
            created_at=self.now,
            change_set_id=f"change-audit-{canonical_sha256((self.run_id, self.stage.stage_id, phase, self._audit_number, before.root_digest, after.root_digest))}",
        )
        self.store.write_immutable(before, before.manifest_id)
        self.store.write_immutable(after, after.manifest_id)
        self.store.write_immutable(change, change.change_set_id)
        policies = self._resolved_policies(cast(PreparedStage, self._prepared).role_instance)
        forbidden = tuple(
            entry.path
            for entry in change.entries
            if not any(project_path_pattern_matches(pattern, entry.path) for pattern in self.work_item.approved_scope)
            or not evaluate_effective_permission(
                policies,
                EffectivePermissionRequest(
                    operation=PermissionOperation.WRITE,
                    resource=PermissionResource.PROJECT_PATH,
                    project_path=entry.path,
                ),
                cast(PreparedStage, self._prepared).role_instance.assignment_scope,
                cast(PreparedStage, self._prepared).role_instance.backend_supported_operations,
                cast(PreparedStage, self._prepared).role_instance.backend_supported_resources,
            )
        )
        return change, forbidden

    def _mutable_turn(self, phase: str, operation):
        before = workspace_manifest(self.store.project, created_at=self.now)
        error: BaseException | None = None
        value = None
        try:
            value = operation()
        except BaseException as exc:
            error = exc
        try:
            after = workspace_manifest(self.store.project, created_at=self.now)
            change, forbidden = self._audit_changes(before, after, phase)
        except BaseException as audit_error:
            raise RuntimeOutputError(f"{phase} workspace audit failed: {audit_error}") from audit_error
        if forbidden or (error is not None and change.entries):
            detail = f"; forbidden changes: {', '.join(forbidden)}" if forbidden else ""
            raise RuntimeOutputError(
                f"{phase} failed after workspace changes recorded as {change.change_set_id}{detail}"
            ) from error
        if error is not None:
            raise error
        return value

    def _validate_preflight(
        self, role: RoleInstance, pack: ContextPack, receipt: PreflightReceipt, workspace: Path
    ) -> None:
        resolved = self.catalog.resolve_agent_spec(role.agent_spec.definition_id, role.agent_spec.definition_version)
        expected_refs = (
            self.catalog.ref("agent_spec", resolved.agent_spec.agent_spec_id, resolved.agent_spec.definition_version),
            self.catalog.ref("backend_definition", resolved.backend.backend_id, resolved.backend.definition_version),
            self.catalog.ref("guidance_bundle", resolved.guidance_bundle.bundle_id, resolved.guidance_bundle.definition_version),
        )
        if (role.agent_spec, role.backend, role.guidance_bundle) != expected_refs:
            raise RuntimePreflightError("RoleInstance catalog pins do not resolve exactly")
        if receipt.role_instance_digest != role.resolved_digest or receipt.context_pack_digest != pack.digest:
            raise RuntimePreflightError("runtime preflight did not echo the exact role and context pins")
        if receipt.catalog_digest != self.catalog.catalog_lock()["catalog_digest"]:
            raise RuntimePreflightError("runtime preflight catalog digest mismatch")
        if Path(receipt.workspace).resolve() != workspace.resolve() or workspace.resolve() != self.store.project:
            raise RuntimePreflightError("runtime preflight workspace mismatch")
        if receipt.backend_id != role.backend.definition_id:
            raise RuntimePreflightError("runtime preflight backend mismatch")
        for module in resolved.guidance_modules:
            content = (self.catalog.root / module.path).read_bytes()
            if hashlib.sha256(content).hexdigest() != module.digest:
                raise RuntimePreflightError(f"guidance content mismatch: {module.path}")
        policies = self._resolved_policies(role)
        required_operations = {
            operation for capability in resolved.capabilities for operation in capability.required_operations
        }
        required_resources = {
            resource for capability in resolved.capabilities for resource in capability.required_resources
        }
        if not set(receipt.observed_capabilities) >= {item.capability_id for item in resolved.capabilities}:
            raise RuntimePreflightError("backend observed capability support is incomplete")
        if any(probe.status != "passed" for probe in receipt.probes):
            raise RuntimePreflightError("runtime preflight contains a failed observed operation/resource probe")
        observed_operations = {probe.operation for probe in receipt.probes}
        observed_resources = {probe.resource for probe in receipt.probes}
        if not observed_operations >= required_operations:
            raise RuntimePreflightError("backend observed operation probes are incomplete")
        if not observed_resources >= required_resources:
            raise RuntimePreflightError("backend observed resource probes are incomplete")
        required_rules = tuple(
            rule
            for rule in resolved.permission_policy.rules
            if rule.effect == "allow"
            and rule.operation in required_operations
            and rule.resource in required_resources
        )
        observed_pairs = {(probe.operation, probe.resource) for probe in receipt.probes}
        missing_pairs = {
            (rule.operation, rule.resource) for rule in required_rules
        } - observed_pairs
        if missing_pairs:
            raise RuntimePreflightError("runtime preflight operation/resource probes are incomplete")
        for rule in required_rules:
            resource = rule.resource
            path_pattern = rule.resource_pattern
            if resource == PermissionResource.PROJECT_PATH:
                path_pattern = next(
                    (
                        scope
                        for scope in role.assignment_scope
                        if project_path_pattern_matches(
                            rule.resource_pattern, scope, candidate_is_pattern=True
                        )
                    ),
                    rule.resource_pattern,
                )
            concrete_path = "/".join(
                "probe" if "*" in part else part for part in path_pattern.split("/")
            )
            request = EffectivePermissionRequest(
                operation=rule.operation,
                resource=resource,
                **(
                    {"project_path": concrete_path}
                    if resource == PermissionResource.PROJECT_PATH
                    else {"resource_name": rule.resource_pattern}
                ),
            )
            if not evaluate_effective_permission(
                policies,
                request,
                role.assignment_scope,
                role.backend_supported_operations,
                role.backend_supported_resources,
            ):
                raise RuntimePreflightError("effective permissions do not satisfy backend requirements")
        if not set(resolved.backend.supported_operations) >= required_operations:
            raise RuntimePreflightError("backend operation support is incomplete")

    def _render_context(self, pack: ContextPack, assignment_scope: tuple[str, ...]) -> RenderedContext:
        if len(pack.items) > MAX_CONTEXT_ITEMS:
            raise RuntimePreflightError(f"rendered context exceeds {MAX_CONTEXT_ITEMS} items")
        rendered: list[RenderedContextItem] = []
        total = 0
        for reference in pack.items:
            resolved = self.store.resolve(reference)
            if not isinstance(resolved, ContextItem):
                raise RuntimePreflightError("ContextPack item did not resolve to a ContextItem")
            if resolved.path is None:
                content = resolved.summary
                content_bytes = content.encode("utf-8")
            else:
                try:
                    content_bytes = self._read_context_file(resolved.path)
                    content = content_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise RuntimePreflightError(f"context item is not UTF-8 text: {resolved.path}") from exc
            content_digest = hashlib.sha256(content_bytes).hexdigest()
            if content_digest != resolved.digest:
                raise RuntimePreflightError(f"context content digest mismatch: {resolved.context_item_id}")
            total += len(content_bytes)
            if total > MAX_CONTEXT_BYTES:
                raise RuntimePreflightError(f"rendered context exceeds {MAX_CONTEXT_BYTES} bytes")
            rendered.append(
                RenderedContextItem(
                    category=resolved.category,
                    summary=resolved.summary,
                    locator=resolved.path,
                    content=content,
                    content_digest=content_digest,
                    intended_use=f"Use as {resolved.category} context for stage {self.stage.stage_id}.",
                )
            )
        scope_content = canonical_json({
            "assignment_scope": assignment_scope,
            "paths_are_relative_to": "canary root",
        })
        scope_bytes = scope_content.encode("utf-8")
        total += len(scope_bytes)
        if total > MAX_CONTEXT_BYTES:
            raise RuntimePreflightError(f"rendered context exceeds {MAX_CONTEXT_BYTES} bytes")
        rendered.append(RenderedContextItem(
            category="limitation",
            summary="Exact assignment scope for this stage.",
            locator=None,
            content=scope_content,
            content_digest=hashlib.sha256(scope_bytes).hexdigest(),
            intended_use="Enforce these exact write boundaries; they are not suggestions.",
        ))
        items = tuple(rendered)
        return RenderedContext(
            context_pack_digest=pack.digest,
            items=items,
            rendered_digest=canonical_sha256({"context_pack_digest": pack.digest, "items": items}),
        )

    def _read_context_file(self, relative: str) -> bytes:
        parts = relative.split("/")
        root = os.open(self.store.project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor = root
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                if descriptor != root:
                    os.close(descriptor)
                descriptor = child
            file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                metadata = os.fstat(file_descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise RuntimePreflightError(f"context path is not a contained regular file: {relative}")
                if metadata.st_size > MAX_CONTEXT_BYTES:
                    raise RuntimePreflightError(f"context item exceeds {MAX_CONTEXT_BYTES} bytes: {relative}")
                chunks = []
                total = 0
                while chunk := os.read(file_descriptor, min(8192, MAX_CONTEXT_BYTES + 1 - total)):
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_CONTEXT_BYTES:
                        raise RuntimePreflightError(f"context item exceeds {MAX_CONTEXT_BYTES} bytes: {relative}")
                return b"".join(chunks)
            finally:
                os.close(file_descriptor)
        except OSError as exc:
            raise RuntimePreflightError(f"context path cannot be opened safely: {relative}") from exc
        finally:
            if descriptor != root:
                os.close(descriptor)
            os.close(root)

    def _writable_probe_path(self, role: RoleInstance) -> str | None:
        policies = self._resolved_policies(role)
        resolved = self.catalog.resolve_agent_spec(role.agent_spec.definition_id, role.agent_spec.definition_version)
        for rule in resolved.permission_policy.rules:
            if rule.effect != "allow" or rule.operation != PermissionOperation.WRITE or rule.resource != PermissionResource.PROJECT_PATH:
                continue
            parts = rule.resource_pattern.split("/")
            if parts[-1] == "**":
                parts[-1] = ".codexteam-preflight-canary"
            else:
                parts = ["codexteam-preflight-canary" if "*" in part else part for part in parts]
            candidate = "/".join(parts)
            request = EffectivePermissionRequest(
                operation=PermissionOperation.WRITE,
                resource=PermissionResource.PROJECT_PATH,
                project_path=candidate,
            )
            if evaluate_effective_permission(
                policies,
                request,
                role.assignment_scope,
                role.backend_supported_operations,
                role.backend_supported_resources,
            ):
                return candidate
        return None

    def _kernel_probes(
        self, role: RoleInstance, adapter_probes: tuple[ProbeResult, ...] = ()
    ) -> tuple[ProbeResult, ...]:
        resolved = self.catalog.resolve_agent_spec(role.agent_spec.definition_id, role.agent_spec.definition_version)
        operations = {item for capability in resolved.capabilities for item in capability.required_operations}
        resources = {item for capability in resolved.capabilities for item in capability.required_resources}
        probes: list[ProbeResult] = []
        before = workspace_manifest(self.store.project, created_at=self.now).root_digest
        if PermissionOperation.READ in operations or PermissionResource.PROJECT_PATH in resources:
            self.store.resolve(self.store.reference(self.work_item))
            probes.append(ProbeResult(operation=PermissionOperation.READ, resource=PermissionResource.PROJECT_PATH, status="passed", evidence_summary="Resolved the pinned WorkItem from the contained v2 store."))
        adapter_pairs = {(probe.operation, probe.resource) for probe in adapter_probes}
        if (
            PermissionOperation.WRITE in operations
            and PermissionResource.PROJECT_PATH in resources
            and (PermissionOperation.WRITE, PermissionResource.PROJECT_PATH) not in adapter_pairs
        ):
            relative = self._writable_probe_path(role)
            if relative is not None:
                target = self.store.project.joinpath(*relative.split("/"))
                created_parents: list[Path] = []
                parent = target.parent
                while parent != self.store.project and not parent.exists():
                    created_parents.append(parent)
                    parent = parent.parent
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    os.write(descriptor, b"codexteam-v2-preflight\n")
                    os.close(descriptor)
                finally:
                    target.unlink(missing_ok=True)
                    for directory in created_parents:
                        try:
                            directory.rmdir()
                        except OSError:
                            pass
                probes.append(ProbeResult(operation=PermissionOperation.WRITE, resource=PermissionResource.PROJECT_PATH, status="passed", evidence_summary=f"Created and removed contained canary {relative}."))
        if PermissionOperation.EXECUTE in operations:
            result = subprocess.run(("/usr/bin/true",), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, timeout=5, check=False)
            if result.returncode != 0:
                raise RuntimePreflightError("fixed no-shell process probe failed")
            probes.append(ProbeResult(operation=PermissionOperation.EXECUTE, resource=PermissionResource.PROCESS, status="passed", evidence_summary="Executed fixed argv /usr/bin/true without a shell; exit code 0."))
        if PermissionResource.EVIDENCE in resources:
            evidence_dir = self.store.root / "evidence"
            descriptor = os.open(evidence_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            name = f".preflight-{role.role_instance_id}"
            try:
                canary = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
                try:
                    os.write(canary, b"codexteam-v2-preflight\n")
                finally:
                    os.close(canary)
                os.unlink(name, dir_fd=descriptor)
            finally:
                os.close(descriptor)
            probes.append(ProbeResult(operation=PermissionOperation.WRITE, resource=PermissionResource.EVIDENCE, status="passed", evidence_summary="Created and removed a canary in the contained v2 evidence store."))
        after = workspace_manifest(self.store.project, created_at=self.now).root_digest
        if after != before:
            raise RuntimePreflightError("kernel preflight probes changed the workspace manifest")
        return tuple(probes)

    def _recover_candidates(self, role: RoleInstance) -> None:
        prefix = f"candidate-{role.role_instance_id}-"
        recovered: list[tuple[int, CandidateReport]] = []
        for record in self.store.records("candidate_report"):
            if not isinstance(record, CandidateReport) or not record.candidate_report_id.startswith(prefix):
                continue
            suffix = record.candidate_report_id.removeprefix(prefix)
            if suffix.isdigit() and record.role_instance == self.store.reference(role) and record.stage_id == role.stage_id:
                recovered.append((int(suffix), record))
        if recovered:
            self._candidate_number, latest = max(recovered, key=lambda item: item[0])
            self._pending_candidate_ref = self.store.reference(latest)

    def prepare(self) -> PreparedStage:
        if self._prepared is not None:
            return self._prepared
        revision_ref = self.store.reference(self.pipeline_revision)
        identity = canonical_sha256((self.work_item.work_item_id, revision_ref, self.stage.stage_id))
        assignment = Assignment(
            schema_version="2.0",
            kind="assignment",
            assignment_id=f"assignment-{identity}",
            work_item=self.store.reference(self.work_item),
            stage=self.stage.stage,
            agent_spec=self.stage.agent_spec,
            scope=self.scope,
            assurance_domain=self.stage.assurance_domain,
        )
        assignment_ref = self.store.write_immutable(assignment, assignment.assignment_id)
        all_context_items = (*self.context_items, *self._upstream_context())
        item_refs = tuple(self.store.write_immutable(item, item.context_item_id) for item in all_context_items)
        pack = ContextPack(
            schema_version="2.0",
            kind="context_pack",
            context_pack_id=f"context-{identity}",
            assignment=assignment_ref,
            items=item_refs,
            digest=canonical_sha256(item_refs),
        )
        self.store.write_immutable(pack, pack.context_pack_id)
        role = build_role_instance(
            self.catalog,
            assignment=assignment,
            work_item=self.work_item,
            pipeline_revision=self.pipeline_revision,
            stage_spec=self.stage,
            attempt_id=f"attempt-{identity}",
            host_isolation_authorization=(
                opencode_execution_attestation()
                if self.catalog.resolve_agent_spec(
                    self.stage.agent_spec.definition_id,
                    self.stage.agent_spec.definition_version,
                ).backend.provider == "opencode"
                else None
            ),
        )
        self._rendered_context = self._render_context(pack, role.assignment_scope)
        self.store.write_immutable(role, role.role_instance_id)
        self._recover_candidates(role)
        manager = EvidenceManager(self.store)
        base_ref = manager.begin_stage(self.stage.stage_id, role, started_at=self.now)
        base = cast(ProjectManifest, self.store.resolve(base_ref))
        try:
            raw_receipt = self.adapter.preflight(role, pack, self.store.project)
            receipt = cast(PreflightReceipt, validate_runtime_value(PreflightReceipt, raw_receipt))
            receipt = receipt.model_copy(
                update={"probes": (*receipt.probes, *self._kernel_probes(role, receipt.probes))}
            )
            self._validate_preflight(role, pack, receipt, self.store.project)
        except RuntimePreflightError:
            raise
        except Exception as exc:
            raise RuntimePreflightError(f"runtime preflight failed: {exc}") from exc
        projection = self.runtime.replay(self.run_id)
        runtime_stage = next(item for item in projection.stages if item.stage_id == self.stage.stage_id)
        role_ref = self.store.reference(role)
        if runtime_stage.status == "active":
            if runtime_stage.active_role_instance != role_ref or runtime_stage.attempt_id != role.attempt_id:
                raise RuntimePreflightError("active stage is bound to a different role or attempt")
            try:
                session = cast(StageSession, self.store.read_record("stage_session", f"session-{role.role_instance_id}"))
            except FileNotFoundError:
                session = None
            if session is not None:
                if (
                    session.role_instance != role_ref
                    or session.stage_id != role.stage_id
                    or session.attempt_id != role.attempt_id
                    or session.context_digest != self._rendered_context.rendered_digest
                    or Path(session.workspace).resolve() != self.store.project
                ):
                    raise RuntimePreflightError("persisted stage session does not match the active stage")
                self._resume_session_id = session.backend_session_id
        else:
            projection = self.runtime.start(
                self.run_id,
                self.stage.stage_id,
                role,
                expected_state_revision=projection.state_revision,
            )
        self._prepared = PreparedStage(assignment, pack, role, base, receipt, projection)
        return self._prepared

    def draft(self) -> StageExecution:
        prepared = self.prepare()
        context = cast(RenderedContext, self._rendered_context)
        def invoke():
            if self._resume_session_id is None:
                return self.adapter.draft(prepared.role_instance, context, self.store.project)
            return self.adapter.resume(
                self._resume_session_id,
                prepared.role_instance,
                context,
                self.store.project,
                candidate_sequence=self._candidate_number,
            )

        raw = self._mutable_turn("draft", invoke)
        try:
            self._turn = cast(DraftTurn, validate_runtime_value(DraftTurn, raw))
        except RuntimeOutputError as exc:
            raise RuntimeOutputError(f"malformed draft output after audited workspace changes: {exc}") from exc
        if self._turn.consumed_context_digest != context.rendered_digest:
            raise RuntimeOutputError("runtime did not consume the exact rendered context")
        session = StageSession(
            schema_version="2.0",
            kind="stage_session",
            stage_session_id=f"session-{prepared.role_instance.role_instance_id}",
            role_instance=self.store.reference(prepared.role_instance),
            stage_id=self.stage.stage_id,
            attempt_id=prepared.role_instance.attempt_id,
            backend_session_id=self._turn.session_id,
            context_digest=context.rendered_digest,
            workspace=str(self.store.project),
            created_at=self.now,
        )
        self.store.write_immutable(session, session.stage_session_id)
        return StageExecution(prepared, self._turn.session_id, self._turn.response, None, None)

    def feedback(self, packet: DefectPacket) -> SemanticResponse:
        if self._turn is None:
            raise RuntimeOutputError("feedback requires an existing draft session")
        if self._feedback_used:
            raise RuntimeOutputError("a stage permits at most one feedback turn")
        turn = self._turn
        raw = self._mutable_turn("feedback", lambda: self.adapter.feedback(turn.session_id, packet))
        try:
            response = cast(SemanticResponse, validate_runtime_value(SemanticResponse, raw))
        except RuntimeOutputError as exc:
            raise RuntimeOutputError(f"malformed feedback output after audited workspace changes: {exc}") from exc
        self._feedback_used = True
        return response

    def refresh_baseline(self) -> ProjectManifest:
        if self._prepared is None:
            raise RuntimeOutputError("baseline refresh requires a prepared stage")
        reference = EvidenceManager(self.store).refresh_stage(
            self.stage.stage_id, self._prepared.role_instance, started_at=self.now
        )
        base = cast(ProjectManifest, self.store.resolve(reference))
        self._prepared = PreparedStage(
            self._prepared.assignment,
            self._prepared.context_pack,
            self._prepared.role_instance,
            base,
            self._prepared.preflight,
            self._prepared.projection,
        )
        return base

    def candidate(self, *, succeed: bool = True) -> StageExecution:
        if self._prepared is None or self._turn is None:
            raise RuntimeOutputError("candidate requires a prepared draft session")
        if self.stage.stage in {"assurance", "review"}:
            try:
                required_context = tuple(self.store.reference(item) for item in self._upstream_context())
            except RuntimePreflightError as exc:
                raise RuntimeOutputError(f"missing upstream candidate context: {exc}") from exc
            if not set(required_context) <= set(self._prepared.context_pack.items):
                raise RuntimeOutputError("missing upstream candidate context from the pinned ContextPack")
        before_turn = workspace_manifest(self.store.project, created_at=self.now)
        candidate_error: BaseException | None = None
        raw = None
        try:
            raw = self.adapter.candidate(self._turn.session_id, read_only=True)
        except BaseException as exc:
            candidate_error = exc
        after_turn = workspace_manifest(self.store.project, created_at=self.now)
        if before_turn.root_digest != after_turn.root_digest:
            change, _ = self._audit_changes(before_turn, after_turn, "candidate")
            raise RuntimeOutputError(
                f"candidate turn mutated the workspace; changes recorded as {change.change_set_id}"
            ) from candidate_error
        if candidate_error is not None:
            raise candidate_error
        semantic = validate_stage_semantic(raw)
        if semantic.stage != self.stage.stage:
            raise RuntimeOutputError("runtime semantic stage does not match the active stage")
        actor = ActorRef(
            actor_id=f"agent-{self.stage.stage_id}",
            kind="agent",
            role_instance_id=self._prepared.role_instance.role_instance_id,
        )
        manager = EvidenceManager(self.store)
        allowed_evidence_types = {
            "discovery": {EvidenceType.ANALYSIS},
            "architecture": {EvidenceType.ARTIFACT},
            "ux": {EvidenceType.ARTIFACT},
            "implementation": {EvidenceType.ARTIFACT, EvidenceType.ANALYSIS},
            "verification": {EvidenceType.TEST_OUTPUT},
            "assurance": {EvidenceType.REVIEW},
            "review": {EvidenceType.REVIEW},
        }[self.stage.stage]
        if any(item.evidence_type not in allowed_evidence_types for item in semantic.evidence):
            raise RuntimeOutputError(
                f"{self.stage.stage} evidence must use semantic types "
                + ", ".join(sorted(item.value for item in allowed_evidence_types))
            )
        if self.stage.stage == "implementation" and semantic.outcome == "succeeded" and not semantic.evidence:
            raise RuntimeOutputError("successful implementation requires producer evidence")
        evidence_refs = tuple(
            manager.write_artifact(
                item.content.encode("utf-8"),
                item.evidence_type,
                actor,
                created_at=self.now,
                evidence_id=f"evidence-{canonical_sha256((self._prepared.role_instance.role_instance_id, self._candidate_number, index, item))}",
            )[1]
            for index, item in enumerate(semantic.evidence)
        )
        final = workspace_manifest(self.store.project, created_at=self.now)
        change = derive_change_set(self._prepared.base_manifest, final, created_at=self.now)
        policies = self._resolved_policies(self._prepared.role_instance)
        for entry in change.entries:
            if not evaluate_effective_permission(
                policies,
                EffectivePermissionRequest(
                    operation=PermissionOperation.WRITE,
                    resource=PermissionResource.PROJECT_PATH,
                    project_path=entry.path,
                ),
                self._prepared.role_instance.assignment_scope,
                self._prepared.role_instance.backend_supported_operations,
                self._prepared.role_instance.backend_supported_resources,
            ):
                raise RuntimeOutputError(f"runtime changed forbidden path {entry.path!r}")
        change_ref = self.store.write_immutable(change, change.change_set_id)
        criteria = tuple(item.id for item in self.work_item.acceptance_criteria)
        disposition = (
            "unsatisfied"
            if semantic.outcome != "succeeded"
            else "claimed_satisfied"
            if self.stage.stage == "implementation"
            else "not_evaluated"
        )
        dispositions = tuple(
            CriterionDisposition(
                criterion_id=criterion.id,
                disposition=disposition,
                evidence=evidence_refs if disposition == "claimed_satisfied" else (),
                evidence_types=(
                    tuple(sorted({item.evidence_type for item in semantic.evidence}, key=str))
                    if disposition == "claimed_satisfied"
                    else ()
                ),
                note=(
                    None
                    if disposition == "claimed_satisfied"
                    else "Runtime requested correction"
                    if disposition == "unsatisfied"
                    else f"{self.stage.stage} does not authoritatively evaluate work-item satisfaction"
                ),
            )
            for criterion in self.work_item.acceptance_criteria
        )
        self._candidate_number += 1
        report_findings = (
            tuple(item.summary for item in cast(tuple[RuntimeSemanticFinding, ...], semantic.findings))
            if isinstance(semantic, (SemanticAssurance, SemanticReview))
            else semantic.findings
        )
        report = CandidateReport(
            schema_version="2.0",
            kind="candidate_report",
            candidate_report_id=f"candidate-{self._prepared.role_instance.role_instance_id}-{self._candidate_number}",
            work_item=self.store.reference(self.work_item),
            pipeline_revision=self.store.reference(self.pipeline_revision),
            assignment=self.store.reference(self._prepared.assignment),
            role_instance=self.store.reference(self._prepared.role_instance),
            stage=self.stage.stage,
            stage_id=self.stage.stage_id,
            stage_spec_digest=self._prepared.role_instance.stage_spec_digest,
            attempt_id=self._prepared.role_instance.attempt_id,
            context_pack=self.store.reference(self._prepared.context_pack),
            change_set=change_ref if self.stage.stage in {"architecture", "ux", "implementation", "verification"} else None,
            outcome=semantic.outcome,
            criterion_ids=criteria,
            criterion_dispositions=dispositions,
            findings=report_findings,
            limitations=semantic.limitations,
            evidence=evidence_refs,
            produced_at=self.now,
        )
        processed = manager.process_candidate(
            report,
            role_instance=self._prepared.role_instance,
            assignment=self._prepared.assignment,
            work_item=self.work_item,
            pipeline_revision=self.pipeline_revision,
            context_pack=self._prepared.context_pack,
            base_manifest=self._prepared.base_manifest,
            final_manifest=final,
            created_at=self.now,
        )
        self._pending_candidate = processed
        assurance_record = None
        review_record = None
        if isinstance(semantic, SemanticAssurance):
            if self.producer_candidate is None:
                raise RuntimeOutputError("assurance requires the implementation candidate")
            assurance_record = AssuranceReport(
                schema_version="2.0",
                kind="assurance_report",
                assurance_report_id=f"assurance-{self._prepared.role_instance.role_instance_id}-{self._candidate_number}",
                candidate=self.store.reference(self.producer_candidate),
                producer_role_instance_id=self.producer_candidate.role_instance.record_id,
                dispositions=tuple(
                    AssuranceDisposition(
                        domain=item.domain,
                        disposition=item.disposition,
                        findings=tuple(
                            StoredSemanticFinding(**finding.model_dump(mode="python"))
                            for finding in cast(tuple[RuntimeSemanticFinding, ...], item.findings)
                        ),
                        evidence=evidence_refs,
                    )
                    for item in semantic.dispositions
                ),
                auditor=actor,
                produced_at=self.now,
            )
            self.store.write_immutable(assurance_record, assurance_record.assurance_report_id)
            if any(item.disposition != "pass" for item in semantic.dispositions):
                succeed = False
        if isinstance(semantic, SemanticReview):
            if self.producer_candidate is None or self.assurance_report is None:
                raise RuntimeOutputError("review requires implementation and assurance records")
            review_record = ReviewDecision(
                schema_version="2.0",
                kind="review_decision",
                review_decision_id=f"review-{self._prepared.role_instance.role_instance_id}-{self._candidate_number}",
                candidate=self.store.reference(self.producer_candidate),
                producer_role_instance_id=self.producer_candidate.role_instance.record_id,
                decision=semantic.decision,
                rationale=semantic.rationale,
                findings=tuple(
                    StoredSemanticFinding(**finding.model_dump(mode="python"))
                    for finding in cast(tuple[RuntimeSemanticFinding, ...], semantic.findings)
                ),
                evidence=(self.store.reference(self.assurance_report), *evidence_refs),
                verification_receipts=tuple(self.store.reference(item) for item in self.verification_receipts),
                reviewer=actor,
                decided_at=self.now,
            )
            self.store.write_immutable(review_record, review_record.review_decision_id)
            if semantic.decision != "ACCEPT":
                succeed = False
        self._pending_candidate_ref = processed.report_ref
        if succeed and self.stage.stage != "verification":
            if semantic.outcome != "succeeded":
                raise RuntimeOutputError("correction_needed or blocked candidate cannot succeed a stage")
            projection = self.runtime.replay(self.run_id)
            runtime_stage = next(item for item in projection.stages if item.stage_id == self.stage.stage_id)
            if runtime_stage.status == "succeeded":
                projection = self.runtime.replace_candidate(
                    self.run_id,
                    self.stage.stage_id,
                    processed.report_ref,
                    expected_state_revision=projection.state_revision,
                    detail="corrected candidate",
                )
            else:
                projection = self.runtime.succeed(
                    self.run_id,
                    self.stage.stage_id,
                    processed.report_ref,
                    expected_state_revision=projection.state_revision,
                )
            self._prepared = PreparedStage(
                self._prepared.assignment,
                self._prepared.context_pack,
                self._prepared.role_instance,
                self._prepared.base_manifest,
                self._prepared.preflight,
                projection,
            )
        return StageExecution(
            self._prepared,
            self._turn.session_id,
            self._turn.response,
            processed,
            semantic,
            assurance_record,
            review_record,
        )

    def accept_verification(self, receipt_ref: RecordRef) -> PipelineRunProjection:
        if self.stage.stage != "verification" or self._prepared is None or self._pending_candidate_ref is None:
            raise RuntimeOutputError("verification acceptance requires a pending verification candidate")
        receipt = self.store.resolve(receipt_ref)
        if not isinstance(receipt, VerificationReceipt) or not receipt.accepted:
            raise RuntimeOutputError("verification receipt is missing or not accepted")
        if self.producer_candidate is None:
            raise RuntimeOutputError("verification acceptance requires the producer candidate")
        change_set = self.store.resolve(receipt.change_set)
        if not isinstance(change_set, ChangeSet) or not receipt_is_fresh(
            receipt,
            self.producer_candidate,
            change_set,
            workspace_manifest(self.store.project, created_at=self.now),
        ):
            raise RuntimeOutputError("verification receipt is stale or bound to a different candidate")
        if receipt.issued_by.role_instance_id != self._prepared.role_instance.role_instance_id:
            raise RuntimeOutputError("verification receipt was not issued by the active verifier role")
        pending = self._pending_candidate
        if pending is None:
            raise RuntimeOutputError("verification acceptance has no processed candidate")
        evidence_manager = EvidenceManager(self.store)
        verified_dispositions = []
        verified_evidence: list[RecordRef] = []
        for result in receipt.criterion_results:
            types = tuple(sorted({evidence_manager.resolve_artifact(ref).evidence_type for ref in result.evidence}, key=str))
            verified_evidence.extend(result.evidence)
            verified_dispositions.append(
                CriterionDisposition(
                    criterion_id=result.criterion_id,
                    disposition="verified",
                    evidence=result.evidence,
                    evidence_types=types,
                    note=f"Accepted verification receipt {receipt.verification_receipt_id}",
                )
            )
        self._candidate_number += 1
        verified_report = pending.report.model_copy(
            update={
                "candidate_report_id": f"candidate-{self._prepared.role_instance.role_instance_id}-{self._candidate_number}",
                "criterion_dispositions": tuple(verified_dispositions),
                "evidence": tuple(dict.fromkeys((*pending.report.evidence, *verified_evidence))),
            }
        )
        accepted_candidate = evidence_manager.process_candidate(
            verified_report,
            role_instance=self._prepared.role_instance,
            assignment=self._prepared.assignment,
            work_item=self.work_item,
            pipeline_revision=self.pipeline_revision,
            context_pack=self._prepared.context_pack,
            base_manifest=self._prepared.base_manifest,
            final_manifest=workspace_manifest(self.store.project, created_at=self.now),
            created_at=self.now,
        )
        self._accepted_verification_candidate = accepted_candidate
        self._pending_candidate_ref = accepted_candidate.report_ref
        projection = self.runtime.replay(self.run_id)
        runtime_stage = next(item for item in projection.stages if item.stage_id == self.stage.stage_id)
        if runtime_stage.status == "succeeded":
            projection = self.runtime.replace_candidate(
                self.run_id,
                self.stage.stage_id,
                self._pending_candidate_ref,
                expected_state_revision=projection.state_revision,
                detail="accepted fresh verification receipt",
            )
        elif runtime_stage.status == "active":
            projection = self.runtime.succeed(
                self.run_id,
                self.stage.stage_id,
                self._pending_candidate_ref,
                expected_state_revision=projection.state_revision,
                detail="accepted fresh verification receipt",
            )
        else:
            raise RuntimeOutputError("verification stage is not active")
        self._prepared = PreparedStage(
            self._prepared.assignment,
            self._prepared.context_pack,
            self._prepared.role_instance,
            self._prepared.base_manifest,
            self._prepared.preflight,
            projection,
        )
        return projection

    @property
    def accepted_verification_candidate(self) -> StageCandidate | None:
        return self._accepted_verification_candidate

    def run(self) -> StageExecution:
        self.draft()
        return self.candidate()


__all__ = ["PreparedStage", "StageExecution", "StageRunner"]
