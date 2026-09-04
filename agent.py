import os
import copy
import hashlib
import json
import sys
import time
import traceback
import re
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4
# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# 导入配置
# ============================================================================
from config import AppConfig
from config.settings import get_config

# ============================================================================
# 导入日志模块
# ============================================================================
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger
from core.logging.setup import setup_logging, print_evolution_time as _print_evolution_time_core

# ============================================================================
# 导入核心模块（Core First）
# ============================================================================
from core.infrastructure.state import AgentState, get_state_manager
from core.infrastructure.event_bus import get_event_bus
from core.infrastructure.tool_result import truncate_result  # noqa: F401
from core.infrastructure.tool_result import (
    compact_tool_output_for_diagnosis,
    infer_result_from_tool_outputs,
    RuntimeToolMetadata,
)
from core.infrastructure.security import get_security_validator
from core.infrastructure.agent_session import get_session_state
from core.infrastructure.tool_executor import get_tool_executor
from core.infrastructure.git_memory import get_git_memory_service
from core.infrastructure.llm_utils import (
    build_cacheable_system_prefix_message,
    build_dynamic_system_context_message,
    build_system_message,
    extend_system_message_cacheable_prefix,
    is_dynamic_system_context_message,
    is_volatile_system_context_message,
    MAX_CONSECUTIVE_FAILURES,
    parse_tool_args,
    plan_llm_recovery,
)
from core.orchestration.turn_status_bar import (
    build_turn_status_bar_message,
    collect_turn_status_snapshot,
    strip_turn_status_bar_messages,
    upsert_turn_status_bar_message,
)
from core.runtime_status_flags import is_runtime_status_inject_enabled
from core.infrastructure.cli_utils import create_config_from_args, parse_args, should_launch_workbench
from core.infrastructure.boot_pipeline import (
    configure_console_encoding,
    initialize_ui_for_run,
    run_agent_main,
    run_preflight_doctor,
    set_ui_test_mode,
)

# LangChain 核心组件
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage

from core.infrastructure.runtime_input import (
    build_chat_user_message,
    build_chat_user_multimodal_message,
    build_external_request_message,
    build_runtime_notice_message,
)
from core.evaluation.chat_dataset_capture import ChatDatasetCaptureService
from core.evaluation.chat_segmenter import ChatTurnRecord
from core.chat.chat_result_contract import build_chat_coding_result_contract
from core.chat.model_messages import normalize_model_messages
from core.orchestration.output_boundary import sanitize_assistant_visible_text
from core.orchestration.cache_diagnostics import (
    build_llm_usage_from_observation,
    build_runtime_cache_composition,
    build_runtime_context_composition,
)

from core.llm import (
    LLMError,
    LLMInvocationContext,
    discover_model,
    doctor_llm_profile,
    get_llm_client,
    invoke_llm,
    stream_llm,
)
from core.llm.client import current_llm_status_context, llm_cancel_context
from core.llm.invocation import invoke_llm_outcome, run_streaming_llm_outcome
from core.llm.legacy_xml_tool_decoder import canonical_outcome_from_message, canonicalize_legacy_xml_outcome
from core.llm.semantic_messages import InvocationScope
from core.llm.payload_builder import prompt_cache_partition_scope
from core.llm.agent_runtime import (
    AGENT_LLM_SLOT_MENTAL_MODEL,
    AGENT_LLM_SLOT_SUBAGENT_EXECUTION,
    AGENT_LLM_SLOT_SUMMARY,
    AgentLlmResolutionError,
    normalize_agent_llm_bindings,
    resolve_agent_llm,
)

# 导入工具
from tools import Key_Tools
from tools.token_manager import (
    EnhancedTokenCompressor,
    estimate_messages_tokens,
    estimate_messages_tokens_for_threshold,
    estimate_tokens_precise,
    is_compression_requested,
    consume_compression_request,
    request_compression,
)
from tools.compression_strategy import (
    CompressionLevel,
    CompressionStrategy,
    CompressionThresholds,
    get_compression_strategy,
)
from tools.memory_tools import get_current_goal
from tools.rebirth_tools import handle_restart_request  # noqa: F401


# 导入 CLI UI
from core.ui.cli_ui import get_ui, ui_error
from core.ui.workbench import AgentWorkbenchShell
from core.ui.token_display import print_tokens
from core.prompt_manager import (
    build_restart_focus_state_memory,
    build_state_memory_key,
    compose_state_memory,
    get_prompt_manager,
    to_string,
)
from core.prompt_manager.core_prompt_sources import CORE_PROMPT_NAMES
from core.prompt_manager.provider_adapters import (
    build_prompt_assembly_context,
    build_protocol_adapter_section,
    client_supports_tool_calling,
)
from core.prompt_manager.task_analyzer import get_task_analyzer
from core.orchestration.evolution_lifecycle import (
    is_full_evolution_goal,
    is_restart_focused_goal,
)
from core.orchestration.agent_modes import (
    AgentMode,
    ModePolicy,
    normalize_agent_mode,
    resolve_mode_policy,
)
from core.orchestration.runtime_goal import build_runtime_goal_packet
from core.orchestration.round_state import RoundStateController
from core.orchestration.response_processor import ResponseProcessor, ResponseProcessingResult
from core.orchestration.response_surface import ResponseSurfaceController
from core.orchestration.turn_outcome import LifecycleDecision, TurnOutcomeController
from core.orchestration.tool_lifecycle import ToolLifecycleBridge
from core.orchestration.context_engine import build_agent_context
from core.orchestration.subagent_roles import extract_subagent_primary_goal
from core.llm.reasoning_extractor import (
    ThinkTagStreamParser,
    extract_reasoning_text,
    strip_think_tag_reasoning,
)
from core.infrastructure.mental_model import get_mental_model
from core.infrastructure.feature_gate import resolve_feature_decision
from core.mental_model_flags import is_mental_model_enabled

# 导入宠物系统
from core.pet_system import get_pet_system

# 进化测试提示
EVOLUTION_TEST_PROMPT = "制定重启任务，然后对重启任务打勾，然后运行 `trigger_self_restart_tool` 重启你自己。"

from core.orchestration.agent_runtime_bindings import (
    SUBAGENT_RESULT_MARKER,
    _ASSISTANT_GOAL_CONTEXT_KEYWORDS,
    _CONFIRMATION_KEYWORDS,
    _CORE_CHAT_TOOL_NAMES,
    _NUMBERED_CONFIRMATION_RE,
    _SAFE_LLM_ERROR_DIAGNOSTIC_DETAIL_KEYS,
    _SESSION_CHAT_PROMPT_GOAL,
    _STALL_SIGNAL_THRESHOLDS,
    _TOOL_SURFACE_GROUPS,
    _agent_api_key_diagnostic,
    _can_reuse_initial_prompt,
    _can_reuse_system_prompt,
    _compact_goal_context,
    _compact_one_line,
    _context_compression_trigger_source,
    _format_missing_api_key_error,
    _format_tool_result_replacement_summary,
    _latest_assistant_goal_context,
    _llm_effective_route_id,
    _llm_effective_route_identity,
    _llm_route_trace_fields,
    _looks_like_numbered_confirmation,
    _message_content,
    _message_role,
    _normalize_goal_from_chat_history,
    _provider_rejected_responses_continuation,
    _record_agent_scene_event,
    _record_agent_tool_surface_event as _record_agent_tool_surface_event_core,
    _record_llm_route_success as _record_llm_route_success_core,
    _reset_stall_signal_reported,
    _runtime_agent_binding_from_env,
    _runtime_agent_llm_bindings_from_env,
    _runtime_mental_model_override_from_env,
    _safe_llm_error_diagnostic_details,
    _safe_turn_runtime_metadata,
    _stall_signal_threshold_events,
    _turn_runtime_from_env,
)
from core.orchestration.turn_carryover import (
    deserialize_turn_messages,
    serialize_turn_message,
    serialize_turn_messages,
)
from core.orchestration.turn_compression import (
    compress_turn_messages,
    evaluate_context_budget_preflight,
)
from core.orchestration.turn_diagnostics import (
    build_llm_invocation_context,
    publish_llm_retry_status,
    record_turn_cache_diagnostics,
    report_round_state_stall_signals,
)
from core.orchestration.tool_authorization_binding import (
    guard_restart_focus_tool,
    hidden_tool_call_message,
    is_tool_visible_to_agent,
    materialize_authorized_tools,
    resolve_turn_authorization,
    restart_allowed_tool_names,
)
from core.orchestration.turn_message_assembly import (
    TurnJournalReplayError,
    assemble_prepared_turn_messages,
    current_turn_has_journal_conversation_layer,
    insert_pending_volatile_context_messages,
    ledger_conversation_fingerprint_for_messages,
    normalize_seeded_tool_calls,
    reconcile_chat_messages_with_ledger,
    refresh_system_prefix_on_messages,
    replay_current_turn_messages,
    sanitize_seeded_chat_content,
)
from core.orchestration.turn_llm_adapter import (
    AgentLlmTurnHooks,
    invoke_agent_llm_turn,
)


def _record_llm_route_success(*args, **kwargs):
    # Removal: drop when tests stop patching agent._record_agent_scene_event.
    if "recorder" not in kwargs:
        kwargs["recorder"] = _record_agent_scene_event
    return _record_llm_route_success_core(*args, **kwargs)


def _record_agent_tool_surface_event(*args, **kwargs):
    # Removal: drop when tests stop patching agent._record_agent_scene_event.
    if "recorder" not in kwargs:
        kwargs["recorder"] = _record_agent_scene_event
    return _record_agent_tool_surface_event_core(*args, **kwargs)


class TurnStopRequested(Exception):
    """Raised when the active single turn received a web stop request."""

# ============================================================================
# Self-Evolving Agent 主类
# ============================================================================

class SelfEvolvingAgent:
    """
    自我进化 Agent 主类

    基于 LangChain 框架构建，使用 ReAct 风格的 Agent 架构。
    支持定时苏醒，主动思考优化方向。
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        mode: Optional[str] = None,
        workspace_path: Optional[str] = None,
        runtime_agent_binding: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化 Agent 实例"""
        self.config = config or get_config()
        self.runtime_agent_binding = _runtime_agent_binding_from_env(runtime_agent_binding)
        self._runtime_agent_llm_resolution = None
        self._apply_runtime_agent_profile_binding()
        self._apply_runtime_agent_llm_slot_binding()
        self.name = self.config.agent.name
        self.mode = normalize_agent_mode(mode or getattr(self.config.agent, "default_mode", None))
        self.mode_policy = resolve_mode_policy(self.mode, self.config)

        # API Key 检查
        self.api_key = self.config.get_api_key()
        if not self.api_key:
            provider = self.config.llm.get_provider(role="primary")
            if provider.requires_api_key:
                diagnostic = _agent_api_key_diagnostic(self.config)
                _record_agent_scene_event(
                    "startup",
                    "agent.api_key.missing",
                    message="Agent startup blocked because the selected LLM route has no API key.",
                    level="error",
                    outcome="failed",
                    fields={
                        **diagnostic,
                        "agentId": str(self.runtime_agent_binding.get("agentId") or "").strip(),
                        "requestedLlmSlot": str(self.runtime_agent_binding.get("llmSlot") or "dialogue").strip()
                        or "dialogue",
                    },
                )
                raise ValueError(_format_missing_api_key_error(diagnostic))
        self.config.set_api_key(self.api_key or "")

        # 创建主要工具
        llm_facing_tools = Key_Tools.create_llm_facing_tools()
        authorization_report = self._resolve_tool_authorization(llm_facing_tools)
        self.key_tools = self._materialize_authorized_tools(llm_facing_tools, authorization_report)
        self._tool_authorization_decision_fingerprint = str(
            getattr(getattr(authorization_report, "decision", None), "decision_fingerprint", "") or ""
        ).strip()
        self.key_tool_maps = {tool.name for tool in self.key_tools}
        self._key_tool_map = {
            tool.name: tool for tool in self.key_tools if getattr(tool, "name", "")
        }
        _record_agent_tool_surface_event(sorted(self.key_tool_maps))
        self._bound_llm_cache: Dict[str, Any] = {}
        self._context_compression_policy: Dict[str, Any] = {}
        self._compression_strategy: Optional[CompressionStrategy] = None

        # 模型动态发现
        self._effective_max_token_limit = self._init_model_discovery()
        self._apply_runtime_agent_context_compression_policy()
        # LLM 初始化（使用工厂）
        self._init_llm()
        # Token 压缩器
        self._init_token_compressor()
        # Prompt 管理器
        self.prompt_manager = get_prompt_manager()

        # 全局状态
        self.global_recent_actions = []
        self.global_consecutive_count = 0
        self._self_modified = False
        self.start_time = datetime.now()

        # 压缩追踪
        self._compression_count_this_turn = 0
        self._last_compression_iteration = 0
        self._compression_min_iteration_gap = 2

        # 网络退避追踪
        self._last_turn_failed = False
        self._consecutive_failed_turns = 0

        # 工作区域
        project_root = os.path.dirname(os.path.abspath(__file__))
        self.project_root = project_root
        if workspace_path:
            candidate_workspace = Path(workspace_path)
            if not candidate_workspace.is_absolute():
                candidate_workspace = Path(project_root) / candidate_workspace
            self.workspace_path = str(candidate_workspace.resolve())
        else:
            workspace_dir = getattr(self.config.agent, 'workspace', 'workspace')
            self.workspace_path = os.path.join(project_root, workspace_dir)
        os.makedirs(self.workspace_path, exist_ok=True)

        # 核心组件
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self.tool_executor = get_tool_executor()
        set_cancel_checker = getattr(self.tool_executor, "set_cancel_checker", None)
        if callable(set_cancel_checker):
            set_cancel_checker(self._current_turn_stop_reason, owner=self)
        self.security_validator = get_security_validator(project_root)
        self.git_memory = get_git_memory_service()
        self.tool_lifecycle = ToolLifecycleBridge(
            tool_executor_execute=self.tool_executor.execute,
            tool_guard=self._guard_tool_execution,
            tool_result_observer=self._remember_tool_output,
            runtime_metadata_observer=self._remember_runtime_tool_metadata,
            post_close_action_pending=self._expects_restart_after_transaction_close,
            self_modified=self._self_modified,
        )
        self.response_processor = ResponseProcessor()

        # 心智模型（元认知引擎 — 必须在 EventBus 之后初始化）
        self.mental_model = get_mental_model(workspace_root=self.workspace_path)
        mental_model_decision = resolve_feature_decision(
            "mental_model",
            config=self.config,
        )
        _record_agent_scene_event(
            "startup",
            "agent.feature.decision",
            message="已解析心智模型可信配置。",
            fields=mental_model_decision.log_fields(),
        )
        if mental_model_decision.effective_enabled:
            self.mental_model.set_shared_llm(
                self._get_llm_for_agent_slot(
                    AGENT_LLM_SLOT_MENTAL_MODEL,
                    disable_tools=True,
                )
                or self.llm_with_tools
            )

        self._system_prompt_written = False
        self._last_runtime_state_memory = ""
        self._last_runtime_state_memory_key = ""
        self._carryover_state_memory = ""
        self._pending_lifecycle_action: Optional[str] = None
        self._last_llm_error_category: Optional[str] = None
        self._last_llm_error_retryable: bool = False
        self._last_llm_recovery_action: Optional[str] = None
        self._last_llm_error_message: str = ""
        self._last_llm_error_details: Dict[str, Any] = {}
        self._last_llm_failure_attempts: int = 0
        self._last_llm_failure_max_attempts: int = 0
        self._last_visible_response_text: str = ""
        self._last_response_tool_calls: int = 0
        self._recent_tool_outputs: List[str] = []
        self._recent_tool_records: List[Dict[str, Any]] = []
        self._active_goal: str = ""
        self._active_turn_messages: Optional[List[Any]] = None
        self._active_turn_goal: str = ""
        self._active_turn_identity: str = ""
        self._active_turn_terminal: bool = False
        self._pending_static_context_blocks: List[str] = []
        self._pending_runtime_context_blocks: List[str] = []
        self._pending_volatile_context_blocks: List[str] = []
        self._runtime_context_seeded_by_host: bool = False
        self._core_prompt_snapshot_seeded_by_host: bool = False
        self._chat_provider_replay_state = None
        self._ledger_conversation_fingerprint: str = ""
        self._single_turn_mode_active: bool = False
        self._last_turn_metadata: Dict[str, Any] = {}
        self._turn_interrupt_checker = None
        self._mental_model_enabled_override: Optional[bool] = None
        self._runtime_status_enabled_override: Optional[bool] = None
        if self._mental_model_enabled_override is not None:
            _record_agent_scene_event(
                "startup",
                "agent.mental_model.supervised_override_applied",
                message="监督运行按本轮策略覆盖心智模型开关。",
                fields={
                    "enabled": bool(self._mental_model_enabled_override),
                    "supervisedRole": self.runtime_agent_binding.get("supervisedRole", ""),
                    "agentId": self.runtime_agent_binding.get("agentId", ""),
                },
            )
        self._chat_turn_records: List[ChatTurnRecord] = []
        self._active_supervised_case_id: str = ""
        self._pending_supervised_case_id: Optional[str] = None
        self.chat_dataset_capture = ChatDatasetCaptureService(
            project_root=Path(self.project_root),
            config=self.config,
        )
        self._load_previous_session_constraints()

    def _apply_runtime_agent_profile_binding(self) -> None:
        profile_id = str(self.runtime_agent_binding.get("profileId") or "").strip()
        if not profile_id or profile_id == "primary":
            return
        if profile_id not in self.config.llm.profiles:
            _record_agent_scene_event(
                "startup",
                "agent.runtime_profile_binding_missing",
                message="运行时 Agent profile 绑定未找到，继续使用 primary profile。",
                fields={
                    "agentId": self.runtime_agent_binding.get("agentId", ""),
                    "agentProfileId": profile_id,
                    "supervisedRole": self.runtime_agent_binding.get("supervisedRole", ""),
                    "agentWorkspacePath": self.runtime_agent_binding.get("workspacePath", ""),
                },
            )
            return
        self.config = copy.deepcopy(self.config)
        selected = copy.deepcopy(self.config.llm.profiles[profile_id])
        selected.profile_id = "primary"
        self.config.llm.profiles["primary"] = selected
        _record_agent_scene_event(
            "startup",
            "agent.runtime_profile_bound",
            message="运行时 Agent profile 已映射为本次 primary profile。",
            fields={
                "agentId": self.runtime_agent_binding.get("agentId", ""),
                "agentProfileId": profile_id,
                "supervisedRole": self.runtime_agent_binding.get("supervisedRole", ""),
                "agentWorkspacePath": self.runtime_agent_binding.get("workspacePath", ""),
            },
        )

    def _apply_runtime_agent_llm_slot_binding(self) -> None:
        agent_id = str(self.runtime_agent_binding.get("agentId") or "").strip()
        llm_slot = str(self.runtime_agent_binding.get("llmSlot") or "").strip()
        profile_id = str(self.runtime_agent_binding.get("profileId") or "").strip()
        if not agent_id:
            return
        if not llm_slot and profile_id and profile_id != "primary":
            return
        requested_slot = llm_slot or "dialogue"
        try:
            from core.web.services import agent_directory_service

            agent = agent_directory_service.get_agent(agent_id, include_archived=False)
            agent = self._agent_with_runtime_llm_binding_snapshot(agent)
            if not llm_slot:
                bindings = agent.get("llmBindings") if isinstance(agent, dict) else {}
                dialogue_binding = bindings.get("dialogue") if isinstance(bindings, dict) else None
                if not isinstance(dialogue_binding, dict) or not str(dialogue_binding.get("modelId") or "").strip():
                    _record_agent_scene_event(
                        "startup",
                        "agent.runtime_llm_dialogue_binding_skipped",
                        message="运行时 Agent 未声明 dialogue LLM 绑定，保留当前 primary profile。",
                        fields={
                            "agentId": agent_id,
                            "requestedLlmSlot": requested_slot,
                            "supervisedRole": self.runtime_agent_binding.get("supervisedRole", ""),
                            "agentWorkspacePath": self.runtime_agent_binding.get("workspacePath", ""),
                        },
                    )
                    return
            resolved = resolve_agent_llm(
                agent,
                requested_slot,
                config=self.config,
                fallback_to_dialogue=False,
            )
        except Exception as exc:
            _record_agent_scene_event(
                "startup",
                "agent.runtime_llm_slot_binding_failed",
                message="运行时 Agent LLM 绑定解析失败，已阻止启动以避免回退到错误模型。",
                level="error",
                outcome="failed",
                fields={
                    "agentId": agent_id,
                    "requestedLlmSlot": requested_slot,
                    "explicitLlmSlot": bool(llm_slot),
                    "errorType": type(exc).__name__,
                    "errorPreview": str(exc)[:300],
                    "supervisedRole": self.runtime_agent_binding.get("supervisedRole", ""),
                    "agentWorkspacePath": self.runtime_agent_binding.get("workspacePath", ""),
                },
            )
            if isinstance(exc, AgentLlmResolutionError):
                raise
            raise AgentLlmResolutionError(
                f"Runtime Agent LLM slot binding failed for {agent_id}:{requested_slot}: {exc}"
            ) from exc
        self.config = resolved.config or self.config
        self._runtime_agent_llm_resolution = resolved
        _record_agent_scene_event(
            "startup",
            "agent.runtime_llm_slot_bound",
            message="运行时 Agent LLM 已映射为本次 primary profile。",
            fields={
                **resolved.log_fields(),
                "explicitLlmSlot": bool(llm_slot),
                "supervisedRole": self.runtime_agent_binding.get("supervisedRole", ""),
                "agentWorkspacePath": self.runtime_agent_binding.get("workspacePath", ""),
            },
        )

    def _agent_with_runtime_llm_binding_snapshot(self, agent: Any) -> Dict[str, Any]:
        env_bindings = normalize_agent_llm_bindings(self.runtime_agent_binding.get("llmBindings"))
        if not env_bindings:
            return agent if isinstance(agent, dict) else {}
        payload = copy.deepcopy(agent) if isinstance(agent, dict) else {}
        existing_bindings = normalize_agent_llm_bindings(payload.get("llmBindings"))
        payload["llmBindings"] = {**existing_bindings, **env_bindings}
        payload["agentId"] = str(payload.get("agentId") or self.runtime_agent_binding.get("agentId") or "").strip()
        requested_slot = str(self.runtime_agent_binding.get("llmSlot") or "dialogue").strip() or "dialogue"
        _record_agent_scene_event(
            "startup",
            "agent.runtime_llm_env_binding_applied",
            message="运行时 Agent 使用本次监督快照补齐 LLM 绑定。",
            fields={
                "agentId": payload.get("agentId", ""),
                "requestedLlmSlot": requested_slot,
                "envBindingSlots": sorted(env_bindings.keys()),
                "registryAgentPresent": isinstance(agent, dict) and bool(agent),
                "supervisedRole": self.runtime_agent_binding.get("supervisedRole", ""),
                "agentWorkspacePath": self.runtime_agent_binding.get("workspacePath", ""),
            },
        )
        return payload

    def set_mental_model_enabled_override(self, enabled: Optional[bool]) -> None:
        """Override mental-model activity for this agent instance."""

        self._mental_model_enabled_override = None if enabled is None else bool(enabled)

    def set_turn_status_tail_config(self, config: Optional[dict] = None) -> None:
        """Session-level Turn Status Bar composition (blocks/limits)."""
        try:
            from core.orchestration.turn_status_tail_config import normalize_turn_status_tail_config

            self._turn_status_tail_config = normalize_turn_status_tail_config(config)
        except Exception:
            self._turn_status_tail_config = None

    def set_turn_status_tail_context(
        self,
        *,
        session_id: str = "",
        agent_id: str = "",
        task: str = "",
        worktree: str = "",
        cache_hint: Optional[dict] = None,
    ) -> None:
        """Identity / task context for optional tail sections (not secrets)."""
        self._turn_status_tail_context = {
            "session_id": str(session_id or "").strip(),
            "agent_id": str(agent_id or "").strip(),
            "task": str(task or "").strip(),
            "worktree": str(worktree or "").strip(),
            "cache_hint": dict(cache_hint) if isinstance(cache_hint, dict) else None,
        }

    def set_runtime_status_enabled_override(self, enabled: Optional[bool]) -> None:
        """Override runtime-status inject for this agent instance / turn request."""

        self._runtime_status_enabled_override = None if enabled is None else bool(enabled)

    def set_turn_structured_output_contract(self, contract: Any = None) -> None:
        """Bind or clear one server-owned strict final-output contract."""

        self._turn_structured_output_contract = contract

    def is_runtime_status_inject_enabled_for_turn(self) -> bool:
        override = getattr(self, "_runtime_status_enabled_override", None)
        agent = None
        try:
            from core.web.services.agent_directory_service import current_agent_runtime

            runtime = current_agent_runtime() or {}
            agent = runtime.get("agent") if isinstance(runtime.get("agent"), dict) else runtime
        except Exception:
            agent = None
        return is_runtime_status_inject_enabled(
            agent=agent if isinstance(agent, dict) else None,
            requested=override,
        )

    def _llm_identity_for_status(self) -> tuple[str, str, str]:
        model_name = ""
        provider = ""
        profile_id = ""
        try:
            llm_config = self.config.llm
            profile = llm_config.get_profile(role="primary") if hasattr(llm_config, "get_profile") else None
            if profile is not None:
                model_name = str(getattr(profile, "model", "") or "").strip()
                profile_id = str(getattr(profile, "profile_id", "") or getattr(profile, "id", "") or "").strip()
                provider_obj = getattr(profile, "provider", None)
                if provider_obj is not None:
                    provider = str(
                        getattr(provider_obj, "provider_id", "")
                        or getattr(provider_obj, "name", "")
                        or provider_obj
                        or ""
                    ).strip()
            if not model_name:
                model_name = str(getattr(llm_config, "model_name", "") or "").strip()
        except Exception:
            pass
        return model_name, provider, profile_id

    def _apply_turn_status_bar(self, messages: list, *, iteration: int = 0) -> list:
        """Upsert live turn status (budget + optional mental) after the full message trail.

        Must not sit before the current user: a rewritten mid-list status bar severs
        DeepSeek automatic prefix cache so prior tool results never become hits.
        Session may select which tail sections append (git brief/paths, clock, …).
        """

        if not self.is_runtime_status_inject_enabled_for_turn():
            return strip_turn_status_bar_messages(messages)
        model_name, provider, profile_id = self._llm_identity_for_status()
        tool_policy = None
        try:
            from core.web.services.agent_directory_service import current_agent_runtime

            runtime = current_agent_runtime() or {}
            tool_policy = runtime.get("toolPolicy") if isinstance(runtime.get("toolPolicy"), dict) else None
        except Exception:
            tool_policy = None
        mental_enabled = self.is_mental_model_enabled_for_turn()
        snapshot = collect_turn_status_snapshot(
            iteration=iteration,
            model=model_name,
            provider=provider,
            profile_id=profile_id,
            tool_policy=tool_policy,
            mental_enabled=mental_enabled,
            mental_model=self.mental_model if mental_enabled else None,
        )
        tail_config = getattr(self, "_turn_status_tail_config", None)
        tail_ctx = getattr(self, "_turn_status_tail_context", None)
        if not isinstance(tail_ctx, dict):
            tail_ctx = {}
        include_git = False
        try:
            from core.orchestration.turn_status_tail_config import (
                BLOCK_GIT_BRIEF,
                BLOCK_GIT_PATHS,
                block_enabled,
                normalize_turn_status_tail_config,
            )

            cfg = normalize_turn_status_tail_config(tail_config)
            include_git = block_enabled(cfg, BLOCK_GIT_BRIEF) or block_enabled(cfg, BLOCK_GIT_PATHS)
        except Exception:
            cfg = tail_config
            include_git = False
        recent_tools: list[str] = []
        try:
            from core.authorization.tool_authorization_service import current_execution_authorization

            auth = current_execution_authorization()
            recent = getattr(auth, "recent_tool_names", None) or getattr(auth, "tool_names", None)
            if isinstance(recent, (list, tuple)):
                recent_tools = [str(item).strip() for item in recent if str(item).strip()]
        except Exception:
            recent_tools = []
        try:
            from core.orchestration.turn_status_bar import collect_turn_status_tail_extras

            extras = collect_turn_status_tail_extras(
                session_id=str(tail_ctx.get("session_id") or ""),
                agent_id=str(tail_ctx.get("agent_id") or snapshot.agent_id or ""),
                task=str(tail_ctx.get("task") or ""),
                recent_tools=recent_tools,
                include_git=include_git,
                cache_hint=tail_ctx.get("cache_hint") if isinstance(tail_ctx.get("cache_hint"), dict) else None,
                worktree=str(tail_ctx.get("worktree") or ""),
            )
        except Exception:
            extras = {}
        return upsert_turn_status_bar_message(
            messages,
            build_turn_status_bar_message(snapshot, config=cfg, extras=extras),
        )
    def is_mental_model_enabled_for_turn(self) -> bool:
        override = getattr(self, "_mental_model_enabled_override", None)
        return resolve_feature_decision(
            "mental_model",
            config=self.config,
            requested=override,
        ).effective_enabled

    def _init_model_discovery(self):
        """解析模型 max 上下文窗口并派生压缩阈值。

        禁止静默 32k/16k 兜底：窗口未知时直接失败，避免隐藏错误窗口。
        """
        primary_profile_id = self.config.llm.get_role_profile_id("primary")
        doctor = doctor_llm_profile(self.config, primary_profile_id)
        for warning in doctor.warnings:
            _debug_logger.warning(warning, tag="LLM")
        if doctor.errors:
            for item in doctor.errors:
                _debug_logger.error(item, tag="LLM")
        self.model_info = discover_model(self.config, primary_profile_id)
        context_window = int(getattr(self.model_info, "context_window", 0) or 0)
        if context_window <= 0:
            model_name = str(getattr(self.model_info, "model", "") or "").strip() or "unknown"
            message = (
                f"模型 max 上下文窗口未配置（禁止默认兜底）。"
                f"profile={primary_profile_id} model={model_name}。"
                f"请在设置中为该模型/供应商填写 context_window，或先运行模型发现写入后再启动。"
            )
            _debug_logger.error(message, tag="LLM")
            raise RuntimeError(message)
        self._context_window_limit = context_window
        # Compression threshold is derived from the known window; never invent the window itself.
        self._effective_max_token_limit = max(1, int(context_window * 0.5))
        self.config.context_compression.max_token_limit = self._effective_max_token_limit
        try:
            from core.pet_system import get_pet_system
            get_pet_system().update_context_window(self._context_window_limit)
        except Exception:
            pass
        return self._effective_max_token_limit

    def _apply_runtime_agent_context_compression_policy(self) -> None:
        """Apply the bound Agent's context-compression policy to this runtime instance."""

        agent_id = str(self.runtime_agent_binding.get("agentId") or "").strip()
        if not agent_id:
            return
        try:
            from core.web.services import agent_directory_service

            agent = agent_directory_service.get_agent(agent_id, include_archived=False)
            if not isinstance(agent, dict) or not agent:
                return
            policy = agent_directory_service.effective_agent_context_compression_policy(
                agent,
                self.config.context_compression,
                context_window_limit=int(getattr(self, "_context_window_limit", 0) or 0),
            )
        except Exception as exc:
            _record_agent_scene_event(
                "startup",
                "agent.context_compression_policy_failed",
                message="运行时 Agent 上下文压缩策略解析失败，继续使用全局策略。",
                level="warning",
                outcome="fallback",
                fields={
                    "agentId": agent_id,
                    "errorType": type(exc).__name__,
                    "errorPreview": str(exc)[:300],
                },
            )
            return

        self.config = copy.deepcopy(self.config)
        cc = self.config.context_compression
        effective_limit = int(policy.get("effectiveTokenLimit") or getattr(cc, "max_token_limit", 0) or 0)
        if effective_limit > 0:
            cc.max_token_limit = effective_limit
            self._effective_max_token_limit = effective_limit
        cc.enabled = bool(policy.get("enabled", getattr(cc, "enabled", True)))
        max_compressions = policy.get("maxCompressionsPerSession")
        cc.max_compressions_per_session = int(
            max_compressions
            if max_compressions is not None
            else getattr(cc, "max_compressions_per_session", 20) or 20
        )
        levels = policy.get("levels") if isinstance(policy.get("levels"), dict) else {}
        for key in ("light", "standard", "deep", "emergency"):
            if key in levels:
                setattr(cc.levels, key, float(levels[key]))
        summary_chars = policy.get("summaryChars") if isinstance(policy.get("summaryChars"), dict) else {}
        for key in ("light", "standard", "deep", "emergency"):
            if key in summary_chars:
                setattr(cc.summary_chars, key, int(summary_chars[key]))
        preservation = policy.get("preservation") if isinstance(policy.get("preservation"), dict) else {}
        if "keepAiMessages" in preservation:
            cc.preservation.keep_ai_messages = int(preservation.get("keepAiMessages") or 0)
        if "preserveErrors" in preservation:
            cc.preservation.preserve_errors = bool(preservation.get("preserveErrors"))
        if "extractKeyDecisions" in preservation:
            cc.preservation.extract_key_decisions = bool(preservation.get("extractKeyDecisions"))

        self._context_compression_policy = dict(policy)
        # Versioned budget contract (policy v3+): explicit compression trigger,
        # hard input limit and post-compression target override the legacy
        # ratio derivation. Agents without the explicit fields keep the legacy
        # behavior unchanged.
        explicit_trigger = int(policy.get("compressionTriggerTokenLimit") or 0)
        post_target = int(policy.get("postCompressionTargetTokenLimit") or 0)
        self._context_compression_trigger_tokens = max(0, explicit_trigger)
        self._post_compression_target_tokens = max(0, post_target)
        self._context_input_hard_limit = (
            max(0, int(policy.get("effectiveTokenLimit") or 0))
            if explicit_trigger > 0 and post_target > 0
            else 0
        )
        keep_ai_messages = (policy.get("preservation") or {}).get("keepAiMessages")
        if keep_ai_messages is None:
            keep_ai_messages = getattr(cc.preservation, "keep_ai_messages", 5) or 5
        self._compression_strategy = CompressionStrategy(
            CompressionThresholds(
                light_threshold=float(getattr(cc.levels, "light", 0.6)),
                standard_threshold=float(getattr(cc.levels, "standard", 0.8)),
                deep_threshold=float(getattr(cc.levels, "deep", 0.9)),
                emergency_threshold=float(getattr(cc.levels, "emergency", 0.95)),
            ),
            summary_chars=dict(policy.get("summaryChars") or {}),
            keep_ai_messages=int(keep_ai_messages),
            preserve_errors=bool((policy.get("preservation") or {}).get("preserveErrors", getattr(cc.preservation, "preserve_errors", True))),
            extract_key_decisions=bool(
                (policy.get("preservation") or {}).get(
                    "extractKeyDecisions",
                    getattr(cc.preservation, "extract_key_decisions", True),
                )
            ),
        )
        _record_agent_scene_event(
            "startup",
            "agent.context_compression_policy_applied",
            message="运行时 Agent 上下文压缩策略已应用。",
            fields={
                "agentId": agent_id,
                "policyMode": str(policy.get("mode") or "inherit"),
                "policySource": str(policy.get("source") or "global"),
                "enabled": bool(policy.get("enabled", True)),
                "effectiveTokenLimit": self._effective_max_token_limit,
                "contextWindowLimit": int(getattr(self, "_context_window_limit", 0) or 0),
            },
        )

    def _automatic_context_compression_threshold(self) -> float:
        levels = getattr(getattr(self.config, "context_compression", None), "levels", None)
        try:
            threshold = float(getattr(levels, "standard", 0.95))
        except (TypeError, ValueError):
            threshold = 0.95
        return min(1.0, max(0.01, threshold))

    def _automatic_context_compression_threshold_tokens(self) -> int:
        explicit_trigger = int(getattr(self, "_context_compression_trigger_tokens", 0) or 0)
        if explicit_trigger > 0:
            return explicit_trigger
        return int(
            max(1, int(self._effective_max_token_limit))
            * self._automatic_context_compression_threshold()
        )

    def _should_automatically_compress(self, current_tokens: int) -> bool:
        return max(0, int(current_tokens)) > self._automatic_context_compression_threshold_tokens()

    def _context_budget_retention_contract(self) -> Dict[str, Any]:
        """Bounded scope fields pinned into every compression summary header."""

        binding = getattr(self, "runtime_agent_binding", {}) or {}
        turn_runtime = _turn_runtime_from_env() or {}
        policy = getattr(self, "_context_compression_policy", {}) or {}
        contract: Dict[str, Any] = {}
        for key in ("researchProjectId", "projectId", "workflowId", "runId", "stageTaskId"):
            value = str(binding.get(key) or turn_runtime.get(key) or "").strip()
            if value:
                contract[key] = value
        for key, source_name in (
            ("sessionId", "directSessionId"),
            ("agentId", "agentId"),
        ):
            value = str(
                turn_runtime.get(key)
                or binding.get(source_name)
                or ""
            ).strip()
            if value:
                contract[key] = value
        role_key = str(binding.get("roleKey") or binding.get("role") or "").strip()
        if role_key:
            contract["roleKey"] = role_key
        policy_version = int(policy.get("policyVersion") or 0)
        if policy_version > 0:
            contract["policyVersion"] = policy_version
        return contract

    def _context_budget_preflight_guard(
        self,
        *,
        estimated_tokens: int,
        iteration: int,
        message_count: int,
    ) -> bool:
        """Fail-closed hard input-limit gate before any model invocation."""

        hard_limit = int(getattr(self, "_context_input_hard_limit", 0) or 0)
        decision = evaluate_context_budget_preflight(
            estimated_tokens=estimated_tokens,
            context_input_hard_limit=hard_limit,
        )
        if not decision["exhausted"]:
            return False
        _record_agent_scene_event(
            "llm",
            "agent.context_budget_exhausted",
            message="Estimated context exceeds the hard input limit; model call blocked (context_budget_exhausted).",
            level="error",
            outcome="blocked",
            fields={
                "iteration": iteration,
                "estimatedTokens": decision["estimatedTokens"],
                "contextInputHardLimit": decision["hardLimit"],
                "messageCount": message_count,
                "guardReason": decision["guardReason"],
            },
        )
        try:
            get_ui().add_log(
                f"[上下文预算] 估算输入 {decision['estimatedTokens']} tokens 超过硬上限 "
                f"{decision['hardLimit']}，本轮不再调用模型（context_budget_exhausted）。",
                "ERROR",
            )
        except Exception:
            pass
        # The hard gate must leave a structured, prompt-free diagnostic:
        # without it the turn fell into the generic
        # ``agent_turn_failed_without_diagnostics`` fallback and was
        # misclassified as a runtime failure.
        self._record_turn_failure_diagnostic(
            category="context_error",
            reason_code="context_budget_exhausted",
            reason_summary="上下文预算超出硬上限",
            reason_detail=(
                "估算输入 tokens 超过硬上限，模型调用被前置闸拒绝；"
                "请压缩会话上下文或为新任务改用新会话后重试"
                "（context_budget_exhausted）。"
            ),
            chain_stage="llm_preflight",
            event_code="agent.context_budget_exhausted",
            retryable=False,
            recovery_action="compress_context_or_new_session",
            fields={
                "iteration": iteration,
                "estimatedTokens": decision["estimatedTokens"],
                "contextInputHardLimit": decision["hardLimit"],
                "messageCount": message_count,
                "guardReason": decision["guardReason"],
            },
        )
        return True

    def _init_llm(self):
        """初始化统一 LLM client。"""
        llm = get_llm_client(role="primary", config=self.config)
        self._base_llm = llm
        self.llm_with_tools = llm.bind_tools(self.key_tools)
        self._bound_llm_cache = {"default": self.llm_with_tools}

    def _resolve_tool_authorization(self, registered_tools: List[Any]) -> Any:
        # Removal: keep while tests construct SelfEvolvingAgent and patch this method.
        del registered_tools
        return resolve_turn_authorization(
            runtime_agent_binding=getattr(self, "runtime_agent_binding", {}) or {},
            turn_runtime_fn=_turn_runtime_from_env,
        )

    @staticmethod
    def _materialize_authorized_tools(registered_tools: List[Any], authorization_report: Any) -> List[Any]:
        # Removal: keep while tests call SelfEvolvingAgent._materialize_authorized_tools.
        return materialize_authorized_tools(registered_tools, authorization_report)

    def _is_tool_visible_to_current_agent(self, tool_name: str) -> bool:
        # Removal: keep while tests patch this method on the agent instance.
        if not is_tool_visible_to_agent(tool_name, getattr(self, "key_tool_maps", set())):
            return False
        turn_allowed = getattr(self, "_turn_allowed_tool_names", None)
        return turn_allowed is None or str(tool_name or "").strip() in turn_allowed

    def _hidden_tool_call_message(self, tool_name: str) -> str:
        # Removal: keep while tests patch this method on the agent instance.
        return hidden_tool_call_message(tool_name)

    @staticmethod
    def _restart_allowed_tool_names() -> tuple[str, ...]:
        return restart_allowed_tool_names()

    def _get_llm_for_current_mode(
        self,
        *,
        disable_tools: bool = False,
        profile_id: Optional[str] = None,
    ):
        base_llm = getattr(self, "_base_llm", None) or self.llm_with_tools
        if profile_id and profile_id != getattr(base_llm, "profile_id", None):
            base_llm = get_llm_client(profile_id=profile_id, config=self.config)
        if disable_tools or not client_supports_tool_calling(base_llm):
            return base_llm
        turn_allowed = getattr(self, "_turn_allowed_tool_names", None)
        if turn_allowed is not None:
            allowed_tools = [
                self._key_tool_map[name]
                for name in sorted(turn_allowed)
                if name in self._key_tool_map
            ]
            if not allowed_tools:
                return base_llm
            cache_key = "turn_allowed:" + ",".join(sorted(turn_allowed))
            if base_llm is getattr(self, "_base_llm", None):
                cached = self._bound_llm_cache.get(cache_key)
                if cached is not None:
                    return cached
                rebound = base_llm.bind_tools(allowed_tools)
                self._bound_llm_cache[cache_key] = rebound
                return rebound
            return base_llm.bind_tools(allowed_tools)
        if not self._is_restart_focus_mode():
            if not hasattr(self, "_base_llm"):
                return self.llm_with_tools
            if base_llm is getattr(self, "_base_llm", None):
                return self.llm_with_tools
            return base_llm.bind_tools(self.key_tools)

        if base_llm is not getattr(self, "_base_llm", None):
            allowed_tools = [
                self._key_tool_map[name]
                for name in self._restart_allowed_tool_names()
                if name in self._key_tool_map
            ]
            return base_llm.bind_tools(allowed_tools) if allowed_tools else base_llm
        cached = self._bound_llm_cache.get("restart_focus")
        if cached is not None:
            return cached

        allowed_tools = [
            self._key_tool_map[name]
            for name in self._restart_allowed_tool_names()
            if name in self._key_tool_map
        ]
        if not allowed_tools:
            return self._base_llm

        rebound = self._base_llm.bind_tools(allowed_tools)
        self._bound_llm_cache["restart_focus"] = rebound
        return rebound

    def _get_llm_for_agent_slot(self, slot: str, *, disable_tools: bool = False):
        agent_id = str((getattr(self, "runtime_agent_binding", {}) or {}).get("agentId") or "").strip()
        if not agent_id:
            return None
        try:
            from core.web.services import agent_directory_service

            agent = agent_directory_service.get_agent(agent_id, include_archived=False)
            resolved = resolve_agent_llm(
                agent,
                slot,
                config=getattr(self, "config", None),
                fallback_to_dialogue=False,
            )
            llm = get_llm_client(profile_id=resolved.runtime_profile_id, config=resolved.config)
            if disable_tools:
                return llm
            return llm.bind_tools(self.key_tools)
        except Exception:
            return None

    def _should_stream_llm(self, llm_for_turn: Any = None) -> bool:
        if llm_for_turn is not None:
            capabilities = getattr(llm_for_turn, "capabilities", None)
            if capabilities is not None and hasattr(capabilities, "supports_streaming"):
                return bool(capabilities.supports_streaming)
        config = getattr(self, "config", None)
        if config is None:
            return hasattr(self.llm_with_tools, "stream")
        llm_cfg = getattr(config, "llm", None)
        if llm_cfg is not None and hasattr(llm_cfg, "get_profile"):
            return bool(llm_cfg.get_profile(role="primary").streaming)
        return True

    def _should_stream_llm_for_turn(self, llm_for_turn: Any = None) -> bool:
        try:
            return bool(self._should_stream_llm(llm_for_turn))
        except TypeError as exc:
            try:
                return bool(self._should_stream_llm())
            except TypeError:
                raise exc

    def _mark_runtime_state_memory_dirty(self) -> None:
        """Request a runtime state-memory resync before the next LLM preflight."""
        self._runtime_state_memory_dirty = True

    def _sync_runtime_state_memory(self, *, force: bool = False):
        """将会话级短期约束同步到 MEMORY/state_memory。

        Cheap no-op when not dirty and not forced. Main loop marks dirty after tools
        (and similar side effects) so we do not re-render every iteration blindly.
        """
        if not force and not bool(getattr(self, "_runtime_state_memory_dirty", True)):
            return
        try:
            runtime_summary = get_session_state().render_dialogue_runtime_observations()
            restart_focus = (
                build_restart_focus_state_memory(self._restart_allowed_tool_names())
                if self._is_restart_focus_mode()
                else ""
            )
            summary = compose_state_memory(
                runtime_summary=runtime_summary,
                carryover_state_memory=self._carryover_state_memory,
                restart_focus_state_memory=restart_focus,
            )
            summary_key = build_state_memory_key(summary)
            if summary_key == getattr(self, "_last_runtime_state_memory_key", ""):
                # An empty, unchanged projection is not a stable observation yet:
                # keep the next preflight eligible to pick up a diagnostic that
                # materializes without an intervening tool call.
                self._runtime_state_memory_dirty = not bool(summary)
                return
            self._runtime_state_memory_dirty = False
            self._last_runtime_state_memory = summary
            self._last_runtime_state_memory_key = summary_key
            if summary:
                self.prompt_manager.update_state_memory(summary, persist=False)
            else:
                self.prompt_manager.clear_state_memory(persist=False)
        except Exception:
            self._runtime_state_memory_dirty = False

    def _load_previous_session_constraints(self):
        """从最近一次会话分析中恢复下一轮短期约束。"""
        try:
            analyzer = get_task_analyzer(project_root=os.path.dirname(os.path.abspath(__file__)))
            report = analyzer.analyze_evolution_session()
            if not report.next_round_constraints:
                return
            self._carryover_state_memory = analyzer.build_next_round_state_memory(report)
            _debug_logger.info("[Retrospective] 已加载上一会话的短期约束", tag="STATE")
        except Exception:
            self._carryover_state_memory = ""

    def _refresh_retrospective_state_memory(self):
        """根据当前会话日志刷新下一轮短期约束。"""
        try:
            conversation_logger = getattr(logger, "conversation", None)
            if conversation_logger is None:
                return
            session_file = conversation_logger._get_session_file()
            if not session_file or not Path(session_file).exists():
                return
            analyzer = get_task_analyzer(project_root=os.path.dirname(os.path.abspath(__file__)))
            report = analyzer.analyze_evolution_session(session_file=Path(session_file))
            self._carryover_state_memory = (
                analyzer.build_next_round_state_memory(report)
                if report.next_round_constraints
                else ""
            )
            self._sync_runtime_state_memory()
            if self._last_runtime_state_memory:
                self.prompt_manager.update_state_memory(self._last_runtime_state_memory, persist=True)
            else:
                self.prompt_manager.clear_state_memory(persist=True)
        except Exception as exc:
            _debug_logger.warning(f"Failed to refresh retrospective state memory: {exc}")

    def _record_language_drift(self, raw_text: str):
        """语言偏好只由提示词表达，运行时不再强制纠偏。"""
        return

    def _record_inference_activity(self, raw_text: str):
        """在无新增工具动作时记录推理行为，识别诊断漂移。"""
        cleaned = (raw_text or "").strip()
        if not cleaned:
            return
        if cleaned.startswith("<think>") or len(cleaned) > 80:
            session = get_session_state()
            session.note_diagnostic_inference()
            if session.has_diagnostic_drift():
                session.record_blocker(
                    "diagnostic_drift",
                    "连续进行推理但没有新增观测，请先打印最小中间值或验证结果。",
                    "先复现 -> 再观测 -> 再读代码"
                )
            self._sync_runtime_state_memory()

    def _remember_tool_output(self, _tool_call: Dict[str, Any], result: Any, _action: Optional[str]) -> None:
        text = str(result or "").strip()
        tool_name = str((_tool_call or {}).get("name") or "").strip()
        tool_call_id = str((_tool_call or {}).get("id") or "").strip()
        tool_args = parse_tool_args(
            (_tool_call or {}).get("args") or (_tool_call or {}).get("arguments") or {}
        )
        record = {
            "name": tool_name,
            "tool_call_id": tool_call_id,
            "args": tool_args,
            "action": str(_action or "").strip(),
            "result_preview": compact_tool_output_for_diagnosis(text, max_chars=1200) if text else "",
        }
        self._recent_tool_records.append(record)
        if len(self._recent_tool_records) > 20:
            self._recent_tool_records = self._recent_tool_records[-20:]
        if not text:
            return
        self._recent_tool_outputs.append(compact_tool_output_for_diagnosis(text, max_chars=6000))
        if len(self._recent_tool_outputs) > 6:
            self._recent_tool_outputs = self._recent_tool_outputs[-6:]

    def _remember_runtime_tool_metadata(
        self,
        _tool_call: Dict[str, Any],
        metadata: RuntimeToolMetadata,
    ) -> None:
        """保存审计/UI 所需的有界事实，不把续读建议回灌进模型历史。"""
        if not self._recent_tool_records:
            return
        tool_call_id = str((_tool_call or {}).get("id") or "").strip()
        tool_name = str((_tool_call or {}).get("name") or "").strip()
        target = next(
            (
                record
                for record in reversed(self._recent_tool_records)
                if (
                    tool_call_id
                    and str(record.get("tool_call_id") or "").strip() == tool_call_id
                )
                or (
                    not tool_call_id
                    and str(record.get("name") or "").strip() == tool_name
                )
            ),
            None,
        )
        if target is None:
            return
        target["runtime_metadata"] = {
            "result_kind": metadata.result_kind,
            "strategy": metadata.strategy,
            "range_info": metadata.range_info,
            "truncated": metadata.truncated,
            "original_length": metadata.original_length,
            "transport_status": metadata.transport_status,
            "semantic_status": metadata.semantic_status,
            "exit_code": metadata.exit_code,
            "timed_out": metadata.timed_out,
            "failure_class": metadata.failure_class,
        }

    def _get_turn_outcome_controller(self) -> TurnOutcomeController:
        controller = getattr(self, "turn_outcome_controller", None)
        if controller is not None:
            return controller

        controller = TurnOutcomeController(
            max_consecutive_failures=MAX_CONSECUTIVE_FAILURES,
            get_attention_snapshot=lambda: get_session_state().get_attention_snapshot(),
        )
        self.turn_outcome_controller = controller
        return controller

    def _get_response_surface_controller(self) -> ResponseSurfaceController:
        controller = getattr(self, "response_surface_controller", None)
        if controller is not None:
            return controller

        controller = ResponseSurfaceController(
            estimate_tokens=estimate_messages_tokens,
            ui_getter=get_ui,
            logger=logger,
            debug_logger=_debug_logger,
            pet_getter=get_pet_system,
            print_tokens=print_tokens,
        )
        self.response_surface_controller = controller
        return controller

    def _expects_restart_after_transaction_close(self) -> bool:
        """当前目标是否明确要求关账成功后继续触发自我重启。"""
        goal = getattr(self, "_active_goal", "") or ""
        return is_full_evolution_goal(goal)

    def _init_token_compressor(self):
        """初始化 Token 压缩器"""
        compression_decision = resolve_feature_decision(
            "context_compression",
            config=self.config,
        )
        _record_agent_scene_event(
            "startup",
            "agent.feature.decision",
            message="已解析上下文压缩可信配置。",
            fields=compression_decision.log_fields(),
        )
        if not compression_decision.effective_enabled:
            self.token_compressor = None
            return
        self.token_compressor = EnhancedTokenCompressor(
            token_budget=self._effective_max_token_limit,
            compression_llm=(
                self._get_llm_for_agent_slot(AGENT_LLM_SLOT_SUMMARY, disable_tools=True)
                or get_llm_client(role="compression", config=self.config)
            ),
        )
        try:
            get_ui().note_context_compression_config(
                enabled=bool(self.config.context_compression.enabled),
                effective_token_limit=self._effective_max_token_limit,
                context_window_limit=getattr(self, "_context_window_limit", self._effective_max_token_limit),
            )
        except Exception:
            pass

    def _compress_messages(self, messages: list, iteration: int, reason: str = ""):
        """执行消息压缩。返回 (messages, should_break)。"""
        (
            compressed,
            should_break,
            applied,
            self._compression_count_this_turn,
            self._last_compression_iteration,
        ) = compress_turn_messages(
            messages=messages,
            iteration=iteration,
            reason=reason,
            token_compressor=self.token_compressor,
            config=self.config,
            effective_max_token_limit=self._effective_max_token_limit,
            threshold_tokens=self._automatic_context_compression_threshold_tokens(),
            runtime_agent_binding=getattr(self, "runtime_agent_binding", {}) or {},
            project_root=str(getattr(self, "project_root", "") or ""),
            mode=self._get_mode_policy().mode,
            last_compression_iteration=self._last_compression_iteration,
            compression_min_iteration_gap=self._compression_min_iteration_gap,
            compression_count_this_turn=self._compression_count_this_turn,
            compression_strategy=getattr(self, "_compression_strategy", None),
            prompt_manager=getattr(self, "prompt_manager", None),
            turn_runtime_fn=_turn_runtime_from_env,
            estimate_tokens_fn=estimate_messages_tokens,
            get_ui_fn=get_ui,
            get_state_manager_fn=get_state_manager,
            scene_recorder_fn=_record_agent_scene_event,
            context_input_hard_limit=int(getattr(self, "_context_input_hard_limit", 0) or 0),
            post_compression_target_tokens=int(getattr(self, "_post_compression_target_tokens", 0) or 0),
            retention_contract=self._context_budget_retention_contract(),
        )
        self._last_context_compression_applied = applied
        return compressed, should_break

    @staticmethod
    def _fallback_mode_policy() -> ModePolicy:
        return ModePolicy(
            mode=AgentMode.SELF_EVOLUTION,
            orchestrator_kind="evolution",
            keep_multi_turn_context=True,
            allow_auto_loop=True,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_external_request_message,
        )

    def _get_mode_policy(self) -> ModePolicy:
        policy = getattr(self, "mode_policy", None)
        if isinstance(policy, ModePolicy):
            return policy
        config = getattr(self, "config", None)
        try:
            if config is not None:
                resolved = resolve_mode_policy(getattr(self, "mode", None), config)
                self.mode_policy = resolved
                self.mode = resolved.mode
                return resolved
        except Exception:
            pass
        fallback = self._fallback_mode_policy()
        self.mode_policy = fallback
        self.mode = fallback.mode
        return fallback

    def seed_chat_history_ledger_fingerprint(self, fingerprint: str) -> None:
        """Stamp the ledger provenance of the history seeded this turn.

        The session worker assembles chat history from the ConversationLedger
        (windowing and compaction included); the send-time gate accepts that
        seed when its provenance matches the live ledger instead of demanding
        the seed reproduce the canonical replay verbatim.
        """

        self._seeded_history_ledger_fingerprint = str(fingerprint or "").strip()

    def seed_chat_history(self, messages: List[Dict[str, Any]]) -> None:
        """为 chat 模式恢复 canonical model history。

        ConversationLedger/ContextAssembler owns historical tool/result replay.
        This method must not interpret UI ``toolCalls`` again, otherwise the
        Agent would keep a second model-visible source of truth.
        """
        policy = self._get_mode_policy()
        if policy.mode != AgentMode.CHAT:
            mental_clear = getattr(getattr(self, "mental_model", None), "clear_conversation_context", None)
            if callable(mental_clear):
                mental_clear()
            return
        # A new user turn seeds the full canonical history. Responses
        # ``previous_response_id`` is valid only for tool continuations inside
        # one turn; carrying it across this boundary can replay stale tools.
        self._chat_provider_replay_state = None
        from core.chat.conversation_invariant import (
            ConversationSeedInvariantError,
            check_conversation_payload_invariant,
        )
        from core.chat.model_messages import ProviderMessageChain

        seeded_input: list[Any] = []
        for item in list(messages or []):
            if not isinstance(item, dict):
                continue
            message = dict(item)
            if "toolCalls" in message:
                message["tool_calls"] = self._normalize_seeded_tool_calls(message.pop("toolCalls"))
            seeded_input.append(message)
        provider_chain = ProviderMessageChain.from_messages(seeded_input)
        if provider_chain.repaired:
            raise ConversationSeedInvariantError(
                error_type="silent_provider_tool_chain_repair",
                message=(
                    "Silent provider tool-chain repair is not allowed while seeding chat history. "
                    "Build history from ConversationLedger ModelProjection first."
                ),
                details={"providerChainRepaired": True},
            )
        seeded_messages = provider_chain.to_provider_payload()
        invariant = check_conversation_payload_invariant(seeded_messages)
        if not invariant.ok:
            raise ConversationSeedInvariantError(
                error_type=str(invariant.error_type or "conversation_seed_invariant_failed"),
                message=str(invariant.message or "Seeded chat history failed conversation invariant."),
                details=dict(invariant.details or {}),
            )
        canonical_messages = seeded_messages
        if self.is_mental_model_enabled_for_turn():
            mental_seed = getattr(getattr(self, "mental_model", None), "seed_conversation_context", None)
            if callable(mental_seed):
                mental_seed(canonical_messages)
        else:
            mental_clear = getattr(getattr(self, "mental_model", None), "clear_conversation_context", None)
            if callable(mental_clear):
                mental_clear()
        restored: List[Any] = [SystemMessage(content="")]
        for item in canonical_messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            assistant_tool_calls = (
                self._normalize_seeded_tool_calls(item.get("tool_calls") or item.get("toolCalls") or [])
                if role == "assistant"
                else []
            )
            raw_content = item.get("content")
            content = raw_content if isinstance(raw_content, list) else str(raw_content or "").strip()
            if isinstance(content, str):
                content = self._sanitize_seeded_chat_content(role, content)
            if not content and not assistant_tool_calls:
                continue
            if role in {"runtime_context", "runtime", "system"}:
                restored.append(SystemMessage(content=str(content)))
            elif role == "user":
                if isinstance(content, list):
                    restored.append({"role": "user", "content": content})
                else:
                    restored.append(build_chat_user_message(content))
            elif role == "assistant":
                restored.append(AIMessage(content=str(content), tool_calls=assistant_tool_calls))
            elif role == "tool":
                tool_call_id = str(item.get("tool_call_id") or item.get("toolCallId") or "").strip()
                if tool_call_id:
                    restored.append(ToolMessage(content=str(content), tool_call_id=tool_call_id))
        if len(restored) <= 1:
            self._active_turn_messages = None
            self._active_turn_goal = ""
            return
        self._active_turn_messages = restored
        self._active_turn_goal = "__chat_session__"

    def _chat_ledger_identity(self) -> Optional[tuple[Path, str, str]]:
        runtime: Dict[str, Any] = {}
        try:
            from core.web.services.agent_directory_service import current_agent_runtime

            loaded = current_agent_runtime() or {}
            if isinstance(loaded, dict):
                runtime = loaded
        except Exception:
            runtime = {}
        session_id = str(runtime.get("sessionId") or "").strip()
        turn_id = str(runtime.get("turnId") or "").strip()
        if not session_id:
            tail = getattr(self, "_turn_status_tail_context", None)
            if isinstance(tail, dict):
                session_id = str(tail.get("session_id") or "").strip()
        project_root_raw = str(getattr(self, "project_root", "") or "").strip()
        if not session_id or not turn_id or not project_root_raw:
            return None
        return Path(project_root_raw), session_id, turn_id

    def _replay_current_turn_conversation_from_ledger(
        self,
        messages: list,
        *,
        strict: bool = True,
        require_layer: bool = False,
    ) -> list:
        identity = self._chat_ledger_identity()
        if identity is None:
            if strict and require_layer:
                raise TurnJournalReplayError(
                    error_type="ledger_identity_missing",
                    message="Chat turn journal replay requires session and turn identity.",
                )
            return messages
        project_root, session_id, turn_id = identity
        from core.chat.conversation_ledger import load_conversation_events

        events = load_conversation_events(project_root, session_id)
        replayed = replay_current_turn_messages(
            messages,
            events,
            turn_id=turn_id,
            strict=strict,
            require_layer=require_layer,
        )
        if replayed != messages:
            _record_agent_scene_event(
                "chat",
                "agent.turn_journal_replay.applied",
                message="Rebuilt current-turn conversation layer from ConversationLedger.",
                fields={
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "beforeCount": len(messages),
                    "afterCount": len(replayed),
                },
            )
        if strict and current_turn_has_journal_conversation_layer(events, turn_id=turn_id):
            self._ledger_conversation_fingerprint = ledger_conversation_fingerprint_for_messages(replayed)
        return replayed

    def _handle_turn_journal_replay_failure(self, exc: TurnJournalReplayError) -> None:
        identity = self._chat_ledger_identity() or (None, "", "")
        _, session_id, turn_id = identity
        _record_agent_scene_event(
            "chat",
            "agent.turn_journal_replay.blocked",
            message="Current-turn journal replay failed; blocking further LLM calls this turn.",
            fields={
                "sessionId": session_id,
                "turnId": turn_id,
                "errorType": exc.error_type,
                **dict(exc.details or {}),
            },
            level="error",
            outcome="blocked",
        )
        self._ledger_conversation_fingerprint = ""
        self._record_turn_failure_diagnostic(
            category="protocol_error",
            reason_code="turn_journal_replay_failed",
            reason_summary="当前轮对话层无法从 journal 重建",
            reason_detail=str(exc.message or "turn journal replay failed"),
            chain_stage="agent_turn_journal_replay",
            event_code="agent.turn_journal_replay.blocked",
            fields={
                "errorType": exc.error_type,
                **dict(exc.details or {}),
            },
        )
        get_ui().add_log(
            "当前轮对话层无法从 ConversationLedger 重建，已停止继续调用模型。",
            "ERROR",
        )

    def _reconcile_chat_conversation_before_llm(self, messages: list) -> tuple[list, bool]:
        identity = self._chat_ledger_identity()
        if identity is None:
            exc = TurnJournalReplayError(
                error_type="ledger_identity_missing",
                message="Chat turn ledger reconciliation requires session and turn identity.",
            )
            self._handle_turn_journal_replay_failure(exc)
            return messages, False
        project_root, session_id, turn_id = identity
        try:
            from core.chat.conversation_ledger import load_conversation_events

            events = load_conversation_events(project_root, session_id)
            seeded_ledger_fingerprint = str(
                getattr(self, "_seeded_history_ledger_fingerprint", "") or ""
            ).strip()
            if seeded_ledger_fingerprint:
                # One-shot per turn: the seed was ledger-assembled by the
                # session worker, so verify provenance (same ledger state)
                # rather than seed == canonical replay, which legal context
                # windowing/compaction would always break.
                self._seeded_history_ledger_fingerprint = ""
                from core.orchestration.turn_message_assembly import (
                    ledger_seeded_history_fingerprint,
                )

                live_fingerprint = ledger_seeded_history_fingerprint(
                    events,
                    turn_id=turn_id,
                )
                if live_fingerprint == seeded_ledger_fingerprint:
                    return messages, True
            reconciled = reconcile_chat_messages_with_ledger(
                messages,
                events,
                turn_id=turn_id,
                strict=True,
            )
            if reconciled != messages:
                _record_agent_scene_event(
                    "chat",
                    "agent.turn_journal_replay.applied",
                    message="Rebuilt chat conversation layer from ConversationLedger before LLM send.",
                    fields={
                        "sessionId": session_id,
                        "turnId": turn_id,
                        "beforeCount": len(messages),
                        "afterCount": len(reconciled),
                    },
                )
            self._ledger_conversation_fingerprint = ledger_conversation_fingerprint_for_messages(reconciled)
            return reconciled, True
        except TurnJournalReplayError as exc:
            self._handle_turn_journal_replay_failure(exc)
            return messages, False

    def _apply_chat_journal_replay(
        self,
        messages: list,
        *,
        require_layer: bool = False,
    ) -> tuple[list, bool]:
        try:
            return (
                self._replay_current_turn_conversation_from_ledger(
                    messages,
                    strict=True,
                    require_layer=require_layer,
                ),
                True,
            )
        except TurnJournalReplayError as exc:
            self._handle_turn_journal_replay_failure(exc)
            return messages, False

    @staticmethod
    def _normalize_seeded_tool_calls(raw_calls: Any) -> List[Dict[str, Any]]:
        # Removal: keep while seed_chat_history and tests call this method.
        return normalize_seeded_tool_calls(raw_calls)

    @staticmethod
    def _sanitize_seeded_chat_content(role: str, content: str) -> str:
        # Removal: keep while seed_chat_history and tests call this method.
        return sanitize_seeded_chat_content(role, content)

    def seed_runtime_context(self, content: str) -> None:
        """Add non-chat runtime context without making it a user/assistant message."""
        text = str(content or "").strip()
        if not text:
            return
        self._pending_runtime_context_blocks.append(text)

    def seed_static_runtime_context(self, content: str) -> None:
        """Add stable non-chat runtime context near the system prompt."""
        text = str(content or "").strip()
        if not text:
            return
        self._pending_static_context_blocks.append(text)

    def mark_core_prompt_snapshot_seeded_by_host(self, included: bool = True) -> None:
        """Record that the session-static block already contains all three cores."""

        self._core_prompt_snapshot_seeded_by_host = bool(included)

    def seed_volatile_runtime_context(self, content: str) -> None:
        """Add current-turn-only context immediately before the current user message."""
        text = str(content or "").strip()
        if not text:
            return
        pending = getattr(self, "_pending_volatile_context_blocks", None)
        if not isinstance(pending, list):
            pending = []
            self._pending_volatile_context_blocks = pending
        pending.append(text)

    def _insert_pending_volatile_context_messages(self, messages: List[Any]) -> tuple[List[Any], List[str]]:
        # Removal: keep while tests call this method on the agent instance.
        pending_volatile_context_blocks = list(getattr(self, "_pending_volatile_context_blocks", []) or [])
        self._pending_volatile_context_blocks = []
        return insert_pending_volatile_context_messages(
            messages,
            pending_volatile_context_blocks,
            insert_volatile_fn=TurnOutcomeController.insert_volatile_context_before_current_user,
        )

    def mark_runtime_context_seeded_by_host(self) -> None:
        """Mark that the embedding host already injected this turn's runtime context."""

        self._runtime_context_seeded_by_host = True

    def _seed_runtime_agent_context_for_turn(self, *, run_id: str = "") -> None:
        """Seed ContextEngine output when this process is bound to an AgentInstance."""

        if bool(getattr(self, "_runtime_context_seeded_by_host", False)):
            self._runtime_context_seeded_by_host = False
            return
        runtime_binding = getattr(self, "runtime_agent_binding", {}) or {}
        agent_id = str(runtime_binding.get("agentId") or "").strip()
        if not agent_id:
            return
        session_id = str(runtime_binding.get("directSessionId") or "").strip()
        try:
            packet = build_agent_context(agent_id, session_id=session_id, run_id=run_id)
        except Exception as exc:
            _record_agent_scene_event(
                "startup",
                "agent.runtime_context_seed_failed",
                message="运行时 Agent ContextEngine 上下文注入失败。",
                fields={
                    "agentId": agent_id,
                    "sessionId": session_id,
                    "supervisedRole": runtime_binding.get("supervisedRole", ""),
                    "errorType": type(exc).__name__,
                },
            )
            return
        static_context_block = str(getattr(packet, "static_context_block", "") or "").strip()
        dynamic_context_block = str(getattr(packet, "dynamic_context_block", "") or "").strip()
        if not static_context_block and not dynamic_context_block:
            dynamic_context_block = str(getattr(packet, "context_block", "") or "").strip()
        if not static_context_block and not dynamic_context_block:
            return
        if static_context_block:
            self.seed_static_runtime_context(static_context_block)
        _record_agent_scene_event(
            "startup",
            "agent.runtime_context_seeded",
            message="Stable Agent ContextEngine context was seeded; dynamic context stays outside the LLM payload.",
            fields={
                "agentId": agent_id,
                "agentCode": str(getattr(packet, "agent_code", "") or "").strip(),
                "sessionId": session_id,
                "runId": str(run_id or "").strip(),
                "profileId": str(getattr(packet, "profile_id", "") or "").strip(),
                "promptTemplateId": str(getattr(packet, "prompt_template_id", "") or "").strip(),
                "roleKey": str(getattr(packet, "role_key", "") or "").strip(),
                "supervisedRole": runtime_binding.get("supervisedRole", ""),
                "staticContextChars": len(static_context_block),
                "dynamicContextChars": len(dynamic_context_block),
                "dynamicContextOmittedFromModelInput": bool(dynamic_context_block),
                "staticContextHash": str((getattr(packet, "timings", {}) or {}).get("staticContextHash") or "").strip(),
                "dynamicContextHash": str((getattr(packet, "timings", {}) or {}).get("dynamicContextHash") or "").strip(),
                "contextSegmentCount": len(list(getattr(packet, "context_segments", []) or [])),
            },
        )

    def export_turn_carryover(self) -> Dict[str, Any]:
        messages = self._serialize_turn_messages(self._active_turn_messages)
        goal = str(getattr(self, "_active_turn_goal", "") or "").strip()
        turn_identity = str(getattr(self, "_active_turn_identity", "") or "").strip()
        terminal = bool(getattr(self, "_active_turn_terminal", False))
        if terminal and turn_identity:
            return {
                "messages": [],
                "goal": "",
                "turnIdentity": turn_identity,
                "terminal": True,
            }
        if not messages or not goal or not turn_identity:
            return {}
        return {
            "messages": messages,
            "goal": goal,
            "turnIdentity": turn_identity,
            "terminal": False,
        }

    def set_turn_identity(self, turn_identity: str) -> None:
        self._active_turn_identity = str(turn_identity or "").strip()

    def clear_turn_preparation_state(self) -> None:
        """Atomically clear state that could leak an earlier preparation path."""
        self._active_turn_messages = None
        self._active_turn_goal = ""
        self._active_turn_terminal = False
        self._seeded_history_ledger_fingerprint = ""

    def prepare_for_session_turn_reuse(self) -> None:
        """Reset turn-local state while retaining the model transport/session anchor."""

        self.clear_turn_preparation_state()
        self._pending_static_context_blocks = []
        self._pending_runtime_context_blocks = []
        self._pending_volatile_context_blocks = []
        self._runtime_context_seeded_by_host = False
        self._core_prompt_snapshot_seeded_by_host = False
        self._last_turn_metadata = {}
        self._last_visible_response_text = ""
        self._last_response_tool_calls = 0
        self._recent_tool_outputs = []
        self._recent_tool_records = []
        self._pending_lifecycle_action = None
        self._turn_interrupt_checker = None
        # Tool authorization is scoped to one turn.  A cached chat Agent keeps
        # its model transport and tool surface, but must never keep the prior
        # turn's execution decision or every tool call will fail closed with a
        # turn_mismatch denial.
        authorization_report = self._resolve_tool_authorization(self.key_tools)
        self._tool_authorization_decision_fingerprint = str(
            getattr(getattr(authorization_report, "decision", None), "decision_fingerprint", "") or ""
        ).strip()

    def _excluded_system_prompt_sections_for_turn(self, *, stable_session_prompt: bool) -> List[str]:
        excluded: List[str] = []
        if self._get_mode_policy().mode == AgentMode.SUPERVISED_EVOLUTION:
            excluded.extend(["GIT_MEMORY", "RUNTIME_LOG_INDEX"])
        elif stable_session_prompt:
            excluded.append("RUNTIME_LOG_INDEX")
        if bool(getattr(self, "_core_prompt_snapshot_seeded_by_host", False)):
            excluded.extend(CORE_PROMPT_NAMES)
        return list(dict.fromkeys(excluded))

    def _prompt_assembly_context_for_turn(self):
        client = getattr(self, "_base_llm", None)
        route = getattr(client, "protocol_route", None)
        capabilities = getattr(client, "capabilities", None)
        if client is None or route is None or capabilities is None:
            return None
        context = build_prompt_assembly_context(
            client,
            context_window=int(
                getattr(self, "_context_window_limit", 0)
                or getattr(
                    getattr(client, "resolved_spec", None),
                    "context_window",
                    0,
                )
                or 0
            ),
            allowed_tool_names=tuple(
                sorted(getattr(self, "key_tool_maps", set()) or set())
            ),
            permission_fingerprint=str(
                getattr(
                    self,
                    "_tool_authorization_decision_fingerprint",
                    "",
                )
                or ""
            ),
            enforce_core_floor=not bool(
                getattr(self, "_core_prompt_snapshot_seeded_by_host", False)
            ),
        )
        section = build_protocol_adapter_section(route, capabilities)
        setter = getattr(self.prompt_manager, "set_protocol_adapter", None)
        if callable(setter):
            setter(
                section,
                fingerprint=(
                    f"{context.model_protocol}:"
                    f"{context.capability_fingerprint}"
                ),
            )
        return context

    def _build_system_prompt_for_turn(self, *, stable_session_prompt: bool):
        """Build a prompt without unrelated global diagnostics for the current mode."""
        excluded_sections = self._excluded_system_prompt_sections_for_turn(
            stable_session_prompt=stable_session_prompt,
        )
        assembly_context = self._prompt_assembly_context_for_turn()
        if excluded_sections:
            frozen_core_sections = [
                name
                for name in CORE_PROMPT_NAMES
                if name in excluded_sections
            ]
            build_kwargs: Dict[str, Any] = {"exclude": excluded_sections}
            if frozen_core_sections:
                build_kwargs["frozen_core_sections"] = frozen_core_sections
            if assembly_context is not None:
                build_kwargs["assembly_context"] = assembly_context
            return self.prompt_manager.build(**build_kwargs)
        if assembly_context is not None:
            return self.prompt_manager.build(assembly_context=assembly_context)
        return self.prompt_manager.build()

    def clear_chat_provider_replay_state(self) -> None:
        self._chat_provider_replay_state = None

    def record_turn_preparation_diagnostic(self, fields: Dict[str, Any]) -> None:
        """Record bounded preparation shape without prompt or credential content."""
        allowed_paths = {"fresh", "history", "carryover"}
        allowed_statuses = {
            "absent",
            "accepted",
            "terminal",
            "missing_identity",
            "identity_mismatch",
            "invalid",
        }
        safe_fields = {
            "path": str(fields.get("path") or "fresh") if fields.get("path") in allowed_paths else "fresh",
            "carryoverStatus": (
                str(fields.get("carryoverStatus") or "absent")
                if fields.get("carryoverStatus") in allowed_statuses
                else "invalid"
            ),
            "historyMessageCount": min(10000, max(0, int(fields.get("historyMessageCount") or 0))),
            "hasTurnIdentity": bool(fields.get("hasTurnIdentity")),
            "staticContextChars": min(1000000, max(0, int(fields.get("staticContextChars") or 0))),
            "dynamicContextChars": min(1000000, max(0, int(fields.get("dynamicContextChars") or 0))),
        }
        _record_agent_scene_event(
            "prompt",
            "agent.turn_preparation.completed",
            message="Agent turn preparation selected one bounded context path.",
            fields=safe_fields,
        )

    def seed_turn_carryover(self, payload: Dict[str, Any] | None) -> None:
        if TurnOutcomeController.classify_turn_carryover(
            payload,
            expected_turn_identity=str(getattr(self, "_active_turn_identity", "") or "").strip(),
        ) != "accepted":
            return
        goal = str(payload.get("goal") or "").strip()
        messages = self._deserialize_turn_messages(payload.get("messages") or [])
        if not goal or not messages:
            return
        self._active_turn_messages = messages
        self._active_turn_goal = goal
        self._active_turn_terminal = False

    def _serialize_turn_messages(self, messages: Optional[List[Any]]) -> List[Dict[str, Any]]:
        return serialize_turn_messages(messages)

    def _serialize_turn_message(self, message: Any) -> Dict[str, Any]:
        return serialize_turn_message(message)

    def _deserialize_turn_messages(self, messages: List[Dict[str, Any]]) -> List[Any]:
        return deserialize_turn_messages(messages)

    def _reset_mode_context_for_supervised_case(self, case_id: Optional[str] = None) -> None:
        self._active_turn_messages = None
        self._active_turn_goal = ""
        self._active_goal = ""
        self._carryover_state_memory = ""
        self._last_runtime_state_memory = ""
        self._last_runtime_state_memory_key = ""
        self._chat_turn_records = []
        self._active_supervised_case_id = str(case_id or "").strip()
        try:
            session = get_session_state()
            session.reset_runtime_constraints()
            session.set_active_evolution_txn(None)
            session.set_runtime_goal_packet(None)
        except Exception:
            pass
        try:
            self.prompt_manager.clear_state_memory(persist=False)
            self.prompt_manager.update_current_goal("")
        except Exception:
            pass

    def _maybe_reset_supervised_case_context(self) -> None:
        policy = self._get_mode_policy()
        if policy.mode != AgentMode.SUPERVISED_EVOLUTION:
            return
        case_id = str(getattr(self, "_pending_supervised_case_id", None) or "").strip()
        if case_id:
            if case_id != getattr(self, "_active_supervised_case_id", ""):
                self._reset_mode_context_for_supervised_case(case_id)
            return
        if (
            getattr(self, "_active_supervised_case_id", "")
            or getattr(self, "_active_turn_messages", None)
            or getattr(self, "_active_goal", "")
        ):
            self._reset_mode_context_for_supervised_case(None)

    def _capture_chat_dataset_candidate_if_needed(
        self,
        *,
        user_prompt: str,
        current_turn: int,
        tool_names: List[str],
        delegated: bool,
    ) -> None:
        policy = self._get_mode_policy()
        if not policy.capture_chat_dataset_candidates:
            return
        service = getattr(self, "chat_dataset_capture", None)
        if service is None or not service.should_capture_mode(policy.mode.value):
            return
        assistant_text = (getattr(self, "_last_visible_response_text", "") or "").strip()
        record = ChatTurnRecord(
            turn_number=int(current_turn or 0),
            user_message=(user_prompt or "").strip(),
            assistant_message=assistant_text,
            tool_calls=list(dict.fromkeys(tool_names or [])),
            tool_call_count=int(getattr(self, "_last_response_tool_calls", 0) or 0),
            had_delegation=bool(delegated),
            had_explicit_conclusion=bool("结论" in assistant_text or "总结" in assistant_text or "最终" in assistant_text),
            had_next_action=bool("下一步" in assistant_text or "建议" in assistant_text or "接下来" in assistant_text),
            metadata={"mode": policy.mode.value},
        )
        self._chat_turn_records.append(record)
        conversation_logger = getattr(logger, "conversation", None)
        source_log_path = ""
        session_id = ""
        if conversation_logger is not None:
            try:
                source_log_path = str(conversation_logger._get_session_file())
                session_id = str(getattr(conversation_logger, "_session_id", "") or "")
            except Exception:
                source_log_path = ""
                session_id = ""
        try:
            service.capture_candidate(
                mode=policy.mode.value,
                session_id=session_id or "chat_session",
                source_log_path=source_log_path,
                turns=self._chat_turn_records,
            )
        except Exception as exc:
            _debug_logger.warning(f"chat candidate capture skipped: {type(exc).__name__}: {exc}", tag="CHAT")

    def _run_chat_turn(
        self,
        user_prompt: str = None,
        goal_override: str = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        return self._run_orchestrated_turn(
            user_prompt=user_prompt,
            goal_override=goal_override,
            attachments=attachments,
        )

    def _run_evolution_turn(self, user_prompt: str = None, goal_override: str = None) -> bool:
        self._maybe_reset_supervised_case_context()
        return self._run_orchestrated_turn(user_prompt=user_prompt, goal_override=goal_override)

    def think_and_act(
        self,
        user_prompt: str = None,
        goal_override: str = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        policy = self._get_mode_policy()
        if policy.orchestrator_kind == "chat":
            return self._run_chat_turn(
                user_prompt=user_prompt,
                goal_override=goal_override,
                attachments=attachments,
            )
        return self._run_evolution_turn(user_prompt=user_prompt, goal_override=goal_override)

    def _run_orchestrated_turn(
        self,
        user_prompt: str = None,
        goal_override: str = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """苏醒时执行一次思考和行动。

        Returns:
            True: 继续运行, False: 结束当前主循环
        """
        ui = get_ui()
        policy = self._get_mode_policy()
        if user_prompt is None:
            user_prompt = "开始自主进化"
        effective_goal = (
            _normalize_goal_from_chat_history(
                user_prompt,
                None if policy.mode == AgentMode.CHAT else goal_override,
                getattr(self, "_active_turn_messages", None),
            )
            or user_prompt
        )
        self._active_goal = effective_goal
        self._last_turn_metadata = {}
        self._ledger_conversation_fingerprint = ""
        self._last_llm_failure_attempts = 0
        self._last_llm_failure_max_attempts = 0
        stable_session_prompt = (
            policy.mode == AgentMode.CHAT
            and getattr(self, "_allow_session_subagent_auto_delegation", None) is False
        )
        prompt_goal = _SESSION_CHAT_PROMPT_GOAL if stable_session_prompt else effective_goal
        self.prompt_manager.update_current_goal(prompt_goal)
        agent_tool_policy = None
        try:
            from core.web.services import agent_directory_service

            current_runtime = agent_directory_service.current_agent_runtime()
            if isinstance(current_runtime, dict):
                agent_tool_policy = current_runtime.get("toolPolicy")
        except Exception:
            agent_tool_policy = None
        runtime_goal_packet = build_runtime_goal_packet(
            policy,
            prompt_goal,
            agent_tool_policy=agent_tool_policy if isinstance(agent_tool_policy, dict) else None,
        )
        if stable_session_prompt and runtime_goal_packet.allow_subagents:
            runtime_goal_packet = replace(runtime_goal_packet, allow_subagents=False)
        try:
            get_session_state().set_runtime_goal_packet(runtime_goal_packet)
        except Exception:
            pass
        set_goal_packet = getattr(self.prompt_manager, "set_runtime_goal_packet", None)
        get_goal_packet = getattr(self.prompt_manager, "get_runtime_goal_packet", None)
        try:
            current_goal_packet = get_goal_packet() if callable(get_goal_packet) else None
        except Exception:
            current_goal_packet = None
        if callable(set_goal_packet) and current_goal_packet != runtime_goal_packet:
            set_goal_packet(runtime_goal_packet)
        try:
            logger.log_action("runtime_goal_packet", {
                "source": runtime_goal_packet.source,
                "objective_type": runtime_goal_packet.objective_type,
                "allow_auto_continue": runtime_goal_packet.allow_auto_continue,
                "allow_file_writes": runtime_goal_packet.allow_file_writes,
                "allow_code_context": runtime_goal_packet.allow_code_context,
                "allow_git_commit": runtime_goal_packet.allow_git_commit,
                "allow_evolution_transaction": runtime_goal_packet.allow_evolution_transaction,
                "allow_subagents": runtime_goal_packet.allow_subagents,
            })
        except Exception:
            pass
        _record_agent_scene_event(
            "prompt",
            "agent.runtime_goal.bound",
            message="统一 agent 回合已绑定运行目标包。",
            fields={
                "source": runtime_goal_packet.source,
                "objectiveType": runtime_goal_packet.objective_type,
                "allowAutoContinue": runtime_goal_packet.allow_auto_continue,
                "allowFileWrites": runtime_goal_packet.allow_file_writes,
                "allowGitCommit": runtime_goal_packet.allow_git_commit,
                "allowEvolutionTransaction": runtime_goal_packet.allow_evolution_transaction,
                "allowSubagents": runtime_goal_packet.allow_subagents,
                "stableSessionPrompt": stable_session_prompt,
                "userRequestPlacement": "user_message" if stable_session_prompt else "runtime_goal",
            },
        )
        self._pending_lifecycle_action = None
        context_limit = getattr(
            self,
            "_context_window_limit",
            getattr(self, "_effective_max_token_limit", 16000),
        )
        self._seed_runtime_agent_context_for_turn(
            run_id=getattr(self, "_pending_supervised_case_id", None) or effective_goal
        )
        get_session_state().reset_runtime_constraints()
        self._last_runtime_state_memory = ""
        self._last_runtime_state_memory_key = ""
        self._runtime_state_memory_dirty = True
        self.prompt_manager.clear_state_memory(persist=False)
        initial_context_started = time.perf_counter()
        # Git worktree scans are tool-driven (e.g. get_git_status_summary_tool).
        # Do not auto-refresh git memory on every agent turn — that caused TimeoutExpired
        # main-loop failures and is the wrong ownership for git observation.
        initial_git_ms = 0
        initial_runtime_sync_started = time.perf_counter()
        self._sync_runtime_state_memory(force=True)
        initial_runtime_sync_ms = max(0, int((time.perf_counter() - initial_runtime_sync_started) * 1000))
        initial_runtime_state_memory_key = self._last_runtime_state_memory_key
        prompt_built_with_runtime_key = initial_runtime_state_memory_key
        initial_prompt_build_started = time.perf_counter()
        sp = self._build_system_prompt_for_turn(stable_session_prompt=stable_session_prompt)
        initial_prompt_build_ms = max(0, int((time.perf_counter() - initial_prompt_build_started) * 1000))
        self._cached_system_prompt = to_string(sp)
        _record_agent_scene_event(
            "prompt",
            "agent.initial_context.completed",
            message="Agent initial context prepared.",
            fields={
                "gitRefreshMs": initial_git_ms,
                "gitRefreshPolicy": "tool_driven",
                "runtimeStateSyncMs": initial_runtime_sync_ms,
                "promptBuildMs": initial_prompt_build_ms,
                "totalMs": max(0, int((time.perf_counter() - initial_context_started) * 1000)),
                "stableSessionPrompt": stable_session_prompt,
                "excludedPromptSections": self._excluded_system_prompt_sections_for_turn(
                    stable_session_prompt=stable_session_prompt,
                ),
            },
        )
        dynamic_system_context_message = build_dynamic_system_context_message(sp)
        runtime_input_builder_for_turn = policy.runtime_input_builder
        if policy.mode == AgentMode.CHAT and attachments:
            runtime_input_builder_for_turn = lambda content: self._build_chat_user_message_for_turn(
                content,
                attachments,
            )
        pending_static_context_blocks = list(getattr(self, "_pending_static_context_blocks", []) or [])
        turn_static_context_blocks = list(pending_static_context_blocks)
        self._pending_static_context_blocks = []
        pending_runtime_context_blocks = list(getattr(self, "_pending_runtime_context_blocks", []) or [])
        self._pending_runtime_context_blocks = []
        assembled_turn_messages = assemble_prepared_turn_messages(
            system_prompt=sp,
            user_prompt=user_prompt,
            effective_goal=effective_goal,
            active_turn_messages=self._active_turn_messages,
            active_turn_goal=self._active_turn_goal,
            build_system_message=build_cacheable_system_prefix_message,
            build_external_request_message=runtime_input_builder_for_turn,
            allow_append_user_message=policy.mode == AgentMode.CHAT and policy.keep_multi_turn_context,
            static_context_blocks=pending_static_context_blocks,
            runtime_context_blocks=pending_runtime_context_blocks,
            dynamic_system_context_message=dynamic_system_context_message,
            prepare_turn_messages_fn=TurnOutcomeController.prepare_turn_messages,
            insert_static_fn=TurnOutcomeController.insert_static_context_after_system,
            insert_volatile_fn=TurnOutcomeController.insert_volatile_context_before_current_user,
            extend_cacheable_prefix_fn=extend_system_message_cacheable_prefix,
        )
        messages = assembled_turn_messages.messages
        resumed_messages = assembled_turn_messages.resumed
        cacheable_prefix_merged = assembled_turn_messages.cacheable_prefix_merged
        if assembled_turn_messages.static_context_inserted:
            _record_agent_scene_event(
                "prompt",
                "agent.static_runtime_context_inserted_as_system",
                message="Stable Agent runtime context inserted into the turn system prefix.",
                fields={
                    "staticContextBlockCount": len(pending_static_context_blocks),
                    "staticContextChars": sum(len(str(b or "")) for b in pending_static_context_blocks),
                    "systemMessageKind": (
                        "cacheable_system_prefix" if cacheable_prefix_merged else "independent_system_message"
                    ),
                    "insertionPolicy": (
                        "system_cacheable_prefix"
                        if cacheable_prefix_merged
                        else "after_system_before_history"
                    ),
                    "cacheableSystemPrefixMerged": cacheable_prefix_merged,
                },
            )
        messages = self._apply_turn_status_bar(messages, iteration=0)
        if assembled_turn_messages.dynamic_system_context_inserted:
            _record_agent_scene_event(
                "prompt",
                "agent.dynamic_system_context_inserted_before_current_user",
                message="Dynamic system suffix inserted after stable history and before the current user message.",
                fields={
                    "dynamicSystemContextChars": len(str(dynamic_system_context_message.content or "")),
                    "systemMessageKind": "independent_system_message",
                    "insertionPolicy": "after_history_before_current_user",
                    "cachePrefixPlacement": "outside_stable_prefix",
                },
            )
            _record_agent_scene_event(
                "prompt",
                "agent.runtime_context_omitted_from_model_input",
                message="Dynamic runtime context was omitted from the LLM message list.",
                fields={
                    "runtimeContextBlockCount": len(pending_runtime_context_blocks),
                    "runtimeContextChars": sum(len(str(b or "")) for b in pending_runtime_context_blocks),
                    "insertionPolicy": "omitted_from_model_input",
                    "cachePrefixPlacement": "not_in_payload",
                },
            )
        try:
            get_ui().note_context_window(
                estimate_messages_tokens_for_threshold(
                    messages,
                    self._automatic_context_compression_threshold_tokens(),
                ),
                context_limit,
            )
        except Exception:
            pass

        if not self._system_prompt_written:
            logger.write_system_prompt(self._cached_system_prompt)
            self._system_prompt_written = True

        logger.log_external_request(user_prompt)
        if resumed_messages:
            ui.add_log("承接上一轮未完成上下文继续推进。", "INFO")
        current_turn = logger._turn_count
        logger.start_turn(current_turn)
        ui.note_turn_start(current_turn)
        llm_config = self.config.llm
        model_name = (
            llm_config.get_profile(role="primary").model
            if hasattr(llm_config, "get_profile")
            else getattr(llm_config, "model_name", "unknown")
        )
        logger.log_llm_request(messages, model=model_name)
        self._compression_count_this_turn = 0
        self._last_compression_iteration = 0
        round_state = self._create_round_state()
        lifecycle_action: Optional[str] = None
        turn_tool_names: List[str] = []
        delegated_this_turn = False
        round_return_ok = True
        try:
            self._raise_if_turn_stop_requested()
            provider_replay_state = (
                getattr(self, "_chat_provider_replay_state", None)
                if policy.mode == AgentMode.CHAT
                else None
            )
            responses_continuation_disabled = False
            for _ in range(round_state.max_iterations):
                self._raise_if_turn_stop_requested()
                iteration = round_state.next_iteration()
                pre_llm_started = time.perf_counter()
                ui.update_status(
                    "THINKING",
                    **round_state.thinking_status(user_prompt),
                )
                # Git memory is not refreshed here; agents must call git tools when needed.
                git_refresh_ms = 0
                # Runtime state memory: only re-sync when marked dirty (after tools / side effects).
                runtime_sync_started = time.perf_counter()
                did_runtime_sync = bool(getattr(self, "_runtime_state_memory_dirty", False))
                self._sync_runtime_state_memory()
                runtime_sync_ms = (
                    max(0, int((time.perf_counter() - runtime_sync_started) * 1000))
                    if did_runtime_sync
                    else 0
                )
                prompt_build_started = time.perf_counter()
                prompt_build_reused = _can_reuse_system_prompt(
                    has_cached_prompt=bool(self._cached_system_prompt),
                    prompt_built_with_runtime_key=prompt_built_with_runtime_key,
                    current_runtime_state_memory_key=self._last_runtime_state_memory_key,
                )
                if prompt_build_reused:
                    current_sp = sp
                else:
                    current_sp = self._build_system_prompt_for_turn(
                        stable_session_prompt=stable_session_prompt
                    )
                    sp = current_sp
                    prompt_built_with_runtime_key = self._last_runtime_state_memory_key
                current_prompt = to_string(current_sp)
                if current_prompt != self._cached_system_prompt:
                    messages = refresh_system_prefix_on_messages(
                        messages=messages,
                        system_prompt=current_sp,
                        static_context_blocks=turn_static_context_blocks,
                        build_cacheable_prefix_fn=build_cacheable_system_prefix_message,
                        is_dynamic_system_context_fn=is_dynamic_system_context_message,
                        build_dynamic_system_context_fn=build_dynamic_system_context_message,
                        extend_cacheable_prefix_fn=extend_system_message_cacheable_prefix,
                        insert_volatile_fn=TurnOutcomeController.insert_volatile_context_before_current_user,
                    )
                    self._cached_system_prompt = current_prompt
                # Live runtime status (budget/progress/mental) — every iteration.
                messages = self._apply_turn_status_bar(messages, iteration=iteration)
                prompt_build_ms = max(0, int((time.perf_counter() - prompt_build_started) * 1000))
                context_estimate_started = time.perf_counter()
                # Single estimate for UI + compress gate. Far under the compress
                # threshold uses a conservative char upper bound (no full precise walk).
                compress_threshold_tokens = self._automatic_context_compression_threshold_tokens()
                current_tokens = estimate_messages_tokens_for_threshold(
                    messages,
                    compress_threshold_tokens,
                )
                try:
                    ui.note_context_window(current_tokens, context_limit)
                except Exception:
                    pass
                context_estimate_ms = max(0, int((time.perf_counter() - context_estimate_started) * 1000))

                delegated = None
                delegation_ms = 0
                self._raise_if_turn_stop_requested()

                # 硬限制：超出最大上下文时强制压缩
                compression_triggered = self._should_automatically_compress(current_tokens)
                if compression_triggered:
                    messages, should_break = self._compress_messages(
                        messages, iteration, reason="达到配置的上下文压缩阈值"
                    )
                    # Re-estimate only after messages actually changed.
                    after_tokens = estimate_messages_tokens(messages)
                    try:
                        ui.note_context_window(after_tokens, context_limit)
                    except Exception:
                        pass
                    if should_break:
                        break
                    # 只有实际缩减上下文时才写 notice，禁止把 guard skip 伪装成已压缩。
                    if bool(getattr(self, "_last_context_compression_applied", False)):
                        messages.append(build_runtime_notice_message(
                            f"由于上下文超过最大承受能力，现在强制进行了一次压缩"
                            f"（{current_tokens} → {after_tokens} tokens）。"
                        ))
                self._raise_if_turn_stop_requested()
                _record_agent_scene_event(
                    "llm",
                    "agent.llm_preflight.completed",
                    message="Agent LLM preflight completed.",
                    fields={
                        "iteration": iteration,
                        "messageCount": len(messages),
                        "contextEstimatedTokens": current_tokens,
                        "contextCompressionThresholdTokens": compress_threshold_tokens,
                        "contextCompressionTriggered": compression_triggered,
                        "gitRefreshMs": git_refresh_ms,
                        "runtimeStateSyncMs": runtime_sync_ms,
                        "promptBuildMs": prompt_build_ms,
                        "promptBuildReused": prompt_build_reused,
                        "contextEstimateMs": context_estimate_ms,
                        "delegationMs": delegation_ms,
                        "totalPreflightMs": max(0, int((time.perf_counter() - pre_llm_started) * 1000)),
                    },
                )
                # Hard input-limit preflight: never invoke the model when the
                # estimated input still exceeds the versioned hard limit
                # (auditable context_budget_exhausted, fail-closed).
                preflight_tokens = max(
                    int(current_tokens or 0),
                    int(after_tokens) if compression_triggered else 0,
                )
                if self._context_budget_preflight_guard(
                    estimated_tokens=preflight_tokens,
                    iteration=iteration,
                    message_count=len(messages),
                ):
                    # The guard already recorded the structured
                    # context_budget_exhausted diagnostic and set
                    # _last_turn_failed; just close the turn here.
                    break
                if policy.mode == AgentMode.CHAT:
                    messages, reconcile_ok = self._reconcile_chat_conversation_before_llm(messages)
                    if not reconcile_ok:
                        break
                invocation_result = self._invoke_llm(messages, replay_state=provider_replay_state)
                if (
                    invocation_result is None
                    and provider_replay_state is not None
                    and bool(getattr(provider_replay_state, "response_id", ""))
                    and not responses_continuation_disabled
                ):
                    continuation_rejected = _provider_rejected_responses_continuation(
                        category=getattr(self, "_last_llm_error_category", ""),
                        message=getattr(self, "_last_llm_error_message", ""),
                        details=getattr(self, "_last_llm_error_details", {}),
                    )
                    if continuation_rejected:
                        responses_continuation_disabled = True
                        provider_replay_state = provider_replay_state.without_response_id()
                        _record_agent_scene_event(
                            "llm",
                            "agent.responses_continuation.fallback",
                            message="Responses continuation rejected; retrying once with stateless replay.",
                            fields={
                                "iteration": iteration,
                                "reason": "provider_rejected_previous_response_id",
                            },
                        )
                        invocation_result = self._invoke_llm(messages, replay_state=provider_replay_state)
                if invocation_result is None:
                    consecutive_failures = round_state.note_llm_failure()
                    self._last_turn_failed = True
                    ui.update_status(
                        "ERROR",
                        **round_state.current_status(),
                    )
                    ui.add_log(
                        f"LLM 调用失败（第 {consecutive_failures} 次连续失败）", "ERROR"
                    )
                    stop_reason = self._get_turn_outcome_controller().should_stop_after_llm_failure(
                        category=self._last_llm_error_category,
                        retryable=self._last_llm_error_retryable,
                        consecutive_failures=consecutive_failures,
                        iteration=iteration,
                        attempts=self._last_llm_failure_attempts,
                        max_attempts=self._last_llm_failure_max_attempts,
                    )
                    if stop_reason:
                        ui.add_log(stop_reason, "WARN")
                        llm_error_details = dict(getattr(self, "_last_llm_error_details", {}) or {})
                        safe_projection_details = _safe_llm_error_diagnostic_details(llm_error_details)
                        self._last_turn_metadata = {
                            **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                            "llm_failure": {
                                "category": self._last_llm_error_category or "",
                                "retryable": bool(self._last_llm_error_retryable),
                                "recovery_action": self._last_llm_recovery_action or "",
                                "message": self._last_llm_error_message or "",
                                "exception_type": llm_error_details.get("exception_type", ""),
                                "exception_message": llm_error_details.get("exception_message", ""),
                                "provider": llm_error_details.get("provider", ""),
                                "model": llm_error_details.get("model", ""),
                                "api_base": llm_error_details.get("api_base", ""),
                                "consecutive_failures": consecutive_failures,
                                "attempts": self._last_llm_failure_attempts,
                                "max_attempts": self._last_llm_failure_max_attempts,
                                "stop_reason": stop_reason,
                                "payload_validation": safe_projection_details,
                            },
                        }
                        break
                    self._publish_llm_retry_status(
                        attempt=max(consecutive_failures, int(self._last_llm_failure_attempts or 0)),
                        max_attempts=int(self._last_llm_failure_max_attempts or MAX_CONSECUTIVE_FAILURES),
                    )
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        ui.add_log(
                            f"连续失败达到 {MAX_CONSECUTIVE_FAILURES} 次，停止运行。",
                            "ERROR",
                        )
                        break
                    continue
                if isinstance(invocation_result, tuple) and len(invocation_result) == 2:
                    turn_outcome, response = invocation_result
                else:
                    response = invocation_result
                    compatibility_scope = InvocationScope(
                        session_id=str(getattr(self, "session_id", "") or "agent-session"),
                        turn_id=str(
                            getattr(current_turn, "turn_id", "")
                            or getattr(current_turn, "id", "")
                            or f"turn-{iteration}"
                        ),
                        invocation_id=f"compatibility-{iteration}",
                        iteration=max(0, int(iteration or 0)),
                    )
                    turn_outcome = canonical_outcome_from_message(response, scope=compatibility_scope)
                provider_replay_state = turn_outcome.replay_state
                if responses_continuation_disabled and provider_replay_state is not None:
                    provider_replay_state = provider_replay_state.without_response_id()
                if policy.mode == AgentMode.CHAT:
                    self._chat_provider_replay_state = provider_replay_state

# 轻量预解析：先看 raw_content / tool_calls / xml_tool_calls，重活留给 finalize
                response_preview = self._get_response_processor().preview(response)
                raw_content = response_preview.raw_content
                _debug_logger.debug(f"content 长度={len(raw_content)}", tag="RAW")
                tool_call_count = response_preview.tool_call_count
                has_tool_calls = response_preview.has_tool_calls
                try:
                    iteration_decision = TurnOutcomeController.decide_llm_iteration(turn_outcome)
                except ValueError as exc:
                    consecutive_failures = round_state.note_llm_failure()
                    self._record_turn_failure_diagnostic(
                        category="protocol_error",
                        reason_code="canonical_turn_outcome_missing",
                        reason_summary="模型响应未完成规范化",
                        reason_detail="模型已返回，但响应适配器没有生成 canonical TurnOutcome。",
                        chain_stage="llm_response_normalization",
                        event_code="llm.turn_outcome.missing",
                        exception_type=type(exc).__name__,
                        fields={
                            "iteration": iteration,
                            "consecutiveFailures": consecutive_failures,
                        },
                    )
                    ui.update_status("ERROR", **round_state.current_status())
                    ui.add_log("LLM 响应缺少 canonical TurnOutcome，本轮失败收口。", "ERROR")
                    break
                tool_call_count = len(iteration_decision.tool_calls)
                has_tool_calls = iteration_decision.should_execute_tools
                round_state.note_turn_outcome(iteration_decision.outcome.kind)
                from core.infrastructure.event_bus import EventNames

                self.event_bus.publish(
                    EventNames.LLM_RESPONSE,
                    {"turn_outcome": iteration_decision.outcome},
                    source="agent.canonical_turn_outcome",
                    blocking=True,
                )
                _record_agent_scene_event(
                    "llm",
                    "llm.turn_outcome.finalized",
                    message="Agent accepted canonical TurnOutcome for iteration control.",
                    fields={
                        "iteration": iteration,
                        "outcomeKind": iteration_decision.outcome.kind,
                        "terminalEventSeen": bool(iteration_decision.outcome.terminal_event_seen),
                        "pendingCallCount": len(iteration_decision.outcome.pending_tool_call_ids),
                        "toolCallCount": tool_call_count,
                        "invocationId": iteration_decision.outcome.identity.invocation_id,
                    },
                )

                # ── 感知层触发 ──
                state_block_str = self._get_response_surface_controller().build_state_block(
                    raw_content=raw_content,
                    has_tool_calls=has_tool_calls,
                    consecutive_failures=round_state.consecutive_failures,
                    iteration=iteration,
                    messages=messages,
                    mental_model=self.mental_model,
                    effective_max_token_limit=self._effective_max_token_limit,
                    mental_model_enabled=self.is_mental_model_enabled_for_turn(),
                )

# <state> 注入：剥离模型输出中的回显，防止雪球效应
                processed = self._get_response_processor().finalize(
                    response, response_preview, state_block_str
                )
                self._apply_active_components_request(processed)
                self._get_response_surface_controller().apply_state_feedback(
                    processed=processed,
                    record_language_drift=self._record_language_drift,
                    record_inference_activity=self._record_inference_activity,
                    mental_model_enabled=self.is_mental_model_enabled_for_turn(),
                )
                # 进展标记
                round_state.note_progress()
                self._last_turn_failed = False

                # Token 使用统计
                token_usage = self._get_response_surface_controller().record_token_usage(
                    response=response,
                    round_state=round_state,
                    current_turn=current_turn,
                    messages=messages,
                    raw_content=raw_content,
                    estimate_output_tokens=estimate_tokens_precise,
                )
                input_tokens, output_tokens = token_usage
                self._record_turn_cache_diagnostics(
                    token_usage=token_usage,
                    response=response,
                    messages=messages,
                    current_turn=current_turn,
                )

                logger.log_llm_response(
                    raw_content,
                    raw_response=raw_content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tool_call_count=tool_call_count,
                )

                # 输出思考内容到 UI
                response_surface = self._get_response_surface_controller().emit_visible_response(
                    raw_content=raw_content,
                    processed=processed,
                    tool_call_count=tool_call_count,
                )
                self._last_visible_response_text = response_surface["last_visible_response_text"]
                self._last_response_tool_calls = response_surface["last_response_tool_calls"]
                reasoning_content = ResponseProcessor.coerce_content_text(
                    (getattr(response, "additional_kwargs", None) or {}).get("reasoning_content", "")
                ).strip()
                if reasoning_content:
                    self._last_turn_metadata = {
                        **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                        "reasoning_content": reasoning_content,
                    }
                if processed.state_info:
                    self._last_turn_metadata = {
                        **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                        "state_info": dict(processed.state_info),
                    }

                tool_calls = list(iteration_decision.tool_calls)
                response_tool_names = [
                    str(tool_call.get("name") or "").strip()
                    for tool_call in tool_calls
                    if str(tool_call.get("name") or "").strip()
                ]
                round_state.note_response_tools(
                    tool_call_count,
                    self._last_visible_response_text,
                    tool_names=response_tool_names,
                )
                self._report_round_state_stall_signals(round_state)
                turn_tool_names.extend(response_tool_names)
                if iteration_decision.should_execute_tools:
                    ui.update_status(
                        "ACTING",
                        **round_state.acting_status(len(tool_calls)),
                    )
                elif iteration_decision.should_finish:
                    ui.update_status(
                        "SUCCESS",
                        **round_state.current_status(),
                    )
                else:
                    ui.update_status(
                        "ERROR",
                        **round_state.current_status(),
                    )
                messages.append(
                    processed.build_ai_message(
                        response,
                        tool_calls_override=tool_calls,
                    )
                )
                self._raise_if_turn_stop_requested()
                if iteration_decision.should_finish:
                    ui.add_log("模型已返回 canonical final_answer，本轮收束。", "INFO")
                    break
                if iteration_decision.should_stop_unsuccessfully:
                    round_state.note_llm_failure()
                    self._record_turn_failure_diagnostic(
                        category="protocol_error",
                        reason_code="canonical_turn_unsuccessful",
                        reason_summary="模型返回了非成功 canonical 终态",
                        reason_detail=(
                            f"canonical TurnOutcome 以 {iteration_decision.outcome.kind} 结束，未标记完成。"
                        ),
                        chain_stage="agent_outcome_evaluation",
                        event_code="llm.turn_outcome.unsuccessful",
                        fields={"outcomeKind": iteration_decision.outcome.kind, "iteration": iteration},
                    )
                    ui.add_log(
                        f"模型本轮以 canonical {iteration_decision.outcome.kind} 终止，未标记完成。",
                        "ERROR",
                    )
                    break
                if not iteration_decision.should_execute_tools:
                    round_state.note_llm_failure()
                    self._record_turn_failure_diagnostic(
                        category="protocol_error",
                        reason_code="canonical_tool_calls_empty",
                        reason_summary="模型返回的工具终态没有可执行调用",
                        reason_detail="canonical tool_calls outcome 未包含可执行工具。",
                        chain_stage="agent_tool_dispatch",
                        event_code="llm.turn_outcome.empty_tools",
                        fields={"iteration": iteration},
                    )
                    ui.add_log("canonical tool_calls outcome 未包含可执行工具，本轮失败收口。", "ERROR")
                    break
                round_state.add_tool_calls(len(tool_calls))
                self._raise_if_turn_stop_requested()
                executable_tool_calls = []
                for tool_call in tool_calls:
                    tool_name = str(tool_call.get("name") or "").strip()
                    if self._is_tool_visible_to_current_agent(tool_name):
                        executable_tool_calls.append(tool_call)
                        continue
                    result = self._hidden_tool_call_message(tool_name)
                    _record_agent_scene_event(
                        "tool_visibility",
                        "agent.hidden_tool_call.blocked",
                        message="Canonical tool call was blocked before ToolExecutor.",
                        fields={
                            "agentId": str((getattr(self, "runtime_agent_binding", {}) or {}).get("agentId") or "").strip(),
                            "toolName": tool_name,
                            "visibleToolCount": len(getattr(self, "key_tool_maps", set()) or []),
                        },
                    )
                    self._remember_tool_output(tool_call, result, None)
                    self.tool_lifecycle.handle_tool_result(tool_call, result, None, messages)
                lifecycle_action = (
                    self.tool_lifecycle.execute_tools(executable_tool_calls, messages)
                    if executable_tool_calls
                    else None
                )
                # Tools (and tool blockers / validation notes) may change runtime state memory.
                if executable_tool_calls or tool_calls:
                    self._mark_runtime_state_memory_dirty()
                self._raise_if_turn_stop_requested()
                if lifecycle_action == "turn_complete":
                    round_state.note_lifecycle_completion()
                    get_session_state().note_scope_completion("当前事务已完成，停止当前轮继续扩散。")
                    self._mark_runtime_state_memory_dirty()
                if lifecycle_action == "tool_budget_exhausted":
                    # Hard stop: budget resets on the next user message's auth install.
                    self._mark_runtime_state_memory_dirty()
                lifecycle_decision = (
                    self._get_turn_outcome_controller().handle_lifecycle_action(lifecycle_action)
                    if lifecycle_action
                    else LifecycleDecision()
                )
                if lifecycle_decision.pending_action:
                    self._pending_lifecycle_action = lifecycle_decision.pending_action
                if lifecycle_decision.info_log:
                    ui.add_log(lifecycle_decision.info_log, "INFO")
                if not lifecycle_decision.continue_main_loop:
                    return False
                if lifecycle_decision.break_round:
                    break
                if tool_calls:
                    ui.update_status(
                        "WORKING",
                        **round_state.current_status(),
                    )

                # 检查压缩请求（compress_context_tool 设置的标志）
                if is_compression_requested():
                    reason = consume_compression_request()
                    _debug_logger.info(f"[压缩] 感知层请求压缩: {reason}", tag="STATE")
                    messages, _ = self._compress_messages(messages, iteration, reason=reason)
                    self._mark_runtime_state_memory_dirty()
                    self._raise_if_turn_stop_requested()

        except TurnStopRequested as stop_request:
            self._last_turn_metadata = {
                **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                "status": "stopped",
                "stop_requested": True,
                "stop_reason": str(stop_request or "").strip(),
            }
            ui.add_log("收到网页终止请求，本轮在安全点收束。", "WARN")
        except Exception as e:
            # Keep failure sticky across finalize_round: consecutive_failures may still be 0
            # (e.g. subprocess.TimeoutExpired) while the turn must not look completed.
            round_return_ok = False
            exception_preview = str(e or "").strip()
            if len(exception_preview) > 240:
                exception_preview = exception_preview[:237] + "..."
            reason_detail = (
                f"Agent 主循环发生 {type(e).__name__}"
                + (f"：{exception_preview}" if exception_preview else "")
                + "，请按 Trace 定位运行场景。"
            )
            self._record_turn_failure_diagnostic(
                category="runtime_error",
                reason_code="agent_main_loop_exception",
                reason_summary="Agent 主循环异常",
                reason_detail=reason_detail,
                chain_stage="agent_main_loop",
                event_code="agent.turn.failed_exception",
                exception_type=type(e).__name__,
            )
            self._last_turn_failed = True
            self._last_turn_metadata = {
                **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                "status": "failed",
                "outcome": "failed",
                "main_loop_exception": type(e).__name__,
            }
            ui.update_status(
                "ERROR",
                **round_state.current_status(),
            )
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=traceback.format_exc())
        finally:
            # 轮次结束统计（无论正常结束还是异常，都记录）
            exception_failed = bool(getattr(self, "_last_turn_failed", False))
            finalization = self._get_turn_outcome_controller().finalize_round(round_state=round_state)
            # Do not let progress-only finalization wipe a main-loop / diagnostic failure.
            self._last_turn_failed = bool(finalization.last_turn_failed or exception_failed)
            if bool(getattr(finalization, "max_iteration_exhausted_without_final_answer", False)) and not exception_failed:
                round_return_ok = False
                stop_reason = str(getattr(finalization, "stop_reason", "") or "").strip()
                ui.add_log(stop_reason, "WARN")
                self._last_turn_metadata = {
                    **dict(getattr(self, "_last_turn_metadata", {}) or {}),
                    "status": "stopped",
                    "outcome": "blocked",
                    "max_iteration_exhausted": True,
                    "stop_reason": stop_reason,
                    "summary": stop_reason,
                    "raw_output": stop_reason,
                }
            turn_success = bool(finalization.turn_success) and not self._last_turn_failed
            ui_status = (
                "ERROR"
                if self._last_turn_failed
                else finalization.ui_status
            )
            ui.note_turn_result(success=turn_success, had_progress=round_state.turn_had_progress)
            ui.update_status(
                ui_status,
                **round_state.current_status(),
            )
            logger.log_turn_end(current_turn, finalization.turn_stats)
            carryover_messages = [
                message for message in messages
                if not is_volatile_system_context_message(message)
            ]
            carryover = TurnOutcomeController.finish_turn_message_carryover(
                messages=carryover_messages,
                lifecycle_action=lifecycle_action,
                active_goal=self._active_goal,
                turn_identity=str(getattr(self, "_active_turn_identity", "") or "").strip(),
            )
            self._active_turn_messages = carryover.messages
            self._active_turn_goal = carryover.goal
            self._active_turn_identity = carryover.turn_identity
            self._active_turn_terminal = carryover.terminal
            self._capture_chat_dataset_candidate_if_needed(
                user_prompt=user_prompt,
                current_turn=current_turn,
                tool_names=turn_tool_names,
                delegated=delegated_this_turn,
            )
            self._refresh_retrospective_state_memory()
            _debug_logger.turn_end(current_turn, tool_count=round_state.total_tool_calls)

        return round_return_ok

    def _build_chat_user_message_for_turn(
        self,
        content: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        image_urls: List[str] = []
        for item in list(attachments or []):
            if not isinstance(item, dict):
                continue
            data_url = str(item.get("dataUrl") or item.get("data_url") or "").strip()
            if data_url:
                image_urls.append(data_url)
        if image_urls:
            return build_chat_user_multimodal_message(content, image_urls)
        return build_chat_user_message(content)

    def _publish_llm_retry_status(self, *, attempt: int, max_attempts: int) -> None:
        """Surface outer Agent reconnect attempts for live session feedback."""
        publish_llm_retry_status(
            attempt=attempt,
            max_attempts=max_attempts,
            category=str(getattr(self, "_last_llm_error_category", "") or ""),
            action=str(getattr(self, "_last_llm_recovery_action", "") or ""),
            event_bus_getter=get_event_bus,
        )

    def _record_turn_cache_diagnostics(
        self,
        *,
        token_usage: Any,
        response: Any,
        messages: List[Any],
        current_turn: int,
    ) -> Dict[str, Any]:
        llm_usage, metadata_update = record_turn_cache_diagnostics(
            token_usage=token_usage,
            response=response,
            messages=messages,
            current_turn=current_turn,
            context_window_limit=int(
                getattr(
                    self,
                    "_context_window_limit",
                    getattr(self, "_effective_max_token_limit", 0),
                )
                or 0
            ),
            get_ui_fn=get_ui,
            turn_runtime_fn=_turn_runtime_from_env,
        )
        self._last_turn_metadata = {
            **dict(getattr(self, "_last_turn_metadata", {}) or {}),
            **metadata_update,
        }
        return llm_usage

    def _build_llm_invocation_context(
        self,
        *,
        prompt_purpose: str = "main_reply",
        route_attempt: int = 1,
    ) -> LLMInvocationContext:
        try:
            policy = self._get_mode_policy()
            mode_value = str(getattr(policy.mode, "value", policy.mode) or "").strip()
            orchestrator_kind = str(getattr(policy, "orchestrator_kind", "") or "").strip()
        except Exception:
            mode_value = ""
            orchestrator_kind = ""
        return build_llm_invocation_context(
            runtime_binding=getattr(self, "runtime_agent_binding", {}) or {},
            mode_value=mode_value,
            orchestrator_kind=orchestrator_kind,
            pending_supervised_case_id=str(getattr(self, "_pending_supervised_case_id", "") or ""),
            tool_authorization_fingerprint=str(getattr(self, "_tool_authorization_decision_fingerprint", "") or ""),
            ledger_conversation_fingerprint=str(getattr(self, "_ledger_conversation_fingerprint", "") or ""),
            prompt_purpose=prompt_purpose,
            route_attempt=route_attempt,
            turn_runtime_fn=_turn_runtime_from_env,
            status_context_fn=current_llm_status_context,
        )

    def _report_round_state_stall_signals(self, round_state) -> None:
        """RoundState 卡住信号跨阈值时记录一次性诊断日志（STATE tag）。

        信号归零（进展恢复）后清除已报告标记，再次跨越阈值可重复报告。
        任何失败静默降级，绝不干扰主循环。
        Removal: keep while tests/monkeypatch still target this agent method.
        """
        try:
            self._last_reported_stall_signals = report_round_state_stall_signals(
                round_state,
                dict(getattr(self, "_last_reported_stall_signals", {}) or {}),
                debug_logger=_debug_logger,
            )
        except Exception:
            pass

    def _record_turn_failure_diagnostic(
        self,
        *,
        category: str,
        reason_code: str,
        reason_summary: str,
        reason_detail: str,
        chain_stage: str,
        event_code: str,
        exception_type: str = "",
        retryable: bool = False,
        recovery_action: str = "inspect_runtime_scene",
        message: str = "",
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a bounded, prompt-free failure envelope for the whole turn chain."""

        def _bounded(value: Any, limit: int = 500) -> str:
            return str(value or "").strip()[:limit]

        category_value = _bounded(category, 80) or "runtime_error"
        reason_code_value = _bounded(reason_code, 120) or category_value
        reason_summary_value = _bounded(reason_summary, 240) or "当前轮执行失败"
        reason_detail_value = _bounded(reason_detail, 500) or reason_summary_value
        chain_stage_value = _bounded(chain_stage, 120) or "agent_turn"
        event_code_value = _bounded(event_code, 160) or "agent.turn.failed"
        exception_type_value = _bounded(exception_type, 160)
        visible_message = _bounded(message, 500) or f"{reason_summary_value}：{reason_detail_value}"

        previous_details = dict(getattr(self, "_last_llm_error_details", {}) or {})
        details = {
            **previous_details,
            "reason_code": reason_code_value,
            "reason_summary": reason_summary_value,
            "reason_detail": reason_detail_value,
            "chain_stage": chain_stage_value,
            "event_code": event_code_value,
            "exception_type": exception_type_value,
        }
        failure = {
            "category": category_value,
            "retryable": bool(retryable),
            "recovery_action": _bounded(recovery_action, 120),
            "message": visible_message,
            "exception_type": exception_type_value,
            "provider": _bounded(previous_details.get("provider"), 160),
            "model": _bounded(previous_details.get("model"), 160),
            "api_base": _bounded(previous_details.get("api_base"), 240),
            "reason_code": reason_code_value,
            "reason_summary": reason_summary_value,
            "reason_detail": reason_detail_value,
            "chain_stage": chain_stage_value,
            "event_code": event_code_value,
            "attempts": int(getattr(self, "_last_llm_failure_attempts", 0) or 0),
            "max_attempts": int(getattr(self, "_last_llm_failure_max_attempts", 0) or 0),
        }

        self._last_turn_failed = True
        self._last_llm_error_category = category_value
        self._last_llm_error_retryable = bool(retryable)
        self._last_llm_recovery_action = _bounded(recovery_action, 120)
        self._last_llm_error_message = visible_message
        self._last_llm_error_details = details
        self._last_turn_metadata = {
            **dict(getattr(self, "_last_turn_metadata", {}) or {}),
            "llm_failure": failure,
        }

        runtime = _turn_runtime_from_env()
        status_context = current_llm_status_context()
        binding = getattr(self, "runtime_agent_binding", {}) or {}
        scene_fields = {
            "sessionId": str(
                runtime.get("sessionId")
                or status_context.get("session_id")
                or status_context.get("sessionId")
                or binding.get("directSessionId")
                or ""
            ).strip(),
            "turnId": str(
                status_context.get("turn_id")
                or status_context.get("turnId")
                or runtime.get("runId")
                or ""
            ).strip(),
            "runId": str(runtime.get("runId") or "").strip(),
            "agentId": str(
                runtime.get("agentId")
                or binding.get("agentId")
                or ""
            ).strip(),
            "chainStage": chain_stage_value,
            "reasonCode": reason_code_value,
            "category": category_value,
            "retryable": bool(retryable),
            "exceptionType": exception_type_value,
        }
        for key, value in dict(fields or {}).items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                scene_fields[str(key)[:80]] = _bounded(value, 240) if isinstance(value, str) else value
        _record_agent_scene_event(
            "llm",
            event_code_value,
            message=reason_summary_value,
            level="error",
            fields=scene_fields,
        )
        self._announce_scene_diagnostic_package()
        return failure

    def _resolve_current_scene_dir_for_diagnostic(self):
        """解析当前运行时场景目录（CLI/无 UI 模式下排查入口提示用）。"""
        try:
            from core.web.services.runtime_scene.record import _resolve_current_runtime_scene_dir

            return _resolve_current_runtime_scene_dir()
        except Exception:
            return None

    def _announce_scene_diagnostic_package(self) -> None:
        """失败时提示场景诊断包入口（UI 模式已有场景页导航；CLI 模式给出文件路径）。"""
        try:
            scene_dir = self._resolve_current_scene_dir_for_diagnostic()
            if scene_dir is None:
                return
            ui = get_ui()
            if ui is None or not hasattr(ui, "add_log"):
                return
            try:
                from core.runtime_manager.constants import PROJECT_ROOT

                display_path = os.path.relpath(str(scene_dir), str(PROJECT_ROOT)).replace("\\", "/")
            except Exception:
                display_path = str(scene_dir)
            ui.add_log(
                f"诊断包: {display_path}/（先读 package_index.json，再按推荐顺序展开）",
                "ERROR",
            )
        except Exception:
            pass

    def _invoke_llm(self, messages: list, *, replay_state: Any = None) -> Optional[Any]:
        # Removal: keep while tests call SelfEvolvingAgent._invoke_llm and patch agent.* helpers.
        # Reset before delegation so a stop/interrupt cannot leave diagnostics
        # from an earlier invocation attached to the active turn.
        self._last_llm_error_category = None
        self._last_llm_error_retryable = False
        self._last_llm_recovery_action = None
        self._last_llm_error_message = ""
        self._last_llm_error_details = {}
        self._last_llm_failure_attempts = 0
        self._last_llm_failure_max_attempts = MAX_CONSECUTIVE_FAILURES

        def _turn_llm_cancel_context(checker):
            # Provider abort is a Challenge-only extension. Ordinary Agent
            # turns still observe the stop checker, but must not allocate a
            # LiteLLM HTTP watcher merely because the checker is callable.
            return llm_cancel_context(
                checker,
                enable_chat_provider_abort=bool(
                    getattr(
                        getattr(self, "_turn_interrupt_checker", None),
                        "_vibelution_chat_provider_abort_enabled",
                        False,
                    )
                ),
            )

        result = invoke_agent_llm_turn(
            messages=messages,
            replay_state=replay_state,
            hooks=AgentLlmTurnHooks(
                get_ui=get_ui,
                llm_cancel_context=_turn_llm_cancel_context,
                raise_if_stop=self._raise_if_turn_stop_requested,
                current_stop_reason=self._current_turn_stop_reason,
                get_llm_for_mode=self._get_llm_for_current_mode,
                should_stream=self._should_stream_llm_for_turn,
                build_invocation_context=self._build_llm_invocation_context,
                invoke_outcome=invoke_llm_outcome,
                run_streaming_outcome=run_streaming_llm_outcome,
                canonicalize=canonicalize_legacy_xml_outcome,
                plan_recovery=plan_llm_recovery,
                record_scene_event=_record_agent_scene_event,
                record_route_success=_record_llm_route_success,
                request_compression=request_compression,
                debug_logger=_debug_logger,
                error_logger=logger,
                config=getattr(self, "config", None),
                force_disable_tools=bool(getattr(self, "_force_disable_tools_for_turn", False)),
                stop_error_cls=TurnStopRequested,
                base_llm=getattr(self, "_base_llm", None),
                structured_output_contract=getattr(
                    self,
                    "_turn_structured_output_contract",
                    None,
                ),
            ),
        )
        self._last_llm_error_category = result.last_error_category
        self._last_llm_error_retryable = result.last_error_retryable
        self._last_llm_recovery_action = result.last_recovery_action
        self._last_llm_error_message = result.last_error_message
        self._last_llm_error_details = dict(result.last_error_details)
        self._last_llm_failure_attempts = result.last_failure_attempts
        self._last_llm_failure_max_attempts = result.last_failure_max_attempts
        return result.payload

    def _get_response_processor(self) -> ResponseProcessor:
        processor = getattr(self, "response_processor", None)
        if processor is None:
            processor = ResponseProcessor()
            self.response_processor = processor
        return processor

    def _apply_active_components_request(self, processed: ResponseProcessingResult) -> None:
        components = list(getattr(processed, "active_components", []) or [])
        if not components:
            return
        _debug_logger.info(
            f"[PromptManager] 观测到兼容标签但不应用: {', '.join(components)}",
            tag="PROMPT",
        )
        try:
            logger.log_action(
                "active_components_observed",
                {
                    "requested": components,
                    "applied": [],
                    "mode": "diagnostic_only",
                },
            )
        except Exception:
            pass
        _record_agent_scene_event(
            "prompt",
            "prompt.components.request_observed",
            message="模型组件请求仅作为兼容诊断记录，未修改系统 Prompt。",
            fields={
                "requested": components,
                "applied": [],
                "mode": "diagnostic_only",
            },
        )

    def _create_round_state(self) -> RoundStateController:
        return RoundStateController(max_iterations=self.config.agent.max_iterations)

    def _is_restart_focus_mode(self) -> bool:
        if self._expects_restart_after_transaction_close():
            return False
        return is_restart_focused_goal(getattr(self, "_active_goal", ""))

    def _guard_tool_execution(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        # Removal: keep while ToolLifecycleBridge is constructed with this bound method.
        del tool_args
        return guard_restart_focus_tool(
            tool_name,
            restart_focus=self._is_restart_focus_mode(),
        )

    def set_turn_interrupt_checker(self, checker=None) -> None:
        self._turn_interrupt_checker = checker
        set_cancel_checker = getattr(getattr(self, "tool_executor", None), "set_cancel_checker", None)
        if callable(set_cancel_checker):
            # Cached chat Agents can resume on a different worker thread. Bind the
            # checker in that thread's ContextVar so an active tool sees stop now.
            set_cancel_checker(
                self._current_turn_stop_reason if callable(checker) else None,
                owner=self,
            )

    def _current_turn_stop_reason(self) -> str:
        checker = getattr(self, "_turn_interrupt_checker", None)
        if not callable(checker):
            return ""
        try:
            reason = checker()
        except Exception:
            return ""
        return str(reason or "").strip()

    def _raise_if_turn_stop_requested(self) -> None:
        reason = self._current_turn_stop_reason()
        if reason:
            raise TurnStopRequested(reason)

    def run_loop(self, initial_prompt: str = None) -> None:
        policy = self._get_mode_policy()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        _debug_logger.start_session(session_id)
        _debug_logger.system("主循环开始", tag=self.name)

        llm_config = self.config.llm
        model_name = (
            llm_config.get_profile(role="primary").model
            if hasattr(llm_config, "get_profile")
            else getattr(llm_config, "model_name", "unknown")
        )
        logger.start_session(metadata={
            "model": model_name,
            "agent_mode": policy.mode.value,
            "token_limit": self._effective_max_token_limit,
            "tools_count": len(self.key_tools),
            "max_iterations": self.config.agent.max_iterations,
            "awake_interval": self.config.agent.awake_interval,
            "session_topic": f"main_loop_{policy.mode.value}",
        })
        logger.log_action("会话开始", f"模型: {model_name}")
        get_state_manager().set_state(AgentState.AWAKENING, action="主循环启动")

        try:
            _debug_logger.kv("记忆状态", f"{get_current_goal()[:50]}")
            _print_evolution_time_core()

            external_request = initial_prompt

            while True:
                self._last_turn_failed = False
                result = self.think_and_act(user_prompt=external_request)
                external_request = None

                if not result:
                    break
                if not policy.allow_auto_loop:
                    break

                _debug_logger.system("执行完成，准备下一轮...", tag="AGENT")

                # 网络退避：连续失败的轮次越多，等待越久
                if self._last_turn_failed:
                    self._consecutive_failed_turns += 1
                    backoff = min(30 * self._consecutive_failed_turns, 300)
                    _debug_logger.warning(
                        f"上一轮 LLM 连续失败，等待 {backoff}s 后重试 "
                        f"(连续失败轮次: {self._consecutive_failed_turns})", tag="AGENT"
                    )
                    time.sleep(backoff)
                else:
                    self._consecutive_failed_turns = 0

                # 检查 Cron 到期任务
                try:
                    from core.infrastructure.cron_scheduler import get_cron_scheduler
                    from core.infrastructure.background_tasks import get_background_task_manager
                    sched = get_cron_scheduler()
                    due_jobs = sched.get_due_jobs()
                    if due_jobs:
                        mgr = get_background_task_manager()
                        for job in due_jobs:
                            mgr.start_task(command=job["command"], timeout=300)
                            _debug_logger.info(f"Cron 触发: {job['name']} ({job['id']})", tag="CRON")
                except Exception:
                    pass

                time.sleep(2)

        except KeyboardInterrupt:
            _debug_logger.info("收到中断，退出", tag="AGENT")
        except Exception as e:
            _debug_logger.error(f"主循环异常: {type(e).__name__}: {e}", exc_info=traceback.format_exc())
            logger.log_error("main_loop_exception", str(e), traceback.format_exc())
        finally:
            # 会话结束自动清理碎片
            try:
                from core.infrastructure.workspace_cleaner import auto_clean_session_debris
                ws_path = str(self.workspace_path)
                result = auto_clean_session_debris(ws_path, mental_model=self.mental_model)
                if result.get("deleted_count", 0) > 0:
                    _debug_logger.info(
                        f"[AutoClean] 已清理 {result['deleted_count']} 个碎片文件",
                        tag="CLEANER"
                    )
            except Exception:
                pass

            uptime = datetime.now() - self.start_time
            _debug_logger.info(f"运行结束 (运行时长: {uptime})", tag=self.name)
            get_state_manager().set_state(AgentState.IDLE, action="系统已关闭")
            _debug_logger.end_session()
            logger.end_session({
                "uptime_seconds": uptime.total_seconds(),
                "total_turns": logger._turn_count,
            })

        if self._pending_lifecycle_action == "restart":
            _debug_logger.info("检测到重启动作，当前进程退出，交由守护进程接管", tag="RESTART")
            raise SystemExit(0)

        if self._pending_lifecycle_action == "hibernated":
            _debug_logger.info("休眠动作已完成，当前主循环返回", tag="HIBERNATION")

    def run_single_turn(
        self,
        initial_prompt: str = None,
        goal_override: str = None,
        case_id: str = None,
        disable_tools: bool = False,
        allowed_tool_names: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """执行单轮思考并返回结构化摘要。"""
        policy = self._get_mode_policy()
        effective_goal_override = None if policy.mode == AgentMode.CHAT else goal_override
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        _debug_logger.start_session(session_id)
        _debug_logger.system("单轮主循环开始", tag=self.name)
        llm_config = self.config.llm
        model_name = (
            llm_config.get_profile(role="primary").model
            if hasattr(llm_config, "get_profile")
            else getattr(llm_config, "model_name", "unknown")
        )
        conversation_topic = _normalize_goal_from_chat_history(
            initial_prompt or "",
            effective_goal_override,
            getattr(self, "_active_turn_messages", None),
        )
        logger.start_session(metadata={
            "mode": "single_turn",
            "agent_mode": policy.mode.value,
            "model": model_name,
            "token_limit": self._effective_max_token_limit,
            "tools_count": len(self.key_tools),
            "max_iterations": self.config.agent.max_iterations,
            "awake_interval": self.config.agent.awake_interval,
            "conversation_topic": str(conversation_topic or case_id or "single_turn").strip()[:160],
        })
        self._last_visible_response_text = ""
        self._last_response_tool_calls = 0
        self._recent_tool_outputs = []
        self._recent_tool_records = []
        self._last_turn_metadata = {}
        self._last_llm_error_message = ""
        self._last_llm_failure_attempts = 0
        self._last_llm_failure_max_attempts = 0
        session = get_session_state()
        turn_runtime = _turn_runtime_from_env()
        turn_runtime_metadata = _safe_turn_runtime_metadata(turn_runtime)
        ok = False
        previous_force_disable_tools = bool(getattr(self, "_force_disable_tools_for_turn", False))
        previous_turn_allowed_tool_names = getattr(self, "_turn_allowed_tool_names", None)
        try:
            self._single_turn_mode_active = True
            self._force_disable_tools_for_turn = bool(disable_tools)
            self._turn_allowed_tool_names = (
                {
                    str(item or "").strip()
                    for item in list(allowed_tool_names or [])
                    if str(item or "").strip()
                }
                if allowed_tool_names is not None
                else None
            )
            self._pending_supervised_case_id = case_id
            cache_partition = str(turn_runtime.get("promptCachePartition") or "").strip()
            cache_scope = prompt_cache_partition_scope(cache_partition) if cache_partition else nullcontext()
            with cache_scope:
                ok = self.think_and_act(
                    user_prompt=initial_prompt,
                    goal_override=effective_goal_override,
                    attachments=attachments,
                )
            snapshot = session.get_attention_snapshot()
            latest_delegation = None
            if snapshot.get("delegation_findings"):
                latest_delegation = snapshot["delegation_findings"][-1]
            partial_visible = sanitize_assistant_visible_text(self._last_visible_response_text)
            error_message = str(getattr(self, "_last_llm_error_message", "") or "").strip()
            parsed_payload: Dict[str, Any] = {}
            if partial_visible.startswith("{") and partial_visible.endswith("}"):
                try:
                    candidate = json.loads(partial_visible)
                    if isinstance(candidate, dict):
                        parsed_payload = candidate
                except Exception:
                    parsed_payload = {}
            inferred_payload: Dict[str, Any] = {}
            if not parsed_payload:
                # 模型已给出可见回答时，工具输出中的异常字样只作诊断上下文，不得裁决整轮状态。
                inferred_payload = infer_result_from_tool_outputs(
                    getattr(self, "_recent_tool_outputs", []),
                    include_status=not bool(partial_visible),
                )
            metadata_status = str(
                (getattr(self, "_last_turn_metadata", {}) or {}).get("status") or ""
            ).strip().lower()
            has_llm_failure = isinstance(
                (getattr(self, "_last_turn_metadata", {}) or {}).get("llm_failure"),
                dict,
            ) and bool((getattr(self, "_last_turn_metadata", {}) or {}).get("llm_failure"))
            status = "completed"
            if has_llm_failure or metadata_status in {"failed", "error", "timeout"}:
                status = "failed"
            elif self._last_turn_failed:
                # Misclassification guard: a bare ``_last_turn_failed`` without
                # any structured failure evidence (no llm_failure, metadata not
                # failed/error/timeout) must not downgrade a turn that already
                # produced a visible final answer with no pending tool calls
                # into a runtime failure.
                has_unfinished_tool_calls = (
                    int(getattr(self, "_last_response_tool_calls", 0) or 0) > 0
                )
                if partial_visible and not has_unfinished_tool_calls:
                    status = "stopped"
                else:
                    status = "failed"
            elif metadata_status == "stopped" or not ok:
                status = "stopped"
            if status == "failed" and not has_llm_failure:
                self._record_turn_failure_diagnostic(
                    category=str(getattr(self, "_last_llm_error_category", "") or "runtime_error"),
                    reason_code="agent_turn_failed_without_diagnostics",
                    reason_summary="当前轮执行失败",
                    reason_detail="Agent 未返回结构化失败诊断，请按 Trace 检查运行场景。",
                    chain_stage="agent_turn_finalize",
                    event_code="agent.turn.failed_without_diagnostics",
                    retryable=bool(getattr(self, "_last_llm_error_retryable", False)),
                    recovery_action=str(
                        getattr(self, "_last_llm_recovery_action", "") or "inspect_runtime_scene"
                    ),
                    message=error_message,
                )
                error_message = str(getattr(self, "_last_llm_error_message", "") or "").strip()
                has_llm_failure = True
            # Failed turns must not present intermediate stream fragments as a successful final answer.
            summary = partial_visible
            if status == "failed":
                summary = (
                    error_message
                    or "当前轮执行失败，请检查 LLM 配置、工具超时或运行日志后重试。"
                )
            elif not summary:
                if status == "stopped":
                    summary = "当前轮已停止，未产生可见回复。"
            tool_trace = list(getattr(self, "_recent_tool_records", []) or [])
            result = {
                "status": status,
                "summary": summary,
                "findings": [],
                "evidence": [],
                "recommended_next_action": (
                    latest_delegation.get("recommended_next_action", "")
                    if isinstance(latest_delegation, dict)
                    else ""
                ),
                "confidence": "medium" if summary else "low",
                "raw_output": summary,
                "tool_call_count": max(self._last_response_tool_calls, len(tool_trace)),
                "tool_trace": tool_trace,
            }
            if status == "failed" and partial_visible and partial_visible != summary:
                # Keep the interrupted fragment only as non-final thought context.
                result["thought"] = partial_visible
            if error_message:
                result["error"] = error_message
            llm_failure = getattr(self, "_last_turn_metadata", {}).get("llm_failure")
            if isinstance(llm_failure, dict) and llm_failure:
                result["llm_failure"] = dict(llm_failure)
            if parsed_payload and status != "failed":
                result.update(parsed_payload)
                result.setdefault("raw_output", summary)
                result["status"] = result.get("status") or status
            elif inferred_payload and status != "failed":
                result.update(inferred_payload)
                result.setdefault("raw_output", summary)
                result["status"] = result.get("status") or status
            if self._last_turn_metadata:
                result.update(self._last_turn_metadata)
                # Metadata may carry llm_usage/context; never allow it to downgrade a hard failure.
                if status == "failed":
                    result["status"] = "failed"
                    result["outcome"] = "failed"
                    result["summary"] = summary
                    result["raw_output"] = summary
                    if error_message:
                        result["error"] = error_message
                else:
                    result["status"] = result.get("status") or status
            if turn_runtime_metadata:
                result["turn_runtime"] = turn_runtime_metadata
            if policy.mode == AgentMode.CHAT:
                explicit_outcome = str(result.get("outcome") or result.get("task_outcome") or "").strip().lower()
                result.update(build_chat_coding_result_contract(result))
                metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
                metadata["chat_contract_outcome_source"] = "explicit" if explicit_outcome else "inferred"
                if explicit_outcome:
                    metadata["chat_contract_explicit_outcome"] = explicit_outcome
                result["metadata"] = metadata
            return result
        finally:
            self._single_turn_mode_active = False
            self._force_disable_tools_for_turn = previous_force_disable_tools
            self._turn_allowed_tool_names = previous_turn_allowed_tool_names
            self._pending_supervised_case_id = None
            self._turn_interrupt_checker = None
            set_cancel_checker = getattr(getattr(self, "tool_executor", None), "set_cancel_checker", None)
            if callable(set_cancel_checker):
                set_cancel_checker(None, owner=self)
            _debug_logger.info("单轮运行结束", tag=self.name)
            _debug_logger.end_session()
            logger.end_session({
                "mode": "single_turn",
                "agent_mode": policy.mode.value,
                "total_turns": logger._turn_count,
                "tool_calls": self._last_response_tool_calls,
                "ok": ok,
            })


def main(initial_prompt: str = None, args=None):
    """Agent 主入口函数。"""
    return run_agent_main(
        initial_prompt=initial_prompt,
        args=args,
        parse_args_fn=parse_args,
        agent_cls=SelfEvolvingAgent,
        workbench_cls=AgentWorkbenchShell,
        get_ui_fn=get_ui,
        ui_error_fn=ui_error,
        setup_logging_fn=setup_logging,
        create_config_fn=create_config_from_args,
        set_ui_test_mode_fn=set_ui_test_mode,
        run_preflight_doctor_fn=run_preflight_doctor,
        should_launch_workbench_fn=should_launch_workbench,
        initialize_ui_for_run_fn=initialize_ui_for_run,
        extract_subagent_primary_goal_fn=extract_subagent_primary_goal,
        evolution_test_prompt=EVOLUTION_TEST_PROMPT,
        subagent_result_marker=SUBAGENT_RESULT_MARKER,
    )


if __name__ == "__main__":
    configure_console_encoding()
    _print_evolution_time_core()
    cli_args = parse_args()
    main(initial_prompt=getattr(cli_args, "prompt", None), args=cli_args)
