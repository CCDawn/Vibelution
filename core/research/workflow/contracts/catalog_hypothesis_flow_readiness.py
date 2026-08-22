"""Auditable DEV readiness contract for the catalog hypothesis flow.

``PlatformFlowReadinessReport`` answers whether the existing platform fixture
surface can run.  This contract sits one level above it and answers whether
the catalog hypothesis flow has all five protocol prerequisites needed to
enter the DEV G1 pilot.  It deliberately never grants a real campaign.

The report is immutable, serializes to a deterministic shape, and points at
the first failing gate's concrete repair action.  This mirrors established
deployment protection patterns (a protected environment has explicit checks
and reviewers) without introducing another approval or lifecycle store.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._canonical import sha256_hex
from ._validation import (
    ContractValidationError,
    require_list,
    require_sha256,
    require_text,
)

CATALOG_HYPOTHESIS_FLOW_REPORT_KIND = "CatalogHypothesisFlowReadinessReport"
CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION = 1
CATALOG_HYPOTHESIS_FLOW_MODE = "dev"
CATALOG_HYPOTHESIS_FLOW_READY_STATUS = "READY"
CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS = "NOT_READY"
CATALOG_HYPOTHESIS_FLOW_BLOCKED_STATUS = "BLOCKED"
CATALOG_HYPOTHESIS_FLOW_G1_ACTION = "enter_g1_pilot"

# The ordering is part of the contract: the first failed prerequisite owns the
# next action, so users get a deterministic repair target instead of a generic
# "readiness failed" message.
CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "six_role_prerequisites",
        "六角色前置",
        "repair_catalog_hypothesis_six_role_prerequisites",
    ),
    (
        "schema_batch_export",
        "Schema/批处理/导出",
        "repair_catalog_hypothesis_schema_batch_export",
    ),
    (
        "question_model_receipts",
        "Qwen 题目级调用回执",
        "repair_catalog_hypothesis_question_model_receipts",
    ),
    (
        "api_frontend_r0_r1",
        "API/前端与 R0/R1",
        "repair_catalog_hypothesis_api_frontend_r0_r1",
    ),
    (
        "human_authorization",
        "人工授权",
        "repair_catalog_hypothesis_human_authorization",
    ),
)

CATALOG_HYPOTHESIS_FLOW_GATE_IDS: tuple[str, ...] = tuple(
    item[0] for item in CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS
)
CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTIONS: dict[str, str] = {
    gate_id: repair_action
    for gate_id, _label, repair_action in CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS
}


def _gate_status(value: Any) -> str:
    status = str(value or "").strip().upper()
    if status not in {"PASS", "FAIL", "BLOCKED"}:
        raise ContractValidationError(
            "catalog hypothesis readiness gate status must be PASS, FAIL, or BLOCKED"
        )
    return status


def _content_payload(
    *,
    schema_version: int,
    report_kind: str,
    mode: str,
    status: str,
    real_campaign_allowed: bool,
    g1_pilot_allowed: bool,
    gates: Sequence[Mapping[str, Any]],
    next_legal_action: str,
) -> dict[str, Any]:
    """Return hash input without generated timestamps or the hash itself."""

    return {
        "schemaVersion": schema_version,
        "reportKind": report_kind,
        "mode": mode,
        "status": status,
        "realCampaignAllowed": real_campaign_allowed,
        "g1PilotAllowed": g1_pilot_allowed,
        "gates": [dict(item) for item in gates],
        "nextLegalAction": next_legal_action,
    }


@dataclass(frozen=True, slots=True)
class CatalogHypothesisFlowReadinessReport:
    """Immutable five-gate DEV readiness report.

    ``humanAuthorizationRequired`` remains true even when the DEV pilot gate
    is satisfied.  ``g1PilotAllowed`` only unlocks the bounded fixture pilot;
    ``realCampaignAllowed`` is permanently false and is validated as such.
    """

    schemaVersion: int
    reportKind: str
    status: str
    mode: str
    realCampaignAllowed: bool
    humanAuthorizationRequired: bool
    g1PilotAllowed: bool
    gates: tuple[dict[str, Any], ...]
    nextLegalAction: str
    generatedAt: str
    reportHash: str

    def __post_init__(self) -> None:
        if self.schemaVersion != CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION:
            raise ContractValidationError("unsupported catalog hypothesis readiness schemaVersion")
        if self.reportKind != CATALOG_HYPOTHESIS_FLOW_REPORT_KIND:
            raise ContractValidationError("invalid catalog hypothesis readiness reportKind")
        if self.mode != CATALOG_HYPOTHESIS_FLOW_MODE:
            raise ContractValidationError("CatalogHypothesisFlowReadinessReport is DEV-only")
        if self.status not in {
            CATALOG_HYPOTHESIS_FLOW_READY_STATUS,
            CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS,
            CATALOG_HYPOTHESIS_FLOW_BLOCKED_STATUS,
        }:
            raise ContractValidationError("invalid catalog hypothesis readiness status")
        if self.realCampaignAllowed is not False:
            raise ContractValidationError(
                "CatalogHypothesisFlowReadinessReport can never authorize a real campaign"
            )
        if self.humanAuthorizationRequired is not True:
            raise ContractValidationError("humanAuthorizationRequired must remain true")
        if not self.gates or len(self.gates) != len(CATALOG_HYPOTHESIS_FLOW_GATE_IDS):
            raise ContractValidationError("catalog hypothesis readiness requires exactly five gates")
        gate_ids: list[str] = []
        for gate in self.gates:
            gate_id = require_text(gate, "gateId")
            if gate_id not in CATALOG_HYPOTHESIS_FLOW_GATE_IDS:
                raise ContractValidationError(f"unknown catalog hypothesis readiness gate: {gate_id}")
            if gate_id in gate_ids:
                raise ContractValidationError(f"duplicate catalog hypothesis readiness gate: {gate_id}")
            _gate_status(gate.get("status"))
            repair_action = str(gate.get("repairAction") or "").strip()
            if repair_action != CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTIONS[gate_id]:
                raise ContractValidationError(f"repair action drifted for gate: {gate_id}")
            detail = str(gate.get("detail") or "").strip()
            if not detail:
                raise ContractValidationError(f"detail is required for gate: {gate_id}")
            gate_ids.append(gate_id)
        if tuple(gate_ids) != CATALOG_HYPOTHESIS_FLOW_GATE_IDS:
            raise ContractValidationError("catalog hypothesis readiness gates must use canonical order")

        failing = next(
            (gate for gate in self.gates if gate["status"] in {"FAIL", "BLOCKED"}),
            None,
        )
        if failing is None:
            if self.status != CATALOG_HYPOTHESIS_FLOW_READY_STATUS:
                raise ContractValidationError("all PASS gates require READY status")
            if self.g1PilotAllowed is not True:
                raise ContractValidationError("all PASS gates require g1PilotAllowed")
            if self.nextLegalAction != CATALOG_HYPOTHESIS_FLOW_G1_ACTION:
                raise ContractValidationError("all PASS gates must enter the G1 pilot")
        else:
            if self.status == CATALOG_HYPOTHESIS_FLOW_READY_STATUS:
                raise ContractValidationError("a failed gate cannot produce READY status")
            if self.g1PilotAllowed is not False:
                raise ContractValidationError("a failed gate must block the G1 pilot")
            if self.nextLegalAction != failing["repairAction"]:
                raise ContractValidationError(
                    "nextLegalAction must target the first failing gate repair action"
                )
        expected_hash = sha256_hex(
            _content_payload(
                schema_version=self.schemaVersion,
                report_kind=self.reportKind,
                mode=self.mode,
                status=self.status,
                real_campaign_allowed=self.realCampaignAllowed,
                g1_pilot_allowed=self.g1PilotAllowed,
                gates=self.gates,
                next_legal_action=self.nextLegalAction,
            )
        )
        if self.reportHash != expected_hash:
            raise ContractValidationError("catalog hypothesis readiness reportHash is invalid")
        require_text({"generatedAt": self.generatedAt}, "generatedAt")

    @classmethod
    def build(
        cls,
        *,
        gates: Sequence[Mapping[str, Any]],
        generated_at: str,
        human_authorization_required: bool = True,
    ) -> CatalogHypothesisFlowReadinessReport:
        if human_authorization_required is not True:
            raise ContractValidationError("human_authorization_required must remain true")
        normalized: list[dict[str, Any]] = []
        for expected_id, label, repair_action in CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS:
            raw = next((item for item in gates if str(item.get("gateId") or "") == expected_id), None)
            if raw is None:
                raise ContractValidationError(f"missing catalog hypothesis readiness gate: {expected_id}")
            normalized.append(
                {
                    "gateId": expected_id,
                    "label": str(raw.get("label") or label),
                    "status": _gate_status(raw.get("status")),
                    "detail": str(raw.get("detail") or "").strip(),
                    "repairAction": repair_action,
                }
            )
        failing = next((gate for gate in normalized if gate["status"] in {"FAIL", "BLOCKED"}), None)
        status = CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS if failing else CATALOG_HYPOTHESIS_FLOW_READY_STATUS
        next_action = failing["repairAction"] if failing else CATALOG_HYPOTHESIS_FLOW_G1_ACTION
        g1_allowed = failing is None
        content = _content_payload(
            schema_version=CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION,
            report_kind=CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
            mode=CATALOG_HYPOTHESIS_FLOW_MODE,
            status=status,
            real_campaign_allowed=False,
            g1_pilot_allowed=g1_allowed,
            gates=normalized,
            next_legal_action=next_action,
        )
        return cls(
            schemaVersion=CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION,
            reportKind=CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
            status=status,
            mode=CATALOG_HYPOTHESIS_FLOW_MODE,
            realCampaignAllowed=False,
            humanAuthorizationRequired=True,
            g1PilotAllowed=g1_allowed,
            gates=tuple(normalized),
            nextLegalAction=next_action,
            generatedAt=str(generated_at),
            reportHash=sha256_hex(content),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CatalogHypothesisFlowReadinessReport:
        gates_raw = require_list(payload, "gates", non_empty=True)
        gates: list[dict[str, Any]] = []
        for raw in gates_raw:
            if not isinstance(raw, Mapping):
                raise ContractValidationError("catalog hypothesis readiness gates must be objects")
            gates.append(dict(raw))
        return cls(
            schemaVersion=int(payload.get("schemaVersion") or 0),
            reportKind=require_text(payload, "reportKind"),
            status=require_text(payload, "status"),
            mode=require_text(payload, "mode").lower(),
            realCampaignAllowed=payload.get("realCampaignAllowed") is True,
            humanAuthorizationRequired=payload.get("humanAuthorizationRequired") is True,
            g1PilotAllowed=payload.get("g1PilotAllowed") is True,
            gates=tuple(gates),
            nextLegalAction=require_text(payload, "nextLegalAction"),
            generatedAt=require_text(payload, "generatedAt"),
            reportHash=require_sha256(payload, "reportHash"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "reportKind": self.reportKind,
            "status": self.status,
            "mode": self.mode,
            "realCampaignAllowed": self.realCampaignAllowed,
            "humanAuthorizationRequired": self.humanAuthorizationRequired,
            "g1PilotAllowed": self.g1PilotAllowed,
            "gates": [dict(item) for item in self.gates],
            "nextLegalAction": self.nextLegalAction,
            "generatedAt": self.generatedAt,
            "reportHash": self.reportHash,
        }

    # Compatibility aliases make the report safe to pass through existing
    # ``*_payload`` naming used by older workflow contracts.
    from_payload = from_dict
    to_payload = to_dict


__all__ = [
    "CATALOG_HYPOTHESIS_FLOW_BLOCKED_STATUS",
    "CATALOG_HYPOTHESIS_FLOW_G1_ACTION",
    "CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS",
    "CATALOG_HYPOTHESIS_FLOW_GATE_IDS",
    "CATALOG_HYPOTHESIS_FLOW_MODE",
    "CATALOG_HYPOTHESIS_FLOW_NOT_READY_STATUS",
    "CATALOG_HYPOTHESIS_FLOW_READY_STATUS",
    "CATALOG_HYPOTHESIS_FLOW_REPAIR_ACTIONS",
    "CATALOG_HYPOTHESIS_FLOW_REPORT_KIND",
    "CATALOG_HYPOTHESIS_FLOW_SCHEMA_VERSION",
    "CatalogHypothesisFlowReadinessReport",
]
