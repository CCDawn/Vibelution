"""HF-3 hypothesis review executor tests.

Covers the batch contract: a closed ``hypothesis_review`` meeting (digest v2
with ``sourceMessageRefs`` + decision records) feeds the four-step separated
review — Reflection (per-candidate seven-dimension independent scoring, role
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

import pytest

from core.research.workflow.contracts import (
    COMPARISON_OUTCOMES,
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
    SCORE_DIMENSIONS,
    ContractValidationError,
    HypothesisRound,
    HYPOTHESIS_REVIEW_MEETING_TYPE,
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

    # Reflection: every candidate scored independently on all seven dimensions
    # by the evidence reviewer role.
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
        return {"outcome": "left_wins", "justification": "七维评分多数维度占优"}

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
