"""R1.4 automation policy shadow evaluator tests.

Covers the shadow execution core beside real decision points:

- the pure ``wouldDecide`` rules for every capability switch (table-driven,
  one row per documented gate);
- the fail-closed ``PolicyShadowDecision`` / ``PolicyShadowEvaluationRecord``
  contracts (closed enums, derived agreement, no records about a non-shadow
  policy);
- the chain hooks stay behavior-identical: with a configured shadow policy the
  closure results keep the exact same shape and the dedicated
  ``policy_shadow_evaluations.jsonl`` store gains the meeting-close /
  converge-question records; with no policy configured nothing is written and
  the chain ledger stays untouched.

All discussion content comes from fake runners; no real model, network, or
research activity is involved.  The shadow store is advisory only — nothing in
these tests lets a shadow decision execute or emit a command.
"""

from __future__ import annotations

import json
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path

import pytest
from core.research.workflow.contracts import (
    AUTO_ADVANCE_CAPABILITIES,
    AutoAdvancePolicyV2,
    ContractValidationError,
    POLICY_SHADOW_SCHEMA_VERSION,
    PolicyShadowDecision,
    PolicyShadowEvaluationRecord,
    compute_policy_content_hash,
    derive_shadow_agreement,
)
from core.research.workflow.contracts.policy_shadow import (
    POLICY_SHADOW_ACTION_FOR_POINT,
    POLICY_SHADOW_CAPABILITY_FOR_POINT,
)
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import meeting_runtime
from core.web.services.team_workflow import hypothesis_selection as selections
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import policy_shadow_evaluator as ev
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    reset_formal_write_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)

from tests._support.team_workflow.helpers import (
    _seed_claim_belief_gate_fixture,
    _use_fake_local_research_config,
    _use_tmp_project_root,
)

_ROLES = ("coordinator", "researcher")
_QUESTION_ID = "SCI-096"
_FROZEN_NOW = "2026-08-28T00:00:00Z"


# ---------------------------------------------------------------------------
# policy + chain fixtures


def _shadow_policy_payload(**capability_overrides) -> dict:
    capabilities = {name: True for name in sorted(AUTO_ADVANCE_CAPABILITIES)}
    capabilities.update(capability_overrides)
    payload = {
        "schemaVersion": "1.0.0",
        "policyId": "cc-auto-advance-policy-shadow-test",
        "version": "2.0.0-candidate.1",
        "status": "candidate",
        "executionMode": "shadow",
        "createdAt": "2026-08-28T00:00:00+08:00",
        "capabilities": capabilities,
        "maxRevisionRounds": 2,
        "maxRevisionRoundsAdjustableTo": 1,
        "allowedRiskClasses": ["low_risk_standard"],
        "effectiveFromCheckpoint": None,
        "drainMode": "none",
        "uiPresets": None,
        "calibrationGate": {
            "confusionMatrix": {
                "axes": ["autoAdvanceDecision", "humanReviewDecision"]
            },
            "kappaWithCI": {
                "measure": "cohens_kappa",
                "minimumKappa": 0.75,
                "confidenceInterval": "95_percent",
            },
            "stratifiedBy": ["risk_class", "catalog_domain"],
            "falseAutoApproveUpperBound": {
                "method": "wilson",
                "side": "one_sided_upper",
            },
            "sequentialSamplingDeclaration": {
                "mode": "fixed_n_then_sequential_extension",
                "declaredBeforeUnblinding": True,
            },
            "notAPermanentDelegation": True,
        },
        "supersedes": {
            "policyId": "cc-auto-advance-policy-001",
            "supersededFields": ["autoAdvanceLevel"],
        },
        "activationRequires": (
            "explicit approval recorded against policyId + version + contentHash"
        ),
        "approval": {
            "requiredApprovers": ["competition_owner"],
            "approvedBy": [],
            "frozenAt": None,
            "contentHash": None,
            "contentHashRule": (
                "sha256 over canonical JSON (sort_keys=True, separators=(',',':'), "
                "ensure_ascii=False) with contentHash set to null; uppercase hex"
            ),
        },
    }
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    return payload


@pytest.fixture
def shadow_policy() -> AutoAdvancePolicyV2:
    return AutoAdvancePolicyV2.from_dict(_shadow_policy_payload())


@pytest.fixture
def shadow_policy_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "auto-advance-policy.json"
    path.write_text(
        json.dumps(_shadow_policy_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setenv(ev.SHADOW_POLICY_ENV, str(path))
    ev._POLICY_CACHE.clear()
    return path


class _InlineExecutor:
    """Run submitted chat-room rounds synchronously (DEV tests only)."""

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - surfaced via future
            future.set_exception(exc)
        return future


@pytest.fixture
def hf_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    reset_formal_write_runtime_for_tests()
    from core.web.services.team_workflow import (
        hypothesis_rounds as hrounds,
        meeting_rounds as meetings,
        personal_memory_candidates as memories,
        research_templates as templates,
    )

    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(templates, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    # The R2.2 claim belief gate reads the claim ledger inside chain_state;
    # pin its store root to the tmp workspace like every other store.
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    monkeypatch.setattr(claim_ledger_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _InlineExecutor())
    monkeypatch.delenv(ev.SHADOW_POLICY_ENV, raising=False)
    ev._POLICY_CACHE.clear()
    agents: dict[str, str] = {}
    for role in (
        *_ROLES,
        "source_finder",
        "source_relation_mapper",
        "experiment_planner",
        "experiment_ledger",
    ):
        agent = agent_directory_service.create_agent_instance(
            display_name=f"shadow {role}", role_key=role, created_by="shadow-test"
        )
        session_service.ensure_agent_direct_session(
            agent_id=agent["agentId"], title=f"shadow {role}"
        )
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="shadow 评估团队",
        purpose="policy-shadow-evaluator",
        members=[
            {"agentId": agents[role], "role": role} for role in agents
        ],
    )["teamId"]
    return team_id, agents


def _patch_approved_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """Define the approved question artifact with hyp-a/hyp-b/hyp-c candidates."""

    from core.web.services.team_workflow.research_runtime import question_launch

    detail = {
        "teamId": "shadow",
        "questionId": _QUESTION_ID,
        "selectedRunId": "stage1-sci-096-v1",
        "record": {
            "questionId": _QUESTION_ID,
            "runId": "stage1-sci-096-v1",
            "schemaVersion": 2,
            "submissionEligible": True,
            "status": "approved",
            "humanGates": {
                "allApproved": True,
                "decisions": {
                    "H1_problem_understanding": "approved",
                    "H2_hypothesis_selection": "approved",
                    "H3_research_plan": "approved",
                    "H4_external_output": "approved",
                },
            },
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": _QUESTION_ID,
                "question_en": "Fixture question",
            },
            "hypotheses": [
                {"hypothesis_id": "hyp-a", "statement": "candidate hyp-a"},
                {"hypothesis_id": "hyp-b", "statement": "candidate hyp-b"},
            ],
            "selection": {"selected_hypothesis_id": "hyp-a"},
            "review": {"human_review_status": "passed"},
            "submission": {"eligible": True},
        },
        "artifact": {"sha256": "b" * 64, "immutable": True},
    }
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: {_QUESTION_ID.upper(): detail},
    )


def _scope_fields(agent_id: str) -> dict[str, str]:
    return {
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": _QUESTION_ID,
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": agent_id,
        "mode": "dev",
    }


def _selection_payload(agent_id: str, **overrides) -> dict:
    payload = {
        **_scope_fields(agent_id),
        "questionId": _QUESTION_ID,
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
        "decidedBy": agent_id,
    }
    payload.update(overrides)
    return payload


def _marker_runner(participant, prompt, context):
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role in {"source_finder", "challenge_cup_search"}:
        content = "AGREE: hyp-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: hyp-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: researcher | 补充 hyp-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _generation_runner(participant, prompt, context):
    role = str(participant.get("teamRole") or "participant")
    if role in {"source_finder", "challenge_cup_search"}:
        content = (
            "CANDIDATE: cand-a | 睡眠剥夺通过腺苷积累损害记忆巩固 | 腺苷受体机制明确\n"
            "CANDIDATE: cand-b | 睡眠剥夺通过突触稳态失衡损害记忆巩固 | 突触稳态假说"
        )
    else:
        content = "AGREE: cand-a 的检验路径更直接"
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _select_decision(agent_id: str) -> dict:
    return {
        "decision": "select_candidate",
        "rationale": "hyp-a 证据最完整，收敛进入实验设计。",
        "decidedBy": agent_id,
        "candidateRefs": ["hyp-a"],
        "evidenceRefs": ["evidence:review-matrix-2"],
        "status": "adopted",
    }


def _closure_payload(agent_ids: list[str], decisions: list[dict]) -> dict:
    return {
        "decisions": decisions,
        "closedBy": agent_ids[0],
        "memorySummaries": {agent_id: f"{agent_id} 的评审记忆" for agent_id in agent_ids},
        "memoryClass": "lesson",
        "reusePolicy": "reusable_same_scope",
        "evidenceStatus": "reported",
    }


def _drive_to_awaiting_approval(team_id: str, meeting_round_id: str, actor: str) -> None:
    drafted = meeting_runtime.prepare_meeting_summary_draft(
        team_id, meeting_round_id, actor=actor, force=False
    )
    assert drafted["status"] == "awaiting_approval"


def _open_first_meeting(
    team_id: str, agent_ids: list[str], **selection_overrides
) -> list[dict]:
    recorded = selections.record_hypothesis_selection(
        team_id,
        _selection_payload(agent_ids[0], **selection_overrides),
        agent_runner=_marker_runner,
    )
    assert recorded["status"] == "created"
    review = recorded["reviewMeeting"]
    siblings = list(review.get("reviewMeetings") or [])
    if siblings:
        return [dict(item["meetingRound"]) for item in siblings]
    return [dict(review["meetingRound"])]


def _shadow_records(team_id: str, question_id: str = _QUESTION_ID) -> list[dict]:
    listed = ev.list_policy_shadow_evaluations(team_id, question_id=question_id)
    return listed["evaluations"]


def _store_path(team_id: str) -> Path:
    return ev.policy_shadow_store_path(team_id)


# ---------------------------------------------------------------------------
# pure wouldDecide rules (table-driven, one row per documented gate)


def _meeting_close_context(**overrides) -> dict:
    context = {
        "meetingRoundId": "meeting-1",
        "meetingType": "hypothesis_review",
        "closureApproved": True,
        "digestConfirmed": True,
        "decisionsResolved": True,
        "unresolvedDecisionCount": 0,
        "closedBy": "agent-1",
    }
    context.update(overrides)
    return context


def test_would_decide_table(shadow_policy: AutoAdvancePolicyV2) -> None:
    cases = [
        # meeting_close / autoCloseMeetingRound -> auto_close iff the full
        # confirmation chain passed.
        ("meeting_close", _meeting_close_context(), "auto_close"),
        (
            "meeting_close",
            _meeting_close_context(digestConfirmed=False),
            "hold",
        ),
        (
            "meeting_close",
            _meeting_close_context(decisionsResolved=False, unresolvedDecisionCount=1),
            "hold",
        ),
        (
            "meeting_close",
            _meeting_close_context(closureApproved=False),
            "hold",
        ),
        (
            "meeting_close",
            _meeting_close_context(closedBy=""),
            "hold",
        ),
        # candidate_selection / autoSelectCandidates -> auto_select iff every
        # candidate carries a score, all clear the threshold, and the count
        # stays within the finalist limit.
        (
            "candidate_selection",
            {
                "candidates": [
                    {"candidateId": "hyp-a", "score": 0.9},
                    {"candidateId": "hyp-b", "score": 0.8},
                ],
                "minScore": 0.75,
                "finalistLimit": 3,
            },
            "auto_select",
        ),
        (
            "candidate_selection",
            {
                "candidates": [{"candidateId": "hyp-a", "score": 0.5}],
                "minScore": 0.75,
            },
            "hold",
        ),
        (
            "candidate_selection",
            {"candidates": [{"candidateId": "hyp-a"}]},
            "hold",
        ),
        (
            "candidate_selection",
            {
                "candidates": [
                    {"candidateId": f"hyp-{index}", "score": 0.9}
                    for index in range(6)
                ],
                "finalistLimit": 5,
            },
            "hold",
        ),
        ("candidate_selection", {"candidates": []}, "hold"),
        # evidence_repair / autoStartEvidenceRepair -> auto_repair iff a gap
        # exists and the bounded revision budget has remaining rounds.
        (
            "evidence_repair",
            {"gapCount": 2, "revisionRoundsUsed": 0},
            "auto_repair",
        ),
        (
            "evidence_repair",
            {"gapCount": 1, "revisionRoundsUsed": 2},
            "hold",
        ),
        ("evidence_repair", {"gapCount": 0, "revisionRoundsUsed": 0}, "hold"),
        # converge_question / autoConvergeQuestion -> auto_converge mirrors the
        # chain_state convergence gates exactly.
        (
            "converge_question",
            {
                "roundId": "hround-1",
                "latestRoundClosed": True,
                "metaReviewAccepted": True,
                "newEvidenceRequestCount": 0,
                "pendingHandoffCount": 0,
            },
            "auto_converge",
        ),
        (
            "converge_question",
            {
                "roundId": "hround-1",
                "latestRoundClosed": True,
                "metaReviewAccepted": False,
                "newEvidenceRequestCount": 0,
                "pendingHandoffCount": 0,
            },
            "hold",
        ),
        (
            "converge_question",
            {
                "roundId": "hround-1",
                "latestRoundClosed": True,
                "metaReviewAccepted": True,
                "newEvidenceRequestCount": 1,
                "pendingHandoffCount": 0,
            },
            "hold",
        ),
        (
            "converge_question",
            {
                "roundId": "hround-1",
                "latestRoundClosed": True,
                "metaReviewAccepted": True,
                "newEvidenceRequestCount": 0,
                "pendingHandoffCount": 2,
            },
            "hold",
        ),
        # batch_gate / autoAdvanceBatchGate -> auto_gate iff every stage gate
        # passed and the budget is not exhausted.
        (
            "batch_gate",
            {"stageGates": {"g1": True, "g2": True}, "budgetExhausted": False},
            "auto_gate",
        ),
        (
            "batch_gate",
            {"stageGates": {"g1": True, "g2": False}, "budgetExhausted": False},
            "hold",
        ),
        (
            "batch_gate",
            {"stageGates": {"g1": True}, "budgetExhausted": True},
            "hold",
        ),
    ]
    for decision_point, context, expected in cases:
        decision = ev.evaluate_policy_shadow_decision(
            shadow_policy, decision_point, context, evaluated_at=_FROZEN_NOW
        )
        assert decision.wouldDecide == expected, (decision_point, context)
        assert decision.capability == POLICY_SHADOW_CAPABILITY_FOR_POINT[decision_point]
        assert decision.decisionPoint == decision_point
        assert decision.evaluatedAt == _FROZEN_NOW
        if expected != "hold":
            assert decision.wouldDecide == POLICY_SHADOW_ACTION_FOR_POINT[decision_point]
        # Advisory output only: the decision never carries a command.
        rendered = json.dumps(decision.to_dict())
        assert "command" not in rendered


def test_disabled_capability_switch_yields_hold_with_capability_gate(
    shadow_policy: AutoAdvancePolicyV2,
) -> None:
    policy = AutoAdvancePolicyV2.from_dict(
        _shadow_policy_payload(autoConvergeQuestion=False)
    )
    decision = ev.evaluate_policy_shadow_decision(
        policy,
        "converge_question",
        {
            "roundId": "hround-1",
            "latestRoundClosed": True,
            "metaReviewAccepted": True,
            "newEvidenceRequestCount": 0,
            "pendingHandoffCount": 0,
        },
    )
    assert decision.wouldDecide == "hold"
    capability_gate = next(
        entry for entry in decision.evidence if entry["gateId"] == "capabilityEnabled"
    )
    assert capability_gate["passed"] is False
    assert capability_gate["capability"] == "autoConvergeQuestion"


def test_decision_payload_summaries_reference_real_inputs(
    shadow_policy: AutoAdvancePolicyV2,
) -> None:
    selection = ev.evaluate_policy_shadow_decision(
        shadow_policy,
        "candidate_selection",
        {
            "candidates": [
                {"candidateId": "hyp-a", "score": 0.9},
                {"candidateId": "hyp-b", "score": 0.8},
            ],
            "minScore": 0.75,
        },
    )
    assert selection.wouldDecidePayload["candidateIds"] == ["hyp-a", "hyp-b"]
    threshold_gate = next(
        entry for entry in selection.evidence if entry["gateId"] == "scoresAboveThreshold"
    )
    assert threshold_gate["passed"] is True
    assert threshold_gate["minScore"] == 0.75
    assert threshold_gate["lowestScore"] == 0.8

    repair = ev.evaluate_policy_shadow_decision(
        shadow_policy,
        "evidence_repair",
        {"gapCount": 3, "revisionRoundsUsed": 1},
    )
    assert repair.wouldDecidePayload["gapCount"] == 3
    budget_gate = next(
        entry for entry in repair.evidence if entry["gateId"] == "revisionBudgetRemaining"
    )
    assert budget_gate["maxRevisionRounds"] == shadow_policy.maxRevisionRounds


def test_evaluation_rejects_unknown_point_and_non_policy(
    shadow_policy: AutoAdvancePolicyV2,
) -> None:
    with pytest.raises(ev.PolicyShadowEvaluationError) as unknown:
        ev.evaluate_policy_shadow_decision(shadow_policy, "gut_feeling", {})
    assert unknown.value.code == "unsupported_decision_point"
    with pytest.raises(ev.PolicyShadowEvaluationError) as not_policy:
        ev.evaluate_policy_shadow_decision({"executionMode": "shadow"}, "meeting_close", {})
    assert not_policy.value.code == "unsupported_policy"


def test_active_policy_is_refused_fail_closed() -> None:
    # An in-memory active policy (the shape activation will produce once an
    # activation path exists) must never be shadow-evaluable.
    payload = _shadow_policy_payload()
    payload["executionMode"] = "active"
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    with pytest.raises(Exception):
        # Preview validation refuses to even parse an active policy...
        AutoAdvancePolicyV2.from_dict(payload)
    active = AutoAdvancePolicyV2(
        policyId="cc-auto-advance-active",
        version="2.0.0-candidate.1",
        status="approved",
        executionMode="active",
        schemaVersion="1.0.0",
        capabilities={name: True for name in sorted(AUTO_ADVANCE_CAPABILITIES)},
        maxRevisionRounds=2,
        maxRevisionRoundsAdjustableTo=1,
        allowedRiskClasses=["low_risk_standard"],
        effectiveFromCheckpoint=None,
        drainMode="none",
        calibrationGate={},
        uiPresets={},
        supersedes={"policyId": "cc-auto-advance-policy-001"},
        activationRequires="explicit approval",
        declaredContentHash="A" * 64,
    )
    with pytest.raises(ev.PolicyShadowEvaluationError) as refused:
        ev.evaluate_policy_shadow_decision(active, "meeting_close", _meeting_close_context())
    assert refused.value.code == "active_execution_mode_forbidden"
    decision = PolicyShadowDecision(
        schemaVersion=POLICY_SHADOW_SCHEMA_VERSION,
        capability="autoCloseMeetingRound",
        decisionPoint="meeting_close",
        wouldDecide="auto_close",
        wouldDecidePayload={},
        evidence=[{"gateId": "capabilityEnabled", "passed": True}],
        evaluatedAt=_FROZEN_NOW,
    )
    with pytest.raises(ContractValidationError, match="policyExecutionMode"):
        ev.build_policy_shadow_evaluation_record(
            decision,
            policy=active,
            team_id="team-1",
            question_id=_QUESTION_ID,
            actual_outcome={"outcome": "closed", "outcomeClass": "acted"},
        )


# ---------------------------------------------------------------------------
# record contracts (fail-closed)


def test_agreement_derivation_matches_g12_calibration_shape() -> None:
    assert derive_shadow_agreement("auto_close", "acted") == "agree"
    assert derive_shadow_agreement("auto_converge", "escalated") == "false_auto_approve"
    assert derive_shadow_agreement("auto_select", "vetoed") == "false_auto_approve"
    assert derive_shadow_agreement("hold", "acted") == "false_escalate"
    assert derive_shadow_agreement("hold", "escalated") == "agree"
    assert derive_shadow_agreement("hold", "none") == "neutral"
    assert derive_shadow_agreement("auto_gate", "none") == "neutral"


def test_record_roundtrips_and_pins_shadow_policy_snapshot(
    shadow_policy: AutoAdvancePolicyV2,
) -> None:
    decision = ev.evaluate_policy_shadow_decision(
        shadow_policy,
        "converge_question",
        {
            "roundId": "hround-1",
            "latestRoundClosed": True,
            "metaReviewAccepted": True,
            "newEvidenceRequestCount": 0,
            "pendingHandoffCount": 0,
        },
        evaluated_at=_FROZEN_NOW,
    )
    record = ev.build_policy_shadow_evaluation_record(
        decision,
        policy=shadow_policy,
        team_id="team-1",
        question_id="sci-096",
        actual_outcome={
            "outcome": "closed_without_new_evidence",
            "outcomeClass": "acted",
            "command": "close_review_meeting",
            "ref": "meeting_round:m-1",
        },
        scope={"program": "XH-202619", "theme": "cc-neuro-001"},
    )
    assert record.agreement == "agree"
    assert record.questionId == "SCI-096"
    assert record.policyId == shadow_policy.policyId
    assert record.policyContentHash == shadow_policy.declaredContentHash
    assert record.policyExecutionMode == "shadow"

    restored = PolicyShadowEvaluationRecord.from_dict(record.to_dict())
    assert restored == record
    assert restored.to_dict() == record.to_dict()


@pytest.mark.parametrize(
    "would,outcome_class,expected_agreement",
    [
        ("auto_close", "acted", "agree"),
        ("auto_close", "escalated", "false_auto_approve"),
        ("hold", "acted", "false_escalate"),
        ("hold", "escalated", "agree"),
        ("auto_close", "none", "neutral"),
    ],
)
def test_record_agreement_is_derived_never_free_form(
    shadow_policy: AutoAdvancePolicyV2, would, outcome_class, expected_agreement
) -> None:
    decision = ev.evaluate_policy_shadow_decision(
        shadow_policy,
        "meeting_close",
        _meeting_close_context(),
        evaluated_at=_FROZEN_NOW,
    )
    forced = PolicyShadowDecision(
        schemaVersion=POLICY_SHADOW_SCHEMA_VERSION,
        capability=decision.capability,
        decisionPoint=decision.decisionPoint,
        wouldDecide=would,
        wouldDecidePayload=decision.wouldDecidePayload,
        evidence=decision.evidence,
        evaluatedAt=_FROZEN_NOW,
    )
    record = ev.build_policy_shadow_evaluation_record(
        forced,
        policy=shadow_policy,
        team_id="team-1",
        question_id=_QUESTION_ID,
        actual_outcome={"outcome": "whatever", "outcomeClass": outcome_class},
    )
    assert record.agreement == expected_agreement


def test_record_rejects_tampered_agreement_and_wrong_point_action(
    shadow_policy: AutoAdvancePolicyV2,
) -> None:
    decision = ev.evaluate_policy_shadow_decision(
        shadow_policy, "meeting_close", _meeting_close_context(), evaluated_at=_FROZEN_NOW
    )
    record = ev.build_policy_shadow_evaluation_record(
        decision,
        policy=shadow_policy,
        team_id="team-1",
        question_id=_QUESTION_ID,
        actual_outcome={"outcome": "closed", "outcomeClass": "acted"},
    )
    tampered = record.to_dict()
    tampered["agreement"] = "false_auto_approve"
    with pytest.raises(ContractValidationError, match="agreement"):
        PolicyShadowEvaluationRecord.from_dict(tampered)

    wrong_point = record.to_dict()
    wrong_point["decisionPoint"] = "converge_question"
    with pytest.raises(ContractValidationError, match="capability"):
        PolicyShadowEvaluationRecord.from_dict(wrong_point)

    wrong_action = record.to_dict()
    wrong_action["wouldDecide"] = "auto_converge"
    with pytest.raises(ContractValidationError, match="wouldDecide"):
        PolicyShadowEvaluationRecord.from_dict(wrong_action)

    unknown_point = record.to_dict()
    unknown_point["decisionPoint"] = "gut_feeling"
    with pytest.raises(ContractValidationError, match="decisionPoint"):
        PolicyShadowEvaluationRecord.from_dict(unknown_point)


def test_record_rejects_unknown_enums_and_missing_identity(
    shadow_policy: AutoAdvancePolicyV2,
) -> None:
    decision = ev.evaluate_policy_shadow_decision(
        shadow_policy, "meeting_close", _meeting_close_context(), evaluated_at=_FROZEN_NOW
    )
    record = ev.build_policy_shadow_evaluation_record(
        decision,
        policy=shadow_policy,
        team_id="team-1",
        question_id=_QUESTION_ID,
        actual_outcome={"outcome": "closed", "outcomeClass": "acted"},
    )
    payload = record.to_dict()
    payload["actualOutcome"]["outcomeClass"] = "sort_of_acted"
    with pytest.raises(ContractValidationError, match="outcomeClass"):
        PolicyShadowEvaluationRecord.from_dict(payload)

    no_team = record.to_dict()
    no_team["teamId"] = ""
    with pytest.raises(ContractValidationError, match="teamId"):
        PolicyShadowEvaluationRecord.from_dict(no_team)

    bad_hash = record.to_dict()
    bad_hash["policyContentHash"] = "not-a-hash"
    with pytest.raises(ContractValidationError, match="policyContentHash"):
        PolicyShadowEvaluationRecord.from_dict(bad_hash)


# ---------------------------------------------------------------------------
# chain hooks: behavior identical + records produced


def test_review_closure_shadow_records_match_convergence_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hf_env,
    shadow_policy_file: Path,
) -> None:
    team_id, agents = hf_env
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]

    with server_operator_scope("u-1", roles=("operator",)):
        siblings = _open_first_meeting(team_id, agent_ids)
        assert len(siblings) == 2
        # R2.2 claim belief gate: seed review-supported core claims for the
        # selected candidates so the otherwise-converged chain can converge.
        _seed_claim_belief_gate_fixture(
            monkeypatch, team_id, _QUESTION_ID, ["hyp-a", "hyp-b"]
        )

        first_id = siblings[0]["meetingRoundId"]
        _drive_to_awaiting_approval(team_id, first_id, agent_ids[0])
        closed_first = chain.close_review_meeting(
            team_id,
            first_id,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
        # Execution behavior is unchanged by the shadow hook.
        assert closed_first["meetingRound"]["status"] == "closed"
        assert closed_first["hypothesisRound"]["status"] == "waiting_for_sibling_reviews"
        assert closed_first["collection"]["requests"] == []

        records = _shadow_records(team_id)
        assert [item["decisionPoint"] for item in records] == [
            "meeting_close",
            "converge_question",
        ]
        close_record = records[0]
        assert close_record["capability"] == "autoCloseMeetingRound"
        assert close_record["wouldDecide"] == "auto_close"
        assert close_record["agreement"] == "agree"
        assert close_record["actualOutcome"]["command"] == "close_review_meeting"
        assert close_record["policyId"] == "cc-auto-advance-policy-shadow-test"
        assert len(close_record["policyContentHash"]) == 64
        # Sibling round still open -> the policy would NOT converge yet, while
        # the human closed anyway: false_escalate calibration signal.
        converge_record = records[1]
        assert converge_record["capability"] == "autoConvergeQuestion"
        assert converge_record["wouldDecide"] == "hold"
        assert converge_record["agreement"] == "false_escalate"

        second_id = siblings[1]["meetingRoundId"]
        _drive_to_awaiting_approval(team_id, second_id, agent_ids[0])
        closed_second = chain.close_review_meeting(
            team_id,
            second_id,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
        assert closed_second["meetingRound"]["status"] == "closed"
        generated = closed_second["hypothesisRound"]
        assert generated["status"] == "created"
        assert generated["round"]["metaReview"]["accepted"] is True

        records = _shadow_records(team_id)
        assert len(records) == 4
        final_close = records[2]
        final_converge = records[3]
        assert final_close["wouldDecide"] == "auto_close"
        assert final_close["agreement"] == "agree"
        # All convergence hard gates pass (round closed, meta review accepted,
        # zero new requests, zero pending handoffs): the policy WOULD have
        # auto-converged exactly where the human converged.
        assert final_converge["wouldDecide"] == "auto_converge"
        assert final_converge["agreement"] == "agree"
        assert final_converge["wouldDecidePayload"]["roundId"] == generated["roundId"]
        assert final_converge["actualOutcome"]["outcome"] == "closed_without_new_evidence"
        assert final_converge["evidence"] != []

        # Shadow records never leak into the executing chain ledger.
        assert all("wouldDecide" not in item for item in chain._records(team_id))

        # Chain-state convergence (the authoritative read model) is unchanged.
        state = chain.chain_state(team_id, _QUESTION_ID)
        assert state["hypothesisConverged"] is True


def test_generation_digest_confirmation_shadow_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hf_env,
    shadow_policy_file: Path,
) -> None:
    team_id, agents = hf_env
    from core.web.services.team_workflow.research_runtime import question_launch

    monkeypatch.setattr(
        question_launch,
        "challenge_question_run_summary",
        lambda _team_id: {"completedQuestionIds": [], "completedQuestionResults": []},
    )
    with server_operator_scope("u-1", roles=("operator",)):
        opened = chain.open_candidate_generation_meeting(
            team_id, _QUESTION_ID, agent_runner=_generation_runner
        )
        meeting_round_id = opened["meetingRound"]["meetingRoundId"]
        agent_ids = [agents[role] for role in _ROLES]
        _drive_to_awaiting_approval(team_id, meeting_round_id, agent_ids[0])
        closed = chain.close_review_meeting(
            team_id, meeting_round_id, _closure_payload(agent_ids, [])
        )
        # Behavior unchanged: candidates registered, meeting closed.
        assert closed["meetingRound"]["status"] == "closed"
        assert closed["candidateCount"] == 2

        records = _shadow_records(team_id)
        assert [item["decisionPoint"] for item in records] == ["meeting_close"]
        record = records[0]
        assert record["capability"] == "autoCloseMeetingRound"
        assert record["wouldDecide"] == "auto_close"
        assert record["agreement"] == "agree"
        assert record["actualOutcome"]["outcome"] == "generation_digest_approved"
        assert record["actualOutcome"]["ref"] == f"meeting_round:{meeting_round_id}"
        assert record["scope"].get("question") == _QUESTION_ID


def test_envelope_closure_records_escalated_converge_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hf_env,
    shadow_policy_file: Path,
) -> None:
    team_id, agents = hf_env
    _patch_approved_question(monkeypatch)
    from core.web.services.team_workflow.source_collection import runs as collection_runs

    def fake_start(team_id, payload=None):
        return {"runId": "dprun-shadow-1", "status": "accepted"}

    def fake_background_start(team_id, run_id, payload=None):
        return {"teamId": team_id, "runId": run_id, "status": "running"}

    monkeypatch.setattr(collection_runs, "start_source_collection_run", fake_start)
    monkeypatch.setattr(
        collection_runs, "start_source_collection_search_background", fake_background_start
    )
    agent_ids = [agents[role] for role in _ROLES]
    envelope_decision = {
        "decision": "request_new_evidence",
        "rationale": "hyp-b 的泛化证据不足，需要按信封补充搜集。",
        "decidedBy": agent_ids[0],
        "candidateRefs": ["hyp-b"],
        "evidenceRefs": ["evidence:review-matrix-1"],
        "status": "adopted",
        "searchEnvelope": {
            "keywords": ["predictive coding", "spike train coding"],
            "sourceTypes": ["paper"],
            "evidenceLevels": ["peer_reviewed"],
        },
        "requirements": {"minEvidenceLevel": "medium", "completeness": "stage-one"},
        "writebackPolicy": {},
    }
    with server_operator_scope("u-1", roles=("operator",)):
        siblings = _open_first_meeting(team_id, agent_ids)
        first_id = siblings[0]["meetingRoundId"]
        _drive_to_awaiting_approval(team_id, first_id, agent_ids[0])
        closed = chain.close_review_meeting(
            team_id,
            first_id,
            _closure_payload(agent_ids, [envelope_decision]),
        )
        assert closed["meetingRound"]["status"] == "closed"
        assert len(closed["collection"]["requests"]) == 1

        records = _shadow_records(team_id)
        converge = next(
            item for item in records if item["decisionPoint"] == "converge_question"
        )
        # New evidence requested -> policy would hold AND the human escalated:
        # consistent (agree), never a false auto-approve.
        assert converge["wouldDecide"] == "hold"
        assert converge["agreement"] == "agree"
        assert converge["actualOutcome"]["outcomeClass"] == "escalated"
        assert converge["actualOutcome"]["outcome"] == "requested_new_evidence"
        assert converge["wouldDecidePayload"]["newEvidenceRequestCount"] == 1


def test_closure_without_shadow_policy_is_unchanged_and_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hf_env
) -> None:
    team_id, agents = hf_env  # fixture guarantees the policy env is unset
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        siblings = _open_first_meeting(team_id, agent_ids)
        _seed_claim_belief_gate_fixture(
            monkeypatch, team_id, _QUESTION_ID, ["hyp-a", "hyp-b"]
        )
        results = []
        for sibling in siblings:
            meeting_id = sibling["meetingRoundId"]
            _drive_to_awaiting_approval(team_id, meeting_id, agent_ids[0])
            results.append(
                chain.close_review_meeting(
                    team_id,
                    meeting_id,
                    _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
                )
            )
        assert results[0]["meetingRound"]["status"] == "closed"
        assert results[0]["hypothesisRound"]["status"] == "waiting_for_sibling_reviews"
        assert results[1]["hypothesisRound"]["status"] == "created"
        assert results[1]["hypothesisRound"]["round"]["metaReview"]["accepted"] is True
        assert results[1]["collection"]["requests"] == []
        # Same frozen baseline the shadow-enabled twin asserts: the closure
        # result shape is identical with and without a shadow policy.
        assert _closure_result_shape(results[0]) == _FIRST_SELECT_CLOSURE_SHAPE

        state = chain.chain_state(team_id, _QUESTION_ID)
        assert state["hypothesisConverged"] is True
        assert state["collectionReady"] is True

        # No policy configured -> no shadow store, no chain ledger pollution.
        assert not _store_path(team_id).exists()
        assert _shadow_records(team_id) == []
        assert all("wouldDecide" not in item for item in chain._records(team_id))


def _closure_result_shape(result: dict) -> dict:
    """Comparable, id-free shape of one ``close_review_meeting`` result."""

    meeting = result["meetingRound"]
    hypothesis_round = result["hypothesisRound"]
    collection = result["collection"]
    return {
        "topLevelKeys": sorted(result),
        "meetingStatus": meeting["status"],
        "meetingType": meeting["meetingType"],
        "hypothesisRoundStatus": hypothesis_round["status"],
        "hypothesisRoundKeys": sorted(hypothesis_round),
        "collectionKeys": sorted(collection),
        "requestCount": len(collection["requests"]),
        "skippedCount": len(collection["skipped"]),
    }


# The frozen baseline both runs must reproduce: the shadow hook may not add,
# drop, or alter any closure result field.
_FIRST_SELECT_CLOSURE_SHAPE = {
    "topLevelKeys": sorted(
        {
            "schemaVersion",
            "teamId",
            "status",
            "closed",
            "meetingRound",
            "digest",
            "decisions",
            "personalMemoryCandidateRefs",
            "memorySummary",
            "storagePath",
            "collection",
            "hypothesisRound",
            "resume",
            # Sibling archive gate report appended by a88e6f9d6; present on
            # every close_review_meeting result regardless of shadow policy.
            "deferredNextReview",
        }
    ),
    "meetingStatus": "closed",
    "meetingType": "hypothesis_review",
    "hypothesisRoundStatus": "waiting_for_sibling_reviews",
    "hypothesisRoundKeys": [
        "closed",
        "closedMeetingRoundIds",
        # Persisted failure-trace id appended by the round-persist-fallback
        # chain (hypothesis_round_failures ledger), present on every
        # waiting/failed generation attempt regardless of shadow policy.
        "failureRecordId",
        "missingCandidateIds",
        "pendingMeetingRoundIds",
        "roundIndex",
        "selectionId",
        "status",
        "supersededCandidateIds",
        "supersededMeetingRoundIds",
    ],
    "collectionKeys": ["requests", "skipped"],
    "requestCount": 0,
    "skippedCount": 0,
}


def test_closure_result_shape_identical_with_and_without_shadow_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hf_env,
    shadow_policy_file: Path,
) -> None:
    """With a shadow policy configured, the closure result keeps the exact
    baseline shape (the no-shadow twin of this assertion lives in
    ``test_closure_without_shadow_policy_is_unchanged_and_records_nothing``).
    """

    team_id, agents = hf_env
    _patch_approved_question(monkeypatch)
    agent_ids = [agents[role] for role in _ROLES]
    with server_operator_scope("u-1", roles=("operator",)):
        siblings = _open_first_meeting(team_id, agent_ids)
        meeting_id = siblings[0]["meetingRoundId"]
        _drive_to_awaiting_approval(team_id, meeting_id, agent_ids[0])
        closed_with_shadow = chain.close_review_meeting(
            team_id,
            meeting_id,
            _closure_payload(agent_ids, [_select_decision(agent_ids[0])]),
        )
    assert _closure_result_shape(closed_with_shadow) == _FIRST_SELECT_CLOSURE_SHAPE
    assert _store_path(team_id).exists()
    assert len(_shadow_records(team_id)) == 2


def test_policy_source_env_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ev.SHADOW_POLICY_ENV, raising=False)
    ev._POLICY_CACHE.clear()
    assert ev.load_shadow_policy_from_environment() is None

    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(_shadow_policy_payload(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv(ev.SHADOW_POLICY_ENV, str(path))
    policy = ev.load_shadow_policy_from_environment()
    assert policy is not None
    assert policy.executionMode == "shadow"
    # Cached per path/mtime/size: a second load returns the same document.
    assert ev.load_shadow_policy_from_environment() is policy

    monkeypatch.setenv(ev.SHADOW_POLICY_ENV, str(tmp_path / "missing.json"))
    ev._POLICY_CACHE.clear()
    assert ev.load_shadow_policy_from_environment() is None

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(_shadow_policy_payload())[:-20], encoding="utf-8")
    monkeypatch.setenv(ev.SHADOW_POLICY_ENV, str(broken))
    ev._POLICY_CACHE.clear()
    assert ev.load_shadow_policy_from_environment() is None


def test_record_jsonl_store_is_dedicated_and_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shadow_policy: AutoAdvancePolicyV2
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv(ev.SHADOW_POLICY_ENV, raising=False)
    ev._POLICY_CACHE.clear()
    team_id = "shadow-store-team"
    decision = ev.evaluate_policy_shadow_decision(
        shadow_policy, "meeting_close", _meeting_close_context(), evaluated_at=_FROZEN_NOW
    )
    record = ev.build_policy_shadow_evaluation_record(
        decision,
        policy=shadow_policy,
        team_id=team_id,
        question_id=_QUESTION_ID,
        actual_outcome={"outcome": "closed", "outcomeClass": "acted"},
    )
    ev.append_policy_shadow_evaluation_record(record)
    ev.append_policy_shadow_evaluation_record(record)
    path = _store_path(team_id)
    assert path.name == ev.SHADOW_EVALUATION_STORE_FILENAME
    assert path.parent.name == "research_workflow"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["recordId"] == record.recordId
    assert _shadow_records(team_id) == rows


def test_record_policy_shadow_decision_safely_degrades_quietly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shadow_policy: AutoAdvancePolicyV2
) -> None:
    monkeypatch.delenv(ev.SHADOW_POLICY_ENV, raising=False)
    ev._POLICY_CACHE.clear()
    # No policy configured -> silent no-op, no store.
    assert (
        ev.record_policy_shadow_decision_safely(
            team_id="team-x",
            question_id=_QUESTION_ID,
            decision_point="meeting_close",
            context=_meeting_close_context(),
            actual_outcome={"outcome": "closed", "outcomeClass": "acted"},
        )
        is None
    )
    assert not _store_path("team-x").exists()

    # Fail-closed violations are swallowed into a None result (never raised).
    payload = _shadow_policy_payload()
    payload["executionMode"] = "active"
    payload["approval"]["contentHash"] = compute_policy_content_hash(payload)
    active = AutoAdvancePolicyV2(
        policyId=payload["policyId"],
        version=payload["version"],
        status=payload["status"],
        executionMode="active",
        schemaVersion=payload["schemaVersion"],
        capabilities=dict(payload["capabilities"]),
        maxRevisionRounds=2,
        maxRevisionRoundsAdjustableTo=1,
        allowedRiskClasses=list(payload["allowedRiskClasses"]),
        effectiveFromCheckpoint=None,
        drainMode="none",
        calibrationGate={},
        uiPresets={},
        supersedes=dict(payload["supersedes"]),
        activationRequires=payload["activationRequires"],
        declaredContentHash=payload["approval"]["contentHash"],
    )
    assert (
        ev.record_policy_shadow_decision_safely(
            team_id="team-x",
            question_id=_QUESTION_ID,
            decision_point="meeting_close",
            context=_meeting_close_context(),
            actual_outcome={"outcome": "closed", "outcomeClass": "acted"},
        )
        is None
    )
    # The active policy would raise through the non-safe entry point.
    with pytest.raises(ev.PolicyShadowEvaluationError):
        ev.record_policy_shadow_decision(
            team_id="team-x",
            question_id=_QUESTION_ID,
            policy=active,
            decision_point="meeting_close",
            context=_meeting_close_context(),
            actual_outcome={"outcome": "closed", "outcomeClass": "acted"},
        )


def test_unused_fixture_payloads_stay_valid(shadow_policy: AutoAdvancePolicyV2) -> None:
    """Guards the fixture builder itself: all-on switch matrix parses."""

    assert set(shadow_policy.capabilities) == AUTO_ADVANCE_CAPABILITIES
    assert shadow_policy.enabled_capabilities == tuple(sorted(AUTO_ADVANCE_CAPABILITIES))
    assert deepcopy(shadow_policy) is not None
