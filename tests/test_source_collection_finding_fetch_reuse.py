"""Accepted finding handoff receipts can anchor extraction without a refetch."""

from dataclasses import replace
import json

import pytest

from core.chat.conversation_ledger import append_conversation_event
from core.research.workflow.contracts import PendingAction
from core.research.workflow.knowledge_sideflow_definition import KNOWLEDGE_SIDEFLOW_WORKFLOW_ID
from core.research.workflow.models import ActorKind
from core.web.services import team_workflow_orchestration_service as service
from core.web.services.team_workflow.research_runtime import (
    agent_turn_completion,
    artifact_readback_registry,
    formal_read_runtime,
)
from core.web.services.team_workflow.research_runtime.domain_ports import AgentTaskHandle
from core.web.services.team_workflow.research_runtime.source_extraction_evidence_cards import (
    build_source_extraction_evidence_cards,
)
from core.web.services.team_workflow.source_collection import candidates, search_execution
from core.web.services.team_workflow.source_collection.extraction_fetch_text import (
    finding_fetched_text_by_source,
)
from core.web.services.team_workflow.source_collection.extraction_quote_anchor_supply import extraction_quotable_sources
from core.web.services.team_workflow.source_collection.stage_reconcile import _source_collection_stage_task_idempotency_key
from core.web.services.team_workflow.source_collection.stage_writeback import (
    _source_collection_stage_writeback_quote_anchor_audit,
)
from core.web.services.team_workflow.source_collection_context import compact_source_collection_quotable_sources
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_run_record,
    open_ledger_store,
)


_TEAM = "team-1"
_RUN = "source-run-1"
_WORKFLOW = "workflow-1"
_URL = "https://arxiv.org/abs/2412.12345"
_ORIGINAL = "Warp occupancy falls when shared memory capacity is exhausted."
_UNRELATED = "A different turn fetched a newer page with unrelated text."
_FINDING_TASK_KIND = "source_collection_stage_session_task"


def _append_fetch(tmp_path, session_id, turn_id, *, text, status="done"):
    return append_conversation_event(
        tmp_path, session_id, turn_id, "tool_result", status=status,
        payload={"toolCall": {
            "name": "web_fetch_tool", "status": status, "arguments": {"url": _URL},
            "result": f"[网页内容] {_URL}\n\n{text}",
        }},
    )


def _initial_message_metadata(finding):
    return {
        **{key: finding[key] for key in ("teamId", "runId", "workflowRunId", "stageId", "agentId", "agentRole", "taskId")},
        "kind": _FINDING_TASK_KIND,
        "sourceCollectionStageTaskId": finding["taskId"],
        "sourceCollectionStageTaskKey": finding["idempotencyKey"],
        "sourceSurface": "team_workflow_stage_task",
    }


def _append_message(tmp_path, session_id, turn_id, content, metadata, *, message_source="agent_inbox"):
    return append_conversation_event(
        tmp_path, session_id, turn_id, "user_message", source="submit_session_message",
        payload={"content": content, "source": message_source, "metadata": {**metadata, "turnId": turn_id}},
    )


def _adopt_final_turn(store, finding, final_turn_id):
    original_turn_id = finding["turn"]["turnId"]
    finding["turn"] = {"turnId": final_turn_id, "previousTurnId": original_turn_id}
    finding["turnIds"] = [original_turn_id, final_turn_id]
    store.submit(
        lambda uow: uow.repository.update_anchor_by_node_run(
            node_run_id="node-finding", anchor_json="{}", turn_id=final_turn_id, status="bound",
        ),
        force_flush=True,
    ).result(timeout=10)


@pytest.fixture(params=["operator_child", "generic"])
def setup(tmp_path, monkeypatch, request):
    candidate = {
        "candidateId": "candidate-1", "teamId": _TEAM, "sourceCollectionRunId": _RUN,
        "candidateType": "source_manifest", "title": "A source", "sourceUrl": _URL,
        "summary": "An Agent summary is not evidence.",
        "metadata": {"sourceRecordId": "record-1", "workflowRunId": _WORKFLOW},
    }
    decoy = {**candidate, "candidateId": "candidate-2"}
    stored_candidates = [candidate, decoy]
    monkeypatch.setattr(candidates, "list_candidate_store_authority_records", lambda *_a, **_kw: stored_candidates)
    monkeypatch.setattr(candidates, "filter_active_source_candidates", lambda _t, _r, items: items)
    monkeypatch.setattr(service, "_source_collection_candidates_for_run", lambda *_a: stored_candidates)
    monkeypatch.setattr(service, "_source_collection_stage_records_for_run", lambda *_a: [])
    monkeypatch.setattr(service, "_project_root", lambda: tmp_path)
    search_trace = [{"receiptRefSets": [[_URL]]}]
    monkeypatch.setattr(search_execution, "project_source_collection_search_trace", lambda *_a: search_trace)

    finding_task = {
        "teamId": _TEAM, "runId": _RUN, "workflowRunId": _WORKFLOW, "stageId": "finding",
        "taskId": "finding-task", "sessionId": "finding-session", "agentId": "finder",
        "agentRole": "source_finder", "status": "completed", "turn": {"turnId": "finding-turn"},
        "idempotencyKey": _source_collection_stage_task_idempotency_key(
            team_id=_TEAM, run_id=_RUN, stage_id="finding", agent_id="finder", agent_role="source_finder",
            task_id="", requested_key="agent-task:node-finding",
        ),
        "writeback": {"materializedSources": {"lineage": [{
            "candidate": {"status": "created", "candidateId": "candidate-1"},
            "record": {"status": "created", "recordId": "record-1"},
        }]}},
    }
    monkeypatch.setattr(
        service, "_find_source_collection_stage_session_task_by_id",
        lambda team_id, task_id: (finding_task, _RUN) if (team_id, task_id) == (_TEAM, "finding-task") else (None, ""),
    )
    extraction_task = {
        "teamId": _TEAM, "runId": _RUN, "workflowRunId": _WORKFLOW, "stageId": "extraction",
        "taskId": "extraction-task", "sessionId": "extraction-session", "agentId": "extractor", "agentRole": "source_extractor",
        "idempotencyKey": _source_collection_stage_task_idempotency_key(
            team_id=_TEAM, run_id=_RUN, stage_id="extraction", agent_id="extractor", agent_role="source_extractor",
            task_id="", requested_key="agent-task:node-extraction",
        ),
    }
    snapshot = {"sourceCollectionRunId": _RUN}
    if request.param == "operator_child":
        operator = {
            "formalNodeRunId": "node-extraction", "formalNodeId": "source_extraction",
            "workflowRunId": _WORKFLOW, "agentId": "extractor", "agentRole": "source_extractor",
        }
        extraction_task["operatorSourceAuthority"] = operator.copy()
        snapshot["operatorSourceAuthorities"] = {"node-extraction": operator}
    _append_message(tmp_path, "finding-session", "finding-turn", "Find evidence", _initial_message_metadata(finding_task))
    event = _append_fetch(tmp_path, "finding-session", "finding-turn", text=_ORIGINAL)
    _append_fetch(tmp_path, "finding-session", "unrelated-turn", text=_UNRELATED)
    _append_fetch(tmp_path, "finding-session", "finding-turn", text="A later failure is not text.", status="failed")

    store = open_ledger_store(tmp_path / "ledger.sqlite")
    monkeypatch.setattr(formal_read_runtime, "get_formal_read_store", lambda: store)

    def seed(uow):
        repo = uow.repository
        run = build_run_record(_WORKFLOW, team_id=_TEAM, workflow_id=KNOWLEDGE_SIDEFLOW_WORKFLOW_ID, status="running")
        repo.insert_run(replace(run, input_snapshot_json=json.dumps(snapshot)))
        repo.insert_command(build_command_record(run_id=_WORKFLOW, team_id=_TEAM))
        finding = build_attempt_record("node-finding", run_id=_WORKFLOW, node_id="source_finding", status="succeeded")
        repo.insert_attempt(replace(finding, execution_anchor_id="finding-anchor", finished_at_ms=FIXED_NOW_MS + 1))
        repo.insert_anchor(
            anchor_id="finding-anchor", node_run_id="node-finding", actor_kind="agent", anchor_json="{}",
            agent_id="finder", role_key="source_finder", session_id="finding-session", task_id="finding-task",
            turn_id="finding-turn", created_at_ms=FIXED_NOW_MS,
        )
        repo.insert_attempt(build_attempt_record(
            "node-extraction", run_id=_WORKFLOW, node_id="source_extraction", status="running", started_at_ms=FIXED_NOW_MS + 2,
        ))
        content_hash = "a" * 64
        ref = artifact_readback_registry.build_canonical_ref(
            kind="source_candidate_batch", team_id=_TEAM, authority_run_id=_RUN, content_hash=content_hash,
        )
        repo.insert_artifact_receipt(
            receipt_id="receipt-finding", run_id=_WORKFLOW, node_run_id="node-finding", team_id=_TEAM,
            artifact_kind="source_candidate_batch", canonical_ref_json=json.dumps({"canonicalRef": ref}),
            artifact_version="1.0.0", sha256=content_hash, domain_revision="verified", materialized=1, verified_at_ms=FIXED_NOW_MS + 1,
        )
        repo.insert_handoff(
            handoff_id="handoff-1", run_id=_WORKFLOW, edge_id="source_finding->source_extraction",
            from_node_run_id="node-finding", to_node_id="source_extraction", to_node_run_id="node-extraction",
            gate_kind="auto", input_snapshot_hash="a" * 64, offered_at_ms=FIXED_NOW_MS + 1,
        )
        repo.update_handoff_status("handoff-1", "ready", FIXED_NOW_MS + 1)
        repo.update_handoff_status("handoff-1", "accepted", FIXED_NOW_MS + 2)
        repo.insert_handoff_receipt("handoff-1", "receipt-finding", 0)

    store.submit(seed, force_flush=True).result(timeout=10)
    yield extraction_task, finding_task, stored_candidates, search_trace, store, event
    store.close()


def _entry(candidate_id="candidate-1", *, quote=_ORIGINAL):
    return {"candidateId": candidate_id, "title": "A source", "source_type": "preprint", "source_url": _URL,
            "retrieved_at": "2026-11-15T00:00:00Z", "relation": "supports", "verification_status": "full_text_checked",
            "claims": [{"fact": "Resource limits constrain occupancy.", "quote": quote, "sourceRef": _URL}]}


def test_handoff_original_text_reaches_compact_context_audit_and_evidence_card(setup):
    task, _, stored_candidates, _, _, event = setup
    source_receipts = finding_fetched_text_by_source(_TEAM, _RUN, task, stored_candidates)
    assert set(source_receipts) == {("candidate", "candidate-1"), ("record", "record-1")}
    sources = compact_source_collection_quotable_sources(extraction_quotable_sources(
        stored_candidates, [], finding_text_by_source=source_receipts,
    ))
    block = sources[0]["blocks"][0]
    assert block["text"] == _ORIGINAL
    assert block["eventId"] == event.event_id
    assert block["findingReceipt"] == {
        "nodeRunId": "node-finding", "taskId": "finding-task", "artifactReceiptId": "receipt-finding",
        "sessionId": "finding-session", "turnId": "finding-turn",
    }
    assert not sources[1]["quoteAvailable"]  # same URL, absent from finding's candidate lineage
    result = {"candidateExtractions": [_entry(quote=block["text"])]}
    audit = _source_collection_stage_writeback_quote_anchor_audit(_TEAM, _RUN, task, result)
    assert not audit["hard_errors"] and not audit["mismatches"]
    paraphrased = _source_collection_stage_writeback_quote_anchor_audit(
        _TEAM, _RUN, task, {"candidateExtractions": [_entry(quote=_UNRELATED)]},
    )
    assert paraphrased["mismatches"][0]["finding"] == "mismatched_quote"
    cards = build_source_extraction_evidence_cards(
        {"candidateExtractions": [_entry(), _entry("candidate-2"), _entry(quote=_UNRELATED)]},
        fetched_text={}, finding_text_by_source=source_receipts,
    )
    assert [card["verification_status"] for card in cards] == ["full_text_checked", "unverified", "metadata_checked"]


def test_wrong_attempt_task_run_or_source_binding_cannot_supply_external_text(setup):
    task, finding, stored_candidates, trace, store, _ = setup

    def read(t=task):
        return finding_fetched_text_by_source(_TEAM, _RUN, t, stored_candidates)

    assert not read({**task, "runId": "another-run"})
    assert not read({**task, "idempotencyKey": "manual-extraction"})
    finding["sessionId"] = "other-session"
    assert not read()
    finding["sessionId"] = "finding-session"
    trace[0]["receiptRefSets"] = [["https://arxiv.org/abs/2401.12345"]]
    assert not read()
    trace[0]["receiptRefSets"] = [[_URL]]
    store.submit(lambda uow: uow.repository.insert_attempt(build_attempt_record(
        "node-finding-rerun", run_id=_WORKFLOW, node_id="source_finding", status="running", attempt=2,
    )), force_flush=True).result(timeout=10)
    assert not read()  # a rerun supersedes the accepted predecessor


def test_extraction_own_fetch_still_wins_and_unmarked_finding_turns_do_not_leak(setup, tmp_path):
    task, _, stored_candidates, _, _, _ = setup
    source_receipts = finding_fetched_text_by_source(_TEAM, _RUN, task, stored_candidates)
    assert _UNRELATED not in source_receipts[("candidate", "candidate-1")][_URL]["text"]
    own = "This is extraction's newer authoritative fetch."
    _append_fetch(tmp_path, "extraction-session", "extraction-turn", text=own)
    result = {"candidateExtractions": [_entry(quote=own)]}
    audit = _source_collection_stage_writeback_quote_anchor_audit(_TEAM, _RUN, task, result)
    assert not audit["hard_errors"] and not audit["mismatches"]
    block = audit["blocks_by_id"]["candidate-1"][0]
    assert block["text"] == own and "findingReceipt" not in block


def test_final_anchor_reuses_fetch_from_formal_nonliteral_remediation_predecessor(setup, tmp_path, monkeypatch):
    from core.web.services.session import submit

    task, finding, stored_candidates, _, store, _ = setup
    session_id = finding["sessionId"]
    handle = AgentTaskHandle(session_id, 1, finding["taskId"], "finding-turn")
    action = PendingAction(
        action_id="find-action", run_id=_WORKFLOW, node_id="source_finding", node_run_id="node-finding",
        attempt=1, actor_kind=ActorKind.AGENT, action_kind="start_agent_task", input_snapshot_hash="a" * 64,
        input_artifact_refs=(), binding_snapshot_id=None, budget_policy_hash="b" * 64,
    )
    seen = []
    turn_ids = iter(("finding-repair", "finding-final"))

    def admit(session_id, content, *, message_metadata, message_source, **_options):
        turn_id = next(turn_ids)
        assert not {"runId", "stageId", "agentId", "agentRole"} & message_metadata.keys()
        seen.append(content)
        _append_message(tmp_path, session_id, turn_id, content, message_metadata, message_source=message_source)
        return {"turnId": turn_id}

    monkeypatch.setattr(submit, "submit_session_message", admit)
    monkeypatch.setattr(agent_turn_completion, "_record_turn_continuation_scene_event", lambda *args, **kwargs: None)

    repair_turn = agent_turn_completion._submit_agent_turn_continuation(
        handle, action=action, input_snapshot={"teamId": _TEAM}, attempt=1, from_turn_id="finding-turn",
        paused_status="stage_task_needs_review", continuation_message="Use the repaired source query.",
        source_collection_scope=True,
    )
    repaired_text = "The remedial turn supplied this verbatim source text."
    repaired_event = _append_fetch(tmp_path, session_id, repair_turn, text=repaired_text)
    final_turn = agent_turn_completion._submit_agent_turn_continuation(
        handle, action=action, input_snapshot={"teamId": _TEAM}, attempt=2, from_turn_id=repair_turn,
        paused_status="paused_limit", source_collection_scope=True,
    )
    # This turn shares task, session, and locator but belongs to another attempt.
    _append_message(tmp_path, session_id, "foreign-attempt", "Try again", {
        "kind": _FINDING_TASK_KIND,
        "sourceCollectionStageTaskId": finding["taskId"], "taskId": finding["taskId"], "teamId": _TEAM,
        "workflowRunId": _WORKFLOW, "workflowNodeId": "source_finding", "nodeRunId": "node-finding-rerun",
        "sourceSurface": "team_workflow_agent_turn_continuation", "continuationOfTurnId": final_turn,
    })
    _append_fetch(tmp_path, session_id, "foreign-attempt", text=_UNRELATED)
    _adopt_final_turn(store, finding, final_turn)

    assert seen == ["Use the repaired source query.", "继续"]
    receipts = finding_fetched_text_by_source(_TEAM, _RUN, task, stored_candidates)
    receipt = receipts[("candidate", "candidate-1")][_URL]
    assert (receipt["text"], receipt["turnId"], receipt["eventId"]) == (repaired_text, repair_turn, repaired_event.event_id)


def test_legacy_inherited_continue_can_use_adopted_stage_task_predecessor(setup, tmp_path):
    from core.web.services.session.session_ops import _source_collection_stage_task_continuation_metadata

    task, finding, stored_candidates, _, store, original = setup
    session_id = finding["sessionId"]
    metadata = _source_collection_stage_task_continuation_metadata([
        {"role": "user", "content": "Find evidence", "metadata": _initial_message_metadata(finding)},
    ])
    assert "workflowRunId" not in metadata
    _append_message(tmp_path, session_id, "legacy-continue", "继续", {
        **metadata, "sourceCollectionStageContinuation": True,
    }, message_source="raw")
    _adopt_final_turn(store, finding, "legacy-continue")

    receipts = finding_fetched_text_by_source(_TEAM, _RUN, task, stored_candidates)
    assert receipts[("candidate", "candidate-1")][_URL]["eventId"] == original.event_id


def test_continuation_cannot_follow_a_predecessor_from_another_node_attempt(setup, tmp_path):
    task, finding, stored_candidates, _, store, _ = setup
    session_id = finding["sessionId"]
    metadata = {
        "kind": _FINDING_TASK_KIND,
        "sourceCollectionStageTaskId": finding["taskId"], "taskId": finding["taskId"], "teamId": _TEAM,
        "workflowRunId": _WORKFLOW, "workflowNodeId": "source_finding",
        "sourceSurface": "team_workflow_agent_turn_continuation",
    }
    _append_message(tmp_path, session_id, "wrong-parent", "A different attempt", {
        **metadata, "nodeRunId": "node-finding-other", "continuationOfTurnId": "finding-turn",
    })
    _append_fetch(tmp_path, session_id, "wrong-parent", text=_UNRELATED)
    _append_message(tmp_path, session_id, "finding-final", "继续", {
        **metadata, "nodeRunId": "node-finding", "continuationOfTurnId": "wrong-parent",
    })
    _adopt_final_turn(store, finding, "finding-final")

    assert not finding_fetched_text_by_source(_TEAM, _RUN, task, stored_candidates)


def test_url_claim_materializes_from_reused_journal_not_the_agent_declaration(setup, tmp_path, monkeypatch):
    from core.research.evidence import ClaimEvidenceStore
    from core.web.services import team_service
    from core.web.services.team_workflow import claim_ledger
    from core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer import (
        materialize_claim_evidence_from_task,
    )
    from core.web.services.team_workflow.research_runtime.hypothesis_first_chain import _question_scope_envelope

    task, _, _, _, _, _ = setup
    monkeypatch.setattr(team_service, "assert_team_exists", lambda team_id: team_id)
    monkeypatch.setattr(claim_ledger, "PROJECT_ROOT", tmp_path)
    created = materialize_claim_evidence_from_task(
        project_root=tmp_path, team_id=_TEAM, workflow_run_id=_WORKFLOW, source_collection_run_id=_RUN,
        task={**task, "result": {"candidateExtractions": [_entry(), _entry("candidate-2"), _entry(quote=_UNRELATED)]}},
        model_ref="test/model", question_scope=_question_scope_envelope(_TEAM, "SCI-FETCH"),
    )
    assert len(created) == 1
    assert created[0]["challengeEvidence"]["verification_status"] == "full_text_checked"
    assert created[0]["locator"] == {"kind": "url", "url": _URL}
    assert [record["quote"] for record in ClaimEvidenceStore(tmp_path).list(_TEAM)] == [_ORIGINAL]
