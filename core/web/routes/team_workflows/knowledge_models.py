"""Public contracts for team workflow knowledge routes.

Ingest/complete payloads still evolve across sync vs background shapes.
Dual-shape endpoints only require identifiers that exist on every
successful shape. Routes must use response_model_exclude_unset=True so
missing optional fields stay absent instead of being filled with defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KnowledgeIngestionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""


class KnowledgeIngestionPrecheckResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class KnowledgeCollectionExtractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    runId: str = ""


class KnowledgeCollectionIngestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class KnowledgeCollectionCompleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class CoordinationStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    teamId: str = ""


class CandidateGraphBuildResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class CandidateSourceExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class PaperNoteDraftResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
