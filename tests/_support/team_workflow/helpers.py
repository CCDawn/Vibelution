import json
import ast
import uuid
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.chat.conversation_ledger import append_conversation_event
from core.agent_kernel import service as agent_kernel_service
from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services import (
    agent_directory_service,
    agent_role_tool_profile_service,
    chat_room_service,
    data_processing_service,
    project_agent_bus_service,
    session_service,
    team_knowledge_service,
    team_service,
    team_workflow_orchestration_service,
)
from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.problem_understanding_artifact_writer import (
    write_problem_understanding_artifact,
)
from tools import team_knowledge_tools

# Domain case modules intentionally omit module-level ``serial``.
# Cases isolate via tmp_path + PROJECT_ROOT monkeypatch and are safe for
# pytest-xdist ``--dist loadfile`` across the five domain pack files.


class _FakeLocalResearchMessage:
    def __init__(self, content, *, reasoning_content=""):
        self.content = content
        self.additional_kwargs = {"reasoning_content": reasoning_content} if reasoning_content else {}

class _FakeLocalResearchClient:
    response = _FakeLocalResearchMessage("{}")
    captured_messages = []

    def __init__(self, *, config=None, profile_id=None):
        self.config = config
        self.profile_id = profile_id

    def invoke(self, messages, tools=None, metadata=None):
        type(self).captured_messages.append({"messages": messages, "metadata": metadata, "profile_id": self.profile_id})
        return type(self).response

class _NoopBackgroundExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append({"fn": fn, "args": args, "kwargs": kwargs})
        future = Future()
        future.set_result(None)
        return future

def _fake_local_research_public_config(*, prompt_cache_mode="explicit_cache_control"):
    return {
        "llm": {
            "profiles": {},
            "model_library": {
                "houmo_qwen35_9b_agent": {
                    "model": "qwen3.5-9b",
                    "provider": "local",
                    "prompt_cache": {"mode": prompt_cache_mode},
                }
            },
        }
    }

def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_processing_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "load_public_config", _fake_local_research_public_config)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", _NoopBackgroundExecutor())
    # The official Challenge Cup dataset is operator-provided and intentionally
    # ignored by Git. Give isolated worktrees a minimal immutable catalog so
    # policy tests exercise the same fail-closed question lookup without
    # reaching into a different worktree or weakening production validation.
    catalog_path = tmp_path / "science_125_questions.test.json"
    catalog_path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "id": "SCI-096",
                        "question_en": "What are the coding principles embedded in neuronal spike trains?",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(challenge_question_runs, "_catalog_path", lambda: catalog_path)


def _canonical_problem_understanding_for_test() -> dict[str, object]:
    return {
        "scope": "验证当前资料搜集阶段的受管测试行为。",
        "subquestions": ["finding 阶段是否遵守当前测试声明的边界？"],
        "assumptions": ["资料搜集运行已绑定当前工作流。"],
        "known_unknowns": ["Agent 的实际资料结果尚未产生。"],
        "human_gate": {
            "required": True,
            "decision": "approved",
            "reviewer": "test-reviewer",
            "decided_at": "2026-08-24T00:00:00Z",
            "rationale": "测试已确认问题边界，可以进入 finding 阶段。",
        },
    }


def _with_problem_understanding_scope(payload):
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    scope = dict(request_payload.get("scope") or {})
    workflow_run_id = str(scope.get("workflowRunId") or "").strip()
    if not workflow_run_id:
        workflow_run_id = f"workflow-test-{uuid.uuid4().hex}"
        scope["workflowRunId"] = workflow_run_id
    request_payload["scope"] = scope
    return request_payload, workflow_run_id


def _write_test_problem_understanding(team_id, run_response, workflow_run_id):
    source_run = run_response.get("run") if isinstance(run_response, dict) else {}
    source_run_id = str((source_run or {}).get("runId") or "").strip()
    assert source_run_id
    write_problem_understanding_artifact(
        team_id=team_id,
        workflow_run_id=workflow_run_id,
        source_collection_run_id=source_run_id,
        node_run_id=f"node-problem-test-{uuid.uuid4().hex}",
        problem_understanding=_canonical_problem_understanding_for_test(),
    )
    return run_response


def _start_source_collection_run_with_problem_understanding(team_id, payload=None):
    request_payload, workflow_run_id = _with_problem_understanding_scope(payload)
    response = team_workflow_orchestration_service.start_source_collection_run(
        team_id,
        request_payload,
    )
    return _write_test_problem_understanding(team_id, response, workflow_run_id)


def _start_research_stage_round_with_problem_understanding(team_id, payload=None):
    request_payload, workflow_run_id = _with_problem_understanding_scope(payload)
    response = team_workflow_orchestration_service.start_research_stage_round(
        team_id,
        request_payload,
    )
    return _write_test_problem_understanding(team_id, response, workflow_run_id)

def _capture_workflow_events(monkeypatch):
    events = []

    def fake_record_runtime_scene_event(*args, **kwargs):
        events.append((args, kwargs))
        return {"accepted": True, "path": kwargs.get("child_log_path", "")}

    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "record_runtime_scene_event",
        fake_record_runtime_scene_event,
    )
    return events

def _seed_source_collection_raw_records(
    run_id: str,
    *,
    count: int = 1,
    title_prefix: str = "Raw source",
    doi_prefix: str = "10.0000/raw-source",
) -> list[dict]:
    """Seed DataProcessing raw records so extraction stage advance preflight can open.

    Product gate ``assert_source_collection_stage_advance_ready`` requires
    ``record_count > 0`` before ``stageId=extraction`` session tasks start.
    """
    records: list[dict] = []
    for index in range(max(1, int(count))):
        records.append(
            data_processing_service.add_record(
                run_id,
                {
                    "sourceType": "paper",
                    "sourceRef": f"https://doi.org/{doi_prefix}-{index}",
                    "title": f"{title_prefix} {index}",
                    "summary": "Seeded raw record for source-collection extraction stage tests.",
                    "metadata": {"doi": f"{doi_prefix}-{index}"},
                },
            )
        )
    return records


def _append_stage_task_tool_trace(project_root: Path, task: dict, *, complete: bool = True, turn_id: str = "") -> None:
    session_id = task["sessionId"]
    turn_id = turn_id or task["turn"]["turnId"]
    tool_names = list(
        dict.fromkeys(
            str(item.get("requiredTool") or "").strip()
            for item in list(task.get("taskChecklist") or [])
            if str(item.get("requiredTool") or "").strip()
        )
    )
    if not complete:
        tool_names = [name for name in tool_names if name != "source_collection_stage_writeback_tool"]
    for tool_name in tool_names:
        append_conversation_event(
            project_root,
            session_id,
            turn_id,
            "tool_result",
            status="done",
            payload={
                "toolCall": {
                    "name": tool_name,
                    "status": "done",
                    "args": {"task_id": task.get("taskId")},
                    "result": "stage tool completed",
                }
            },
        )

def _stage_task_feedback_events(task: dict, *, complete: bool = True) -> list[dict]:
    tool_names = list(
        dict.fromkeys(
            str(item.get("requiredTool") or "").strip()
            for item in list(task.get("taskChecklist") or [])
            if str(item.get("requiredTool") or "").strip()
        )
    )
    if not complete:
        tool_names = [name for name in tool_names if name != "source_collection_stage_writeback_tool"]
    events: list[dict] = []
    for sequence, tool_name in enumerate(tool_names, start=1):
        events.append(
            {
                "sequence": sequence,
                "kind": "tool",
                "status": "done",
                "name": tool_name,
                "arguments": {"task_id": task.get("taskId")},
                "resultPreview": "stage tool completed",
            }
        )
    return events

def _workflow_scene_events_by_code(events, event_code):
    return [
        kwargs
        for args, kwargs in events
        if len(args) >= 3 and args[2] == event_code
    ]

def _stub_source_collection_search_background(monkeypatch):
    calls = []

    def fake_start(team_id, run_id, payload=None):
        calls.append({"teamId": team_id, "runId": run_id, "payload": dict(payload or {})})
        run = data_processing_service.get_processing_run(run_id)
        assignments = data_processing_service.list_collection_assignments(run_id)["assignments"]
        run_status = data_processing_service.get_processing_status(run_id)
        return {
            "schemaVersion": 1,
            "teamId": team_id,
            "runId": run_id,
            "status": "accepted",
            "executionMode": "background",
            "accepted": True,
            "provider": team_workflow_orchestration_service.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
            "executedQueryCount": 0,
            "skippedQueryCount": 0,
            "failedQueryCount": 0,
            "resultCount": 0,
            "recordCount": 0,
            "outputCount": 0,
            "importedCount": 0,
            "run": run,
            "runStatus": run_status,
            "storageArtifacts": {"runDirectory": f"workspace/teams/{team_id}/source_collection_runs/{run_id}"},
            "assignments": assignments,
            "outputs": [],
            "createdRecords": [],
            "imported": [],
            "executionEvents": [],
            "activeWorkRun": {
                "runId": run_id,
                "status": "queued",
                "currentPhase": "queued",
                "summary": "资料搜索已进入后台执行，页面可继续操作。",
                "openAssignmentCount": len(assignments),
                "recordCount": 0,
                "queryCount": 1,
                "storagePath": f"workspace/teams/{team_id}/source_collection_runs/{run_id}",
            },
            "boundaries": {
                "externalSearchTriggered": False,
                "externalSearchQueued": True,
                "metadataOnlyDownload": True,
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
            },
            "nextActions": [],
        }

    monkeypatch.setattr(team_workflow_orchestration_service, "start_source_collection_search_background", fake_start)
    return calls

def _use_fake_local_research_config(monkeypatch):
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "load_public_config",
        lambda: {
            "llm": {
                "schema_version": 1,
                "profiles": {},
                "model_library": {
                    "houmo_qwen35_9b_agent": {
                        "model": "qwen3.5-9b",
                        "provider": "local",
                        "prompt_cache": {"mode": "explicit_cache_control"},
                    }
                },
            }
        },
    )
    monkeypatch.setattr(team_workflow_orchestration_service, "build_effective_config", lambda public_config: public_config)

def _steward_pack_output(*, candidate_ids=None, confidence=0.61):
    normalized_candidate_ids = list(candidate_ids or ["hypothesis-1", "review-1"])
    return {
        "candidateType": "review_record",
        "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
        "evidenceRefs": [{"type": "review", "id": "review-1", "label": "Review 1"}],
        "claims": [{"claim": "Candidate is ready for knowledge governance.", "sourceRef": "paper-1"}],
        "candidateIds": normalized_candidate_ids,
        "targetDomain": "challenge_cup_neuro_algorithm",
        "sourceTrace": {"sourceIds": ["paper-1"], "reviewRecordIds": ["review-1"], "candidateGraphId": "graph-1"},
        "riskSummary": "Evidence is traceable, but experiment remains a smoke test.",
        "proposalPayload": {"title": "Govern context-gated routing hypothesis", "summary": "Add the hypothesis as governed knowledge."},
        "ratingSuggestion": {"importanceLevel": "high", "confidence": 0.66, "stability": "evolving", "reviewPriority": "elevated"},
        "approvalRequired": True,
        "uncertainty": ["experiment not yet validated"],
        "riskFlags": ["approval_required"],
        "confidence": confidence,
        "nextAction": "send_to_ingestion_approval_gate",
        "requiresReview": True,
    }

def _submit_steward_pack_through_source_review(team_id: str, candidate_id: str, knowledge_base_id: str, steward_agent_id: str) -> dict:
    source_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team_id,
        candidate_id,
        {"knowledgeBaseId": knowledge_base_id, "proposedByAgentId": steward_agent_id},
    )
    inbox_source_id = source_pending["candidate"]["metadata"]["knowledgeIngestion"]["inboxSourceId"]
    reviewed = team_knowledge_service.review_owner_inbox_source(
        "team",
        team_id,
        inbox_source_id,
        decision="accepted",
        reviewed_by_agent_id=steward_agent_id,
    )
    knowledge_pending = team_workflow_orchestration_service.submit_steward_pack_to_knowledge_ingestion(
        team_id,
        candidate_id,
        {
            "knowledgeBaseId": knowledge_base_id,
            "proposedByAgentId": steward_agent_id,
            "centralSourceId": reviewed["centralSource"]["centralSourceId"],
        },
    )
    return {"sourcePending": source_pending, "reviewedSource": reviewed, "knowledgePending": knowledge_pending}

def _fake_source_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [
            {
                "title": "Predictive coding cortical hierarchy",
                "sourceRef": "https://doi.org/10.0000/predictive-coding",
                "rawLocation": "https://api.example.test/works/10.0000/predictive-coding",
                "summary": "Metadata-only result for a predictive coding paper.",
                "sourceType": "paper",
                "metadata": {"doi": "10.0000/predictive-coding", "containerTitle": "Journal of Neural Computation"},
                "qualitySignals": {"providerScore": 98.7, "hasDoi": True},
            },
            {
                "title": "Cortical hierarchy dataset",
                "sourceRef": "https://doi.org/10.0000/cortical-dataset",
                "rawLocation": "https://api.example.test/works/10.0000/cortical-dataset",
                "summary": "Metadata-only result for a related dataset.",
                "sourceType": "dataset",
                "metadata": {"doi": "10.0000/cortical-dataset", "containerTitle": "Neural Data Archive"},
                "qualitySignals": {"providerScore": 87.5, "hasDoi": True},
            },
        ][:max_results],
    }

def _fake_low_quality_source_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [
            {
                "title": "机械设计与自动化控制中应注意的问题",
                "sourceRef": "https://doi.org/10.0000/mechanical-design",
                "rawLocation": "https://api.example.test/works/10.0000/mechanical-design",
                "summary": "高考志愿填报与专业目录页面摘录，未讨论神经预测编码、皮层层级或突触可塑性。",
                "sourceType": "paper",
                "metadata": {"doi": "10.0000/mechanical-design", "containerTitle": "Vocational Education Weekly"},
                "qualitySignals": {"providerScore": 88.1, "hasDoi": True},
            },
        ][:max_results],
    }

def _fake_arxiv_atom_feed(entries: list[dict]) -> bytes:
    """Build a minimal arXiv Atom feed (namespace http://www.w3.org/2005/Atom)."""
    entry_xml = ""
    for entry in entries:
        authors = "".join(f"<author><name>{name}</name></author>" for name in entry.get("authors", []))
        categories = ""
        for index, term in enumerate(entry.get("categories", [])):
            primary = ' primary="true"' if index == 0 else ""
            categories += f'<category{primary} term="{term}" />'
        entry_xml += (
            "<entry>"
            f"<id>{entry['id']}</id>"
            f"<title>{entry['title']}</title>"
            f"<summary>{entry['summary']}</summary>"
            f"<published>{entry['published']}</published>"
            f"<updated>{entry.get('updated') or entry['published']}</updated>"
            f"{authors}"
            f"{categories}"
            "</entry>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<id>http://arxiv.org/api/query</id>"
        "<title>ArXiv Query</title>"
        f"{entry_xml}"
        "</feed>"
    ).encode("utf-8")

def _fake_arxiv_atom_entries(feed: bytes):
    from core.web.services.team_workflow.source_collection import residual

    return residual._source_collection_arxiv_atom_entries(feed)

def _fake_arxiv_search_response(query, *, max_results, provider):
    """Mimic one arXiv Atom query: parse the fixture through the real mapper."""
    from core.web.services.team_workflow.source_collection import residual

    query_text = str(query.get("query") or "neural source")
    feed = _fake_arxiv_atom_feed(
        entries=[
            {
                "id": "http://arxiv.org/abs/2101.00983v1",
                "title": "Predictive coding cortical hierarchy preprint",
                "summary": (
                    "We prove new results on predictive coding and the cortical hierarchy "
                    "using rigorous computations; metadata only, no full text."
                ),
                "published": "2021-01-11T18:00:00Z",
                "authors": ["Timothy Platt", "Tim Trudgian"],
                "categories": ["cs.NE", "q-bio.NC"],
            },
            {
                "id": "http://arxiv.org/abs/2007.00001v2",
                "title": "Cortical hierarchy verification dataset",
                "summary": (
                    "A companion dataset for predictive coding cortical hierarchy verification "
                    "experiments with annotated neural recordings."
                ),
                "published": "2020-06-30T17:00:00Z",
                "authors": ["Ada Lovelace"],
                "categories": ["cs.LG"],
            },
        ]
    )
    results = [
        residual._source_collection_result_from_arxiv_entry(
            entry, fallback_source_type=str(query.get("sourceType") or "")
        )
        for entry in _fake_arxiv_atom_entries(feed)
    ]
    return {
        "provider": provider,
        "searchUrl": f"https://export.arxiv.org/api/query?search_query={query_text.replace(' ', '+')}",
        "results": results[:max_results],
    }

def _fake_openalex_works_payload(works: list[dict]) -> bytes:
    """Build a minimal OpenAlex ``/works`` response body."""
    return json.dumps({"meta": {"count": len(works)}, "results": works}).encode("utf-8")

def _fake_openalex_search_response(query, *, max_results, provider):
    """Mimic one OpenAlex works query: parse the fixture through the real mapper.

    The first work carries a deliberately shuffled ``abstract_inverted_index``
    so the real mapper's position-based rebuild is exercised end to end.
    """
    from core.web.services.team_workflow.source_collection import residual

    query_text = str(query.get("query") or "neural source")
    payload = _fake_openalex_works_payload(
        [
            {
                "id": "https://openalex.org/W210100983",
                "doi": "https://doi.org/10.0000/openalex-predictive",
                "title": "Predictive coding cortical hierarchy preprint",
                "publication_year": 2021,
                "publication_date": "2021-01-11",
                "type": "preprint",
                "authorships": [
                    {"author": {"display_name": "Timothy Platt"}},
                    {"author": {"display_name": "Tim Trudgian"}},
                ],
                "primary_location": {
                    "landing_page_url": "https://arxiv.org/abs/2101.00983",
                    "source": {"display_name": "arXiv (Cornell University)"},
                },
                "abstract_inverted_index": {
                    "coding": [3],
                    "predictive": [2],
                    "We": [0],
                    "hierarchy.": [6],
                    "study": [4],
                    "cortical": [5],
                    "the": [1],
                },
            },
            {
                "id": "https://openalex.org/W200700001",
                "doi": "https://doi.org/10.0000/openalex-dataset",
                "title": "Cortical hierarchy verification dataset",
                "publication_year": 2020,
                "publication_date": "2020-06-30",
                "type": "article",
                "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                "primary_location": {
                    "landing_page_url": "https://example.org/works/cortical-hierarchy-verification",
                    "source": {"display_name": "Journal of Neuroscience"},
                },
                "abstract_inverted_index": {
                    "dataset": [4],
                    "A": [0],
                    "annotated": [5],
                    "companion": [1],
                    "with": [7],
                    "recordings.": [9],
                    "neural": [8],
                    "verification": [3],
                    "for": [2],
                },
            },
        ]
    )
    works = json.loads(payload.decode("utf-8")).get("results") or []
    results = [
        residual._source_collection_result_from_openalex_work(
            work, fallback_source_type=str(query.get("sourceType") or "")
        )
        for work in works
    ]
    return {
        "provider": provider,
        "searchUrl": f"https://api.openalex.org/works?search={query_text.replace(' ', '+')}",
        "results": results[:max_results],
    }

def _fake_mixed_excluded_source_search_response(query, *, max_results, provider):
    query_text = str(query.get("query") or "neural source")
    return {
        "provider": provider,
        "searchUrl": f"https://api.example.test/search?q={query_text.replace(' ', '+')}",
        "results": [
            {
                "title": "Empty landing page for predictive coding",
                "sourceRef": "https://doi.org/10.0000/empty-source",
                "rawLocation": "https://api.example.test/works/10.0000/empty-source",
                "summary": "Only a placeholder title was available; no abstract or usable source content.",
                "sourceType": "paper",
                "metadata": {"doi": "10.0000/empty-source", "containerTitle": "Placeholder Journal"},
                "qualitySignals": {"providerScore": 91.0, "hasDoi": True},
            },
            {
                "title": "Predictive coding useful web note",
                "sourceRef": "https://example.test/predictive-coding-useful-note",
                "rawLocation": "https://example.test/predictive-coding-useful-note",
                "summary": "A useful explanation of predictive coding hierarchy without DOI metadata.",
                "sourceType": "url",
                "metadata": {"containerTitle": "Neural Research Notes", "published": "2025"},
                "qualitySignals": {"providerScore": 74.0, "hasDoi": False},
            },
        ][:max_results],
    }

def _create_experiment_plan_with_active_baseline(team_id):
    hypothesis = team_workflow_orchestration_service.record_local_research_model_output(
        team_id,
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Context gated routing",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )["candidate"]
    team_workflow_orchestration_service.decide_research_review(
        team_id,
        {
            "candidateIds": [hypothesis["candidateId"]],
            "decision": "approve",
            "reviewedByAgent": "Research Coordination Agent",
        },
    )
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team_id,
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team_id,
        {"stageRoundId": stage["stageRound"]["stageRoundId"], "createdByAgent": "Research Coordination Agent"},
    )
    baseline = team_workflow_orchestration_service.register_experiment_baseline_artifact(
        team_id,
        draft["plan"]["planId"],
        {
            "artifactPath": "workspace/experiments/baselines/standard-moe-router.json",
            "reproductionCommand": "python experiments/run_baseline.py --config configs/standard_moe_router.yaml",
            "evaluationCommand": "python experiments/evaluate.py --run standard-moe-router",
            "metricValue": "0.71 validation accuracy",
            "registeredByAgent": "Experiment Planning Agent",
        },
    )
    return {"stage": stage, "draft": draft, "baseline": baseline}

def _register_paper_note(team_id, *, evidence=True):
    payload = {
        "candidateType": "paper_note",
        "title": "Predictive coding note",
        "sourceUrl": "https://example.test/paper",
        "summary": "predictive coding key finding",
    }
    if evidence:
        payload["evidenceRefs"] = [{"type": "page_anchor", "id": "anchor-1"}]
    return team_workflow_orchestration_service.register_candidate_source(team_id, payload)["candidate"]["candidateId"]

def _register_typed_candidate(team_id, candidate_type, *, metadata=None):
    payload = {
        "candidateType": candidate_type,
        "title": f"{candidate_type} candidate",
        "sourceUrl": "https://example.test/c",
        "evidenceRefs": [{"type": "page_anchor", "id": "anchor-1"}],
    }
    if metadata:
        payload["metadata"] = metadata
    return team_workflow_orchestration_service.register_candidate_source(team_id, payload)["candidate"]["candidateId"]

def _mock_local_research_invoke(monkeypatch, candidate, *, valid=True):
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "invoke_local_research_model",
        lambda team_id, payload, *, llm_client_factory=None: {
            "candidate": candidate,
            "validation": {"valid": valid, "issues": []},
            "task": {"taskId": "task-x"},
        },
    )

def _seed_plan_with_smoke_run(team_id):
    store = team_workflow_orchestration_service._load_experiment_plan_store(team_id)
    plan = {
        "planId": "exp_deliverable",
        "status": "smoke_passed",
        "dataset": "synthetic",
        "metric": ["accuracy"],
        "baseline": "nearest_centroid",
        "smokePlan": {},
        "smokeRunResults": [{"smokeRunId": "sr-1", "artifactHash": "sha256:abc", "status": "passed"}],
        "updatedAt": "2026-06-25T00:00:00+00:00",
    }
    store.setdefault("plans", []).append(plan)
    store["activePlanId"] = "exp_deliverable"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team_id), store
    )

_PRD_VALIDATE_PATHS = [
    "/teams/{team_id}/workflow-orchestration/" + endpoint
    for endpoint in (
        "knowledge-collection/extract",
        "research/mechanisms/extract",
        "research/mechanisms/map",
        "research/hypotheses/generate",
        "research/review/decide",
        "experiments/plans/{plan_id}/smoke-run",
        "iterations/propose",
        "deliverables/export",
    )
]

def _seed_experiment_plan(team_id, plan_id="exp_plan_smoke", *, baseline=True):
    store = team_workflow_orchestration_service._load_experiment_plan_store(team_id)
    plan = {
        "planId": plan_id,
        "status": "draft",
        "dataset": "synthetic_classification",
        "metric": ["accuracy", "macro_f1"],
        "smokePlan": {"seed": 42, "successThreshold": {"macro_f1_delta": 0.0}},
        "smokeResults": [],
        "updatedAt": "2026-06-25T00:00:00+00:00",
    }
    if baseline:
        plan["baseline"] = "nearest_centroid"
    store.setdefault("plans", []).append(plan)
    store["activePlanId"] = plan_id
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team_id), store
    )
    return plan_id

def _seed_formal_full_run_plan(team_id, plan_id="exp_formal_full_run"):
    from core.research import formal_runner

    store = team_workflow_orchestration_service._load_experiment_plan_store(team_id)
    plan = {
        "planId": plan_id,
        "status": "smoke_passed",
        "experimentContract": {
            "schemaVersion": 2,
            "adapterSelection": {"resolvedAdapterId": formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER},
            "methodConfig": {"seeds": [17, 42, 101]},
        },
        "contractValidation": {"valid": True},
        "readiness": {"readyForFullRun": True},
        "updatedAt": "2026-06-25T00:00:00+00:00",
    }
    store.setdefault("plans", []).append(plan)
    store["activePlanId"] = plan_id
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team_id), store
    )
    return plan_id


def _seed_claim_belief_gate_fixture(
    monkeypatch,
    team_id: str,
    question_id: str,
    candidate_ids,
) -> list[dict]:
    """Seed review-supported core claims so the R2.2 claim belief gate evaluates.

    Claims are proposed and supported through the real owning claim-ledger
    service with the server-authoritative question scope, then bound to their
    candidates through the claim-evidence bridge records the belief service
    consumes.  The bridge records carry the authoritative accepted/support
    state and scope hash; the real ``ClaimEvidenceStore`` is not written
    because its records do not yet carry ``scopeHash`` (belief evaluation
    would neutralize them), so the chain's evidence-reader seam is stubbed
    with exactly those records.
    """
    from collections.abc import Sequence as _Sequence

    assert isinstance(candidate_ids, _Sequence) and not isinstance(candidate_ids, str)
    from core.research.workflow.contracts import scope_hash_for
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain as chain,
    )

    # Align the claim ledger store with the chain module's (tmp-patched) root
    # so fixture claims never land in the real developer workspace.
    monkeypatch.setattr(
        claim_ledger_service, "PROJECT_ROOT", chain.PROJECT_ROOT, raising=False
    )
    scope = chain._question_scope_envelope(team_id, question_id)
    identity = {
        field: scope[field]
        for field in ("program", "theme", "campaign", "question", "branch", "workflow")
    }
    scope_hash = scope_hash_for(
        **identity, agent_id=scope["agentId"], mode=scope["mode"]
    )
    evidence_records: list[dict] = []
    for index, candidate_id in enumerate(candidate_ids, start=1):
        evidence_id = f"ce-gate-{index:02d}"
        claim_id = f"claim-gate-{index:02d}"
        created = claim_ledger_service.propose_claim(
            team_id,
            {
                **identity,
                "agentId": scope["agentId"],
                "mode": scope["mode"],
                "claimId": claim_id,
                "claim": f"Candidate {candidate_id} carries a review-supported core claim.",
                "createdBy": "operator",
                "source": "agent",
            },
        )
        assert created["status"] in {"created", "reused"}, created
        supported = claim_ledger_service.support_claim(
            team_id,
            claim_id,
            {
                "evidenceRefs": [
                    {
                        "claimEvidenceId": evidence_id,
                        "scopeHash": scope_hash,
                        "reviewStatus": "accepted",
                        "supportLevel": "supports",
                        "sourceId": "fixture:claim-belief-gate",
                    }
                ],
                "supportedBy": "operator",
            },
        )
        assert supported["claim"]["status"] == "supported", supported
        evidence_records.append(
            {
                "claimEvidenceId": evidence_id,
                "claimId": claim_id,
                "candidateId": candidate_id,
                "sourceId": "fixture:claim-belief-gate",
                "reviewStatus": "accepted",
                "supportLevel": "supports",
                "scopeHash": scope_hash,
            }
        )
    monkeypatch.setattr(
        chain,
        "_claim_evidence_records",
        lambda _team_id: [dict(record) for record in evidence_records],
    )
    return evidence_records


# Allow case modules to `from ...helpers import *` including private helpers.
__all__ = [name for name in globals() if not name.startswith("__")]
