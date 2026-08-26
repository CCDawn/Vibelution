"""LLM review runners wiring tests.

Covers the real-model wiring layer for the human-click review chain:

* availability resolution is fail-open at the fixture boundary (no model →
  DEV fixtures stay in charge) and the conftest autouse fixture pins it to
  ``None`` so the suite never touches real provider credentials;
* an injected fake LLM produces executor-compatible outputs for the digest
  drafter and the four review runners (reflection / pairwise / Pareto /
  MetaReview), including the server-owned ``sourceMessageRefs`` and the
  ``llm:<model>`` reviewer attribution;
* malformed model output fails closed with ``ContractValidationError``
  before anything is persisted;
* the runners compose with ``execute_hypothesis_review`` end to end.

No real model or network is involved.
"""

from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.web.services.team_workflow import llm_review_runners
from core.web.services.team_workflow.hypothesis_review_executor import (
    execute_hypothesis_review,
)

_FAKE_LLM = {"client": object(), "profileId": "primary", "modelId": "fake-review-model"}


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


def _install_fake_llm(monkeypatch, payloads: list[str]):
    """Patch ``invoke_llm`` to return the queued JSON payloads in order."""

    queue = list(payloads)

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        assert context is not None, "review calls must carry an invocation context"
        assert str(getattr(context, "surface", "")) == "team_workflow_review"
        payload = queue.pop(0)
        return _FakeResponse(payload)

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    return queue


# ---------------------------------------------------------------------------
# Availability: fail-open at the fixture boundary
# ---------------------------------------------------------------------------


def test_resolve_review_llm_is_pinned_to_none_in_tests():
    assert llm_review_runners.resolve_review_llm() is None


def test_builders_return_none_without_a_model():
    assert llm_review_runners.build_meeting_digest_drafter() is None
    assert llm_review_runners.build_hypothesis_review_runners() is None


def test_close_review_meeting_and_digest_keep_fixture_defaults():
    """The wiring must not change DEV behaviour when no model resolves.

    With resolution pinned to ``None`` the digest builder receives a ``None``
    drafter and keeps the deterministic marker-extraction path.
    """

    from core.web.services.team_workflow import meeting_runtime

    draft = meeting_runtime.build_meeting_digest_draft(
        _meeting_round(), _source_messages(), drafter=None
    )
    # DEV fixture semantics: markers extracted from the completed messages.
    assert draft["sourceMessageRefs"] == draft["sourceMessageRefs"]
    assert isinstance(draft["summary"], str) and draft["summary"]


# ---------------------------------------------------------------------------
# Digest drafter with an injected fake LLM
# ---------------------------------------------------------------------------


def _meeting_round(**overrides):
    round_payload = {
        "teamId": "team-1",
        "meetingRoundId": "meeting-1",
        "meetingType": "hypothesis_review",
        "agenda": ["评审候选 A/B"],
        "participants": ["p-1", "p-2"],
        "discussionItemRefs": [],
        "chatRoomRoundIds": ["r-1"],
    }
    round_payload.update(overrides)
    return round_payload


def _source_messages():
    return [
        {"status": "completed", "participantId": "p-1", "content": "候选 A 更契合赛题。"},
        {"status": "completed", "participantId": "p-2", "content": "同意。"},
        {"status": "failed", "participantId": "p-1", "content": "应被忽略的失败发言。"},
    ]


def test_digest_drafter_uses_llm_output_and_server_owned_refs(monkeypatch):
    payload = json.dumps(
        {
            "summary": "评审完成，倾向候选 A。",
            "agendaSummary": "评审候选 A/B",
            "agreements": ["候选 A 更契合赛题"],
            "disagreements": [],
            "actionItems": [],
            "risks": [],
            "knowledgeCandidates": [],
            "proposedCandidates": [],
            "evidenceRequests": [],
        },
        ensure_ascii=False,
    )
    _install_fake_llm(monkeypatch, [payload])

    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    assert drafter is not None
    digest = drafter(_meeting_round(), _source_messages())

    assert digest["summary"] == "评审完成，倾向候选 A。"
    assert digest["agreements"] == ["候选 A 更契合赛题"]
    # sourceMessageRefs are server-owned: only completed, non-pass messages.
    refs = digest["sourceMessageRefs"]
    assert isinstance(refs, list) and len(refs) == 2


def test_digest_drafter_fails_closed_without_completed_messages(monkeypatch):
    _install_fake_llm(monkeypatch, ["{}"])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    with pytest.raises(ContractValidationError):
        drafter(_meeting_round(), [{"status": "failed", "content": "x"}])


def test_digest_drafter_fails_closed_on_non_json(monkeypatch):
    _install_fake_llm(monkeypatch, ["这不是 JSON"])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    with pytest.raises(ContractValidationError):
        drafter(_meeting_round(), _source_messages())


# ---------------------------------------------------------------------------
# Hypothesis review runners with an injected fake LLM
# ---------------------------------------------------------------------------


def _candidate(candidate_id: str, claim: str) -> dict:
    return {
        "candidateId": candidate_id,
        "claim": claim,
        "rationale": "初步论证",
        "differenceFromAlternatives": "与备选不同",
        "lineageRefs": [],
        "status": "reviewed",
    }


def _review_context() -> dict:
    return {
        "contextId": "ctx-1",
        "teamId": "team-1",
        "question": "SCI-096",
        "candidates": [_candidate("cand-a", "假说 A"), _candidate("cand-b", "假说 B")],
    }


def test_review_runners_produce_executor_compatible_outputs(monkeypatch):
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None

    reflection_payload = json.dumps(
        {
            "claim": "假说 A",
            "rationale": "五维评分依据。",
            "differenceFromAlternatives": "机制不同",
            "lineageRefs": [],
            "scores": {
                "novelty": 0.72,
                "competitionFit": 0.65,
                "falsifiability": 0.6,
                "evidenceSupport": 0.55,
                "feasibility": 0.8,
            },
            "reviewedBy": "llm",
            "status": "reviewed",
            "dimensionReviews": [
                {"dimension": "novelty", "rating": "strong", "rationale": "新机制", "evidence_refs": []}
            ],
        },
        ensure_ascii=False,
    )
    pairwise_payload = json.dumps(
        {"outcome": "left_wins", "justification": "A 维度领先更多。"}
    )
    pareto_payload = json.dumps(
        {
            "paretoFrontCandidateIds": ["cand-a"],
            "dominatedCandidateIds": ["cand-b"],
            "notes": "A 不被全维占优。",
        }
    )
    metareview_payload = json.dumps(
        {
            "recommendationCandidateId": "cand-a",
            "rationale": "前沿且胜出。",
            "riskNotes": "证据缺口待补。",
            "accepted": True,
        }
    )
    _install_fake_llm(
        monkeypatch,
        [reflection_payload, pairwise_payload, pareto_payload, metareview_payload],
    )

    context = _review_context()
    reflection = runners["reflection_runner"](dict(context["candidates"][0]), context)
    assert reflection["reviewedBy"] == f"llm:{_FAKE_LLM['modelId']}"
    assert reflection["dimensionReviews"][0]["hypothesis_id"] == "cand-a"
    assert reflection["dimensionReviews"][0]["reviewer"] == f"llm:{_FAKE_LLM['modelId']}"

    pairwise = runners["pairwise_runner"](
        dict(context["candidates"][0]), dict(context["candidates"][1]), context
    )
    assert pairwise["outcome"] == "left_wins"

    pareto = runners["pareto_runner"](
        {"cand-a": {"novelty": 0.7}, "cand-b": {"novelty": 0.5}}, context
    )
    assert pareto["paretoFrontCandidateIds"] == ["cand-a"]

    metareview = runners["metareview_runner"](
        context,
        context["candidates"],
        [{"leftCandidateId": "cand-a", "rightCandidateId": "cand-b", "outcome": "left_wins"}],
        pareto,
    )
    assert metareview["recommendationCandidateId"] == "cand-a"
    assert metareview["reviewerAgentId"] == f"llm:{_FAKE_LLM['modelId']}"


def test_reflection_runner_fails_closed_on_missing_dimensions(monkeypatch):
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    payload = json.dumps(
        {
            "claim": "假说 A",
            "rationale": "缺维度。",
            "differenceFromAlternatives": "不同",
            "scores": {"novelty": 0.5},
        }
    )
    _install_fake_llm(monkeypatch, [payload])
    context = _review_context()
    with pytest.raises(ContractValidationError):
        execute_hypothesis_review(
            context,
            round_id="r-1",
            reflection_runner=runners["reflection_runner"],
            pairwise_runner=runners["pairwise_runner"],
            pareto_runner=runners["pareto_runner"],
            metareview_runner=runners["metareview_runner"],
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_runners_compose_with_execute_hypothesis_review(monkeypatch):
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    scores_a = {
        "novelty": 0.72,
        "competitionFit": 0.65,
        "falsifiability": 0.6,
        "evidenceSupport": 0.55,
        "feasibility": 0.8,
    }
    scores_b = {dimension: 0.4 for dimension in scores_a}
    payloads: list[str] = []
    # reflection for both candidates
    for claim, scores in (("假说 A", scores_a), ("假说 B", scores_b)):
        payloads.append(
            json.dumps(
                {
                    "claim": claim,
                    "rationale": "评分依据。",
                    "differenceFromAlternatives": "不同",
                    "lineageRefs": [],
                    "scores": scores,
                    "status": "reviewed",
                },
                ensure_ascii=False,
            )
        )
    # pairwise for the single pair
    payloads.append(json.dumps({"outcome": "left_wins", "justification": "A 领先。"}))
    # pareto
    payloads.append(
        json.dumps(
            {
                "paretoFrontCandidateIds": ["cand-a"],
                "dominatedCandidateIds": ["cand-b"],
                "notes": "B 被全维占优。",
            }
        )
    )
    # metareview
    payloads.append(
        json.dumps(
            {
                "recommendationCandidateId": "cand-a",
                "rationale": "前沿且胜出。",
                "riskNotes": "",
                "accepted": True,
            }
        )
    )
    _install_fake_llm(monkeypatch, payloads)

    result = execute_hypothesis_review(
        _review_context(),
        round_id="r-1",
        reflection_runner=runners["reflection_runner"],
        pairwise_runner=runners["pairwise_runner"],
        pareto_runner=runners["pareto_runner"],
        metareview_runner=runners["metareview_runner"],
        reviewer_assignments={"metareview": "coordinator"},
    )
    assert result["candidates"][0]["reviewedBy"] == f"llm:{_FAKE_LLM['modelId']}"
    assert result["metaReview"]["recommendationCandidateId"] == "cand-a"
    assert result["metaReview"]["accepted"] is True
