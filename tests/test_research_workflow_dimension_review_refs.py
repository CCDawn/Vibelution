"""dimension_reviews 单一权威：轮次行只携带引用，payload 只落权威店一次。

回归背景（P0-A3）：历史上 ``hypothesis_rounds.jsonl`` 的候选里内嵌
``dimensionReviews`` 副本，``dimension_reviews`` 权威店又写一份，两份可写
副本在生产数据里漂移（零哈希重叠）。本文件锁定新的单一权威契约：

1. 写方：新生成轮次的候选只携带 ``dimensionReviewRefs``（minimal locator），
   payload 不再内嵌；行随生成结果在内存中走一次（``dimensionReviewsPayload``），
   权威店在同一生成路径上落盘。
2. 读方：权威物化按「生成内存行 → 权威店引用解析 → 历史内嵌行」取数；
   历史轮（引用绑定之前写入的 append-only 行）永不被改写；引用解析失败
   fail-open 退化为今天的缺评审行为（writer 精确 blocker，不崩溃）。
3. 打包：legacy 内嵌形状与 ref 形状在同一权威内容下产出逐字节相同的
   v2 打包输出。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from core.web.services.team_workflow import meeting_rounds
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
    workflow_artifact_store,
)

_TEAM_ID = "team-dim-refs"
_QUESTION_ID = "SCI-100"
_SELECTION_ID = "hsel-dim-refs"
_RUN_ID = "run-dim-refs"
_NODE_ID = "nr-dim-refs-1"
_MEETING_ID = "hf-review-hsel-dim-refs-r1"
_DIGEST_ID = "digest-dim-refs-1"
_DECISION_ID = "decision-dim-refs-1"
_ROUND_ID = "hround-dim-refs"
_CANDIDATE_A = "hyp-dim-a"
_CANDIDATE_B = "hyp-dim-b"
_CITED_CARD_CANDIDATE = "candidate-20260908171714-7c13f5b4"
_CITED_CARD_RUN = "dprun-20260908163835448433-c0caf640"
_COORDINATOR = "agent-coordinator"
_SCOPE = {
    "program": "XH-202619",
    "theme": "cc-dim-refs",
    "campaign": "cc-campaign-dim-refs",
    "question": _QUESTION_ID,
    "branch": "main",
    "workflow": "hypothesis_and_plan",
    "agentId": _COORDINATOR,
    "mode": "dev",
}
_MEETING = {
    **_SCOPE,
    "meetingRoundId": _MEETING_ID,
    "question": _QUESTION_ID,
    "meetingType": "hypothesis_review",
    "status": "closed",
    "digestId": _DIGEST_ID,
    "decisionRefs": [_DECISION_ID],
    "participants": [_COORDINATOR],
    "participantRoleIds": ["coordinator"],
    "closedBy": _COORDINATOR,
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
        "sourceCollectionRunId": _RUN_ID,
    },
    "nodeRunId": _NODE_ID,
    "inputSnapshotHash": "a" * 64,
}


def _real_scope_hash() -> str:
    from core.research.workflow.contracts.research_scope import scope_hash_for

    return scope_hash_for(
        **{key: _SCOPE[key] for key in ("program", "theme", "campaign", "question", "branch", "workflow")},
        agent_id=_SCOPE["agentId"],
        mode=_SCOPE["mode"],
    )


def _binding_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tmp-isolated stores: round/meeting/chain/artifact/evidence."""
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


def _canonical_ref(tmp_path: Path) -> str:
    """经真实 store 权威算出的可读回 evidence_card_batch ref。"""
    evidence_dir = tmp_path / "workspace" / "teams" / _TEAM_ID / "claim_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schemaVersion": 1,
        "claimEvidenceId": "ce-dim-refs-1",
        "claimId": "claim-dim-refs-1",
        "candidateId": _CITED_CARD_CANDIDATE,
        "sourceId": "https://example.org/evidence",
        "quote": "支撑性证据原文",
        "supportLevel": "supports",
        "sourceCollectionRunId": _CITED_CARD_RUN,
        "workflowRunId": _RUN_ID,
    }
    with open(evidence_dir / "index.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_input_binding as binding,
    )

    ref = binding.evidence_batch_ref_for_run(_TEAM_ID, _CITED_CARD_RUN)
    assert ref
    return ref


def _canonical_rows(canonical_ref: str) -> dict[str, list[dict[str, Any]]]:
    """完整 7 维审计行（canonical refs，可直接通过权威 writer 校验）。"""
    from core.research.competition.question_result_package import (
        REQUIRED_REVIEW_DIMENSIONS,
    )

    def rows_for(candidate_id: str) -> list[dict[str, Any]]:
        return [
            {
                "hypothesis_id": candidate_id,
                "dimension": dimension,
                "rating": "adequate",
                "rationale": f"{dimension} 理由",
                "reviewer": "reviewer-1",
                "evidence_refs": [canonical_ref],
            }
            for dimension in REQUIRED_REVIEW_DIMENSIONS
        ]

    return {_CANDIDATE_A: rows_for(_CANDIDATE_A), _CANDIDATE_B: rows_for(_CANDIDATE_B)}


def _generation_review_output(canonical_ref: str) -> dict[str, Any]:
    """真实执行器形态：候选 A 带裸引用审计行（经 canonical 化），候选 B 带行。"""
    from core.web.services.team_workflow.hypothesis_review_executor import (
        SCORE_DIMENSIONS,
    )

    rows_by_candidate = _canonical_rows(canonical_ref)
    bare_rows_a = [
        {**row, "evidence_refs": [_CITED_CARD_CANDIDATE]}
        for row in rows_by_candidate[_CANDIDATE_A]
    ]

    def candidate(candidate_id: str, claim: str, rows: list[dict[str, Any]] | None) -> dict[str, Any]:
        item = {
            "candidateId": candidate_id,
            "claim": claim,
            "rationale": f"rationale-{candidate_id}",
            "differenceFromAlternatives": f"{candidate_id} 的差异点",
            "lineageRefs": [],
            "scores": {dim: 0.8 for dim in SCORE_DIMENSIONS},
            "reviewedBy": _COORDINATOR,
            "status": "proposed",
        }
        if rows is not None:
            item["dimensionReviews"] = rows
        return item

    return {
        "candidates": [
            candidate(_CANDIDATE_A, "候选 A 的机制陈述", bare_rows_a),
            candidate(_CANDIDATE_B, "候选 B 的机制陈述", rows_by_candidate[_CANDIDATE_B]),
        ],
        "pairwiseComparisons": [
            {
                "comparisonId": "cmp-dim-refs-a-b",
                "leftCandidateId": _CANDIDATE_A,
                "rightCandidateId": _CANDIDATE_B,
                "reviewerAgentId": _COORDINATOR,
                "outcome": "left_wins",
                "justification": "候选 A 证据更完整",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": [_CANDIDATE_A],
            "dominatedCandidateIds": [_CANDIDATE_B],
            "analystAgentId": _COORDINATOR,
            "notes": "explicit front",
        },
        "metaReview": {
            "metaReviewId": "meta-dim-refs-1",
            "reviewerAgentId": _COORDINATOR,
            "recommendationCandidateId": _CANDIDATE_A,
            "rationale": "收敛",
            "riskNotes": "",
            "accepted": True,
        },
        "reviewContextId": "ctx-dim-refs",
        "executionMode": "dev",
        "positionSeed": "seed",
        "roles": {"metareview": _COORDINATOR},
        "modelInvocationReceipts": [],
    }


def _seed_meeting_graph(monkeypatch: pytest.MonkeyPatch, scope_hash: str) -> None:
    """生成路径的会议/摘要/决议以受控记录供给（复用既有测试缝隙）。"""
    meeting = {**_MEETING, "scopeHash": scope_hash}
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
    monkeypatch.setattr(meeting_rounds, "_decisions_path", lambda _team_id: Path("decisions"))
    monkeypatch.setattr(
        meeting_rounds,
        "_read_jsonl",
        lambda path: [digest] if str(path) == "digests" else [decision],
    )


def _patch_generation_executor(
    monkeypatch: pytest.MonkeyPatch, output: dict[str, Any], candidates: list[dict[str, Any]]
) -> None:
    from core.web.services.team_workflow import (
        hypothesis_review_executor,
        research_memory_context,
    )

    # 会议带 receipt authority → FORMAL 路径会从 bounded context 推导预算，
    # 受控 context 必须携带同一候选集。
    monkeypatch.setattr(
        research_memory_context,
        "build_hypothesis_review_context",
        lambda **_kwargs: {"contextId": "ctx-dim-refs", "candidates": candidates},
    )
    monkeypatch.setattr(
        hypothesis_review_executor,
        "execute_hypothesis_review",
        lambda context, **_kwargs: output,
    )


def _patch_chain_inputs(
    monkeypatch: pytest.MonkeyPatch, meeting: dict[str, Any], candidates: list[dict[str, Any]]
) -> None:
    from core.web.services.team_workflow import hypothesis_selection

    monkeypatch.setattr(
        chain,
        "_review_meeting_fan_in_group",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "selectionId": _SELECTION_ID,
            "roundIndex": 1,
            "meetings": [meeting],
        },
    )
    monkeypatch.setattr(
        hypothesis_selection,
        "get_hypothesis_selection",
        lambda *_args, **_kwargs: {
            "selection": {
                "scopeHash": meeting["scopeHash"],
                "questionId": _QUESTION_ID,
                "selectedCandidateIds": [_CANDIDATE_A, _CANDIDATE_B],
            }
        },
    )
    monkeypatch.setattr(chain, "_build_round_candidates", lambda *_a, **_k: candidates)


def test_generation_stores_refs_payload_free_rows_and_same_path_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新轮次：行不内嵌、引用可解析，权威店在同一生成路径收到 payload。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    scope_hash = _real_scope_hash()
    _seed_meeting_graph(monkeypatch, scope_hash)
    output = _generation_review_output(canonical_ref)
    candidates = [
        {"candidateId": item["candidateId"], "claim": item["claim"]}
        for item in output["candidates"]
    ]
    _patch_generation_executor(monkeypatch, output, candidates)
    _patch_chain_inputs(monkeypatch, {**_MEETING, "scopeHash": scope_hash}, candidates)

    result = chain._generate_hypothesis_round(_TEAM_ID, {**_MEETING, "scopeHash": scope_hash})
    assert result["status"] == "created"
    round_record = result["round"]
    round_id = round_record["roundId"]

    # 轮次行 payload-free：候选上没有内嵌审计行，只有 minimal references。
    for candidate in round_record["candidates"]:
        assert "dimensionReviews" not in candidate
        assert "dimension_reviews" not in candidate
        if candidate["candidateId"] == _CANDIDATE_A:
            refs = candidate["dimensionReviewRefs"]
            assert refs[0]["kind"] == "dimension_reviews"
            assert refs[0]["reviewRoundId"] == round_id
            assert refs[0]["hypothesisId"] == _CANDIDATE_A
            assert refs[0]["reviewId"].startswith("drev-")
    # 磁盘上的 append-only ledger 也不携带 payload 副本。
    ledger_path = hrounds._storage_path(_TEAM_ID)
    stored_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line]
    assert stored_rows and all(
        "dimensionReviews" not in candidate and "dimension_reviews" not in candidate
        for record in stored_rows
        for candidate in record.get("candidates", [])
    )

    # 权威店在同一生成路径收到 payload：恰好一条记录，行已 canonical 化。
    authority = result["dimensionReviewsAuthority"]
    assert authority["status"] == "written"
    authority_record = workflow_artifact_store.list_workflow_artifacts(
        _TEAM_ID, kind="dimension_reviews", workflow_run_id=_RUN_ID
    )
    assert len(authority_record) == 1
    authority_payload = authority_record[0]["payload"]
    assert authority_payload["reviewRoundId"] == round_id
    stored_authority_rows = authority_payload["dimensionReviews"]
    assert {
        (row["hypothesis_id"], row["dimension"])
        for row in stored_authority_rows
    } == {
        (candidate_id, row["dimension"])
        for candidate_id in (_CANDIDATE_A, _CANDIDATE_B)
        for row in _canonical_rows(canonical_ref)[candidate_id]
    }
    assert all(
        row["evidence_refs"] == [canonical_ref] for row in stored_authority_rows
    )
    assert result["round"] == round_record


def test_generation_replay_resolves_refs_from_authority_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """refs-only 轮次重放：读方从权威店解析行，权威物化幂等且不翻倍。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    scope_hash = _real_scope_hash()
    meeting = {**_MEETING, "scopeHash": scope_hash}
    _seed_meeting_graph(monkeypatch, scope_hash)
    output = _generation_review_output(canonical_ref)
    candidates = [
        {"candidateId": item["candidateId"], "claim": item["claim"]}
        for item in output["candidates"]
    ]
    _patch_generation_executor(monkeypatch, output, candidates)
    _patch_chain_inputs(monkeypatch, meeting, candidates)

    first = chain._generate_hypothesis_round(_TEAM_ID, meeting)
    assert first["status"] == "created"
    records_after_first = workflow_artifact_store.list_workflow_artifacts(
        _TEAM_ID, kind="dimension_reviews", workflow_run_id=_RUN_ID
    )
    assert len(records_after_first) == 1
    first_hash = records_after_first[0]["contentHash"]

    # 重放：dedup 复用已存轮次（无内存 payload），读方从权威店解析 refs。
    second = chain._generate_hypothesis_round(_TEAM_ID, meeting)
    assert second["status"] == "reused"
    assert second["dimensionReviewsAuthority"]["status"] == "written"
    records_after_second = workflow_artifact_store.list_workflow_artifacts(
        _TEAM_ID, kind="dimension_reviews", workflow_run_id=_RUN_ID
    )
    # 幂等：同一权威身份、同一内容，店不翻倍。
    assert len(records_after_second) == 1
    assert records_after_second[0]["contentHash"] == first_hash
    assert (
        records_after_second[0]["payload"]["dimensionReviews"]
        == records_after_first[0]["payload"]["dimensionReviews"]
    )


def test_refs_round_with_missing_authority_degrades_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引用解析失败 fail-open：退化为缺评审行为（blocked，不崩溃）。"""
    _binding_env(tmp_path, monkeypatch)
    scope_hash = _real_scope_hash()
    meeting = {**_MEETING, "scopeHash": scope_hash}
    refs_round = {
        "roundId": _ROUND_ID,
        "reviewContextId": "ctx-dim-refs",
        "executionMode": "dev",
        "roles": {"metareview": _COORDINATOR},
        "modelInvocationReceipts": [],
        "candidates": [
            {
                "candidateId": _CANDIDATE_A,
                "claim": "候选 A 的机制陈述",
                "dimensionReviewRefs": [
                    {
                        "kind": "dimension_reviews",
                        "reviewId": "drev-missing",
                        "reviewRoundId": _ROUND_ID,
                        "workflowRunId": _RUN_ID,
                        "hypothesisId": _CANDIDATE_A,
                    }
                ],
            },
            {"candidateId": _CANDIDATE_B, "claim": "候选 B 的机制陈述"},
        ],
        "pairwiseComparisons": [],
        "pareto": {},
        "metaReview": {},
    }
    _patch_chain_inputs(monkeypatch, meeting, list(refs_round["candidates"]))
    # 重放/复用形态：生成路径返回已存的 refs-only 轮次（无内存 payload）。
    monkeypatch.setattr(
        hrounds,
        "generate_hypothesis_round_from_meeting",
        lambda *_args, **_kwargs: {"status": "reused", "round": refs_round, "closed": True},
    )

    result = chain._generate_hypothesis_round(_TEAM_ID, meeting)
    authority = result["dimensionReviewsAuthority"]
    # 无权威记录可解析且无内嵌行：writer 以精确 blocker fail-closed（不崩溃、不伪造）。
    assert authority["status"] == "blocked"
    assert "dimension_reviews_missing" in authority["blockerCodes"]


def test_authority_input_resolution_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """读方解析顺序：内存 payload → 权威店 refs → 历史内嵌行（永不被改写）。"""
    _binding_env(tmp_path, monkeypatch)
    canonical_ref = _canonical_ref(tmp_path)
    rows_by_candidate = _canonical_rows(canonical_ref)
    legacy_candidates = [
        {"candidateId": _CANDIDATE_A, "claim": "A", "dimensionReviews": rows_by_candidate[_CANDIDATE_A]},
        {"candidateId": _CANDIDATE_B, "claim": "B", "dimensionReviews": rows_by_candidate[_CANDIDATE_B]},
    ]

    def ref_for(candidate_id: str) -> list[dict[str, str]]:
        return [
            {
                "kind": "dimension_reviews",
                "reviewId": "drev-unit",
                "reviewRoundId": _ROUND_ID,
                "hypothesisId": candidate_id,
            }
        ]

    refs_candidates = [
        {"candidateId": _CANDIDATE_A, "claim": "A", "dimensionReviewRefs": ref_for(_CANDIDATE_A)},
        {"candidateId": _CANDIDATE_B, "claim": "B", "dimensionReviewRefs": ref_for(_CANDIDATE_B)},
    ]

    # (0) 历史内嵌形状：无 payload、无 refs → 原样返回（不重写历史行）。
    legacy_round = {"roundId": _ROUND_ID, "candidates": legacy_candidates}
    assert chain._dimension_review_authority_input(_TEAM_ID, {}, legacy_round, "") is legacy_round

    # (1) 生成内存 payload 优先：行合并到轮次候选投影上。
    refs_round = {"roundId": _ROUND_ID, "candidates": refs_candidates, "pareto": {"k": 1}}
    payload_result = {
        "dimensionReviewsPayload": {
            "reviewId": "drev-unit",
            "reviewRoundId": _ROUND_ID,
            "candidates": [
                {"candidateId": _CANDIDATE_A, "dimensionReviews": rows_by_candidate[_CANDIDATE_A]},
                {"candidateId": _CANDIDATE_B, "dimensionReviews": rows_by_candidate[_CANDIDATE_B]},
            ],
        }
    }
    projected = chain._dimension_review_authority_input(
        _TEAM_ID, payload_result, refs_round, _RUN_ID
    )
    assert projected["pareto"] == {"k": 1}
    assert projected["candidates"][0]["dimensionReviews"] == rows_by_candidate[_CANDIDATE_A]

    # (2) refs 解析自权威店：按 hypothesis_id 分组挂回候选。
    workflow_artifact_store.put_workflow_artifact(
        _TEAM_ID,
        kind="dimension_reviews",
        workflow_run_id=_RUN_ID,
        payload={
            "reviewRoundId": _ROUND_ID,
            "dimensionReviews": [
                *rows_by_candidate[_CANDIDATE_A],
                *rows_by_candidate[_CANDIDATE_B],
            ],
        },
    )
    resolved = chain._dimension_review_authority_input(_TEAM_ID, {}, refs_round, _RUN_ID)
    assert resolved["candidates"][0]["dimensionReviews"] == rows_by_candidate[_CANDIDATE_A]
    assert resolved["candidates"][1]["dimensionReviews"] == rows_by_candidate[_CANDIDATE_B]

    # (3) 店里没有匹配轮次的记录 → 返回原 round（fail-open 交给 writer blocker）。
    empty_store_round = {
        "roundId": "hround-unresolved",
        "candidates": [
            {
                "candidateId": _CANDIDATE_A,
                "claim": "A",
                "dimensionReviewRefs": ref_for(_CANDIDATE_A),
            }
        ],
    }
    assert chain._dimension_review_authority_input(_TEAM_ID, {}, empty_store_round, "") is (
        empty_store_round
    )


def test_packaging_output_identical_for_legacy_and_ref_round_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一权威内容：legacy 内嵌形状与 ref 形状的 v2 打包输出逐字节一致。"""
    _binding_env(tmp_path, monkeypatch)
    from tests.test_research_workflow_result_package_v2 import (
        _authority_sections,
        _build_v2_with_artifacts,
    )

    expected, base_artifacts = _authority_sections()
    fixture_rows = deepcopy(expected["dimension_reviews"])
    hypothesis_ids = sorted({row["hypothesis_id"] for row in fixture_rows})
    assert len(hypothesis_ids) >= 2
    rows_by_hypothesis = {
        hypothesis_id: [row for row in fixture_rows if row["hypothesis_id"] == hypothesis_id]
        for hypothesis_id in hypothesis_ids
    }

    def ref_for(candidate_id: str) -> list[dict[str, str]]:
        return [
            {
                "kind": "dimension_reviews",
                "reviewId": "drev-parity",
                "reviewRoundId": _ROUND_ID,
                "workflowRunId": _RUN_ID,
                "hypothesisId": candidate_id,
            }
        ]

    # legacy 形状：行内嵌在轮次候选上（引用绑定之前的 append-only 形状）。
    legacy_round = {
        "roundId": _ROUND_ID,
        "candidates": [
            {
                "candidateId": hypothesis_id,
                "claim": f"claim {hypothesis_id}",
                "dimensionReviews": rows_by_hypothesis[hypothesis_id],
            }
            for hypothesis_id in hypothesis_ids
        ],
    }
    # refs 形状：同一行内容预先落权威店，轮次候选只带引用。
    workflow_artifact_store.put_workflow_artifact(
        _TEAM_ID,
        kind="dimension_reviews",
        workflow_run_id=_RUN_ID,
        payload={"reviewRoundId": _ROUND_ID, "dimensionReviews": fixture_rows},
    )
    refs_round = {
        "roundId": _ROUND_ID,
        "candidates": [
            {
                "candidateId": hypothesis_id,
                "claim": f"claim {hypothesis_id}",
                "dimensionReviewRefs": ref_for(hypothesis_id),
            }
            for hypothesis_id in hypothesis_ids
        ],
    }

    from core.web.services.team_workflow.research_runtime import (
        dimension_reviews_input_binding as binding,
    )

    def resolved_rows(round_record: dict[str, Any]) -> list[dict[str, Any]]:
        projection = chain._dimension_review_authority_input(
            _TEAM_ID, {}, round_record, _RUN_ID
        )
        canonicalized, _report = binding.canonicalize_dimension_review_evidence(
            _TEAM_ID, projection
        )
        rows: list[dict[str, Any]] = []
        for candidate in canonicalized["candidates"]:
            rows.extend(candidate.get("dimensionReviews") or [])
        return rows

    rows_from_legacy = resolved_rows(legacy_round)
    rows_from_refs = resolved_rows(refs_round)

    # 单一权威：两条读路径解析出完全相同的权威行。
    assert rows_from_legacy == rows_from_refs == fixture_rows

    def build(dimension_payload: dict[str, Any]) -> dict[str, Any]:
        from core.web.services.team_workflow import challenge_question_runs

        artifacts = {
            **deepcopy(base_artifacts),
            "dimension_reviews": deepcopy(dimension_payload),
        }
        package = _build_v2_with_artifacts(monkeypatch, artifacts)
        output = package["challengeQuestionOutput"]
        assert challenge_question_runs._schema_issues(output) == []
        return output

    output_legacy = build({"dimensionReviews": rows_from_legacy})
    output_refs = build({"dimensionReviews": rows_from_refs})
    assert output_legacy == output_refs
    # 与权威内容本身的基准打包一致（权威内容就是 fixture 的同一组行）。
    assert output_legacy == build(base_artifacts["dimension_reviews"])
