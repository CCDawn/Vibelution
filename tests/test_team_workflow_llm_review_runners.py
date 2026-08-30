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
import threading
import time

import pytest

from core.llm.types import CanonicalItemIdentity, LLMError, TurnOutcome
from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.web.services import agent_directory_service, team_service
from core.web.services.team_workflow import llm_review_runners
from core.web.services.team_workflow.hypothesis_review_executor import (
    ProviderBoundReviewResult,
    execute_hypothesis_review,
)
from core.web.services.team_workflow.research_runtime import meeting_receipt_authority

_RESOLVE_REVIEW_LLM_UNDER_TEST = llm_review_runners.resolve_review_llm
_FAKE_LLM = {"client": object(), "profileId": "primary", "modelId": "fake-review-model"}
_FORMAL_FAKE_LLM = {
    **_FAKE_LLM,
    "providerId": "opencode",
    "modelId": "deepseek-v4-flash",
    "modelRef": "opencode/deepseek-v4-flash",
}


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


def test_review_llm_uses_challenge_cup_team_model_instead_of_operator_primary(
    monkeypatch,
):
    runtime_config = object()
    captured: dict[str, object] = {}

    class _Provider:
        provider_id = "team-provider"
        api_key = "configured"
        api_key_env = ""
        requires_api_key = True

    class _Profile:
        model = "team-model"

    class _Client:
        provider = _Provider()
        profile = _Profile()

    def fake_config_for_agent_llm_model(config, **kwargs):
        captured["baseConfig"] = config
        captured.update(kwargs)
        return runtime_config

    def fake_get_llm_client(*, profile_id, config):
        captured["clientProfileId"] = profile_id
        captured["clientConfig"] = config
        return _Client()

    base_config = object()
    monkeypatch.setattr(
        team_service,
        "get_team_light",
        lambda team_id: {
            "teamId": team_id,
            "members": [
                {
                    "role": "challenge_cup_evaluator",
                    "agentId": "agent-evaluator",
                }
            ],
        },
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **kwargs: {
            "agentId": agent_id,
            "llmBindings": {
                "dialogue": {"modelId": "relay_openai/gpt-5.6-luna"}
            },
        },
    )
    monkeypatch.setattr(llm_review_runners, "get_config", lambda: base_config)
    monkeypatch.setattr(
        llm_review_runners,
        "config_for_agent_llm_model",
        fake_config_for_agent_llm_model,
    )
    monkeypatch.setattr(llm_review_runners, "get_llm_client", fake_get_llm_client)

    resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert captured == {
        "baseConfig": base_config,
        "model_id": "relay_openai/gpt-5.6-luna",
        "runtime_profile_id": "primary",
        "slot": "dialogue",
        "clientProfileId": "primary",
        "clientConfig": runtime_config,
    }
    assert resolved is not None
    assert resolved["providerId"] == "team-provider"
    assert resolved["agentId"] == "agent-evaluator"
    assert resolved["modelId"] == "team-model"
    assert resolved["modelRef"] == "team-provider/team-model"


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


def _formal_review_context(**overrides) -> dict:
    context = {
        **_review_context(),
        "questionId": "SCI-096",
        "_modelInvocationReceiptAuthority": {
            "schemaVersion": 1,
            "authorityKind": "workflow_run",
            "teamId": "team-1",
            "questionId": "SCI-096",
            "workflowRunId": "workflow-run-formal",
            "workflowId": "challenge-cup-research",
            "workflowVersionId": "workflow-version-formal",
            "modelPolicySha256": "a" * 64,
        },
    }
    context.update(overrides)
    return context


def _final_outcome(invocation_context, *, receipt=None, final_text=None) -> TurnOutcome:
    identity = CanonicalItemIdentity(
        session_id=invocation_context.session_id,
        turn_id=str(invocation_context.metadata["turnId"]),
        invocation_id=str(invocation_context.metadata["invocationId"]),
        iteration=0,
        item_id="review-final",
    )
    return TurnOutcome(
        kind="final_answer",
        identity=identity,
        final_text=(
            final_text
            if final_text is not None
            else json.dumps({"outcome": "left_wins", "justification": "A 领先"})
        ),
        terminal_event_seen=True,
        model_invocation_receipt=receipt,
    )


def test_review_receipt_context_binds_stable_unique_step_identity():
    context = _formal_review_context()
    route = {
        "modelRef": "opencode/deepseek-v4-flash",
        "providerId": "opencode",
        "modelId": "deepseek-v4-flash",
    }

    first = meeting_receipt_authority.build_review_step_receipt_context(
        context,
        review_step="reflection",
        identity_parts=("cand-a",),
        session_id="team-1",
        expected_model_route=route,
    )
    replay = meeting_receipt_authority.build_review_step_receipt_context(
        context,
        review_step="reflection",
        identity_parts=("cand-a",),
        session_id="team-1",
        expected_model_route=route,
    )
    pairwise = meeting_receipt_authority.build_review_step_receipt_context(
        context,
        review_step="pairwise",
        identity_parts=("cand-a", "cand-b"),
        session_id="team-1",
        expected_model_route=route,
    )

    assert first == replay
    assert first["invocationId"] != pairwise["invocationId"]
    assert first["questionStageBinding"]["questionStage"] == "review"
    assert first["questionStageBinding"]["formalNodeId"] == "hypothesis_design"
    assert first["outcomeKinds"] == ["review"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"teamId": "wrong-team"},
        {"questionId": "SCI-001"},
    ],
)
def test_review_receipt_context_rejects_authority_scope_mismatch(overrides):
    with pytest.raises(meeting_receipt_authority.MeetingReceiptAuthorityError):
        meeting_receipt_authority.build_review_step_receipt_context(
            _formal_review_context(**overrides),
            review_step="reflection",
            identity_parts=("cand-a",),
            session_id="team-1",
            expected_model_route={
                "modelRef": "opencode/deepseek-v4-flash",
                "providerId": "opencode",
                "modelId": "deepseek-v4-flash",
            },
        )


def test_review_receipt_context_rejects_invalid_model_route():
    with pytest.raises(
        meeting_receipt_authority.MeetingReceiptAuthorityError,
        match="model route",
    ):
        meeting_receipt_authority.build_review_step_receipt_context(
            _formal_review_context(),
            review_step="reflection",
            identity_parts=("cand-a",),
            session_id="team-1",
            expected_model_route={
                "modelRef": "other/deepseek-v4-flash",
                "providerId": "opencode",
                "modelId": "deepseek-v4-flash",
            },
        )


def test_receipt_required_runner_fails_before_provider_call_without_authority(monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_review_runners,
        "invoke_llm_outcome",
        lambda *_args, **_kwargs: calls.append(True),
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        dict(_FORMAL_FAKE_LLM), require_provider_receipts=True
    )

    with pytest.raises(ContractValidationError, match="authority"):
        runners["reflection_runner"](_candidate("cand-a", "假说 A"), _review_context())
    assert calls == []


def test_receipt_required_runner_rejects_provider_outcome_without_receipt(monkeypatch):
    monkeypatch.setattr(
        llm_review_runners,
        "invoke_llm_outcome",
        lambda *_args, **kwargs: _final_outcome(kwargs["context"]),
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        dict(_FORMAL_FAKE_LLM), require_provider_receipts=True
    )

    with pytest.raises(ContractValidationError, match="receipt"):
        runners["pairwise_runner"](
            _candidate("cand-a", "假说 A"),
            _candidate("cand-b", "假说 B"),
            _formal_review_context(),
        )


def test_receipt_required_runner_returns_provider_bound_result(monkeypatch):
    receipt = {
        "receiptId": "provider-review-receipt",
        "status": "succeeded",
    }
    monkeypatch.setattr(
        llm_review_runners,
        "invoke_llm_outcome",
        lambda *_args, **kwargs: _final_outcome(kwargs["context"], receipt=receipt),
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        dict(_FORMAL_FAKE_LLM), require_provider_receipts=True
    )

    result = runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"),
        _candidate("cand-b", "假说 B"),
        _formal_review_context(),
    )

    assert isinstance(result, ProviderBoundReviewResult)
    assert result.payload["outcome"] == "left_wins"
    assert result.model_invocation_receipt == receipt


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
    # Reflection calls may run concurrently; every candidate must receive the
    # same malformed payload so the failure surfaces from payload validation,
    # not from an exhausted fake queue.
    _install_fake_llm(monkeypatch, [payload, payload])
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


def _formal_step_receipt(step: str, marker: str) -> dict:
    receipt_id = f"provider-{step}-{marker}"
    return ModelInvocationReceipt.from_invocation(
        receipt_id=receipt_id,
        run_id="workflow-run-formal",
        node_run_id=f"review-node-{receipt_id}",
        scope={
            "questionId": "SCI-096",
            "workflowRunId": "workflow-run-formal",
            "questionStage": "review",
        },
        provider="opencode",
        model="deepseek-v4-flash",
        requested_model="deepseek-v4-flash",
        status=ModelInvocationStatus.SUCCEEDED,
        request_content={"receiptId": receipt_id},
        response_content={"ok": True},
        started_at_ms=10,
        finished_at_ms=20,
        retry_count=0,
        metadata={"questionStage": "review", "outcomeKinds": ["review"]},
        evidence_locator={"kind": "hypothesis_review_step"},
    ).to_dict()


def test_formal_parallel_runner_calls_see_only_their_own_receipt_scope(monkeypatch):
    """FORMAL receipt binding must survive bounded-parallel execution.

    ``model_invocation_receipt_context_scope`` is ContextVar-based: worker
    threads do not inherit the caller's context.  The binding works only
    because each runner enters the scope around its own invoke; this test
    drives real concurrent reflection calls and asserts every in-flight call
    reads back exactly the receipt authority minted for it.
    """

    from core.llm import client as llm_client

    captured: list[dict[str, str]] = []
    capture_lock = threading.Lock()
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
        },
        ensure_ascii=False,
    )
    payload_by_purpose = {
        "hypothesis_reflection": reflection_payload,
        "hypothesis_pairwise": json.dumps(
            {"outcome": "left_wins", "justification": "A 领先"}
        ),
        "hypothesis_pareto": json.dumps(
            {
                "paretoFrontCandidateIds": ["cand-a"],
                "dominatedCandidateIds": ["cand-b"],
                "notes": "B 被全维占优。",
            }
        ),
        "hypothesis_metareview": json.dumps(
            {
                "recommendationCandidateId": "cand-a",
                "rationale": "前沿且胜出。",
                "riskNotes": "",
                "accepted": True,
            }
        ),
    }

    def fake_invoke_llm_outcome(client, messages, context=None, **kwargs):
        assert context is not None
        purpose = str(context.metadata.get("purpose") or "")
        invocation_id = str(context.metadata.get("invocationId") or "")
        bound = llm_client._MODEL_INVOCATION_RECEIPT_CONTEXT.get()
        record = {
            "purpose": purpose,
            "invocationId": invocation_id,
            "scopeInvocationId": str((bound or {}).get("invocationId") or ""),
        }
        with capture_lock:
            captured.append(record)
        time.sleep(0.02)  # widen the concurrent window on purpose
        return _final_outcome(
            context,
            receipt=_formal_step_receipt(purpose, invocation_id),
            final_text=payload_by_purpose[purpose],
        )

    monkeypatch.setattr(llm_review_runners, "invoke_llm_outcome", fake_invoke_llm_outcome)
    runners = llm_review_runners.build_hypothesis_review_runners(
        dict(_FORMAL_FAKE_LLM), require_provider_receipts=True
    )
    context = _formal_review_context()

    result = execute_hypothesis_review(
        context,
        execution_mode="formal",
        **runners,
        reviewer_assignments={"metareview": "coordinator"},
    )

    # Two concurrent reflections plus pairwise/pareto/metareview: every call
    # must read back exactly its own binding while others are in flight.
    purposes = [record["purpose"] for record in captured]
    assert purposes.count("hypothesis_reflection") == 2
    for record in captured:
        assert record["scopeInvocationId"] == record["invocationId"]
    assert len({record["invocationId"] for record in captured}) == len(captured)
    receipts = result["modelInvocationReceipts"]
    assert [item["status"] for item in receipts] == ["succeeded"] * 5
    assert len({item["receiptId"] for item in receipts}) == 5


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


# ---------------------------------------------------------------------------
# Review-call timeout budget (SCI-096: a hung review-profile call pinned the
# meeting in summarizing for 33+ minutes while holding the summary lock)
# ---------------------------------------------------------------------------


def test_review_llm_call_timeout_seconds_env_override(monkeypatch):
    from core.web.services.team_workflow import challenge_deadline_policy

    monkeypatch.setattr(
        challenge_deadline_policy,
        "derive_per_call_budget",
        lambda *_args, **_kwargs: {"perCallBudgetMs": 450_000},
    )
    monkeypatch.delenv(
        llm_review_runners._REVIEW_LLM_CALL_TIMEOUT_ENV, raising=False
    )
    default = llm_review_runners.review_llm_call_timeout_seconds()
    assert default == 450.0

    monkeypatch.setenv(
        llm_review_runners._REVIEW_LLM_CALL_TIMEOUT_ENV, "420"
    )
    assert llm_review_runners.review_llm_call_timeout_seconds() == 420.0

    for junk in ("not-a-number", "0", "-3", "42.5", "601"):
        monkeypatch.setenv(
            llm_review_runners._REVIEW_LLM_CALL_TIMEOUT_ENV, junk
        )
        assert (
            llm_review_runners.review_llm_call_timeout_seconds()
            == 450.0
        )


def test_digest_drafter_times_out_with_structured_error(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr(llm_review_runners.time, "time", lambda: now[0])

    def hanging_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        now[0] = 1_001.0
        return _FakeResponse("{}")

    monkeypatch.setattr(llm_review_runners, "invoke_llm", hanging_invoke_llm)
    monkeypatch.setattr(
        llm_review_runners, "review_llm_call_timeout_seconds", lambda **_kwargs: 0.2
    )

    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    with pytest.raises(llm_review_runners.ReviewLLMTimeoutError) as exc_info:
        drafter(_meeting_round(), _source_messages())

    error = exc_info.value
    assert isinstance(error, LLMError)
    assert error.category == "cancelled"
    assert error.retryable is False
    assert error.purpose == "meeting_digest"
    assert error.timeout_seconds == 0.2
    assert "meeting_digest" in str(error)


def test_receipt_bound_runner_times_out_with_structured_error(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr(llm_review_runners.time, "time", lambda: now[0])

    def hanging_invoke_outcome(client, messages, tools=None, context=None, **kwargs):
        now[0] = 1_001.0
        return object()

    monkeypatch.setattr(llm_review_runners, "invoke_llm_outcome", hanging_invoke_outcome)
    monkeypatch.setattr(
        llm_review_runners, "review_llm_call_timeout_seconds", lambda **_kwargs: 0.2
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        dict(_FORMAL_FAKE_LLM), require_provider_receipts=True
    )
    context = _formal_review_context()
    with pytest.raises(llm_review_runners.ReviewLLMTimeoutError) as exc_info:
        runners["pairwise_runner"](
            _candidate("cand-a", "假说 A"),
            _candidate("cand-b", "假说 B"),
            context,
        )

    assert exc_info.value.purpose == "hypothesis_pairwise"
    assert exc_info.value.category == "cancelled"
    assert exc_info.value.retryable is False
