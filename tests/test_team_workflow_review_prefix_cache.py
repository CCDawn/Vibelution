"""Review-pipeline prefix-cache design contracts.

Pins the design fixes that make DashScope explicit prompt caching actually
replay across the hypothesis review pipeline:

* L0 shared system head: every review step's system prompt opens with one
  byte-identical ``cache_control`` head block (rubric + dimension constants +
  JSON-only rule); the step tail follows as a second marked block, and the
  round-gap keepalive probe builds the very same message shape;
* pairwise wave system payload: the wave-invariant
  ``{context, candidatesBank(sorted by candidateId)}`` rides INSIDE the
  system message as its single ``cache_control``-marked block (DashScope
  compatible-mode only forms cache entries for full system messages, so a
  marked user prefix never hit), the user message carries only the per-call
  ``pair{leftId, rightId}`` selector with the lexicographically smaller id
  in the left slot, the verdict is mapped back to the executor's debated
  frame, and the executor hands every pair call the full reviewed bank so
  MetaReview/Pareto consumers see the same comparison records as before;
* review-wave gap keepalive: armed when the reflection wave starts, cancelled
  when it completes, so only a wave predicted to outlive the provider TTL
  fires a probe (and does so even though the meeting round is already
  closed at review time); the probe rebuilds the exact system message the
  pairwise calls send (byte-identical merged construction).

No real model or network is involved.
"""

from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest

from core.research.competition.question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
)
from core.research.workflow.contracts.hypothesis_quality import (
    HYPOTHESIS_SCORE_DIMENSIONS,
)
from core.web.services import runtime_scene_service
from core.web.services.team_workflow import (
    hypothesis_review_executor,
    llm_review_runners,
    meeting_rounds,
    review_cache_keepalive,
)
from core.web.services.team_workflow.hypothesis_review_executor import (
    PAIRWISE_CANDIDATE_BANK_CONTEXT_KEY,
    ProviderBoundReviewResult,
    execute_hypothesis_review,
)

_FAKE_LLM = {"client": object(), "profileId": "primary", "modelId": "fake-review-model"}


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content
        self.response_metadata: dict[str, Any] = {}


def _candidate(candidate_id: str, claim: str) -> dict[str, Any]:
    return {
        "candidateId": candidate_id,
        "claim": claim,
        "rationale": "初步论证",
        "differenceFromAlternatives": "与备选不同",
        "lineageRefs": [],
        "status": "reviewed",
    }


def _review_context(**overrides: Any) -> dict[str, Any]:
    context = {
        "contextId": "ctx-1",
        "teamId": "team-1",
        "question": "SCI-096",
        "candidates": [_candidate("cand-a", "假说 A"), _candidate("cand-b", "假说 B")],
    }
    context.update(overrides)
    return context


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "".join(str(block.get("text") or "") for block in content if isinstance(block, dict))


def _pairwise_system_payload(message: dict[str, Any]) -> dict[str, Any]:
    """Parse the wave-invariant JSON payload a pairwise system message carries."""

    text = _message_text(message)
    assert text.startswith(llm_review_runners._PAIRWISE_SYSTEM_PROMPT)
    return json.loads(text[len(llm_review_runners._PAIRWISE_SYSTEM_PROMPT) :])


@pytest.fixture(autouse=True)
def _reset_keepalive_state():
    review_cache_keepalive.reset_meeting_cache_keepalive_for_tests()
    yield
    review_cache_keepalive.reset_meeting_cache_keepalive_for_tests()


@pytest.fixture()
def scene_events(monkeypatch) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runtime_scene_service,
        "record_runtime_scene_event_quietly",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )
    return events


def _capture_review_calls(monkeypatch, outcome: str = "tie") -> list[dict[str, Any]]:
    """Fake ``invoke_llm`` recording every review request; pairwise verdicts fixed."""

    captured: list[dict[str, Any]] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        captured.append(
            {
                "messages": messages,
                "purpose": str(getattr(context, "prompt_purpose", "")),
                "payload": json.loads(_message_text(messages[1])),
            }
        )
        return _FakeResponse(
            json.dumps({"outcome": outcome, "justification": "cand 依据"}, ensure_ascii=False)
        )

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    return captured


# ---------------------------------------------------------------------------
# L0 shared system head
# ---------------------------------------------------------------------------


def test_review_step_prompts_share_one_byte_identical_head():
    """All five step prompts open with the same marked head; split is lossless."""

    prompts = llm_review_runners.review_step_system_prompts()
    assert [tag for tag, _ in prompts] == [
        "reflection",
        "pairwise",
        "pareto",
        "metareview",
        "revision",
    ]
    head_hashes: set[str] = set()
    for _tag, prompt in prompts:
        message = llm_review_runners.build_review_system_message(prompt)
        assert message["role"] == "system"
        head, tail = message["content"]
        assert head["cache_control"] == {"type": "ephemeral"}
        assert tail["cache_control"] == {"type": "ephemeral"}
        assert head["text"] == llm_review_runners.REVIEW_SHARED_SYSTEM_HEAD
        # Semantic-equivalent split: head + tail is exactly the prompt text.
        assert head["text"] + tail["text"] == prompt
        assert tail["text"].lstrip().startswith("本步骤：")
        head_hashes.add(hashlib.sha256(head["text"].encode("utf-8")).hexdigest())
    assert len(head_hashes) == 1
    head_text = llm_review_runners.REVIEW_SHARED_SYSTEM_HEAD
    assert llm_review_runners._rubric_block() in head_text
    assert "严格输出单个 JSON 对象" in head_text
    assert all(dimension in head_text for dimension in HYPOTHESIS_SCORE_DIMENSIONS)
    assert all(dimension in head_text for dimension in REQUIRED_REVIEW_DIMENSIONS)


def test_review_calls_send_the_shared_head_as_leading_block(monkeypatch):
    """Two different steps put byte-identical first system blocks on the wire."""

    captured = _capture_review_calls(monkeypatch)
    for purpose, prompt in (
        ("hypothesis_reflection", llm_review_runners._REFLECTION_SYSTEM_PROMPT),
        ("hypothesis_pareto", llm_review_runners._PARETO_SYSTEM_PROMPT),
    ):
        llm_review_runners._invoke_review_llm(
            dict(_FAKE_LLM),
            agent_id="reviewer",
            purpose=purpose,
            system_prompt=prompt,
            user_payload={"context": {"contextId": "ctx-1"}, "candidate": {}},
            session_id="team-1",
        )
    first_blocks = [call["messages"][0]["content"][0] for call in captured]
    second_blocks = [call["messages"][0]["content"][1] for call in captured]
    assert first_blocks[0] == first_blocks[1]
    assert first_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert second_blocks[0]["text"] != second_blocks[1]["text"]


def test_prompts_without_the_head_keep_single_block_shape():
    message = llm_review_runners.build_review_system_message("digest prompt")
    assert len(message["content"]) == 1
    assert message["content"][0]["text"] == "digest prompt"
    assert message["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_keepalive_probe_builds_the_same_system_message_as_review_calls(
    monkeypatch, scene_events
):
    """A step-prompt probe sends head + tail blocks identical to a review call."""

    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "10")
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_CHAIN_MAX_PROBES", "1")
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, meeting_round_id: {"meetingRound": {"status": "open"}},
    )
    probe_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        review_cache_keepalive,
        "invoke_llm",
        lambda client, messages, tools=None, context=None, **kwargs: (
            probe_calls.append({"messages": messages}),
            SimpleNamespace(content=".", response_metadata={}),
        )[1],
    )
    resolved = {**_FAKE_LLM, "providerId": "dashscope", "modelRef": "dashscope/qwen", "agentId": "a"}
    review_cache_keepalive.schedule_meeting_cache_keepalive(
        "team-1",
        "meeting-1",
        dedupe_key="round-1",
        system_prompt=llm_review_runners._PAIRWISE_SYSTEM_PROMPT,
        resolve=lambda: resolved,
    )
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not probe_calls:
        time.sleep(0.02)
    assert probe_calls
    assert probe_calls[0]["messages"][0] == llm_review_runners.build_review_system_message(
        llm_review_runners._PAIRWISE_SYSTEM_PROMPT
    )
    assert len(probe_calls[0]["messages"][0]["content"]) == 2


# ---------------------------------------------------------------------------
# Pairwise candidate bank + lexicographic left slot
# ---------------------------------------------------------------------------


def test_pairwise_no_longer_marks_a_user_prefix():
    """The pairwise invariant payload moved into the system message."""

    assert (
        "hypothesis_pairwise"
        not in llm_review_runners._REVIEW_CACHEABLE_USER_PREFIX_KEYS
    )
    assert "literatureContrast" not in (
        llm_review_runners._REVIEW_CACHEABLE_USER_PREFIX_KEYS["hypothesis_reflection"]
    )


def test_pairwise_runner_sends_sorted_bank_inside_one_marked_system_block(monkeypatch):
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None
    captured = _capture_review_calls(monkeypatch, "tie")
    bank = [_candidate(f"cand-{tag}", f"假说 {tag}") for tag in ("c", "a", "b")]
    context = _review_context(**{PAIRWISE_CANDIDATE_BANK_CONTEXT_KEY: bank})

    # Debated order puts cand-c left; the model must see cand-a in the slot.
    result = runners["pairwise_runner"](
        _candidate("cand-c", "假说 C"), _candidate("cand-a", "假说 A"), context
    )

    assert result["outcome"] == "tie"
    # The system message is ONE block carrying prompt + context + full bank,
    # marked exactly once at its end.
    system = captured[0]["messages"][0]
    assert system["role"] == "system"
    assert len(system["content"]) == 1
    assert system["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert _pairwise_system_payload(system) == {
        "context": {"contextId": "ctx-1", "question": "SCI-096"},
        "candidatesBank": [_candidate(f"cand-{tag}", f"假说 {tag}") for tag in ("a", "b", "c")],
    }
    # The user message is the unmarked per-call pair selector only.
    user = captured[0]["messages"][1]
    assert user["role"] == "user"
    assert isinstance(user["content"], str)
    assert not isinstance(user["content"], list)
    assert json.loads(user["content"]) == {"pair": {"leftId": "cand-a", "rightId": "cand-c"}}
    assert "candidatesBank" not in user["content"]


def test_pairwise_sibling_calls_share_byte_identical_marked_system_message(monkeypatch):
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None
    captured = _capture_review_calls(monkeypatch, "tie")
    bank = [_candidate(f"cand-{tag}", f"假说 {tag}") for tag in ("a", "b", "c")]
    by_id = {item["candidateId"]: item for item in bank}
    context = _review_context(**{PAIRWISE_CANDIDATE_BANK_CONTEXT_KEY: bank})
    for left_id, right_id in (("cand-c", "cand-a"), ("cand-b", "cand-c"), ("cand-a", "cand-b")):
        runners["pairwise_runner"](dict(by_id[left_id]), dict(by_id[right_id]), context)

    assert len(captured) == 3
    systems = [call["messages"][0] for call in captured]
    # Byte-identical (single-block) system messages across the whole wave.
    assert systems[0] == systems[1] == systems[2]
    blocks = systems[0]["content"]
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert '"candidatesBank"' in blocks[0]["text"]
    # Users differ only by the pair selector and never carry the bank.
    users = [call["messages"][1] for call in captured]
    assert [json.loads(user["content"])["pair"] for user in users] == [
        {"leftId": "cand-a", "rightId": "cand-c"},
        {"leftId": "cand-b", "rightId": "cand-c"},
        {"leftId": "cand-a", "rightId": "cand-b"},
    ]
    assert all("candidatesBank" not in user["content"] for user in users)


@pytest.mark.parametrize(
    ("debated_left", "debated_right", "model_outcome", "expected_outcome"),
    [
        ("cand-a", "cand-b", "left_wins", "left_wins"),
        ("cand-a", "cand-b", "right_wins", "right_wins"),
        ("cand-a", "cand-b", "tie", "tie"),
        ("cand-b", "cand-a", "left_wins", "right_wins"),
        ("cand-b", "cand-a", "right_wins", "left_wins"),
        ("cand-b", "cand-a", "tie", "tie"),
    ],
)
def test_pairwise_runner_maps_verdict_back_to_the_debated_frame(
    monkeypatch, debated_left, debated_right, model_outcome, expected_outcome
):
    """A model ``left_wins`` means "smaller id wins"; the caller frame is restored."""

    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None
    captured = _capture_review_calls(monkeypatch, model_outcome)
    result = runners["pairwise_runner"](
        _candidate(debated_left, "左"), _candidate(debated_right, "右"), _review_context()
    )
    assert result["outcome"] == expected_outcome
    assert result["justification"] == "cand 依据"
    assert captured[0]["payload"]["pair"] == {"leftId": "cand-a", "rightId": "cand-b"}
    # Without an executor bank the pair itself is the (sorted) bank, riding
    # inside the wave-invariant system payload.
    assert [
        item["candidateId"]
        for item in _pairwise_system_payload(captured[0]["messages"][0])["candidatesBank"]
    ] == [
        "cand-a",
        "cand-b",
    ]


def test_pairwise_runner_keeps_invalid_outcomes_for_executor_validation(monkeypatch):
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None
    _capture_review_calls(monkeypatch, "both_win")
    result = runners["pairwise_runner"](
        _candidate("cand-b", "假说 B"), _candidate("cand-a", "假说 A"), _review_context()
    )
    assert result["outcome"] == "both_win"


def test_pairwise_runner_provider_bound_result_keeps_receipt_and_maps_verdict(monkeypatch):
    receipt = {"receiptId": "receipt-1", "status": "succeeded"}
    seen: list[dict[str, Any]] = []
    seen_system_payloads: list[Any] = []

    def fake_invoke(llm, **kwargs):
        seen.append(dict(kwargs["user_payload"]))
        seen_system_payloads.append(kwargs.get("cacheable_system_payload"))
        return ProviderBoundReviewResult(
            {"outcome": "left_wins", "justification": "cand-a 更优"}, receipt
        )

    monkeypatch.setattr(llm_review_runners, "_invoke_review_llm", fake_invoke)
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None
    result = runners["pairwise_runner"](
        _candidate("cand-b", "假说 B"), _candidate("cand-a", "假说 A"), _review_context()
    )
    assert isinstance(result, ProviderBoundReviewResult)
    assert result.model_invocation_receipt == receipt
    assert result.payload["outcome"] == "right_wins"
    assert seen[0]["pair"] == {"leftId": "cand-a", "rightId": "cand-b"}
    assert [item["candidateId"] for item in seen_system_payloads[0]["candidatesBank"]] == [
        "cand-a",
        "cand-b",
    ]


def test_executor_hands_the_full_reviewed_bank_to_every_pairwise_call():
    """The executor-side half of the contract: the bank rides on the context."""

    ids = ["cand-a", "cand-b", "cand-c"]
    seen_banks: list[list[str]] = []

    def reflection(candidate, context):
        return {
            "rationale": f"rationale:{candidate['candidateId']}",
            "scores": {dimension: 0.6 for dimension in HYPOTHESIS_SCORE_DIMENSIONS},
        }

    def pairwise(left, right, context):
        bank = context[PAIRWISE_CANDIDATE_BANK_CONTEXT_KEY]
        seen_banks.append([item["candidateId"] for item in bank])
        assert all("scores" in item for item in bank), "bank carries reviewed candidates"
        return {"outcome": "left_wins", "justification": f"{left['candidateId']} 胜"}

    result = execute_hypothesis_review(
        {
            "contextId": "ctx-bank",
            "candidates": [
                {
                    "candidateId": cid,
                    "claim": f"候选 {cid}",
                    "differenceFromAlternatives": f"{cid} 差异",
                }
                for cid in ids
            ],
        },
        round_id="round-bank",
        reflection_runner=reflection,
        pairwise_runner=pairwise,
        reviewer_assignments={"metareview": "coordinator"},
        position_seed="bank-seed",
    )
    assert len(seen_banks) == 3
    assert all(sorted(bank) == ids for bank in seen_banks)
    assert [
        (item["leftCandidateId"], item["rightCandidateId"])
        for item in result["pairwiseComparisons"]
    ] == hypothesis_review_executor.deterministic_pairwise_order(ids, "bank-seed")


def test_pairwise_runner_composes_with_executor_and_downstream_consumers(monkeypatch):
    """End to end: bank payloads on the wire, unchanged comparison records."""

    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None
    pairwise_wire: list[dict[str, Any]] = []
    metareview_inputs: list[list[dict[str, Any]]] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        purpose = str(getattr(context, "prompt_purpose", ""))
        payload = json.loads(_message_text(messages[1]))
        if purpose == "hypothesis_pairwise":
            pairwise_wire.append(
                {
                    "systemPayload": _pairwise_system_payload(messages[0]),
                    "pair": payload["pair"],
                }
            )
            # Always prefer the lexicographically smaller candidate (left slot).
            return _FakeResponse(
                json.dumps({"outcome": "left_wins", "justification": "字典序小者胜"}, ensure_ascii=False)
            )
        if purpose == "hypothesis_pareto":
            return _FakeResponse(
                json.dumps(
                    {
                        "paretoFrontCandidateIds": ["cand-a", "cand-b", "cand-c"],
                        "dominatedCandidateIds": [],
                        "notes": "全部前沿",
                    }
                )
            )
        if purpose == "hypothesis_metareview":
            metareview_inputs.append(payload["pairwiseComparisons"])
            return _FakeResponse(
                json.dumps(
                    {
                        "recommendationCandidateId": "cand-a",
                        "rationale": "胜场最多",
                        "riskNotes": "",
                        "accepted": True,
                    }
                )
            )
        raise AssertionError(f"unexpected purpose {purpose}")

    monkeypatch.setattr(llm_review_runners, "invoke_llm", fake_invoke_llm)
    ids = ["cand-a", "cand-b", "cand-c"]

    def reflection(candidate, ctx):
        return {
            "rationale": f"rationale:{candidate['candidateId']}",
            "scores": {dimension: 0.7 for dimension in HYPOTHESIS_SCORE_DIMENSIONS},
        }

    result = execute_hypothesis_review(
        _review_context(
            contextId="ctx-bank",
            candidates=[_candidate(cid, f"假说 {cid}") for cid in ids],
        ),
        round_id="round-bank",
        reflection_runner=reflection,
        pairwise_runner=runners["pairwise_runner"],
        pareto_runner=runners["pareto_runner"],
        metareview_runner=runners["metareview_runner"],
        reviewer_assignments={"metareview": "coordinator"},
        position_seed="bank-seed",
    )

    comparisons = result["pairwiseComparisons"]
    assert [
        (c["leftCandidateId"], c["rightCandidateId"]) for c in comparisons
    ] == hypothesis_review_executor.deterministic_pairwise_order(ids, "bank-seed")
    assert len(pairwise_wire) == 3
    for wire in pairwise_wire:
        system_payload = wire["systemPayload"]
        assert [item["candidateId"] for item in system_payload["candidatesBank"]] == ids
        assert all("scores" in item for item in system_payload["candidatesBank"])
        assert system_payload["context"] == {"contextId": "ctx-bank", "question": "SCI-096"}
        assert wire["pair"]["leftId"] < wire["pair"]["rightId"]
    # Whatever the debated order, the recorded winner is the smaller id.
    for comparison in comparisons:
        left_id, right_id = comparison["leftCandidateId"], comparison["rightCandidateId"]
        winner = left_id if comparison["outcome"] == "left_wins" else right_id
        assert comparison["outcome"] in {"left_wins", "right_wins"}
        assert winner == min(left_id, right_id)
    # The MetaReview consumer received the historical comparison shape.
    assert metareview_inputs and all(
        {"leftCandidateId", "rightCandidateId", "outcome", "justification"} <= set(item)
        for item in metareview_inputs[0]
    )
    assert result["metaReview"]["recommendationCandidateId"] == "cand-a"


# ---------------------------------------------------------------------------
# Review-wave gap keepalive
# ---------------------------------------------------------------------------


def _closed_meeting(monkeypatch) -> None:
    """At review time the bound meeting round is already closed."""

    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda team_id, meeting_round_id: {"meetingRound": {"status": "closed"}},
    )


def _probe_events(events, code: str):
    return [event for event in events if event["eventCode"] == code]


def _install_probe_llm(monkeypatch) -> list[dict[str, Any]]:
    probe_calls: list[dict[str, Any]] = []

    def fake_invoke_llm(client, messages, tools=None, context=None, **kwargs):
        probe_calls.append({"messages": messages, "context": context})
        return SimpleNamespace(content=".", response_metadata={})

    monkeypatch.setattr(review_cache_keepalive, "invoke_llm", fake_invoke_llm)
    return probe_calls


def _wait(condition, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


_RESOLVED = {**_FAKE_LLM, "providerId": "dashscope", "modelRef": "dashscope/qwen", "agentId": "a"}


def test_wave_gap_keepalive_is_disabled_by_the_env_gate(monkeypatch):
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "0")
    assert (
        review_cache_keepalive.schedule_review_wave_gap_keepalive("team-1", "meeting-1")
        is None
    )
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "10")
    assert review_cache_keepalive.schedule_review_wave_gap_keepalive("", "meeting-1") is None
    assert review_cache_keepalive.schedule_review_wave_gap_keepalive("team-1", "") is None


def test_wave_gap_keepalive_cancelled_before_the_delay_never_probes(
    monkeypatch, scene_events
):
    """A reflection wave shorter than one keepalive delay stays probe-free."""

    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "150")
    _closed_meeting(monkeypatch)
    probe_calls = _install_probe_llm(monkeypatch)
    handle = review_cache_keepalive.schedule_review_wave_gap_keepalive(
        "team-1", "meeting-1", resolve=lambda: _RESOLVED
    )
    assert handle is not None
    handle.cancel()
    time.sleep(0.4)
    assert probe_calls == []
    assert _probe_events(scene_events, "review_cache_keepalive.probe.succeeded") == []


def test_wave_gap_keepalive_probes_the_pairwise_prefix_while_the_wave_outlives_the_delay(
    monkeypatch, scene_events
):
    """A wave crossing the delay fires the probe even though the meeting is closed."""

    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "10")
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_CHAIN_MAX_PROBES", "1")
    _closed_meeting(monkeypatch)
    probe_calls = _install_probe_llm(monkeypatch)
    handle = review_cache_keepalive.schedule_review_wave_gap_keepalive(
        "team-1", "meeting-1", resolve=lambda: _RESOLVED
    )
    assert handle is not None
    assert _wait(lambda: bool(probe_calls))
    handle.cancel()
    # The probe targets the next wave: the pairwise system message is the
    # merged single-block construction (step prompt + wave-invariant payload
    # in ONE cache_control-marked block).  A bare arm (no payload inputs yet
    # at reflection time) sends the exact byte prefix of that construction.
    assert probe_calls[0]["messages"][0] == llm_review_runners.build_pairwise_wave_system_message(
        llm_review_runners.pairwise_wave_system_text()
    )
    assert len(probe_calls[0]["messages"][0]["content"]) == 1
    assert probe_calls[0]["messages"][1] == {"role": "user", "content": "."}
    assert str(getattr(probe_calls[0]["context"], "prompt_purpose", "")) == (
        "review_cache_keepalive"
    )
    succeeded = _probe_events(scene_events, "review_cache_keepalive.probe.succeeded")
    assert len(succeeded) == 1
    assert succeeded[0]["fields"]["promptTag"] == "pairwise"
    # The meeting-round liveness gate never skipped it.
    assert _probe_events(scene_events, "review_cache_keepalive.probe.skipped") == []


def test_wave_gap_probe_message_is_byte_identical_to_the_pairwise_call(
    monkeypatch, scene_events
):
    """Given the same (context, bank), the probe replays the pairwise bytes."""

    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "10")
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_CHAIN_MAX_PROBES", "1")
    _closed_meeting(monkeypatch)
    # A real pairwise call first: its wire system message is the authority.
    captured = _capture_review_calls(monkeypatch, "tie")
    bank = [_candidate(f"cand-{tag}", f"假说 {tag}") for tag in ("a", "b", "c")]
    context = _review_context(
        teamId="team-1", **{PAIRWISE_CANDIDATE_BANK_CONTEXT_KEY: bank}
    )
    runners = llm_review_runners.build_hypothesis_review_runners(dict(_FAKE_LLM))
    assert runners is not None
    runners["pairwise_runner"](
        _candidate("cand-a", "假说 A"), _candidate("cand-b", "假说 B"), context
    )
    pairwise_system = captured[0]["messages"][0]

    # The wave-gap probe armed with the same (context, bank) must rebuild it
    # byte for byte — the provider only replays an exact prefix match.
    probe_calls = _install_probe_llm(monkeypatch)
    handle = review_cache_keepalive.schedule_review_wave_gap_keepalive(
        "team-1",
        "meeting-1",
        context={"contextId": "ctx-1", "question": "SCI-096"},
        candidates_bank=bank,
        resolve=lambda: _RESOLVED,
    )
    assert handle is not None
    assert _wait(lambda: bool(probe_calls))
    handle.cancel()
    assert probe_calls[0]["messages"][0] == pairwise_system
    assert probe_calls[0]["messages"][1] == {"role": "user", "content": "."}
    assert len(_probe_events(scene_events, "review_cache_keepalive.probe.succeeded")) == 1


def test_wave_gap_keepalive_rearms_until_cancelled_within_the_chain_budget(
    monkeypatch, scene_events
):
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_DELAY_MS", "10")
    monkeypatch.setenv("VIBELUTION_MEETING_CACHE_KEEPALIVE_CHAIN_MAX_PROBES", "2")
    _closed_meeting(monkeypatch)
    probe_calls = _install_probe_llm(monkeypatch)
    handle = review_cache_keepalive.schedule_review_wave_gap_keepalive(
        "team-1", "meeting-1", resolve=lambda: _RESOLVED
    )
    assert handle is not None
    assert _wait(lambda: len(probe_calls) >= 2)
    time.sleep(0.2)
    # Bounded by the chain budget: no third probe even though never cancelled.
    assert len(probe_calls) == 2
    handle.cancel()
    assert [
        event["fields"]["chainIndex"]
        for event in _probe_events(scene_events, "review_cache_keepalive.probe.succeeded")
    ] == [1, 2]


def test_executor_arms_the_wave_keepalive_around_reflection_and_cancels_before_pairwise(
    monkeypatch,
):
    """Hook timing: armed before the reflection wave, cancelled before pairwise."""

    timeline: list[str] = []

    class _Handle:
        def cancel(self):
            timeline.append("cancel")

    def fake_schedule(team_id, meeting_round_id, **kwargs):
        timeline.append(f"arm:{team_id}:{meeting_round_id}")
        return _Handle()

    monkeypatch.setattr(
        review_cache_keepalive, "schedule_review_wave_gap_keepalive", fake_schedule
    )

    def reflection(candidate, context):
        timeline.append(f"reflect:{candidate['candidateId']}")
        return {
            "rationale": "r",
            "scores": {dimension: 0.6 for dimension in HYPOTHESIS_SCORE_DIMENSIONS},
        }

    def pairwise(left, right, context):
        timeline.append("pairwise")
        return {"outcome": "tie", "justification": "平"}

    execute_hypothesis_review(
        _review_context(meetingRoundId="meeting-1"),
        round_id="round-keepalive",
        reflection_runner=reflection,
        pairwise_runner=pairwise,
        reviewer_assignments={"metareview": "coordinator"},
        max_concurrent_calls=1,
    )
    assert timeline[0] == "arm:team-1:meeting-1"
    assert timeline.index("cancel") > max(
        index for index, item in enumerate(timeline) if item.startswith("reflect:")
    )
    assert timeline.index("cancel") < timeline.index("pairwise")


def test_executor_skips_the_wave_keepalive_without_meeting_scope_or_runner(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        review_cache_keepalive,
        "schedule_review_wave_gap_keepalive",
        lambda team_id, meeting_round_id, **kwargs: calls.append((team_id, meeting_round_id)),
    )

    def reflection(candidate, context):
        return {
            "rationale": "r",
            "scores": {dimension: 0.6 for dimension in HYPOTHESIS_SCORE_DIMENSIONS},
        }

    # No meetingRoundId in scope -> no probe scheduling.
    execute_hypothesis_review(
        _review_context(),
        round_id="round-no-scope",
        reflection_runner=reflection,
        reviewer_assignments={"metareview": "coordinator"},
    )
    # Fixture review (no runner) -> no probe scheduling either.
    execute_hypothesis_review(
        _review_context(meetingRoundId="meeting-1"),
        round_id="round-fixture",
        reviewer_assignments={"metareview": "coordinator"},
    )
    assert calls == []
