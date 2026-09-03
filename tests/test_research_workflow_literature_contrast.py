"""Literature contrast for the hypothesis novelty review dimension.

Covers the evidence-enhancement chain:

* mechanical query construction from the candidate claim and difference
  statement;
* the fail-open retrieval module (success merge/dedup/cap, provider errors,
  deadline abandonment, cache reuse);
* executor wiring: the contrast rides into the reflection runner context and
  is persisted at candidate level together with the runner's structured
  ``noveltyContrast`` conclusion — never inside the seven audit rows;
* runner wiring: the reflection payload carries ``literatureContrast``, the
  system prompt enforces the contrast rules, and a malformed
  ``noveltyContrast`` never fails the review;
* revision pass-through and the canonical authority / result package v2
  pass-through of ``noveltyContrastByCandidate``.

No real model or network is involved.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.research.competition.question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
)
from core.research.workflow.contracts.hypothesis_quality import (
    HYPOTHESIS_SCORE_DIMENSIONS,
)
from core.web.services.team_workflow import (
    hypothesis_review_executor,
    literature_contrast,
    llm_review_runners,
)
from core.web.services.team_workflow.research_runtime.dimension_reviews_artifact_writer import (
    _novelty_contrasts_from_review,
)
from tests.test_team_workflow_llm_review_runners import (
    _candidate,
    _dimension_review_rows,
    _review_context,
)


def _contrast_response(results: list[dict[str, Any]], *, error: str = ""):
    def _query(query, *, max_results, provider):
        if error:
            return {"provider": provider, "results": [], "error": error}
        return {"provider": provider, "results": list(results)[:max_results]}

    return _query


# Captured at collection time, before the conftest autouse fixture pins the
# module function to a ``None`` stub for the rest of the suite.
_REAL_RETRIEVE = literature_contrast.retrieve_literature_contrast


@pytest.fixture
def real_retrieval(monkeypatch):
    """Restore the real fail-open retriever for the retrieval unit tests."""

    monkeypatch.setattr(
        literature_contrast, "retrieve_literature_contrast", _REAL_RETRIEVE
    )


def _paper_result(title: str, *, summary: str = "论文摘要。", **metadata) -> dict[str, Any]:
    return {
        "title": title,
        "sourceRef": f"https://example.org/{title}",
        "rawLocation": f"https://example.org/{title}",
        "summary": summary,
        "metadata": {
            "publicationYear": 2024,
            "venue": "Nature",
            **metadata,
        },
    }


@pytest.fixture(autouse=True)
def _fresh_contrast_cache():
    literature_contrast.clear_cache()
    yield
    literature_contrast.clear_cache()


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


def test_build_queries_from_claim_and_difference():
    queries = literature_contrast.build_literature_contrast_queries(
        {
            "candidateId": "cand-a",
            "claim": "  基于  机制的  假设  ",
            "differenceFromAlternatives": "与备选不同",
        }
    )
    assert queries == ["基于 机制的 假设", "与备选不同"]


def test_build_queries_truncate_dedupe_and_skip_empty():
    long_claim = "重复文本 " * 100
    queries = literature_contrast.build_literature_contrast_queries(
        {
            "candidateId": "cand-a",
            "claim": long_claim,
            "differenceFromAlternatives": long_claim.strip(),
        }
    )
    assert len(queries) == 1
    assert len(queries[0]) == literature_contrast.QUERY_MAX_CHARS
    assert literature_contrast.build_literature_contrast_queries({"candidateId": "x"}) == []


# ---------------------------------------------------------------------------
# Retrieval module: fail-open semantics
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_merges_dedupes_and_caps(monkeypatch):
    responses = {
        "q-arxiv": [
            _paper_result("Paper A"),
            _paper_result("Paper B", summary="另一篇。"),
        ],
        "q-openalex": [
            _paper_result("paper a", summary="标题去重后相同。"),
            _paper_result("Paper C"),
        ],
    }

    def fake_query(query, *, max_results, provider):
        key = "q-arxiv" if provider == "arxiv_api" else "q-openalex"
        return {"provider": provider, "results": responses[key][:max_results]}

    monkeypatch.setattr(literature_contrast, "_execute_source_collection_query", fake_query)
    contrast = literature_contrast.retrieve_literature_contrast(
        {"candidateId": "c1", "claim": "q-arxiv", "differenceFromAlternatives": "q-openalex"}
    )
    assert contrast["degraded"] is False
    assert [paper["title"] for paper in contrast["papers"]] == ["Paper A", "Paper B", "Paper C"]
    assert {paper["provider"] for paper in contrast["papers"]} == {"arxiv_api", "openalex_api"}
    assert set(contrast["papers"][0]) <= {"title", "provider", "url", "year", "venue", "citationCount", "abstract"}
    meta = contrast["retrievalMeta"]
    assert meta["paperCount"] == 3
    assert meta["providers"] == ["arxiv_api", "openalex_api"]
    assert meta["retrievedAt"].endswith("Z")


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_caps_papers_at_ten_and_truncates_abstract(monkeypatch):
    def fake_query(query, *, max_results, provider):
        # Distinct papers per provider so the merged set exceeds the cap.
        results = [
            _paper_result(f"{provider} Paper {index}", summary="很长的摘要 " * 300)
            for index in range(9)
        ]
        return {"provider": provider, "results": results[:max_results]}

    monkeypatch.setattr(
        literature_contrast,
        "_execute_source_collection_query",
        fake_query,
    )
    contrast = literature_contrast.retrieve_literature_contrast(
        {"candidateId": "c2", "claim": "claim", "differenceFromAlternatives": "diff"}
    )
    assert len(contrast["papers"]) == literature_contrast.CONTRAST_PAPER_LIMIT
    for paper in contrast["papers"]:
        assert len(paper["abstract"]) <= literature_contrast.ABSTRACT_MAX_CHARS


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_provider_error_is_partial_not_degraded(monkeypatch):
    def fake_query(query, *, max_results, provider):
        if provider == "arxiv_api":
            return {"provider": provider, "results": [], "error": "429 too many requests"}
        return {"provider": provider, "results": [_paper_result("Paper Z")]}

    monkeypatch.setattr(literature_contrast, "_execute_source_collection_query", fake_query)
    contrast = literature_contrast.retrieve_literature_contrast(
        {"candidateId": "c3", "claim": "claim", "differenceFromAlternatives": "diff"}
    )
    assert contrast["degraded"] is False
    assert [paper["title"] for paper in contrast["papers"]] == ["Paper Z"]
    assert any("429" in item for item in contrast["retrievalMeta"]["errors"])


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_empty_results_degrade(monkeypatch):
    monkeypatch.setattr(
        literature_contrast,
        "_execute_source_collection_query",
        _contrast_response([]),
    )
    contrast = literature_contrast.retrieve_literature_contrast(
        {"candidateId": "c4", "claim": "claim", "differenceFromAlternatives": "diff"}
    )
    assert contrast["degraded"] is True
    assert contrast["papers"] == []
    assert contrast["retrievalMeta"]["degradedReason"] == "no_results"


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_transport_exception_degrades(monkeypatch):
    def boom(query, *, max_results, provider):
        raise OSError("network unreachable")

    monkeypatch.setattr(literature_contrast, "_execute_source_collection_query", boom)
    contrast = literature_contrast.retrieve_literature_contrast(
        {"candidateId": "c5", "claim": "claim", "differenceFromAlternatives": "diff"}
    )
    assert contrast["degraded"] is True
    assert contrast["papers"] == []
    assert contrast["retrievalMeta"]["errors"]


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_deadline_abandons_stragglers(monkeypatch):
    def slow(query, *, max_results, provider):
        import time

        time.sleep(5)
        return {"provider": provider, "results": [_paper_result("Too late")]}

    monkeypatch.setattr(literature_contrast, "_execute_source_collection_query", slow)
    contrast = literature_contrast.retrieve_literature_contrast(
        {"candidateId": "c6", "claim": "claim", "differenceFromAlternatives": "diff"},
        deadline_seconds=0.2,
    )
    assert contrast["degraded"] is True
    assert contrast["retrievalMeta"]["timedOutQueries"] == 4


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_reuses_cache_for_same_candidate(monkeypatch):
    calls: list[str] = []

    def fake_query(query, *, max_results, provider):
        calls.append(query)
        return {"provider": provider, "results": [_paper_result("Cached paper")]}

    monkeypatch.setattr(literature_contrast, "_execute_source_collection_query", fake_query)
    candidate = {
        "candidateId": "c7",
        "claim": "同一主张",
        "differenceFromAlternatives": "同一差异",
    }
    first = literature_contrast.retrieve_literature_contrast(candidate)
    second = literature_contrast.retrieve_literature_contrast(candidate)
    assert len(calls) == 4  # 2 queries x 2 providers, exactly once
    assert first == second


@pytest.mark.usefixtures("real_retrieval")
def test_retrieve_without_retrievable_text_degrades_immediately(monkeypatch):
    def fail(query, *, max_results, provider):
        raise AssertionError("must not query without retrievable text")

    monkeypatch.setattr(literature_contrast, "_execute_source_collection_query", fail)
    contrast = literature_contrast.retrieve_literature_contrast({"candidateId": "c8"})
    assert contrast["degraded"] is True
    assert contrast["retrievalMeta"]["degradedReason"] == "candidate_has_no_retrievable_text"


# ---------------------------------------------------------------------------
# Executor wiring
# ---------------------------------------------------------------------------


def _reflection_output(candidate_id: str, *, novelty_contrast: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "claim": _candidate(candidate_id, "假说")["claim"],
        "rationale": "五维依据。",
        "differenceFromAlternatives": "与备选不同",
        "lineageRefs": [],
        "scores": {dimension: 0.6 for dimension in HYPOTHESIS_SCORE_DIMENSIONS},
        "reviewedBy": "llm",
        "status": "reviewed",
        "dimensionReviews": _dimension_review_rows(candidate_id),
    }
    if novelty_contrast is not None:
        payload["noveltyContrast"] = novelty_contrast
    return payload


def _reflection_step_with_runner(monkeypatch, *, contrast: Any, novelty_contrast: Any = None):
    captured: dict[str, Any] = {"contexts": [], "calls": 0}

    def fake_runner(candidate: dict[str, Any], context: dict[str, Any]):
        captured["calls"] += 1
        captured["contexts"].append(dict(context))
        return _reflection_output(str(candidate["candidateId"]), novelty_contrast=novelty_contrast)

    retrievals: list[str] = []

    def fake_retrieve(candidate):
        retrievals.append(str(candidate.get("candidateId") or ""))
        if isinstance(contrast, BaseException):
            raise contrast
        return contrast

    monkeypatch.setattr(literature_contrast, "retrieve_literature_contrast", fake_retrieve)
    candidates = [_candidate("cand-a", "假说 A"), _candidate("cand-b", "假说 B")]
    reviewed = hypothesis_review_executor._reflection_step(
        _review_context(),
        candidates,
        runner=fake_runner,
        agent_id="reviewer-agent",
        formal_receipts=None,
    )
    return reviewed, captured, retrievals


def test_reflection_step_injects_contrast_and_persists_candidate_keys(monkeypatch):
    contrast = {
        "papers": [{"title": "Paper A", "provider": "arxiv_api", "abstract": "摘要"}],
        "queries": ["假说 A", "与备选不同"],
        "degraded": False,
        "retrievalMeta": {"providers": ["arxiv_api"], "paperCount": 1},
    }
    novelty = {"overlapPapers": ["Paper A"], "deltaStatement": "机制不同", "basis": "retrieved"}
    reviewed, captured, retrievals = _reflection_step_with_runner(
        monkeypatch,
        contrast=contrast,
        novelty_contrast=novelty,
    )
    assert retrievals == ["cand-a", "cand-b"]
    assert captured["calls"] == 2  # still exactly one reflection call per candidate
    for context in captured["contexts"]:
        assert context["literatureContrast"] == contrast
    for item in reviewed:
        assert item["literatureContrast"] == contrast
        assert item["noveltyContrast"] == novelty
        # The audit rows stay exactly seven and never gain contrast fields.
        assert len(item["dimensionReviews"]) == len(REQUIRED_REVIEW_DIMENSIONS)
        assert all(
            set(row) == {
                "hypothesis_id",
                "dimension",
                "rating",
                "rationale",
                "reviewer",
                "evidence_refs",
            }
            for row in item["dimensionReviews"]
        )


def test_reflection_step_survives_retriever_crash(monkeypatch):
    reviewed, captured, _retrievals = _reflection_step_with_runner(
        monkeypatch,
        contrast=RuntimeError("provider exploded"),
    )
    assert captured["calls"] == 2
    for context in captured["contexts"]:
        assert "literatureContrast" not in context
    for item in reviewed:
        assert "literatureContrast" not in item


def test_reflection_step_persists_degraded_contrast(monkeypatch):
    contrast = {
        "papers": [],
        "queries": ["假说 A"],
        "degraded": True,
        "retrievalMeta": {"errors": ["429"], "degradedReason": "no_results"},
    }
    reviewed, _captured, _retrievals = _reflection_step_with_runner(
        monkeypatch, contrast=contrast
    )
    for item in reviewed:
        assert item["literatureContrast"]["degraded"] is True
        assert item["literatureContrast"]["papers"] == []


def test_candidates_with_review_contrast_merges_only_mapped_fields():
    candidates = [{"candidateId": "cand-a", "claim": "A"}, {"candidateId": "cand-b", "claim": "B"}]
    reviewed = [
        {
            "candidateId": "cand-a",
            "literatureContrast": {"papers": [{"title": "T"}], "degraded": False},
            "noveltyContrast": {"overlapPapers": ["T"], "deltaStatement": "d", "basis": "retrieved"},
        }
    ]
    merged = hypothesis_review_executor._candidates_with_review_contrast(candidates, reviewed)
    assert merged[0]["literatureContrast"]["papers"] == [{"title": "T"}]
    assert merged[0]["noveltyContrast"]["basis"] == "retrieved"
    assert "literatureContrast" not in merged[1]


def test_revision_step_receives_contrast_on_parent_candidate(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_revision_runner(context, parent, candidates, meta_review):
        captured["parent"] = dict(parent)
        return {
            "revisedCandidate": {**_candidate("cand-a", "假说 A（修订版）")},
            "changes": ["收窄人群"],
            "unresolvedIssues": ["边界待验证"],
        }

    reviewed = [
        {
            "candidateId": "cand-a",
            "literatureContrast": {"papers": [{"title": "T"}], "degraded": False},
            "noveltyContrast": {"overlapPapers": ["T"], "deltaStatement": "d", "basis": "retrieved"},
        }
    ]
    candidates = [_candidate("cand-a", "假说 A"), _candidate("cand-b", "假说 B")]
    hypothesis_review_executor._revision_step(
        _review_context(),
        hypothesis_review_executor._candidates_with_review_contrast(
            candidates, reviewed
        ),
        {
            "recommendationCandidateId": "cand-a",
            "rationale": "推荐 A",
            "riskNotes": "风险",
        },
        runner=fake_revision_runner,
        round_id="round-1",
        formal_receipts=None,
    )
    assert captured["parent"]["literatureContrast"]["degraded"] is False
    assert captured["parent"]["noveltyContrast"]["basis"] == "retrieved"


# ---------------------------------------------------------------------------
# Runner wiring: payload, prompt rules, lenient noveltyContrast
# ---------------------------------------------------------------------------


def _install_capturing_llm(monkeypatch, payload: str):
    captured: dict[str, Any] = {}

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        captured["messages"] = messages
        captured["system_prompt"] = messages[0]["content"]
        captured["user_payload"] = json.loads(messages[1]["content"])
        return type("_R", (), {"content": payload, "response_metadata": {}})()

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    return captured


def _fake_review_llm(monkeypatch):
    monkeypatch.setattr(
        llm_review_runners,
        "resolve_review_llm",
        lambda: {"client": object(), "profileId": "primary", "modelId": "fake-model"},
    )


def test_reflection_payload_carries_literature_contrast_and_result_keeps_novelty(monkeypatch):
    _fake_review_llm(monkeypatch)
    reflection = _reflection_output("cand-a")
    reflection["noveltyContrast"] = {
        "overlapPapers": ["Paper A", "", None],
        "deltaStatement": "真正的增量",
        "basis": "retrieved",
    }
    captured = _install_capturing_llm(
        monkeypatch, json.dumps(reflection, ensure_ascii=False)
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        {"client": object(), "profileId": "primary", "modelId": "fake-model"}
    )
    context = _review_context()
    context["literatureContrast"] = {
        "papers": [{"title": "Paper A", "abstract": "摘要"}],
        "queries": ["假说 A"],
        "degraded": False,
        "retrievalMeta": {"paperCount": 1},
    }
    result = runners["reflection_runner"](_candidate("cand-a", "假说 A"), context)

    payload_literature = captured["user_payload"]["literatureContrast"]
    assert payload_literature["degraded"] is False
    assert payload_literature["papers"][0]["title"] == "Paper A"
    assert result["noveltyContrast"] == {
        "overlapPapers": ["Paper A"],
        "deltaStatement": "真正的增量",
        "basis": "retrieved",
    }
    # The audit rows remain exactly seven dimensions.
    assert {row["dimension"] for row in result["dimensionReviews"]} == set(
        REQUIRED_REVIEW_DIMENSIONS
    )


def test_reflection_without_contrast_degrades_payload_and_forces_basis(monkeypatch):
    _fake_review_llm(monkeypatch)
    reflection = _reflection_output("cand-a")
    reflection["noveltyContrast"] = {
        "overlapPapers": ["Paper A"],
        "deltaStatement": "增量",
        "basis": "retrieved",
    }
    captured = _install_capturing_llm(
        monkeypatch, json.dumps(reflection, ensure_ascii=False)
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        {"client": object(), "profileId": "primary", "modelId": "fake-model"}
    )
    result = runners["reflection_runner"](_candidate("cand-a", "假说 A"), _review_context())

    assert captured["user_payload"]["literatureContrast"] == {
        "papers": [],
        "degraded": True,
        "retrievalMeta": {},
    }
    assert result["noveltyContrast"]["basis"] == "degraded"


def test_reflection_malformed_novelty_contrast_never_fails_review(monkeypatch):
    _fake_review_llm(monkeypatch)
    reflection = _reflection_output("cand-a")
    reflection["noveltyContrast"] = "不是对象"
    _install_capturing_llm(monkeypatch, json.dumps(reflection, ensure_ascii=False))
    runners = llm_review_runners.build_hypothesis_review_runners(
        {"client": object(), "profileId": "primary", "modelId": "fake-model"}
    )
    result = runners["reflection_runner"](_candidate("cand-a", "假说 A"), _review_context())
    assert "noveltyContrast" not in result
    assert {row["dimension"] for row in result["dimensionReviews"]} == set(
        REQUIRED_REVIEW_DIMENSIONS
    )


def test_reflection_missing_novelty_contrast_stays_absent(monkeypatch):
    _fake_review_llm(monkeypatch)
    captured = _install_capturing_llm(
        monkeypatch, json.dumps(_reflection_output("cand-a"), ensure_ascii=False)
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        {"client": object(), "profileId": "primary", "modelId": "fake-model"}
    )
    result = runners["reflection_runner"](_candidate("cand-a", "假说 A"), _review_context())
    assert "noveltyContrast" not in result


def test_reflection_system_prompt_enforces_contrast_rules():
    prompt = llm_review_runners._REFLECTION_SYSTEM_PROMPT
    assert "literatureContrast" in prompt
    assert "检索结果中未发现显著重叠工作" in prompt
    assert "noveltyContrast" in prompt
    assert "open-access 盲区" in prompt
    assert "禁止写入 evidence_refs" in prompt


# ---------------------------------------------------------------------------
# Canonical authority + result package pass-through
# ---------------------------------------------------------------------------


def test_novelty_contrasts_extraction_is_lenient():
    review = {
        "candidates": [
            {
                "candidateId": "cand-a",
                "noveltyContrast": {
                    "overlapPapers": ["Paper A"],
                    "deltaStatement": "d",
                    "basis": "retrieved",
                },
            },
            {"candidateId": "cand-b", "noveltyContrast": {"basis": "weird"}},
            {"candidateId": "cand-c", "noveltyContrast": "垃圾"},
            {"candidateId": "cand-d"},
        ]
    }
    contrasts = _novelty_contrasts_from_review(review)
    assert set(contrasts) == {"cand-a"}
    assert contrasts["cand-a"] == {
        "overlapPapers": ["Paper A"],
        "deltaStatement": "d",
        "basis": "retrieved",
    }
    assert _novelty_contrasts_from_review([{"dimension": "novelty"}]) == {}


# The former test_merge_novelty_contrasts_into_hypotheses was removed together
# with _merge_novelty_contrasts: the canonical v2 schema closes hypothesis
# items (additionalProperties=false), so novelty contrast conclusions stay in
# the dimension_reviews authority instead of being merged onto hypotheses.


# ---------------------------------------------------------------------------
# Round record persistence (candidate-level keys survive closure)
# ---------------------------------------------------------------------------


def test_round_record_keeps_candidate_level_contrast_keys(tmp_path, monkeypatch):
    from tests.test_research_workflow_hypothesis_rounds import (
        _candidate as _round_candidate,
        _closure,
        _round_payload,
        _team,
    )
    from core.web.services.team_workflow import hypothesis_rounds as rounds_service

    team_id = _team(tmp_path, monkeypatch)
    literature = {
        "papers": [{"title": "Paper A", "provider": "arxiv_api", "abstract": "摘要"}],
        "queries": ["假说 A"],
        "degraded": False,
        "retrievalMeta": {"providers": ["arxiv_api"], "paperCount": 1},
    }
    novelty = {
        "overlapPapers": ["Paper A"],
        "deltaStatement": "真正的增量",
        "basis": "retrieved",
    }
    candidates = [
        _round_candidate("cand-a", "A bounded proxy claim.", "Encoder proxy."),
        _round_candidate("cand-b", "A decoder capacity claim.", "Decoder capacity."),
    ]
    candidates[0]["literatureContrast"] = literature
    candidates[0]["noveltyContrast"] = novelty
    created = rounds_service.create_hypothesis_round(
        team_id, _round_payload(candidates=candidates)
    )
    round_id = created["round"]["roundId"]
    closed = rounds_service.close_hypothesis_round(
        team_id, round_id, _closure(created["round"])
    )
    assert closed["status"] == "created"

    stored = rounds_service.get_hypothesis_round(team_id, round_id)["round"]
    stored_a = next(
        item for item in stored["candidates"] if item["candidateId"] == "cand-a"
    )
    assert stored_a["literatureContrast"] == literature
    assert stored_a["noveltyContrast"] == novelty
    stored_b = next(
        item for item in stored["candidates"] if item["candidateId"] == "cand-b"
    )
    assert "literatureContrast" not in stored_b
    assert "noveltyContrast" not in stored_b
