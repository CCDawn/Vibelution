"""Explicit read-only local-operator graph response contracts."""
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlatformGraphNode(BaseModel):
    id: str
    type: str
    label: str
    summary: str = ""
    status: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    responsibilityQuestion: str = ""
    visual: dict[str, Any] = Field(default_factory=dict)
    childNodeIds: list[str] = Field(default_factory=list)
    contentItems: list[dict[str, Any]] = Field(default_factory=list)


class PlatformGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    label: str
    weight: float = 1.0
    metadata: dict[str, Any]


class PlatformGraphTopic(BaseModel):
    id: str
    label: str
    groupingBasis: Literal["official_target_domain", "tag", "knowledge_base", "title_keywords"]
    nodeIds: list[str]


class PlatformGraphSummary(BaseModel):
    nodeCount: int
    edgeCount: int
    totalNodeCount: int
    totalEdgeCount: int
    topicsCount: int
    truncated: bool
    nodeTypeCounts: dict[str, int]
    edgeTypeCounts: dict[str, int]
    elapsedMs: float


class PlatformGraphFilters(BaseModel):
    limit: int
    knowledgeBaseId: str = ""


class PlatformGraphBoundary(BaseModel):
    readOnly: Literal[True]
    fullContentIncluded: Literal[False]
    canEditGraph: Literal[False]
    canApplyKnowledge: Literal[False]
    accessAuthority: Literal["local_operator"]
    excludedPrivateMemory: Literal[True]
    contentAccess: Literal["metadata_only"]
    honorsKnowledgeLifecycle: Literal[True]


class PlatformKnowledgeGraphResponse(BaseModel):
    schemaVersion: int
    mode: Literal["read_only_platform_knowledge_graph"]
    agentId: Literal[""]
    summary: PlatformGraphSummary
    filters: PlatformGraphFilters
    operatingBoundary: PlatformGraphBoundary
    topics: list[PlatformGraphTopic]
    nodes: list[PlatformGraphNode]
    edges: list[PlatformGraphEdge]


class PlatformKnowledgeGraphDetailResponse(BaseModel):
    schemaVersion: int
    mode: Literal["read_only_platform_knowledge_graph_node_detail"]
    agentId: Literal[""]
    nodeId: str
    node: PlatformGraphNode
    relatedNodes: list[PlatformGraphNode]
    edges: list[PlatformGraphEdge]
    operatingBoundary: PlatformGraphBoundary
    summaryCounts: "PlatformGraphDetailCounts"


class PlatformGraphDetailCounts(BaseModel):
    relatedNodeCount: int
    totalRelatedNodeCount: int
    edgeCount: int
    totalEdgeCount: int
    limit: int
    truncated: bool
