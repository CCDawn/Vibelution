"""Canonical Node → Agent task adapter registry (T5.1-1).

Single map for production RealDomainPorts and legacy agent_node_execution.
Human/System nodes are intentionally absent: they use other adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.research.workflow.contracts.research_team_role_contract import (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
)
from core.research.workflow.definition import node_by_id

AdapterFamily = Literal["source_collection", "research_project"]


@dataclass(frozen=True)
class AgentTaskAdapterSpec:
    node_id: str
    family: AdapterFamily
    # source_collection: stageId; research_project: taskKind
    task_key: str
    role_key: str = ""
    owner_type: Literal["product_agent", "system_capability", ""] = ""
    owner_id: str = ""
    canonical_role_key: str = ""


SOURCE_NODE_TASKS: dict[str, tuple[str, str]] = {
    "source_finding": ("finding", "source_finder"),
    "source_extraction": ("extraction", "source_extractor"),
    "evidence_relations": ("relations", "source_relation_mapper"),
    "knowledge_ingestion": ("ingestion", "source_ingestor"),
}

PROJECT_NODE_TASKS: dict[str, str] = {
    "hypothesis_design": "hypothesis_design",
    "protocol_design": "experiment_design",
    "protocol_review": "protocol_review",
    "result_evaluation": "experiment_evidence_review",
    "iteration_decision": "iteration_decision",
    "version_governance": "version_governance",
}


def resolve_agent_task_adapter(node_id: str) -> AgentTaskAdapterSpec | None:
    source = SOURCE_NODE_TASKS.get(node_id)
    if source is not None:
        stage_id, role_key = source
        owner = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.resolve_role_owner(role_key)
        return AgentTaskAdapterSpec(
            node_id=node_id,
            family="source_collection",
            task_key=stage_id,
            role_key=role_key,
            owner_type=owner[0] if owner else "",
            owner_id=owner[1] if owner else "",
            canonical_role_key=(
                owner[1] if owner is not None and owner[0] == "product_agent" else ""
            ),
        )
    task_kind = PROJECT_NODE_TASKS.get(node_id)
    if task_kind is not None:
        node = node_by_id().get(node_id)
        observed_role = str(node.primaryRoleKey if node is not None else "")
        owner = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.resolve_role_owner(observed_role)
        return AgentTaskAdapterSpec(
            node_id=node_id,
            family="research_project",
            task_key=task_kind,
            owner_type=owner[0] if owner else "",
            owner_id=owner[1] if owner else "",
            canonical_role_key=(
                owner[1] if owner is not None and owner[0] == "product_agent" else ""
            ),
        )
    return None


def all_agent_task_adapter_node_ids() -> tuple[str, ...]:
    return tuple(sorted({*SOURCE_NODE_TASKS, *PROJECT_NODE_TASKS}))
