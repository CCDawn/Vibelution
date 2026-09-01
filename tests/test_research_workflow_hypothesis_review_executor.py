"""HF-3 hypothesis review executor tests.

Covers the batch contract: a closed ``hypothesis_review`` meeting (digest v2
with ``sourceMessageRefs`` + decision records) feeds the four-step separated
review — Reflection (per-candidate 5+2 scoring: five decision dimensions plus
two auxiliary diagnostics, role
``research_evidence_reviewer``) -> Pairwise debate (every unordered pair with
randomized, recorded left/right order, role ``research_theme_synthesizer``)
-> Pareto classification (role ``research_theme_synthesizer``) -> MetaReview
(meeting Coordinator role, recommendation + acceptance).  The generated
``HypothesisRound`` passes ``validate_complete``; any missing dimension,
comparison, Pareto classification, or meeting ref fails closed without a
degraded write.  Lineage walks from any round back to the question candidates
with no gap, no cycle, and every round ref pointing at a closed record.

All review content comes from deterministic DEV fixtures or injected runners;
no real model or network is involved.
"""

from __future__ import annotations

import threading
import time

import pytest

from core.research.workflow.contracts import (
    COMPARISON_OUTCOMES,
    CORE_HYPOTHESIS_COHERENCE_CHECK_IDS,
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
    HYPOTHESIS_REVIEW_MEETING_TYPE,
    SCORE_DIMENSIONS,
    ContractValidationError,
    HypothesisRound,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import (
    hypothesis_review_executor,
    hypothesis_rounds,
    meeting_runtime,
    research_memory_context,
)
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow import personal_memory_candidates as memories
from tests._support.team_workflow.helpers import _use_tmp_project_root

_ROLES = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.participant_policy(
    HYPOTHESIS_REVIEW_MEETING_TYPE
).required_product_role_ids
_TEAM_ROLES = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_role_ids
_SELECTED_IDS = ("cand-a", "cand-b", "cand-c")


def _team_with_room(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(memories, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(hypothesis_rounds, "PROJECT_ROOT", tmp_path)
    agents: dict[str, str] = {}
    for role in _TEAM_ROLES:
        agent = agent_directory_service.create_agent_instance(display_name=f"HF3 {role}")
        session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title=f"HF3 {role}")
        agents[role] = agent["agentId"]
    team_id = team_service.create_team(
        name="HF-3 假说评审执行器团队",
        members=[{"agentId": agents[role], "role": role} for role in _TEAM_ROLES],
    )["teamId"]
    return team_id, agents


def _participant_agent_ids(agents):
    return [agents[role] for role in _ROLES]


def _selection_payload(agent_ids, **overrides):
    payload = {
        "selectionId": "sel-hf3-1",
        "questionId": "SCI-096",
        "selectedCandidateIds": list(_SELECTED_IDS),
        "decidedBy": agent_ids[0],
        "meetingRoundId": "meeting-hf3-1",
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": agent_ids[0],
        "mode": "dev",
        "participants": list(agent_ids),
    }
    payload.update(overrides)
    return payload


def _marker_runner(participant, prompt, context):
    """Round 1 carries the DEV fixture markers; follow-up critique rounds pass."""
    if "批评与修订" in str(prompt):
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}
    role = str(participant.get("teamRole") or "participant")
    if role == "challenge_cup_search":
        content = "AGREE: cand-a 的机制证据最完整，进入有界验证"
    else:
        content = (
            "DISAGREE: cand-b 的泛化证据不足\n"
            "RISK: 数据集偏差尚未评估\n"
            "ACTION: challenge_cup_experiment_revision | 补充 cand-b 的消融实验证据\n"
            "KNOWLEDGE: 预测编码层级最新综述"
        )
    return {"status": "completed", "raw_output": content, "summary": "ok"}


def _closure_payload(agent_ids, **overrides):
    payload = {
        "decisions": [
            {
                "decision": "select_candidate",
                "rationale": "cand-a 证据最完整，进入有界验证。",
                "decidedBy": agent_ids[0],
                "candidateRefs": ["cand-a"],
                "evidenceRefs": ["evidence:review-matrix-1"],
                "status": "adopted",
            }
        ],
        "closedBy": agent_ids[0],
        "memorySummaries": {agent_id: f"{agent_id} 的评审记忆" for agent_id in agent_ids},
        "memoryClass": "lesson",
        "reusePolicy": "reusable_same_scope",
        "evidenceStatus": "reported",
    }
    payload.update(overrides)
    return payload


def _open_and_close_meeting(team_id, agents, **overrides):
    agent_ids = _participant_agent_ids(agents)
    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(agent_ids, **overrides),
        agent_runner=_marker_runner,
        background=False,
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    approved = meetings.approve_meeting_closure(
        team_id, meeting_round_id, _closure_payload(agent_ids)
    )
    return opened, approved


def _closed_meeting(tmp_path, monkeypatch, **overrides):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    opened, approved = _open_and_close_meeting(team_id, agents, **overrides)
    return team_id, agents, opened, approved


def _candidate_inputs(*candidate_ids):
    return [
        {
            "candidateId": candidate_id,
            "claim": f"候选 {candidate_id} 的核心机制陈述：以不同归纳偏置提升样本效率",
            "differenceFromAlternatives": f"{candidate_id} 采用区别于其他入选候选的机制路径",
        }
        for candidate_id in candidate_ids
    ]


def _generate(team_id, meeting_round_id, candidate_ids=_SELECTED_IDS, **kwargs):
    payload = kwargs.pop("payload", None) or {}
    payload.setdefault("candidates", _candidate_inputs(*candidate_ids))
    return hypothesis_rounds.generate_hypothesis_round_from_meeting(
        team_id, meeting_round_id, payload, **kwargs
    )


def _walk_lineage_to_candidates(team_id, round_record):
    """Walk lineage from one round back to the question candidates.

    Asserts the chain has no cycle, every round ref resolves to a closed
    record of the same scope, and returns (round_chain, terminal candidate
    refs) where the terminal refs are the first round's question candidates.
    """
    chain = []
    seen: set[str] = set()
    current = round_record
    while True:
        round_id = str(current["roundId"])
        assert round_id not in seen, f"lineage cycle at {round_id}"
        seen.add(round_id)
        assert current["status"] == "closed", f"lineage round {round_id} is not closed"
        chain.append(current)
        round_refs = [item["id"] for item in current["lineage"] if item["kind"] == "round"]
        candidate_refs = [item["id"] for item in current["lineage"] if item["kind"] == "candidate"]
        if not round_refs:
            assert candidate_refs, f"lineage of {round_id} ends without question candidates"
            return chain, candidate_refs
        assert len(round_refs) == 1, f"lineage of {round_id} has multiple round refs"
        following = hypothesis_rounds.get_hypothesis_round(team_id, round_refs[0])["round"]
        assert following["scopeHash"] == current["scopeHash"], "lineage crosses scope boundary"
        current = following


def test_generate_from_closed_meeting_completes_full_review_loop(tmp_path, monkeypatch):
    team_id, agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round = approved["meetingRound"]
    digest = approved["digest"]
    assert meeting_round["status"] == "closed"
    assert digest["sourceMessageRefs"], "digest v2 must carry the message evidence trail"

    result = _generate(
        team_id, meeting_round["meetingRoundId"], payload={"positionSeed": "hf3-seed-1"}
    )

    assert result["status"] == "created"
    assert result["closed"] is True
    round_record = result["round"]
    assert round_record["status"] == "closed"
    assert round_record["scopeHash"] == meeting_round["scopeHash"]
    parsed = HypothesisRound.from_dict(round_record)
    parsed.validate_complete()

    # The exact Stage-1 review call budget is persisted with the round so the
    # G1 acceptance can prove the budget was respected (n=3 -> 8 calls).
    budget = round_record["reviewCallBudget"]
    assert budget["formula"] == "n + n(n-1)/2 + 2"
    assert budget["finalistCount"] == len(round_record["candidates"]) == 3
    assert budget["totalReviewCalls"] == 8
    assert budget["actual"]["reviewStepCalls"] == 8
    assert budget["actual"]["matchesFormula"] is True

    # Reflection: every candidate carries the five decision scores; auxiliary
    # diagnostics, when present, stay separate from the Pareto input.
    assert [item["candidateId"] for item in round_record["candidates"]] == list(_SELECTED_IDS)
    for candidate in round_record["candidates"]:
        assert set(candidate["scores"]) == set(SCORE_DIMENSIONS)
        assert all(0 <= score <= 1 for score in candidate["scores"].values())
        assert candidate["reviewedBy"] == hypothesis_review_executor.REFLECTION_ROLE
        assert candidate["status"] == "reviewed"
        assert candidate["claim"]
        assert candidate["differenceFromAlternatives"]

    # Pairwise debate: every unordered pair compared exactly once by the theme
    # synthesizer role, with the randomized left/right order recorded.
    comparisons = round_record["pairwiseComparisons"]
    assert len(comparisons) == 3
    assert {
        frozenset((item["leftCandidateId"], item["rightCandidateId"]))
        for item in comparisons
    } == {
        frozenset(pair)
        for pair in (("cand-a", "cand-b"), ("cand-a", "cand-c"), ("cand-b", "cand-c"))
    }
    for comparison in comparisons:
        assert comparison["reviewerAgentId"] == hypothesis_review_executor.PAIRWISE_ROLE
        assert comparison["outcome"] in COMPARISON_OUTCOMES
        assert comparison["justification"]
    replayed_order = hypothesis_review_executor.deterministic_pairwise_order(
        list(_SELECTED_IDS), "hf3-seed-1"
    )
    assert [
        (item["leftCandidateId"], item["rightCandidateId"]) for item in comparisons
    ] == replayed_order
    assert result["review"]["positionSeed"] == "hf3-seed-1"

    # Pareto classification covers every candidate exactly once.
    pareto = round_record["pareto"]
    classified = set(pareto["paretoFrontCandidateIds"]) | set(pareto["dominatedCandidateIds"])
    assert classified == set(_SELECTED_IDS)
    assert not set(pareto["paretoFrontCandidateIds"]) & set(pareto["dominatedCandidateIds"])
    assert pareto["paretoFrontCandidateIds"]
    assert pareto["analystAgentId"] == hypothesis_review_executor.PARETO_ROLE

    # MetaReview: the meeting's closing actor recommends one candidate.
    meta_review = round_record["metaReview"]
    assert meta_review["reviewerAgentId"] == agents["challenge_cup_search"]
    assert meta_review["recommendationCandidateId"] in _SELECTED_IDS
    assert meta_review["recommendationCandidateId"] in pareto["paretoFrontCandidateIds"]
    assert meta_review["accepted"] is True
    assert meta_review["rationale"]

    # meetingRefs point at the closing meeting's round, digest, and decisions.
    ref_pairs = {(item["kind"], item["id"]) for item in round_record["meetingRefs"]}
    assert ("meeting_round", meeting_round["meetingRoundId"]) in ref_pairs
    assert ("meeting_digest", digest["digestId"]) in ref_pairs
    for decision in approved["decisions"]:
        assert ("decision_record", decision["decisionId"]) in ref_pairs

    # First round lineage points at the question's selected candidates.
    assert round_record["lineage"] == [
        {"kind": "candidate", "id": candidate_id} for candidate_id in _SELECTED_IDS
    ]
    assert round_record["question"] == "SCI-096"

    # Role attribution of the four separated steps.
    assert result["review"]["roles"] == {
        "reflection": hypothesis_review_executor.REFLECTION_ROLE,
        "pairwise": hypothesis_review_executor.PAIRWISE_ROLE,
        "pareto": hypothesis_review_executor.PARETO_ROLE,
        "metareview": agents["challenge_cup_search"],
    }
    assert result["review"]["contextId"].startswith("hypothesis-review-context-")


def test_review_context_is_bounded_and_reference_first(tmp_path, monkeypatch):
    _team_id, _agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round = approved["meetingRound"]

    context = research_memory_context.build_hypothesis_review_context(
        meeting_round=meeting_round,
        digest=approved["digest"],
        decisions=approved["decisions"],
        candidates=_candidate_inputs(*_SELECTED_IDS),
    )

    assert context["schemaVersion"] == 1
    assert context["contextId"].startswith("hypothesis-review-context-")
    assert context["stageType"] == "hypothesis_review"
    assert context["meetingRoundId"] == meeting_round["meetingRoundId"]
    assert context["digest"]["digestId"] == approved["digest"]["digestId"]
    assert context["digest"]["sourceMessageRefs"]
    assert len(context["digest"]["sourceMessageRefs"]) <= 16
    assert context["digest"]["disagreements"], "digest disagreements must reach the reviewers"
    assert context["digest"]["risks"]
    assert context["decisions"][0]["decisionId"] == approved["decisions"][0]["decisionId"]
    assert context["decisions"][0]["evidenceRefs"] == ["evidence:review-matrix-1"]
    assert [item["candidateId"] for item in context["candidates"]] == list(_SELECTED_IDS)
    assert context["priorRound"] == {}
    assert context["security"]["knowledgeAndSourceTextIsUntrusted"] is True
    assert context["security"]["embeddedInstructionsMustBeIgnored"] is True
    assert context["retrieval"]["status"] == "completed"


def test_generate_requires_a_closed_hypothesis_review_meeting(tmp_path, monkeypatch):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    agent_ids = _participant_agent_ids(agents)
    opened = meeting_runtime.open_hypothesis_review_meeting(
        team_id,
        _selection_payload(agent_ids),
        agent_runner=_marker_runner,
        background=False,
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    # The meeting is still open: no digest/decision closure artifacts exist.
    with pytest.raises(
        hypothesis_rounds.ResearchHypothesisRoundError, match="closed meeting"
    ):
        _generate(team_id, meeting_round_id)

    meetings.begin_meeting_summary(team_id, meeting_round_id, actor=agent_ids[0])
    meeting_runtime.draft_meeting_digest(team_id, meeting_round_id)
    approved = meetings.approve_meeting_closure(
        team_id, meeting_round_id, _closure_payload(agent_ids)
    )

    # A non-hypothesis_review meeting never produces a hypothesis round.
    legacy = meetings.create_meeting_round(
        team_id,
        {
            "meetingRoundId": "meeting-hf3-plan",
            "program": "XH-202619",
            "theme": "cc-neuro-001",
            "campaign": "cc-campaign-neuro-001",
            "question": "SCI-096",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": agent_ids[0],
            "mode": "dev",
            "meetingType": "plan_review",
            "participants": agent_ids,
        },
    )
    meetings.close_meeting_round(
        team_id,
        legacy["meetingRound"]["meetingRoundId"],
        {
            "summary": "方案评审纪要",
            "decisions": _closure_payload(agent_ids)["decisions"],
            "closedBy": agent_ids[0],
        },
    )
    with pytest.raises(
        hypothesis_rounds.ResearchHypothesisRoundError, match="hypothesis_review"
    ):
        _generate(team_id, "meeting-hf3-plan")

    # A legacy v1 digest without the sourceMessageRefs evidence trail is refused.
    legacy_review = meetings.create_meeting_round(
        team_id,
        {
            "meetingRoundId": "meeting-hf3-legacy",
            "program": "XH-202619",
            "theme": "cc-neuro-001",
            "campaign": "cc-campaign-neuro-001",
            "question": "SCI-096",
            "branch": "main",
            "workflow": "hypothesis_first",
            "agentId": agent_ids[0],
            "mode": "dev",
            "meetingType": "hypothesis_review",
            "participants": agent_ids,
            "discussionItemRefs": [f"hypothesis_candidate:{cid}" for cid in _SELECTED_IDS],
        },
    )
    meetings.close_meeting_round(
        team_id,
        legacy_review["meetingRound"]["meetingRoundId"],
        {
            "summary": "旧版直接关门纪要",
            "decisions": _closure_payload(agent_ids)["decisions"],
            "closedBy": agent_ids[0],
        },
    )
    with pytest.raises(
        hypothesis_rounds.ResearchHypothesisRoundError, match="sourceMessageRefs"
    ):
        _generate(team_id, "meeting-hf3-legacy")

    # Contract level: stripping meetingRefs from an otherwise complete round
    # fails validate_complete instead of degrading into a write.
    result = _generate(team_id, approved["meetingRound"]["meetingRoundId"])
    stripped = {**result["round"], "meetingRefs": []}
    with pytest.raises(ContractValidationError, match="meeting digest and decision refs"):
        HypothesisRound.from_dict(stripped).validate_complete()


def test_reflection_missing_dimension_fails_closed(tmp_path, monkeypatch):
    team_id, _agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round_id = approved["meetingRound"]["meetingRoundId"]

    def incomplete_reflection(candidate, context):
        return {"scores": {dim: 0.7 for dim in SCORE_DIMENSIONS if dim != "novelty"}}

    with pytest.raises(ContractValidationError, match="missing review dimensions"):
        _generate(
            team_id,
            meeting_round_id,
            reflection_runner=incomplete_reflection,
        )

    assert hypothesis_rounds.list_hypothesis_rounds(team_id)["roundCount"] == 0


def test_pairwise_runner_gap_fails_closed(tmp_path, monkeypatch):
    team_id, _agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round_id = approved["meetingRound"]["meetingRoundId"]

    def silent_pairwise(left, right, context):
        if {left["candidateId"], right["candidateId"]} == {"cand-a", "cand-c"}:
            return None
        return {"outcome": "left_wins", "justification": "五维评分多数维度占优"}

    with pytest.raises(ContractValidationError, match="pairwise runner must return a mapping"):
        _generate(team_id, meeting_round_id, pairwise_runner=silent_pairwise)

    def invalid_outcome(left, right, context):
        return {"outcome": "decisive_victory", "justification": "非法结果"}

    with pytest.raises(ContractValidationError, match="outcome"):
        _generate(team_id, meeting_round_id, pairwise_runner=invalid_outcome)

    assert hypothesis_rounds.list_hypothesis_rounds(team_id)["roundCount"] == 0


def test_pareto_must_classify_every_candidate(tmp_path, monkeypatch):
    team_id, _agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round_id = approved["meetingRound"]["meetingRoundId"]

    def incomplete_pareto(scores_by_candidate, context):
        ordered = list(scores_by_candidate)
        return {
            "paretoFrontCandidateIds": ordered[:1],
            "dominatedCandidateIds": ordered[2:],
            "notes": "漏掉一个候选的分类",
        }

    with pytest.raises(ContractValidationError, match="classify every candidate"):
        _generate(team_id, meeting_round_id, pareto_runner=incomplete_pareto)

    assert hypothesis_rounds.list_hypothesis_rounds(team_id)["roundCount"] == 0


def test_metareview_requires_a_recommendation(tmp_path, monkeypatch):
    team_id, _agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round_id = approved["meetingRound"]["meetingRoundId"]

    def no_recommendation(context, candidates, pairwise, pareto):
        return {
            "recommendationCandidateId": "",
            "rationale": "证据不足，无法给出推荐",
            "accepted": False,
        }

    with pytest.raises(ContractValidationError, match="recommendation"):
        _generate(team_id, meeting_round_id, metareview_runner=no_recommendation)

    assert hypothesis_rounds.list_hypothesis_rounds(team_id)["roundCount"] == 0

    # A withheld acceptance with a valid recommendation still closes the round;
    # the convergence decision belongs to the orchestration gate.
    def withheld(context, candidates, pairwise, pareto):
        return {
            "recommendationCandidateId": "cand-a",
            "rationale": "cand-a 领先但证据缺口仍在，暂不收敛",
            "riskNotes": "数据集偏差尚未评估",
            "accepted": False,
        }

    result = _generate(team_id, meeting_round_id, metareview_runner=withheld)
    assert result["round"]["status"] == "closed"
    assert result["round"]["metaReview"]["accepted"] is False
    assert result["round"]["metaReview"]["recommendationCandidateId"] == "cand-a"


def test_generation_is_idempotent_for_the_same_meeting(tmp_path, monkeypatch):
    team_id, _agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round_id = approved["meetingRound"]["meetingRoundId"]

    first = _generate(team_id, meeting_round_id)
    repeated = _generate(team_id, meeting_round_id)

    assert first["status"] == "created"
    assert repeated["status"] == "reused"
    assert repeated["round"]["roundId"] == first["round"]["roundId"]
    assert repeated["round"]["metaReview"] == first["round"]["metaReview"]
    assert hypothesis_rounds.list_hypothesis_rounds(team_id)["roundCount"] == 1


def test_pairwise_order_is_randomized_seeded_and_recorded(tmp_path, monkeypatch):
    candidate_ids = list(_SELECTED_IDS)
    orderings = {
        seed: hypothesis_review_executor.deterministic_pairwise_order(candidate_ids, seed)
        for seed in ("seed-alpha", "seed-beta", "seed-gamma", "seed-delta")
    }
    all_pairs = {
        frozenset(pair)
        for pair in (("cand-a", "cand-b"), ("cand-a", "cand-c"), ("cand-b", "cand-c"))
    }
    for seed, ordering in orderings.items():
        assert {frozenset(pair) for pair in ordering} == all_pairs
        # The recorded order replays deterministically from the seed.
        assert hypothesis_review_executor.deterministic_pairwise_order(candidate_ids, seed) == ordering
    # The scheme actually randomizes: the fixed seed set produces both orders.
    assert len({tuple(ordering) for ordering in orderings.values()}) > 1

    team_id, _agents, _opened, approved = _closed_meeting(tmp_path, monkeypatch)
    result = _generate(
        team_id,
        approved["meetingRound"]["meetingRoundId"],
        payload={"positionSeed": "seed-alpha"},
    )
    persisted = [
        (item["leftCandidateId"], item["rightCandidateId"])
        for item in result["round"]["pairwiseComparisons"]
    ]
    assert persisted == orderings["seed-alpha"]


def test_lineage_chain_walks_from_any_round_to_question_candidates(tmp_path, monkeypatch):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    _opened_1, approved_1 = _open_and_close_meeting(team_id, agents)
    first = _generate(team_id, approved_1["meetingRound"]["meetingRoundId"])
    first_round = first["round"]

    # Second discussion round brings one new candidate alongside the carry-overs.
    _opened_2, approved_2 = _open_and_close_meeting(
        team_id,
        agents,
        selectionId="sel-hf3-2",
        meetingRoundId="meeting-hf3-2",
        selectedCandidateIds=[*_SELECTED_IDS, "cand-d"],
    )
    second = _generate(
        team_id,
        approved_2["meetingRound"]["meetingRoundId"],
        candidate_ids=(*_SELECTED_IDS, "cand-d"),
    )
    second_round = second["round"]

    assert second_round["roundId"] != first_round["roundId"]
    assert {"kind": "round", "id": first_round["roundId"]} in second_round["lineage"]
    assert {"kind": "candidate", "id": "cand-d"} in second_round["lineage"]
    assert not [
        item
        for item in second_round["lineage"]
        if item["kind"] == "candidate" and item["id"] in _SELECTED_IDS
    ], "carry-over candidates trace through the round ref, not duplicate candidate refs"

    chain, terminal = _walk_lineage_to_candidates(team_id, second_round)
    assert [item["roundId"] for item in chain] == [
        second_round["roundId"],
        first_round["roundId"],
    ]
    assert terminal == list(_SELECTED_IDS), "the chain ends at the question candidates"

    chain_from_first, terminal_from_first = _walk_lineage_to_candidates(team_id, first_round)
    assert [item["roundId"] for item in chain_from_first] == [first_round["roundId"]]
    assert terminal_from_first == list(_SELECTED_IDS)


def test_previous_round_ref_must_resolve_to_a_closed_round(tmp_path, monkeypatch):
    team_id, agents = _team_with_room(tmp_path, monkeypatch)
    _opened_1, approved_1 = _open_and_close_meeting(team_id, agents)
    first = _generate(team_id, approved_1["meetingRound"]["meetingRoundId"])
    _opened_2, approved_2 = _open_and_close_meeting(
        team_id, agents, selectionId="sel-hf3-2", meetingRoundId="meeting-hf3-2"
    )
    meeting_2_id = approved_2["meetingRound"]["meetingRoundId"]

    with pytest.raises(
        hypothesis_rounds.ResearchHypothesisRoundError, match="does not resolve"
    ):
        _generate(
            team_id,
            meeting_2_id,
            payload={"previousRoundId": "hround-bogus"},
        )

    # An open (not yet closed) round cannot anchor a lineage ref.
    scope = {
        "program": "XH-202619",
        "theme": "cc-neuro-001",
        "campaign": "cc-campaign-neuro-001",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": next(iter(agents.values())),
        "mode": "dev",
    }
    open_round = hypothesis_rounds.create_hypothesis_round(
        team_id,
        {
            **scope,
            "roundId": "hround-hf3-open",
            "candidates": [
                {
                    "candidateId": "cand-x",
                    "claim": "候选 cand-x 的机制陈述",
                    "differenceFromAlternatives": "cand-x 的差异点",
                    "lineageRefs": [],
                    "scores": {dim: 0.6 for dim in SCORE_DIMENSIONS},
                    "reviewedBy": "agent-reviewer",
                    "status": "proposed",
                },
                {
                    "candidateId": "cand-y",
                    "claim": "候选 cand-y 的机制陈述",
                    "differenceFromAlternatives": "cand-y 的差异点",
                    "lineageRefs": [],
                    "scores": {dim: 0.6 for dim in SCORE_DIMENSIONS},
                    "reviewedBy": "agent-reviewer",
                    "status": "proposed",
                },
            ],
            "lineage": [{"kind": "candidate", "id": "cand-a"}],
        },
    )["round"]
    with pytest.raises(
        hypothesis_rounds.ResearchHypothesisRoundError, match="does not resolve"
    ):
        _generate(
            team_id,
            meeting_2_id,
            payload={"previousRoundId": open_round["roundId"]},
        )

    # The default path still resolves the latest closed round as the anchor.
    second = _generate(team_id, meeting_2_id)
    assert {"kind": "round", "id": first["round"]["roundId"]} in second["round"]["lineage"]


def _direct_review_context() -> dict:
    return {
        "contextId": "ctx-hf-formal-fence",
        "candidates": _candidate_inputs("cand-a", "cand-b"),
    }


def _complete_review_runners():
    scores = {dimension: 0.7 for dimension in SCORE_DIMENSIONS}

    def reflection(candidate, context):
        return {
            "scores": dict(scores),
            "claim": candidate["claim"],
            "differenceFromAlternatives": candidate["differenceFromAlternatives"],
            "rationale": "独立评分依据",
        }

    def pairwise(left, right, context):
        return {"outcome": "left_wins", "justification": "左侧候选领先"}

    def pareto(scores_by_candidate, context):
        ids = list(scores_by_candidate)
        return {
            "paretoFrontCandidateIds": ids[:1],
            "dominatedCandidateIds": ids[1:],
            "notes": "按五个决策维度分类",
        }

    def metareview(context, candidates, pairwise, pareto):
        return {
            "recommendationCandidateId": "cand-a",
            "rationale": "位于 Pareto 前沿",
            "riskNotes": "",
            "accepted": True,
        }

    def revision(context, parent_candidate, candidates, meta_review):
        return {
            "revisedCandidate": {
                **parent_candidate,
                "claim": parent_candidate["claim"] + "（根据评审收窄边界）",
            },
            "changes": ["收窄了适用边界。"],
            "unresolvedIssues": ["外部有效性仍待验证。"],
        }

    return {
        "reflection_runner": reflection,
        "pairwise_runner": pairwise,
        "pareto_runner": pareto,
        "metareview_runner": metareview,
        "revision_runner": revision,
    }


def _coherence_payload(candidate_id: str, *, failed_check: str = "") -> dict:
    return {
        "candidateId": candidate_id,
        "reviewer": "llm:reviewer",
        "checks": [
            {
                "checkId": check_id,
                "passed": check_id != failed_check,
                "rationale": f"{check_id} 已逐项核对",
                "claimRefs": [f"claim:{candidate_id}:core"],
                "evidenceRefs": [f"evidence:{candidate_id}:support"],
            }
            for check_id in CORE_HYPOTHESIS_COHERENCE_CHECK_IDS
        ],
    }


def test_stage_one_coherence_failure_stops_before_pairwise_pareto_and_metareview():
    calls = {"pairwise": 0, "pareto": 0, "metareview": 0}
    runners = _complete_review_runners()

    def reflection(candidate, context):
        payload = runners["reflection_runner"](candidate, context)
        payload["coreHypothesisCoherence"] = _coherence_payload(
            candidate["candidateId"],
            failed_check=(
                "prediction_entails_mechanism"
                if candidate["candidateId"] == "cand-b"
                else ""
            ),
        )
        return payload

    def counted(name, runner):
        def wrapped(*args):
            calls[name] += 1
            return runner(*args)

        return wrapped

    with pytest.raises(ContractValidationError, match="coherence_failure"):
        hypothesis_review_executor.execute_hypothesis_review(
            {
                **_direct_review_context(),
                "requireCoreHypothesisCoherence": True,
            },
            reflection_runner=reflection,
            pairwise_runner=counted("pairwise", runners["pairwise_runner"]),
            pareto_runner=counted("pareto", runners["pareto_runner"]),
            metareview_runner=counted("metareview", runners["metareview_runner"]),
            reviewer_assignments={"metareview": "coordinator"},
        )

    assert calls == {"pairwise": 0, "pareto": 0, "metareview": 0}


def test_stage_one_coherence_passes_with_same_reflection_calls_and_is_returned():
    runners = _complete_review_runners()

    def reflection(candidate, context):
        payload = runners["reflection_runner"](candidate, context)
        payload["coreHypothesisCoherence"] = _coherence_payload(
            candidate["candidateId"]
        )
        return payload

    result = hypothesis_review_executor.execute_hypothesis_review(
        {
            **_direct_review_context(),
            "requireCoreHypothesisCoherence": True,
        },
        reflection_runner=reflection,
        pairwise_runner=runners["pairwise_runner"],
        pareto_runner=runners["pareto_runner"],
        metareview_runner=runners["metareview_runner"],
        reviewer_assignments={"metareview": "coordinator"},
    )

    coherence = result["coreHypothesisCoherence"]
    assert [item["candidateId"] for item in coherence] == ["cand-a", "cand-b"]
    assert all(item["passed"] is True for item in coherence)
    assert all(len(item["artifactHash"]) == 64 for item in coherence)


def test_non_stage_one_review_keeps_existing_behavior_without_coherence_rows():
    result = hypothesis_review_executor.execute_hypothesis_review(
        _direct_review_context(),
        **_complete_review_runners(),
        reviewer_assignments={"metareview": "coordinator"},
    )

    assert "coreHypothesisCoherence" not in result


def _provider_bound_receipt(
    receipt_id: str,
    *,
    question_stage: str = "review",
    outcome_kinds: tuple[str, ...] = ("review",),
    status: ModelInvocationStatus = ModelInvocationStatus.SUCCEEDED,
) -> dict:
    retry_count = 1 if status is ModelInvocationStatus.RETRIED else 0
    return ModelInvocationReceipt.from_invocation(
        receipt_id=receipt_id,
        run_id="workflow-run-formal",
        node_run_id=f"review-node-{receipt_id}",
        scope={
            "questionId": "SCI-096",
            "workflowRunId": "workflow-run-formal",
            "questionStage": question_stage,
        },
        provider="opencode",
        model="deepseek-v4-flash",
        requested_model="deepseek-v4-flash",
        status=status,
        request_content={"receiptId": receipt_id},
        response_content={"ok": True},
        started_at_ms=10,
        finished_at_ms=20,
        retry_count=retry_count,
        metadata={
            "questionStage": question_stage,
            "outcomeKinds": list(outcome_kinds),
        },
        evidence_locator={"kind": "hypothesis_review_step"},
    ).to_dict()


def _provider_bound_review_runners(*, receipt_factory=None, runners=None):
    runners = runners or _complete_review_runners()
    call_index = 0
    # Reflection calls run concurrently now; receipt numbering must stay unique.
    call_index_lock = threading.Lock()

    def wrap(name, runner):
        def wrapped(*args):
            nonlocal call_index
            payload = runner(*args)
            with call_index_lock:
                call_index += 1
                index = call_index
            receipt = (
                receipt_factory(index, name)
                if receipt_factory is not None
                else _provider_bound_receipt(
                    f"formal-review-{index}",
                    outcome_kinds=(
                        ("review", "revision")
                        if name == "revision"
                        else ("review",)
                    ),
                )
            )
            return hypothesis_review_executor.ProviderBoundReviewResult(
                payload=payload,
                model_invocation_receipt=receipt,
            )

        return wrapped

    return {
        key: wrap(key.removesuffix("_runner"), runner)
        for key, runner in runners.items()
    }


def test_review_execution_mode_rejects_unknown_values():
    with pytest.raises(ContractValidationError, match="execution mode"):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            execution_mode="canary",
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_formal_review_requires_all_real_runners_before_any_step():
    with pytest.raises(ContractValidationError, match="FORMAL.*runner"):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            execution_mode="formal",
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_formal_review_stays_blocked_without_provider_bound_receipts():
    runners = _complete_review_runners()

    with pytest.raises(ContractValidationError, match="FORMAL.*receipt"):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            execution_mode="formal",
            **runners,
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_formal_review_accepts_one_unique_provider_receipt_per_model_call():
    result = hypothesis_review_executor.execute_hypothesis_review(
        _direct_review_context(),
        execution_mode="formal",
        **_provider_bound_review_runners(),
        reviewer_assignments={"metareview": "coordinator"},
    )

    receipts = result["modelInvocationReceipts"]
    assert len(receipts) == 6  # 2 reflection + pairwise + Pareto + MetaReview + revision
    assert len({item["receiptId"] for item in receipts}) == 6
    assert {item["metadata"]["questionStage"] for item in receipts} == {"review"}
    assert all("review" in item["metadata"]["outcomeKinds"] for item in receipts)
    assert receipts[-1]["metadata"]["outcomeKinds"] == ["review", "revision"]
    assert result["revisionEnvelope"]["phase"] == "review_revision"
    assert result["revisionEnvelope"]["revision"]["output"]["candidates"][0][
        "claim"
    ].endswith("（根据评审收窄边界）")


def test_formal_review_rejects_revision_that_copies_the_r1_claim():
    runners = _complete_review_runners()

    def copied_revision(context, parent_candidate, candidates, meta_review):
        return {
            "revisedCandidate": dict(parent_candidate),
            "changes": ["Claimed a revision without changing the hypothesis."],
            "unresolvedIssues": ["External validity remains open."],
        }

    runners["revision_runner"] = copied_revision
    with pytest.raises(ContractValidationError, match="genuinely new hypothesis text"):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            execution_mode="formal",
            **_provider_bound_review_runners(runners=runners),
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_formal_artifact_scope_reads_source_collection_run_from_ledger_snapshot(
    monkeypatch,
):
    from core.web.services.team_workflow.research_runtime import formal_write_runtime

    run = type(
        "Run",
        (),
        {
            "input_snapshot_json": '{"sourceCollectionRunId":"source-run-formal"}'
        },
    )()
    store = type("Store", (), {"get_run": lambda self, run_id: run})()
    monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: store)

    assert (
        hypothesis_review_executor._source_collection_run_id_for_formal_workflow(
            "workflow-run-formal"
        )
        == "source-run-formal"
    )


def test_formal_stage_one_coherence_artifact_is_receipt_bound_and_readable(
    tmp_path, monkeypatch
):
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
        workflow_artifact_store,
    )

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        hypothesis_review_executor,
        "_source_collection_run_id_for_formal_workflow",
        lambda workflow_run_id: (
            "source-run-formal"
            if workflow_run_id == "workflow-run-formal"
            else ""
        ),
    )
    runners = _complete_review_runners()
    base_reflection = runners["reflection_runner"]

    def reflection(candidate, context):
        payload = base_reflection(candidate, context)
        payload["coreHypothesisCoherence"] = _coherence_payload(
            candidate["candidateId"]
        )
        return payload

    runners["reflection_runner"] = reflection
    context = {
        **_direct_review_context(),
        "teamId": "team-stage-one",
        "questionId": "SCI-091",
        "_modelInvocationReceiptAuthority": {
            "workflowRunId": "workflow-run-formal",
        },
    }
    context["candidates"] = [
        {**candidate, "candidateAuthority": "formal_grounded_candidate"}
        for candidate in context["candidates"]
    ]

    result = hypothesis_review_executor.execute_hypothesis_review(
        context,
        execution_mode="formal",
        **_provider_bound_review_runners(runners=runners),
        reviewer_assignments={"metareview": "coordinator"},
    )

    artifact_ref = result["coreHypothesisCoherenceArtifactRef"]
    parsed_ref = artifact_readback_registry.parse_canonical_ref(artifact_ref)
    assert parsed_ref is not None
    assert parsed_ref["authorityRunId"] == "source-run-formal"
    assert artifact_readback_registry.read_domain_artifact(artifact_ref) is not None
    coherence = result["coreHypothesisCoherence"]
    assert all(item["receiptRef"] for item in coherence)
    receipt_ids = {item["receiptId"] for item in result["modelInvocationReceipts"]}
    assert {item["receiptRef"] for item in coherence}.issubset(receipt_ids)


@pytest.mark.parametrize(
    ("receipt_factory", "message"),
    [
        (
            lambda _index, _name: _provider_bound_receipt("duplicate-review-receipt"),
            "duplicate",
        ),
        (
            lambda index, _name: _provider_bound_receipt(
                f"wrong-stage-{index}", question_stage="generation"
            ),
            "questionStage",
        ),
        (
            lambda index, _name: _provider_bound_receipt(
                f"wrong-outcome-{index}", outcome_kinds=("candidate",)
            ),
            "outcomeKinds",
        ),
        (
            lambda _index, _name: None,
            "receipt",
        ),
        (
            lambda index, _name: _provider_bound_receipt(
                f"partial-{index}", status=ModelInvocationStatus.PARTIAL
            ),
            "status",
        ),
    ],
)
def test_formal_review_rejects_unverifiable_provider_receipts(
    receipt_factory, message
):
    with pytest.raises(ContractValidationError, match=message):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            execution_mode="formal",
            **_provider_bound_review_runners(receipt_factory=receipt_factory),
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_formal_review_accepts_retried_provider_receipt():
    result = hypothesis_review_executor.execute_hypothesis_review(
        _direct_review_context(),
        execution_mode="formal",
        **_provider_bound_review_runners(
            receipt_factory=lambda index, name: _provider_bound_receipt(
                f"retried-{index}",
                outcome_kinds=(
                    ("review", "revision")
                    if name == "revision"
                    else ("review",)
                ),
                status=(
                    ModelInvocationStatus.RETRIED
                    if index == 1
                    else ModelInvocationStatus.SUCCEEDED
                ),
            )
        ),
        reviewer_assignments={"metareview": "coordinator"},
    )

    assert result["modelInvocationReceipts"][0]["status"] == "retried"


# ---------------------------------------------------------------------------
# Round generation wiring: the meeting's server-owned scope mode drives the
# executor fence (formal meeting -> FORMAL, everything else fails closed to DEV)
# ---------------------------------------------------------------------------


def test_formal_meeting_generation_rejects_dev_fixture_review(tmp_path, monkeypatch):
    """A formal meeting must never close a round from the DEV fixture path."""

    team_id, _agents, opened, _approved = _closed_meeting(
        tmp_path, monkeypatch, mode="formal"
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    assert opened["meetingRound"]["mode"] == "formal"

    with pytest.raises(ContractValidationError, match="FORMAL.*runner"):
        _generate(team_id, meeting_round_id)

    assert hypothesis_rounds.list_hypothesis_rounds(team_id)["roundCount"] == 0


def test_formal_meeting_generation_rejects_fixture_runner_outputs_without_receipts(
    tmp_path, monkeypatch
):
    """Fixture-shaped plain-mapping runner outputs are refused in FORMAL."""

    team_id, _agents, opened, _approved = _closed_meeting(
        tmp_path, monkeypatch, mode="formal"
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    with pytest.raises(ContractValidationError, match="FORMAL.*receipt"):
        _generate(team_id, meeting_round_id, **_complete_review_runners())

    assert hypothesis_rounds.list_hypothesis_rounds(team_id)["roundCount"] == 0


def test_formal_meeting_generation_accepts_provider_bound_runners(tmp_path, monkeypatch):
    team_id, _agents, opened, _approved = _closed_meeting(
        tmp_path, monkeypatch, mode="formal"
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = _generate(
        team_id, meeting_round_id, **_provider_bound_review_runners()
    )

    assert result["closed"] is True
    assert result["review"]["executionMode"] == "formal"
    parsed = HypothesisRound.from_dict(result["round"])
    parsed.validate_complete()


def test_dev_meeting_generation_keeps_fixture_review_and_marks_mode(
    tmp_path, monkeypatch
):
    team_id, _agents, opened, _approved = _closed_meeting(tmp_path, monkeypatch)
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]

    result = _generate(team_id, meeting_round_id)

    assert result["closed"] is True
    assert result["review"]["executionMode"] == "dev"


def test_round_generation_fails_closed_to_dev_without_mode_marker(
    tmp_path, monkeypatch
):
    """A meeting record without the formal marker must never escalate."""
    team_id, _agents, opened, _approved = _closed_meeting(
        tmp_path, monkeypatch, mode="formal"
    )
    meeting_round_id = opened["meetingRound"]["meetingRoundId"]
    real_get_meeting_round = meetings.get_meeting_round

    def strip_mode(team_id_value, round_id_value):
        detail = real_get_meeting_round(team_id_value, round_id_value)
        meeting = dict(detail["meetingRound"])
        meeting.pop("mode", None)
        return {**detail, "meetingRound": meeting}

    monkeypatch.setattr(meetings, "get_meeting_round", strip_mode)

    result = _generate(team_id, meeting_round_id)

    assert result["review"]["executionMode"] == "dev"


def test_review_runner_scores_are_bounded_before_review_artifact_is_built():
    runners = _complete_review_runners()

    def out_of_range_reflection(candidate, context):
        result = runners["reflection_runner"](candidate, context)
        result["scores"]["novelty"] = 1.1
        return result

    with pytest.raises(ContractValidationError, match="between 0 and 1"):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            reflection_runner=out_of_range_reflection,
            pairwise_runner=runners["pairwise_runner"],
            pareto_runner=runners["pareto_runner"],
            metareview_runner=runners["metareview_runner"],
            reviewer_assignments={"metareview": "coordinator"},
        )


# ---------------------------------------------------------------------------
# Bounded parallel runner execution (reflection + pairwise)
# ---------------------------------------------------------------------------


class _InFlightProbe:
    """Thread-safe recorder of concurrent in-flight runner calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight = 0
        self.max_inflight = 0

    def enter(self) -> None:
        with self._lock:
            self._inflight += 1
            if self._inflight > self.max_inflight:
                self.max_inflight = self._inflight

    def exit(self) -> None:
        with self._lock:
            self._inflight -= 1

    def assert_min_inflight(self, required: int, *, timeout: float = 5.0) -> None:
        """Block until ``required`` calls overlap; a serial executor times out."""

        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                reached = self.max_inflight >= required
            if reached:
                return
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"expected at least {required} concurrent review calls, "
                    f"observed max in-flight {self.max_inflight}"
                )
            time.sleep(0.005)


def _parallel_reflection_context(*candidate_ids: str) -> dict:
    return {"contextId": "ctx-parallel", "candidates": _candidate_inputs(*candidate_ids)}


def _marker_reflection_payload(candidate: dict, marker: str | None = None) -> dict:
    candidate_id = str(candidate["candidateId"])
    return {
        "claim": str(candidate["claim"]),
        "rationale": f"rationale:{marker or candidate_id}",
        "differenceFromAlternatives": str(candidate["differenceFromAlternatives"]),
        "scores": {dimension: 0.6 for dimension in SCORE_DIMENSIONS},
    }


def test_reflection_runner_calls_overlap_and_output_follows_input_order():
    ids = [f"cand-{index}" for index in range(4)]
    probe = _InFlightProbe()

    def reflection(candidate, context):
        probe.enter()
        try:
            # The first callers wait for a second concurrent call: a serial
            # executor can never satisfy this and fails by timeout.
            probe.assert_min_inflight(2)
            return _marker_reflection_payload(candidate)
        finally:
            probe.exit()

    result = hypothesis_review_executor.execute_hypothesis_review(
        _parallel_reflection_context(*ids),
        round_id="round-parallel-reflection",
        reflection_runner=reflection,
        reviewer_assignments={"metareview": "coordinator"},
    )

    assert [item["candidateId"] for item in result["candidates"]] == ids
    for item in result["candidates"]:
        assert item["rationale"] == f"rationale:{item['candidateId']}"
    assert probe.max_inflight >= 2


def test_pairwise_runner_calls_overlap_and_comparisons_follow_input_order():
    ids = ["cand-a", "cand-b", "cand-c", "cand-d"]
    expected_pairs = hypothesis_review_executor.deterministic_pairwise_order(ids, "par-seed")
    assert len(expected_pairs) == 6
    probe = _InFlightProbe()

    def pairwise(left, right, context):
        probe.enter()
        try:
            probe.assert_min_inflight(2)
            return {
                "outcome": "left_wins",
                "justification": (
                    f"justify:{left['candidateId']}>{right['candidateId']}"
                ),
            }
        finally:
            probe.exit()

    result = hypothesis_review_executor.execute_hypothesis_review(
        _parallel_reflection_context(*ids),
        round_id="round-parallel-pairwise",
        pairwise_runner=pairwise,
        reviewer_assignments={"metareview": "coordinator"},
        position_seed="par-seed",
    )

    comparisons = result["pairwiseComparisons"]
    assert [
        (item["leftCandidateId"], item["rightCandidateId"]) for item in comparisons
    ] == expected_pairs
    for item in comparisons:
        assert item["justification"] == (
            f"justify:{item['leftCandidateId']}>{item['rightCandidateId']}"
        )
    assert probe.max_inflight >= 2


def test_parallel_results_are_assembled_by_input_order_not_completion_order():
    ids = [f"cand-{index}" for index in range(5)]
    delays = {index: 0.02 * (len(ids) - index) for index in range(len(ids))}

    def reflection(candidate, context):
        index = int(str(candidate["candidateId"]).rsplit("-", 1)[1])
        time.sleep(delays[index])  # the last input finishes first
        return _marker_reflection_payload(candidate)

    result = hypothesis_review_executor.execute_hypothesis_review(
        _parallel_reflection_context(*ids),
        round_id="round-reorder",
        reflection_runner=reflection,
        reviewer_assignments={"metareview": "coordinator"},
        max_concurrent_calls=len(ids),
    )

    assert [item["candidateId"] for item in result["candidates"]] == ids
    for item in result["candidates"]:
        assert item["rationale"] == f"rationale:{item['candidateId']}"
        assert set(item["scores"]) == set(SCORE_DIMENSIONS)


def test_first_runner_failure_in_input_order_wins_without_partial_output():
    ids = ["cand-a", "cand-b", "cand-c"]

    def reflection(candidate, context):
        candidate_id = str(candidate["candidateId"])
        if candidate_id == "cand-a":
            # Fails later in wall-clock than cand-b but sits earlier in input.
            time.sleep(0.15)
            raise ContractValidationError("late failure cand-a")
        if candidate_id == "cand-b":
            raise ContractValidationError("early failure cand-b")
        return _marker_reflection_payload(candidate)

    with pytest.raises(ContractValidationError, match="late failure cand-a"):
        hypothesis_review_executor.execute_hypothesis_review(
            _parallel_reflection_context(*ids),
            round_id="round-first-failure",
            reflection_runner=reflection,
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_max_concurrent_calls_one_keeps_serial_invocation_semantics():
    ids = ["cand-a", "cand-b", "cand-c"]
    expected_pairs = hypothesis_review_executor.deterministic_pairwise_order(ids, "serial-seed")
    call_log: list[tuple[str, str]] = []
    log_lock = threading.Lock()
    probe = _InFlightProbe()

    def track(step: str, key: str):
        with log_lock:
            call_log.append((step, key))

    def reflection(candidate, context):
        candidate_id = str(candidate["candidateId"])
        probe.enter()
        try:
            track("reflection", candidate_id)
            time.sleep(0.01)
            return _marker_reflection_payload(candidate)
        finally:
            probe.exit()

    def pairwise(left, right, context):
        pair_key = f"{left['candidateId']}>{right['candidateId']}"
        probe.enter()
        try:
            track("pairwise", pair_key)
            return {"outcome": "left_wins", "justification": f"justify:{pair_key}"}
        finally:
            probe.exit()

    result = hypothesis_review_executor.execute_hypothesis_review(
        _parallel_reflection_context(*ids),
        round_id="round-serial",
        reflection_runner=reflection,
        pairwise_runner=pairwise,
        reviewer_assignments={"metareview": "coordinator"},
        position_seed="serial-seed",
        max_concurrent_calls=1,
    )

    assert [item["candidateId"] for item in result["candidates"]] == ids
    assert [
        (item["leftCandidateId"], item["rightCandidateId"])
        for item in result["pairwiseComparisons"]
    ] == expected_pairs
    assert call_log == [
        *[("reflection", candidate_id) for candidate_id in ids],
        *[
            ("pairwise", f"{left}>{right}")
            for left, right in expected_pairs
        ],
    ]
    assert probe.max_inflight <= 1


def test_bounded_pool_never_exceeds_the_injected_concurrency():
    ids = [f"cand-{index}" for index in range(8)]
    probe = _InFlightProbe()

    def reflection(candidate, context):
        probe.enter()
        try:
            time.sleep(0.02)
            return _marker_reflection_payload(candidate)
        finally:
            probe.exit()

    result = hypothesis_review_executor.execute_hypothesis_review(
        _parallel_reflection_context(*ids),
        round_id="round-bound",
        reflection_runner=reflection,
        reviewer_assignments={"metareview": "coordinator"},
        max_concurrent_calls=2,
    )

    assert [item["candidateId"] for item in result["candidates"]] == ids
    assert probe.max_inflight <= 2


def test_formal_parallel_review_collects_unique_receipts_in_input_order():
    ids = ["cand-a", "cand-b", "cand-c"]
    base_runners = _complete_review_runners()
    markers: dict[str, list[str]] = {
        "reflection": [f"formal-reflection:{candidate_id}" for candidate_id in ids],
        "pairwise": [
            f"formal-pairwise:{left}>{right}"
            for left, right in hypothesis_review_executor.deterministic_pairwise_order(
                ids, "formal-par"
            )
        ],
        "pareto": ["formal-pareto:" + "|".join(sorted(ids))],
        "metareview": ["formal-metareview:meta"],
        "revision": ["formal-revision:cand-a"],
    }

    def tagged(name, runner):
        reflection_delays = {"cand-a": 0.09, "cand-b": 0.06, "cand-c": 0.03}

        def wrapped(*args):
            payload = runner(*args)
            if name == "reflection":
                marker = f"formal-reflection:{args[0]['candidateId']}"
                time.sleep(reflection_delays[str(args[0]["candidateId"])])
            elif name == "pairwise":
                marker = f"formal-pairwise:{args[0]['candidateId']}>{args[1]['candidateId']}"
            elif name in {"pareto", "metareview"}:
                marker = (
                    "formal-pareto:" + "|".join(sorted(args[0]))
                    if name == "pareto"
                    else "formal-metareview:meta"
                )
            else:
                marker = f"formal-revision:{args[1]['candidateId']}"
            receipt = _provider_bound_receipt(
                marker,
                outcome_kinds=(
                    ("review", "revision")
                    if name == "revision"
                    else ("review",)
                ),
            )
            return hypothesis_review_executor.ProviderBoundReviewResult(
                payload=payload,
                model_invocation_receipt=receipt,
            )

        return wrapped

    result = hypothesis_review_executor.execute_hypothesis_review(
        _parallel_reflection_context(*ids),
        round_id="round-formal-parallel",
        execution_mode="formal",
        reflection_runner=tagged("reflection", base_runners["reflection_runner"]),
        pairwise_runner=tagged("pairwise", base_runners["pairwise_runner"]),
        pareto_runner=tagged("pareto", base_runners["pareto_runner"]),
        metareview_runner=tagged("metareview", base_runners["metareview_runner"]),
        revision_runner=tagged("revision", base_runners["revision_runner"]),
        reviewer_assignments={"metareview": "coordinator"},
        position_seed="formal-par",
    )

    receipts = result["modelInvocationReceipts"]
    receipt_ids = [item["receiptId"] for item in receipts]
    expected_ids = [
        *markers["reflection"],
        *markers["pairwise"],
        *markers["pareto"],
        *markers["metareview"],
        *markers["revision"],
    ]
    # Receipts are recorded in input order (candidates then pairs), not the
    # deliberately inverted completion order of the tagged delays.
    assert receipt_ids == expected_ids
    assert len(set(receipt_ids)) == len(receipt_ids) == 3 + 3 + 1 + 1 + 1
    assert all(item["metadata"]["questionStage"] == "review" for item in receipts)


def _never_called_runners():
    def _refuse(step):
        def _runner(*_args):
            raise AssertionError(f"{step} runner must not be called before budget fence")
        return _runner

    return {
        "reflection_runner": _refuse("reflection"),
        "pairwise_runner": _refuse("pairwise"),
        "pareto_runner": _refuse("pareto"),
        "metareview_runner": _refuse("metareview"),
        "revision_runner": _refuse("revision"),
    }


def test_formal_review_fails_fast_before_any_call_when_finalists_exceed_budget():
    ids = [f"cand-{index}" for index in range(4)]

    with pytest.raises(ContractValidationError, match=r"n \+ n\(n-1\)/2 \+ 2") as excinfo:
        hypothesis_review_executor.execute_hypothesis_review(
            _parallel_reflection_context(*ids),
            execution_mode="formal",
            **_never_called_runners(),
            reviewer_assignments={"metareview": "coordinator"},
        )

    message = str(excinfo.value)
    assert "4 candidates would require 12 review calls" in message
    assert "at most 3 finalists" in message


def test_formal_review_records_exact_eight_call_budget_for_three_finalists():
    ids = ("cand-a", "cand-b", "cand-c")
    result = hypothesis_review_executor.execute_hypothesis_review(
        _parallel_reflection_context(*ids),
        execution_mode="formal",
        **_provider_bound_review_runners(),
        reviewer_assignments={"metareview": "coordinator"},
    )

    budget = result["reviewCallBudget"]
    assert budget["formula"] == "n + n(n-1)/2 + 2"
    assert budget["finalistCount"] == 3
    assert budget["individualReviewCalls"] == 3
    assert budget["pairwiseComparisonCalls"] == 3
    assert budget["closingReviewCalls"] == 2
    assert budget["totalReviewCalls"] == 8
    assert budget["actual"]["reviewStepCalls"] == 8
    assert budget["actual"]["matchesFormula"] is True
    assert budget["actual"]["withinBudget"] is True
    assert budget["revisionRunnerCalls"] == 1
    # The recorded receipts prove the exact budget: 3 reflection + 3 pairwise
    # + Pareto + MetaReview = 8 review calls, plus the out-of-formula revision.
    assert len(result["modelInvocationReceipts"]) == 9


def test_dev_review_records_budget_and_warns_without_hard_finalist_cap(caplog):
    ids = [f"cand-{index}" for index in range(4)]

    with caplog.at_level(
        "WARNING",
        logger="core.web.services.team_workflow.hypothesis_review_executor",
    ):
        result = hypothesis_review_executor.execute_hypothesis_review(
            _parallel_reflection_context(*ids),
            reviewer_assignments={"metareview": "coordinator"},
        )

    budget = result["reviewCallBudget"]
    assert budget["totalReviewCalls"] == 12
    assert budget["actual"]["reviewStepCalls"] == 12
    assert budget["actual"]["matchesFormula"] is True
    # DEV fixtures spend zero model calls; only the structural step count is
    # reconciled against the formula.
    assert "revisionRunnerCalls" not in budget
    assert any("review call budget" in record.message for record in caplog.records)


def test_review_rejects_expected_budget_derived_for_a_different_finalist_count():
    expected_budget = hypothesis_review_executor.review_call_budget_for(3).to_dict()

    with pytest.raises(ContractValidationError, match="derived for 3 finalists"):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            expected_review_call_budget=expected_budget,
            reviewer_assignments={"metareview": "coordinator"},
        )


def test_formal_review_fails_closed_when_recorded_budget_deviates_from_formula(
    monkeypatch,
):
    # Simulate a duplicated pairwise comparison slipping past the structural
    # step: the closing reconciliation must fail the FORMAL round instead of
    # persisting an over-budget review.
    monkeypatch.setattr(
        hypothesis_review_executor,
        "deterministic_pairwise_order",
        lambda candidate_ids, seed: [
            (candidate_ids[0], candidate_ids[1]),
            (candidate_ids[0], candidate_ids[1]),
        ],
    )

    with pytest.raises(
        ContractValidationError, match="deviated from the exact review call budget"
    ):
        hypothesis_review_executor.execute_hypothesis_review(
            _direct_review_context(),
            execution_mode="formal",
            **_provider_bound_review_runners(),
            reviewer_assignments={"metareview": "coordinator"},
        )
