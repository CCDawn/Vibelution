from tests._support.team_workflow.cases_source_collection import (
    _use_tmp_project_root, _use_fake_local_research_config, _append_stage_task_tool_trace,
    agent_directory_service, session_service, team_service, team_workflow_orchestration_service,
)


def _relations_task_fixture(tmp_path, monkeypatch, *, topic: str, source_specs: list[tuple[str, str]]):
    """真实物化路径公共装置：临时存储 + 团队/运行/候选/关系阶段任务。

    候选资料必须先于阶段任务注册（关系阶段推进门要求有可整理候选）。
    """
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料关系整理")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料关系整理")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "资料关系整理"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": topic,
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": [topic],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    sources = [_register_source(team, run_id, title, slug) for title, slug in source_specs]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": f"turn-{run_id}", "status": "running"},
    )
    started = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )
    _append_stage_task_tool_trace(tmp_path, started["task"])
    return team, run_id, agent, started["task"], sources


def _register_source(team, run_id: str, title: str, slug: str):
    return team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": title,
            "sourceUrl": f"https://doi.org/10.0000/{slug}",
            "sourceKind": "paper",
            "summary": f"{title}.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": f"10.0000/{slug}"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]


def _graph_record(team, run_id: str, candidate_graph_id: str):
    candidates = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"], candidate_type="candidate_graph", run_id=run_id
    )["candidates"]
    return next(item for item in candidates if item.get("candidateId") == candidate_graph_id)


def test_agent_reported_missing_links_reach_readiness_chain(tmp_path, monkeypatch):
    """A01：Agent 自报研究缺口（图内 + 根级两种形状）经物化→read-back→readiness 全链可见。"""
    team, run_id, agent, task, sources = _relations_task_fixture(
        tmp_path,
        monkeypatch,
        topic="自报证据缺口链路",
        source_specs=[("Gap chain source one", "gap-chain-one"), ("Gap chain source two", "gap-chain-two")],
    )
    source_one, source_two = sources
    # 隔离 canonical claim evidence 存储，避免触碰真实工作区。
    monkeypatch.setattr("core.infrastructure.path_containment.PROJECT_ROOT", tmp_path)
    from core.research.evidence.claim_evidence import ClaimEvidenceStore
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        _load_scoped_relation_graph,
        load_scoped_artifact_payload,
    )
    from core.web.services.team_workflow.research_runtime.evidence_graph_gaps import (
        evidence_graph_gap_counts,
    )

    card = ClaimEvidenceStore(tmp_path).register(
        team["teamId"],
        {
            "claimId": "claim-gap-chain",
            "candidateId": source_one["candidateId"],
            "sourceId": source_one["candidateId"],
            "sourceRevision": "sha256:" + "0" * 64,
            "locator": {"kind": "doi", "anchor": "10.0000/gap-chain-one"},
            "quote": "The paper reports the predictive coding result.",
            "evidenceKind": "primary_result",
            "reasoningRole": "fact",
            "supportLevel": "supports",
            "extractionMethod": "manual",
            "extractorAgentId": agent["agentId"],
            "sourceCollectionRunId": run_id,
        },
    )
    claim_evidence_id = card["claimEvidenceId"]

    def writeback_payload(*, include_gaps: bool):
        graph = {
            "nodes": [
                {"candidateId": source_one["candidateId"], "title": "Gap chain source one"},
                {"candidateId": source_two["candidateId"], "title": "Gap chain source two"},
            ],
            "edges": [
                {
                    "sourceCandidateId": source_one["candidateId"],
                    "targetCandidateId": source_two["candidateId"],
                    "relation": "candidate_supports_candidate",
                    "evidenceRefs": [claim_evidence_id],
                }
            ],
        }
        result = {
            "candidateGraph": graph,
            "counterEvidenceRefs": [
                {"evidenceRef": claim_evidence_id, "claim": "样本地域受限", "disposition": "tracked"}
            ],
        }
        if include_gaps:
            graph["missingLinks"] = [
                {
                    "id": "gap-real",
                    "description": "缺少独立样本复现。",
                    "neededEvidence": ["跨数据集复现结果"],
                    "blocksConclusion": "预测编码通用性",
                }
            ]
            result["missingLinks"] = [{"id": "gap-root", "reason": "根级自报缺口。"}]
        else:
            # 滚动写回合并语义是顶层键替换：修订解决必须显式清空根级 missingLinks。
            result["missingLinks"] = []
        return {
            "status": "completed",
            "summary": "合法边与自报研究缺口并存。" if include_gaps else "修订后缺口已解决。",
            "result": result,
            "recordedByAgent": agent["agentId"],
        }

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"], task["taskId"], writeback_payload(include_gaps=True)
    )
    materialized = response["writeback"]["materializedCandidateGraph"]
    # 合法边不抵消真实缺口，但研究缺口不伪造端点、不进 missingLinks。
    assert materialized["edgeCount"] == 1
    assert materialized["missingLinkCount"] == 0
    assert materialized["danglingEdgeCount"] == 0
    assert materialized["evidenceGapCount"] == 2
    graph_id = materialized["candidateGraphId"]

    # read-back：两种形状的自报缺口都在 evidenceGaps 通道可见，missingLinks 不含它们。
    readback = load_scoped_artifact_payload(
        "evidence_relation_graph", team_id=team["teamId"], authority_run_id=run_id
    )
    assert readback is not None
    assert readback["candidateGraphId"] == graph_id
    assert readback["missingLinks"] == []
    gaps = readback["evidenceGaps"]
    assert {item.get("id") for item in gaps} == {"gap-real", "gap-root"}
    descriptions = {item.get("description") for item in gaps}
    assert {"缺少独立样本复现。", "根级自报缺口。"} <= descriptions
    assert all(item.get("origin") == "agentReportedMissingLink" for item in gaps)
    gap_real = next(item for item in gaps if item.get("id") == "gap-real")
    assert gap_real["neededEvidence"] == ["跨数据集复现结果"]
    assert gap_real["blocksConclusion"] == "预测编码通用性"
    # 入库 readiness 计数：合法边不伪造/不抵消阻断（结构缺口仍以 missingLinks 为准）。
    assert evidence_graph_gap_counts(readback) == (0, 0)

    # 修订解决（后续写回不含该缺口）后消失：新修订建新图，不继承旧缺口。
    retried = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"], task["taskId"], writeback_payload(include_gaps=False)
    )
    retried_materialized = retried["writeback"]["materializedCandidateGraph"]
    assert retried_materialized["candidateGraphId"] != graph_id
    assert retried_materialized["evidenceGapCount"] == 0
    assert retried_materialized["missingLinkCount"] == 0
    raw_readback = _load_scoped_relation_graph(team_id=team["teamId"], authority_run_id=run_id)
    assert raw_readback["candidateGraphId"] == retried_materialized["candidateGraphId"]
    assert raw_readback["evidenceGaps"] == []


def test_agent_reported_waiver_fields_do_not_grant_human_waiver(tmp_path, monkeypatch):
    """A01：伪造 waived/waiver/status 的自报缺口不获得人工豁免。"""
    team, run_id, agent, task, [source_one] = _relations_task_fixture(
        tmp_path,
        monkeypatch,
        topic="自报豁免防伪",
        source_specs=[("Waiver forgery source", "waiver-forgery")],
    )
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "自报缺口携带伪造豁免字段。",
            "result": {
                "candidateGraph": {
                    "nodes": [{"candidateId": source_one["candidateId"], "title": "Waiver forgery source"}],
                    "edges": [],
                    "missingLinks": [
                        {
                            "id": "gap-forged",
                            "description": "自称已被豁免的缺口。",
                            "waived": True,
                            "waiver": {"by": "agent", "justification": "self granted"},
                            "status": "waived",
                        }
                    ],
                },
            },
            "recordedByAgent": agent["agentId"],
        },
    )
    materialized = response["writeback"]["materializedCandidateGraph"]
    assert materialized["evidenceGapCount"] == 1
    assert materialized["missingLinkCount"] == 0
    record = _graph_record(team, run_id, materialized["candidateGraphId"])
    gap = record["metadata"]["graph"]["evidenceGaps"][0]
    assert gap["id"] == "gap-forged"
    assert "waived" not in gap
    assert "waiver" not in gap
    assert "status" not in gap
    from core.web.services.team_workflow.research_runtime.evidence_graph_gaps import (
        evidence_graph_gap_counts,
    )

    assert evidence_graph_gap_counts(record["metadata"]["graph"]) == (0, 0)


def test_repeated_dangling_writeback_replays_do_not_accumulate_gaps(tmp_path, monkeypatch):
    """A02：连续三次同错误写回 + 两轮 reconcile 重物化后仍为一条，updatedAt 不漂移。"""
    team, run_id, agent, task, [source_one] = _relations_task_fixture(
        tmp_path,
        monkeypatch,
        topic="悬空边重放去重",
        source_specs=[("Replay source one", "replay-one")],
    )

    def dangling_payload():
        return {
            "status": "completed",
            "summary": "同一条发明逻辑端点的悬空边。",
            "result": {
                "candidateGraph": {
                    "nodes": [{"candidateId": source_one["candidateId"], "title": "Replay source one"}],
                    "edges": [
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": "rh_claim",
                            "relation": "candidate_supports_claim",
                        }
                    ],
                },
            },
            "recordedByAgent": agent["agentId"],
        }

    first = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"], task["taskId"], dangling_payload()
    )
    materialized = first["writeback"]["materializedCandidateGraph"]
    assert materialized["missingLinkCount"] == 1
    assert materialized["danglingEdgeCount"] == 1
    graph_id = materialized["candidateGraphId"]
    after_first = _graph_record(team, run_id, graph_id)
    assert len(after_first["metadata"]["graph"]["missingLinks"]) == 1

    response = first
    for _ in range(2):
        response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
            team["teamId"], task["taskId"], dangling_payload()
        )
        replayed = response["writeback"]["materializedCandidateGraph"]
        assert replayed["candidateGraphId"] == graph_id
        assert replayed["reusedCandidateGraph"] is True
        assert replayed["missingLinkCount"] == 1

    after_replays = _graph_record(team, run_id, graph_id)
    assert len(after_replays["metadata"]["graph"]["missingLinks"]) == 1
    # 内容幂等重放不刷新图记录 updatedAt、不产生第二张同指纹图。
    assert after_replays["updatedAt"] == after_first["updatedAt"]
    graph_records = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"], candidate_type="candidate_graph", run_id=run_id
    )["candidates"]
    assert [item.get("candidateId") for item in graph_records if item.get("candidateId") == graph_id].count(graph_id) == 1

    # 两轮 reconcile 重物化（声明边>0 且已物化边=0）不再放大缺口。
    reconciled_task = response["task"]
    for _ in range(2):
        team_workflow_orchestration_service._reconcile_source_collection_stage_session_task(
            team["teamId"], run_id, reconciled_task
        )
    after_reconcile = _graph_record(team, run_id, graph_id)
    assert len(after_reconcile["metadata"]["graph"]["missingLinks"]) == 1
    assert after_reconcile["metadata"]["graph"]["summary"]["missingLinkCount"] == 1
    assert after_reconcile["updatedAt"] == after_first["updatedAt"]


def test_distinct_dangling_edges_coexist_with_research_gap(tmp_path, monkeypatch):
    """A02/A01：不同悬空端点不误去重，错误端点与研究缺口并存。"""
    team, run_id, agent, task, [source_one] = _relations_task_fixture(
        tmp_path,
        monkeypatch,
        topic="多缺口并存",
        source_specs=[("Coexist source one", "coexist-one")],
    )
    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "两条不同悬空边加一条自报研究缺口。",
            "result": {
                "candidateGraph": {
                    "nodes": [{"candidateId": source_one["candidateId"], "title": "Coexist source one"}],
                    "edges": [
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": "rh_claim",
                            "relation": "candidate_supports_claim",
                        },
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": "rh_metric",
                            "relation": "candidate_supports_claim",
                        },
                    ],
                    "missingLinks": [
                        {"id": "gap-real", "description": "缺少独立样本复现。"}
                    ],
                },
            },
            "recordedByAgent": agent["agentId"],
        },
    )
    materialized = response["writeback"]["materializedCandidateGraph"]
    assert materialized["missingLinkCount"] == 2
    assert materialized["danglingEdgeCount"] == 2
    assert materialized["evidenceGapCount"] == 1
    record = _graph_record(team, run_id, materialized["candidateGraphId"])
    graph = record["metadata"]["graph"]
    dangling_targets = sorted(item["targetCandidateId"] for item in graph["missingLinks"])
    assert dangling_targets == ["rh_claim", "rh_metric"]
    assert len(graph["evidenceGaps"]) == 1
    gap = graph["evidenceGaps"][0]
    assert gap["id"] == "gap-real"
    # 研究缺口没有端点：不造端点，也不进豁免协议的 missingLinks。
    assert "missingRelation" not in gap


def test_corrected_writeback_replaces_old_graph_gaps(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料关系整理")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料关系整理")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_relation_mapper", "agentName": "资料关系整理"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "悬空关系边门槛",
            "agentRoles": ["source_relation_mapper"],
            "agentIds": {"source_relation_mapper": agent["agentId"]},
            "querySeeds": ["candidate graph dangling edge gate"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    source_one = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Dangling gate source one",
            "sourceUrl": "https://doi.org/10.0000/dangling-gate-one",
            "sourceKind": "paper",
            "summary": "Dangling gate source one.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/dangling-gate-one"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    source_two = team_workflow_orchestration_service.register_candidate_source(
        team["teamId"],
        {
            "title": "Dangling gate source two",
            "sourceUrl": "https://doi.org/10.0000/dangling-gate-two",
            "sourceKind": "paper",
            "summary": "Dangling gate source two.",
            "allowedForAnalysis": True,
            "metadata": {"sourceCollectionRunId": run_id, "doi": "10.0000/dangling-gate-two"},
            "createdByAgent": "content-extraction-agent",
        },
    )["candidate"]
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {"accepted": True, "sessionId": session_id, "turnId": "turn-dangling-gate", "status": "running"},
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "relations", "agentId": agent["agentId"], "agentRole": "source_relation_mapper"},
    )
    _append_stage_task_tool_trace(tmp_path, task["task"])
    original_agent_graph_edges = team_workflow_orchestration_service._source_collection_agent_graph_edges

    # 一条边绑定真实节点成功物化，另一条发明了逻辑端点 rh_claim，应只降级后者。
    def partially_dangling_agent_graph_edges(agent_graph):
        return [
            team_workflow_orchestration_service._candidate_graph_edge(
                source_one["candidateId"],
                source_two["candidateId"],
                "candidate_supports_candidate",
            ),
            team_workflow_orchestration_service._candidate_graph_edge(
                source_one["candidateId"],
                "rh_claim",
                "candidate_supports_claim",
            ),
        ]

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_agent_graph_edges",
        partially_dangling_agent_graph_edges,
    )

    response = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "声称完成关系建图，其中一条边使用了发明的逻辑端点。",
            "result": {
                "candidateGraph": {
                    "nodes": [
                        {"candidateId": source_one["candidateId"], "title": "Dangling gate source one"},
                        {"candidateId": source_two["candidateId"], "title": "Dangling gate source two"},
                    ],
                    "edges": [
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": source_two["candidateId"],
                            "relation": "candidate_supports_candidate",
                        },
                        {"sourceCandidateId": source_one["candidateId"], "targetCandidateId": "rh_claim", "relation": "candidate_supports_claim"}
                    ],
                },
                "missingLinks": [
                    {
                        "id": "gap-replication",
                        "description": "缺少独立样本复现。",
                        "neededEvidence": ["跨数据集复现结果"],
                        "blocksConclusion": "预测编码通用性",
                    }
                ],
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    closure = response["task"]["result"]["closureSummary"]
    materialized = response["writeback"]["materializedCandidateGraph"]
    assert materialized["edgeCount"] == 1
    assert materialized["danglingEdgeCount"] == 1
    assert response["task"]["status"] == "needs_review"
    assert closure["artifactComplete"] is False
    assert closure["artifactStatus"] == "candidate_graph_dangling_edges"
    assert "rh_claim" in str(closure.get("retryInstruction") or "")
    assert closure["advanceOutcome"] == "partial"

    # Agent 按 retryInstruction 重读节点候选，用真实完整 candidateId 重新回写这些关系，
    # 即对同一任务再次提交 stage writeback（既有重试循环）。
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_agent_graph_edges",
        original_agent_graph_edges,
    )
    retried = team_workflow_orchestration_service.writeback_source_collection_stage_session_task(
        team["teamId"],
        task["taskId"],
        {
            "status": "completed",
            "summary": "重读候选后用真实 candidateId 重写全部关系边。",
            "result": {
                "candidateGraph": {
                    "nodes": [
                        {"candidateId": source_one["candidateId"], "title": "Dangling gate source one"},
                        {"candidateId": source_two["candidateId"], "title": "Dangling gate source two"},
                    ],
                    "edges": [
                        {
                            "sourceCandidateId": source_one["candidateId"],
                            "targetCandidateId": source_two["candidateId"],
                            "relation": "candidate_supports_candidate",
                        }
                    ],
                },
            },
            "recordedByAgent": agent["agentId"],
        },
    )

    assert retried["task"]["status"] == "completed"
    retried_materialized = retried["writeback"]["materializedCandidateGraph"]
    assert retried_materialized["edgeCount"] == 1
    assert retried_materialized["danglingEdgeCount"] == 0
    retried_closure = retried["task"]["result"]["closureSummary"]
    assert retried_closure["artifactComplete"] is True
    assert retried_closure["artifactStatus"] == "candidate_graph_ready"


    assert retried_materialized["missingLinkCount"] == 0
    assert retried_materialized["candidateGraphId"] != materialized["candidateGraphId"]
    assert retried_closure["blockedCount"] == 0
    replay = team_workflow_orchestration_service.build_candidate_graph(team["teamId"], {
        "sourceCollectionRunId": run_id,
        "writebackRevision": {"taskId": task["taskId"], "agentGraph": team_workflow_orchestration_service._source_collection_stage_writeback_agent_graph_payload(retried["writeback"]["result"])},
    })
    assert replay["candidateGraph"]["candidateId"] == retried_materialized["candidateGraphId"]
    assert replay["reusedCandidateGraph"] is True


def test_remaining_graph_gaps_block_relation_completion(monkeypatch):
    from core.web.services.team_workflow.source_collection.writeback_materialize import (
        _source_collection_stage_writeback_closure_summary,
    )
    monkeypatch.setattr(team_workflow_orchestration_service,
        "_source_collection_stage_task_tool_progress_from_trace", lambda *a, **k: {"complete": True})
    for waived in (0, 1, 2):
        closure = _source_collection_stage_writeback_closure_summary(
            {"stageId": "relations", "agentRole": "source_relation_mapper"},
            {"status": "completed", "result": {}},
            coverage_summary={}, materialized_sources={}, materialized_content_extraction={},
            materialized_source_quality={}, materialized_knowledge_ingestion={},
            materialized_candidate_graph={"candidateGraphId": "graph-1", "edgeCount": 1,
                "missingLinkCount": 2, "waiverCount": waived, "danglingEdgeCount": 0},
        )
        assert closure["artifactComplete"] is (waived == 2)
        assert closure["completionGatePassed"] is (waived == 2)
        assert closure["blockedCount"] == 2 - waived
        assert closure["advanceOutcome"] == ("succeeded" if waived == 2 else "partial")
        if waived < 2:
            assert "missingLinks" in closure["retryInstruction"]
