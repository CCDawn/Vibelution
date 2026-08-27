"""Writeback boundary normalizes fetch-attempt-shaped evidenceRefs into attempts."""

from __future__ import annotations

from core.web.services.team_workflow.source_collection.writeback_materialize import (
    _merge_source_collection_stage_writeback_evidence_fetch_attempts,
)


def _ref(candidate_id: str, status: str, **extra):
    return {
        "candidateId": candidate_id,
        "locator": f"https://example.org/{candidate_id}",
        "status": status,
        "toolName": "web_fetch_tool",
        **extra,
    }


def test_attempt_shaped_refs_replace_stale_and_extend_attempts() -> None:
    payload = {
        "evidenceFetchAttempts": [
            {
                "candidateId": "c1",
                "locator": "https://example.org/c1",
                "status": "failed",
                "toolName": "web_fetch_tool",
                "failureCode": "tool_unavailable",
            }
        ]
    }
    merged = _merge_source_collection_stage_writeback_evidence_fetch_attempts(
        payload,
        [
            _ref("c1", "fetched"),
            _ref("c2", "failed", failureCode="http_403"),
        ],
    )
    by_id = {item["candidateId"]: item for item in merged["evidenceFetchAttempts"]}
    assert by_id["c1"]["status"] == "fetched"
    assert "failureCode" not in by_id["c1"]
    assert by_id["c2"]["status"] == "failed"
    assert by_id["c2"]["failureCode"] == "http_403"


def test_non_attempt_refs_are_ignored() -> None:
    merged = _merge_source_collection_stage_writeback_evidence_fetch_attempts(
        {},
        [
            {"candidateId": "c3", "locator": "u", "status": "ok", "toolName": "other_tool"},
            {"candidateId": "", "locator": "u", "status": "fetched", "toolName": "web_fetch_tool"},
            {"locator": "u", "status": "fetched", "toolName": "web_fetch_tool"},
            "not-a-ref",
        ],
    )
    assert "evidenceFetchAttempts" not in merged


def test_no_refs_keeps_existing_attempts_untouched() -> None:
    payload = {"evidenceFetchAttempts": [_ref("c1", "failed", failureCode="tool_unavailable")]}
    merged = _merge_source_collection_stage_writeback_evidence_fetch_attempts(payload, [])
    assert merged["evidenceFetchAttempts"] == payload["evidenceFetchAttempts"]
