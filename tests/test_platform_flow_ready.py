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
    gate_product_projection,
    gate_program_hash,
    gate_r0,
    overall_status,
)
from core.research.competition import platform_flow_ready as platform_flow_ready_module
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
    assert "tests/test_challenge_cup_platform_controls.py" in R1_PYTEST_TARGETS
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
    # gate_r1 extracts a clean clone and runs the full R1 pytest target list
    # there; tests/test_challenge_cup_platform_controls.py is on that list, so
    # this READY proves the D14A DEV control contract runs inside the clone.
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
    assert len(report["sourceCommit"]) == 40
    assert report["sourceCommit"] == report["gates"][1]["sourceCommit"]
    assert report["nextLegalAction"] == "RESEARCH_AUTHORIZATION_REQUIRED"


def test_readiness_defaults_require_clean_tree() -> None:
    """The report defaults to a clean-source gate so dirty trees never regress to READY."""
    import inspect

    params = inspect.signature(build_platform_flow_readiness_report).parameters
    assert params["require_clean"].default is True
    assert params["run_pytest"].default is True


def test_gate_r0_fails_on_dirty_tree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"

    def fake_evaluate(repo_path, *, policy=None, require_clean=False):
        assert require_clean is True
        return {
            "source_integrity": "FAIL",
            "sourceCommit": "",
            "entryCount": 0,
            "manifest": None,
            "failures": ["working tree is dirty; refuse to freeze a source manifest"],
        }

    monkeypatch.setattr(
        platform_flow_ready_module, "evaluate_source_integrity", fake_evaluate
    )
    gate = gate_r0(repo, require_clean=True)
    assert gate["status"] == "FAIL"
    assert "dirty" in gate["detail"]


def test_overall_status_does_not_promote_failures() -> None:
    assert overall_status([{"status": "PASS"}, {"status": "FAIL"}]) == "NOT_READY"
    assert overall_status([{"status": "PASS"}, {"status": "BLOCKED"}]) == "BLOCKED"
    assert overall_status([{"status": "PASS"}]) == "READY"


def test_gate_product_projection_passes_on_current_repo() -> None:
    gate = gate_product_projection(ROOT)
    assert gate["status"] == "PASS", gate


def test_gate_product_projection_fails_when_dev_markers_missing(tmp_path: Path) -> None:
    panel = (
        tmp_path
        / "web"
        / "src"
        / "routes"
        / "teams"
        / "research-workflow"
        / "ChallengeMvpProgressPanel.tsx"
    )
    panel.parent.mkdir(parents=True)
    panel.write_text("competitionProgramProjection requiredDeepExperiments", encoding="utf-8")
    types = tmp_path / "web" / "src" / "api" / "types" / "challengeCup.ts"
    types.parent.mkdir(parents=True, exist_ok=True)
    types.write_text("CompetitionProgramProjection", encoding="utf-8")
    api = tmp_path / "web" / "src" / "api" / "teamExperiment.ts"
    api.parent.mkdir(parents=True, exist_ok=True)
    api.write_text("export function noDevApi() {}", encoding="utf-8")

    gate = gate_product_projection(tmp_path)
    assert gate["status"] == "FAIL"
    assert "typed DEV API" in gate["detail"]
