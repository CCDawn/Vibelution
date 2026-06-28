"""Launcher-owned project reset and initialization maintenance helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from config.paths import resolve_config_home, resolve_config_path
from core.infrastructure import developer_sandbox
from core.runtime_manager.scene_logging import append_runtime_manager_file_event
from core.ui.chat_state import build_chat_state, chat_state_path, save_chat_state
from core.web.services.i18n import get_web_language, text_for


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_PREVIEW_PATHS = 120
MAX_SUMMARY_SCAN_ITEMS = 80_000
MAX_SUMMARY_FAST_SCAN_ITEMS = 5_000
RUNNING_SCENE_STATUSES = {"running", "starting", "queued", "stopping"}
MEMORY_DB_TABLES = ("LongTermMemory", "TaskLog", "ErrorArchive", "CodebaseKnowledge")
MAINTENANCE_PLAN_SCHEMA_VERSION = 1
MAINTENANCE_PLAN_TTL_MINUTES = 30
MAINTENANCE_PLAN_DIR = PROJECT_ROOT / ".runtime" / "launcher" / "maintenance-reset-plans"
LauncherMaintenanceProfile = Literal["custom", "clean_start", "factory_runtime"]
SAFE_RUNTIME_CLEAN_ITEM_IDS = (
    "conversation_logs",
    "diagnostic_payloads",
    "runtime_logs",
    "stopped_runtime_scenes",
    "runtime_manager_results",
    "browser_profiles",
    "workspace_browser_profiles",
    "workspace_service_logs",
    "temp_artifacts",
    "root_temp_artifacts",
    "runtime_preview_artifacts",
)
FACTORY_RUNTIME_ITEM_IDS = (
    "chat_history",
    "workspace_sessions",
    "memory",
    *SAFE_RUNTIME_CLEAN_ITEM_IDS,
)
PROFILES: dict[str, tuple[str, ...]] = {
    "clean_start": SAFE_RUNTIME_CLEAN_ITEM_IDS,
    "factory_runtime": FACTORY_RUNTIME_ITEM_IDS,
}
RESET_CATEGORY_LABELS = {
    "conversation_state": ("对话与会话", "Conversation and sessions"),
    "agent_state": ("Agent 与团队", "Agents and teams"),
    "tool_state": ("工具状态", "Tool state"),
    "diagnostics": ("日志与诊断", "Logs and diagnostics"),
    "runtime_artifacts": ("运行与临时产物", "Runtime and temporary artifacts"),
    "build_artifacts": ("可重建产物", "Rebuildable artifacts"),
}


@dataclass(frozen=True)
class ResetItemDefinition:
    id: str
    name_zh: str
    name_en: str
    description_zh: str
    description_en: str
    detail_zh: str
    detail_en: str
    risk: str
    default_selected: bool
    category: str = "runtime_artifacts"
    category_zh: str = "运行与临时产物"
    category_en: str = "Runtime and temporary artifacts"
    rebuild_hint_zh: str = ""
    rebuild_hint_en: str = ""
    collector: Callable[[], list["ResetCandidate"]] | None = None
    executor: Callable[["ResetCandidate"], "ResetActionResult"] | None = None


@dataclass(frozen=True)
class ResetCandidate:
    path: Path
    kind: str
    action: str = "delete"
    note_zh: str = ""
    note_en: str = ""
    protected: bool = False
    missing: bool = False


@dataclass(frozen=True)
class ResetActionResult:
    status: str
    path: Path
    kind: str
    action: str
    message: str = ""


def _record_reset_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        record_runtime_scene_event(
            "reset",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=lifecycle,
        )
    except Exception:
        return


def record_runtime_scene_event(
    domain: str,
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    """Compatibility-shaped event hook backed by Launcher runtime-manager events."""

    append_runtime_manager_file_event(
        event_code,
        {
            "component": "launcher",
            "domain": domain,
            "phase": f"maintenance_reset.{phase}",
            "message": message or event_code,
            "level": level,
            "outcome": outcome,
            "lifecycle": lifecycle,
            "fields": fields or {},
        },
        suppress_io_errors=True,
    )


def get_reset_summary() -> dict:
    """Return the current reset inventory without executing destructive actions."""

    lang = get_web_language()
    started_at = time.perf_counter()
    item_timings: list[dict[str, Any]] = []
    items = []
    for definition in _reset_items():
        item_started_at = time.perf_counter()
        item = _summarize_item(definition, lang)
        elapsed_ms = round((time.perf_counter() - item_started_at) * 1000, 1)
        item_timings.append(
            {
                "id": definition.id,
                "elapsedMs": elapsed_ms,
                "candidateCount": item.get("candidateCount", 0),
                "fileCount": item.get("fileCount", 0),
                "scanTruncated": bool(item.get("scanTruncated", False)),
            }
        )
        items.append(item)
    protected = [
        {
            "id": "source-code",
            "label": text_for(lang, zh="源代码与工具源码", en="Source code and source tools"),
            "paths": ["core/", "web/src/", "tools/*.py"],
            "reason": text_for(lang, zh="Reset 只清理状态与产物，不删除实现代码。", en="Reset only cleans state and artifacts, not implementation code."),
        },
        {
            "id": "config",
            "label": text_for(lang, zh="配置与模型库", en="Config and model library"),
            "paths": [str(resolve_config_path()), str(resolve_config_home())],
            "reason": text_for(lang, zh="配置不是垃圾内容，不提供重置勾选。", en="Config is not cleanup residue."),
        },
        {
            "id": "dynamic-prompts",
            "label": text_for(lang, zh="动态提示词与身份提示词", en="Dynamic and identity prompts"),
            "paths": ["workspace/prompts/DYNAMIC.md", "workspace/prompts/IDENTITY.md", "workspace/prompts/USER.md", "workspace/prompts/CODEBASE_MAP.md"],
            "reason": text_for(lang, zh="这些提示词不是记忆重置目标，Reset 只会清空 STATE_MEMORY.md。", en="These prompts are not memory reset targets; Reset only clears STATE_MEMORY.md."),
        },
        {
            "id": "evolution",
            "label": text_for(lang, zh="监督进化、自进化与 Gym 证据", en="Evolution and Gym evidence"),
            "paths": ["workspace/supervised_evolution/", "workspace/evolution/", "workspace/gym/"],
            "reason": text_for(lang, zh="训练、建议基线和审计证据不能由 Reset 清理。", en="Training, advisory, and audit evidence are preserved."),
        },
        {
            "id": "project-memory",
            "label": text_for(lang, zh="项目记忆", en="Project memory"),
            "paths": [".docs/project-memory/"],
            "reason": text_for(lang, zh="项目记忆是开发定义完成的一部分。", en="Project memory is part of the development record."),
        },
        {
            "id": "active-runtime",
            "label": text_for(lang, zh="当前运行现场与活跃浏览器 profile", en="Active runtime scene and browser profile"),
            "paths": ["logs/runtime_scenes/<current>", ".runtime/launcher/state.json", ".runtime/launcher/edge-app-profile/"],
            "reason": text_for(lang, zh="运行中内容只跳过，不强删。", en="Live runtime state is skipped, not force-deleted."),
        },
    ]
    payload = {
        "warning": text_for(
            lang,
            zh="Reset 现在只允许从后端白名单中自选清理项。Agent 记忆可作为高风险项单独选择；动态提示词、监督进化、自进化、Gym 证据和项目记忆固定保护。",
            en="Reset now only accepts user-selected backend allow-list items. Agent memory can be selected as a high-risk item; dynamic prompts, supervised/self evolution, Gym evidence, and project memory stay protected.",
        ),
        "mode": "custom",
        "items": items,
        "protected": protected,
        "categories": items,
        "presets": [],
    }
    total_elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    slow_items = [item for item in item_timings if float(item.get("elapsedMs") or 0) >= 250.0]
    _record_reset_scene_event(
        "summary",
        "reset.summary.generated",
        message="Reset summary generated.",
        outcome="succeeded",
        fields={
            "elapsedMs": total_elapsed_ms,
            "itemCount": len(items),
            "slowItemCount": len(slow_items),
            "slowItems": slow_items[:8],
            "truncatedItemIds": [item["id"] for item in item_timings if item.get("scanTruncated")],
        },
    )
    return payload


def preview_reset(item_ids: list[str] | tuple[str, ...]) -> dict:
    """Return a deletion preview for the selected allow-list item ids."""

    lang = get_web_language()
    definitions = _definitions_for_ids(item_ids)
    previews = [_preview_item(definition, lang) for definition in definitions]
    totals = _total_from_item_results(previews)
    warnings = _collect_rebuild_hints(definitions, lang)
    payload = {
        "selectedItemIds": [definition.id for definition in definitions],
        "items": previews,
        "totals": totals,
        "warnings": warnings,
        "rebuildHints": warnings,
        "summary": _preview_summary(totals, lang),
    }
    _record_reset_scene_event(
        "preview",
        "reset.preview.generated",
        message="Reset preview generated.",
        outcome="succeeded",
        fields={
            "selectedItemIds": payload["selectedItemIds"],
            **totals,
        },
        lifecycle=True,
    )
    return payload


def execute_reset(item_ids: list[str] | tuple[str, ...], *, confirmed: bool) -> dict:
    """Execute cleanup for the selected allow-list item ids."""

    if not confirmed:
        raise ValueError("Reset execution requires an explicit confirmation flag")

    lang = get_web_language()
    definitions = _definitions_for_ids(item_ids)
    results = [_execute_item(definition, lang) for definition in definitions]
    totals = _total_from_item_results(results)
    rebuild_hints = _collect_rebuild_hints(definitions, lang)
    payload = {
        "selectedItemIds": [definition.id for definition in definitions],
        "items": results,
        "totals": totals,
        "warnings": rebuild_hints,
        "rebuildHints": rebuild_hints,
        "summary": _execute_summary(totals, lang),
    }
    failed_count = int(totals.get("failedCount") or 0)
    _record_reset_scene_event(
        "execute",
        "reset.execute.completed",
        message="Reset execution completed.",
        level="error" if failed_count else "info",
        outcome="failed" if failed_count else "succeeded",
        fields={
            "selectedItemIds": payload["selectedItemIds"],
            **totals,
        },
        lifecycle=True,
    )
    return payload


class LauncherMaintenancePlanError(ValueError):
    """Raised when a Launcher maintenance reset plan cannot be used safely."""

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def get_launcher_maintenance_summary() -> dict[str, Any]:
    """Return Launcher-owned maintenance inventory and supported initialization profiles."""

    summary = get_reset_summary()
    summary["executionOwner"] = "launcher"
    summary["mode"] = "launcher_maintenance"
    summary["profiles"] = [
        {
            "id": "clean_start",
            "label": "干净启动",
            "description": "清理日志、运行残留和可重建临时产物，保留会话、Agent、Team、配置、项目记忆和进化证据。",
            "itemIds": list(PROFILES["clean_start"]),
        },
        {
            "id": "factory_runtime",
            "label": "恢复初始化",
            "description": "清理会话工作区、Agent 记忆、日志和运行残留，保留 Agent、Team、聊天室、模式配置、工具配置、项目记忆和进化证据。",
            "itemIds": list(PROFILES["factory_runtime"]),
        },
    ]
    summary["applyContract"] = {
        "requiresLauncher": True,
        "requiresPlanId": True,
        "requiresPlanHash": True,
        "requiresProfileId": True,
        "requiresConfirm": True,
        "blocksActiveWork": True,
        "retiredWebApi": True,
    }
    _record_reset_scene_event(
        "summary",
        "launcher.maintenance_reset.summary.generated",
        message="Launcher maintenance reset summary generated.",
        outcome="succeeded",
        fields={
            "itemCount": len(summary.get("items") or []),
            "profileCount": len(summary.get("profiles") or []),
            "executionOwner": "launcher",
        },
    )
    return summary


def preview_launcher_maintenance_plan(
    payload: dict[str, Any],
    *,
    plan_dir: Path | None = None,
) -> dict[str, Any]:
    """Build and store a Launcher-owned project reset/initialization plan."""

    if not isinstance(payload, dict):
        raise ValueError("maintenance preview payload must be an object")
    profile_id = _parse_profile_id(payload.get("profileId"))
    selected_item_ids = _selected_item_ids_from_payload(payload, profile_id=profile_id)
    preview = preview_reset(selected_item_ids)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=MAINTENANCE_PLAN_TTL_MINUTES)
    plan = {
        "schemaVersion": MAINTENANCE_PLAN_SCHEMA_VERSION,
        "planId": f"maintplan-{uuid.uuid4().hex[:12]}",
        "planHash": "",
        "profileId": profile_id,
        "createdAt": _format_dt(now),
        "expiresAt": _format_dt(expires_at),
        "projectRoot": str(PROJECT_ROOT.resolve()),
        "selectedItemIds": list(preview["selectedItemIds"]),
        "targetCount": int(preview.get("totals", {}).get("deleteCount") or 0),
        "estimatedBytes": int(preview.get("totals", {}).get("deleteSizeBytes") or 0),
        "requiresConfirm": True,
        "blocksActiveWork": True,
        "preview": preview,
    }
    plan["planHash"] = _maintenance_plan_hash(plan)
    _store_maintenance_plan(plan, plan_dir=plan_dir)
    _record_reset_scene_event(
        "preview",
        "launcher.maintenance_reset.previewed",
        message="Launcher maintenance reset plan previewed.",
        outcome="previewed",
        fields={
            "planId": plan["planId"],
            "planHash": plan["planHash"],
            "profileId": profile_id,
            "selectedItemIds": plan["selectedItemIds"],
            "targetCount": plan["targetCount"],
            "estimatedBytes": plan["estimatedBytes"],
        },
        lifecycle=True,
    )
    return {
        "ok": True,
        "mode": "preview",
        "plan": plan,
        "preview": preview,
        "message": "Launcher 维护计划已生成；执行前会再次校验 planId、planHash、确认状态和 active work。",
    }


def apply_launcher_maintenance_plan(
    payload: dict[str, Any],
    *,
    active_work_runs: list[dict[str, str]] | None = None,
    plan_dir: Path | None = None,
) -> dict[str, Any]:
    """Apply a stored Launcher maintenance plan after guard checks."""

    if not isinstance(payload, dict):
        raise ValueError("maintenance apply payload must be an object")
    if not bool(payload.get("confirm", False)):
        raise LauncherMaintenancePlanError("confirm_required", "执行恢复初始化前必须显式确认。")
    active_work_runs = list(active_work_runs or [])
    if active_work_runs:
        raise LauncherMaintenancePlanError(
            "active_work_blocked",
            "有进行中的任务，无法执行恢复初始化。请等待任务完成或先停止任务。",
            detail={"activeWorkRuns": active_work_runs},
        )
    plan_id = str(payload.get("planId") or "").strip()
    plan_hash = str(payload.get("planHash") or "").strip()
    requested_profile_id = _parse_profile_id(payload.get("profileId"))
    plan = _load_maintenance_plan(plan_id, plan_dir=plan_dir)
    if str(plan.get("planHash") or "") != plan_hash or _maintenance_plan_hash(plan) != plan_hash:
        raise LauncherMaintenancePlanError("plan_hash_mismatch", "维护计划 hash 不匹配，请重新预览。")
    plan_profile_id = _parse_profile_id(plan.get("profileId"))
    if plan_profile_id != requested_profile_id:
        raise LauncherMaintenancePlanError(
            "profile_mismatch",
            "维护档位与预览计划不一致，请重新生成预览。",
            detail={"planProfileId": plan_profile_id, "requestedProfileId": requested_profile_id},
        )
    if _maintenance_plan_expired(str(plan.get("expiresAt") or "")):
        raise LauncherMaintenancePlanError("plan_expired", "维护计划已过期，请重新预览。")
    if Path(str(plan.get("projectRoot") or "")).resolve() != PROJECT_ROOT.resolve():
        raise LauncherMaintenancePlanError("project_root_mismatch", "维护计划不属于当前项目工作区。")
    item_ids = [str(item_id) for item_id in plan.get("selectedItemIds", [])]
    result = execute_reset(item_ids, confirmed=True)
    failed_count = int(result.get("totals", {}).get("failedCount") or 0)
    _record_reset_scene_event(
        "apply",
        "launcher.maintenance_reset.applied",
        message="Launcher maintenance reset plan applied.",
        level="error" if failed_count else "info",
        outcome="failed" if failed_count else "succeeded",
        fields={
            "planId": plan["planId"],
            "planHash": plan["planHash"],
            "profileId": plan.get("profileId", "custom"),
            "selectedItemIds": item_ids,
            "failedCount": failed_count,
            "deletedCount": int(result.get("totals", {}).get("deletedCount") or 0),
        },
        lifecycle=True,
    )
    return {
        "ok": failed_count == 0,
        "mode": "apply",
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "profileId": str(plan.get("profileId") or "custom"),
        "result": result,
        "frontendInvalidation": {
            "clearChatWorkspace": bool(set(item_ids) & {"chat_history", "workspace_sessions", "chat_rooms"}),
            "clearSessionUrl": bool(set(item_ids) & {"chat_history", "workspace_sessions", "chat_rooms"}),
            "invalidate": [
                "launcherMaintenanceSummary",
                "launcherStatus",
                "conversations",
                "sessions",
                "chatRooms",
                "agents",
                "teams",
                "memoryOverview",
                "runtimeScenes",
                "logRoots",
            ],
        },
        "message": result.get("summary") or "Launcher 维护计划已执行。",
    }


def _parse_profile_id(value: object) -> LauncherMaintenanceProfile:
    profile_id = str(value or "custom").strip() or "custom"
    if profile_id in {"custom", "clean_start", "factory_runtime"}:
        return profile_id  # type: ignore[return-value]
    raise ValueError(f"Unsupported maintenance profile: {profile_id}")


def _selected_item_ids_from_payload(payload: dict[str, Any], *, profile_id: LauncherMaintenanceProfile) -> list[str]:
    raw_item_ids = payload.get("itemIds")
    item_ids: list[str] = []
    if isinstance(raw_item_ids, list):
        item_ids = [str(item_id or "").strip() for item_id in raw_item_ids if str(item_id or "").strip()]
    if item_ids:
        return item_ids
    if profile_id in PROFILES:
        return list(PROFILES[profile_id])
    raise ValueError("Select at least one maintenance reset item")


def _store_maintenance_plan(plan: dict[str, Any], *, plan_dir: Path | None) -> None:
    directory = Path(plan_dir or MAINTENANCE_PLAN_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{plan['planId']}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_maintenance_plan(plan_id: str, *, plan_dir: Path | None) -> dict[str, Any]:
    normalized = str(plan_id or "").strip()
    if not normalized or not normalized.startswith("maintplan-") or not normalized.replace("maintplan-", "").isalnum():
        raise LauncherMaintenancePlanError("invalid_plan_id", "维护计划 ID 无效。")
    path = Path(plan_dir or MAINTENANCE_PLAN_DIR) / f"{normalized}.json"
    if not path.is_file():
        raise LauncherMaintenancePlanError("plan_not_found", "维护计划不存在，请重新预览。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LauncherMaintenancePlanError("plan_unreadable", "维护计划无法读取，请重新预览。") from exc
    if not isinstance(payload, dict):
        raise LauncherMaintenancePlanError("plan_unreadable", "维护计划格式无效，请重新预览。")
    return payload


def _maintenance_plan_hash(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload["planHash"] = ""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _maintenance_plan_expired(expires_at: str) -> bool:
    try:
        deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) > deadline


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _reset_items() -> tuple[ResetItemDefinition, ...]:
    return (
        ResetItemDefinition(
            id="chat_history",
            name_zh="聊天历史",
            name_en="Chat history",
            description_zh="清空 workspace/chat/chat_state.json，并写回一个空默认会话。",
            description_en="Clear workspace/chat/chat_state.json and recreate one empty default session.",
            detail_zh="workspace/chat/chat_state.json",
            detail_en="workspace/chat/chat_state.json",
            risk="medium",
            default_selected=False,
            category="conversation_state",
            category_zh="对话与会话",
            category_en="Conversation and sessions",
            collector=_collect_chat_history,
            executor=_execute_chat_history,
        ),
        ResetItemDefinition(
            id="workspace_sessions",
            name_zh="会话工作区",
            name_en="Session workspaces",
            description_zh="删除 workspace/sessions/ 下的会话运行工作区。聊天历史需单独选择。",
            description_en="Delete session runtime workspaces under workspace/sessions/. Select chat history separately.",
            detail_zh="workspace/sessions/",
            detail_en="workspace/sessions/",
            risk="high",
            default_selected=False,
            category="conversation_state",
            category_zh="对话与会话",
            category_en="Conversation and sessions",
            collector=_collect_workspace_sessions,
        ),
        ResetItemDefinition(
            id="chat_rooms",
            name_zh="聊天室与群聊",
            name_en="Chat rooms",
            description_zh="删除 workspace/chat_rooms/ 的聊天室索引和房间目录。",
            description_en="Delete chat room indexes and room folders under workspace/chat_rooms/.",
            detail_zh="workspace/chat_rooms/",
            detail_en="workspace/chat_rooms/",
            risk="high",
            default_selected=False,
            category="conversation_state",
            category_zh="对话与会话",
            category_en="Conversation and sessions",
            collector=_collect_chat_rooms,
        ),
        ResetItemDefinition(
            id="memory",
            name_zh="Agent 记忆",
            name_en="Agent memory",
            description_zh="重置 agent_brain.db 中的记忆表、workspace/memory/ 与 STATE_MEMORY.md；保留动态提示词、进化证据和项目记忆。",
            description_en="Reset memory tables in agent_brain.db, workspace/memory/, and STATE_MEMORY.md while preserving dynamic prompts, evolution evidence, and project memory.",
            detail_zh="workspace/agent_brain.db 记忆表、workspace/memory/、workspace/prompts/STATE_MEMORY.md",
            detail_en="workspace/agent_brain.db memory tables, workspace/memory/, workspace/prompts/STATE_MEMORY.md",
            risk="high",
            default_selected=False,
            category="agent_state",
            category_zh="Agent 与团队",
            category_en="Agents and teams",
            collector=_collect_memory,
            executor=_execute_memory,
        ),
        ResetItemDefinition(
            id="agents",
            name_zh="Agent 注册表与工作区",
            name_en="Agent registry and workspaces",
            description_zh="删除 workspace/agents/ 下的 Agent 注册表、事件和私有工作区；不会删除 workspace/shared/。",
            description_en="Delete Agent registry, events, and private workspaces under workspace/agents/; workspace/shared/ is not touched.",
            detail_zh="workspace/agents/",
            detail_en="workspace/agents/",
            risk="high",
            default_selected=False,
            category="agent_state",
            category_zh="Agent 与团队",
            category_en="Agents and teams",
            collector=_collect_agents,
            executor=_execute_agents,
        ),
        ResetItemDefinition(
            id="agent_config_state",
            name_zh="Agent 模式与提示词配置",
            name_en="Agent mode and prompt config",
            description_zh="删除 workspace/agent_config/ 下的模式绑定与提示词模板状态；动态提示词文件仍固定保护。",
            description_en="Delete mode bindings and prompt template state under workspace/agent_config/; dynamic prompt files stay protected.",
            detail_zh="workspace/agent_config/mode_bindings.json、prompt_templates.json",
            detail_en="workspace/agent_config/mode_bindings.json, prompt_templates.json",
            risk="high",
            default_selected=False,
            category="agent_state",
            category_zh="Agent 与团队",
            category_en="Agents and teams",
            collector=_collect_agent_config_state,
        ),
        ResetItemDefinition(
            id="teams",
            name_zh="团队配置",
            name_en="Teams",
            description_zh="删除 workspace/teams/ 的团队索引、团队目录和团队运行状态。",
            description_en="Delete team indexes, folders, and team runtime state under workspace/teams/.",
            detail_zh="workspace/teams/",
            detail_en="workspace/teams/",
            risk="high",
            default_selected=False,
            category="agent_state",
            category_zh="Agent 与团队",
            category_en="Agents and teams",
            collector=_collect_teams,
        ),
        ResetItemDefinition(
            id="project_agent_bus",
            name_zh="Agent 消息总线",
            name_en="Agent message bus",
            description_zh="删除 workspace/project_agent_bus/ 的跨 Agent 消息队列和投递残留。",
            description_en="Delete cross-Agent message queue and delivery residue under workspace/project_agent_bus/.",
            detail_zh="workspace/project_agent_bus/",
            detail_en="workspace/project_agent_bus/",
            risk="high",
            default_selected=False,
            category="agent_state",
            category_zh="Agent 与团队",
            category_en="Agents and teams",
            collector=_collect_project_agent_bus,
        ),
        ResetItemDefinition(
            id="generated_tools",
            name_zh="生成工具注册表",
            name_en="Generated tool registry",
            description_zh="清空 workspace/tool_registry/generated_tools.json；不会删除 tools/ 下的源码工具。",
            description_en="Clear workspace/tool_registry/generated_tools.json without deleting source tools under tools/.",
            detail_zh="workspace/tool_registry/generated_tools.json",
            detail_en="workspace/tool_registry/generated_tools.json",
            risk="high",
            default_selected=False,
            category="tool_state",
            category_zh="工具状态",
            category_en="Tool state",
            collector=_collect_generated_tools,
            executor=_execute_generated_tools,
        ),
        ResetItemDefinition(
            id="conversation_logs",
            name_zh="会话日志",
            name_en="Conversation logs",
            description_zh="删除 log_info/ 下的 conversation_*.jsonl 与 debug_*.log 等会话诊断文件。",
            description_en="Delete conversation_*.jsonl, debug_*.log, and related session diagnostics under log_info/.",
            detail_zh="log_info/ 中的会话与 debug 日志",
            detail_en="conversation and debug logs in log_info/",
            risk="medium",
            default_selected=False,
            category="diagnostics",
            category_zh="日志与诊断",
            category_en="Logs and diagnostics",
            collector=_collect_conversation_logs,
        ),
        ResetItemDefinition(
            id="diagnostic_payloads",
            name_zh="诊断 payload 与报告",
            name_en="Diagnostic payloads and reports",
            description_zh="删除 log_info/payloads/ 与 log_info/harness_reports/ 等诊断大对象。",
            description_en="Delete large diagnostic payloads such as log_info/payloads/ and log_info/harness_reports/.",
            detail_zh="log_info/payloads/、log_info/harness_reports/",
            detail_en="log_info/payloads/, log_info/harness_reports/",
            risk="medium",
            default_selected=False,
            category="diagnostics",
            category_zh="日志与诊断",
            category_en="Logs and diagnostics",
            collector=_collect_diagnostic_payloads,
        ),
        ResetItemDefinition(
            id="runtime_logs",
            name_zh="普通运行日志",
            name_en="Runtime logs",
            description_zh="删除 logs/ 下除 runtime_scenes/ 以外的普通日志文件。",
            description_en="Delete ordinary files under logs/ while excluding logs/runtime_scenes/.",
            detail_zh="logs/ 非 runtime_scenes 内容",
            detail_en="logs/ excluding runtime_scenes/",
            risk="low",
            default_selected=False,
            category="diagnostics",
            category_zh="日志与诊断",
            category_en="Logs and diagnostics",
            collector=_collect_runtime_logs,
        ),
        ResetItemDefinition(
            id="stopped_runtime_scenes",
            name_zh="已停止运行现场",
            name_en="Stopped runtime scenes",
            description_zh="删除 logs/runtime_scenes/ 中状态不是 running/starting/queued/stopping 的运行现场。",
            description_en="Delete runtime scene bundles whose status is not running, starting, queued, or stopping.",
            detail_zh="logs/runtime_scenes/ 已停止现场；当前运行现场跳过",
            detail_en="stopped logs/runtime_scenes/ bundles; current scene is skipped",
            risk="medium",
            default_selected=False,
            category="diagnostics",
            category_zh="日志与诊断",
            category_en="Logs and diagnostics",
            collector=_collect_stopped_runtime_scenes,
        ),
        ResetItemDefinition(
            id="runtime_manager_results",
            name_zh="runtime-manager 历史结果",
            name_en="Runtime-manager results",
            description_zh="删除 .runtime/runtime-manager/results/ 中的旧命令残留。",
            description_en="Delete old command result residue under .runtime/runtime-manager/results/.",
            detail_zh=".runtime/runtime-manager/results/",
            detail_en=".runtime/runtime-manager/results/",
            risk="low",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_runtime_manager_results,
        ),
        ResetItemDefinition(
            id="browser_profiles",
            name_zh="旧浏览器/测试 profile",
            name_en="Old browser/test profiles",
            description_zh="删除 .runtime/ 下旧 profile 目录，保护当前 launcher 使用的浏览器 profile。",
            description_en="Delete old profile directories under .runtime/ while protecting the active launcher browser profile.",
            detail_zh=".runtime/*profile*，当前 browserProfileDir 跳过",
            detail_en=".runtime/*profile* with current browserProfileDir skipped",
            risk="medium",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_browser_profiles,
        ),
        ResetItemDefinition(
            id="workspace_browser_profiles",
            name_zh="workspace 浏览器 profile",
            name_en="Workspace browser profiles",
            description_zh="删除 workspace/ 下的 headless/edge/browser 测试 profile。",
            description_en="Delete headless/edge/browser test profiles under workspace/.",
            detail_zh="workspace/*profile*、workspace/edge-headless-profile/",
            detail_en="workspace/*profile*, workspace/edge-headless-profile/",
            risk="medium",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_workspace_browser_profiles,
        ),
        ResetItemDefinition(
            id="workspace_service_logs",
            name_zh="workspace 服务日志",
            name_en="Workspace service logs",
            description_zh="删除 workspace 根下 *.out.log、*.err.log 与 workspace/logs/。",
            description_en="Delete workspace root *.out.log, *.err.log, and workspace/logs/.",
            detail_zh="workspace/*.out.log、workspace/*.err.log、workspace/logs/",
            detail_en="workspace/*.out.log, workspace/*.err.log, workspace/logs/",
            risk="low",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_workspace_service_logs,
        ),
        ResetItemDefinition(
            id="python_test_caches",
            name_zh="Python/测试缓存",
            name_en="Python/test caches",
            description_zh="删除 __pycache__/、.pytest_cache/、.ruff_cache/，跳过 .venv 和 node_modules。",
            description_en="Delete __pycache__/, .pytest_cache/, and .ruff_cache/ while skipping .venv and node_modules.",
            detail_zh="递归缓存目录",
            detail_en="recursive cache directories",
            risk="low",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_python_test_caches,
        ),
        ResetItemDefinition(
            id="temp_artifacts",
            name_zh="临时截图/HTML",
            name_en="Temporary screenshots/HTML",
            description_zh="删除 workspace/tmp-* 与 .runtime 根下明确临时的 png/html/log/txt 文件。",
            description_en="Delete workspace/tmp-* and clearly temporary png/html/log/txt files at the .runtime root.",
            detail_zh="workspace/tmp-*、.runtime/*.png|*.html|*.log|*.txt",
            detail_en="workspace/tmp-* and .runtime/*.png|*.html|*.log|*.txt",
            risk="low",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_temp_artifacts,
        ),
        ResetItemDefinition(
            id="root_temp_artifacts",
            name_zh="根目录临时残留",
            name_en="Root temporary residue",
            description_zh="删除根目录显式临时目录和临时日志，如 .tmp、tmp_prompt_debug、.tmp-vite-chat2.log。",
            description_en="Delete explicit root-level temporary folders and logs such as .tmp, tmp_prompt_debug, and .tmp-vite-chat2.log.",
            detail_zh=".tmp、tmp、tmp-*、tmp_prompt_debug、.codex-temp、.tmp-*.log",
            detail_en=".tmp, tmp, tmp-*, tmp_prompt_debug, .codex-temp, .tmp-*.log",
            risk="low",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_root_temp_artifacts,
        ),
        ResetItemDefinition(
            id="runtime_preview_artifacts",
            name_zh="预览/冒烟运行残留",
            name_en="Preview/smoke runtime residue",
            description_zh="删除 .runtime/codex-preview、codex-reset-server、codex-ui-check、tmp-* 与预览/冒烟日志。",
            description_en="Delete .runtime/codex-preview, codex-reset-server, codex-ui-check, tmp-*, and preview/smoke logs.",
            detail_zh=".runtime/codex-preview、.runtime/codex-reset-server、.runtime/codex-ui-check、.runtime/tmp-*",
            detail_en=".runtime/codex-preview, .runtime/codex-reset-server, .runtime/codex-ui-check, .runtime/tmp-*",
            risk="low",
            default_selected=False,
            category="runtime_artifacts",
            category_zh="运行与临时产物",
            category_en="Runtime and temporary artifacts",
            collector=_collect_runtime_preview_artifacts,
        ),
        ResetItemDefinition(
            id="web_dist",
            name_zh="可重建前端产物",
            name_en="Rebuildable frontend output",
            description_zh="删除 web/dist/。单后端静态托管模式需要重新 npm run build，或用 Bun 辅助构建后才能打开前端。",
            description_en="Delete web/dist/. Single-backend static hosting needs npm run build, or the Bun auxiliary build, before the frontend opens again.",
            detail_zh="web/dist/",
            detail_en="web/dist/",
            risk="medium",
            default_selected=False,
            category="build_artifacts",
            category_zh="可重建产物",
            category_en="Rebuildable artifacts",
            rebuild_hint_zh="删除 web/dist/ 后，单后端静态托管模式需要在 web/ 重新执行 npm run build；本地辅助构建可用 bun run bun:build。",
            rebuild_hint_en="After deleting web/dist/, run npm run build in web/ before using single-backend static hosting; local auxiliary builds can use bun run bun:build.",
            collector=_collect_web_dist,
        ),
    )


def _summarize_item(definition: ResetItemDefinition, lang: str) -> dict:
    candidates = definition.collector() if definition.collector else []
    deletable = [candidate for candidate in candidates if _candidate_is_deletable(candidate)]
    protected = [candidate for candidate in candidates if candidate.protected]
    missing = [candidate for candidate in candidates if candidate.missing]
    totals = _sum_existing_totals(deletable, max_scan_items=MAX_SUMMARY_FAST_SCAN_ITEMS)
    size_bytes = totals["sizeBytes"]
    file_count = totals["fileCount"]
    exists = bool(deletable)
    return {
        "id": definition.id,
        "name": _localized(definition, "name", lang),
        "description": _localized(definition, "description", lang),
        "detail": _localized(definition, "detail", lang),
        "category": definition.category,
        "categoryLabel": _localized_category(definition, lang),
        "risk": definition.risk,
        "defaultSelected": definition.default_selected,
        "exists": exists,
        "sizeBytes": size_bytes,
        "size": _format_size(size_bytes) if exists else text_for(lang, zh="无可清理内容", en="nothing to clean"),
        "fileCount": file_count,
        "scanTruncated": totals["scanTruncated"],
        "candidateCount": len(deletable),
        "protectedCount": len(protected),
        "missingCount": len(missing),
        "rebuildHint": _localized_rebuild_hint(definition, lang),
    }


def _preview_item(definition: ResetItemDefinition, lang: str) -> dict:
    candidates = definition.collector() if definition.collector else []
    delete_candidates = [candidate for candidate in candidates if _candidate_is_deletable(candidate)]
    protected = [candidate for candidate in candidates if candidate.protected]
    skipped = [candidate for candidate in candidates if candidate.missing]
    summary = {
        "deleteCount": len(delete_candidates),
        "deleteFileCount": _sum_file_count(delete_candidates),
        "deleteSizeBytes": _sum_existing_size(delete_candidates),
        "skippedCount": len(skipped),
        "protectedCount": len(protected),
        "failedCount": 0,
    }
    return {
        "id": definition.id,
        "name": _localized(definition, "name", lang),
        "category": definition.category,
        "categoryLabel": _localized_category(definition, lang),
        "risk": definition.risk,
        "deleteCandidates": [_candidate_payload(candidate, lang) for candidate in delete_candidates[:MAX_PREVIEW_PATHS]],
        "skipped": [_candidate_payload(candidate, lang) for candidate in skipped[:MAX_PREVIEW_PATHS]],
        "protected": [_candidate_payload(candidate, lang) for candidate in protected[:MAX_PREVIEW_PATHS]],
        "failed": [],
        "warnings": [_localized_rebuild_hint(definition, lang)] if _localized_rebuild_hint(definition, lang) else [],
        "truncated": len(delete_candidates) > MAX_PREVIEW_PATHS,
        "summary": summary,
    }


def _execute_item(definition: ResetItemDefinition, lang: str) -> dict:
    candidates = definition.collector() if definition.collector else []
    deleted: list[ResetActionResult] = []
    failed: list[ResetActionResult] = []
    skipped: list[ResetActionResult] = []
    protected: list[ResetCandidate] = []

    for candidate in candidates:
        if candidate.protected:
            protected.append(candidate)
            continue
        if candidate.missing and candidate.action != "reset":
            skipped.append(
                ResetActionResult(
                    status="skipped",
                    path=candidate.path,
                    kind=candidate.kind,
                    action=candidate.action,
                    message=_candidate_note(candidate, lang) or text_for(lang, zh="不存在，已跳过。", en="Missing; skipped."),
                )
            )
            continue
        executor = definition.executor or _execute_delete_candidate
        result = executor(candidate)
        if result.status == "deleted":
            deleted.append(result)
        elif result.status == "skipped":
            skipped.append(result)
        else:
            failed.append(result)

    summary = {
        "deletedCount": len(deleted),
        "deletedFileCount": _sum_result_file_count(deleted),
        "deletedSizeBytes": 0,
        "skippedCount": len(skipped),
        "protectedCount": len(protected),
        "failedCount": len(failed),
    }
    return {
        "id": definition.id,
        "name": _localized(definition, "name", lang),
        "category": definition.category,
        "categoryLabel": _localized_category(definition, lang),
        "risk": definition.risk,
        "deleted": [_result_payload(result) for result in deleted[:MAX_PREVIEW_PATHS]],
        "skipped": [_result_payload(result) for result in skipped[:MAX_PREVIEW_PATHS]],
        "protected": [_candidate_payload(candidate, lang) for candidate in protected[:MAX_PREVIEW_PATHS]],
        "failed": [_result_payload(result) for result in failed[:MAX_PREVIEW_PATHS]],
        "warnings": [_localized_rebuild_hint(definition, lang)] if _localized_rebuild_hint(definition, lang) else [],
        "truncated": len(deleted) > MAX_PREVIEW_PATHS,
        "summary": summary,
    }


def _collect_chat_history() -> list[ResetCandidate]:
    path = chat_state_path(PROJECT_ROOT)
    return [_candidate_for_path(path, kind="file", action="reset", missing=not path.exists())]


def _collect_workspace_sessions() -> list[ResetCandidate]:
    path = developer_sandbox.route_workspace_path(PROJECT_ROOT, "session", "sessions", intent="state")
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _collect_chat_rooms() -> list[ResetCandidate]:
    path = developer_sandbox.route_workspace_path(PROJECT_ROOT, "chat_room", "chat_rooms", intent="state")
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _collect_memory() -> list[ResetCandidate]:
    workspace_root = developer_sandbox.formal_workspace_path(PROJECT_ROOT)
    candidates = [
        _candidate_for_path(
            workspace_root / "agent_brain.db",
            kind="database",
            action="reset",
            note_zh="清空 agent_brain.db 中的记忆表，保留数据库结构和 Git/进化状态表。",
            note_en="Clear memory tables in agent_brain.db while preserving schema and Git/evolution state tables.",
        ),
        _candidate_for_path(workspace_root / "memory", kind="directory"),
        _candidate_for_path(workspace_root / "prompts" / "STATE_MEMORY.md", kind="file", action="reset"),
    ]
    return _dedupe_candidates(candidates)


def _collect_agents() -> list[ResetCandidate]:
    path = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "agents")
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _execute_agents(candidate: ResetCandidate) -> ResetActionResult:
    result = _execute_delete_candidate(candidate)
    if result.status != "deleted":
        return result
    registry_path = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "agents", "agents.json")
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps({"version": 1, "agents": []}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        failed = ResetActionResult("failed", registry_path, "file", "reset", str(exc))
        _record_reset_candidate_event(failed)
        return failed
    return ResetActionResult(
        status="deleted",
        path=candidate.path,
        kind=candidate.kind,
        action=candidate.action,
        message="reset agent registry to empty state",
    )


def _collect_agent_config_state() -> list[ResetCandidate]:
    workspace_root = developer_sandbox.formal_workspace_path(PROJECT_ROOT)
    paths = [
        workspace_root / "agent_config" / "mode_bindings.json",
        workspace_root / "agent_config" / "prompt_templates.json",
    ]
    return _dedupe_candidates(
        [_candidate_for_path(path, kind="file", missing=not path.exists()) for path in paths]
    )


def _collect_teams() -> list[ResetCandidate]:
    path = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "teams")
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _collect_project_agent_bus() -> list[ResetCandidate]:
    path = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "project_agent_bus")
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _collect_generated_tools() -> list[ResetCandidate]:
    path = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "tool_registry", "generated_tools.json")
    return [
        _candidate_for_path(
            path,
            kind="file",
            action="reset",
            missing=not path.exists(),
            note_zh="清空生成工具注册表；源码 tools/ 不会被删除。",
            note_en="Clear generated tool registry; source tools/ is not deleted.",
        )
    ]


def _execute_generated_tools(candidate: ResetCandidate) -> ResetActionResult:
    try:
        candidate.path.parent.mkdir(parents=True, exist_ok=True)
        candidate.path.write_text("[]\n", encoding="utf-8")
    except OSError as exc:
        result = ResetActionResult("failed", candidate.path, candidate.kind, candidate.action, str(exc))
        _record_reset_candidate_event(result)
        return result
    result = ResetActionResult("deleted", candidate.path, candidate.kind, candidate.action, "reset to empty generated tool registry")
    _record_reset_candidate_event(result)
    return result


def _execute_memory(candidate: ResetCandidate) -> ResetActionResult:
    relative = _relative_path(candidate.path)
    if relative == "workspace/agent_brain.db":
        return _execute_memory_database_reset(candidate)
    if relative == "workspace/prompts/STATE_MEMORY.md":
        return _execute_state_memory_reset(candidate)
    return _execute_delete_candidate(candidate)


def _execute_memory_database_reset(candidate: ResetCandidate) -> ResetActionResult:
    if not candidate.path.exists():
        result = ResetActionResult("skipped", candidate.path, candidate.kind, candidate.action, "missing")
        _record_reset_candidate_event(result)
        return result
    try:
        with sqlite3.connect(str(candidate.path)) as conn:
            cursor = conn.cursor()
            existing = {
                str(row[0])
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            cleared = [table for table in MEMORY_DB_TABLES if table in existing]
            for table in cleared:
                cursor.execute(f"DELETE FROM {table}")
            conn.commit()
    except sqlite3.Error as exc:
        result = ResetActionResult("failed", candidate.path, candidate.kind, candidate.action, str(exc))
        _record_reset_candidate_event(result)
        return result
    message = f"reset memory tables: {', '.join(cleared)}" if cleared else "no memory tables found"
    result = ResetActionResult("deleted", candidate.path, candidate.kind, candidate.action, message)
    _record_reset_candidate_event(result)
    return result


def _execute_state_memory_reset(candidate: ResetCandidate) -> ResetActionResult:
    try:
        from core.prompt_manager import get_prompt_manager

        prompt_manager = get_prompt_manager()
        dynamic_root = str(prompt_manager.get_status().get("dynamic_root") or "").strip()
        if dynamic_root and _same_path(Path(dynamic_root), candidate.path.parent):
            prompt_manager.clear_state_memory(persist=False)
    except Exception:
        pass
    try:
        candidate.path.parent.mkdir(parents=True, exist_ok=True)
        candidate.path.write_text("", encoding="utf-8")
    except OSError as exc:
        result = ResetActionResult("failed", candidate.path, candidate.kind, candidate.action, str(exc))
        _record_reset_candidate_event(result)
        return result
    result = ResetActionResult("deleted", candidate.path, candidate.kind, candidate.action, "reset to empty state memory")
    _record_reset_candidate_event(result)
    return result


def _execute_chat_history(candidate: ResetCandidate) -> ResetActionResult:
    try:
        save_chat_state(PROJECT_ROOT, build_chat_state([]))
    except OSError as exc:
        return ResetActionResult(
            status="failed",
            path=candidate.path,
            kind=candidate.kind,
            action="reset",
            message=str(exc),
        )
    return ResetActionResult(
        status="deleted",
        path=candidate.path,
        kind=candidate.kind,
        action="reset",
        message="reset to empty chat state",
    )


def _collect_conversation_logs() -> list[ResetCandidate]:
    root = PROJECT_ROOT / "log_info"
    if not root.exists():
        return [_candidate_for_path(root, kind="directory", missing=True)]
    candidates: list[ResetCandidate] = []
    for path in _walk_project_paths(root):
        if path.is_file() and _is_conversation_log_file(path):
            candidates.append(_candidate_for_path(path, kind="file"))
    return _dedupe_candidates(candidates)


def _collect_diagnostic_payloads() -> list[ResetCandidate]:
    paths = [
        PROJECT_ROOT / "log_info" / "payloads",
        PROJECT_ROOT / "log_info" / "harness_reports",
    ]
    return _dedupe_candidates(
        [_candidate_for_path(path, kind="directory", missing=not path.exists()) for path in paths]
    )


def _collect_runtime_logs() -> list[ResetCandidate]:
    root = PROJECT_ROOT / "logs"
    if not root.exists():
        return [_candidate_for_path(root, kind="directory", missing=True)]
    candidates: list[ResetCandidate] = []
    runtime_scenes_root = (root / "runtime_scenes").resolve()
    for path in _walk_project_paths(root, skip_roots=[runtime_scenes_root]):
        try:
            path.resolve().relative_to(runtime_scenes_root)
            continue
        except ValueError:
            pass
        if path.is_file():
            candidates.append(_candidate_for_path(path, kind="file"))
    return _dedupe_candidates(candidates)


def _collect_stopped_runtime_scenes() -> list[ResetCandidate]:
    root = PROJECT_ROOT / "logs" / "runtime_scenes"
    if not root.exists():
        return [_candidate_for_path(root, kind="directory", missing=True)]
    active_scene_dir = _current_runtime_scene_dir()
    candidates: list[ResetCandidate] = []
    for scene_dir in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not scene_dir.is_dir():
            continue
        status = _runtime_scene_status(scene_dir)
        if active_scene_dir is not None and _same_path(scene_dir, active_scene_dir):
            candidates.append(
                _candidate_for_path(
                    scene_dir,
                    kind="directory",
                    protected=True,
                    note_zh="当前 launcher 正在使用的运行现场。",
                    note_en="Active launcher runtime scene.",
                )
            )
            continue
        if status in RUNNING_SCENE_STATUSES:
            candidates.append(
                _candidate_for_path(
                    scene_dir,
                    kind="directory",
                    protected=True,
                    note_zh=f"运行现场状态为 {status}，已保护。",
                    note_en=f"Runtime scene status is {status}; protected.",
                )
            )
            continue
        candidates.append(_candidate_for_path(scene_dir, kind="directory"))
    return _dedupe_candidates(candidates)


def _collect_runtime_manager_results() -> list[ResetCandidate]:
    path = PROJECT_ROOT / ".runtime" / "runtime-manager" / "results"
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _collect_browser_profiles() -> list[ResetCandidate]:
    runtime_root = PROJECT_ROOT / ".runtime"
    if not runtime_root.exists():
        return [_candidate_for_path(runtime_root, kind="directory", missing=True)]
    current_profile = _current_browser_profile_dir()
    candidates: list[ResetCandidate] = []
    if current_profile is not None:
        candidates.append(
            _candidate_for_path(
                current_profile,
                kind="directory",
                protected=True,
                note_zh="当前 launcher 正在使用的浏览器 profile。",
                note_en="Active launcher browser profile.",
            )
        )
    for path in _iter_runtime_profile_dirs(runtime_root):
        if current_profile is not None and (_same_path(path, current_profile) or _is_relative_to(path, current_profile)):
            continue
        candidates.append(_candidate_for_path(path, kind="directory"))
    return _collapse_nested_candidates(_dedupe_candidates(candidates))


def _collect_workspace_browser_profiles() -> list[ResetCandidate]:
    workspace = developer_sandbox.formal_workspace_path(PROJECT_ROOT)
    if not workspace.exists():
        return [_candidate_for_path(workspace, kind="directory", missing=True)]
    candidates: list[ResetCandidate] = []
    for path in workspace.iterdir():
        if not path.is_dir():
            continue
        lowered = path.name.lower()
        if "profile" in lowered and ("browser" in lowered or "edge" in lowered or "headless" in lowered):
            candidates.append(_candidate_for_path(path, kind="directory"))
    return _collapse_nested_candidates(_dedupe_candidates(candidates))


def _collect_workspace_service_logs() -> list[ResetCandidate]:
    workspace = developer_sandbox.formal_workspace_path(PROJECT_ROOT)
    if not workspace.exists():
        return [_candidate_for_path(workspace, kind="directory", missing=True)]
    candidates: list[ResetCandidate] = []
    logs_dir = workspace / "logs"
    candidates.append(_candidate_for_path(logs_dir, kind="directory", missing=not logs_dir.exists()))
    for pattern in ("*.out.log", "*.err.log"):
        for path in workspace.glob(pattern):
            if path.is_file():
                candidates.append(_candidate_for_path(path, kind="file"))
    return _dedupe_candidates(candidates)


def _collect_python_test_caches() -> list[ResetCandidate]:
    names = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    candidates: list[ResetCandidate] = []
    for name in sorted(names):
        path = PROJECT_ROOT / name
        if path.is_dir():
            candidates.append(_candidate_for_path(path, kind="directory"))
    for root in _python_cache_search_roots():
        if not root.exists():
            continue
        for path in _walk_project_paths(root):
            if path.is_dir() and path.name in names:
                candidates.append(_candidate_for_path(path, kind="directory"))
    return _collapse_nested_candidates(_dedupe_candidates(candidates))


def _collect_temp_artifacts() -> list[ResetCandidate]:
    candidates: list[ResetCandidate] = []
    workspace = developer_sandbox.formal_workspace_path(PROJECT_ROOT)
    if workspace.exists():
        for path in workspace.glob("tmp-*"):
            if path.exists():
                candidates.append(_candidate_for_path(path, kind="directory" if path.is_dir() else "file"))
    runtime_root = PROJECT_ROOT / ".runtime"
    if runtime_root.exists():
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.html", "*.htm", "*.log", "*.txt"):
            for path in runtime_root.glob(pattern):
                if path.is_file():
                    candidates.append(_candidate_for_path(path, kind="file"))
    return _dedupe_candidates(candidates)


def _collect_root_temp_artifacts() -> list[ResetCandidate]:
    candidates: list[ResetCandidate] = []
    exact_names = {
        ".tmp",
        "tmp",
        "tmp-research-debug",
        "tmp_prompt_debug",
        ".codex-temp",
        ".tmp-vite-chat2.log",
    }
    for name in sorted(exact_names):
        path = PROJECT_ROOT / name
        if path.exists():
            candidates.append(_candidate_for_path(path, kind="directory" if path.is_dir() else "file"))
    for path in PROJECT_ROOT.glob("tmp-*"):
        if path.name in exact_names or not path.exists():
            continue
        candidates.append(_candidate_for_path(path, kind="directory" if path.is_dir() else "file"))
    for path in PROJECT_ROOT.glob(".tmp-*.log"):
        if path.name in exact_names or not path.is_file():
            continue
        candidates.append(_candidate_for_path(path, kind="file"))
    return _collapse_nested_candidates(_dedupe_candidates(candidates))


def _collect_runtime_preview_artifacts() -> list[ResetCandidate]:
    runtime_root = PROJECT_ROOT / ".runtime"
    if not runtime_root.exists():
        return [_candidate_for_path(runtime_root, kind="directory", missing=True)]
    current_profile = _current_browser_profile_dir()
    explicit_dirs = [
        runtime_root / "codex-preview",
        runtime_root / "codex-reset-server",
        runtime_root / "codex-ui-check",
    ]
    candidates: list[ResetCandidate] = [
        _candidate_for_path(path, kind="directory", missing=not path.exists()) for path in explicit_dirs
    ]
    for path in runtime_root.glob("tmp-*"):
        if path.exists():
            candidates.append(_candidate_for_path(path, kind="directory" if path.is_dir() else "file"))
    for pattern in ("*preview*.log", "*smoke*.log", "*ui-check*.log", "*reset-server*.log"):
        for path in runtime_root.glob(pattern):
            if path.is_file():
                candidates.append(_candidate_for_path(path, kind="file"))
    if current_profile is not None:
        candidates = [
            candidate for candidate in candidates
            if not _same_or_child(candidate.path, current_profile)
        ]
    return _collapse_nested_candidates(_dedupe_candidates(candidates))


def _collect_web_dist() -> list[ResetCandidate]:
    path = PROJECT_ROOT / "web" / "dist"
    return [_candidate_for_path(path, kind="directory", missing=not path.exists())]


def _execute_delete_candidate(candidate: ResetCandidate) -> ResetActionResult:
    try:
        if not candidate.path.exists():
            result = ResetActionResult("skipped", candidate.path, candidate.kind, candidate.action, "missing")
            _record_reset_candidate_event(result)
            return result
        if candidate.path.is_file() or candidate.path.is_symlink():
            candidate.path.unlink()
        elif candidate.path.is_dir():
            shutil.rmtree(candidate.path)
        else:
            result = ResetActionResult("skipped", candidate.path, candidate.kind, candidate.action, "unsupported path type")
            _record_reset_candidate_event(result)
            return result
    except Exception as exc:
        result = ResetActionResult("failed", candidate.path, candidate.kind, candidate.action, str(exc))
        _record_reset_candidate_event(result)
        return result
    result = ResetActionResult("deleted", candidate.path, candidate.kind, candidate.action)
    _record_reset_candidate_event(result)
    return result


def _record_reset_candidate_event(result: ResetActionResult) -> None:
    if result.status == "deleted":
        level = "info"
        outcome = "succeeded"
    elif result.status == "failed":
        level = "error"
        outcome = "failed"
    else:
        level = "warning"
        outcome = "skipped"
    _record_reset_scene_event(
        "delete",
        f"reset.candidate.{result.status}",
        message=f"Reset candidate {result.status}: {_relative_path(result.path)}",
        level=level,
        outcome=outcome,
        fields={
            "path": _relative_path(result.path),
            "kind": result.kind,
            "action": result.action,
            "message": result.message,
        },
    )


def _definitions_for_ids(item_ids: list[str] | tuple[str, ...]) -> list[ResetItemDefinition]:
    normalized: list[str] = []
    for raw in item_ids:
        item_id = str(raw or "").strip()
        if item_id and item_id not in normalized:
            normalized.append(item_id)
    if not normalized:
        raise ValueError("Select at least one reset item")
    by_id = {definition.id: definition for definition in _reset_items()}
    unknown = [item_id for item_id in normalized if item_id not in by_id]
    if unknown:
        raise ValueError(f"Unknown reset item id: {', '.join(unknown)}")
    return [by_id[item_id] for item_id in normalized]


def _candidate_for_path(
    path: Path,
    *,
    kind: str,
    action: str = "delete",
    note_zh: str = "",
    note_en: str = "",
    protected: bool = False,
    missing: bool = False,
) -> ResetCandidate:
    resolved = _resolve_project_path(path)
    return ResetCandidate(
        path=resolved,
        kind=kind,
        action=action,
        note_zh=note_zh,
        note_en=note_en,
        protected=protected,
        missing=missing or not resolved.exists(),
    )


def _resolve_project_path(path: Path) -> Path:
    candidate = path.resolve()
    root = PROJECT_ROOT.resolve()
    workspace_root = developer_sandbox.formal_workspace_path(root).resolve()
    try:
        candidate.relative_to(root)
        return candidate
    except ValueError:
        pass
    try:
        candidate.relative_to(workspace_root)
        return candidate
    except ValueError as exc:
        raise ValueError("Reset paths must stay inside the project root or the Vibelution data workspace") from exc


def _candidate_is_deletable(candidate: ResetCandidate) -> bool:
    return not candidate.protected and (candidate.path.exists() or candidate.action == "reset")


def _candidate_payload(candidate: ResetCandidate, lang: str) -> dict:
    size_bytes = 0 if candidate.protected else _path_size(candidate.path) if candidate.path.exists() else 0
    file_count = 0 if candidate.protected else _path_file_count(candidate.path) if candidate.path.exists() else 0
    return {
        "path": _relative_path(candidate.path),
        "kind": candidate.kind,
        "action": candidate.action,
        "sizeBytes": size_bytes,
        "fileCount": file_count,
        "message": _candidate_note(candidate, lang),
    }


def _result_payload(result: ResetActionResult) -> dict:
    return {
        "path": _relative_path(result.path),
        "kind": result.kind,
        "action": result.action,
        "status": result.status,
        "message": result.message,
    }


def _candidate_note(candidate: ResetCandidate, lang: str) -> str:
    return text_for(lang, zh=candidate.note_zh, en=candidate.note_en) if candidate.note_zh or candidate.note_en else ""


def _localized(definition: ResetItemDefinition, field: str, lang: str) -> str:
    zh = getattr(definition, f"{field}_zh")
    en = getattr(definition, f"{field}_en")
    return text_for(lang, zh=zh, en=en)


def _localized_category(definition: ResetItemDefinition, lang: str) -> str:
    zh = definition.category_zh
    en = definition.category_en
    if not zh or not en:
        zh, en = RESET_CATEGORY_LABELS.get(definition.category, RESET_CATEGORY_LABELS["runtime_artifacts"])
    return text_for(lang, zh=zh, en=en)


def _localized_rebuild_hint(definition: ResetItemDefinition, lang: str) -> str:
    if not definition.rebuild_hint_zh and not definition.rebuild_hint_en:
        return ""
    return text_for(lang, zh=definition.rebuild_hint_zh, en=definition.rebuild_hint_en)


def _relative_path(path: Path) -> str:
    resolved = path.resolve()
    workspace_root = developer_sandbox.formal_workspace_path(PROJECT_ROOT).resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        pass
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _sum_existing_size(candidates: Iterable[ResetCandidate]) -> int:
    return sum(_path_size(candidate.path) for candidate in candidates if candidate.path.exists())


def _sum_file_count(candidates: Iterable[ResetCandidate]) -> int:
    return sum(_path_file_count(candidate.path) for candidate in candidates if candidate.path.exists())


def _sum_existing_totals(
    candidates: Iterable[ResetCandidate],
    *,
    max_scan_items: int | None = None,
) -> dict[str, Any]:
    size_bytes = 0
    file_count = 0
    scanned = 0
    scan_truncated = False
    for candidate in candidates:
        path = candidate.path
        if not path.exists():
            continue
        try:
            if path.is_file():
                if max_scan_items is not None and scanned >= max_scan_items:
                    scan_truncated = True
                    break
                file_count += 1
                size_bytes += int(path.stat().st_size)
                scanned += 1
                continue
            if not path.is_dir():
                continue
            for child in path.rglob("*"):
                if max_scan_items is not None and scanned >= max_scan_items:
                    scan_truncated = True
                    break
                scanned += 1
                try:
                    if child.is_file():
                        file_count += 1
                        size_bytes += int(child.stat().st_size)
                except OSError:
                    continue
            if scan_truncated:
                break
        except OSError:
            continue
    return {
        "sizeBytes": size_bytes,
        "fileCount": file_count,
        "scanTruncated": scan_truncated,
    }


def _sum_result_file_count(results: Iterable[ResetActionResult]) -> int:
    return sum(1 for _ in results)


def _path_file_count(path: Path) -> int:
    try:
        if path.is_file():
            return 1
        if path.is_dir():
            count = 0
            scanned = 0
            for child in path.rglob("*"):
                scanned += 1
                if scanned > MAX_SUMMARY_SCAN_ITEMS:
                    break
                if child.is_file():
                    count += 1
            return count
    except OSError:
        return 0
    return 0


def _path_size(path: Path) -> int:
    try:
        if path.is_file():
            return int(path.stat().st_size)
        if path.is_dir():
            total = 0
            scanned = 0
            for child in path.rglob("*"):
                scanned += 1
                if scanned > MAX_SUMMARY_SCAN_ITEMS:
                    break
                try:
                    if child.is_file():
                        total += int(child.stat().st_size)
                except OSError:
                    continue
            return total
    except OSError:
        return 0
    return 0


def _format_size(size_bytes: int) -> str:
    value = float(max(0, int(size_bytes or 0)))
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size_bytes)} B"


def _total_from_item_results(items: list[dict]) -> dict:
    totals = {
        "deleteCount": 0,
        "deleteFileCount": 0,
        "deleteSizeBytes": 0,
        "deletedCount": 0,
        "deletedFileCount": 0,
        "deletedSizeBytes": 0,
        "skippedCount": 0,
        "protectedCount": 0,
        "failedCount": 0,
    }
    for item in items:
        summary = item.get("summary") if isinstance(item, dict) else {}
        if not isinstance(summary, dict):
            continue
        for key in totals:
            totals[key] += int(summary.get(key) or 0)
    return totals


def _preview_summary(totals: dict, lang: str) -> str:
    return text_for(
        lang,
        zh=(
            f"预览到 {totals.get('deleteCount', 0)} 个待处理目标，"
            f"约 {_format_size(totals.get('deleteSizeBytes', 0))}，"
            f"{totals.get('protectedCount', 0)} 个受保护目标会跳过。"
        ),
        en=(
            f"Preview found {totals.get('deleteCount', 0)} target(s), "
            f"about {_format_size(totals.get('deleteSizeBytes', 0))}, "
            f"with {totals.get('protectedCount', 0)} protected target(s) skipped."
        ),
    )


def _execute_summary(totals: dict, lang: str) -> str:
    return text_for(
        lang,
        zh=(
            f"清理完成：{totals.get('deletedCount', 0)} 个目标已处理，"
            f"{totals.get('skippedCount', 0)} 个跳过，"
            f"{totals.get('failedCount', 0)} 个失败。"
        ),
        en=(
            f"Cleanup complete: {totals.get('deletedCount', 0)} target(s) handled, "
            f"{totals.get('skippedCount', 0)} skipped, "
            f"{totals.get('failedCount', 0)} failed."
        ),
    )


def _collect_rebuild_hints(definitions: list[ResetItemDefinition], lang: str) -> list[str]:
    hints: list[str] = []
    for definition in definitions:
        hint = _localized_rebuild_hint(definition, lang)
        if hint and hint not in hints:
            hints.append(hint)
    return hints


def _is_conversation_log_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.startswith("conversation_")
        or name.startswith("debug_")
        or name.startswith("transcript")
        or name.endswith(".jsonl")
        or name.endswith(".log")
    )


def _runtime_scene_status(scene_dir: Path) -> str:
    try:
        manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(manifest, dict):
        return "unknown"
    return str(manifest.get("status") or "unknown").strip().lower() or "unknown"


def _launcher_state() -> dict[str, Any]:
    path = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _current_runtime_scene_dir() -> Path | None:
    raw = str(_launcher_state().get("runtimeSceneDir") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).resolve()
    except OSError:
        return None
    root = (PROJECT_ROOT / "logs" / "runtime_scenes").resolve()
    if not _is_relative_to(path, root):
        return None
    return path if path.exists() else None


def _current_browser_profile_dir() -> Path | None:
    raw = str(_launcher_state().get("browserProfileDir") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).resolve()
    except OSError:
        return None
    runtime_root = (PROJECT_ROOT / ".runtime").resolve()
    if not _is_relative_to(path, runtime_root):
        return None
    return path if path.exists() else None


def _iter_runtime_profile_dirs(runtime_root: Path):
    """Discover browser profiles from bounded .runtime locations without walking profile contents."""

    try:
        top_level_dirs = [path for path in runtime_root.iterdir() if path.is_dir()]
    except OSError:
        return
    for path in sorted(top_level_dirs, key=lambda item: item.name.lower()):
        lowered = path.name.lower()
        if "profile" in lowered:
            yield path
        try:
            child_dirs = [child for child in path.iterdir() if child.is_dir()]
        except OSError:
            continue
        for child in sorted(child_dirs, key=lambda item: item.name.lower()):
            if "profile" in child.name.lower():
                yield child


def _python_cache_search_roots() -> list[Path]:
    """Return bounded Python-bearing roots for cache discovery."""

    names = ("config", "core", "scripts", "tests", "tools")
    return [PROJECT_ROOT / name for name in names]


def _walk_project_paths(root: Path, *, skip_roots: list[Path] | None = None):
    resolved_root = _resolve_project_path(root)
    resolved_skips = [path.resolve() for path in list(skip_roots or []) if path is not None]
    for current, dirnames, filenames in os.walk(resolved_root, topdown=True):
        current_path = Path(current).resolve()
        if _has_ignored_part(current_path) or any(_same_or_child(current_path, skip) for skip in resolved_skips):
            dirnames[:] = []
            continue
        kept_dirs: list[str] = []
        for dirname in dirnames:
            child = (current_path / dirname).resolve()
            if _has_ignored_part(child) or any(_same_or_child(child, skip) for skip in resolved_skips):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for dirname in kept_dirs:
            yield current_path / dirname
        for filename in filenames:
            yield current_path / filename


def _has_ignored_part(path: Path) -> bool:
    ignored = {".venv", "node_modules", ".git"}
    return any(part in ignored for part in path.parts)


def _dedupe_candidates(candidates: Iterable[ResetCandidate]) -> list[ResetCandidate]:
    seen: set[str] = set()
    result: list[ResetCandidate] = []
    for candidate in candidates:
        key = str(candidate.path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _collapse_nested_candidates(candidates: list[ResetCandidate]) -> list[ResetCandidate]:
    collapsed: list[ResetCandidate] = []
    for candidate in sorted(candidates, key=lambda item: len(item.path.parts)):
        if candidate.protected:
            collapsed.append(candidate)
            continue
        if any(
            not existing.protected and _is_relative_to(candidate.path, existing.path)
            for existing in collapsed
        ):
            continue
        collapsed.append(candidate)
    return collapsed


def _same_path(left: Path, right: Path) -> bool:
    return str(left.resolve()).lower() == str(right.resolve()).lower()


def _same_or_child(path: Path, parent: Path) -> bool:
    return _same_path(path, parent) or _is_relative_to(path, parent)


def _is_relative_to(path: Path | None, parent: Path | None) -> bool:
    if path is None or parent is None:
        return False
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
