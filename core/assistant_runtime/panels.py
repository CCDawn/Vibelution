from typing import Annotated, Literal, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.web.routes.personal_assistant import SettingsUpdateRequest, ModelUpdateRequest
from core.web.routes.personal_assistant_affairs import PersonalAffairDueRequest
from core.web.routes.virtual_human_life_models import VirtualHumanDialogueSettingsRequest


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Read(Request):
    operation: Literal["panelSettings", "panelDialogue", "panelProposals"]


class AffairsList(Request):
    operation: Literal["panelAffairs"]
    kind: Literal["", "todo", "schedule", "goal"] = ""
    status: Literal["", "open", "done", "cancelled"] = ""


class AffairAddPayload(Request):
    kind: Literal["todo", "schedule", "goal"] = "todo"
    title: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=600)
    dueAt: str = Field(default="", max_length=40)


class AffairsAdd(Request):
    operation: Literal["panelAffairAdd"]
    payload: AffairAddPayload


class AffairsAction(Request):
    operation: Literal["panelAffairComplete", "panelAffairCancel", "panelAffairReopen"]
    itemId: str = Field(min_length=1, max_length=160)


class AffairsDue(Request):
    operation: Literal["panelAffairDue"]
    itemId: str = Field(min_length=1, max_length=160)
    payload: PersonalAffairDueRequest


class DialogueUpdate(Request):
    operation: Literal["panelDialogueUpdate"]
    payload: VirtualHumanDialogueSettingsRequest


class ProposalDecision(Request):
    operation: Literal["panelProposalAccept", "panelProposalReject"]
    proposalId: str = Field(min_length=1, max_length=160)


class SettingsUpdate(Request):
    operation: Literal["panelSettingsUpdate"]
    payload: SettingsUpdateRequest


class ModelUpdate(Request):
    operation: Literal["panelModelUpdate"]
    payload: ModelUpdateRequest


PanelRequest = Annotated[Union[Read, AffairsList, AffairsAdd, AffairsAction, AffairsDue,
                               DialogueUpdate, ProposalDecision, SettingsUpdate, ModelUpdate],
                         Field(discriminator="operation")]


def panel_router(native) -> APIRouter:
    """Fixed resident identity and explicitly enumerated UI operations."""
    router = APIRouter()

    @router.post("/api/assistant/panels")
    def panels(request: PanelRequest):
        identity = native.identity().get("assistant") or {}
        agent_id = identity.get("agentId")
        pinned = getattr(native, "assistant", None)
        if (not isinstance(agent_id, str) or not agent_id or not isinstance(pinned, dict)
                or agent_id != pinned.get("agentId")
                or identity.get("directSessionId") != pinned.get("directSessionId")):
            raise HTTPException(503, detail="Assistant identity unavailable")
        from core.web.services import personal_assistant_service as assistant
        from core.web.services import personal_affairs_service as affairs
        from core.web.services import virtual_human_life_service as dialogue
        op = request.operation
        try:
            if op == "panelSettings":
                return assistant.get_personal_assistant_settings()
            if op == "panelSettingsUpdate":
                p = request.payload
                return assistant.update_personal_assistant_settings(display_name=p.displayName,
                    preferences=p.preferences.model_dump(exclude_none=True) if p.preferences else None)
            if op == "panelModelUpdate":
                return assistant.update_personal_assistant_model(request.payload.modelId)
            if op == "panelDialogue":
                return dialogue.virtual_human_dialogue_settings(agent_id)
            if op == "panelDialogueUpdate":
                # Partial patches must not reset unrelated fields or race another writer.
                from tools.pa_assistant_actions import execute
                execute("dialogue_settings_update", request.payload.model_dump(exclude_none=True), {"agentId": agent_id})
                return dialogue.virtual_human_dialogue_settings(agent_id)
            if op == "panelProposals":
                return dialogue.virtual_human_preference_proposals(agent_id)
            if op == "panelProposalAccept":
                return dialogue.accept_virtual_human_preference_proposal(agent_id, proposal_id=request.proposalId)
            if op == "panelProposalReject":
                return dialogue.reject_virtual_human_preference_proposal(agent_id, proposal_id=request.proposalId)
            service = affairs.get_personal_affairs_service()
            if op == "panelAffairs":
                return service.list_items(agent_id, kind=request.kind, status=request.status)
            if op == "panelAffairAdd":
                p = request.payload
                item = service.add_item(agent_id, kind=p.kind, title=p.title, note=p.note,
                                        due_at=p.dueAt)
            elif op == "panelAffairDue":
                item = service.set_due(agent_id, item_id=request.itemId, due_at=request.payload.dueAt)
            else:
                action = {"panelAffairComplete": service.complete_item, "panelAffairCancel": service.cancel_item,
                          "panelAffairReopen": service.reopen_item}[op]
                item = action(agent_id, item_id=request.itemId)
            return {"agentId": agent_id, "item": item}
        except Exception:
            # Native exceptions may contain private paths or content.
            raise HTTPException(422, detail="Assistant panel operation failed") from None

    return router
