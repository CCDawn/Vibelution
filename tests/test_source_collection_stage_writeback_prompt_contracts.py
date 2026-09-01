"""Finding prompts require balanced, traceable evidence discovery."""

import pytest

from core.web.services.team_workflow.source_collection.relation_endpoints import (
    build_relation_endpoint_registry,
    normalize_relation_endpoint_token,
    resolve_relation_endpoint,
)
from core.web.services.team_workflow.source_collection.stage_writeback_prompt_contracts import (
    stage_writeback_prompt_lines,
)
from core.web.services.team_workflow.source_collection_stage_tasks import (
    MAX_RELATION_ENDPOINT_ENUM_IDS,
    source_collection_stage_task_writeback_contract,
)
from core.web.services.team_workflow.source_collection.writeback_materialize import (
    _enforce_source_collection_finding_writeback_batch_limits,
    _merge_source_collection_stage_writeback_agent_graph,
    _source_collection_stage_writeback_agent_graph_payload,
)


def test_finding_prompt_requires_counter_search_without_fabrication() -> None:
    prompt = "\n".join(stage_writeback_prompt_lines("finding"))

    assert "mechanism" in prompt
    assert "independent_baseline" in prompt
    assert "limitation_or_null" in prompt
    assert "falsification" in prompt
    assert "canonical searchTrace" in prompt
    assert "Agent 自报 `result.searchTrace[]` 不作为审计权威" in prompt
    assert "status=needs_review" in prompt
    assert "不得伪造负面资料" in prompt


def test_finding_prompt_names_the_writeback_result_argument_and_rejects_payload_json() -> None:
    # 真实故障：模型把结构化候选传给不存在的 payload_json，工具签名拒绝后
    # 耗尽本轮 token 预算。Prompt 必须直接固定正式参数名，不能只描述 result 形状。
    prompt = "\n".join(stage_writeback_prompt_lines("finding"))

    assert "参数 `result_json`" in prompt
    assert "没有 `payload_json` 参数" in prompt
    assert "禁止使用 `payload_json`" in prompt


def test_finding_prompt_requires_rolling_writeback_bounded_verification_and_no_fabricated_doi() -> None:
    # 真实故障：模型把契约读成"攒齐并验证完再一次性写回"，61 分钟零写回；
    # 又自行构造错误 DOI 后在 crossref/doi.org 上试 17 次变体。契约必须
    # 同时压住这三个行为面：滚动写回、定位验证最多一次、禁止构造 DOI。
    prompt = "\n".join(stage_writeback_prompt_lines("finding"))

    assert "滚动写回" in prompt
    assert "source_collection_stage_writeback_tool" in prompt
    assert "禁止等全部候选或 locator 验证完成后再一次性写回" in prompt
    assert "最多 1 次" in prompt
    assert "`result.invalidSources[]`" in prompt
    assert "不得反复重试同一 URL/DOI" in prompt
    assert "绝不自行构造或猜测 DOI" in prompt
    assert "https://api.crossref.org/works?query.bibliographic=" in prompt
    assert "404/429" in prompt


def test_finding_prompt_states_writeback_budget_with_hard_limits() -> None:
    # finding 闭合化第一步：滚动写回保留，但每批 candidateLeads[] 有界、
    # 每任务总批次有上限，超限由服务端硬拒绝；契约必须把预算值和收口
    # 动作写清楚，且预算行只能追加在滚动写回行之后。
    lines = stage_writeback_prompt_lines("finding")
    prompt = "\n".join(lines)

    assert "写回预算" in prompt
    assert "总计最多接受 8 条去重来源" in prompt
    assert "最多 4 个写回批次" in prompt
    assert "每批 `candidateLeads[]` 最多 4 条" in prompt
    assert "实际接受上限取小为 8 条" in prompt
    assert "重复/复用来源不重复消耗总预算" in prompt
    assert "写回收口并结束任务" in prompt
    rolling_index = next(index for index, line in enumerate(lines) if "滚动写回" in line)
    budget_index = next(index for index, line in enumerate(lines) if "写回预算" in line)
    assert budget_index == rolling_index + 1


def test_finding_writeback_limits_are_env_overridable(monkeypatch) -> None:
    from core.web.services.team_workflow.source_collection import writeback_materialize

    assert writeback_materialize.finding_max_writeback_batches_per_task() == 4
    assert writeback_materialize.finding_max_leads_per_writeback_batch() == 4
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_WRITEBACK_BATCHES_PER_TASK", "3")
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_LEADS_PER_WRITEBACK_BATCH", "8")
    assert writeback_materialize.finding_max_writeback_batches_per_task() == 3
    assert writeback_materialize.finding_max_leads_per_writeback_batch() == 8
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_WRITEBACK_BATCHES_PER_TASK", "not-a-number")
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_LEADS_PER_WRITEBACK_BATCH", "-2")
    assert writeback_materialize.finding_max_writeback_batches_per_task() == 4
    assert writeback_materialize.finding_max_leads_per_writeback_batch() == 4


def test_finding_contract_freezes_resolved_search_envelope(monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_WRITEBACK_BATCHES_PER_TASK", "2")
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_LEADS_PER_WRITEBACK_BATCH", "6")
    contract = source_collection_stage_task_writeback_contract(
        "team-a",
        "run-a",
        "task-a",
        stage_id="finding",
        agent_id="agent-a",
        agent_role="source_finder",
        schema_version=1,
    )
    assert contract["searchEnvelope"] == {
        "schemaVersion": 1,
        "totalAcceptedLeadBudget": 8,
        "maxLeadsPerWriteback": 6,
        "maxWritebackBatches": 2,
        "effectiveAcceptedLeadLimit": 8,
        "requiredPerspectives": [
            "mechanism",
            "independent_baseline",
            "limitation_or_null",
            "falsification",
        ],
        "authority": "task_creation_resolved",
    }

    # Later process-env changes cannot alter an already-created task.
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_WRITEBACK_BATCHES_PER_TASK", "1")
    monkeypatch.setenv("VIBELUTION_FINDING_MAX_LEADS_PER_WRITEBACK_BATCH", "1")
    task = {
        "taskId": "task-a",
        "stageId": "finding",
        "agentRole": "source_finder",
        "writebackContract": contract,
    }
    first = [
        {"title": f"Source {index}", "locator": f"https://example.test/{index}"}
        for index in range(6)
    ]
    second = [
        {"title": f"Source {index}", "locator": f"https://example.test/{index}"}
        for index in range(6, 8)
    ]
    _enforce_source_collection_finding_writeback_batch_limits(task, first)
    _enforce_source_collection_finding_writeback_batch_limits(task, second)
    assert sum(
        int(item["newAcceptedLeadCount"])
        for item in task["sourceCollectionWritebackBatches"]
    ) == 8
    with pytest.raises(Exception, match="检索批次已达上限"):
        _enforce_source_collection_finding_writeback_batch_limits(
            task,
            [{"title": "Source 9", "locator": "https://example.test/9"}],
        )


def test_extraction_contract_states_nested_findings_carry_fact_themselves() -> None:
    # 运行时物化只认每条嵌套 finding 自身的 fact（claim 键不能替代），
    # 契约必须把这一点讲清楚，避免模型把 fact 只写在 extraction 父项。
    prompt = "\n".join(stage_writeback_prompt_lines("extraction"))

    assert "都要自带显式事实字段 `fact`" in prompt
    assert "不能用 `claim` 替代" in prompt
    assert "不能只写在 extraction 父项" in prompt
    assert "扁平 extraction" in prompt
    assert "`limitations`（字符串数组" in prompt


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

    # 端点绑定规则：先读真实节点，再写边；允许语义端点但必须先声明枢纽；
    # 解析不了的边降级为 missingLinks 并阻塞下游 knowledge_ingestion。
    assert "`candidateRelations[]`" in prompt
    assert "完整 `candidateId`" in prompt
    assert "source-theme:<themeId>" in prompt
    assert "rh_claim" in prompt
    assert "计入 `missingLinks`" in prompt
    assert "阻塞下游 knowledge_ingestion" in prompt
    assert "themeNodes[]" in prompt
    assert "语义端点" in prompt


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


def test_normalize_relation_endpoint_token_collapses_presentation_forms() -> None:
    # 全角/大小写/空白/首尾标点都折叠到同一键；这保证标题语义端点是
    # 确定性匹配而不是模糊匹配。
    assert (
        normalize_relation_endpoint_token("Ｐｒｅｄｉｃｔｉｖｅ　Ｃｏｄｉｎｇ…")
        == normalize_relation_endpoint_token("Predictive Coding")
    )
    assert normalize_relation_endpoint_token(None) == ""
    assert normalize_relation_endpoint_token("  ") == ""


def test_resolve_relation_endpoint_matrix_exact_title_theme_and_unresolved() -> None:
    registry = build_relation_endpoint_registry(
        [
            {"candidateId": "candidate-20260827aaaa-0001", "title": "Frozen Baseline"},
            {"candidateId": "candidate-20260827bbbb-0002", "title": "Temporal Coding Paper"},
        ]
    )
    registry["ids"].add("source-theme:theme-baseline")
    registry["themes"].setdefault(
        normalize_relation_endpoint_token("frozen baseline"),
        "source-theme:theme-baseline",
    )
    registry["themes"].setdefault(
        normalize_relation_endpoint_token("theme-baseline"),
        "source-theme:theme-baseline",
    )

    # 矩阵：精确 ID / 规范化标题 / 主题 label / 裸主题 ID / source-theme 前缀值 / 不可解析。
    assert resolve_relation_endpoint("candidate-20260827aaaa-0001", registry) == "candidate-20260827aaaa-0001"
    assert resolve_relation_endpoint("frozen baseline", registry) == "candidate-20260827aaaa-0001"
    assert resolve_relation_endpoint("FROZEN BASELINE", registry) == "candidate-20260827aaaa-0001"
    assert resolve_relation_endpoint("theme-baseline", registry) == "source-theme:theme-baseline"
    assert resolve_relation_endpoint("source-theme:theme-baseline", registry) == "source-theme:theme-baseline"
    assert resolve_relation_endpoint("rh_claim", registry) == ""
    assert resolve_relation_endpoint("", registry) == ""

    # 服务端图节点 + agent 声明主题节点合并建表后，label 也能解析。
    merged_registry = build_relation_endpoint_registry(
        [
            {"candidateId": "candidate-a", "title": "Alpha Paper"},
            {
                "candidateId": "source-theme:rh_hub",
                "candidateType": "source_topic",
                "title": "Reward Hub Claim",
            },
        ]
    )
    assert resolve_relation_endpoint("reward hub claim", merged_registry) == "source-theme:rh_hub"
    assert resolve_relation_endpoint("rh_hub", merged_registry) == "source-theme:rh_hub"
    assert resolve_relation_endpoint("alpha paper", merged_registry) == "candidate-a"


def test_relations_contract_injects_closed_set_endpoint_enum() -> None:
    contract = source_collection_stage_task_writeback_contract(
        "team-a",
        "run-a",
        "task-a",
        stage_id="relations",
        agent_id="agent-a",
        agent_role="source_relation_mapper",
        schema_version=1,
        allowed_relation_endpoint_ids=[
            "candidate-20260827aaaa-0001",
            "candidate-20260827bbbb-0002",
            "candidate-20260827aaaa-0001",  # 重复项必须去重
        ],
    )

    policy = contract["resultContract"]["endpointPolicy"]
    assert policy["allowedEndpointIds"] == [
        "candidate-20260827aaaa-0001",
        "candidate-20260827bbbb-0002",
    ]
    assert policy["allowedEndpointIdCount"] == 2
    assert policy["allowedEndpointIdsTruncated"] is False
    assert policy["mode"] == "closed_set_ids_plus_declared_themes_with_semantic_fallback"
    assert policy["semanticEndpoints"]["unresolvedOutcome"] == (
        "edgeDroppedToMissingLinksAndCountedAsDanglingEdge"
    )


def test_relations_contract_truncates_huge_endpoint_enums_and_flags_it() -> None:
    ids = [f"candidate-{index:05d}" for index in range(MAX_RELATION_ENDPOINT_ENUM_IDS + 5)]
    contract = source_collection_stage_task_writeback_contract(
        "team-a",
        "run-a",
        "task-a",
        stage_id="relations",
        agent_id="agent-a",
        agent_role="source_relation_mapper",
        schema_version=1,
        allowed_relation_endpoint_ids=ids,
    )

    policy = contract["resultContract"]["endpointPolicy"]
    assert len(policy["allowedEndpointIds"]) == MAX_RELATION_ENDPOINT_ENUM_IDS
    assert policy["allowedEndpointIdCount"] == MAX_RELATION_ENDPOINT_ENUM_IDS
    assert policy["allowedEndpointIdsTruncated"] is True


def test_extraction_contract_has_no_relations_endpoint_policy() -> None:
    contract = source_collection_stage_task_writeback_contract(
        "team-a",
        "run-a",
        "task-a",
        stage_id="extraction",
        agent_id="agent-a",
        agent_role="source_extractor",
        schema_version=1,
        allowed_relation_endpoint_ids=["candidate-a"],
    )

    assert "endpointPolicy" not in (contract.get("resultContract") or {})
    assert "challengeV2Evidence" in contract["resultContract"]


def test_merge_resolves_semantic_endpoints_to_registered_node_ids() -> None:
    payload = _source_collection_stage_writeback_agent_graph_payload(
        {
            "themes": [{"id": "theme-baseline", "label": "Frozen Baseline"}],
            "candidateRelations": [
                {
                    # 标题端点：服务端规范化解析回 candidateId。
                    "from": "FROZEN BASELINE PAPER",
                    "to": "Temporal coding paper ",  # 尾随空格也要命中规范化标题。
                    "type": "compares_against",
                    "evidenceRefs": ["record-a#p4"],
                },
                {
                    # 已声明主题的 label 直接作为端点：解析到 source-theme 节点。
                    "from": "candidate-source-a",
                    "to": "Frozen Baseline",
                    "type": "supports_theme",
                },
            ],
        }
    )

    graph = _merge_source_collection_stage_writeback_agent_graph(
        {
            "nodes": [
                {"candidateId": "candidate-source-a", "title": "Frozen Baseline Paper"},
                {"candidateId": "candidate-source-b", "title": "Temporal Coding Paper"},
            ]
        },
        payload,
    )

    summary = graph["summary"]
    assert summary["danglingEdgeCount"] == 0
    assert summary["edgeCount"] == 2
    assert summary["semanticBindingEdgeCount"] == 2
    by_relation = {edge["relation"]: edge for edge in graph["edges"]}
    assert by_relation["compares_against"]["sourceCandidateId"] == "candidate-source-a"
    assert by_relation["compares_against"]["targetCandidateId"] == "candidate-source-b"
    assert by_relation["supports_theme"]["targetCandidateId"] == "source-theme:theme-baseline"


def test_merge_keeps_fail_closed_for_undeclared_semantic_hubs() -> None:
    # rh_claim 没有在 themeNodes[] 声明，也没有任何注册表别名命中：
    # resolver 不发明节点，边仍降级 missingLinks 并计数 danglingEdgeCount。
    payload = _source_collection_stage_writeback_agent_graph_payload(
        {
            "themes": [{"id": "theme-real", "label": "Real Theme"}],
            "candidateRelations": [
                {
                    "from": "candidate-source-a",
                    "to": "rh_claim",
                    "type": "candidate_supports_claim",
                }
            ],
        }
    )

    graph = _merge_source_collection_stage_writeback_agent_graph(
        {"nodes": [{"candidateId": "candidate-source-a", "title": "Alpha"}]},
        payload,
    )

    summary = graph["summary"]
    assert summary["edgeCount"] == 0
    assert summary["danglingEdgeCount"] == 1
    assert summary["semanticBindingEdgeCount"] == 0
    dropped = graph["missingLinks"][0]
    assert dropped["targetCandidateId"] == "rh_claim"
