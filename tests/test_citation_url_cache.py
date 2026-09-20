"""Team-scoped citation URL cache: TTL policy, latest-wins, compaction."""

from __future__ import annotations

import json

from core.web.services.team_workflow import citation_url_cache
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain_store,
)

TEAM_ID = "research-team"
VERIFIED_TTL = citation_url_cache.VERIFIED_TTL_MS
NEGATIVE_TTL = citation_url_cache.NEGATIVE_TTL_MS


def _use_tmp_cache(tmp_path, monkeypatch):
    path = tmp_path / "research_workflow" / "citation_url_cache.jsonl"
    monkeypatch.setattr(
        hypothesis_first_chain_store,
        "_storage_path",
        lambda team_id: path.parent / "hypothesis_first_chain.jsonl",
    )
    return path


def test_record_and_read_latest_wins(tmp_path, monkeypatch) -> None:
    path = _use_tmp_cache(tmp_path, monkeypatch)
    citation_url_cache.record_citation_url_results(
        TEAM_ID,
        [
            {"sourceUrl": "https://a.example/p1", "outcome": "failed",
             "reason": "doi_definitive_rejection:403", "questionId": "sci-001",
             "runId": "run-1", "atMs": 1_000},
            {"sourceUrl": "https://a.example/p1", "outcome": "verified",
             "reason": "", "questionId": "sci-001", "runId": "run-2",
             "atMs": 2_000},
            {"sourceUrl": "", "outcome": "verified", "reason": ""},
        ],
    )
    cache = citation_url_cache.read_citation_url_cache(TEAM_ID)
    assert set(cache) == {"https://a.example/p1"}
    assert cache["https://a.example/p1"]["outcome"] == "verified"
    assert cache["https://a.example/p1"]["questionId"] == "SCI-001"


def test_split_fresh_ttl_policy() -> None:
    now = 10_000_000
    verified_fresh = {"outcome": "verified", "reason": "", "atMs": now - VERIFIED_TTL + 1}
    verified_stale = {"outcome": "verified", "reason": "", "atMs": now - VERIFIED_TTL}
    negative_fresh = {
        "outcome": "failed", "reason": "doi_definitive_rejection:403",
        "atMs": now - NEGATIVE_TTL + 1,
    }
    negative_stale = {
        "outcome": "failed", "reason": "non_retryable", "atMs": now - NEGATIVE_TTL,
    }
    transient = {"outcome": "failed", "reason": "attempts_exhausted", "atMs": now - 1}

    verified, negative = citation_url_cache.split_fresh(
        {
            "vf": verified_fresh,
            "vs": verified_stale,
            "nf": negative_fresh,
            "ns": negative_stale,
            "tr": transient,
        },
        now_ms=now,
    )
    assert verified == {"vf": True}
    assert set(negative) == {"nf"}


def test_is_cacheable_failure_reason_truth_table() -> None:
    assert citation_url_cache.is_cacheable_failure_reason("doi_definitive_rejection:403")
    assert citation_url_cache.is_cacheable_failure_reason("non_retryable")
    assert not citation_url_cache.is_cacheable_failure_reason("attempts_exhausted")
    assert not citation_url_cache.is_cacheable_failure_reason("no_doi_authority")
    assert not citation_url_cache.is_cacheable_failure_reason("")


def test_compaction_rewrites_when_appends_dominate(tmp_path, monkeypatch) -> None:
    path = _use_tmp_cache(tmp_path, monkeypatch)
    entries = [
        {"sourceUrl": "https://a.example/p1", "outcome": "verified", "reason": "",
         "atMs": index}
        for index in range(6)
    ]
    citation_url_cache.record_citation_url_results(TEAM_ID, entries)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    # 6 appends over 1 distinct URL exceed the 4x ratio: back to one line.
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["atMs"] == 5

    cache = citation_url_cache.read_citation_url_cache(TEAM_ID)
    assert set(cache) == {"https://a.example/p1"}


def test_record_never_raises_on_unwritable_path(tmp_path, monkeypatch) -> None:
    path = _use_tmp_cache(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a directory blocker", encoding="utf-8")
    path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Make the ledger path itself a directory so the append hits OSError.
    path.mkdir()
    result = citation_url_cache.record_citation_url_results(
        TEAM_ID,
        [{"sourceUrl": "https://a.example/p1", "outcome": "verified", "reason": ""}],
    )
    assert "error" in result
