from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .canonical import canonical_sha256
from .models import (
    ActorRef,
    Assignment,
    CandidateReport,
    ChangeEntry,
    ChangeSet,
    ContextPack,
    EvidenceArtifact,
    EvidenceType,
    ManifestEntry,
    PipelineRevision,
    ProjectManifest,
    RecordRef,
    RoleInstance,
    WorkItem,
    build_manifest_root_digest,
    pipeline_stage_digest,
    project_path_pattern_matches,
)
from .storage import CorruptStore, V2ProjectStore


_CACHE_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox"}


@dataclass(frozen=True)
class StageCandidate:
    report: CandidateReport
    report_ref: RecordRef
    change_set: ChangeSet
    change_set_ref: RecordRef
    base_manifest: ProjectManifest
    final_manifest: ProjectManifest


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _file_digest(descriptor: int) -> str:
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _walk_workspace(
    project: str | Path,
    visit_file: Callable[[str, int, os.stat_result], None],
) -> None:
    requested = Path(project).absolute()
    cursor = Path(requested.anchor)
    for part in requested.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"workspace path has a symlink ancestor: {cursor}")
    try:
        expected_root = os.stat(requested, follow_symlinks=False)
    except OSError as exc:
        raise ValueError("workspace root cannot be inspected safely") from exc
    try:
        root_fd = os.open(requested, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError("workspace root cannot be opened safely") from exc
    try:
        root_identity = os.fstat(root_fd)
        if not stat.S_ISDIR(root_identity.st_mode) or (root_identity.st_dev, root_identity.st_ino) != (
            expected_root.st_dev,
            expected_root.st_ino,
        ):
            raise ValueError("workspace root must be a real directory")

        def unchanged(parent_fd: int, name: str, opened: os.stat_result, relative: str) -> None:
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as exc:
                raise ValueError(f"workspace entry changed during traversal: {relative}") from exc
            if (current.st_dev, current.st_ino, current.st_mode) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
            ):
                raise ValueError(f"workspace entry changed during traversal: {relative}")

        def walk(directory_fd: int, relative: str = "") -> None:
            try:
                names = sorted(os.listdir(directory_fd))
            except OSError as exc:
                raise ValueError("workspace directory cannot be listed safely") from exc
            for name in names:
                child_relative = f"{relative}/{name}".lstrip("/")
                if child_relative in {".git", ".codexteam"} or child_relative.startswith((".git/", ".codexteam/")):
                    continue
                if name in _CACHE_NAMES or name.endswith((".pyc", ".pyo")):
                    continue
                try:
                    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError as exc:
                    raise ValueError(f"workspace entry changed during traversal: {child_relative}") from exc
                if stat.S_ISLNK(before.st_mode):
                    raise ValueError(f"workspace symlinks are forbidden: {child_relative}")
                if stat.S_ISDIR(before.st_mode):
                    try:
                        child_fd = os.open(
                            name,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory_fd,
                        )
                    except OSError as exc:
                        raise ValueError(f"workspace directory cannot be opened safely: {child_relative}") from exc
                    try:
                        opened = os.fstat(child_fd)
                        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                            raise ValueError(f"workspace entry changed during traversal: {child_relative}")
                        walk(child_fd, child_relative)
                        unchanged(directory_fd, name, opened, child_relative)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(before.st_mode):
                    try:
                        child_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    except OSError as exc:
                        raise ValueError(f"workspace file cannot be opened safely: {child_relative}") from exc
                    try:
                        opened = os.fstat(child_fd)
                        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                            before.st_dev,
                            before.st_ino,
                        ):
                            raise ValueError(f"workspace entry changed during traversal: {child_relative}")
                        visit_file(child_relative, child_fd, opened)
                        after = os.fstat(child_fd)
                        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                            opened.st_dev,
                            opened.st_ino,
                            opened.st_size,
                            opened.st_mtime_ns,
                        ):
                            raise ValueError(f"workspace file changed while reading: {child_relative}")
                        unchanged(directory_fd, name, opened, child_relative)
                    finally:
                        os.close(child_fd)
                else:
                    raise ValueError(f"unsupported workspace entry: {child_relative}")

        walk(root_fd)
        try:
            current_root = os.stat(requested, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("workspace root changed during traversal") from exc
        if (current_root.st_dev, current_root.st_ino) != (root_identity.st_dev, root_identity.st_ino):
            raise ValueError("workspace root changed during traversal")
    finally:
        os.close(root_fd)


def workspace_manifest(
    project: str | Path,
    *,
    created_at: datetime | None = None,
    manifest_id: str | None = None,
) -> ProjectManifest:
    entries: list[ManifestEntry] = []

    def capture(relative: str, descriptor: int, metadata: os.stat_result) -> None:
        entries.append(ManifestEntry(path=relative, digest=_file_digest(descriptor), size_bytes=metadata.st_size))

    _walk_workspace(project, capture)
    sorted_entries = tuple(sorted(entries, key=lambda item: item.path))
    root_digest = build_manifest_root_digest(sorted_entries)
    timestamp = _now(created_at)
    identity = {
        "schema_version": "2.0",
        "kind": "project_manifest",
        "created_at": timestamp,
        "entries": sorted_entries,
        "root_digest": root_digest,
    }
    return ProjectManifest(
        schema_version="2.0",
        kind="project_manifest",
        manifest_id=manifest_id or f"manifest-{canonical_sha256(identity)}",
        entries=sorted_entries,
        root_digest=root_digest,
        created_at=timestamp,
    )


build_workspace_manifest = workspace_manifest


def derive_change_set(
    base: ProjectManifest,
    final: ProjectManifest,
    *,
    created_at: datetime | None = None,
    change_set_id: str | None = None,
) -> ChangeSet:
    before = {entry.path: entry for entry in base.entries}
    after = {entry.path: entry for entry in final.entries}
    entries: list[ChangeEntry] = []
    for path in sorted(before.keys() | after.keys()):
        left = before.get(path)
        right = after.get(path)
        if left is None:
            entries.append(ChangeEntry(path=path, action="create", after_digest=cast(ManifestEntry, right).digest))
        elif right is None:
            entries.append(ChangeEntry(path=path, action="delete", before_digest=left.digest))
        elif left.digest != right.digest:
            entries.append(ChangeEntry(path=path, action="modify", before_digest=left.digest, after_digest=right.digest))
    timestamp = _now(created_at)
    identity = {
        "schema_version": "2.0",
        "kind": "change_set",
        "base_manifest_digest": base.root_digest,
        "created_at": timestamp,
        "entries": entries,
        "final_manifest_digest": final.root_digest,
    }
    return ChangeSet(
        schema_version="2.0",
        kind="change_set",
        change_set_id=change_set_id or f"change-{canonical_sha256(identity)}",
        base_manifest_digest=base.root_digest,
        final_manifest_digest=final.root_digest,
        entries=tuple(entries),
        created_at=timestamp,
    )


def compose_change_sets(base: ProjectManifest, changes: tuple[ChangeSet, ...] | list[ChangeSet]) -> ChangeSet:
    """Compose ordered writing-stage changes into their net workspace attribution."""
    state = {entry.path: entry.digest for entry in base.entries}
    if changes and changes[0].base_manifest_digest != base.root_digest:
        raise ValueError("writing-stage ChangeSets do not begin at the run base manifest")
    for change in changes:
        for entry in change.entries:
            current = state.get(entry.path)
            if current != entry.before_digest:
                raise ValueError(f"writing-stage ChangeSet chain breaks at {entry.path!r}")
            if entry.after_digest is None:
                state.pop(entry.path, None)
            else:
                state[entry.path] = entry.after_digest
    if changes:
        for left, right in zip(changes, changes[1:]):
            if left.final_manifest_digest != right.base_manifest_digest:
                raise ValueError("writing-stage ChangeSets are not contiguous")
    entries = []
    before = {entry.path: entry.digest for entry in base.entries}
    for path in sorted(before.keys() | state.keys()):
        left = before.get(path)
        right = state.get(path)
        if left is None:
            entries.append(ChangeEntry(path=path, action="create", after_digest=right))
        elif right is None:
            entries.append(ChangeEntry(path=path, action="delete", before_digest=left))
        elif left != right:
            entries.append(ChangeEntry(path=path, action="modify", before_digest=left, after_digest=right))
    final_digest = changes[-1].final_manifest_digest if changes else base.root_digest
    return ChangeSet(
        schema_version="2.0",
        kind="change_set",
        change_set_id=f"composed-{canonical_sha256((base.root_digest, final_digest, entries))}",
        base_manifest_digest=base.root_digest,
        final_manifest_digest=final_digest,
        entries=tuple(entries),
        created_at=changes[-1].created_at if changes else base.created_at,
    )


def validate_change_attribution(
    base: ProjectManifest,
    cumulative: ChangeSet,
    writing_changes: tuple[ChangeSet, ...] | list[ChangeSet],
) -> None:
    composed = compose_change_sets(base, writing_changes)
    if (
        composed.base_manifest_digest != cumulative.base_manifest_digest
        or composed.final_manifest_digest != cumulative.final_manifest_digest
        or composed.entries != cumulative.entries
    ):
        raise ValueError("cumulative ChangeSet contains unattributed or mismatched path changes")


class EvidenceManager:
    def __init__(
        self,
        store: V2ProjectStore,
        *,
        stage_id: str | None = None,
        role_instance: RoleInstance | None = None,
        started_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        self.store = store
        self.base_manifest_ref: RecordRef | None = None
        if (stage_id is None) != (role_instance is None):
            raise ValueError("stage_id and role_instance must be supplied together")
        if stage_id is not None and role_instance is not None:
            self.base_manifest_ref = self.begin_stage(
                stage_id,
                role_instance,
                started_at=started_at,
                idempotency_key=idempotency_key,
            )

    def capture_manifest(
        self,
        *,
        created_at: datetime | None = None,
        idempotency_key: str | None = None,
        operation_id: str | None = None,
    ) -> tuple[ProjectManifest, RecordRef]:
        if operation_id is not None:
            journaled = self.store.journaled_record(operation_id, "project_manifest", f"manifest-{operation_id}")
            if journaled is not None:
                manifest = cast(ProjectManifest, journaled)
                current = workspace_manifest(self.store.project, created_at=manifest.created_at, manifest_id=manifest.manifest_id)
                if current.entries != manifest.entries or current.root_digest != manifest.root_digest:
                    raise ValueError("journaled manifest no longer matches the workspace")
                return manifest, self.store.write_immutable(manifest, idempotency_key or operation_id)
        timestamp = created_at or _now(None)
        manifest = workspace_manifest(self.store.project, created_at=timestamp)
        if operation_id is not None:
            manifest = manifest.model_copy(update={"manifest_id": f"manifest-{operation_id}"})
        key = idempotency_key or manifest.manifest_id
        if operation_id is None:
            return manifest, self.store.write_immutable(manifest, key)
        reference = self.store.reference(manifest)
        self.store.commit_records_event(
            operation_id,
            ((manifest, key),),
            f"manifest-capture-{operation_id}",
            {"manifest": reference.model_dump(mode="json"), "type": "manifest_captured"},
            expected_version=0,
        )
        return manifest, reference

    def begin_stage(
        self,
        stage_id: str,
        role_instance: RoleInstance,
        *,
        started_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> RecordRef:
        if role_instance.stage_id != stage_id:
            raise ValueError("stage baseline role does not match stage_id")
        aggregate = f"stage-evidence-{role_instance.role_instance_id}"
        events = self.store.replay_events(aggregate)
        if events:
            if (
                len(events) != 1
                or events[0].payload.get("type") != "stage_started"
                or events[0].payload.get("stage_id") != stage_id
                or events[0].payload.get("role_instance_id") != role_instance.role_instance_id
            ):
                raise ValueError("stage baseline event conflicts with the role instance")
            reference = RecordRef.model_validate(events[0].payload["base_manifest"])
            self.store.resolve(reference)
            self.base_manifest_ref = reference
            return reference
        operation_id = f"stage-start-{role_instance.role_instance_id}"
        journaled = self.store.journaled_record(operation_id, "project_manifest", f"manifest-{operation_id}")
        timestamp = started_at or (cast(ProjectManifest, journaled).created_at if journaled is not None else _now(None))
        manifest = workspace_manifest(
            self.store.project,
            created_at=timestamp,
            manifest_id=f"manifest-{operation_id}",
        )
        manifest_ref = self.store.reference(manifest)
        payload = {
            "base_manifest": manifest_ref.model_dump(mode="json"),
            "role_instance_id": role_instance.role_instance_id,
            "stage_id": stage_id,
            "type": "stage_started",
        }
        self.store.commit_records_event(
            operation_id,
            ((manifest, idempotency_key or f"stage-base-{role_instance.role_instance_id}"),),
            aggregate,
            payload,
            expected_version=0,
        )
        self.base_manifest_ref = manifest_ref
        return manifest_ref

    def refresh_stage(
        self,
        stage_id: str,
        role_instance: RoleInstance,
        *,
        started_at: datetime | None = None,
    ) -> RecordRef:
        """Persist a new read baseline after an upstream correction, retaining the exact role."""
        if role_instance.stage_id != stage_id:
            raise ValueError("stage baseline role does not match stage_id")
        aggregate = f"stage-evidence-{role_instance.role_instance_id}"
        events = self.store.replay_events(aggregate)
        if not events or events[0].payload.get("type") != "stage_started":
            raise ValueError("stage must be started before its evidence baseline can be refreshed")
        sequence = len(events) + 1
        operation_id = f"stage-refresh-{role_instance.role_instance_id}-{sequence}"
        timestamp = started_at or _now(None)
        manifest = workspace_manifest(
            self.store.project,
            created_at=timestamp,
            manifest_id=f"manifest-{operation_id}",
        )
        reference = self.store.reference(manifest)
        self.store.commit_records_event(
            operation_id,
            ((manifest, operation_id),),
            aggregate,
            {
                "base_manifest": reference.model_dump(mode="json"),
                "role_instance_id": role_instance.role_instance_id,
                "stage_id": stage_id,
                "type": "stage_refreshed",
            },
            expected_version=len(events),
        )
        self.base_manifest_ref = reference
        return reference

    def write_artifact(
        self,
        content: bytes,
        evidence_type: EvidenceType,
        producer: ActorRef,
        *,
        created_at: datetime | None = None,
        evidence_id: str | None = None,
    ) -> tuple[EvidenceArtifact, RecordRef]:
        digest = hashlib.sha256(content).hexdigest()
        timestamp = _now(created_at)
        identity = {
            "created_at": timestamp,
            "digest": digest,
            "evidence_type": evidence_type,
            "producer": producer,
        }
        identifier = evidence_id or f"evidence-{canonical_sha256(identity)}"
        path = self.store._contained("evidence", f"{identifier}.bin")
        if self.store._path_exists(path):
            if self.store._read_bytes(path) != content:
                raise ValueError(f"evidence artifact conflict for {identifier}")
        else:
            self.store._write_projection("evidence", f"{identifier}.bin", content, create_only=True)
        relative = path.relative_to(self.store.project).as_posix()
        artifact = EvidenceArtifact(
            schema_version="2.0",
            kind="evidence_artifact",
            evidence_id=identifier,
            evidence_type=evidence_type,
            path=relative,
            digest=digest,
            size_bytes=len(content),
            producer=producer,
            created_at=timestamp,
        )
        return artifact, self.store.write_immutable(artifact, identifier)

    def resolve_artifact(self, reference: RecordRef) -> EvidenceArtifact:
        artifact = self.store.resolve(reference)
        if not isinstance(artifact, EvidenceArtifact) or self.store.reference(artifact) != reference:
            raise ValueError("evidence reference does not resolve to its metadata record")
        expected = f".codexteam/v2/evidence/{artifact.evidence_id}.bin"
        if artifact.path != expected:
            raise CorruptStore("evidence metadata path does not match its evidence ID")
        try:
            content = self.store._read_projection("evidence", f"{artifact.evidence_id}.bin")
        except FileNotFoundError as exc:
            raise CorruptStore(f"missing evidence blob for {artifact.evidence_id}") from exc
        if len(content) != artifact.size_bytes or hashlib.sha256(content).hexdigest() != artifact.digest:
            raise CorruptStore(f"evidence blob integrity mismatch for {artifact.evidence_id}")
        return artifact

    def process_candidate(
        self,
        report: CandidateReport,
        *,
        role_instance: RoleInstance,
        assignment: Assignment,
        work_item: WorkItem,
        pipeline_revision: PipelineRevision,
        context_pack: ContextPack,
        base_manifest: ProjectManifest,
        final_manifest: ProjectManifest | None = None,
        created_at: datetime | None = None,
    ) -> StageCandidate:
        baseline_events = self.store.replay_events(f"stage-evidence-{role_instance.role_instance_id}")
        if (
            not baseline_events
            or baseline_events[0].payload.get("type") != "stage_started"
            or any(event.payload.get("type") not in {"stage_started", "stage_refreshed"} for event in baseline_events)
        ):
            raise ValueError("candidate stage has no valid persisted stage baseline")
        pinned_base_ref = RecordRef.model_validate(baseline_events[-1].payload["base_manifest"])
        pinned_base = cast(ProjectManifest, self.store.resolve(pinned_base_ref))
        if pinned_base != base_manifest or self.store.reference(base_manifest) != pinned_base_ref:
            raise ValueError("candidate base manifest does not match the stage-start pin")
        final = final_manifest or workspace_manifest(self.store.project, created_at=created_at)
        derived = derive_change_set(base_manifest, final, created_at=created_at)
        expected = {
            "work_item": self.store.reference(work_item),
            "pipeline_revision": self.store.reference(pipeline_revision),
            "assignment": self.store.reference(assignment),
            "role_instance": self.store.reference(role_instance),
            "context_pack": self.store.reference(context_pack),
        }
        for field, reference in expected.items():
            if getattr(report, field) != reference:
                raise ValueError(f"candidate {field} does not match the resolved record")
        if assignment.work_item != expected["work_item"] or assignment.stage != report.stage:
            raise ValueError("candidate assignment does not match the work item and stage")
        if context_pack.assignment != expected["assignment"]:
            raise ValueError("candidate ContextPack does not match the assignment")
        stage = next((item for item in pipeline_revision.stages if item.stage_id == report.stage_id), None)
        if stage is None or stage.stage != report.stage or pipeline_stage_digest(stage) != report.stage_spec_digest:
            raise ValueError("candidate stage does not match the pipeline revision")
        if (
            role_instance.assignment != expected["assignment"]
            or role_instance.pipeline_revision != expected["pipeline_revision"]
            or role_instance.stage_id != report.stage_id
            or role_instance.stage_spec_digest != report.stage_spec_digest
            or role_instance.attempt_id != report.attempt_id
        ):
            raise ValueError("candidate does not match its pinned RoleInstance")
        criterion_ids = tuple(item.id for item in work_item.acceptance_criteria)
        if set(report.criterion_ids) != set(criterion_ids):
            raise ValueError("candidate criteria do not match the work item")
        criterion_by_id = {item.id: item for item in work_item.acceptance_criteria}
        allowed_dispositions = {
            "implementation": {"claimed_satisfied", "unsatisfied"},
            "verification": {"not_evaluated", "verified", "unsatisfied"},
            "discovery": {"not_evaluated", "unsatisfied"},
            "architecture": {"not_evaluated", "unsatisfied"},
            "ux": {"not_evaluated", "unsatisfied"},
            "assurance": {"not_evaluated", "unsatisfied"},
            "review": {"not_evaluated", "unsatisfied"},
        }[report.stage]
        if any(item.disposition not in allowed_dispositions for item in report.criterion_dispositions):
            raise ValueError(f"{report.stage} candidate uses a stage-inappropriate criterion disposition")
        resolved_evidence: dict[RecordRef, EvidenceArtifact] = {}
        for reference in report.evidence:
            artifact = self.resolve_artifact(reference)
            resolved_evidence[reference] = artifact
        for disposition in report.criterion_dispositions:
            actual_types = set()
            for reference in disposition.evidence:
                if reference not in resolved_evidence:
                    raise ValueError("criterion evidence must be included in candidate evidence")
                artifact = resolved_evidence.get(reference)
                if artifact is None:
                    artifact = self.resolve_artifact(reference)
                actual_types.add(artifact.evidence_type)
            if actual_types != set(disposition.evidence_types):
                raise ValueError("criterion declared evidence types do not match resolved evidence")
            required = set(criterion_by_id[disposition.criterion_id].required_evidence_types)
            if disposition.disposition == "verified" and not required <= actual_types:
                raise ValueError("criterion evidence does not satisfy required evidence types")
        read_only = report.stage in {"discovery", "assurance", "review"}
        if read_only and derived.entries:
            raise ValueError(f"read-only {report.stage} candidate changed the workspace")
        if any(
            not any(project_path_pattern_matches(pattern, entry.path) for pattern in assignment.scope)
            for entry in derived.entries
        ):
            raise ValueError("candidate ChangeSet contains a path outside assignment scope")
        if any(
            not any(project_path_pattern_matches(pattern, entry.path) for pattern in work_item.approved_scope)
            for entry in derived.entries
        ):
            raise ValueError("candidate ChangeSet contains a path outside WorkItem approved scope")
        change_ref = self.store.write_immutable(derived, derived.change_set_id)
        if report.change_set is not None and report.change_set != change_ref:
            raise ValueError("candidate change_set does not match the derived workspace change")
        if report.stage in {"architecture", "ux", "implementation", "verification"} and report.change_set != change_ref:
            raise ValueError("writing-stage candidate must reference the derived ChangeSet")
        report_ref = self.store.write_immutable(report, report.candidate_report_id)
        aggregate = f"candidate-history-{report.work_item.record_id}"
        with self.store.run_lock(aggregate):
            events = self.store.replay_events(aggregate, _locked=True)
            payload = {
                "assignment": expected["assignment"].model_dump(mode="json"),
                "base_manifest": pinned_base_ref.model_dump(mode="json"),
                "candidate": report_ref.model_dump(mode="json"),
                "change_set": change_ref.model_dump(mode="json"),
                "context_pack": expected["context_pack"].model_dump(mode="json"),
                "final_manifest": self.store.reference(final).model_dump(mode="json"),
                "pipeline_revision": expected["pipeline_revision"].model_dump(mode="json"),
                "role_instance": expected["role_instance"].model_dump(mode="json"),
                "stage": report.stage,
                "stage_id": report.stage_id,
                "type": "candidate_processed",
                "work_item": expected["work_item"].model_dump(mode="json"),
            }
            matching = [
                event for event in events
                if event.payload.get("candidate") == payload["candidate"]
            ]
            if matching:
                if len(matching) != 1 or matching[0].payload != payload:
                    raise ValueError("candidate history conflicts with the immutable candidate")
            else:
                self.store._append_event_internal(
                    aggregate,
                    payload,
                    expected_version=len(events),
                    _locked=True,
                )
        return StageCandidate(report, report_ref, derived, change_ref, base_manifest, final)


def evidence_is_fresh(
    candidate: CandidateReport,
    change_set: ChangeSet,
    workspace: ProjectManifest,
    *,
    candidate_ref: RecordRef | None = None,
) -> bool:
    return (
        candidate.change_set is not None
        and candidate.change_set.digest == canonical_sha256(change_set)
        and candidate.change_set.record_id == change_set.change_set_id
        and change_set.final_manifest_digest == workspace.root_digest
        and (candidate_ref is None or candidate_ref.digest == canonical_sha256(candidate))
    )


__all__ = [
    "EvidenceManager",
    "StageCandidate",
    "build_workspace_manifest",
    "derive_change_set",
    "compose_change_sets",
    "evidence_is_fresh",
    "workspace_manifest",
    "validate_change_attribution",
]
