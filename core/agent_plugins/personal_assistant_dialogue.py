"""Prompt-only dialogue preferences for the canonical personal assistant."""

from __future__ import annotations

from typing import Any


_SPEAKING = {
    "restrained": "表达克制，简短回应，避免不必要的展开。",
    "natural": "表达自然，按任务需要给出适量说明。",
    "talkative": "表达更充分，可适度补充相关解释，避免无关扩展。",
}
_QUESTIONS = {
    "few": "少提问题；仅在缺少会阻止完成任务的必要信息时询问。信息足够就直接完成；不要在末尾追加‘要不要我……’、‘需要我继续吗’等可选邀约或无必要的追问。",
    "natural": "按需要自然提问，不强求追问。",
    "proactive": "可主动提出与当前任务相关的澄清问题，避免连续追问。",
}
_PROPOSALS = {
    "ask_first": "可先征求用户同意再建议调整偏好；不得自动修改偏好、记忆或权限。",
    "manual_only": "偏好仅由用户在设置面板调整；不要主动建议修改偏好，也不得自动写入。",
}


class PersonalAssistantDialogueRuntimeExtension:
    plugin_id = "personal-assistant-dialogue"
    source_kind = plugin_id

    def build_prompt_segments(
        self, agent_id: str, *, session_id: str = "", run_id: str = ""
    ) -> list[dict[str, Any]]:
        normalized_agent_id = str(agent_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_agent_id or not normalized_session_id:
            return []
        from core.web.services import personal_assistant_service as personal
        from core.web.services import virtual_human_life_service as facade

        try:
            candidate = facade._default_agent_loader(normalized_agent_id) or {}
            if (candidate.get("metadata") or {}).get("personalAssistantProfile") != personal.PROFILE:
                return []
            service = facade.get_virtual_human_life_service()
            binding = service.binding_for(normalized_agent_id)
            if binding and binding.get("enabled"):
                # An enabled Companion already owns its dialogue prompt.
                return []
            assistant = personal.profile_agent()
            if (
                not assistant
                or assistant.get("agentId") != normalized_agent_id
                or assistant.get("status") != "active"
                or str(assistant.get("directSessionId") or "").strip() != normalized_session_id
                or not personal._owns_session(assistant, personal._session_row(assistant))
            ):
                return []
            settings = service.dialogue_settings(normalized_agent_id)
            # Only closed-enum instructions enter the prompt, never stored text.
            instructions = [
                _SPEAKING[settings["speakingInitiative"]],
                _QUESTIONS[settings["questionInitiative"]],
                "高风险操作仍须按现有规则取得确认，不得因提问偏好跳过确认。",
                _PROPOSALS[settings["preferenceProposalMode"]],
            ]
        except Exception:  # noqa: BLE001 - optional prompt provider fails closed
            return []
        return [{
            "key": "personal_assistant_dialogue",
            "block": "## 个人助理对话偏好\n" + "\n".join(instructions),
            "placement": "volatile_turn",
            "stability": "turn_dynamic",
            "trust": "operator_controlled",
        }]

    def filter_tool_names(
        self, agent_id: str, tool_names: list[str], *,
        runtime_context: dict[str, Any] | None = None,
    ) -> list[str]:
        return tool_names

    def blocked_tool_names(self, agent_id: str) -> list[str]:
        return []

    def tool_execution_denial(self, runtime: dict[str, Any], tool_name: str) -> str | None:
        return None

    def prepare_agent_archive(self, agent_id: str, *, stage_workspace: bool = False) -> Any:
        return None

    def rollback_agent_archive(self, token: Any) -> None:
        return None

    def commit_agent_purge(self, token: Any) -> None:
        return None

    def proactive_turn_is_current(
        self, *, agent_id: str, binding_revision: int, delivery_token: str,
    ) -> bool:
        return False

    def cancel_proactive_attempt(
        self, *, agent_id: str, delivery_token: str, reason: str,
    ) -> None:
        return None

    def finalize_proactive_delivery(self, context: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def proactive_runtime_metadata(self, context: dict[str, Any]) -> dict[str, Any]:
        return {}


PERSONAL_ASSISTANT_DIALOGUE_RUNTIME_EXTENSION = PersonalAssistantDialogueRuntimeExtension()
