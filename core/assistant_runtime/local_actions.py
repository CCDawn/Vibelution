"""Closed Launcher-local actions over the existing assistant/config owners.

The canonical tool wrapper supplies the current assistant identity. Only its
native manage-tool path may set ``governed=True`` after authorization; this is
never a model parameter. Project object operations belong to project dispatch.
"""

from __future__ import annotations


_ASSISTANT_ACTIONS = (
    "assistant_settings", "assistant_settings_update", "assistant_model_set",
    "dialogue_settings", "dialogue_settings_update",
)
_CONFIG_ACTIONS = (
    "provider_catalog", "provider_add", "provider_update", "provider_remove",
    "provider_test", "provider_discover", "provider_models", "model_update",
    "model_details", "model_defaults", "model_remove", "model_default",
)
_PLATFORM_ACTIONS = ("settings_update", "model_add", "model_options")
_REFERENCE_DELETIONS = frozenset({"model_remove", "provider_remove"})
_REFERENCE_GUARD_MESSAGE = "尚未完成全部项目及助理自身的模型引用校验；保留现有配置，不能按单项目零引用执行删除或停用。"


def contracts() -> dict:
    """Reuse native schemas and approval flags without exposing project actions."""
    from tools import pa_assistant_actions, pa_config_actions, pa_platform_actions

    result = {}
    for names, source in (
        (_ASSISTANT_ACTIONS, pa_assistant_actions.contracts()),
        (_CONFIG_ACTIONS, pa_config_actions.contracts()),
    ):
        for name in names:
            result[name] = source[name]
    for name in _PLATFORM_ACTIONS:
        result[name] = {**pa_platform_actions.action_catalog(name), "governed": False}
    from . import operator_image_actions
    result.update(operator_image_actions.contracts())
    from . import history_actions
    result.update(history_actions.contracts())
    from . import affairs_conflict_actions
    result.update(affairs_conflict_actions.contracts())
    result["assistant_settings_update"] = {**result["assistant_settings_update"],
        "description": result["assistant_settings_update"]["description"] + " 当前轮结束后自动刷新生效，不要求用户手动刷新或重启。"}
    # This native read action predates describe support. Its empty arguments
    # are validated by the same Arguments model in execute_action.
    result["settings_catalog"] = {
        "action": "settings_catalog", "description": "读取 operator 普通设置、头像预设和壁纸选项。",
        "governed": False, "parameters": pa_platform_actions.Arguments.model_json_schema(),
    }
    for name in _REFERENCE_DELETIONS:
        result[name] = {**result[name], "available": False, "unavailableReason": _REFERENCE_GUARD_MESSAGE}
    return result


def execute(action: str, parameters: dict, runtime: dict, *, governed: bool = False) -> dict:
    """Reject everything outside the local allowlist before native execution."""
    contract = contracts().get(action)
    if contract is None:
        raise ValueError("未知的 Launcher 本地操作，请先 index/describe 查询。")
    if action in {"history_list", "history_read"}:
        from .history_actions import execute as execute_history
        return execute_history(action, parameters)
    if action in {"affairs_conflict_sets", "affairs_conflict_list", "affairs_conflict_read", "affairs_sync_receipt"}:
        from .affairs_conflict_actions import execute as execute_conflict
        return execute_conflict(action, parameters, runtime)
    # The reused config owner currently checks one project. A packaged source
    # tree is not the project registry, and unreadable stores cannot prove that
    # references are absent. Native approval does not fill that evidence gap.
    disabling = (action == "provider_update" and parameters.get("enabled") is False) or (
        action == "model_update" and isinstance(parameters.get("updates"), dict)
        and parameters["updates"].get("enabled") is False)
    if action in _REFERENCE_DELETIONS or disabling:
        return {"ok": False, "status": "unavailable", "action": action,
                "error": "cross_project_reference_validation_unavailable", "message": _REFERENCE_GUARD_MESSAGE}
    from tools import pa_platform_actions

    if action in {"operator_image_options", "operator_image_select"}:
        from .operator_image_actions import execute as execute_image
        return execute_image(action, parameters)
    if contract["governed"] and governed is True:
        return pa_platform_actions.execute_extension(action, parameters, runtime, governed=True)
    # Native dispatch normalizes immutable JSON arguments, validates the native
    # DTO, and returns its approval_required guidance before a sensitive write.
    return pa_platform_actions.execute_action(action, parameters, runtime)
