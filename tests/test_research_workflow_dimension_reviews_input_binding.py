"""dimension_reviews 权威输入绑定（inputSnapshotHash 派生 + 裸引用 canonical 化）。

覆盖两件事的真实数据形态：
1. 生成路径计算并持久化的 ``inputSnapshotHash`` 必须能从存储轮 + meeting 店
   逐字节复算（可复算 = 可审计）；
2. 评审行裸 ``candidate-*`` 引用经 ClaimEvidenceStore 权威映射为可读回的
   ``evidence_card_batch://`` canonical ref；混合行中不可解析引用被剪枝并全量
   审计（行级 ``citationRefs`` + report），零引用行回退到假说自身证据卡批次，
   无卡假说行保持原样 fail-closed，backfill 重放因此要么整体落盘要么以精确
   blocker 保持 blocked。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.web.services.team_workflow import meeting_rounds
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow.research_runtime import (
    dimension_reviews_input_binding as binding,
    hypothesis_first_chain as chain,
    workflow_artifact_store,
)

_TEAM_ID = "team-dim-binding"
_QUESTION_ID = "SCI-100"
_SELECTION_ID = "hsel-dim-binding"
_RUN_ID = "run-dim-binding"
_NODE_ID = "nr-dim-binding-1"
_MEETING_ID = "hf-review-hsel-dim-binding-r1"
_DIGEST_ID = "digest-dim-binding-1"
_DECISION_ID = "decision-dim-binding-1"
_CANDIDATE_A = "hyp-dim-a"
_CANDIDATE_B = "hyp-dim-b"
_CITED_CARD_CANDIDATE = "candidate-20260908171714-7c13f5b4"
_CITED_CARD_RUN = "dprun-20260908163835448433-c0caf640"
_UNRESOLVED_CITATION = "candidate-19700101000000-deadbeef"
_SCOPE_HASH = "scope-dim-binding"
_SCOPE = {
    "program": "XH-202619",
    "theme": "cc-dim-binding",
    "campaign": "cc-campaign-dim-binding",
    "question": _QUESTION_ID,
    "branch": "main",
    "workflow": "hypothesis_and_plan",
    "agentId": "agent-coordinator",
    "mode": "dev",
}


def _real_scope_hash() -> str:
    from core.research.workflow.contracts.research_scope import scope_hash_for

    return scope_hash_for(
        **{key: _SCOPE[key] for key in ("program", "theme", "campaign", "question", "branch", "workflow")},
        agent_id=_SCOPE["agentId"],
        mode=_SCOPE["mode"],
    )


def _binding_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tmp-isolated stores: round/meeting/selection/chain/artifact/evidence."""
    from core.infrastructure import path_containment
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("VIBELUTION_PROJECTS_HOME", raising=False)
    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    for module in (meeting_rounds, hrounds, chain, hypothesis_selection):
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(path_containment, "PROJECT_ROOT", tmp_path)
    # 并发去重标记是进程级的：新环境不得继承。
    hrounds._IN_FLIGHT_GENERATIONS.clear()


def _seed_claim_evidence(tmp_path: Path, *, candidate_id: str, run_id: str) -> None:
    """一卡权威：ClaimEvidenceStore 只是被读的 jsonl 权威，直接落盘即可。"""
    evidence_dir = tmp_path / "workspace" / "teams" / _TEAM_ID / "claim_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schemaVersion": 1,
        "claimEvidenceId": f"ce-{abs(hash(candidate_id)) % 10**16:016x}",
        "claimId": "claim-dim-1",
        "candidateId": candidate_id,
        "sourceId": "https://example.org/evidence",
        "quote": "支撑性证据原文",
        "supportLevel": "supports",
        "sourceCollectionRunId": run_id,
        "workflowRunId": _RUN_ID,
    }
    with open(evidence_dir / "index.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _canonical_ref(tmp_path: Path) -> str:
    """经真实 store 权威算出的可读回 evidence_card_batch ref。"""
    _seed_claim_evidence(tmp_path, candidate_id=_CITED_CARD_CANDIDATE, run_id=_CITED_CARD_RUN)
    ref = binding.evidence_batch_ref_for_run(_TEAM_ID, _CITED_CARD_RUN)
    assert ref
    return ref


def _review_rows(
    refs_by_dimension: dict[str, list[str]],
    *,
    hypothesis_id: str = "",
) -> list[dict[str, Any]]:
    from core.research.competition.question_result_package import (
        REQUIRED_REVIEW_DIMENSIONS,
    )

    return [
        {
            "hypothesis_id": hypothesis_id or _CANDIDATE_A,
            "dimension": dimension,
            "rating": "adequate",
            "rationale": f"{dimension} 理由",
            "reviewer": "reviewer-1",
            "evidence_refs": refs_by_dimension.get(dimension, []),
        }
        for dimension in REQUIRED_REVIEW_DIMENSIONS
    ]


def _seed_meeting_fan_in(*, scope_hash: str) -> None:
    meeting_rounds._rounds_path(_TEAM_ID).parent.mkdir(parents=True, exist_ok=True)
    meeting_rounds._append_jsonl(
        meeting_rounds._rounds_path(_TEAM_ID),
        {
            **_SCOPE,
            "meetingRoundId": _MEETING_ID,
            "question": _QUESTION_ID,
            "meetingType": "hypothesis_review",
            "status": "closed",
            "scopeHash": scope_hash,
            "digestId": _DIGEST_ID,
            "decisionRefs": [_DECISION_ID],
            "participants": ["agent-coordinator"],
            "participantRoleIds": ["coordinator"],
            "closedBy": "agent-coordinator",
            "inputArtifactRefs": [f"hypothesis_selection:{_SELECTION_ID}"],
            "discussionItemRefs": [
                f"hypothesis_candidate:{_CANDIDATE_A}",
                f"hypothesis_candidate:{_CANDIDATE_B}",
            ],
            "discussionScope": {"workflowRunId": _RUN_ID},
            "modelInvocationReceiptAuthority": {
                "authorityKind": "workflow_run",
                "teamId": _TEAM_ID,
                "questionId": _QUESTION_ID,
                "workflowRunId": _RUN_ID,
            },
            "nodeRunId": _NODE_ID,
        },
    )
    meeting_rounds._append_jsonl(
        meeting_rounds._digests_path(_TEAM_ID),
        {
            "digestId": _DIGEST_ID,
            "summary": "评审摘要",
            "sourceMessageRefs": ["message-1"],
            "contentHash": "digest-content-hash-1",
        },
    )
    meeting_rounds._append_jsonl(
        meeting_rounds._decisions_path(_TEAM_ID),
        {
            "decisionId": _DECISION_ID,
            "decision": "approve",
            "candidateRefs": [_CANDIDATE_A],
        },
    )


def _derived_round_id(scope_hash: str) -> str:
    from core.web.services.team_workflow.hypothesis_rounds import _stable_hash

    return f"hround-{_stable_hash({'meetingRoundId': _MEETING_ID, 'scopeHash': scope_hash})[:12]}"


def _generation_review_output(canonical_ref: str) -> dict[str, Any]:
    """真实执行器形态：候选上挂 7 维审计行，含混合证据引用。"""
    from core.research.competition.question_result_package import (
        REQUIRED_REVIEW_DIMENSIONS,
        REVIEW_DIMENSION_RATINGS,
    )
    from core.web.services.team_workflow.hypothesis_review_executor import (
        SCORE_DIMENSIONS,
    )

    rating = sorted(REVIEW_DIMENSION_RATINGS)[0]
    rows_a = [
        {
            "hypothesis_id": _CANDIDATE_A,
            "dimension": dimension,
            "rating": rating,
            "rationale": f"{dimension} 理由",
            "reviewer": "reviewer-1",
            "evidence_refs": [_CITED_CARD_CANDIDATE],
        }
        for dimension in REQUIRED_REVIEW_DIMENSIONS
    ]
    return {
        "candidates": [
            {
                "candidateId": _CANDIDATE_A,
                "claim": "候选 A 的机制陈述",
                "rationale": "rationale-a",
                "differenceFromAlternatives": "候选 A 的差异点",
                "lineageRefs": [],
                "scores": {dim: 0.8 for dim in SCORE_DIMENSIONS},
                "reviewedBy": "agent-coordinator",
                "status": "proposed",
                "dimensionReviews": rows_a,
            },
            {
                "candidateId": _CANDIDATE_B,
                "claim": "候选 B 的机制陈述",
                "rationale": "rationale-b",
                "differenceFromAlternatives": "候选 B 的差异点",
                "lineageRefs": [],
                "scores": {dim: 0.6 for dim in SCORE_DIMENSIONS},
                "reviewedBy": "agent-coordinator",
                "status": "proposed",
            },
        ],
        "pairwiseComparisons": [
            {
                "comparisonId": "cmp-dim-a-b",
                "leftCandidateId": _CANDIDATE_A,
                "rightCandidateId": _CANDIDATE_B,
                "reviewerAgentId": "agent-coordinator",
                "outcome": "left_wins",
                "justification": "候选 A 证据更完整",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": [_CANDIDATE_A],
            "dominatedCandidateIds": [_CANDIDATE_B],
            "analystAgentId": "agent-coordinator",
            "notes": "explicit front",
        },
        "metaReview": {
            "metaReviewId": "meta-dim-1",
            "reviewerAgentId": "agent-coordinator",
            "recommendationCandidateId": _CANDIDATE_A,
            "rationale": "收敛",
            "riskNotes": "",
            "accepted": True,
        },
        "reviewContextId": "ctx-dim-binding",
        "executionMode": "dev",
        "positionSeed": "seed",
        "roles": {"metareview": "agent-coordinator"},
        "modelInvocationReceipts": [],
        "_canonical_ref": canonical_ref,
    }


def _patch_generation_executor(monkeypatch: pytest.MonkeyPatch, output: dict[str, Any]) -> None:
    from core.web.services.team_workflow import (
        hypothesis_review_executor,
        research_memory_context,
    )

    monkeypatch.setattr(
        research_memory_context,
        "build_hypothesis_review_context",
        lambda **_kwargs: {"contextId": "ctx-dim-binding"},
    )
    monkeypatch.setattr(
        hypothesis_review_executor,
        "execute_hypothesis_review",
        lambda context, **_kwargs: output,
    )


def _seed_meeting_graph_for_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """复用生成测试的既有缝隙：会议/摘要/决议以受控记录供给。"""

    scope_hash = _real_scope_hash()
    meeting = {
        **_SCOPE,
        "meetingRoundId": _MEETING_ID,
        "question": _QUESTION_ID,
        "meetingType": "hypothesis_review",
        "status": "closed",
        "scopeHash": scope_hash,
        "digestId": _DIGEST_ID,
        "decisionRefs": [_DECISION_ID],
        "participants": ["agent-coordinator"],
        "participantRoleIds": ["coordinator"],
        "closedBy": "agent-coordinator",
        "inputArtifactRefs": [f"hypothesis_selection:{_SELECTION_ID}"],
        "discussionItemRefs": [
            f"hypothesis_candidate:{_CANDIDATE_A}",
            f"hypothesis_candidate:{_CANDIDATE_B}",
        ],
    }
    digest = {
        "digestId": _DIGEST_ID,
        "summary": "评审摘要",
        "sourceMessageRefs": ["message-1"],
        "contentHash": "digest-content-hash-1",
    }
    decision = {"decisionId": _DECISION_ID, "decision": "approve"}
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda _team_id, _meeting_id: {"meetingRound": meeting},
    )
    monkeypatch.setattr(meeting_rounds, "_digests_path", lambda _team_id: Path("digests"))
    monkeypatch.setattr(
        meeting_rounds, "_decisions_path", lambda _team_id: Path("decisions")
    )
    monkeypatch.setattr(
        meeting_rounds,
        "_read_jsonl",
        lambda path: [digest] if str(path) == "digests" else [decision],
    )


def test_generation_persists_recomputable_snapshot_hash_and_canonical_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生成即持久化：inputSnapshotHash 可从存储轮逐字节复算；裸引用被映射。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    _seed_meeting_graph_for_generation(monkeypatch)
    output = _generation_review_output(canonical_ref)
    _patch_generation_executor(monkeypatch, output)

    result = hrounds.generate_hypothesis_round_from_meeting(
        _TEAM_ID, _MEETING_ID, {"candidates": output["candidates"]}
    )
    assert result["status"] == "created"
    stored = result["round"]

    snapshot_hash = str(stored.get("inputSnapshotHash") or "")
    assert len(snapshot_hash) == 64 and all(c in "0123456789abcdef" for c in snapshot_hash)
    # 哈希复算断言：审计路径与生成路径必须逐字节一致，且重复复算稳定。
    recomputed = binding.recompute_round_input_snapshot_hash(_TEAM_ID, stored)
    assert recomputed == snapshot_hash
    assert binding.recompute_round_input_snapshot_hash(_TEAM_ID, stored) == snapshot_hash

    # 评审行的裸 candidate-* 引用被映射为可读回的 canonical ref。
    rows = stored["candidates"][0]["dimensionReviews"]
    assert rows and all(
        row["evidence_refs"] == [canonical_ref] for row in rows
    )

    # 输入变化必须可见：摘要内容哈希改变 → 快照哈希改变。
    tampered = dict(stored)
    monkeypatch.setattr(
        meeting_rounds,
        "_read_jsonl",
        lambda path: (
            [{"digestId": _DIGEST_ID, "contentHash": "tampered", "sourceMessageRefs": ["m"]}]
            if str(path) == "digests"
            else [{"decisionId": _DECISION_ID}]
        ),
    )
    assert binding.recompute_round_input_snapshot_hash(_TEAM_ID, tampered) != snapshot_hash


def test_canonicalize_maps_real_citations_and_reports_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """混合行：可解析引用落地为 canonical ref，不可解析引用被剪枝但全量审计。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        read_domain_artifact,
    )

    review = {
        "candidates": [
            {
                "candidateId": _CANDIDATE_A,
                "claim": "claim a",
                "dimensionReviews": [
                    {
                        "hypothesis_id": _CANDIDATE_A,
                        "dimension": "novelty",
                        "rating": "strong",
                        "rationale": "r",
                        "reviewer": "reviewer-1",
                        "evidence_refs": [
                            _CITED_CARD_CANDIDATE,
                            canonical_ref,
                            _UNRESOLVED_CITATION,
                        ],
                    },
                    {
                        "hypothesis_id": _CANDIDATE_A,
                        "dimension": "factual_accuracy",
                        "rating": "adequate",
                        "rationale": "r",
                        "reviewer": "reviewer-1",
                        "evidence_refs": [],
                    },
                ],
            }
        ]
    }

    projection, report = binding.canonicalize_dimension_review_evidence(
        _TEAM_ID, review
    )
    rows = projection["candidates"][0]["dimensionReviews"]
    mapped = rows[0]["evidence_refs"]
    # 真实读回：映射出的 ref 必须能被权威读回验证（哈希一致）。
    assert read_domain_artifact(mapped[0]) is not None
    # 混合行剪枝：不可解析引用被剪掉，evidence_refs 只留可解析的 canonical ref。
    assert mapped == [canonical_ref]
    # 原始引用全量保留在行级 citationRefs（原顺序），审计不丢失。
    assert rows[0]["citationRefs"] == [
        _CITED_CARD_CANDIDATE,
        canonical_ref,
        _UNRESOLVED_CITATION,
    ]
    assert report["resolvedCitations"] == {
        _CITED_CARD_CANDIDATE: [canonical_ref]
    }
    assert report["unresolvedRefs"] == [_UNRESOLVED_CITATION]
    assert report["rowsWithoutRefs"] == 1
    assert report["canonicalRefsPassedThrough"] == 1
    assert report["rowsFallbackToHypothesisEvidence"] == 0
    # 无卡假说的空引用行保持原样，不写 citationRefs。
    assert rows[1]["evidence_refs"] == []
    assert "citationRefs" not in rows[1]
    # 原始评审不被改写。
    assert review["candidates"][0]["dimensionReviews"][0]["evidence_refs"] == [
        _CITED_CARD_CANDIDATE,
        canonical_ref,
        _UNRESOLVED_CITATION,
    ]
    assert "citationRefs" not in review["candidates"][0]["dimensionReviews"][0]


def test_canonicalize_falls_back_to_hypothesis_evidence_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """零引用行回退到假说自身证据卡批次；无卡假说行保持空；重放幂等。"""
    _binding_env(tmp_path, monkeypatch)
    hypothesis_run = "dprun-20260908163835448499-11aa22bb"
    _seed_claim_evidence(tmp_path, candidate_id=_CANDIDATE_A, run_id=hypothesis_run)
    hypothesis_ref = binding.evidence_batch_ref_for_run(_TEAM_ID, hypothesis_run)
    assert hypothesis_ref

    review = {
        "dimensionReviews": [
            {
                "hypothesis_id": _CANDIDATE_A,
                "dimension": "novelty",
                "rating": "strong",
                "rationale": "r",
                "reviewer": "reviewer-1",
                "evidence_refs": [],
            },
            {
                # 无卡假说：回退不到任何批次，行保持空。
                "hypothesis_id": _CANDIDATE_B,
                "dimension": "novelty",
                "rating": "adequate",
                "rationale": "r",
                "reviewer": "reviewer-1",
                "evidence_refs": [],
            },
        ]
    }

    projection, report = binding.canonicalize_dimension_review_evidence(
        _TEAM_ID, review
    )
    rows = projection["dimensionReviews"]
    assert rows[0]["evidence_refs"] == [hypothesis_ref]
    # 原始引用为空：无 citationRefs 可保留。
    assert "citationRefs" not in rows[0]
    assert rows[1]["evidence_refs"] == []
    assert "citationRefs" not in rows[1]
    assert report["rowsFallbackToHypothesisEvidence"] == 1
    assert report["rowsWithoutRefs"] == 2
    assert report["unresolvedRefs"] == []

    # 幂等：回退后的投影再走一遍 canonicalize 完全稳定，不再计回退。
    projection2, report2 = binding.canonicalize_dimension_review_evidence(
        _TEAM_ID, projection
    )
    rows2 = projection2["dimensionReviews"]
    assert rows2[0]["evidence_refs"] == [hypothesis_ref]
    assert rows2[1]["evidence_refs"] == []
    assert "citationRefs" not in rows2[0]
    assert report2["rowsFallbackToHypothesisEvidence"] == 0
    assert report2["canonicalRefsPassedThrough"] == 1


def test_canonicalize_all_unresolvable_refs_fall_back_or_stay_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全部不可解析：有卡假说行回退批次，无卡假说行原样透传供 writer fail-closed。"""
    _binding_env(tmp_path, monkeypatch)
    hypothesis_run = "dprun-20260908163835448500-22bb33cc"
    _seed_claim_evidence(tmp_path, candidate_id=_CANDIDATE_A, run_id=hypothesis_run)
    hypothesis_ref = binding.evidence_batch_ref_for_run(_TEAM_ID, hypothesis_run)
    assert hypothesis_ref

    review = {
        "dimensionReviews": [
            {
                "hypothesis_id": _CANDIDATE_A,
                "dimension": "novelty",
                "rating": "strong",
                "rationale": "r",
                "reviewer": "reviewer-1",
                "evidence_refs": [_UNRESOLVED_CITATION],
            },
            {
                # 无卡假说：行保持不变（refs 原样透传）。
                "hypothesis_id": _CANDIDATE_B,
                "dimension": "novelty",
                "rating": "adequate",
                "rationale": "r",
                "reviewer": "reviewer-1",
                "evidence_refs": [_UNRESOLVED_CITATION],
            },
        ]
    }

    projection, report = binding.canonicalize_dimension_review_evidence(
        _TEAM_ID, review
    )
    rows = projection["dimensionReviews"]
    assert rows[0]["evidence_refs"] == [hypothesis_ref]
    assert rows[0]["citationRefs"] == [_UNRESOLVED_CITATION]
    assert rows[1]["evidence_refs"] == [_UNRESOLVED_CITATION]
    assert "citationRefs" not in rows[1]
    assert report["rowsFallbackToHypothesisEvidence"] == 1
    assert report["unresolvedRefs"] == [_UNRESOLVED_CITATION]


def test_canonicalize_canonical_rows_pass_through_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已是 canonical 引用的行完全直通：不新增字段、计数稳定（幂等）。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    row = {
        "hypothesis_id": _CANDIDATE_A,
        "dimension": "novelty",
        "rating": "strong",
        "rationale": "r",
        "reviewer": "reviewer-1",
        "evidence_refs": [canonical_ref],
    }
    review = {"dimensionReviews": [dict(row)]}

    projection, report = binding.canonicalize_dimension_review_evidence(
        _TEAM_ID, review
    )
    assert projection["dimensionReviews"] == [row]
    assert report["canonicalRefsPassedThrough"] == 1
    assert report["resolvedCitationCount"] == 0
    assert report["unresolvedRefs"] == []
    assert report["rowsWithoutRefs"] == 0
    assert report["rowsFallbackToHypothesisEvidence"] == 0

    projection2, report2 = binding.canonicalize_dimension_review_evidence(
        _TEAM_ID, projection
    )
    assert projection2 == projection
    assert report2["canonicalRefsPassedThrough"] == 1


def _seed_backfill_round(
    tmp_path: Path,
    *,
    scope_hash: str,
    rows: list[dict[str, Any]],
    rows_b: list[dict[str, Any]] | None = None,
) -> str:
    """存量形态：闭合轮 + 完整 selection 元组，但无 inputSnapshotHash。"""
    from core.web.services.team_workflow import hypothesis_selection

    round_id = _derived_round_id(scope_hash)
    hrounds._storage_path(_TEAM_ID).parent.mkdir(parents=True, exist_ok=True)
    hrounds._append_jsonl(
        hrounds._storage_path(_TEAM_ID),
        {
            "roundId": round_id,
            "question": _QUESTION_ID,
            "scopeHash": scope_hash,
            "status": "closed",
            "candidates": [
                {
                    "candidateId": _CANDIDATE_A,
                    "claim": "候选 A 的机制陈述",
                    "rationale": "rationale-a",
                    "differenceFromAlternatives": "候选 A 的差异点",
                    "lineageRefs": [],
                    "dimensionReviews": rows,
                },
                {
                    "candidateId": _CANDIDATE_B,
                    "claim": "候选 B 的机制陈述",
                    "rationale": "rationale-b",
                    "differenceFromAlternatives": "候选 B 的差异点",
                    "lineageRefs": [],
                    **({"dimensionReviews": rows_b} if rows_b is not None else {}),
                },
            ],
            "pairwiseComparisons": [],
            "pareto": {
                "paretoFrontCandidateIds": [_CANDIDATE_A],
                "dominatedCandidateIds": [_CANDIDATE_B],
                "notes": "explicit front",
            },
            "metaReview": {
                "metaReviewId": "meta-dim-1",
                "reviewerAgentId": "agent-coordinator",
                "recommendationCandidateId": _CANDIDATE_A,
                "rationale": "收敛",
                "riskNotes": "",
                "accepted": True,
            },
            "executionMode": "dev",
            "modelInvocationReceipts": [],
            "meetingRefs": [
                {"kind": "meeting_round", "id": _MEETING_ID},
                {"kind": "meeting_digest", "id": _DIGEST_ID},
                {"kind": "decision_record", "id": _DECISION_ID},
            ],
            "createdAt": "2026-09-09T00:00:00Z",
        },
    )
    hypothesis_selection._append_jsonl(
        hypothesis_selection._storage_path(_TEAM_ID),
        {
            "selectionId": _SELECTION_ID,
            "questionId": _QUESTION_ID,
            "scopeHash": scope_hash,
            "selectedCandidateIds": [_CANDIDATE_A, _CANDIDATE_B],
        },
    )
    chain._storage_path(_TEAM_ID).parent.mkdir(parents=True, exist_ok=True)
    chain._append_jsonl(
        chain._storage_path(_TEAM_ID),
        {
            "schemaVersion": 1,
            "recordKind": chain.REVIEW_ROUND_LINK_KIND,
            "linkId": f"hf-link-{_MEETING_ID}",
            "meetingRoundId": _MEETING_ID,
            "previousMeetingRoundId": "",
            "selectionId": _SELECTION_ID,
            "collectionRequestId": "request-dim-1",
            "questionId": _QUESTION_ID,
            "roundIndex": 1,
            "roundBudget": chain.HARD_ROUND_LIMIT,
            "candidateId": "",
            "candidateOrder": None,
            "createdAt": "2026-09-09T00:00:00Z",
        },
    )
    return round_id


def _patch_round_candidate_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """重放前置校验需要候选输入；候选权威本身不是本任务的关注点。"""
    monkeypatch.setattr(
        chain,
        "_build_round_candidates",
        lambda _team_id, _meeting, **_kwargs: [
            {
                "candidateId": _CANDIDATE_A,
                "claim": "候选 A 的机制陈述",
                "rationale": "rationale-a",
                "differenceFromAlternatives": "候选 A 的差异点",
                "lineageRefs": [],
            },
            {
                "candidateId": _CANDIDATE_B,
                "claim": "候选 B 的机制陈述",
                "rationale": "rationale-b",
                "differenceFromAlternatives": "候选 B 的差异点",
                "lineageRefs": [],
            },
        ],
    )


def _artifact_rows() -> list[dict[str, Any]]:
    return workflow_artifact_store.list_workflow_artifacts(
        _TEAM_ID, kind="dimension_reviews", workflow_run_id=_RUN_ID
    )


def test_auto_backfill_writes_legacy_round_with_recomputed_snapshot_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """存量轮端到端：真实 replay → 真实 writer → 落盘 + 哈希可复算断言。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    scope_hash = _real_scope_hash()
    _seed_meeting_fan_in(scope_hash=scope_hash)
    from core.research.competition.question_result_package import (
        REQUIRED_REVIEW_DIMENSIONS,
    )

    rows = _review_rows(
        {dimension: [canonical_ref] for dimension in REQUIRED_REVIEW_DIMENSIONS},
        hypothesis_id=_CANDIDATE_A,
    )
    rows_b = _review_rows(
        {dimension: [canonical_ref] for dimension in REQUIRED_REVIEW_DIMENSIONS},
        hypothesis_id=_CANDIDATE_B,
    )
    round_id = _seed_backfill_round(
        tmp_path, scope_hash=scope_hash, rows=rows, rows_b=rows_b
    )
    _patch_round_candidate_inputs(monkeypatch)

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["status"] == "backfilled", summary
    assert summary["backfilled"] == 1
    artifact_rows = _artifact_rows()
    assert len(artifact_rows) == 1
    payload = artifact_rows[0]["payload"]
    assert payload["reviewRoundId"] == round_id
    stored = hrounds._latest_by_id(
        hrounds._read_jsonl(hrounds._storage_path(_TEAM_ID)), "roundId", round_id
    )
    # 存量轮本身未被改写（round 无 inputSnapshotHash，落盘哈希来自复算）。
    assert not stored.get("inputSnapshotHash")
    recomputed = binding.recompute_round_input_snapshot_hash(_TEAM_ID, stored)
    assert len(recomputed) == 64
    assert payload["inputSnapshotHash"] == recomputed
    # 行引用是落盘前的 canonical 形态。
    assert {row["dimension"]: row["evidence_refs"] for row in payload["dimensionReviews"]}.values()
    assert all(
        row["evidence_refs"] == [canonical_ref]
        for row in payload["dimensionReviews"]
    )


def test_auto_backfill_keeps_citationless_legacy_round_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无引用可映射的存量轮保持 fail-closed blocked，精确 blocker 可见。"""
    _binding_env(tmp_path, monkeypatch)
    scope_hash = _real_scope_hash()
    _seed_meeting_fan_in(scope_hash=scope_hash)
    rows = _review_rows({})
    _seed_backfill_round(tmp_path, scope_hash=scope_hash, rows=rows)
    _patch_round_candidate_inputs(monkeypatch)

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary["status"] == "failed"
    assert summary["reason"] == "authority_still_blocked"
    assert "dimension_review_evidence_refs_missing" in summary["blockerCodes"]
    # 不部分写入：store 无任何记录。
    assert _artifact_rows() == []


def test_auto_backfill_grounds_mixed_citation_round_through_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """writer 集成：混合引用 7 维双候选轮剪枝后 materialize 不再报引用 blocker。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    scope_hash = _real_scope_hash()
    _seed_meeting_fan_in(scope_hash=scope_hash)
    from core.research.competition.question_result_package import (
        REQUIRED_REVIEW_DIMENSIONS,
    )

    mixed_refs = {
        dimension: [canonical_ref, _UNRESOLVED_CITATION]
        for dimension in REQUIRED_REVIEW_DIMENSIONS
    }
    rows = _review_rows(mixed_refs, hypothesis_id=_CANDIDATE_A)
    rows_b = _review_rows(mixed_refs, hypothesis_id=_CANDIDATE_B)
    round_id = _seed_backfill_round(
        tmp_path, scope_hash=scope_hash, rows=rows, rows_b=rows_b
    )
    _patch_round_candidate_inputs(monkeypatch)

    summary = chain.auto_backfill_missing_round_authorities(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    # 剪枝后每行只剩可读回的 canonical ref：引用类 blocker 全部消失。
    assert summary["status"] == "backfilled", summary
    assert summary["backfilled"] == 1
    assert "dimension_review_evidence_ref_invalid" not in summary.get(
        "blockerCodes", []
    )
    assert "dimension_review_evidence_refs_missing" not in summary.get(
        "blockerCodes", []
    )
    artifact_rows = _artifact_rows()
    assert len(artifact_rows) == 1
    payload = artifact_rows[0]["payload"]
    assert payload["reviewRoundId"] == round_id
    assert payload["dimensionReviews"] and all(
        row["evidence_refs"] == [canonical_ref]
        for row in payload["dimensionReviews"]
    )
    # writer 只按自己的字段重建行：审计 citationRefs 不落盘。
    assert all(
        "citationRefs" not in row for row in payload["dimensionReviews"]
    )
