"""Shared harness for T4 graph runner tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.research.workflow.challenge_cup_runtime import (
    ChallengeCupGraphCoordinator,
    GraphDispatch,
)
from core.research.workflow.contracts import ExecutionReceipt
from core.web.services.team_workflow.research_runtime.checkpoint_fork_worker import (
    CheckpointForkWorker,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)

from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS

NODE_ORDER = [
    "source_finding",
    "source_extraction",
    "evidence_relations",
    "knowledge_ingestion",
    "knowledge_handoff",
    "hypothesis_design",
    "protocol_design",
    "protocol_review",
    "protocol_freeze",
    "smoke_gate",
    "controlled_run",
    "result_evaluation",
    "iteration_decision",
    "version_governance",
    "candidate_promotion",
    "result_package",
]


class GraphHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.commands = CommandHarness(tmp_path / "ledger.sqlite3")
        self.coordinator = ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite")
        self.worker = GraphDispatchWorker(
            store=self.commands.store,
            coordinator=self.coordinator,
            owner_id="graph-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 1000,
        )
        self.fork_worker = CheckpointForkWorker(
            store=self.commands.store,
            coordinator=self.coordinator,
            owner_id="checkpoint-fork-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 1000,
        )

    def close(self) -> None:
        self.commands.close()

    def seed(self, run_id: str = "run-test", **overrides: Any) -> None:
        self.commands.seed_run(run_id=run_id, **overrides)

    def enqueue_graph_dispatch(
        self,
        run_id: str,
        node_id: str,
        attempt: int,
        *,
        dispatch_kind: str = "start",
        command_id: str = "cmd-driver",
        input_snapshot_hash: str = "a" * 64,
        workflow_version_id: str = "challenge-cup-research-v2.1.0",
        team_id: str = "research-team",
        receipt: ExecutionReceipt | None = None,
        idempotency_key: str | None = None,
        state_update: dict | None = None,
    ) -> None:
        dispatch = GraphDispatch(
            action_id="act-driver",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-{node_id}-a{attempt}",
            node_id=node_id,
            attempt=attempt,
            dispatch_kind=dispatch_kind,
            input_snapshot_hash=input_snapshot_hash,
            workflow_version_id=workflow_version_id,
            team_id=team_id,
            receipt=receipt,
            state_update=state_update,
        )
        payload = dispatch.to_payload()

        def mutate(uow):
            if uow.repository.get_command(command_id) is None:
                from tests._support.workflow_ledger_helpers import build_command_record

                uow.repository.insert_command(
                    build_command_record(
                        command_id=command_id,
                        run_id=run_id,
                        idempotency_key=f"cmd:{command_id}:{node_id}:{attempt}",
                        node_id=node_id,
                    )
                )
            if uow.repository.get_attempt(dispatch.node_run_id) is None:
                from tests._support.workflow_ledger_helpers import build_attempt_record

                uow.repository.insert_attempt(
                    build_attempt_record(
                        node_run_id=dispatch.node_run_id,
                        run_id=run_id,
                        node_id=node_id,
                        attempt=attempt,
                        status="starting",
                        command_id=command_id,
                        input_snapshot_hash=input_snapshot_hash,
                        started_at_ms=FIXED_NOW_MS,
                    )
                )
            uow.repository.insert_outbox(
                _graph_outbox(
                    run_id=run_id,
                    command_id=command_id,
                    node_run_id=dispatch.node_run_id,
                    payload=payload,
                    now_ms=FIXED_NOW_MS,
                    idempotency_key=idempotency_key,
                )
            )

        self.commands.store.submit(mutate, force_flush=True).result(timeout=10)

    def latest_adapter_pending(self, run_id: str = "run-test"):
        records = self.commands.store.list_pending_outbox(run_id)
        for record in records:
            if record.action_kind == "adapter_dispatch":
                return record
        return None

    def consume_adapter(self, action_id: str) -> None:
        """测试用：模拟 adapter 已消费（把 adapter_dispatch 标记为 succeeded）。"""

        def mutate(uow):
            uow.repository.execute(
                "UPDATE outbox_actions SET status = 'succeeded' WHERE action_id = ?",
                (action_id,),
            )

        self.commands.store.submit(mutate, force_flush=True).result(timeout=10)

    def resume(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
        outcome: str = "succeeded",
        action_id: str | None = None,
        receipt_id: str = "rcpt-1",
        branch_decision: str | None = None,
    ) -> None:
        action_id = action_id or (
            "act-"
            + __import__("hashlib")
            .sha256(f"{run_id}:{node_id}:{attempt}".encode())
            .hexdigest()[:16]
        )
        receipt = ExecutionReceipt(
            action_id=action_id,
            node_run_id=f"nr-{run_id}-{node_id}-a{attempt}",
            outcome=outcome,
            artifact_receipt_ids=(),
            execution_anchor_id=None,
            budget_receipt_id=None,
            problem=None,
            completed_at_ms=FIXED_NOW_MS,
        )
        key = f"resume:{action_id}"
        if self._outbox_key_exists(key):
            return
        self.enqueue_graph_dispatch(
            run_id,
            node_id,
            attempt,
            dispatch_kind="resume_action",
            receipt=receipt,
            idempotency_key=key,
            state_update={"branch_decision": branch_decision} if branch_decision else None,
        )

    def _outbox_key_exists(self, idempotency_key: str) -> bool:
        def query(uow):
            rows = uow.repository.execute(
                "SELECT 1 FROM outbox_actions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchall()
            return bool(rows)

        return bool(self.commands.store.submit(query, force_flush=True).result(timeout=10))


def _graph_outbox(*, run_id: str, command_id: str, node_run_id: str, payload: dict, now_ms: int, idempotency_key: str | None):
    import json

    from core.research.workflow.ledger import OutboxRecord

    key = idempotency_key or f"graph:{node_run_id}:{payload.get('dispatchKind')}"
    action_id = f"act-{key.replace(':', '-')[:48]}"
    return OutboxRecord(
        action_id=action_id,
        run_id=run_id,
        command_id=command_id,
        node_run_id=node_run_id,
        action_kind="graph_dispatch",
        idempotency_key=idempotency_key or f"graph:{node_run_id}:{payload.get('dispatchKind')}",
        payload_json=json.dumps(payload),
        status="pending",
        attempt_count=0,
        available_at_ms=now_ms,
        lease_owner=None,
        lease_expires_at_ms=None,
        last_problem_json=None,
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )
