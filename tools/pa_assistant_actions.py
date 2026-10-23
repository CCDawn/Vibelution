"""Canonical assistant preferences through their existing owning services."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Preferences(Arguments):
    characterId: Literal["dafeiyu", "xiaoluo"] | None = None
    showStatus: bool | None = None
    showTitles: bool | None = None
    showCompletion: bool | None = None
    idleMessage: str | None = Field(default=None, max_length=48)


class SettingsUpdate(Arguments):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    preferences: Preferences | None = None


class ModelSet(Arguments):
    model_id: str = Field(min_length=1, max_length=200)


class DialogueUpdate(Arguments):
    speakingInitiative: Literal["restrained", "natural", "talkative"] | None = None
    questionInitiative: Literal["few", "natural", "proactive"] | None = None
    preferenceProposalMode: Literal["ask_first", "manual_only"] | None = None


_ACTIONS = {
    "assistant_settings": (Arguments, "读取当前个人助理名称、外观、提示开关和对话模型。", False),
    "assistant_settings_update": (SettingsUpdate, "调整助理名称、鲸鱼/小萝外观、状态/标题/完成提示和空闲提示；未指定字段保持原值。", False),
    "assistant_model_set": (ModelSet, "给当前个人助理切换已配置且可用的对话模型；不改变其他Agent。", False),
    "dialogue_settings": (Arguments, "读取当前助理的主动说话、提问和偏好建议设置。", False),
    "dialogue_settings_update": (DialogueUpdate, "调整助理主动说话、提问和偏好建议程度；仅作用于当前助理，未指定字段保持原值。", False),
}
_DIALOGUE_FIELDS = ("speakingInitiative", "questionInitiative", "preferenceProposalMode")


def contracts() -> dict:
    return {name: {"action": name, "description": item[1], "governed": item[2],
                   "parameters": item[0].model_json_schema()} for name, item in _ACTIONS.items()}


def _settings() -> dict:
    from core.web.services import personal_assistant_service as owner

    settings = owner.get_personal_assistant_settings().get("settings")
    if not settings:
        raise ValueError("个人助理设置未就绪。")
    model = settings.get("model") or {}
    return {"displayName": settings.get("displayName", ""),
            "preferences": {key: value for key, value in (settings.get("preferences") or {}).items()
                            if key in owner.PREFERENCES_FIELDS},
            "modelId": model.get("currentModelId", "")}


def _patch(args: BaseModel) -> dict:
    values = args.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise ValueError("至少提供一个非空的设置字段。")
    return values


def execute(action: str, parameters: dict, runtime: dict, *, governed: bool = False) -> dict:
    from core.web.services import personal_assistant_service as owner

    contract = _ACTIONS.get(action)
    if not contract:
        raise ValueError("未知的助理设置操作。")
    args = contract[0].model_validate(parameters)
    if action in {"assistant_settings", "assistant_settings_update", "assistant_model_set"}:
        expected = None
        if action == "assistant_settings_update":
            expected = _patch(args)
            if "preferences" in expected:
                expected["preferences"] = _patch(args.preferences)
            owner.update_personal_assistant_settings(**expected)
        elif action == "assistant_model_set":
            owner.update_personal_assistant_model(args.model_id)
        observed = _settings()
        verified = True
        if expected:
            verified = ("display_name" not in expected or observed["displayName"] == expected["display_name"])
            verified = verified and all(observed["preferences"].get(key) == value
                                       for key, value in expected.get("preferences", {}).items())
        if action == "assistant_model_set":
            verified = observed["modelId"] == args.model_id
        return {"ok": verified, "verified": verified, "status": "completed" if verified else "unknown", **observed}
    from core.web.services import virtual_human_life_service as dialogue

    agent_id = runtime["agentId"]
    native = dialogue.get_virtual_human_life_service()
    # The native endpoint is a full replacement. Hold its same Agent lock over
    # read/merge/write so a partial tool patch cannot reset unrelated choices.
    with native._lock_for(agent_id):
        current = dialogue.virtual_human_dialogue_settings(agent_id)
        patch = _patch(args) if action == "dialogue_settings_update" else {}
        if patch:
            merged = {key: current[key] for key in _DIALOGUE_FIELDS if key in current}
            dialogue.update_virtual_human_dialogue_settings(agent_id, settings={**merged, **patch})
        observed = dialogue.virtual_human_dialogue_settings(agent_id)
    verified = all(observed.get(key) == value for key, value in patch.items())
    return {"ok": verified, "verified": verified, "status": "completed" if verified else "unknown",
            "agentId": agent_id, **{key: observed.get(key) for key in _DIALOGUE_FIELDS}}
