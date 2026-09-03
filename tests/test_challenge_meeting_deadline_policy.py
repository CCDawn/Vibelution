from __future__ import annotations

import json

import pytest

from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
from core.research.workflow.contracts.review_call_budget import (
    MAX_BUDGET_FINALIST_COUNT,
    review_call_budget_for,
)
from core.web.services.team_workflow import challenge_deadline_policy as policy
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as receipt_registry,
)


@pytest.fixture(autouse=True)
def _isolate_operator_config_from_budget(monkeypatch):
    """Default every test to an unconfigured operator fence.

    The live operator config may pin ``[research]``
    ``challenge_meeting_per_call_budget_ms``; policy tests assert specific
    derivation outcomes, so the config gate is neutralized unless a test
    explicitly overrides ``config.settings.get_config`` itself.
    """

    from types import SimpleNamespace

    unconfigured = SimpleNamespace(
        research=SimpleNamespace(challenge_meeting_per_call_budget_ms=None)
    )
    monkeypatch.setattr("config.settings.get_config", lambda: unconfigured)


def test_binding_p95_derives_bounded_call_budget(monkeypatch):
    samples = [
        {
            "provider": "relay_autodl",
            "model": "GLM-5.3-flash",
            "purpose": "meeting_speaker",
            "latencyMs": 470_000 + index * 1_000,
        }
        for index in range(20)
    ]
    monkeypatch.delenv(policy._PER_CALL_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(policy, "_receipt_latency_samples", lambda _team: samples)

    result = policy.derive_per_call_budget(
        "research-team",
        model_refs=["relay_autodl/GLM-5.3-flash"],
        purpose="meeting_speaker",
    )

    assert result["sampleSource"] == "provider_model_purpose_p95"
    assert result["sampleCount"] == 20
    assert result["latencyP95Ms"] == 488_000
    assert result["perCallBudgetMs"] == 800_000


def test_low_p95_floors_at_governed_cap(monkeypatch):
    """Pin the raised per-call floor: a 118s p95 must no longer derive 300s.

    Live meeting-speaker calls regularly ran 300-416s with a heavy tail past
    600s, so the former 300s floor truncated valid calls mid-flight; the
    derivation band now collapses onto the governed 800s cap.
    """

    samples = [
        {
            "provider": "relay_autodl",
            "model": "GLM-5.3-flash",
            "purpose": "meeting_speaker",
            "latencyMs": 100_000 + index * 1_000,
        }
        for index in range(20)
    ]
    monkeypatch.delenv(policy._PER_CALL_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(policy, "_receipt_latency_samples", lambda _team: samples)

    result = policy.derive_per_call_budget(
        "research-team",
        model_refs=["relay_autodl/GLM-5.3-flash"],
        purpose="meeting_speaker",
    )

    assert result["sampleSource"] == "provider_model_purpose_p95"
    assert result["latencyP95Ms"] == 118_000
    # 118s p95 x 1.25 = 147.5s; previously floored at 300s, now governed to 800s.
    assert result["perCallBudgetMs"] == 800_000


def test_sparse_samples_use_audited_default(monkeypatch):
    monkeypatch.delenv(policy._PER_CALL_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(
        policy,
        "_receipt_latency_samples",
        lambda _team: [{"provider": "p", "model": "m", "latencyMs": 10_000}],
    )

    speaker_result = policy.derive_per_call_budget(
        "research-team", model_refs=["p/m"], purpose="meeting_speaker"
    )
    review_result = policy.derive_per_call_budget(
        "research-team", model_refs=["p/m"], purpose="team_workflow_review"
    )

    assert speaker_result["sampleSource"] == "audited_default"
    assert speaker_result["perCallBudgetMs"] == 450_000
    assert review_result["sampleSource"] == "audited_default"
    assert review_result["perCallBudgetMs"] == 800_000


def test_operator_override_is_bounded(monkeypatch):
    # The derivation band collapsed onto the 800s cap, so the override domain
    # is now the single governed value; lower pins fail loudly instead of
    # re-creating the observed 300s speaker-call truncation.
    monkeypatch.setenv(policy._PER_CALL_OVERRIDE_ENV, "799999")
    with pytest.raises(policy.ChallengeMeetingDeadlinePolicyError):
        policy.derive_per_call_budget("research-team")

    monkeypatch.setenv(policy._PER_CALL_OVERRIDE_ENV, "800000")
    assert policy.derive_per_call_budget("research-team") == {
        "perCallBudgetMs": 800_000,
        "latencyP95Ms": 0,
        "sampleCount": 0,
        "sampleSource": "operator_env",
        "overrideEnv": policy._PER_CALL_OVERRIDE_ENV,
    }


def test_operator_config_pins_fence_and_precedes_env(monkeypatch):
    monkeypatch.delenv(policy._PER_CALL_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(policy, "_operator_config_override_ms", lambda: 800_000)

    assert policy.derive_per_call_budget("research-team") == {
        "perCallBudgetMs": 800_000,
        "latencyP95Ms": 0,
        "sampleCount": 0,
        "sampleSource": "operator_config",
        "overrideEnv": "",
    }

    monkeypatch.setenv(policy._PER_CALL_OVERRIDE_ENV, "360000")
    assert (
        policy.derive_per_call_budget("research-team")["perCallBudgetMs"] == 800_000
    )


def test_operator_config_out_of_domain_is_rejected(monkeypatch):
    monkeypatch.delenv(policy._PER_CALL_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(policy, "_operator_config_override_ms", lambda: 700_000)

    with pytest.raises(policy.ChallengeMeetingDeadlinePolicyError):
        policy.derive_per_call_budget("research-team")


def test_operator_config_override_reads_live_settings(monkeypatch):
    from types import SimpleNamespace

    def _settings(value):
        return SimpleNamespace(
            research=SimpleNamespace(challenge_meeting_per_call_budget_ms=value)
        )

    monkeypatch.setattr("config.settings.get_config", lambda: _settings(800_000))
    assert policy._operator_config_override_ms() == 800_000

    monkeypatch.setattr("config.settings.get_config", lambda: _settings(None))
    assert policy._operator_config_override_ms() is None

    for bogus in (True, 0, -300_000, "600000", 600.0):
        monkeypatch.setattr("config.settings.get_config", lambda bogus=bogus: _settings(bogus))
        assert policy._operator_config_override_ms() is None

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr("config.settings.get_config", _boom)
    assert policy._operator_config_override_ms() is None


def _stub_call_budget(monkeypatch, per_call_ms: int = 300_000) -> None:
    monkeypatch.setattr(policy, "_participant_model_refs", lambda _ids: ["p/m"])
    monkeypatch.setattr(
        policy,
        "derive_per_call_budget",
        lambda *_args, **_kwargs: {
            "perCallBudgetMs": per_call_ms,
            "latencyP95Ms": 100_000,
            "sampleCount": 24,
            "sampleSource": "provider_model_purpose_p95",
            "overrideEnv": "",
        },
    )


def test_meeting_budget_sums_serial_speakers_and_digest(monkeypatch):
    _stub_call_budget(monkeypatch)

    result = policy.derive_meeting_deadline_policy(
        "research-team",
        {"participants": ["a", "b", "c", "d"], "rounds": 2},
        server_created_at_ms=1_000_000,
    )

    assert result["plannedSerialCallCount"] == 9
    assert result["plannedCallCountBasis"] == "speakers_plus_digest"
    assert result["reviewFinalistCount"] == 0
    assert result["meetingBudgetMs"] == 2_700_000
    assert result["meetingDeadlineAtMs"] == 3_700_000
    assert result["challengeDeadlineAtMs"] == 3_700_000
    assert len(result["deadlinePolicyHash"]) == 64

    insufficient = policy.derive_meeting_deadline_policy(
        "research-team",
        {"participants": ["a", "b", "c", "d"], "rounds": 2},
        server_created_at_ms=1_000_000,
        outer_deadline_at_ms=2_000_000,
    )
    assert insufficient["challengeDeadlineAtMs"] == 2_000_000
    assert insufficient["deadlineBudgetSufficient"] is False
    assert insufficient["deadlineProblem"] == {
        "code": "deadline_budget_insufficient",
        "availableMs": 1_000_000,
        "requiredMs": 2_700_000,
        "outerDeadlineAtMs": 2_000_000,
        "meetingDeadlineAtMs": 3_700_000,
    }


def test_hypothesis_review_budget_adds_exact_review_call_budget(monkeypatch):
    _stub_call_budget(monkeypatch)
    # Cross-check the fixture against the live contract: n=3 -> 3 + 3 + 2 = 8.
    assert review_call_budget_for(3).totalReviewCalls == 8

    result = policy.derive_meeting_deadline_policy(
        "research-team",
        {
            "meetingType": "hypothesis_review",
            "participants": ["a", "b"],
            "rounds": 1,
            "discussionItemRefs": [
                "hypothesis_candidate:c1",
                "hypothesis_candidate:c2",
                "hypothesis_candidate:c3",
            ],
        },
        server_created_at_ms=1_000_000,
    )

    assert result["reviewFinalistCount"] == 3
    assert result["plannedCallCountBasis"] == "speakers_digest_review_call_budget"
    # 2 speakers x 1 round + 1 digest + the exact review budget = 11.
    assert (
        result["plannedSerialCallCount"]
        == 2 * 1 + 1 + review_call_budget_for(3).totalReviewCalls
    )
    assert result["meetingBudgetMs"] == 3_300_000
    assert result["meetingDeadlineAtMs"] == 4_300_000
    assert result["challengeDeadlineAtMs"] == 4_300_000


def test_review_meeting_counts_distinct_refs_and_ignores_foreign_ones(monkeypatch):
    _stub_call_budget(monkeypatch)

    result = policy.derive_meeting_deadline_policy(
        "research-team",
        {
            "meetingType": "hypothesis_review",
            "participants": ["a"],
            "rounds": 1,
            "discussionItemRefs": [
                "hypothesis_candidate:c1",
                "hypothesis_candidate:c1",
                "hypothesis_candidate:",
                "other_ref:keep-out",
            ],
        },
        server_created_at_ms=1_000_000,
    )

    # n=1 -> 1 + 0 + 2 = 3 review calls; 1 speaker + 1 digest + 3 = 5.
    assert result["reviewFinalistCount"] == 1
    assert (
        result["plannedSerialCallCount"]
        == 2 + review_call_budget_for(1).totalReviewCalls
    )
    assert result["plannedCallCountBasis"] == "speakers_digest_review_call_budget"


def test_review_budget_clamps_to_bounded_review_context_cap(monkeypatch):
    _stub_call_budget(monkeypatch)
    overflow = MAX_BUDGET_FINALIST_COUNT + 1

    result = policy.derive_meeting_deadline_policy(
        "research-team",
        {
            "meetingType": "hypothesis_review",
            "participants": ["a"],
            "rounds": 1,
            "discussionItemRefs": [
                f"hypothesis_candidate:c{index}" for index in range(overflow)
            ],
        },
        server_created_at_ms=1_000_000,
    )

    # The bounded review context truncates at the same cap, so the unreachable
    # overflow candidates must not inflate the budget beyond the n=16 formula.
    assert result["reviewFinalistCount"] == MAX_BUDGET_FINALIST_COUNT
    assert (
        result["plannedSerialCallCount"]
        == 2 + review_call_budget_for(MAX_BUDGET_FINALIST_COUNT).totalReviewCalls
    )


def test_review_meeting_without_candidate_refs_keeps_legacy_estimate(monkeypatch):
    _stub_call_budget(monkeypatch)

    result = policy.derive_meeting_deadline_policy(
        "research-team",
        {
            "meetingType": "hypothesis_review",
            "participants": ["a", "b", "c", "d"],
            "rounds": 2,
            "discussionItemRefs": [],
        },
        server_created_at_ms=1_000_000,
    )

    assert result["plannedSerialCallCount"] == 9
    assert result["plannedCallCountBasis"] == "speakers_plus_digest"
    assert result["reviewFinalistCount"] == 0


def test_candidate_generation_meeting_keeps_legacy_estimate(monkeypatch):
    _stub_call_budget(monkeypatch)

    result = policy.derive_meeting_deadline_policy(
        "research-team",
        {
            "meetingType": "hypothesis_candidate_generation",
            "participants": ["a", "b", "c", "d"],
            "rounds": 2,
        },
        server_created_at_ms=1_000_000,
    )

    assert result["plannedSerialCallCount"] == 9
    assert result["plannedCallCountBasis"] == "speakers_plus_digest"
    assert result["reviewFinalistCount"] == 0


def test_effective_call_deadline_uses_earliest_clock():
    assert policy.effective_call_deadline_at_ms(
        call_started_at_ms=1_000_000,
        per_call_budget_ms=300_000,
        meeting_deadline_at_ms=1_500_000,
        outer_deadline_at_ms=1_200_000,
    ) == 1_200_000


def test_latency_projection_reads_receipt_facts_without_excerpts(tmp_path, monkeypatch):
    root = tmp_path / "receipts"
    path = root / "question" / "run.json"
    path.parent.mkdir(parents=True)
    scope = {
        "questionId": "SCI-091",
        "workflowRunId": "run-1",
        "sessionId": "session-1",
        "taskId": "task-1",
        "turnId": "turn-1",
        "formalNodeId": "node-1",
        "formalNodeRunId": "node-run-1",
        "modelPolicySha256": "a" * 64,
    }
    locator = {
        **scope,
        "kind": "turn_journal",
        "outputRef": "session:session-1/turn:turn-1",
        "outputSha256": "b" * 64,
        "receiptId": "receipt-1",
        "invocationId": "invocation-1",
        "attempt": 1,
    }
    receipt = ModelInvocationReceipt.from_invocation(
        receipt_id="receipt-1",
        run_id="run-1",
        node_run_id="node-run-1",
        scope=scope,
        provider="relay_autodl",
        model="GLM-5.3-flash",
        request_content="secret request",
        response_content="secret response",
        started_at_ms=1_000,
        finished_at_ms=121_000,
        metadata={"outcomeKinds": ["candidate"], "purpose": "meeting_speaker"},
        evidence_locator=locator,
    )
    path.write_text(
        json.dumps(
            {
                "schemaVersion": receipt_registry.STORE_SCHEMA_VERSION,
                "storeKind": receipt_registry.STORE_KIND,
                "teamId": "research-team",
                "questionId": "SCI-091",
                "workflowRunId": "run-1",
                "receipts": [receipt.to_dict()],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(receipt_registry, "_receipt_store_root", lambda _team: root)

    rows = receipt_registry.list_team_model_invocation_latency_samples(
        "research-team"
    )

    assert rows == [
        {
            "provider": "relay_autodl",
            "model": "GLM-5.3-flash",
            "latencyMs": 120_000,
            "finishedAtMs": 121_000,
            "purpose": "meeting_speaker",
        }
    ]
    assert "secret" not in str(rows)
