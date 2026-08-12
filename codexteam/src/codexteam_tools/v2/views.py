from __future__ import annotations

from collections.abc import Sequence

from .canonical import canonical_sha256
from .models import AssuranceReport, CandidateSeal, VerificationReceipt
from .pipeline_runtime import PipelineRunProjection
from .storage import V2ProjectStore


def _document(title: str, source: object, lines: Sequence[str]) -> bytes:
    digest = canonical_sha256(source)
    body = ["<!-- generated: codexteam-v2; canonical-authority: false -->", f"<!-- source-digest: {digest} -->", "", f"# {title}", "", *lines]
    return ("\n".join(body).rstrip() + "\n").encode("utf-8")


def render_pipeline(projection: PipelineRunProjection) -> bytes:
    lines = ["| Stage | Status | Revision |", "|---|---|---|"]
    lines.extend(f"| `{stage.stage_id}` | {stage.status} | `{stage.pipeline_revision.record_id}` |" for stage in projection.stages)
    return _document("Pipeline", projection, lines)


def render_status(projection: PipelineRunProjection) -> bytes:
    lines = [
        f"- Run: `{projection.run_id}`",
        f"- State revision: {projection.state_revision}",
        f"- Complete: {'yes' if projection.complete else 'no'}",
        f"- Operator required: {'yes' if projection.operator_required else 'no'}",
    ]
    return _document("Status", projection, lines)


def render_assurance(report: AssuranceReport, receipts: Sequence[VerificationReceipt] = ()) -> bytes:
    ordered_receipts = tuple(sorted(receipts, key=lambda item: item.verification_receipt_id))
    lines = ["| Domain | Disposition |", "|---|---|"]
    lines.extend(f"| {item.domain.value} | {item.disposition} |" for item in sorted(report.dispositions, key=lambda value: value.domain.value))
    lines.extend(("", f"Accepted verification receipts: {sum(item.accepted for item in ordered_receipts)}/{len(ordered_receipts)}"))
    return _document("Assurance", {"report": report, "receipts": ordered_receipts}, lines)


def render_candidate(seal: CandidateSeal) -> bytes:
    lines = [
        f"- Seal: `{seal.seal_id}`",
        f"- Project: `{seal.project_id}`",
        f"- Candidate digest: `{seal.candidate_digest}`",
        f"- Pipeline revision: `{seal.pipeline_revision.record_id}`",
        f"- Required stages: {', '.join(f'`{item}`' for item in seal.required_stage_ids)}",
    ]
    return _document("Candidate", seal, lines)


def write_view(store: V2ProjectStore, name: str, content: bytes) -> None:
    path = store._contained("views", f"{name}.md")
    if path.exists() and path.read_bytes() == content:
        return
    store._atomic_replace(path, content)


__all__ = ["render_assurance", "render_candidate", "render_pipeline", "render_status", "write_view"]
