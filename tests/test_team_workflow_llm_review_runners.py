"""LLM review runners wiring tests.

Covers the real-model wiring layer for the human-click review chain:

* availability resolution is fail-open at the fixture boundary (no model →
  DEV fixtures stay in charge) and the conftest autouse fixture pins it to
  ``None`` so the suite never touches real provider credentials; every
  fallback branch announces itself with a warning log and a quiet scene
  event naming the missing configuration, so the fallback is never silent;
* an injected fake LLM produces executor-compatible outputs for the digest
  drafter and the four review runners (reflection / pairwise / Pareto /
  MetaReview), including the server-owned ``sourceMessageRefs`` and the
  ``llm:<model>`` reviewer attribution;
* malformed model output fails closed with ``ContractValidationError``
  before anything is persisted;
* the runners compose with ``execute_hypothesis_review`` end to end;
* a ``mode=formal`` hypothesis-review meeting fails closed at closure time
  when no real receipt-bound runners resolve, while dev/platform scopes and
  candidate-generation closures keep the fixture fallback.

No real model or network is involved.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from core.llm.types import CanonicalItemIdentity, LLMError, TurnOutcome
from core.research.competition.question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
)
from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.hypothesis_quality import (
    AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS,
    HYPOTHESIS_SCORE_DIMENSIONS,
)
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
from core.web.services.team_workflow.research_runtime.hypothesis_first_chain import (
    HypothesisFirstChainError,
)

_RESOLVE_REVIEW_LLM_UNDER_TEST = llm_review_runners.resolve_review_llm
_FAKE_LLM = {"client": object(), "profileId": "primary", "modelId": "fake-review-model"}
_FORMAL_FAKE_LLM = {
    **_FAKE_LLM,
    "providerId": "opencode",
    "modelId": "deepseek-v4-flash",
    "modelRef": "opencode/deepseek-v4-flash",
}
_EVIDENCE_REF = (
    "evidence_card_batch://team-1/source-1/"
    "0123456789abcdef0123456789abcdef"
)


class _FakeResponse:
    def __init__(self, content: str, *, response_metadata: dict | None = None):
        self.content = content
        self.response_metadata = dict(response_metadata or {})


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


@pytest.fixture(autouse=True)
def _redirect_failure_dumps_to_tmp(tmp_path, monkeypatch):
    """Keep failure-dump evidence inside the per-test temp directory."""

    dump_dir = tmp_path / "review-llm-failure-dumps"
    monkeypatch.setattr(
        llm_review_runners,
        "_REVIEW_LLM_FAILURE_DUMP_DIR_OVERRIDE",
        str(dump_dir),
    )
    yield dump_dir


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
# Unavailable diagnostics: the fixture fallback is never silent
# ---------------------------------------------------------------------------

_REVIEW_LLM_LOGGER = "core.web.services.team_workflow.llm_review_runners"


@pytest.fixture()
def review_llm_scene_events(monkeypatch):
    """Capture the quiet scene events emitted by the resolution fallback."""

    from core.web.services import runtime_scene_service

    events: list[dict[str, Any]] = []

    def _capture(*args, **kwargs):
        events.append({"args": args, "kwargs": kwargs})
        return {"accepted": True}

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        _capture,
    )
    return events


def _assert_unavailable_scene_event(events, reason: str) -> dict[str, Any]:
    matching = [
        event
        for event in events
        if event["args"][2:3] == ("review_llm.resolve.unavailable",)
        and isinstance(event["kwargs"].get("fields"), dict)
        and event["kwargs"]["fields"].get("reason") == reason
    ]
    assert matching, f"expected an unavailable scene event for {reason}: {events}"
    event = matching[0]
    assert event["args"][:2] == ("team_workflow", "review_llm")
    assert event["kwargs"]["level"] == "warning"
    assert event["kwargs"]["outcome"] == "fallback_dev_fixture"
    assert event["kwargs"]["lifecycle"] is False
    return event


def _patch_review_team(monkeypatch, *, team, agent):
    monkeypatch.setattr(team_service, "get_team_light", lambda team_id: team)
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **kwargs: agent,
    )


def _evaluator_team(agent_id: str | None = "agent-evaluator"):
    members = [] if agent_id is None else [
        {"role": "challenge_cup_evaluator", "agentId": agent_id},
    ]
    return {"teamId": "challenge-cup", "members": members}


def _bound_evaluator_agent(model_id: str = "relay_openai/gpt-5.6-luna"):
    return {
        "agentId": "agent-evaluator",
        "llmBindings": {"dialogue": {"modelId": model_id}},
    }


class _UnavailableClient:
    """Provider/profile pair driving the post-client fallback branches."""

    def __init__(
        self,
        *,
        model: str = "",
        api_key: str = "",
        api_key_env: str = "",
        requires_api_key: bool = True,
    ):
        self.profile = type("Profile", (), {"model": model})()
        self.provider = type(
            "Provider",
            (),
            {
                "provider_id": "team-provider",
                "api_key": api_key,
                "api_key_env": api_key_env,
                "requires_api_key": requires_api_key,
            },
        )()


def test_resolve_review_llm_reports_resolve_error_instead_of_silent_fallback(
    monkeypatch, caplog, review_llm_scene_events
):
    def broken_team_lookup(team_id):
        raise RuntimeError("team store unavailable")

    monkeypatch.setattr(team_service, "get_team_light", broken_team_lookup)

    with caplog.at_level(logging.WARNING, logger=_REVIEW_LLM_LOGGER):
        resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is None
    assert "resolve_error" in caplog.text
    assert "RuntimeError: team store unavailable" in caplog.text
    _assert_unavailable_scene_event(review_llm_scene_events, "resolve_error")


def test_resolve_review_llm_reports_missing_evaluator_role(
    monkeypatch, caplog, review_llm_scene_events
):
    _patch_review_team(
        monkeypatch,
        team=_evaluator_team(agent_id=None),
        agent=None,
    )

    with caplog.at_level(logging.WARNING, logger=_REVIEW_LLM_LOGGER):
        resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is None
    assert "evaluator_agent_missing" in caplog.text
    assert "challenge_cup_evaluator role" in caplog.text
    _assert_unavailable_scene_event(review_llm_scene_events, "evaluator_agent_missing")


def test_resolve_review_llm_reports_missing_or_archived_evaluator_agent(
    monkeypatch, caplog, review_llm_scene_events
):
    _patch_review_team(
        monkeypatch,
        team=_evaluator_team(),
        agent=None,
    )

    with caplog.at_level(logging.WARNING, logger=_REVIEW_LLM_LOGGER):
        resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is None
    assert "evaluator_agent_missing" in caplog.text
    assert "agent-evaluator" in caplog.text
    _assert_unavailable_scene_event(review_llm_scene_events, "evaluator_agent_missing")


def test_resolve_review_llm_reports_unbound_evaluator_model(
    monkeypatch, caplog, review_llm_scene_events
):
    _patch_review_team(
        monkeypatch,
        team=_evaluator_team(),
        agent={"agentId": "agent-evaluator", "llmBindings": {}},
    )

    with caplog.at_level(logging.WARNING, logger=_REVIEW_LLM_LOGGER):
        resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is None
    assert "evaluator_model_unbound" in caplog.text
    assert "agent-evaluator" in caplog.text
    _assert_unavailable_scene_event(review_llm_scene_events, "evaluator_model_unbound")


def test_resolve_review_llm_reports_client_build_error(
    monkeypatch, caplog, review_llm_scene_events
):
    _patch_review_team(
        monkeypatch,
        team=_evaluator_team(),
        agent=_bound_evaluator_agent(),
    )

    def broken_client_build(*args, **kwargs):
        raise RuntimeError("runtime profile projection failed")

    monkeypatch.setattr(
        llm_review_runners, "config_for_agent_llm_model", broken_client_build
    )

    with caplog.at_level(logging.WARNING, logger=_REVIEW_LLM_LOGGER):
        resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is None
    assert "client_build_error" in caplog.text
    assert "RuntimeError: runtime profile projection failed" in caplog.text
    _assert_unavailable_scene_event(review_llm_scene_events, "client_build_error")


def test_resolve_review_llm_reports_unresolved_profile_model(
    monkeypatch, caplog, review_llm_scene_events
):
    _patch_review_team(
        monkeypatch,
        team=_evaluator_team(),
        agent=_bound_evaluator_agent(),
    )
    monkeypatch.setattr(
        llm_review_runners,
        "get_llm_client",
        lambda **kwargs: _UnavailableClient(model="  "),
    )

    with caplog.at_level(logging.WARNING, logger=_REVIEW_LLM_LOGGER):
        resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is None
    assert "model_unresolved" in caplog.text
    _assert_unavailable_scene_event(review_llm_scene_events, "model_unresolved")


def test_resolve_review_llm_reports_missing_provider_credentials(
    monkeypatch, caplog, review_llm_scene_events
):
    _patch_review_team(
        monkeypatch,
        team=_evaluator_team(),
        agent=_bound_evaluator_agent(),
    )
    monkeypatch.setattr(
        llm_review_runners,
        "get_llm_client",
        lambda **kwargs: _UnavailableClient(model="team-model"),
    )

    with caplog.at_level(logging.WARNING, logger=_REVIEW_LLM_LOGGER):
        resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is None
    assert "provider_credentials_missing" in caplog.text
    assert "team-provider" in caplog.text
    _assert_unavailable_scene_event(review_llm_scene_events, "provider_credentials_missing")


def test_resolve_review_llm_still_resolves_via_api_key_env_fallback(
    monkeypatch, review_llm_scene_events
):
    """The env-var credential fallback must keep resolving (no over-blocking)."""

    _patch_review_team(
        monkeypatch,
        team=_evaluator_team(),
        agent=_bound_evaluator_agent(),
    )
    monkeypatch.setattr(
        llm_review_runners,
        "get_llm_client",
        lambda **kwargs: _UnavailableClient(
            model="team-model", api_key_env="VIBELUTION_TEST_REVIEW_API_KEY"
        ),
    )
    monkeypatch.setenv("VIBELUTION_TEST_REVIEW_API_KEY", "env-provided")

    resolved = _RESOLVE_REVIEW_LLM_UNDER_TEST()

    assert resolved is not None
    assert resolved["modelId"] == "team-model"
    assert review_llm_scene_events == []


# ---------------------------------------------------------------------------
# Formal fence: formal review meetings never close onto DEV fixtures
# ---------------------------------------------------------------------------


def _formal_fence_env(monkeypatch, *, mode: str, meeting_type: str = "hypothesis_review"):
    from core.web.services.team_workflow import meeting_rounds
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    meeting_round = _meeting_round(mode=mode, meetingType=meeting_type)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda team_id: team_id)
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, round_id: {"meetingRound": meeting_round},
    )
    captured: dict[str, Any] = {}

    def fake_build_runners(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        llm_review_runners, "build_hypothesis_review_runners", fake_build_runners
    )
    return hypothesis_first_chain, meeting_rounds, meeting_round, captured


def test_formal_review_meeting_close_fails_closed_without_real_runners(monkeypatch):
    chain, meeting_rounds, _meeting_round, captured = _formal_fence_env(
        monkeypatch, mode="formal"
    )

    def _must_not_close(*args, **kwargs):
        raise AssertionError("formal closure must fail before approve_meeting_closure")

    monkeypatch.setattr(meeting_rounds, "approve_meeting_closure", _must_not_close)

    with pytest.raises(HypothesisFirstChainError) as excinfo:
        chain.close_review_meeting("team-1", "meeting-1", {})

    assert captured == {"require_provider_receipts": True}
    message = str(excinfo.value)
    assert "meeting-1" in message
    assert "cannot close" in message
    assert "receipt-bound review runners" in message
    assert "dev/platform scope" in message


def test_dev_review_meeting_close_keeps_fixture_fallback(monkeypatch):
    chain, meeting_rounds, meeting_round, captured = _formal_fence_env(
        monkeypatch, mode="dev"
    )
    approved: list[str] = []
    monkeypatch.setattr(
        meeting_rounds,
        "approve_meeting_closure",
        lambda team_id, round_id, request: approved.append(round_id)
        or {"meetingRound": {**meeting_round, "status": "closed"}},
    )
    monkeypatch.setattr(
        chain,
        "_process_collection_decisions",
        lambda *args, **kwargs: {"requests": [], "skipped": []},
    )
    monkeypatch.setattr(
        chain,
        "_generate_hypothesis_round",
        lambda *args, **kwargs: {"status": "created", "round": {"status": "closed"}},
    )
    monkeypatch.setattr(chain, "_record_policy_shadow_decisions", lambda *a, **k: None)
    monkeypatch.setattr(chain, "_auto_advance_converge_tick", lambda *a, **k: None)

    result = chain.close_review_meeting("team-1", "meeting-1", {})

    assert approved == ["meeting-1"]
    assert captured == {"require_provider_receipts": False}
    assert result["hypothesisRound"]["status"] == "created"


def test_formal_generation_meeting_close_does_not_require_review_runners(monkeypatch):
    """Candidate-generation closures never consume review runners."""

    chain, _meeting_rounds, meeting_round, captured = _formal_fence_env(
        monkeypatch, mode="formal", meeting_type="hypothesis_candidate_generation"
    )
    sentinel = {"status": "closed", "meetingRound": meeting_round}
    monkeypatch.setattr(chain, "_close_generation_meeting", lambda *args, **k: sentinel)

    result = chain.close_review_meeting("team-1", "meeting-1", {})

    assert result is sentinel
    assert captured == {"require_provider_receipts": True}


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


def test_digest_drafter_uses_llm_markdown_and_server_owned_refs(monkeypatch):
    payload = """# 候选 A/B 评审纪要

## 会议结论

评审完成，倾向候选 A。

## 关键讨论

- 候选 A 更契合赛题。
"""
    _install_fake_llm(monkeypatch, [payload])

    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    assert drafter is not None
    digest = drafter(_meeting_round(), _source_messages())

    assert digest["summary"] == "评审完成，倾向候选 A。"
    assert digest["documentMarkdown"] == payload.strip()
    assert digest["documentTemplateId"] == "open_sections_v1"
    assert digest["discussionTopics"] == ["评审候选 A/B"]
    assert "agreements" not in digest
    # sourceMessageRefs are server-owned: only completed, non-pass messages.
    refs = digest["sourceMessageRefs"]
    assert isinstance(refs, list) and len(refs) == 2


def test_digest_observability_records_bounded_chain_metrics(monkeypatch):
    from core.web.services import runtime_scene_service
    from core.web.services.team_workflow import meeting_runtime

    payload = """# 候选 A/B 评审纪要

## 会议结论

评审完成，倾向候选 A。

## 关键讨论

- 仅保留必要结论。
"""
    events: list[dict] = []

    def capture_event(component, phase, event_code, **kwargs):
        events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )
        return {"accepted": True}

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        return _FakeResponse(
            payload,
            response_metadata={
                "finish_reason": "stop",
                "usage_observation": {
                    "input_tokens": 120,
                    "output_tokens": 45,
                    "reasoning_output_tokens": 11,
                    "total_tokens": 165,
                },
            },
        )

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        capture_event,
    )
    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)

    drafter = llm_review_runners.build_meeting_digest_drafter(
        {
            **_FAKE_LLM,
            "providerId": "fake-provider",
            "modelRef": "fake-provider/fake-review-model",
        }
    )
    assert drafter is not None
    digest = drafter(_meeting_round(), _source_messages())
    monkeypatch.setattr(
        meeting_runtime.meeting_rounds,
        "completed_meeting_source_messages",
        lambda _meeting_round: _source_messages()[:2],
    )
    meeting_runtime.build_meeting_digest_draft(
        _meeting_round(),
        _source_messages(),
        drafter=lambda *_args: digest,
    )

    by_code = {event["eventCode"]: event for event in events}
    started = by_code["meeting_digest.llm.started"]["fields"]
    completed = by_code["meeting_digest.llm.completed"]["fields"]
    contract = by_code["meeting_digest.contract.validated"]["fields"]
    ledger = by_code["meeting_digest.fact_ledger.projected"]["fields"]

    assert started["meetingRoundId"] == "meeting-1"
    assert started["providerId"] == "fake-provider"
    assert started["messageCount"] == 2
    assert started["inputChars"] > 0
    assert completed["finishReason"] == "stop"
    assert completed["inputTokens"] == 120
    assert completed["outputTokens"] == 45
    assert completed["reasoningOutputTokens"] == 11
    assert completed["outputChars"] == len(payload)
    assert contract == {
        "teamId": "team-1",
        "meetingRoundId": "meeting-1",
        "hasH1": True,
        "hasConclusionSection": True,
        "sectionCount": 2,
        "documentChars": len(payload.strip()),
    }
    assert ledger["sourceMessageRefCount"] == 2
    serialized_events = json.dumps(events, ensure_ascii=False)
    assert "候选 A 更契合赛题" not in serialized_events
    assert "只依据给出的会议发言" not in serialized_events


def test_digest_observability_classifies_timeout_without_logging_content(monkeypatch):
    from core.web.services import runtime_scene_service

    events: list[dict] = []

    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        lambda component, phase, event_code, **kwargs: events.append(
            {"eventCode": event_code, **kwargs}
        ),
    )

    def timeout(*_args, **_kwargs):
        raise llm_review_runners.ReviewLLMTimeoutError(
            purpose="meeting_digest", timeout_seconds=450
        )

    monkeypatch.setattr(llm_review_runners, "_invoke_llm_with_timeout", timeout)
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))

    with pytest.raises(llm_review_runners.ReviewLLMTimeoutError):
        drafter(_meeting_round(), _source_messages())

    failed = next(
        event for event in events if event["eventCode"] == "meeting_digest.llm.failed"
    )
    assert failed["fields"]["errorCategory"] == "timeout"
    assert failed["fields"]["errorType"] == "ReviewLLMTimeoutError"
    assert "候选 A 更契合赛题" not in json.dumps(events, ensure_ascii=False)


def test_digest_observability_outage_does_not_change_business_result(monkeypatch):
    from core.web.services import runtime_scene_service

    _install_fake_llm(
        monkeypatch,
        ["# 评审纪要\n\n## 会议结论\n\n纪要仍应正常生成。"],
    )
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scene down")),
    )
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))

    digest = drafter(_meeting_round(), _source_messages())

    assert digest["summary"] == "纪要仍应正常生成。"


def test_digest_prompt_requests_open_markdown_instead_of_protocol_fact_json():
    """The digest model owns prose; protocol facts stay in the source-ledger path."""

    prompt = llm_review_runners._DIGEST_SYSTEM_PROMPT
    assert "Markdown" in prompt
    assert "自行选择" in prompt
    assert "不要输出 JSON" in prompt
    assert "协议事实" in prompt
    assert "proposedCandidates" not in prompt
    assert "evidenceRequests" not in prompt


def _digest_effort_client(profile_attrs: dict):
    from types import SimpleNamespace

    return SimpleNamespace(profile=SimpleNamespace(**profile_attrs))


def test_digest_drafter_disables_provider_thinking_for_the_call():
    """SCI-007 regression: qwen3.8-max's default provider-side thinking pass
    alone outran the governed 600s per-call fence, so the digest drafter
    call never returned and the meeting stayed ``summarizing`` with zero
    digest/candidates.  The drafter pins ``thinking_type="disabled"`` so
    the qwen thinking channel (``enable_thinking: false``) is emitted."""

    profile_attrs = {"thinking_type": ""}
    client = _digest_effort_client(profile_attrs)
    drafter = llm_review_runners.build_meeting_digest_drafter(
        {**_FAKE_LLM, "client": client}
    )
    assert callable(drafter)
    assert client.profile.thinking_type == "disabled"


def test_digest_drafter_client_without_profile_is_untouched():
    """Injected bare clients (existing fake shape) keep working."""

    client = object()
    drafter = llm_review_runners.build_meeting_digest_drafter(
        {**_FAKE_LLM, "client": client}
    )
    assert callable(drafter)


def test_digest_drafter_fails_closed_without_completed_messages(monkeypatch):
    _install_fake_llm(monkeypatch, ["{}"])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    with pytest.raises(ContractValidationError):
        drafter(_meeting_round(), [{"status": "failed", "content": "x"}])


def test_digest_transcript_keeps_the_full_completed_message():
    content = "前序论证" * 400 + "尾部限定条件"

    transcript = llm_review_runners._meeting_transcript(
        [{"status": "completed", "participantId": "p-1", "content": content}]
    )

    assert transcript == [{"speaker": "p-1", "content": content}]


def test_digest_drafter_fails_closed_on_empty_markdown(monkeypatch):
    _install_fake_llm(monkeypatch, ["   "])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    with pytest.raises(ContractValidationError):
        drafter(_meeting_round(), _source_messages())


def test_digest_drafter_fails_closed_without_required_markdown_structure(monkeypatch):
    _install_fake_llm(monkeypatch, ["只有一段没有标题的纪要。"])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    with pytest.raises(ContractValidationError, match="H1 title"):
        drafter(_meeting_round(), _source_messages())


def test_digest_drafter_requires_conclusion_section(monkeypatch):
    _install_fake_llm(monkeypatch, ["# 评审纪要\n\n## 关键讨论\n\n候选 A 更契合赛题。"])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    with pytest.raises(ContractValidationError, match="会议结论"):
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


def _dimension_review_rows(
    candidate_id: str,
    *,
    evidence_refs: list[str] | None = None,
) -> list[dict[str, object]]:
    return [
        {
            "hypothesis_id": candidate_id,
            "dimension": dimension,
            "rating": "adequate",
            "rationale": f"{candidate_id} {dimension} 审计依据",
            "reviewer": "model-output-is-server-overridden",
            "evidence_refs": list(evidence_refs or []),
        }
        for dimension in REQUIRED_REVIEW_DIMENSIONS
    ]


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
    revision = meeting_receipt_authority.build_review_step_receipt_context(
        context,
        review_step="revision",
        identity_parts=("cand-a", "meta-1"),
        session_id="team-1",
        expected_model_route=route,
    )

    assert first == replay
    assert first["invocationId"] != pairwise["invocationId"]
    assert first["questionStageBinding"]["questionStage"] == "review"
    assert first["questionStageBinding"]["formalNodeId"] == "hypothesis_design"
    assert first["outcomeKinds"] == ["review"]
    assert revision["outcomeKinds"] == ["review", "revision"]
    assert revision["invocationId"] not in {
        first["invocationId"],
        pairwise["invocationId"],
    }


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
            "dimensionReviews": _dimension_review_rows("cand-a"),
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
    revision_payload = json.dumps(
        {
            "revisedCandidate": {
                **_candidate("cand-a", "假说 A（收窄到目标人群）"),
            },
            "changes": ["收窄目标人群"],
            "unresolvedIssues": ["外部有效性待验证"],
        },
        ensure_ascii=False,
    )
    _install_fake_llm(
        monkeypatch,
        [
            reflection_payload,
            pairwise_payload,
            pareto_payload,
            metareview_payload,
            revision_payload,
        ],
    )

    context = _review_context()
    reflection = runners["reflection_runner"](dict(context["candidates"][0]), context)
    assert reflection["reviewedBy"] == f"llm:{_FAKE_LLM['modelId']}"
    assert {
        row["dimension"] for row in reflection["dimensionReviews"]
    } == set(REQUIRED_REVIEW_DIMENSIONS)
    assert all(
        row["hypothesis_id"] == "cand-a"
        and row["reviewer"] == f"llm:{_FAKE_LLM['modelId']}"
        for row in reflection["dimensionReviews"]
    )

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

    revision = runners["revision_runner"](
        context,
        context["candidates"][0],
        context["candidates"],
        {**metareview, "metaReviewId": "meta-1"},
    )
    assert revision["revisedCandidate"]["claim"] == "假说 A（收窄到目标人群）"


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


def test_reflection_runner_rejects_5_plus_2_rows_as_audit_dimensions(monkeypatch):
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    score_dimensions = [
        *HYPOTHESIS_SCORE_DIMENSIONS,
        *AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS,
    ]
    payload = json.dumps(
        {
            "claim": "假说 A",
            "rationale": "错误地把 5+2 当作审计七维。",
            "differenceFromAlternatives": "机制不同",
            "scores": {
                dimension: 0.7 for dimension in HYPOTHESIS_SCORE_DIMENSIONS
            },
            "dimensionReviews": [
                {
                    "dimension": dimension,
                    "rating": "adequate",
                    "rationale": f"错误维度 {dimension}",
                    "evidence_refs": [],
                }
                for dimension in score_dimensions
            ],
        },
        ensure_ascii=False,
    )
    _install_fake_llm(monkeypatch, [payload])

    with pytest.raises(ContractValidationError, match="audit dimensions"):
        runners["reflection_runner"](
            dict(_review_context()["candidates"][0]),
            _review_context(),
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
        metadata={
            "questionStage": "review",
            "outcomeKinds": (
                ["review", "revision"]
                if "revision" in step
                else ["review"]
            ),
        },
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
            "dimensionReviews": _dimension_review_rows("model-placeholder"),
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
        "hypothesis_revision": json.dumps(
            {
                "revisedCandidate": {
                    **_candidate("cand-a", "假说 A（根据评审收窄边界）"),
                },
                "changes": ["收窄适用边界"],
                "unresolvedIssues": ["外部有效性待验证"],
            },
            ensure_ascii=False,
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

    # Two concurrent reflections plus pairwise/metareview/revision: every call
    # must read back exactly its own binding while others are in flight.  The
    # N=2 Pareto step is decided locally and issues no provider call.
    purposes = [record["purpose"] for record in captured]
    assert purposes.count("hypothesis_reflection") == 2
    assert "hypothesis_pareto" not in purposes
    for record in captured:
        assert record["scopeInvocationId"] == record["invocationId"]
    assert len({record["invocationId"] for record in captured}) == len(captured)
    receipts = result["modelInvocationReceipts"]
    assert [item["status"] for item in receipts] == ["succeeded"] * 5
    assert len({item["receiptId"] for item in receipts}) == 5
    assert receipts[-1]["metadata"]["outcomeKinds"] == ["review", "revision"]


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
    for candidate_id, claim, scores in (
        ("cand-a", "假说 A", scores_a),
        ("cand-b", "假说 B", scores_b),
    ):
        payloads.append(
            json.dumps(
                {
                    "claim": claim,
                    "rationale": "评分依据。",
                    "differenceFromAlternatives": "不同",
                    "lineageRefs": [],
                    "scores": scores,
                    "status": "reviewed",
                    "dimensionReviews": _dimension_review_rows(candidate_id),
                },
                ensure_ascii=False,
            )
        )
    # pairwise for the single pair
    payloads.append(json.dumps({"outcome": "left_wins", "justification": "A 领先。"}))
    # pareto: N=2 is decided locally by deterministic dominance, so the model
    # is never called for the Pareto step and no payload is queued for it.
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
    queue = _install_fake_llm(monkeypatch, payloads)
    # The reflection wave issues its two calls concurrently, so a shared FIFO
    # queue can hand cand-a's payload to cand-b's call (and vice versa) —
    # a test-fake race, not product behavior.  Bind reflection payloads to
    # the candidate id carried by the request instead of pop order.
    reflection_by_candidate = {
        "cand-a": payloads[0],
        "cand-b": payloads[1],
    }

    def ordered_fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        assert context is not None, "review calls must carry an invocation context"
        request = json.loads(str(messages[-1].get("content") or "{}"))
        candidate_id = str(
            (request.get("candidate") or {}).get("candidateId") or ""
        )
        if candidate_id in reflection_by_candidate:
            queue.pop(0)  # keep the ordered queue accounting in sync
            return _FakeResponse(reflection_by_candidate.pop(candidate_id))
        return _FakeResponse(queue.pop(0))

    monkeypatch.setattr(
        llm_review_runners, "invoke_llm", ordered_fake_invoke_llm
    )

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
    # The Pareto partition came from the local dominance decision, not a call.
    assert queue == []
    assert result["pareto"]["paretoFrontCandidateIds"] == ["cand-a"]
    assert result["pareto"]["dominatedCandidateIds"] == ["cand-b"]


def test_runner_executor_round_and_review_artifacts_integrate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow import hypothesis_rounds
    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_artifact_writer,
        review_independence_artifact_writer,
    )

    context = _review_context()
    context["candidates"][0].update(
        {
            "claim": "候选 A 通过事件相机稀疏编码降低边缘推理延迟",
            "differenceFromAlternatives": "采用事件驱动稀疏编码机制",
        }
    )
    context["candidates"][1].update(
        {
            "claim": "候选 B 通过时序蒸馏提高弱光场景识别稳定性",
            "differenceFromAlternatives": "采用教师学生时序蒸馏机制",
        }
    )
    for candidate in context["candidates"]:
        candidate["evidenceRefs"] = [_EVIDENCE_REF]

    def fake_invoke_llm(client, messages, tools=None, invocation_context=None, context=None, **kwargs):
        call_context = invocation_context or context
        purpose = str(call_context.metadata.get("purpose") or "")
        request = json.loads(messages[-1]["content"])
        if purpose == "hypothesis_reflection":
            candidate = request["candidate"]
            candidate_id = candidate["candidateId"]
            return _FakeResponse(
                json.dumps(
                    {
                        "claim": candidate["claim"],
                        "rationale": f"{candidate_id} 五维评分依据",
                        "differenceFromAlternatives": candidate[
                            "differenceFromAlternatives"
                        ],
                        "lineageRefs": [],
                        "scores": {
                            "novelty": 0.8 if candidate_id == "cand-a" else 0.6,
                            "competitionFit": 0.8,
                            "falsifiability": 0.75,
                            "evidenceSupport": 0.7,
                            "feasibility": 0.8,
                        },
                        "dimensionReviews": _dimension_review_rows(
                            candidate_id,
                            evidence_refs=[_EVIDENCE_REF],
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        if purpose == "hypothesis_pairwise":
            return _FakeResponse(
                json.dumps(
                    {"outcome": "left_wins", "justification": "左侧证据更完整"},
                    ensure_ascii=False,
                )
            )
        if purpose == "hypothesis_pareto":
            return _FakeResponse(
                json.dumps(
                    {
                        "paretoFrontCandidateIds": ["cand-a"],
                        "dominatedCandidateIds": ["cand-b"],
                        "notes": "cand-a 位于前沿",
                    },
                    ensure_ascii=False,
                )
            )
        return _FakeResponse(
            json.dumps(
                {
                    "recommendationCandidateId": "cand-a",
                    "rationale": "审计七维与五维决策均支持 cand-a",
                    "riskNotes": "仍需第一阶段修订",
                    "accepted": True,
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    review = execute_hypothesis_review(
        context,
        round_id="round-integration",
        **runners,
        reviewer_assignments={"metareview": "coordinator-1"},
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(
        hypothesis_rounds,
        "_storage_path",
        lambda _team_id: tmp_path / "hypothesis_rounds.jsonl",
    )
    round_result = hypothesis_rounds.create_hypothesis_round(
        "team-1",
        {
            "program": "XH-202619",
            "theme": "direction-1a",
            "campaign": "challenge-stage-one",
            "question": "SCI-091",
            "branch": "main",
            "workflow": "hypothesis_and_plan",
            "agentId": "coordinator-1",
            "mode": "dev",
            "roundId": "round-integration",
            "status": "closed",
            **review,
            "meetingRefs": [
                {"kind": "meeting_round", "id": "meeting-1"},
                {"kind": "meeting_digest", "id": "digest-1"},
                {"kind": "decision_record", "id": "decision-1"},
            ],
            "closedBy": "coordinator-1",
            "closedAt": "2026-09-01T00:00:00Z",
        },
    )
    round_record = round_result["round"]

    def fake_put(team_id, **kwargs):
        return {
            "recordId": kwargs["artifact_identity"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": dimension_reviews_artifact_writer.canonical_sha256(
                kwargs["payload"]
            ),
        }

    monkeypatch.setattr(
        dimension_reviews_artifact_writer, "put_workflow_artifact", fake_put
    )
    monkeypatch.setattr(
        dimension_reviews_artifact_writer,
        "read_domain_artifact",
        lambda _ref: object(),
    )
    monkeypatch.setattr(
        review_independence_artifact_writer, "put_workflow_artifact", fake_put
    )
    dimensions = dimension_reviews_artifact_writer.materialize_dimension_reviews_authority(
        team_id="team-1",
        workflow_run_id="workflow-1",
        node_run_id="node-1",
        question_id="SCI-091",
        selection_id="selection-1",
        review_round_id="round-integration",
        input_refs=[_EVIDENCE_REF],
        input_snapshot_hash="a" * 64,
        candidates=round_record["candidates"],
        review=round_record,
        workflow_authority={
            "authorityKind": "workflow_run",
            "teamId": "team-1",
            "questionId": "SCI-091",
            "workflowRunId": "workflow-1",
        },
        source_collection_run_id="source-1",
    )
    independence = review_independence_artifact_writer.write_review_independence_artifacts(
        team_id="team-1",
        workflow_run_id="workflow-1",
        node_run_id="node-1",
        review_round_id="round-integration",
        review=round_record,
        reviewer_assignments=round_record["roles"],
        source_collection_run_id="source-1",
    )

    assert dimensions["status"] == "written"
    assert independence["status"] == "written"
    assert len(round_record["candidates"][0]["dimensionReviews"]) == 7


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


# ---------------------------------------------------------------------------
# Failed-response evidence dump (offline attribution support)
# ---------------------------------------------------------------------------


def _failure_dump_dir(dump_dir: Path) -> list[Path]:
    if not dump_dir.exists():
        return []
    return sorted(dump_dir.glob("*.json"))


def _read_dump(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_failed_review_call_dumps_raw_response_for_offline_triage(
    monkeypatch, _redirect_failure_dumps_to_tmp
):
    dump_dir = _redirect_failure_dumps_to_tmp
    malformed = "这是非 JSON 的模型回复 {broken"
    _install_fake_llm(monkeypatch, [malformed])
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    context = _review_context()

    with pytest.raises(ContractValidationError, match="did not return valid JSON"):
        runners["reflection_runner"](_candidate("cand-a", "假说 A"), context)

    dumps = _failure_dump_dir(dump_dir)
    assert len(dumps) == 1
    record = _read_dump(dumps[0])
    assert record["schemaVersion"] == 1
    assert record["purpose"] == "hypothesis_reflection"
    assert record["failureCategory"] == "contract_validation"
    assert record["errorType"] == "ContractValidationError"
    assert record["rawResponse"] == malformed
    assert record["responseChars"] == len(malformed)
    assert record["sessionId"] == "team-1"
    assert record["contextId"] == "ctx-1"
    assert record["capturedAt"]
    # Bounded identity only: no credentials or prompt material in the dump.
    assert "api_key" not in json.dumps(record)
    assert "messages" not in record


def test_timeout_failure_dumps_with_timeout_category_and_empty_response(
    monkeypatch, _redirect_failure_dumps_to_tmp
):
    dump_dir = _redirect_failure_dumps_to_tmp
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
    with pytest.raises(llm_review_runners.ReviewLLMTimeoutError):
        drafter(_meeting_round(), _source_messages())

    dumps = _failure_dump_dir(dump_dir)
    assert len(dumps) == 1
    record = _read_dump(dumps[0])
    assert record["purpose"] == "meeting_digest"
    assert record["failureCategory"] == "timeout"
    assert record["errorType"] == "ReviewLLMTimeoutError"
    # The call never returned, so there is no raw response to keep.
    assert record["rawResponse"] == ""
    assert record["meetingRoundId"] == "meeting-1"


def test_receipt_bound_runner_invalid_json_dumps_outcome_final_text(
    monkeypatch, _redirect_failure_dumps_to_tmp
):
    dump_dir = _redirect_failure_dumps_to_tmp
    malformed = "模型说：这不是 JSON"

    def fake_invoke_llm_outcome(client, messages, context=None, **kwargs):
        invocation_id = str(context.metadata.get("invocationId") or "")
        return _final_outcome(
            context,
            receipt=_formal_step_receipt("hypothesis_pareto", invocation_id),
            final_text=malformed,
        )

    monkeypatch.setattr(
        llm_review_runners, "invoke_llm_outcome", fake_invoke_llm_outcome
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        dict(_FORMAL_FAKE_LLM), require_provider_receipts=True
    )
    context = _formal_review_context()

    with pytest.raises(ContractValidationError, match="did not return valid JSON"):
        runners["pareto_runner"]({"cand-a": {}, "cand-b": {}}, context)

    dumps = _failure_dump_dir(dump_dir)
    assert len(dumps) == 1
    record = _read_dump(dumps[0])
    assert record["purpose"] == "hypothesis_pareto"
    assert record["failureCategory"] == "contract_validation"
    assert record["rawResponse"] == malformed
    assert record["runId"]
    assert record["modelRef"] == "opencode/deepseek-v4-flash"


def test_dump_failure_never_breaks_the_call_contract(
    monkeypatch, _redirect_failure_dumps_to_tmp, caplog
):
    dump_dir = _redirect_failure_dumps_to_tmp
    dump_dir.mkdir(parents=True)
    # A regular file where the dump directory should be makes every write fail.
    blocker = dump_dir / "blocker.json"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(
        llm_review_runners,
        "_review_llm_failure_dump_dir",
        lambda: str(blocker),
    )
    _install_fake_llm(monkeypatch, ["{broken json"])
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))

    with caplog.at_level("WARNING", logger=llm_review_runners.logger.name):
        with pytest.raises(ContractValidationError, match="did not return valid JSON"):
            runners["pairwise_runner"](
                _candidate("cand-a", "假说 A"),
                _candidate("cand-b", "假说 B"),
                _review_context(),
            )

    assert any("failure dump" in record.message for record in caplog.records)


def test_successful_review_call_writes_no_dump(
    monkeypatch, _redirect_failure_dumps_to_tmp
):
    dump_dir = _redirect_failure_dumps_to_tmp
    payloads = [
        json.dumps(
            {
                "claim": "假说 A",
                "rationale": "评分依据。",
                "differenceFromAlternatives": "不同",
                "lineageRefs": [],
                "scores": {dimension: 0.6 for dimension in HYPOTHESIS_SCORE_DIMENSIONS},
                "status": "reviewed",
                "dimensionReviews": _dimension_review_rows("cand-a"),
            },
            ensure_ascii=False,
        )
    ]
    queue = _install_fake_llm(monkeypatch, payloads)
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))

    produced = runners["reflection_runner"](_candidate("cand-a", "假说 A"), _review_context())

    assert queue == []
    assert produced["scores"]["novelty"] == 0.6
    assert not dump_dir.exists() or _failure_dump_dir(dump_dir) == []


def test_failure_dump_retention_sweeps_files_older_than_24h(
    tmp_path, _redirect_failure_dumps_to_tmp
):
    dump_dir = _redirect_failure_dumps_to_tmp
    dump_dir.mkdir(parents=True)
    stale = dump_dir / "20260101T000000-deadbeef-purpose-failure-session.json"
    fresh = dump_dir / "20260902T000000-deadbeef-purpose-failure-session.json"
    for path in (stale, fresh):
        path.write_text("{}", encoding="utf-8")
    # 25 hours old vs 1 hour old.
    now = time.time()
    os.utime(stale, (now - 25 * 3600, now - 25 * 3600))
    os.utime(fresh, (now - 1 * 3600, now - 1 * 3600))

    llm_review_runners._sweep_expired_failure_dumps(
        str(dump_dir), now_s=now
    )

    assert not stale.exists()
    assert fresh.exists()


# ---------------------------------------------------------------------------
# Structured review calls: per-purpose max_tokens clamp + capability-gated
# strict JSON schema (falls back to prompt + brace parsing without capability)
# ---------------------------------------------------------------------------


def _install_capturing_fake_llm(monkeypatch, payloads: list[str]):
    """Patch ``invoke_llm`` to queue payloads and capture call kwargs."""

    queue = list(payloads)
    captured: list[dict[str, Any]] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        captured.append(dict(kwargs))
        return _FakeResponse(queue.pop(0))

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    return queue, captured


def _fake_llm_with_strict_json_capability(*, supported: bool) -> dict[str, Any]:
    from types import SimpleNamespace

    return {
        **_FAKE_LLM,
        "client": SimpleNamespace(
            capabilities=SimpleNamespace(supports_strict_json_schema=supported)
        ),
    }


def _reflection_output_payload() -> str:
    return json.dumps(
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
            "dimensionReviews": _dimension_review_rows("cand-a"),
        },
        ensure_ascii=False,
    )


def test_structured_review_calls_carry_schema_and_clamp_when_capability_allows(
    monkeypatch,
):
    llm = _fake_llm_with_strict_json_capability(supported=True)
    queue, captured = _install_capturing_fake_llm(
        monkeypatch,
        [
            _reflection_output_payload(),
            json.dumps({"outcome": "left_wins", "justification": "A 维度领先更多。"}),
        ],
    )
    runners = llm_review_runners.build_hypothesis_review_runners(dict(llm))

    context = _review_context()
    reflection = runners["reflection_runner"](_candidate("cand-a", "假说 A"), context)
    pairwise = runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"),
        _candidate("cand-b", "假说 B"),
        context,
    )

    assert queue == []
    reflection_schema = captured[0]["output_schema"]
    pairwise_schema = captured[1]["output_schema"]
    assert reflection_schema is not None and pairwise_schema is not None
    assert reflection_schema.name == "hypothesis_reflection_v1"
    assert pairwise_schema.name == "hypothesis_pairwise_v1"
    assert reflection_schema.schema["type"] == "object"
    assert set(reflection_schema.schema["required"]) >= {"claim", "scores", "dimensionReviews"}
    assert captured[0]["metadata"] == {"llmMaxOutputTokensOverride": 8192}
    assert captured[1]["metadata"] == {"llmMaxOutputTokensOverride": 8192}
    assert reflection["reviewedBy"].startswith("llm:")
    assert pairwise["outcome"] == "left_wins"


def test_review_schema_is_skipped_without_capability_while_clamp_remains(monkeypatch):
    queue, captured = _install_capturing_fake_llm(
        monkeypatch,
        [json.dumps({"outcome": "tie", "justification": "势均力敌。"})],
    )
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))

    produced = runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"),
        _candidate("cand-b", "假说 B"),
        _review_context(),
    )

    assert queue == []
    assert produced["outcome"] == "tie"
    assert captured[0]["output_schema"] is None
    assert captured[0]["metadata"] == {"llmMaxOutputTokensOverride": 8192}


def test_capability_true_but_explicit_false_resolves_through_client_capability(monkeypatch):
    llm = _fake_llm_with_strict_json_capability(supported=False)
    queue, captured = _install_capturing_fake_llm(
        monkeypatch,
        [json.dumps({"outcome": "tie", "justification": "势均力敌。"})],
    )
    runners = llm_review_runners.build_hypothesis_review_runners(dict(llm))

    runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"),
        _candidate("cand-b", "假说 B"),
        _review_context(),
    )

    assert queue == []
    assert captured[0]["output_schema"] is None


def test_revision_runner_sends_default_revision_cap_and_skips_schema(monkeypatch):
    llm = _fake_llm_with_strict_json_capability(supported=True)
    revision_payload = json.dumps(
        {
            "revisedCandidate": {
                **_candidate("cand-a", "假说 A（收窄到目标人群）"),
            },
            "changes": ["收窄目标人群"],
            "unresolvedIssues": ["外部有效性待验证"],
        },
        ensure_ascii=False,
    )
    queue, captured = _install_capturing_fake_llm(monkeypatch, [revision_payload])
    runners = llm_review_runners.build_hypothesis_review_runners(dict(llm))

    produced = runners["revision_runner"](
        _review_context(),
        _candidate("cand-a", "假说 A"),
        [_candidate("cand-a", "假说 A")],
        {"metaReviewId": "meta-1", "recommendationCandidateId": "cand-a"},
    )

    assert queue == []
    assert produced["revisedCandidate"]["claim"].startswith("假说 A")
    assert captured[0]["output_schema"] is None
    assert captured[0]["metadata"] == {
        llm_review_runners.MAX_OUTPUT_TOKENS_OVERRIDE_METADATA_KEY: llm_review_runners.revision_max_output_tokens()
    }


def test_digest_drafter_sends_strict_json_schema_and_keeps_profile_tokens(
    monkeypatch,
):
    """Strict-capable providers get the digest contract at the wire level.

    The persisted artifact stays open Markdown; it travels as the
    ``documentMarkdown`` field of one schema-constrained JSON object, and the
    digest call is never clamped (profile max_tokens default).
    """

    markdown = """# 候选 A/B 评审纪要

## 会议结论

评审完成，倾向候选 A。
"""
    llm = _fake_llm_with_strict_json_capability(supported=True)
    queue, captured = _install_capturing_fake_llm(
        monkeypatch,
        [json.dumps({"documentMarkdown": markdown}, ensure_ascii=False)],
    )
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(llm))

    digest = drafter(_meeting_round(), _source_messages())

    assert queue == []
    assert digest["summary"].startswith("评审完成")
    assert digest["documentMarkdown"] == markdown.strip()
    assert digest["documentTemplateId"] == "open_sections_v1"
    schema = captured[0]["output_schema"]
    assert schema is not None
    assert schema.name == "meeting_digest_v1"
    assert schema.schema["type"] == "object"
    assert list(schema.schema["required"]) == ["documentMarkdown"]
    assert schema.schema["additionalProperties"] is False
    # Red line: the digest generation budget is never clamped.
    assert captured[0]["metadata"] is None


def _system_prompt_text(messages: list[Any]) -> str:
    first = messages[0]
    if isinstance(first, Mapping):
        content = first.get("content")
        if isinstance(content, list):
            return "".join(
                str(block.get("text") or "") for block in content if isinstance(block, Mapping)
            )
        return str(content or "")
    return str(getattr(first, "content", "") or "")


def test_digest_strict_mode_uses_json_prompt_and_serves_document_markdown(
    monkeypatch,
):
    markdown = "# 评审纪要\n\n## 会议结论\n\n纪要正常生成。\n"
    llm = _fake_llm_with_strict_json_capability(supported=True)
    captured_messages: list[Any] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        captured_messages.append(list(messages))
        return _FakeResponse(json.dumps({"documentMarkdown": markdown}, ensure_ascii=False))

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(llm))

    digest = drafter(_meeting_round(), _source_messages())

    assert digest["documentMarkdown"] == markdown.strip()
    system_prompt = _system_prompt_text(captured_messages[0])
    assert "documentMarkdown" in system_prompt
    assert "会议结论" in system_prompt
    assert "不得编造发言人" in system_prompt
    assert "proposedCandidates" not in system_prompt
    assert "evidenceRequests" not in system_prompt


def test_digest_without_capability_keeps_open_markdown_text_path(monkeypatch):
    """No strict capability → the historical text contract is unchanged."""

    markdown = "# 评审纪要\n\n## 会议结论\n\n纪要仍应正常生成。\n"
    llm = _fake_llm_with_strict_json_capability(supported=False)
    queue = [markdown]
    captured: list[dict[str, Any]] = []
    captured_messages: list[Any] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        captured.append(dict(kwargs))
        captured_messages.append(list(messages))
        return _FakeResponse(queue.pop(0))

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(llm))

    digest = drafter(_meeting_round(), _source_messages())

    assert queue == []
    assert digest["summary"].startswith("纪要仍应正常生成。")
    assert captured[0]["output_schema"] is None
    assert captured[0]["metadata"] is None
    system_prompt = _system_prompt_text(captured_messages[0])
    assert "不要输出 JSON" in system_prompt
    assert "documentMarkdown" not in system_prompt


def test_digest_strict_mode_invalid_json_fails_closed_and_dumps_raw_response(
    monkeypatch, _redirect_failure_dumps_to_tmp
):
    broken = '{broken json from "provider"'
    llm = _fake_llm_with_strict_json_capability(supported=True)
    _install_fake_llm(monkeypatch, [broken])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(llm))

    with pytest.raises(ContractValidationError, match="did not return valid JSON"):
        drafter(_meeting_round(), _source_messages())

    dumps = _failure_dump_dir(_redirect_failure_dumps_to_tmp)
    assert len(dumps) == 1
    record = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert record["purpose"] == "meeting_digest"
    assert record["failureCategory"] == "contract_validation"
    assert record["rawResponse"] == broken


def test_digest_strict_mode_missing_document_markdown_fails_closed(
    monkeypatch, _redirect_failure_dumps_to_tmp
):
    llm = _fake_llm_with_strict_json_capability(supported=True)
    _install_fake_llm(monkeypatch, [json.dumps({"unrelated": True})])
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(llm))

    with pytest.raises(
        ContractValidationError, match="documentMarkdown"
    ):
        drafter(_meeting_round(), _source_messages())

    dumps = _failure_dump_dir(_redirect_failure_dumps_to_tmp)
    assert len(dumps) == 1
    record = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert record["failureCategory"] == "contract_validation"
    assert "unrelated" in record["rawResponse"]


def test_review_max_output_tokens_env_overrides_and_defaults(monkeypatch):
    monkeypatch.delenv("VIBELUTION_REVIEW_JSON_MAX_OUTPUT_TOKENS", raising=False)

    assert llm_review_runners.review_json_max_output_tokens() == 8192
    assert (
        llm_review_runners._purpose_max_output_tokens("hypothesis_metareview") == 8192
    )
    # Red line: digest never clamps; it keeps the profile default. Revision
    # carries its own cap (see the dedicated revision cap test below).
    assert llm_review_runners._purpose_max_output_tokens("meeting_digest") is None
    assert llm_review_runners._purpose_max_output_tokens("hypothesis_revision") == 12288

    monkeypatch.setenv("VIBELUTION_REVIEW_JSON_MAX_OUTPUT_TOKENS", "4096")
    assert llm_review_runners.review_json_max_output_tokens() == 4096
    assert (
        llm_review_runners._purpose_max_output_tokens("hypothesis_pairwise") == 4096
    )
    assert llm_review_runners._purpose_max_output_tokens("hypothesis_pareto") == 4096
    assert llm_review_runners._purpose_max_output_tokens("meeting_digest") is None

    monkeypatch.setenv("VIBELUTION_REVIEW_JSON_MAX_OUTPUT_TOKENS", "not-a-number")
    assert llm_review_runners.review_json_max_output_tokens() == 8192

    monkeypatch.setenv("VIBELUTION_REVIEW_JSON_MAX_OUTPUT_TOKENS", "1")
    assert llm_review_runners.review_json_max_output_tokens() == 512

    monkeypatch.setenv("VIBELUTION_REVIEW_JSON_MAX_OUTPUT_TOKENS", "999999")
    assert llm_review_runners.review_json_max_output_tokens() == 65536


def test_revision_max_output_tokens_env_overrides_and_defaults(monkeypatch):
    monkeypatch.delenv("VIBELUTION_REVISION_MAX_OUTPUT_TOKENS", raising=False)

    assert llm_review_runners.revision_max_output_tokens() == 12288
    assert (
        llm_review_runners._purpose_max_output_tokens("hypothesis_revision") == 12288
    )
    # Red line: the digest generation budget is never clamped.
    assert llm_review_runners._purpose_max_output_tokens("meeting_digest") is None
    # The four JSON review purposes keep their own clamp, untouched by the
    # revision env override.
    assert llm_review_runners._purpose_max_output_tokens("hypothesis_reflection") == 8192

    monkeypatch.setenv("VIBELUTION_REVISION_MAX_OUTPUT_TOKENS", "4096")
    assert llm_review_runners.revision_max_output_tokens() == 4096
    assert llm_review_runners._purpose_max_output_tokens("hypothesis_revision") == 4096

    monkeypatch.setenv("VIBELUTION_REVISION_MAX_OUTPUT_TOKENS", "not-a-number")
    assert llm_review_runners.revision_max_output_tokens() == 12288

    # Boundary: below minimum clamps up to 2048.
    monkeypatch.setenv("VIBELUTION_REVISION_MAX_OUTPUT_TOKENS", "1")
    assert llm_review_runners.revision_max_output_tokens() == 2048

    monkeypatch.setenv("VIBELUTION_REVISION_MAX_OUTPUT_TOKENS", "2047")
    assert llm_review_runners.revision_max_output_tokens() == 2048

    # Boundary: above maximum clamps down to 32768.
    monkeypatch.setenv("VIBELUTION_REVISION_MAX_OUTPUT_TOKENS", "999999")
    assert llm_review_runners.revision_max_output_tokens() == 32768


def test_receipt_bound_structured_call_passes_schema_and_clamp(monkeypatch):
    llm = {
        **_fake_llm_with_strict_json_capability(supported=True),
        "providerId": "opencode",
        "modelId": "deepseek-v4-flash",
        "modelRef": "opencode/deepseek-v4-flash",
    }
    receipt = {"receiptId": "provider-review-receipt", "status": "succeeded"}
    captured: list[dict[str, Any]] = []

    def fake_invoke_llm_outcome(_client, _messages, **kwargs):
        captured.append(dict(kwargs))
        return _final_outcome(kwargs["context"], receipt=receipt)

    monkeypatch.setattr(llm_review_runners, "invoke_llm_outcome", fake_invoke_llm_outcome)
    runners = llm_review_runners.build_hypothesis_review_runners(
        dict(llm), require_provider_receipts=True
    )

    result = runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"),
        _candidate("cand-b", "假说 B"),
        _formal_review_context(),
    )

    assert isinstance(result, ProviderBoundReviewResult)
    assert result.payload["outcome"] == "left_wins"
    assert captured[0]["output_schema"] is not None
    assert captured[0]["output_schema"].name == "hypothesis_pairwise_v1"
    # Receipt-bound structured calls keep the review clamp (digest-only
    # unclamping does not touch the hypothesis review purposes).
    assert captured[0]["metadata"] == {"llmMaxOutputTokensOverride": 8192}


# ---------------------------------------------------------------------------
# Direct-call telemetry: scene events per review purpose and team-scoped
# usage-ledger metadata (latency / model / tokens / failure category)
# ---------------------------------------------------------------------------


def _capture_scene_events(monkeypatch) -> list[dict]:
    from core.web.services import runtime_scene_service

    events: list[dict] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        lambda component, phase, event_code, **kwargs: events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        ),
    )
    return events


def test_review_call_telemetry_records_scene_events_for_review_purposes(
    monkeypatch,
):
    events = _capture_scene_events(monkeypatch)

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        return _FakeResponse(
            json.dumps({"outcome": "left_wins", "justification": "A 更优。"}),
            response_metadata={
                "finish_reason": "stop",
                "usage_observation": {
                    "input_tokens": 90,
                    "output_tokens": 30,
                    "total_tokens": 120,
                },
            },
        )

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))

    produced = runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"),
        _candidate("cand-b", "假说 B"),
        _review_context(),
    )

    assert produced["outcome"] == "left_wins"
    codes = [event["eventCode"] for event in events]
    assert "review_llm.call.started" in codes
    completed = next(
        event for event in events if event["eventCode"] == "review_llm.call.completed"
    )
    assert completed["component"] == "team_workflow"
    assert completed["phase"] == "review_llm"
    fields = completed["fields"]
    assert fields["purpose"] == "hypothesis_pairwise"
    assert fields["modelId"] == "fake-review-model"
    assert fields["inputTokens"] == 90
    assert fields["outputTokens"] == 30
    assert fields["totalTokens"] == 120
    assert fields["finishReason"] == "stop"
    assert fields["latencyMs"] >= 0


def test_review_call_telemetry_records_failure_category(monkeypatch):
    events = _capture_scene_events(monkeypatch)
    _install_fake_llm(monkeypatch, ["{broken json"])
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))

    with pytest.raises(ContractValidationError, match="did not return valid JSON"):
        runners["pairwise_runner"](
            _candidate("cand-a", "假说 A"),
            _candidate("cand-b", "假说 B"),
            _review_context(),
        )

    failed = next(
        event for event in events if event["eventCode"] == "review_llm.call.failed"
    )
    assert failed["level"] == "error"
    assert failed["fields"]["purpose"] == "hypothesis_pairwise"
    assert failed["fields"]["errorCategory"] == "contract_validation"
    assert failed["fields"]["errorType"] == "ContractValidationError"


def test_review_invocation_metadata_carries_team_scope_for_usage_ledger(
    monkeypatch,
):
    """teamId in the invocation metadata routes the client-side usage-ledger
    write into the team_workflow scope, so digest/review traffic is visible
    in team-filtered ledger views (latency and token distribution)."""

    captured_contexts: list[Any] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        captured_contexts.append(context)
        purpose = str(context.metadata.get("purpose") or "")
        if purpose == "meeting_digest":
            return _FakeResponse(
                "# 评审纪要\n\n## 会议结论\n\n纪要正常生成。\n"
            )
        return _FakeResponse(json.dumps({"outcome": "tie", "justification": "x"}))

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"),
        _candidate("cand-b", "假说 B"),
        _review_context(),
    )
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(_FAKE_LLM))
    drafter(_meeting_round(), _source_messages())

    assert len(captured_contexts) == 2
    for context in captured_contexts:
        assert context.metadata["teamId"] == "team-1"
        assert context.metadata["purpose"] in {
            "hypothesis_pairwise",
            "meeting_digest",
        }


def test_digest_strict_mode_timeout_keeps_existing_failure_semantics(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise llm_review_runners.ReviewLLMTimeoutError(
            purpose="meeting_digest", timeout_seconds=450
        )

    monkeypatch.setattr(llm_review_runners, "_invoke_llm_with_timeout", timeout)
    llm = _fake_llm_with_strict_json_capability(supported=True)
    drafter = llm_review_runners.build_meeting_digest_drafter(dict(llm))

    with pytest.raises(llm_review_runners.ReviewLLMTimeoutError):
        drafter(_meeting_round(), _source_messages())
