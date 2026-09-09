from tests._support.team_workflow.cases_source_collection import (
    _use_tmp_project_root, _use_fake_local_research_config, _append_stage_task_tool_trace,
    agent_directory_service, session_service, team_service, team_workflow_orchestration_service,
)

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
