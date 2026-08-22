"""BUG-7 CatalogHypothesisFlowReadinessReport contract and DEV gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.competition import catalog_hypothesis_flow_ready as ready
from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.catalog_hypothesis_flow_readiness import (
    CATALOG_HYPOTHESIS_FLOW_G1_ACTION,
    CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS,
    CATALOG_HYPOTHESIS_FLOW_REPORT_KIND,
    CatalogHypothesisFlowReadinessReport,
)

ROOT = Path(__file__).resolve().parents[1]


def _platform_pass() -> dict:
    return {
        "reportKind": "ChallengeCupPlatformDevelopmentReadinessReport",
        "status": "READY",
        "mode": "dev",
        "realCampaignAllowed": False,
        "researchAuthorizationRequired": True,
        "sourceCommit": "a" * 40,
        "gates": [
            {"gateId": gate_id, "status": "PASS", "detail": "fixture PASS"}
            for gate_id in ("r0_source_integrity", "r1_clean_clone", "product_projection")
        ],
    }


def _build(*, human_authorized: bool | None = None) -> dict:
    return ready.build_catalog_hypothesis_flow_readiness_report(
        ROOT,
        platform_report=_platform_pass(),
        human_authorized=human_authorized,
    )


def test_all_five_gates_pass_only_enters_g1_pilot() -> None:
    report = _build()
    assert report["reportKind"] == CATALOG_HYPOTHESIS_FLOW_REPORT_KIND
    assert report["mode"] == "dev"
    assert report["realCampaignAllowed"] is False
    assert report["status"] == "READY"
    assert report["g1PilotAllowed"] is True
    assert report["nextLegalAction"] == CATALOG_HYPOTHESIS_FLOW_G1_ACTION
    assert [gate["status"] for gate in report["gates"]] == ["PASS"] * 5


@pytest.mark.parametrize(
    ("gate_id", "repair_action"),
    [(gate_id, repair_action) for gate_id, _label, repair_action in CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS],
)
def test_each_failed_gate_points_to_its_own_repair_action(
    monkeypatch: pytest.MonkeyPatch,
    gate_id: str,
    repair_action: str,
) -> None:
    for current_id, _label, _action in CATALOG_HYPOTHESIS_FLOW_GATE_DEFINITIONS:
        monkeypatch.setattr(
            ready,
            {
                "six_role_prerequisites": "gate_six_role_prerequisites",
                "schema_batch_export": "gate_schema_batch_export",
                "question_model_receipts": "gate_question_model_receipts",
                "api_frontend_r0_r1": "gate_api_frontend_r0_r1",
                "human_authorization": "gate_human_authorization",
            }[current_id],
            lambda *args, current_id=current_id, **kwargs: {
                "gateId": current_id,
                "status": "FAIL" if current_id == gate_id else "PASS",
                "detail": f"{current_id} fixture",
            },
        )
    report = ready.build_catalog_hypothesis_flow_readiness_report(ROOT)
    assert report["status"] == "NOT_READY"
    assert report["g1PilotAllowed"] is False
    assert report["nextLegalAction"] == repair_action
    failed = next(item for item in report["gates"] if item["gateId"] == gate_id)
    assert failed["repairAction"] == repair_action


def test_human_authorization_is_fail_closed_when_explicitly_rejected() -> None:
    report = _build(human_authorized=False)
    assert report["status"] == "NOT_READY"
    assert report["nextLegalAction"] == "repair_catalog_hypothesis_human_authorization"
    assert report["realCampaignAllowed"] is False


def test_formal_mode_is_rejected_before_any_gate_runs() -> None:
    with pytest.raises(ValueError, match="DEV-only"):
        ready.build_catalog_hypothesis_flow_readiness_report(ROOT, mode="formal")


def test_report_round_trip_and_hash_are_stable() -> None:
    report = _build()
    contract = CatalogHypothesisFlowReadinessReport.from_dict(report)
    encoded_a = json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True)
    encoded_b = json.dumps(
        CatalogHypothesisFlowReadinessReport.from_dict(contract.to_dict()).to_dict(),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert contract.reportHash == report["reportHash"]
    assert encoded_a == encoded_b
    tampered = dict(report)
    tampered["nextLegalAction"] = "formal_submission"
    with pytest.raises(ContractValidationError, match="G1 pilot"):
        CatalogHypothesisFlowReadinessReport.from_dict(tampered)
