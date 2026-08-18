"""D12 PlatformFlowReady DEV report tests. No real research side effects."""

from __future__ import annotations

from pathlib import Path

from core.research.competition.platform_flow_ready import (
    REPORT_KIND,
    build_platform_flow_readiness_report,
    gate_adapters,
    gate_catalog_resume,
    gate_control_flow_contracts,
    gate_model_receipt,
    gate_multimodal,
    gate_program_hash,
    overall_status,
)
from core.research.competition.source_boundary import R1_PYTEST_TARGETS

ROOT = Path(__file__).resolve().parents[1]


def test_program_hash_and_dev_control_gates_pass() -> None:
    assert gate_program_hash()["status"] == "PASS"
    assert gate_adapters()["status"] == "PASS"
    assert gate_catalog_resume()["status"] == "PASS"
    assert gate_control_flow_contracts(ROOT)["status"] == "PASS"
    assert gate_model_receipt()["status"] == "PASS"
    assert gate_multimodal()["status"] == "PASS"


def test_r1_pytest_targets_exist_and_exclude_this_report() -> None:
    assert "tests/test_platform_flow_ready.py" not in R1_PYTEST_TARGETS
    missing = [path for path in R1_PYTEST_TARGETS if not (ROOT / path).is_file()]
    assert missing == []


def test_skipped_r1_pytest_cannot_be_ready(tmp_path: Path) -> None:
    report = build_platform_flow_readiness_report(
        ROOT,
        clone_dest=tmp_path / "clone",
        require_clean=False,
        run_pytest=False,
    )
    r1 = next(item for item in report["gates"] if item["gateId"] == "r1_clean_clone")
    assert r1["status"] == "BLOCKED"
    assert report["status"] != "READY"
    assert report["reportKind"] == REPORT_KIND


def test_platform_flow_readiness_report_is_ready_for_dev_control_flow(
    tmp_path: Path,
) -> None:
    report = build_platform_flow_readiness_report(
        ROOT,
        clone_dest=tmp_path / "clone",
        require_clean=False,
        run_pytest=True,
    )
    assert report["reportKind"] == REPORT_KIND
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
