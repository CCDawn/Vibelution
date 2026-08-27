"""Finding prompts require balanced, traceable evidence discovery."""

from core.web.services.team_workflow.source_collection.stage_writeback_prompt_contracts import (
    stage_writeback_prompt_lines,
)
from core.web.services.team_workflow.source_collection_stage_tasks import (
    source_collection_stage_task_writeback_contract,
)
from core.web.services.team_workflow.source_collection.writeback_materialize import (
    _merge_source_collection_stage_writeback_agent_graph,
    _source_collection_stage_writeback_agent_graph_payload,
)


def test_finding_prompt_requires_counter_search_without_fabrication() -> None:
    prompt = "\n".join(stage_writeback_prompt_lines("finding"))

    assert "mechanism" in prompt
    assert "independent_baseline" in prompt
    assert "limitation_or_null" in prompt
    assert "falsification" in prompt
    assert "result.searchTrace[]" in prompt
    assert "status=found/no_credible_source" in prompt
    assert "status=needs_review" in prompt
    assert "不得伪造负面资料" in prompt


def test_unknown_stage_has_no_extra_writeback_contract() -> None:
    assert stage_writeback_prompt_lines("unknown") == []


def test_extraction_contract_exposes_explicit_challenge_v2_evidence_fields() -> None:
    contract = source_collection_stage_task_writeback_contract(
        "team-a",
        "run-a",
        "task-a",
        stage_id="extraction",
        agent_id="agent-a",
        agent_role="source_extractor",
        schema_version=1,
    )
    challenge = contract["resultContract"]["challengeV2Evidence"]
    assert challenge["mode"] == "challenge_v2_fail_closed"
    assert challenge["requiredFields"] == [
        "title",
        "source_type",
        "source_url",
        "retrieved_at",
        "fact",
        "relation",
        "verification_status",
    ]
    assert challenge["linkage"] == {
        "requiredOneOf": ["candidateId", "recordId"],
        "sourceIdMustEqual": "candidateId_or_recordId",
        "urlCannotBeIdentity": True,
    }


def test_relation_prompt_candidate_relations_materialize_as_candidate_graph_edges() -> None:
    payload = _source_collection_stage_writeback_agent_graph_payload(
        {
            "themes": [{"id": "theme-baseline", "label": "Frozen baseline"}],
            "candidateRelations": [
                {
                    "from": "candidate-source-a",
                    "to": "theme-baseline",
                    "type": "compares_against",
                    "evidenceRefs": ["record-a#p4"],
                }
            ],
        }
    )

    assert payload["themeNodes"] == [
        {"id": "theme-baseline", "label": "Frozen baseline"}
    ]
    assert payload["sourceThemeEdges"] == [
        {
            "candidateId": "candidate-source-a",
            "themeId": "theme-baseline",
            "relation": "compares_against",
            "evidenceRefs": ["record-a#p4"],
        }
    ]
    graph = _merge_source_collection_stage_writeback_agent_graph(
        {"nodes": [{"candidateId": "candidate-source-a"}]},
        payload,
    )

    assert graph["summary"]["edgeCount"] == 1
    assert graph["edges"] == [
        {
            "sourceCandidateId": "candidate-source-a",
            "targetCandidateId": "source-theme:theme-baseline",
            "relation": "compares_against",
            "edgeState": "candidate_only",
            "evidenceRefs": ["record-a#p4"],
        }
    ]


def test_relation_prompt_candidate_graph_predicate_preserves_evidence_refs() -> None:
    payload = _source_collection_stage_writeback_agent_graph_payload(
        {
            "candidateGraph": {
                "nodes": [
                    {"id": "candidate-source-a", "type": "source"},
                    {"id": "theme-temporal", "type": "theme"},
                ],
                "edges": [
                    {
                        "from": "candidate-source-a",
                        "to": "theme-temporal",
                        "predicate": "supports_temporal_coding",
                        "evidenceRefs": ["record-a#results"],
                    }
                ],
            }
        }
    )

    graph = _merge_source_collection_stage_writeback_agent_graph({}, payload)

    assert graph["summary"]["edgeCount"] == 1
    assert graph["edges"] == [
        {
            "sourceCandidateId": "candidate-source-a",
            "targetCandidateId": "theme-temporal",
            "relation": "supports_temporal_coding",
            "edgeState": "candidate_only",
            "evidenceRefs": ["record-a#results"],
        }
    ]


def test_relation_prompt_binds_candidate_relations_endpoints_to_real_nodes() -> None:
    prompt = "\n".join(stage_writeback_prompt_lines("relations"))

    # 端点绑定规则：先读真实节点，再写边；禁止发明逻辑端点；后果是降级并阻塞下游。
    assert "`candidateRelations[]`" in prompt
    assert "完整 `candidateId`" in prompt
    assert "source-theme:<themeId>" in prompt
    assert "rh_claim" in prompt
    assert "计入 `missingLinks`" in prompt
    assert "阻塞下游 knowledge_ingestion" in prompt


def test_merge_counts_dangling_edges_without_counting_contract_missing_links() -> None:
    payload = _source_collection_stage_writeback_agent_graph_payload(
        {
            "candidateRelations": [
                {
                    "from": "candidate-source-a",
                    "to": "candidate-source-b",
                    "type": "candidate_supports_candidate",
                    "evidenceRefs": ["record-a#p2"],
                },
                {
                    "from": "candidate-source-a",
                    "to": "rh_claim",
                    "type": "candidate_supports_claim",
                },
            ],
            # 契约型证据缺口是合法产物，形状为 id/description/...，
            # 不参与边合并，也不得计入 danglingEdgeCount。
            "missingLinks": [
                {
                    "id": "gap-cross-domain",
                    "description": "缺少跨被试重复验证。",
                    "neededEvidence": ["跨数据集复现结果"],
                    "blocksConclusion": "预测编码通用性",
                }
            ],
        }
    )

    graph = _merge_source_collection_stage_writeback_agent_graph(
        {
            "nodes": [
                {"candidateId": "candidate-source-a"},
                {"candidateId": "candidate-source-b"},
            ]
        },
        payload,
    )

    summary = graph["summary"]
    assert summary["agentRelationEdgeCount"] == 2
    assert summary["edgeCount"] == 1
    assert summary["danglingEdgeCount"] == 1
    assert summary["missingLinkCount"] == 1
    dangling_edge = graph["missingLinks"][0]
    assert dangling_edge["targetCandidateId"] == "rh_claim"
