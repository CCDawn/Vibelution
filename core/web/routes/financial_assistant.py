"""Typed financial entry routes; native services remain lifecycle authorities."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.services import financial_assistant_service as service
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    AgentStateConflictError,
)

router = APIRouter(tags=["financial-assistant"])


class FinancialAssistantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agentId: str
    agentCode: str
    displayName: str
    status: str
    setupStatus: str
    directSessionId: str
    knowledgeBaseId: str
    knowledgeReadable: bool
    modelStatus: str
    reportStatus: str
    marketDataStatus: str
    newsDelegationStatus: str
    privateLedgerStatus: str
    tradingEnabled: bool


class FinancialAssistantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: str = Field(default="炒股智能体", min_length=1, max_length=80)


class FinancialAssistantCreateResponse(BaseModel):
    created: bool
    assistant: FinancialAssistantResponse


@router.get("/financial-assistants", response_model=list[FinancialAssistantResponse])
def financial_assistant_list() -> list[dict]:
    return service.list_financial_assistants()


@router.post("/financial-assistants", response_model=FinancialAssistantCreateResponse)
def financial_assistant_create(payload: FinancialAssistantCreateRequest) -> dict:
    try:
        return service.create_financial_assistant(payload.displayName)
    except AgentStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentDirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
