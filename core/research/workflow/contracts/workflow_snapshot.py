"""ResearchWorkflowSnapshot contract — formal server read projection (spec 11.3).

UI-only state (selected node, panel, viewport, hover, dialog, URL) is forbidden.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .workflow_command import CommandOffer


@dataclass(frozen=True, slots=True)
class ResearchWorkflowSnapshot:
    run: Mapping[str, Any]
    definition: Mapping[str, Any]
    node_attempts: Mapping[str, tuple[Mapping[str, Any], ...]]
    active_node_ids: tuple[str, ...]
    pending_human_tasks: tuple[Mapping[str, Any], ...]
    command_offers: tuple[CommandOffer, ...]
    handoff_summary: Mapping[str, Any]
    agent_binding_summary: Mapping[str, Any]
    budget_summary: Mapping[str, Any]
    latest_event_sequence: int
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": dict(self.run),
            "definition": dict(self.definition),
            "nodeAttempts": {
                node_id: [dict(item) for item in attempts]
                for node_id, attempts in self.node_attempts.items()
            },
            "activeNodeIds": list(self.active_node_ids),
            "pendingHumanTasks": [dict(item) for item in self.pending_human_tasks],
            "commandOffers": [offer.to_dict() for offer in self.command_offers],
            "handoffSummary": dict(self.handoff_summary),
            "agentBindingSummary": dict(self.agent_binding_summary),
            "budgetSummary": dict(self.budget_summary),
            "latestEventSequence": int(self.latest_event_sequence),
            "generatedAt": self.generated_at,
        }
