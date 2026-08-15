"""Public JSON envelopes for research workflow runtime routes.

These snapshots and action receipts still evolve. Keep declared fields empty
so FastAPI cannot inject defaults or drop unknown nested keys. JSON routes
must use response_model_exclude_unset=True. SSE stays on StreamingResponse.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ResearchRuntimeJsonResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ResearchWorkflowDefinitionResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowRunListResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowLaunchOptionsResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowEffectiveBindingsResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowBindingConfigResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowCreateRunResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowRunSnapshotResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowNodeDetailResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowEventPageResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowHandoffListResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowLedgerResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowBudgetResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowHypothesisListResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowCampaignListResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowEvaluationResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowHandoffDetailResponse(ResearchRuntimeJsonResponse):
    pass


class ResearchWorkflowCommandReceiptResponse(ResearchRuntimeJsonResponse):
    pass
