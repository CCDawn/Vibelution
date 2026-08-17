"""D12 PlatformFlowReady DEV report tests. No real research side effects."""

from __future__ import annotations

from pathlib import Path

from core.research.competition.platform_flow_ready import (
    build_platform_flow_readiness_report,
    gate_adapters,
    gate_catalog_resume,
    gate_model_receipt,
    gate_multimodal,
    gate_program_hash,
    overall_status,
)

ROOT = Path(__file__).resolve().parents[1]


def test_program_hash_and_dev_control_gates_pass() -> None:
    assert gate_program_hash()["status"] == "PASS"
    assert gate_adapters()["status"] == "PASS"
    assert gate_catalog_resume()["status"] == "PASS"
    assert gate_model_receipt()["status"] == "PASS"
    assert gate_multimodal()["status"] == "PASS"


def test_platform_flow_readiness_report_is_ready_for_dev_control_flow(
    tmp_path: Path,
) -> None:
    report = build_platform_flow_readiness_report(
        ROOT, clone_dest=tmp_path / "clone"
    )
    assert report["reportKind"] == "PlatformFlowReadinessReport"
    assert report["researchAuthorizationRequired"] is True
    assert report["realCampaignAllowed"] is False
    assert overall_status(report["gates"]) == report["status"]
    failed = [item for item in report["gates"] if item["status"] != "PASS"]
    assert failed == [], failed
    assert report["status"] == "READY"
    assert report["nextLegalAction"] == "RESEARCH_AUTHORIZATION_REQUIRED"


def test_overall_status_does_not_promote_failures() -> None:
    assert overall_status([{"status": "PASS"}, {"status": "FAIL"}]) == "NOT_READY"
    assert overall_status([{"status": "PASS"}, {"status": "BLOCKED"}]) == "BLOCKED"
    assert overall_status([{"status": "PASS"}]) == "READY"
