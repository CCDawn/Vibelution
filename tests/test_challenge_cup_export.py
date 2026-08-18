"""D13 delivery toolchain tests. Fixture packs never impersonate a final 125/125."""

from __future__ import annotations

import pytest

from core.research.competition.delivery import (
    build_evidence_index,
    check_pdf_limit,
    export_results,
    validate_submission_projection,
)
from core.research.competition.resources import CATALOG_QUESTION_COUNT

COMPLETE = {
    "approvedQuestionCount": CATALOG_QUESTION_COUNT,
    "r0": "PASS",
    "r1": "PASS",
    "r2": "PASS",
    "r3": "PASS",
    "pendingClaimCount": 0,
    "submissionProjectionFrozen": True,
    "evidenceIndex": [{"path": "offline/receipt.json", "kind": "receipt", "sha256": "A" * 64}],
}


def test_preview_pack_is_not_final_without_125() -> None:
    pack = export_results({"approvedQuestionCount": 1, "r0": "FAIL"}, mode="preview")
    assert pack["status"] == "preview"
    assert pack["final"] is False
    assert pack["blockers"] == []
    assert pack["requiredQuestionCount"] == 125


def test_formal_pack_refuses_incomplete_catalog_and_unfrozen_projection() -> None:
    pack = export_results(
        {
            "approvedQuestionCount": 5,
            "r0": "PASS",
            "r1": "PASS",
            "r2": "PASS",
            "r3": "PASS",
            "pendingClaimCount": 1,
            "submissionProjectionFrozen": False,
        },
        mode="formal",
    )
    assert pack["status"] == "refused"
    assert pack["final"] is False
    assert "catalog_incomplete" in pack["blockers"]
    assert "pending_claims" in pack["blockers"]
    assert "submission_projection_unfrozen" in pack["blockers"]


def test_formal_pack_rejects_preview_r2_r3_exemption() -> None:
    pack = export_results(
        {
            **COMPLETE,
            "r2": "not_required_for_preview",
            "r3": "not_required_for_preview",
        },
        mode="formal",
    )
    assert pack["status"] == "refused"
    assert pack["final"] is False
    assert "r2_not_pass" in pack["blockers"]
    assert "r3_not_pass" in pack["blockers"]


def test_submission_projection_unfrozen_only_allows_preview() -> None:
    report = validate_submission_projection(
        {
            "captured": False,
            "submissionProjectionFrozen": False,
            "officialPageObservedState": "submission_entry_coming_soon",
        }
    )
    assert report["allowedPackMode"] == "preview"
    assert report["blocksFormalPack"] is True


def test_evidence_index_rejects_path_escape() -> None:
    with pytest.raises(ValueError, match="unsafe evidence path"):
        build_evidence_index([{"path": "../secret.json"}])
    index = build_evidence_index(
        [{"path": "offline/receipt.json", "kind": "receipt", "sha256": "A" * 64}]
    )
    assert index["entryCount"] == 1


def test_pdf_limit_is_decoupled_from_generation() -> None:
    ok = check_pdf_limit(1024)
    assert ok["withinLimit"] is True
    assert ok["generatedContent"] is False
    over = check_pdf_limit(ok["limitBytes"] + 1)
    assert over["withinLimit"] is False
