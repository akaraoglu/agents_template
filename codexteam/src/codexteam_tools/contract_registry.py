from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


ARTIFACT_REPORT = "artifact-report-v1"
DEFAULT_DRAFT_FORMAT = ARTIFACT_REPORT
DRAFT_FORMATS = (ARTIFACT_REPORT,)


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
})


def get_contract(contract_id: str) -> ContractEntry:
    try:
        return CONTRACT_REGISTRY[contract_id]
    except KeyError as exc:
        raise ValueError(f"unknown CodexTeam contract: {contract_id}") from exc
