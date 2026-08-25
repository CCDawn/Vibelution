from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from core.research.workflow.checkpoint_store import (
    CheckpointResetPortError,
    list_checkpoint_thread_ids,
    list_team_scoped_checkpoints,
    prepare_checkpoint_reset_stage,
    purge_checkpoint_reset_stage,
    restore_checkpoint_reset_stage,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as receipt_registry,
)


def _checkpoint(path: Path, *, thread_id: str, team_id: str, checkpoint_id: str) -> None:
    with SqliteSaver.from_conn_string(str(path)) as saver:
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        saver.put(
            config,
            {
                "v": 1,
                "id": checkpoint_id,
                "ts": "2026-08-24T00:00:00+00:00",
                "channel_values": {
                    "team_id": team_id,
                    "run_id": thread_id,
                },
                "channel_versions": {},
                "versions_seen": {},
            },
            {"source": "input", "step": 0, "writes": {}},
            {},
        )


def _receipt(kind: str, *, question_id: str = "SCI-096", run_id: str = "run-096") -> dict:
    receipt_id = f"receipt-{kind}-{run_id}"
    node_run_id = f"node-run-{kind}-{run_id}"
    scope = {
        "questionId": question_id,
        "workflowRunId": run_id,
        "sessionId": f"session-{kind}-{run_id}",
        "taskId": f"task-{kind}-{run_id}",
        "turnId": f"turn-{kind}-{run_id}",
        "formalNodeId": f"node-{kind}",
        "formalNodeRunId": node_run_id,
        "modelPolicySha256": "a" * 64,
    }
    return ModelInvocationReceipt.from_invocation(
        receipt_id=receipt_id,
        run_id=run_id,
        node_run_id=node_run_id,
        scope=scope,
        provider="flash",
        model="flash-dev",
        requested_model="flash-dev",
        request_content={"kind": kind},
        response_content={"kind": kind},
        started_at_ms=100,
        finished_at_ms=120,
        token_usage={"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        metadata={"outcomeKinds": [kind]},
        evidence_locator={
            **scope,
            "kind": "turn_journal",
            "outputRef": f"session:{scope['sessionId']}/turn:{scope['turnId']}",
            "outputSha256": "b" * 64,
            "receiptId": receipt_id,
            "invocationId": f"invocation-{kind}-{run_id}",
            "attempt": 1,
        },
    ).to_dict()


def test_checkpoint_reset_stage_is_scoped_and_restorable(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    _checkpoint(path, thread_id="run-research", team_id="research-team", checkpoint_id="ck-research")
    _checkpoint(path, thread_id="run-other", team_id="other-team", checkpoint_id="ck-other")
    authority = {
        "run-research": {"teamId": "research-team", "runId": "run-research"},
        "run-other": {"teamId": "other-team", "runId": "run-other"},
    }

    assert list_checkpoint_thread_ids(path) == ["run-other", "run-research"]

    rows = list_team_scoped_checkpoints(
        "research-team", checkpoint_path=path, scope_authority=authority
    )
    assert [row["checkpointId"] for row in rows] == ["ck-research"]

    stage = prepare_checkpoint_reset_stage(
        "research-team",
        "reset-checkpoint-1",
        checkpoint_path=path,
        scope_authority=authority,
    )
    assert stage["recordCount"] == 1
    assert "rawRows" not in stage
    assert "checkpoint" not in stage.get("records", [])

    purged = purge_checkpoint_reset_stage(stage, checkpoint_path=path)
    assert purged["ok"] is True
    assert list_team_scoped_checkpoints(
        "research-team", checkpoint_path=path, scope_authority=authority
    ) == []
    assert [row["checkpointId"] for row in list_team_scoped_checkpoints(
        "other-team", checkpoint_path=path, scope_authority=authority
    )] == ["ck-other"]

    restored = restore_checkpoint_reset_stage(stage, checkpoint_path=path)
    assert restored["ok"] is True
    assert [row["checkpointId"] for row in list_team_scoped_checkpoints(
        "research-team", checkpoint_path=path, scope_authority=authority
    )] == ["ck-research"]


def test_checkpoint_reset_rejects_unmapped_or_changed_candidates(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    _checkpoint(path, thread_id="run-a", team_id="research-team", checkpoint_id="ck-a")
    authority = {"run-a": {"teamId": "research-team", "runId": "run-a"}}
    with pytest.raises(CheckpointResetPortError, match="no scope authority"):
        list_team_scoped_checkpoints(
            "research-team",
            checkpoint_path=path,
            scope_authority={"run-other": {"teamId": "other-team", "runId": "run-other"}},
        )

    stage = prepare_checkpoint_reset_stage(
        "research-team", "reset-checkpoint-2", checkpoint_path=path, scope_authority=authority
    )
    _checkpoint(path, thread_id="run-a", team_id="research-team", checkpoint_id="ck-new")
    with pytest.raises(CheckpointResetPortError, match="changed after stage"):
        purge_checkpoint_reset_stage(stage, checkpoint_path=path)


def test_receipt_reset_stage_is_scoped_and_restorable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        receipt_registry,
        "resolve_team_program_root",
        lambda _team_id: tmp_path,
    )
    authority = [
        {"teamId": "research-team", "questionId": "SCI-096", "workflowRunId": "run-096"}
    ]
    receipt_registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=[_receipt("candidate")],
    )
    rows = receipt_registry.list_team_scoped_model_invocation_receipts(
        "research-team", scope_authority=authority
    )
    assert [row["receiptId"] for row in rows] == ["receipt-candidate-run-096"]

    stage = receipt_registry.prepare_model_invocation_receipt_reset_stage(
        "research-team", "reset-receipt-1", scope_authority=authority
    )
    assert stage["storeCount"] == 1
    assert "rawBytes" not in json.dumps(stage)
    receipt_registry.purge_model_invocation_receipt_reset_stage(stage)
    assert receipt_registry.list_team_scoped_model_invocation_receipts(
        "research-team", scope_authority=authority
    ) == []

    restored = receipt_registry.restore_model_invocation_receipt_reset_stage(stage)
    assert restored["ok"] is True
    assert [row["receiptId"] for row in receipt_registry.list_team_scoped_model_invocation_receipts(
        "research-team", scope_authority=authority
    )] == ["receipt-candidate-run-096"]


def test_receipt_reset_rejects_cross_team_store_and_reset_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(receipt_registry, "resolve_team_program_root", lambda _team_id: tmp_path)
    receipt_registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=[_receipt("candidate")],
    )
    path = receipt_registry._path("research-team", "SCI-096", "run-096")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["teamId"] = "other-team"
    path.write_text(json.dumps(payload), encoding="utf-8")
    authority = [
        {"teamId": "research-team", "questionId": "SCI-096", "workflowRunId": "run-096"}
    ]
    with pytest.raises(receipt_registry.ReceiptResetPortError, match="another team"):
        receipt_registry.list_team_scoped_model_invocation_receipts(
            "research-team", scope_authority=authority
        )

    # Rebuild a valid store and prove the stage cannot be replayed under a
    # different reset id.
    path.unlink()
    receipt_registry.register_question_model_invocation_receipts(
        "research-team",
        question_id="SCI-096",
        workflow_run_id="run-096",
        receipts=[_receipt("candidate")],
    )
    stage = receipt_registry.prepare_model_invocation_receipt_reset_stage(
        "research-team", "reset-receipt-2", scope_authority=authority
    )
    with pytest.raises(receipt_registry.ReceiptResetPortError, match="resetId"):
        receipt_registry.purge_model_invocation_receipt_reset_stage(
            stage, reset_id="reset-receipt-other"
        )
