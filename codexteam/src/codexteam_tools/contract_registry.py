from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


ARTIFACT_REPORT = "artifact-report-v1"
DEFAULT_DRAFT_FORMAT = ARTIFACT_REPORT
DRAFT_FORMATS = (ARTIFACT_REPORT,)
EVALUATION_CHECKS = (
    "boundary_binding",
    "preparation_binding",
    "evidence_binding",
    "prepared_analysis_binding",
    "evidence_reference_integrity",
    "causal_analysis",
    "evidence_ceiling",
    "authority",
)
_HEX64 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class ContractEntry:
    contract_id: str
    version: str
    encoding: str
    schema_path: str | None
    validator_symbol: str
    unknown_fields: str
    responsibility: str


CONTRACT_REGISTRY: Mapping[str, ContractEntry] = MappingProxyType({
    "handoff": ContractEntry(
        "handoff", "1.0", "json", "schemas/handoff.json",
        "codexteam_tools.contracts.validate_handoff", "strict-root",
        "Launch-time task and role assignment envelope.",
    ),
    ARTIFACT_REPORT: ContractEntry(
        ARTIFACT_REPORT, "1", "json", None,
        "codexteam_tools.contracts.validate_artifact_report", "permissive",
        "Worker-owned artifact report sealed deterministically after acceptance.",
    ),
    "result": ContractEntry(
        "result", "1.0", "json", "schemas/result.json",
        "codexteam_tools.contracts.validate_result", "additive",
        "Final worker artifact persisted once per attempt.",
    ),
    "session": ContractEntry(
        "session", "1.0", "json", "schemas/session.json",
        "codexteam_tools.contracts.validate_session", "strict",
        "Private resumability and immutable attempt-pin metadata.",
    ),
    "role-policy": ContractEntry(
        "role-policy", "1.0", "toml-or-json", "schemas/role-policy.json",
        "codexteam_tools.roles.validate_role_policy_contract", "strict",
        "Canonical role identity, permissions, defaults, and guidance policy.",
    ),
    "gate-record": ContractEntry(
        "gate-record", "1.0", "json", "schemas/gate-record.json",
        "codexteam_tools.test_gates.validate_gate_record", "strict",
        "Rolling Development or Integration Gate execution record.",
    ),
    "execution-spec": ContractEntry(
        "execution-spec", "1.0", "json", "schemas/execution-spec.json",
        "codexteam_tools.execution_spec.validate_execution_spec", "strict",
        "Immutable supporting execution identity for one attempt.",
    ),
    "agent-spec": ContractEntry(
        "agent-spec", "1.0", "toml", "schemas/agent-spec.json",
        "codexteam_tools.agent_specs.agent_spec_from_mapping", "strict",
        "Technical specialization overlay bounded by one protocol role.",
    ),
    "milestone-retrospective": ContractEntry(
        "milestone-retrospective", "1.0", "json",
        "schemas/milestone-retrospective.json",
        "codexteam_tools.milestone_retrospective.validate_retrospective", "strict",
        "Evidence-backed analysis of one verified milestone commit.",
    ),
    "milestone-retrospective-evaluation": ContractEntry(
        "milestone-retrospective-evaluation", "1.0", "json",
        "schemas/milestone-retrospective-evaluation.json",
        "codexteam_tools.contract_registry.validate_milestone_retrospective_evaluation",
        "strict",
        "Prepared-packet-bound evaluator report with no task or implementation authority.",
    ),
    "improvement-proposal": ContractEntry(
        "improvement-proposal", "1.0", "json",
        "schemas/improvement-proposal.json",
        "codexteam_tools.milestone_retrospective.validate_proposal", "strict",
        "Qualified improvement recorded as Proposed without execution authority.",
    ),
    "improvement-disposition": ContractEntry(
        "improvement-disposition", "1.0", "json",
        "schemas/improvement-disposition.json",
        "codexteam_tools.milestone_retrospective.validate_disposition", "strict",
        "Immutable human decision granting at most planning approval.",
    ),
})


def get_contract(contract_id: str) -> ContractEntry:
    try:
        return CONTRACT_REGISTRY[contract_id]
    except KeyError as exc:
        raise ValueError(f"unknown CodexTeam contract: {contract_id}") from exc


def validate_milestone_retrospective_evaluation(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "boundary_id", "boundary_digest", "preparation_digest",
        "evidence_digest", "prepared_analysis_digest", "agent_spec_id",
        "agent_spec_version", "agent_spec_digest", "profile", "verdict",
        "checks", "observation_assessments", "investigations", "proposals",
        "creates_task", "grants_implementation_authority",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("evaluation fields do not match the strict contract")
    if value["schema_version"] != "1.0":
        raise ValueError("evaluation schema_version must be '1.0'")
    if not isinstance(value["boundary_id"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value["boundary_id"]
    ):
        raise ValueError("evaluation boundary_id is invalid")
    for field in (
        "boundary_digest", "preparation_digest", "evidence_digest",
        "prepared_analysis_digest", "agent_spec_digest",
    ):
        if not isinstance(value[field], str) or not _HEX64.fullmatch(value[field]):
            raise ValueError(f"evaluation {field} is invalid")
    if value["agent_spec_id"] != "agent-evaluator" or value["agent_spec_version"] != "1.0":
        raise ValueError("evaluation AgentSpec identity is invalid")
    if not isinstance(value["profile"], str) or not re.fullmatch(
        r"codex/[a-z0-9][a-z0-9.-]{0,99}", value["profile"]
    ):
        raise ValueError("evaluation profile is invalid")
    if value["verdict"] not in {"ACCEPT", "REVISE", "BLOCKED"}:
        raise ValueError("evaluation verdict is invalid")
    checks = value["checks"]
    if not isinstance(checks, dict) or set(checks) != set(EVALUATION_CHECKS):
        raise ValueError("evaluation check names do not match the strict contract")
    statuses = []
    for name, check in checks.items():
        if not isinstance(check, dict) or set(check) != {"status", "detail"}:
            raise ValueError(f"evaluation check {name} is invalid")
        if check["status"] not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError(f"evaluation check {name} status is invalid")
        _evaluation_text(check["detail"], f"check {name} detail")
        statuses.append(check["status"])
    if value["verdict"] == "ACCEPT" and any(status != "PASS" for status in statuses):
        raise ValueError("ACCEPT evaluation requires all checks to pass")
    if value["verdict"] == "REVISE" and "FAIL" not in statuses:
        raise ValueError("REVISE evaluation requires a failed check")
    if value["verdict"] == "BLOCKED" and "BLOCKED" not in statuses:
        raise ValueError("BLOCKED evaluation requires a blocked check")
    if value["creates_task"] is not False or value["grants_implementation_authority"] is not False:
        raise ValueError("evaluation cannot create a task or grant implementation authority")

    assessments = _evaluation_collection(value["observation_assessments"], "assessments")
    actions: dict[str, tuple[str, str]] = {}
    for assessment in assessments:
        required = {
            "observation_id", "evidence_ceiling", "classification", "facts",
            "hypotheses", "alternatives", "discriminator", "action", "rationale",
            "evidence_refs",
        }
        if not isinstance(assessment, dict) or set(assessment) != required:
            raise ValueError("evaluation assessment fields are invalid")
        identifier = _evaluation_id(assessment["observation_id"], "observation ID")
        if identifier in actions:
            raise ValueError("evaluation contains duplicate observation assessments")
        allowed = {
            "E1": {"NO_CHANGE", "OBSERVE"},
            "E2": {"NO_CHANGE", "INVESTIGATE"},
            "E3": {"NO_CHANGE", "INVESTIGATE", "PROPOSE"},
        }
        ceiling, action = assessment["evidence_ceiling"], assessment["action"]
        if ceiling not in allowed or action not in allowed[ceiling]:
            raise ValueError("evaluation action exceeds its evidence ceiling")
        if assessment["classification"] not in {
            "AVOIDABLE_FRICTION", "NATURAL_COMPLEXITY", "INSUFFICIENT_EVIDENCE",
            "UNSUPPORTED",
        }:
            raise ValueError("evaluation assessment classification is invalid")
        _evaluation_texts(assessment["alternatives"], "alternatives", minimum=1, maximum=20)
        _evaluation_text(assessment["discriminator"], "discriminator")
        _evaluation_text(assessment["rationale"], "rationale")
        _evaluation_refs(assessment["evidence_refs"])
        _evaluation_texts(assessment["facts"], "facts", minimum=1, maximum=50)
        _evaluation_texts(assessment["hypotheses"], "hypotheses", minimum=1, maximum=20)
        actions[identifier] = (ceiling, action)

    investigations = _evaluation_collection(value["investigations"], "investigations")
    investigated: set[str] = set()
    investigation_ids: set[str] = set()
    for investigation in investigations:
        required = {
            "investigation_id", "observation_ids", "question", "discriminator",
            "evidence_needed", "evidence_refs",
        }
        if not isinstance(investigation, dict) or set(investigation) != required:
            raise ValueError("evaluation investigation fields are invalid")
        investigation_id = _evaluation_id(investigation["investigation_id"], "investigation ID")
        if investigation_id in investigation_ids:
            raise ValueError("evaluation contains duplicate investigation IDs")
        investigation_ids.add(investigation_id)
        observation_ids = _evaluation_ids(investigation["observation_ids"])
        if not set(observation_ids) <= set(actions):
            raise ValueError("investigation references an unknown observation")
        investigated.update(observation_ids)
        _evaluation_text(investigation["question"], "investigation question")
        _evaluation_text(investigation["discriminator"], "investigation discriminator")
        _evaluation_texts(investigation["evidence_needed"], "evidence needed", minimum=1, maximum=20)
        _evaluation_refs(investigation["evidence_refs"])

    proposals = _evaluation_collection(value["proposals"], "proposals")
    proposed: set[str] = set()
    proposal_ids: set[str] = set()
    for proposal in proposals:
        required = {
            "proposal_id", "observation_ids", "target", "mechanism", "alternatives",
            "validation_cases", "rollback", "evidence_refs", "creates_task",
            "grants_implementation_authority",
        }
        if not isinstance(proposal, dict) or set(proposal) != required:
            raise ValueError("evaluation proposal fields are invalid")
        proposal_id = _evaluation_id(proposal["proposal_id"], "proposal ID")
        if proposal_id in proposal_ids:
            raise ValueError("evaluation contains duplicate proposal IDs")
        proposal_ids.add(proposal_id)
        observation_ids = _evaluation_ids(proposal["observation_ids"])
        if any(actions.get(item) != ("E3", "PROPOSE") for item in observation_ids):
            raise ValueError("proposal requires referenced E3 PROPOSE assessments")
        proposed.update(observation_ids)
        _evaluation_text(proposal["target"], "proposal target")
        _evaluation_text(proposal["mechanism"], "proposal mechanism")
        _evaluation_texts(proposal["alternatives"], "proposal alternatives", minimum=1, maximum=20)
        _evaluation_texts(
            proposal["validation_cases"], "validation cases", minimum=1, maximum=20
        )
        _evaluation_text(proposal["rollback"], "proposal rollback")
        _evaluation_refs(proposal["evidence_refs"])
        if proposal["creates_task"] is not False or proposal["grants_implementation_authority"] is not False:
            raise ValueError("evaluation proposal cannot create a task or grant implementation authority")
    for identifier, (_, action) in actions.items():
        if action == "INVESTIGATE" and identifier not in investigated:
            raise ValueError("INVESTIGATE action requires an investigation")
        if action == "PROPOSE" and identifier not in proposed:
            raise ValueError("PROPOSE action requires an E3 proposal")
        if action != "INVESTIGATE" and identifier in investigated:
            raise ValueError("investigation requires an INVESTIGATE assessment")
        if action != "PROPOSE" and identifier in proposed:
            raise ValueError("proposal requires a PROPOSE assessment")
    if len(investigated) != sum(
        len(item["observation_ids"]) for item in investigations
    ):
        raise ValueError("each investigated observation requires one investigation")
    if len(proposed) != sum(len(item["observation_ids"]) for item in proposals):
        raise ValueError("each proposed observation requires one proposal")
    for assessment in assessments:
        classification = assessment["classification"]
        action = assessment["action"]
        if action == "PROPOSE" and classification != "AVOIDABLE_FRICTION":
            raise ValueError("PROPOSE requires AVOIDABLE_FRICTION classification")
        if action == "INVESTIGATE" and classification != "INSUFFICIENT_EVIDENCE":
            raise ValueError("INVESTIGATE requires INSUFFICIENT_EVIDENCE classification")
    return value


def _evaluation_collection(
    value: Any, label: str, *, minimum: int = 0, maximum: int = 999
) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"evaluation {label} are invalid")
    return value


def _evaluation_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", value):
        raise ValueError(f"evaluation {label} is invalid")
    return value


def _evaluation_ids(value: Any) -> tuple[str, ...]:
    items = _evaluation_collection(value, "observation IDs", minimum=1, maximum=50)
    result = tuple(_evaluation_id(item, "observation ID") for item in items)
    if len(result) != len(set(result)):
        raise ValueError("evaluation observation IDs contain duplicates")
    return result


def _evaluation_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 2_000
        or any(character in value for character in ("\x00", "\r", "\n"))
        or "<!--" in value
        or "-->" in value
    ):
        raise ValueError(f"evaluation {label} is invalid")
    return value


def _evaluation_texts(
    value: Any, label: str, *, minimum: int, maximum: int
) -> tuple[str, ...]:
    items = _evaluation_collection(value, label, minimum=minimum, maximum=maximum)
    result = tuple(_evaluation_text(item, label) for item in items)
    if len(result) != len(set(result)):
        raise ValueError(f"evaluation {label} contain duplicates")
    return result


def _evaluation_ref(value: Any) -> str:
    if (
        not isinstance(value, str) or not value.strip() or len(value) > 500
        or value.startswith("/") or "\\" in value or ".." in value.split("/")
        or any(character in value for character in ("\x00", "\r", "\n"))
        or "<!--" in value or "-->" in value
        or "codexteam-improvement:" in value.casefold()
    ):
        raise ValueError("evaluation evidence reference is unsafe")
    return value


def _evaluation_refs(value: Any) -> tuple[str, ...]:
    items = _evaluation_collection(
        value, "evidence references", minimum=1, maximum=50
    )
    result = tuple(_evaluation_ref(item) for item in items)
    if len(result) != len(set(result)):
        raise ValueError("evaluation evidence references contain duplicates")
    return result
