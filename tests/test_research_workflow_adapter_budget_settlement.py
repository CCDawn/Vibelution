"""Production-shaped adapter settlement keeps provider usage authoritative."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import (
    ActionRegistry,
)
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    AgentActionAdapter,
)
from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
    record_budget_usage,
    reserve_budget_authority,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_factory import (
    budget_policy_hash_from_input_snapshot,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests.test_research_workflow_budget_ordering import _action, _seed


class _ProviderUsagePorts(FakeDomainPorts):
    def __init__(self, harness: CommandHarness, input_snapshot: dict[str, Any]) -> None:
        super().__init__()
        self._harness = harness
        self._input_snapshot = input_snapshot
        self._reservation_by_action: dict[str, dict[str, Any]] = {}

    def reserve_budget(
        self, *, action: PendingAction, estimate_tokens: int
    ) -> dict[str, Any]:
        self.calls.append("reserve_budget")
        self.reservations.append(action.action_id)
        reservation = reserve_budget_authority(
            self._harness.store,
            action=action,
            estimate_tokens=estimate_tokens,
            input_snapshot=self._input_snapshot,
        )
        self._reservation_by_action[action.action_id] = reservation
        return reservation

    def execute_agent_turn(self, *, action: PendingAction, handle: Any):
        reservation = self._reservation_by_action[action.action_id]
        common = {
            "run_id": action.run_id,
            "node_run_id": action.node_run_id,
            "reservation_id": reservation["reservationId"],
        }
        record_budget_usage(
            self._harness.store,
            **common,
            invocation_id="invocation-1",
            input_tokens=6_000,
            output_tokens=4_965,
        )
        record_budget_usage(
            self._harness.store,
            **common,
            invocation_id="invocation-2",
            input_tokens=8_000,
            output_tokens=6_266,
        )
        return super().execute_agent_turn(action=action, handle=handle)


def test_adapter_settlement_preserves_recorded_provider_invocations(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        input_snapshot = {
            "budgetPolicy": {
                "tokens": 4_000_000,
                "toolCalls": 300,
                "wallClockSeconds": 21_600,
                "autoRetries": 2,
            }
        }
        policy_hash = budget_policy_hash_from_input_snapshot(input_snapshot)
        action = replace(
            _action(
                action_id="act-provider-usage",
                node_id="source_finding",
                actor=ActorKind.AGENT,
                action_kind="start_agent_task",
            ),
            budget_policy_hash=policy_hash,
        )
        _seed(harness, action, "source_finding")
        ports = _ProviderUsagePorts(harness, input_snapshot)
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: ("source_extraction",),
        )

        assert worker.run_once() == 1

        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status, policy_hash, settled_json "
                "FROM budget_receipts WHERE run_id = ? AND node_run_id = ?",
                (action.run_id, action.node_run_id),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None
        settled = json.loads(row[2])
        assert row[0] == "settled"
        assert row[1] == policy_hash
        assert row[1]
        assert set(settled["invocations"]) == {"invocation-1", "invocation-2"}
        assert settled["usage"]["tokens"] == 25_231
        assert settled["usage"]["inputTokens"] == 14_000
        assert settled["usage"]["outputTokens"] == 11_231
        assert settled["usage"]["estimate_tokens"] == 2_000_000
    finally:
        harness.close()
