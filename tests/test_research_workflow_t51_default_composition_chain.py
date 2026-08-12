"""T5.1-8: deterministic composition integration gate (not a production gate).

build_workflow_runtime() without agent_task_factory / domain_overrides drives
source_finding → source_extraction → evidence_relations with real Session/
Task/Turn anchors and Ledger receipts. This gate stubs only model decisions;
canonical tool calls still pass through the real Agent tool lifecycle and
production source-collection writeback tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.contracts import ActorRef, CommandRequest, WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)
from tests._support.llm_turn_stub import install_fast_stage_writeback_llm_stub
from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)
from tests._support.workflow_ledger_helpers import build_event_record, build_run_record


def _seed_team_and_agents(tmp_path: Path):
    from core.web.services import agent_directory_service, team_service
    from core.web.services.team_workflow import research_projects as research_project_service

    finder = agent_directory_service.create_agent_instance(
        display_name="T518 Finder",
        role_key="source_finder",
        created_by="t518",
    )
    extractor = agent_directory_service.create_agent_instance(
        display_name="T518 Extractor",
        role_key="source_extractor",
        created_by="t518",
    )
    mapper = agent_directory_service.create_agent_instance(
        display_name="T518 Mapper",
        role_key="source_relation_mapper",
        created_by="t518",
    )
    team = team_service.create_team(
        name="T518 Research Team",
        purpose="challenge-workflow-t518",
        members=[
            {"agentId": finder["agentId"], "role": "source_finder"},
            {"agentId": extractor["agentId"], "role": "source_extractor"},
            {"agentId": mapper["agentId"], "role": "source_relation_mapper"},
        ],
    )
    team_id = str(team.get("teamId") or team.get("id") or "")
    project = research_project_service.create_research_project(
        team_id,
        {
            "name": "T518 Project",
            "title": "T518 Project",
            "questionId": "SCI-096",
            "objective": "Deterministic three-node gate",
        },
    )
    active = research_project_service.get_active_research_project(team_id)
    project_id = str(active.get("projectId") or "")
    assert project_id
    _ = project
    return {
        "teamId": team_id,
        "projectId": project_id,
        "finderId": str(finder["agentId"]),
        "extractorId": str(extractor["agentId"]),
        "mapperId": str(mapper["agentId"]),
        "tmp": tmp_path,
    }


def _seed_run(store, *, team_id: str, project_id: str, agents: dict[str, str]) -> None:
    input_snapshot = {
        "teamId": team_id,
        "projectId": project_id,
        "questionId": "SCI-096",
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "researchBriefHash": "b" * 64,
        "datasetRefs": [],
        "metricContract": {},
        "constraintSnapshot": {},
        "competitionRuleRef": "rule",
        "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {},
        "researchObjectiveContract": {"question": "How do spike trains encode information?"},
        "sourcePolicy": {},
        "budgetPolicy": {
            "stageBudgets": {
                "knowledge_collection": {"tokens": 250000, "toolCalls": 300}
            }
        },
        "stopPolicy": {},
        "environmentSnapshotRef": "env-1",
        "modelRoutingPolicy": {},
        "evaluationContract": {},
        "agentBindingSnapshot": [
            {
                "snapshotId": "snap:run-t518:source_finding",
                "nodeId": "source_finding",
                "agentId": agents["finderId"],
                "roleKey": "source_finder",
            },
            {
                "snapshotId": "snap:run-t518:source_extraction",
                "nodeId": "source_extraction",
                "agentId": agents["extractorId"],
                "roleKey": "source_extractor",
            },
            {
                "snapshotId": "snap:run-t518:evidence_relations",
                "nodeId": "evidence_relations",
                "agentId": agents["mapperId"],
                "roleKey": "source_relation_mapper",
            },
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-12T00:00:00Z",
        "snapshotHash": "c" * 64,
    }
    record = build_run_record(
        run_id="run-t518",
        team_id=team_id,
        last_event_sequence=1,
        input_snapshot_hash="c" * 64,
        thread_id="run-t518",
    )
    record = record.__class__(
        **{
            **record.__dict__,
            "project_id": project_id,
            "question_id": "SCI-096",
            "input_snapshot_json": json.dumps(input_snapshot, ensure_ascii=False),
        }
    )

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id="run-t518",
                event_type="run_created",
                event_id="evt-created-run-t518",
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)


def _drive_until_node_succeeded(runtime, node_id: str, *, max_ticks: int = 80) -> None:
    for _ in range(max_ticks):
        attempt = runtime.store.latest_attempt("run-t518", node_id)
        if attempt is not None and attempt.status == "succeeded":
            return
        if attempt is not None and attempt.status in {
            "failed",
            "blocked",
            "cancelled",
            "reconciliation_required",
        }:
            raise AssertionError(
                f"{node_id} entered terminal status {attempt.status}: {attempt.problem_json}"
            )
        handled = runtime.run_workers_once(limit=8)
        if handled == 0:
            # Allow async settle / after_commit hooks a beat.
            import time

            time.sleep(0.05)
    attempt = runtime.store.latest_attempt("run-t518", node_id)
    raise AssertionError(
        f"{node_id} did not succeed; latest={None if attempt is None else attempt.status} "
        f"problem={None if attempt is None else attempt.problem_json}"
    )


def _ensure_session_context_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session submit fails closed without a resolvable dialogue context window."""
    from core.web.services import session_service

    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda conversation=None: {"limit": 65536, "source": "t518-stub"},
    )


def test_deterministic_composition_integration_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    import core.infrastructure.path_containment as path_containment

    monkeypatch.setattr(path_containment, "PROJECT_ROOT", tmp_path)
    _ensure_session_context_window(monkeypatch)
    stub_counters = install_fast_stage_writeback_llm_stub(monkeypatch)

    seeded = _seed_team_and_agents(tmp_path)
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
    )
    try:
        assert runtime.ports._agent_task_factory is None  # noqa: SLF001
        _seed_run(
            runtime.store,
            team_id=seeded["teamId"],
            project_id=seeded["projectId"],
            agents=seeded,
        )

        with server_operator_scope("u-1", roles=("operator",)):
            receipt = runtime.command_service.submit(
                CommandRequest(
                    command_id="cmd-t518",
                    run_id="run-t518",
                    team_id=seeded["teamId"],
                    command=WorkflowCommandKind.START_NODE,
                    node_id="source_finding",
                    expected_run_version=1,
                    idempotency_key="ui:t518-start",
                    payload={},
                    requested_by=ActorRef("user", "u-1"),
                    requested_at_ms=1_750_000_000_000,
                )
            )
        assert receipt.status == "accepted"

        _drive_until_node_succeeded(runtime, "source_finding")
        finding = runtime.store.latest_attempt("run-t518", "source_finding")
        assert finding is not None
        anchor = runtime.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(finding.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert anchor is not None
        anchor_json = json.loads(anchor[13])
        session_id = anchor_json["sessionId"]
        task_id = anchor_json["taskId"]
        turn_id = anchor_json["turnId"]
        assert session_id and task_id and turn_id

        from core.web.services import session_service

        detail = session_service.get_session_detail(
            session_id, message_limit=0, transcript_scope="none"
        )
        assert str(detail.get("id") or "") == session_id

        receipts = runtime.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT artifact_kind, canonical_ref_json, sha256, domain_revision "
                "FROM artifact_receipts WHERE run_id = ? AND node_run_id = ?",
                ("run-t518", finding.node_run_id),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(receipts) >= 1
        assert receipts[0][0] == "source_candidate_batch"
        ref_json = json.loads(receipts[0][1])
        assert ref_json.get("canonicalRef") or ref_json.get("ref")
        assert len(str(receipts[0][2])) == 64
        assert str(receipts[0][3]).strip()

        # Extraction preflight requires raw records; finding writeback materializes them.
        run_snap = json.loads(runtime.store.get_run("run-t518").input_snapshot_json)
        sc_run_id = str(run_snap.get("sourceCollectionRunId") or "")
        assert sc_run_id

        _drive_until_node_succeeded(runtime, "source_extraction")
        extraction = runtime.store.latest_attempt("run-t518", "source_extraction")
        assert extraction is not None
        assert extraction.binding_snapshot_id == "snap:run-t518:source_extraction"

        handoff = runtime.store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node(
                "run-t518", finding.node_run_id
            ),
            force_flush=True,
        ).result(timeout=10)
        assert handoff is not None and handoff[8] == "accepted"

        _drive_until_node_succeeded(runtime, "evidence_relations")
        relations = runtime.store.latest_attempt("run-t518", "evidence_relations")
        assert relations is not None and relations.status == "succeeded"
        assert int(stub_counters["writeback_calls"]) >= 3

        outbox = runtime.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_kind, status FROM outbox_actions WHERE run_id = ?",
                ("run-t518",),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert outbox
        # No permanent leased/dispatching leftovers for completed nodes.
        bad = [row for row in outbox if row[1] in {"leased", "dispatching"}]
        assert not bad, bad
        # Completed adapter/graph work for the three-node prefix must be terminal.
        for kind, status in outbox:
            if kind == "adapter_dispatch":
                assert status in {"succeeded", "cancelled", "failed"}, (kind, status)
    finally:
        runtime.close()


def test_legacy_injected_factory_chain_renamed_away() -> None:
    """The old no_fakes name must not claim production composition evidence."""
    import tests.test_research_workflow_integration_chain as mod

    assert not hasattr(mod, "test_full_chain_no_fakes")
    assert hasattr(mod, "test_full_chain_with_injected_task_factory")


def test_tool_dispatch_writeback_guard_fails_closed() -> None:
    """Missing required writeback remains a fail-closed session condition."""
    from core.web.services.session.signals_format import _required_tool_progress_missing
    from core.web.services.team_workflow.source_collection.stage_writeback import (
        writeback_source_collection_stage_session_task,
    )
    from core.web.services.team_workflow.source_collection_stage_tasks import (
        source_collection_stage_task_writeback_contract,
    )

    assert callable(writeback_source_collection_stage_session_task)
    contract = source_collection_stage_task_writeback_contract(
        "team-canary",
        "run-canary",
        "task-canary",
        stage_id="finding",
        agent_id="agent-canary",
        agent_role="source_finder",
        schema_version=1,
    )
    assert contract.get("contractKind") == "source_collection_stage_session_task_writeback"
    required_tool = str(contract.get("toolName") or "").strip()
    assert required_tool == "source_collection_stage_writeback_tool"

    missing = _required_tool_progress_missing(
        {
            "raw_output": "done without tools",
            "tool_call_count": 0,
        },
        require_tool_progress=True,
        required_tool_names=[required_tool],
        observed_tool_names=set(),
    )
    assert missing is True

    present = _required_tool_progress_missing(
        {
            "raw_output": "done with writeback",
            "tool_call_count": 1,
        },
        require_tool_progress=True,
        required_tool_names=[required_tool],
        observed_tool_names={required_tool},
    )
    assert present is False
