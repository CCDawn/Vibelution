"""Web service facade for Research theme discovery."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.research.agent_templates import (
    RESEARCH_AGENT_TEMPLATES,
    RESEARCH_PROMPT_FILES,
    ensure_research_prompt_defaults,
    normalize_research_agent_key,
    normalize_research_prompt_filename,
    research_prompt_filename_for_key,
    research_default_prompt,
    normalize_research_agent_config,
)
from core.research import ResearchThemeDiscoveryService
from core.infrastructure.workspace_manager import get_workspace
from config.public_config import build_effective_config, load_public_config
from . import agent_directory_service, session_service
from .config_service import _profile_label
from .runtime_scene_service import record_research_scene_event


_SERVICE = ResearchThemeDiscoveryService()

_FLOW_CANVAS_STATUSES = {
    "idle",
    "ready",
    "running",
    "done",
    "failed",
    "stale",
    "needs_review",
    "needs_input",
    "needs_evidence",
    "blocked",
    "skipped",
}

_FLOW_CANVAS_NODE_TYPES = {"agent", "decision", "artifact", "human", "tool", "evaluation"}
_FLOW_CANVAS_EDGE_TYPES = {
    "success",
    "evidence_loop",
    "approval_gate",
    "human_handoff",
    "selection",
    "failure",
    "blocked",
}
_FLOW_CANVAS_EDGE_CONDITIONS = {
    "completed",
    "needs_evidence",
    "approved",
    "selected",
    "failed",
    "blocked",
}
_FLOW_CANVAS_CONDITION_EDGE_TYPES = {
    "completed": {"success", "human_handoff"},
    "needs_evidence": {"evidence_loop"},
    "approved": {"approval_gate"},
    "selected": {"selection"},
    "failed": {"failure"},
    "blocked": {"blocked"},
}
_MOJIBAKE_MARKER_RE = re.compile(r"(?:[ÃÂåæçèäéïã][\u0080-\u00bf]|�|\?{3,})")
_FLOW_CANVAS_TEXT_FIELDS = ("label", "description", "routeCondition")
_FLOW_CANVAS_EDGE_TEXT_FIELDS = ("label", "condition")
_FLOW_NODE_ACTION_ALIASES = {
    "broad_search": "broad",
    "deep_search": "deep",
    "evidence_review": "review",
    "theme_generation": "themes",
    "theme_card": "card",
    "human_choice": "human_choice",
    "knowledge_store": "knowledge_store",
    "knowledge_lookup": "knowledge_lookup",
    "literature_project_parse": "literature_project_parse",
    "semantic_cluster": "semantic_cluster",
    "novelty_reverse_check": "novelty_reverse_check",
}
_RESEARCH_FLOW_MODULE_CONTRACTS: dict[str, dict[str, Any]] = {
    "broad": {
        "label": "广撒网探索",
        "inputs": [],
        "outputs": {
            "completed": {"sources", "research_leads", "knowledge_candidates"},
            "needs_evidence": {"sources", "evidence_requests"},
        },
        "terminal": False,
    },
    "knowledge_store": {
        "label": "科研知识入库",
        "inputs": [{"sources"}, {"knowledge_candidates"}],
        "outputs": {"completed": {"knowledge_entries", "knowledge_context"}},
        "terminal": False,
    },
    "knowledge_lookup": {
        "label": "知识库检索",
        "inputs": [{"knowledge_entries"}, {"sources"}, {"knowledge_context"}],
        "outputs": {"completed": {"knowledge_context", "sources"}},
        "terminal": False,
    },
    "deep": {
        "label": "定向深搜",
        "inputs": [{"knowledge_context"}, {"sources"}, {"evidence_requests"}, {"research_leads"}],
        "outputs": {"completed": {"sources", "evidence_context", "research_leads"}},
        "terminal": False,
    },
    "literature_project_parse": {
        "label": "文献/项目解析",
        "inputs": [{"sources"}],
        "outputs": {"completed": {"parsed_records", "source_signals"}},
        "terminal": False,
    },
    "semantic_cluster": {
        "label": "语义去重与聚类",
        "inputs": [{"parsed_records"}],
        "outputs": {"completed": {"clusters", "gaps"}},
        "terminal": False,
    },
    "novelty_reverse_check": {
        "label": "新颖性反查",
        "inputs": [{"clusters"}, {"gaps"}],
        "outputs": {"completed": {"novelty_evidence", "evidence_context"}},
        "terminal": False,
    },
    "review": {
        "label": "证据审查",
        "inputs": [{"novelty_evidence"}, {"evidence_context"}, {"sources"}, {"parsed_records"}],
        "outputs": {
            "approved": {"approved_evidence"},
            "needs_evidence": {"evidence_requests"},
            "completed": {"approved_evidence"},
        },
        "terminal": False,
        "expectedOutcomes": {"approved", "needs_evidence"},
    },
    "themes": {
        "label": "主题生成",
        "inputs": [{"approved_evidence"}],
        "outputs": {"completed": {"candidate_themes"}},
        "terminal": False,
    },
    "human_choice": {
        "label": "人工选题确认",
        "inputs": [{"candidate_themes"}],
        "outputs": {"selected": {"selected_theme"}},
        "terminal": False,
    },
    "card": {
        "label": "正式主题卡",
        "inputs": [{"selected_theme"}],
        "outputs": {"completed": {"theme_card"}},
        "terminal": True,
    },
}
_RESEARCH_CAPABILITY_ACTIONS = {
    "knowledge_lookup",
    "literature_project_parse",
    "semantic_cluster",
    "novelty_reverse_check",
}
_RESEARCH_CAPABILITY_NODE_IDS = [
    "knowledge_lookup",
    "literature_project_parse",
    "semantic_cluster",
    "novelty_reverse_check",
]
_PARSE_SIGNAL_KEYWORDS = {
    "method": ["method", "methods", "model", "algorithm", "framework", "architecture", "agent", "rag", "reasoning", "optimization"],
    "dataset": ["dataset", "benchmark", "corpus", "data", "evaluation set", "leaderboard"],
    "implementation": ["github", "repository", "code", "implementation", "package", "library", "api"],
    "metric": ["metric", "accuracy", "score", "f1", "latency", "throughput", "ablation", "result"],
    "gap": ["gap", "limitation", "challenge", "future work", "open problem", "unexplored", "bottleneck"],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_research_flow_canvas() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "updatedAt": _utc_now(),
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": [
            {
                "id": "broad_search",
                "label": "广撒网探索",
                "type": "agent",
                "status": "ready",
                "x": 80,
                "y": 120,
                "agentKey": "broad",
                "promptKey": "broad",
                "llmConfigId": "research_broad",
                "description": "从开放目标出发，让 agent 使用真实网络和工具发现跨学科候选方向。",
                "routeCondition": "输入开放目标、约束和偏好后启动",
            },
            {
                "id": "knowledge_store",
                "label": "科研知识入库",
                "type": "tool",
                "status": "idle",
                "x": 380,
                "y": 120,
                "agentKey": "knowledge_store",
                "promptKey": "",
                "llmConfigId": "",
                "description": "把广搜/深搜得到的来源、论断、证据和缺口写入 ResearchKnowledgeBase，供后续调研、自进化记忆和避免重复搜索复用。",
                "routeCondition": "搜索完成后自动写入知识库",
            },
            {
                "id": "knowledge_lookup",
                "label": "知识库检索",
                "type": "tool",
                "status": "idle",
                "x": 680,
                "y": 120,
                "agentKey": "knowledge_lookup",
                "promptKey": "",
                "llmConfigId": "",
                "description": "从本地科研知识库检索已有来源、论断、证据和缺口，给后续搜索提供上下文并减少重复搜索。",
                "routeCondition": "知识入库完成后先查本地知识库",
            },
            {
                "id": "deep_search",
                "label": "定向深搜",
                "type": "agent",
                "status": "idle",
                "x": 980,
                "y": 120,
                "agentKey": "deep",
                "promptKey": "deep",
                "llmConfigId": "research_deep",
                "description": "围绕上一阶段发现的关键缺口、论文、GitHub 项目和数据集补充证据。",
                "routeCondition": "知识库检索完成并提供已知证据上下文后继续",
            },
            {
                "id": "literature_project_parse",
                "label": "文献/项目解析",
                "type": "tool",
                "status": "idle",
                "x": 1280,
                "y": 120,
                "agentKey": "literature_project_parse",
                "promptKey": "",
                "llmConfigId": "",
                "description": "对论文、PDF、GitHub README 和项目结构做结构化解析，提取方法、数据集、指标、限制和可复用组件。",
                "routeCondition": "深搜拿到文献、项目或数据集来源后解析",
            },
            {
                "id": "semantic_cluster",
                "label": "语义去重与聚类",
                "type": "tool",
                "status": "idle",
                "x": 1580,
                "y": 120,
                "agentKey": "semantic_cluster",
                "promptKey": "",
                "llmConfigId": "",
                "description": "对来源、论断和候选问题做去重、聚类和低密度空白识别，减少重复证据并暴露交叉创新点。",
                "routeCondition": "解析完成后进行语义去重和簇级空白发现",
            },
            {
                "id": "novelty_reverse_check",
                "label": "新颖性反查",
                "type": "tool",
                "status": "idle",
                "x": 1880,
                "y": 120,
                "agentKey": "novelty_reverse_check",
                "promptKey": "",
                "llmConfigId": "",
                "description": "围绕候选问题、关键词和机制组合反向检索论文、网页和 GitHub，标记已有相似工作与仍未覆盖的缺口。",
                "routeCondition": "聚类后对高潜力空白做反向查重",
            },
            {
                "id": "evidence_review",
                "label": "证据审查",
                "type": "agent",
                "status": "needs_review",
                "x": 2180,
                "y": 120,
                "agentKey": "review",
                "promptKey": "review",
                "llmConfigId": "research_review",
                "description": "审查来源可靠性、论断可追溯性和缺失证据，决定是否回到补搜。",
                "routeCondition": "深搜完成后进入；若证据不足则回到定向深搜",
            },
            {
                "id": "theme_generation",
                "label": "主题生成",
                "type": "agent",
                "status": "idle",
                "x": 2480,
                "y": 120,
                "agentKey": "themes",
                "promptKey": "themes",
                "llmConfigId": "research_themes",
                "description": "基于证据链生成可证伪、新颖且扣题的科研主题候选。",
                "routeCondition": "证据审查通过或用户手动确认继续",
            },
            {
                "id": "human_choice",
                "label": "人工选题确认",
                "type": "human",
                "status": "needs_input",
                "x": 2480,
                "y": 340,
                "agentKey": "",
                "promptKey": "",
                "llmConfigId": "",
                "description": "用户比较候选主题卡，选择最值得推进的方向。",
                "routeCondition": "主题候选生成后等待确认",
            },
            {
                "id": "theme_card",
                "label": "正式主题卡",
                "type": "artifact",
                "status": "idle",
                "x": 2780,
                "y": 220,
                "agentKey": "card",
                "promptKey": "card",
                "llmConfigId": "research_card",
                "description": "产出赛题要求的科学假设与研究计划结构，包括数据集、方法、实验、指标和参考文献。",
                "routeCondition": "用户确认主题后生成",
            },
        ],
        "edges": [
            {"id": "edge_broad_store", "source": "broad_search", "target": "knowledge_store", "label": "搜索结果", "condition": "completed", "type": "success"},
            {"id": "edge_store_lookup", "source": "knowledge_store", "target": "knowledge_lookup", "label": "入库索引", "condition": "completed", "type": "success"},
            {"id": "edge_lookup_deep", "source": "knowledge_lookup", "target": "deep_search", "label": "检索上下文", "condition": "completed", "type": "success"},
            {"id": "edge_deep_parse", "source": "deep_search", "target": "literature_project_parse", "label": "来源集合", "condition": "completed", "type": "success"},
            {"id": "edge_parse_cluster", "source": "literature_project_parse", "target": "semantic_cluster", "label": "结构化条目", "condition": "completed", "type": "success"},
            {"id": "edge_cluster_novelty", "source": "semantic_cluster", "target": "novelty_reverse_check", "label": "候选空白", "condition": "completed", "type": "success"},
            {"id": "edge_novelty_review", "source": "novelty_reverse_check", "target": "evidence_review", "label": "新颖性证据", "condition": "completed", "type": "success"},
            {"id": "edge_review_deep", "source": "evidence_review", "target": "deep_search", "label": "缺证据补搜", "condition": "needs_evidence", "type": "evidence_loop"},
            {"id": "edge_review_themes", "source": "evidence_review", "target": "theme_generation", "label": "证据通过", "condition": "approved", "type": "approval_gate"},
            {"id": "edge_themes_choice", "source": "theme_generation", "target": "human_choice", "label": "候选主题", "condition": "completed", "type": "human_handoff"},
            {"id": "edge_choice_card", "source": "human_choice", "target": "theme_card", "label": "选定主题", "condition": "selected", "type": "selection"},
        ],
    }


def list_theme_discovery_sessions() -> dict[str, Any]:
    return _SERVICE.list_sessions()


def get_research_knowledge_base(
    *,
    query: str = "",
    kind: str = "",
    category: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    return _SERVICE.get_knowledge_base(query=query, kind=kind, category=category, limit=limit)


def create_theme_discovery_session(payload: dict[str, Any]) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.create_session(payload))


def get_theme_discovery_session(session_id: str) -> dict[str, Any]:
    return _SERVICE.get_session(session_id)


def delete_theme_discovery_session(session_id: str) -> dict[str, Any]:
    result = _SERVICE.delete_session(session_id)
    _record_research_config_event(
        "research.session.deleted",
        phase="session",
        message="Research discovery session deleted",
        fields={"sessionId": session_id},
    )
    return result


def run_broad_theme_search(session_id: str) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.run_broad_search(session_id))


def run_deep_theme_search(session_id: str, evidence_requests: list[str] | None = None) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.run_deep_search(session_id, evidence_requests=evidence_requests))


def extract_theme_discovery_evidence(session_id: str) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.extract_evidence(session_id))


def generate_candidate_themes(session_id: str) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.generate_themes(session_id))


def run_theme_discovery_draft(session_id: str) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.run_draft(session_id))


def select_candidate_theme(session_id: str, theme_id: str) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.select_theme(session_id, theme_id))


def generate_theme_card(session_id: str, theme_id: str) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.generate_theme_card(session_id, theme_id))


def approve_theme_card(session_id: str, card_id: str) -> dict[str, Any]:
    return _sync_research_flow_canvas_with_session_payload(_SERVICE.approve_theme_card(session_id, card_id))


def list_research_prompts() -> dict[str, Any]:
    workspace = get_workspace()
    ensure_research_prompt_defaults(workspace)
    agent_config = _load_research_agent_config()
    agent_config = _ensure_research_agent_instances(agent_config)
    llm_configs = _list_llm_config_options()
    prompts: list[dict[str, Any]] = []
    deleted_default_agents = set(agent_config.get("deletedDefaultAgents") or [])
    prompt_files: dict[str, str] = {
        key: filename for key, filename in RESEARCH_PROMPT_FILES.items() if key not in deleted_default_agents
    }
    for agent in agent_config["agents"]:
        key = str(agent.get("key") or "").strip()
        filename = str(agent.get("promptFilename") or "").strip()
        if key and filename:
            prompt_files[key] = filename
    for key, filename in prompt_files.items():
        prompts.append(
            {
                "key": key,
                "filename": filename,
                "path": str(workspace.get_research_prompt_path(filename)),
                "content": workspace.read_research_prompt(filename),
                "defaultContent": research_default_prompt(key),
            }
        )
    return {
        "root": str(workspace.research_prompts_dir()),
        "agentConfigPath": str(workspace.get_research_agent_config_path()),
        "prompts": prompts,
        "agentTemplates": RESEARCH_AGENT_TEMPLATES,
        "llmConfigs": llm_configs,
        "agents": agent_config["agents"],
    }


def _ensure_research_agent_instances(agent_config: dict[str, Any]) -> dict[str, Any]:
    """Ensure enabled research agents have persistent AgentInstances and direct sessions."""

    workspace = get_workspace()
    project_root = Path(getattr(workspace, "root", session_service.PROJECT_ROOT)).resolve()
    previous_session_root = session_service.PROJECT_ROOT
    previous_agent_root = agent_directory_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = project_root
    agent_directory_service.PROJECT_ROOT = project_root
    agents = [dict(item) for item in list(agent_config.get("agents") or []) if isinstance(item, dict)]
    changed = False
    try:
        for agent in agents:
            if agent.get("enabled") is False:
                continue
            key = str(agent.get("key") or "").strip()
            if not key:
                continue
            label = str(agent.get("label") or key).strip() or key
            llm_config_id = str(agent.get("llmConfigId") or "").strip() or "primary"
            agent_instance_id = str(agent.get("agentInstanceId") or agent.get("agentId") or "").strip()
            instance = agent_directory_service.get_agent(agent_instance_id) if agent_instance_id else None
            if not instance:
                try:
                    session_detail = session_service.create_chat_session(
                        title=label,
                        agent_profile_id=llm_config_id,
                        created_by="research_agent_pool",
                    )
                except Exception as exc:
                    _record_research_config_event(
                        "research.agent_instance.sync_failed",
                        phase="agent_template_config",
                        message="Research agent instance sync failed",
                        outcome="failed",
                        level="warning",
                        fields={
                            "agentKey": key,
                            "llmConfigId": llm_config_id,
                            "errorType": type(exc).__name__,
                            "message": str(exc),
                        },
                        agent_key=key,
                    )
                    continue
                agent_instance_id = str(session_detail.get("agentId") or "").strip()
                agent["agentInstanceId"] = agent_instance_id
                agent["agentId"] = agent_instance_id
                agent["directSessionId"] = str(session_detail.get("id") or "").strip()
                changed = True
            if agent_instance_id:
                try:
                    updated_instance = agent_directory_service.update_agent_instance(
                        agent_instance_id,
                        display_name=label,
                        profile_id=llm_config_id,
                        metadata={
                            "researchAgentKey": key,
                            "researchTemplateId": str(agent.get("templateId") or "").strip(),
                            "researchPromptFilename": str(agent.get("promptFilename") or "").strip(),
                        },
                    )
                    direct_session_id = str(updated_instance.get("directSessionId") or agent.get("directSessionId") or "").strip()
                    if direct_session_id:
                        try:
                            session_service.update_chat_session(
                                direct_session_id,
                                title=label,
                                agent_profile_id=llm_config_id,
                            )
                        except Exception:
                            pass
                        if agent.get("directSessionId") != direct_session_id:
                            agent["directSessionId"] = direct_session_id
                            changed = True
                except Exception:
                    pass
        if changed:
            next_config = {
                "schemaVersion": 1,
                "deletedDefaultAgents": list(agent_config.get("deletedDefaultAgents") or []),
                "agents": agents,
            }
            workspace.write_research_agent_config(next_config)
            _record_research_config_event(
                "research.agent_instance.synced",
                phase="agent_template_config",
                message="Research agent instances synced to conversation registry",
                fields={"agentCount": len(agents)},
            )
            return normalize_research_agent_config(next_config)
        return {**agent_config, "agents": agents}
    finally:
        session_service.PROJECT_ROOT = previous_session_root
        agent_directory_service.PROJECT_ROOT = previous_agent_root


def save_research_prompt(key: str, content: str) -> dict[str, Any]:
    normalized = str(key or "").strip().lower()
    agent_config = _load_research_agent_config()
    agent_by_key = {str(agent.get("key") or ""): agent for agent in agent_config["agents"]}
    if normalized not in RESEARCH_PROMPT_FILES and normalized not in agent_by_key:
        _record_research_config_event(
            "research.prompt.update_failed",
            phase="prompt_config",
            message="Research prompt update failed",
            outcome="failed",
            level="error",
            fields={
                "agentKey": normalized,
                "reason": "unknown_prompt_key",
                "errorType": "ValueError",
                "message": f"Unknown research prompt key: {key}",
            },
            agent_key=normalized,
        )
        raise ValueError(f"Unknown research prompt key: {key}")
    workspace = get_workspace()
    filename = str(agent_by_key.get(normalized, {}).get("promptFilename") or RESEARCH_PROMPT_FILES.get(normalized) or "").strip()
    if not workspace.write_research_prompt(filename, str(content or "")):
        _record_research_config_event(
            "research.prompt.update_failed",
            phase="prompt_config",
            message="Research prompt update failed",
            outcome="failed",
            level="error",
            fields={
                "agentKey": normalized,
                "filename": filename,
                "contentLength": len(str(content or "")),
                "errorType": "ValueError",
                "message": "Failed to write research prompt.",
            },
            agent_key=normalized,
        )
        raise ValueError("Failed to write research prompt.")
    _record_research_config_event(
        "research.prompt.updated",
        phase="prompt_config",
        message="Research prompt updated",
        fields={
            "agentKey": normalized,
            "filename": filename,
            "contentLength": len(str(content or "")),
        },
        agent_key=normalized,
    )
    return list_research_prompts()


def save_research_agent_binding(
    key: str,
    template_id: str,
    llm_config_id: str | None = None,
    *,
    label: str = "",
    prompt_filename: str = "",
    enabled: bool | None = None,
) -> dict[str, Any]:
    raw_key = str(key or "").strip().lower().replace("-", "_")
    try:
        normalized = normalize_research_agent_key(key)
    except ValueError as exc:
        _record_research_config_event(
            "research.agent_binding.update_failed",
            phase="agent_template_config",
            message="Research agent template binding update failed",
            outcome="failed",
            level="error",
            fields={
                "agentKey": raw_key,
                "reason": "unknown_agent_key",
                "errorType": "ValueError",
                "message": str(exc),
            },
            agent_key=raw_key,
        )
        raise
    known_templates = {item["templateId"] for item in RESEARCH_AGENT_TEMPLATES}
    selected_template = str(template_id or "").strip()
    if selected_template not in known_templates:
        _record_research_config_event(
            "research.agent_binding.update_failed",
            phase="agent_template_config",
            message="Research agent template binding update failed",
            outcome="failed",
            level="error",
            fields={
                "agentKey": normalized,
                "templateId": selected_template,
                "reason": "unknown_template",
                "errorType": "ValueError",
                "message": f"Unknown research agent template: {template_id}",
            },
            agent_key=normalized,
        )
        raise ValueError(f"Unknown research agent template: {template_id}")
    selected_llm_config = str(llm_config_id or "").strip()
    if selected_llm_config:
        known_llm_configs = {item["configId"] for item in _list_llm_config_options()}
        if selected_llm_config not in known_llm_configs:
            _record_research_config_event(
                "research.agent_binding.update_failed",
                phase="agent_template_config",
                message="Research agent template binding update failed",
                outcome="failed",
                level="error",
                fields={
                    "agentKey": normalized,
                    "templateId": selected_template,
                    "llmConfigId": selected_llm_config,
                    "reason": "unknown_llm_config",
                    "errorType": "ValueError",
                    "message": f"Unknown research LLM config: {llm_config_id}",
                },
                agent_key=normalized,
            )
            raise ValueError(f"Unknown research LLM config: {llm_config_id}")
    config = _load_research_agent_config()
    agents = config["agents"]
    deleted_default_agents = set(config.get("deletedDefaultAgents") or [])
    deleted_default_agents.discard(normalized)
    existing_agent = next((agent for agent in agents if agent["key"] == normalized), None)
    if not selected_llm_config:
        selected_llm_config = str((existing_agent or {}).get("llmConfigId") or "").strip()
    if not selected_llm_config:
        raise ValueError("Research agent requires an LLM config.")
    prompt_file = normalize_research_prompt_filename(
        prompt_filename or str((existing_agent or {}).get("promptFilename") or "") or research_prompt_filename_for_key(normalized),
        normalized,
    )
    next_label = str(label or (existing_agent or {}).get("label") or normalized.replace("_", " ").title()).strip()
    if not next_label:
        next_label = normalized
    updated = False
    for agent in agents:
        if agent["key"] == normalized:
            agent["label"] = next_label
            agent["promptFilename"] = prompt_file
            agent["templateId"] = selected_template
            agent["llmConfigId"] = selected_llm_config
            if enabled is not None:
                agent["enabled"] = bool(enabled)
            updated = True
            break
    if not updated:
        agents.append(
            {
                "key": normalized,
                "label": next_label,
                "promptFilename": prompt_file,
                "templateId": selected_template,
                "llmConfigId": selected_llm_config,
                "enabled": True if enabled is None else bool(enabled),
            }
        )
    workspace = get_workspace()
    prompt_path = workspace.get_research_prompt_path(prompt_file)
    if not prompt_path.exists():
        workspace.write_research_prompt(prompt_file, research_default_prompt(normalized))
    if not workspace.write_research_agent_config({"schemaVersion": 1, "deletedDefaultAgents": sorted(deleted_default_agents), "agents": agents}):
        _record_research_config_event(
            "research.agent_binding.update_failed",
            phase="agent_template_config",
            message="Research agent template binding update failed",
            outcome="failed",
            level="error",
            fields={
                "agentKey": normalized,
                "templateId": selected_template,
                "llmConfigId": selected_llm_config,
                "errorType": "ValueError",
                "message": "Failed to write research agent template config.",
            },
            agent_key=normalized,
        )
        raise ValueError("Failed to write research agent template config.")
    _record_research_config_event(
            "research.agent_binding.updated",
            phase="agent_template_config",
            message="Research agent template binding updated",
            fields={
                "agentKey": normalized,
                "label": next_label,
                "promptFilename": prompt_file,
                "templateId": selected_template,
                "llmConfigId": selected_llm_config,
                "created": not updated,
            },
            agent_key=normalized,
        )
    return list_research_prompts()


def delete_research_agent_binding(key: str) -> dict[str, Any]:
    normalized = normalize_research_agent_key(key)
    canvas = get_research_flow_canvas()
    referencing_nodes = [
        str(node.get("id") or "")
        for node in canvas.get("nodes", [])
        if isinstance(node, dict) and str(node.get("agentKey") or "").strip() == normalized
    ]
    if referencing_nodes:
        raise ValueError(f"Research agent {normalized} is still used by flow nodes: {', '.join(referencing_nodes[:5])}")
    config = _load_research_agent_config()
    agents = config["agents"]
    removed_agent = next((agent for agent in agents if agent["key"] == normalized), None)
    remaining = [agent for agent in agents if agent["key"] != normalized]
    if len(remaining) == len(agents):
        raise ValueError(f"Unknown research agent key: {key}")
    deleted_default_agents = set(config.get("deletedDefaultAgents") or [])
    if normalized in RESEARCH_PROMPT_FILES:
        deleted_default_agents.add(normalized)
    workspace = get_workspace()
    if not workspace.write_research_agent_config({"schemaVersion": 1, "deletedDefaultAgents": sorted(deleted_default_agents), "agents": remaining}):
        raise ValueError("Failed to delete research agent config.")
    agent_instance_id = str((removed_agent or {}).get("agentInstanceId") or (removed_agent or {}).get("agentId") or "").strip()
    if agent_instance_id:
        try:
            agent_directory_service.archive_agent_instance(agent_instance_id)
        except Exception:
            pass
    _record_research_config_event(
        "research.agent_binding.deleted",
        phase="agent_template_config",
        message="Research agent template binding deleted",
        fields={"agentKey": normalized},
        agent_key=normalized,
    )
    return list_research_prompts()


def get_research_flow_canvas() -> dict[str, Any]:
    workspace = get_workspace()
    raw = workspace.read_research_flow_canvas()
    canvas = _normalize_research_flow_canvas(_with_default_research_flow_canvas_migrations(raw or _default_research_flow_canvas()))
    return _with_flow_canvas_validation({
        **canvas,
        "path": str(workspace.get_research_flow_canvas_path()),
    })


def save_research_flow_canvas(payload: dict[str, Any], *, record_event: bool = True) -> dict[str, Any]:
    workspace = get_workspace()
    try:
        canvas = _normalize_research_flow_canvas(payload)
        mojibake_report = _detect_flow_canvas_mojibake(canvas)
        if mojibake_report["markerCount"] > 0:
            raise ValueError(_format_flow_canvas_mojibake_error(mojibake_report))
        validation = _validate_research_flow_canvas(canvas)
        if not validation["valid"]:
            raise ValueError(_format_flow_canvas_validation_error(validation))
    except ValueError as exc:
        if record_event:
            validation_fields = locals().get("validation")
            mojibake_fields = locals().get("mojibake_report")
            _record_research_config_event(
                "research.flow_canvas.update_failed",
                phase="flow_canvas",
                message="Research flow canvas update failed",
                outcome="failed",
                level="error",
                fields={
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                    **_flow_canvas_validation_log_fields(validation_fields if isinstance(validation_fields, dict) else None),
                    **_flow_canvas_mojibake_log_fields(
                        mojibake_fields if isinstance(mojibake_fields, dict) else None
                    ),
                },
            )
        raise
    canvas["updatedAt"] = _utc_now()
    if not workspace.write_research_flow_canvas(canvas):
        if record_event:
            _record_research_config_event(
                "research.flow_canvas.update_failed",
                phase="flow_canvas",
                message="Research flow canvas update failed",
                outcome="failed",
                level="error",
                fields={
                    "path": str(workspace.get_research_flow_canvas_path()),
                    "nodeCount": len(canvas["nodes"]),
                    "edgeCount": len(canvas["edges"]),
                    "errorType": "ValueError",
                    "message": "Failed to write research flow canvas.",
                },
            )
        raise ValueError("Failed to write research flow canvas.")
    if record_event:
        _record_research_config_event(
            "research.flow_canvas.updated",
            phase="flow_canvas",
            message="Research flow canvas updated",
            fields={
                "path": str(workspace.get_research_flow_canvas_path()),
                "nodeCount": len(canvas["nodes"]),
                "edgeCount": len(canvas["edges"]),
                **_flow_canvas_mojibake_log_fields(mojibake_report),
            },
        )
    return _with_flow_canvas_validation({
        **canvas,
        "path": str(workspace.get_research_flow_canvas_path()),
    })


def execute_research_flow_canvas_node(session_id: str, node_id: str | None = None) -> dict[str, Any]:
    normalized_session_id = _safe_text(session_id, max_length=128)
    if not normalized_session_id:
        raise ValueError("Research flow execution requires a session id.")
    canvas = get_research_flow_canvas()
    validation = canvas.get("validation") if isinstance(canvas.get("validation"), dict) else _validate_research_flow_canvas(canvas)
    if not validation.get("valid", False):
        _record_research_config_event(
            "research.flow_canvas.execution_blocked",
            phase="flow_canvas_execution",
            message="Research flow canvas execution blocked by contract validation",
            outcome="blocked",
            level="warning",
            fields={
                "sessionId": normalized_session_id,
                **_flow_canvas_validation_log_fields(validation),
            },
        )
        raise ValueError(_format_flow_canvas_validation_error(validation))
    nodes = [dict(node) for node in canvas["nodes"]]
    edges = [dict(edge) for edge in canvas["edges"]]
    try:
        selected = _select_flow_execution_node(nodes, node_id)
    except ValueError as exc:
        _record_research_config_event(
            "research.flow_canvas.execution_blocked",
            phase="flow_canvas_execution",
            message="Research flow canvas execution blocked by node state",
            outcome="blocked",
            level="warning",
            fields={
                "sessionId": normalized_session_id,
                "nodeId": _safe_token(node_id, default="") if node_id else "",
                "reason": str(exc)[:500],
            },
        )
        raise
    if not selected:
        raise ValueError("No executable research flow node is ready.")

    node_index = next(index for index, node in enumerate(nodes) if node["id"] == selected["id"])
    rerun = str(selected.get("status") or "") in {"done", "failed", "stale"}
    stale_downstream: list[dict[str, Any]] = []
    if rerun:
        stale_downstream = _mark_flow_downstream_stale(nodes, edges, selected["id"])
    nodes[node_index] = {**selected, "status": "running"}
    _persist_research_flow_canvas_state(canvas, nodes, edges)

    action_key = _flow_node_action_key(selected)
    _record_research_flow_execution_event(
        "research.flow_canvas.node_started",
        outcome="started",
        session_id=normalized_session_id,
        node=selected,
        action_key=action_key,
        fields={
            "rerun": rerun,
            "staleDownstreamNodeIds": [node["id"] for node in stale_downstream],
        },
    )
    result: dict[str, Any] | None = None
    route_outcome = "completed"
    try:
        result, route_outcome = _execute_research_flow_action(action_key, normalized_session_id)
    except Exception as exc:
        nodes[node_index] = {**nodes[node_index], "status": "failed"}
        _persist_research_flow_canvas_state(canvas, nodes, edges)
        _record_research_flow_execution_event(
            "research.flow_canvas.node_failed",
            outcome="failed",
            session_id=normalized_session_id,
            node=selected,
            action_key=action_key,
            fields={"errorType": type(exc).__name__, "error": str(exc)[:500]},
        )
        if isinstance(exc, (FileNotFoundError, ValueError)):
            raise
        raise ValueError(f"Research flow node execution failed: {type(exc).__name__}: {exc}") from exc

    latest_canvas = get_research_flow_canvas()
    nodes = [dict(node) for node in latest_canvas["nodes"]]
    edges = [dict(edge) for edge in latest_canvas["edges"]]
    node_index = next(index for index, node in enumerate(nodes) if node["id"] == selected["id"])
    if rerun:
        stale_downstream = _mark_flow_downstream_stale(nodes, edges, selected["id"])
    nodes[node_index] = {**nodes[node_index], "status": "done"}
    activated = _activate_flow_successors(nodes, edges, selected["id"], route_outcome)
    saved_canvas = _persist_research_flow_canvas_state(latest_canvas, nodes, edges)
    _record_research_flow_execution_event(
        "research.flow_canvas.node_executed",
        outcome="succeeded",
        session_id=normalized_session_id,
        node=selected,
        action_key=action_key,
        fields={
            "routeOutcome": route_outcome,
            "activatedNodeIds": [node["id"] for node in activated],
            "sourceCount": _safe_summary_count(result, "sourceCount"),
            "evidenceCount": _safe_summary_count(result, "evidenceCount"),
            "candidateThemeCount": _safe_summary_count(result, "candidateThemeCount"),
            "themeCardCount": _safe_summary_count(result, "themeCardCount"),
        },
    )
    return {
        "canvas": saved_canvas,
        "session": result,
        "execution": {
            "sessionId": normalized_session_id,
            "nodeId": selected["id"],
            "nodeLabel": selected["label"],
            "actionKey": action_key,
            "status": "done",
            "routeOutcome": route_outcome,
            "activatedNodeIds": [node["id"] for node in activated],
            "message": _flow_execution_message(selected, action_key, route_outcome, activated),
        },
    }


def get_research_agent_bindings() -> dict[str, Any]:
    return _load_research_agent_config()


def _sync_research_flow_canvas_with_session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    try:
        canvas = get_research_flow_canvas()
        nodes = [dict(node) for node in canvas["nodes"]]
        edges = [dict(edge) for edge in canvas["edges"]]
        changed: list[dict[str, Any]] = []
        for index, node in enumerate(nodes):
            next_status = _derive_flow_node_status_from_session(node, payload)
            if not next_status or next_status == node.get("status"):
                continue
            nodes[index] = {**node, "status": next_status}
            changed.append({"nodeId": node.get("id"), "status": next_status})
        if changed:
            _persist_research_flow_canvas_state(canvas, nodes, edges)
            _record_research_flow_sync_event(payload, changed)
    except Exception:
        pass
    return payload


def _derive_flow_node_status_from_session(node: dict[str, Any], payload: dict[str, Any]) -> str:
    action_key = _flow_node_action_key(node)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    candidate_count = _safe_int(summary.get("candidateThemeCount"))
    evidence_count = _safe_int(summary.get("evidenceCount"))
    card_count = _safe_int(summary.get("themeCardCount"))
    selected_theme_id = str(session.get("selectedThemeId") or "").strip()
    missing_requests = _latest_missing_evidence_requests(payload)

    if action_key == "broad":
        return _search_run_flow_status(payload, "broad", fallback="ready")
    if action_key == "knowledge_store":
        if _search_run_flow_status(payload, "deep", fallback="idle") == "done":
            return "done"
        if _search_run_flow_status(payload, "broad", fallback="idle") == "done":
            return "ready"
        return "idle"
    if action_key == "knowledge_lookup":
        if node.get("status") == "done":
            return "done"
        return "ready" if _search_run_flow_status(payload, "broad", fallback="idle") == "done" else "idle"
    if action_key == "deep":
        return _search_run_flow_status(payload, "deep", fallback="idle")
    if action_key == "literature_project_parse":
        if node.get("status") == "done":
            return "done"
        return "ready" if _search_run_flow_status(payload, "deep", fallback="idle") == "done" else "idle"
    if action_key == "semantic_cluster":
        if node.get("status") == "done":
            return "done"
        return "ready" if _flow_capability_event_seen(payload, "literature_project_parse") else "idle"
    if action_key == "novelty_reverse_check":
        if node.get("status") == "done":
            return "done"
        return "ready" if _flow_capability_event_seen(payload, "semantic_cluster") else "idle"
    if action_key == "review":
        if evidence_count:
            return "needs_evidence" if missing_requests else "done"
        if _search_run_flow_status(payload, "deep", fallback="idle") != "done":
            return "idle"
        return "ready" if _flow_capability_event_seen(payload, "novelty_reverse_check") else "idle"
    if action_key == "themes":
        if candidate_count:
            return "done"
        return "ready" if evidence_count and not missing_requests else "idle"
    if action_key == "human_choice":
        if selected_theme_id:
            return "done"
        return "needs_input" if candidate_count else "idle"
    if action_key == "card":
        if card_count:
            return "done"
        return "ready" if selected_theme_id else "idle"
    return str(node.get("status") or "idle")


def _search_run_flow_status(payload: dict[str, Any], phase: str, *, fallback: str) -> str:
    runs = payload.get("searchRuns") if isinstance(payload.get("searchRuns"), list) else []
    latest = next((run for run in reversed(runs) if isinstance(run, dict) and run.get("phase") == phase), None)
    if not latest:
        return fallback
    status = str(latest.get("status") or "")
    if status == "completed":
        return "done"
    if status == "running":
        return "running"
    if status == "failed":
        return "failed"
    return fallback


def _flow_capability_event_seen(payload: dict[str, Any], action_key: str) -> bool:
    expected = f"research.capability.{action_key}.completed"
    for event in payload.get("events") or []:
        if isinstance(event, dict) and str(event.get("eventCode") or "") == expected:
            return True
    return False


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _record_research_flow_sync_event(payload: dict[str, Any], changed: list[dict[str, Any]]) -> None:
    try:
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        session_id = str(session.get("sessionId") or "")
        record_research_scene_event(
            "research.flow_canvas.synced",
            phase="flow_canvas",
            message="Research flow canvas synced from discovery session state",
            outcome="succeeded",
            fields={"sessionId": session_id, "changedNodes": changed[:20], "changedNodeCount": len(changed)},
            session_id=session_id,
        )
    except Exception:
        pass


def _select_flow_execution_node(nodes: list[dict[str, Any]], node_id: str | None) -> dict[str, Any] | None:
    requested = _safe_token(node_id, default="") if node_id else ""
    runnable_statuses = {"ready", "needs_review", "needs_evidence"}
    explicit_rerun_statuses = {"done", "failed", "stale"}
    running = next((node for node in nodes if str(node.get("status") or "") == "running"), None)
    if running:
        running_id = str(running.get("id") or "")
        raise ValueError(f"Research flow node is already running: {running_id}")
    if requested:
        for node in nodes:
            if node["id"] == requested:
                if node["status"] not in runnable_statuses | explicit_rerun_statuses | {"needs_input"}:
                    raise ValueError(f"Research flow node is not ready to execute: {node_id}")
                return node
        raise ValueError(f"Unknown research flow node: {node_id}")
    for node in nodes:
        if node["status"] in runnable_statuses:
            return node
    return None


def _mark_flow_downstream_stale(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    source_node_id: str,
) -> list[dict[str, Any]]:
    node_index = {str(node.get("id") or ""): index for index, node in enumerate(nodes)}
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, []).append(target)

    changed: list[dict[str, Any]] = []
    pending = list(adjacency.get(source_node_id, []))
    visited: set[str] = {source_node_id}
    staleable_statuses = {"ready", "done", "failed", "needs_review", "needs_input", "needs_evidence", "blocked"}
    while pending:
        node_id = pending.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        index = node_index.get(node_id)
        if index is not None:
            current = nodes[index]
            if str(current.get("status") or "") in staleable_statuses:
                nodes[index] = {**current, "status": "stale"}
                changed.append(nodes[index])
        pending.extend(adjacency.get(node_id, []))
    return changed


def _flow_node_action_key(node: dict[str, Any]) -> str:
    raw = _safe_token(node.get("agentKey") or node.get("promptKey") or node.get("id"), default="")
    return _FLOW_NODE_ACTION_ALIASES.get(raw, raw)


def _execute_research_flow_action(action_key: str, session_id: str) -> tuple[dict[str, Any], str]:
    if action_key == "broad":
        return run_broad_theme_search(session_id), "completed"
    if action_key == "knowledge_store":
        return get_theme_discovery_session(session_id), "completed"
    if action_key in _RESEARCH_CAPABILITY_ACTIONS:
        return _run_research_capability_action(action_key, session_id), "completed"
    if action_key == "deep":
        return run_deep_theme_search(session_id), "completed"
    if action_key == "review":
        result = extract_theme_discovery_evidence(session_id)
        return result, "needs_evidence" if _latest_missing_evidence_requests(result) else "approved"
    if action_key == "themes":
        return generate_candidate_themes(session_id), "completed"
    if action_key == "human_choice":
        result = get_theme_discovery_session(session_id)
        if not result.get("session", {}).get("selectedThemeId"):
            raise ValueError("Select a candidate theme before advancing the human choice node.")
        return result, "selected"
    if action_key == "card":
        session = get_theme_discovery_session(session_id)
        theme_id = str(session.get("session", {}).get("selectedThemeId") or "").strip()
        if not theme_id:
            raise ValueError("Select a candidate theme before generating a theme card.")
        return generate_theme_card(session_id, theme_id), "completed"
    raise ValueError(f"Research flow node action is not executable yet: {action_key}")


def _run_research_capability_action(action_key: str, session_id: str) -> dict[str, Any]:
    payload = get_theme_discovery_session(session_id)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    agent_report = payload.get("agentReport") if isinstance(payload.get("agentReport"), dict) else {}
    knowledge_base = get_research_knowledge_base(limit=25)
    knowledge_summary = knowledge_base.get("summary") if isinstance(knowledge_base.get("summary"), dict) else {}
    fields = {
        "agentKey": action_key,
        "sourceCount": _safe_int(summary.get("sourceCount")),
        "evidenceCount": _safe_int(summary.get("evidenceCount")),
        "knowledgeEntryCount": _safe_int(knowledge_summary.get("entryCount")),
        "knowledgeClaimCount": _safe_int(knowledge_summary.get("claimCount")),
        "knowledgeGapCount": _safe_int(knowledge_summary.get("gapCount")),
        "sourceKindCounts": agent_report.get("sourceKindCounts") if isinstance(agent_report.get("sourceKindCounts"), dict) else {},
        "capabilityMode": "routing_capability",
    }
    if action_key == "knowledge_lookup":
        fields["capabilitySummary"] = "Queried the local research knowledge base before additional deep search."
    elif action_key == "literature_project_parse":
        fields.update(_parse_literature_project_sources(payload))
    elif action_key == "semantic_cluster":
        fields["capabilitySummary"] = "Prepared source and claim sets for semantic deduplication, clustering, and gap discovery."
    elif action_key == "novelty_reverse_check":
        fields["capabilitySummary"] = "Prepared candidate gaps for novelty reverse-check against papers, web pages, and GitHub repositories."
    _record_research_capability_event(session_id, f"research.capability.{action_key}.completed", fields)
    return get_theme_discovery_session(session_id)


def _parse_literature_project_sources(payload: dict[str, Any]) -> dict[str, Any]:
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    records = [_parse_literature_project_source(source) for source in sources if isinstance(source, dict)]
    parsed = [record for record in records if record]
    parse_type_counts = Counter(str(record.get("parsedType") or "unknown") for record in parsed)
    signal_counts: Counter[str] = Counter()
    for record in parsed:
        for signal in record.get("signals") or []:
            signal_counts[str(signal)] += 1
    return {
        "capabilityMode": "metadata_signal_parser",
        "capabilitySummary": (
            f"Parsed {len(parsed)} research sources into structured paper/project/dataset/web signal records."
        ),
        "parsedSourceCount": len(parsed),
        "parseTypeCounts": dict(parse_type_counts),
        "signalCounts": dict(signal_counts),
        "parsedRecords": parsed[:40],
    }


def _parse_literature_project_source(source: dict[str, Any]) -> dict[str, Any]:
    kind = str(source.get("kind") or "web").strip().lower()
    title = _safe_text(source.get("title"), max_length=240)
    url = _safe_text(source.get("url"), max_length=500)
    snippet = _safe_text(source.get("snippet"), max_length=600)
    combined = f"{title}\n{url}\n{snippet}".lower()
    parsed_type = _parsed_source_type(kind, url)
    signals = _parse_signal_hits(combined)
    record: dict[str, Any] = {
        "sourceId": _safe_text(source.get("sourceId") or source.get("source_id"), max_length=128),
        "kind": kind,
        "parsedType": parsed_type,
        "title": title,
        "url": url,
        "reliability": _safe_text(source.get("reliability"), max_length=40),
        "signals": signals,
        "extracted": {
            "methodSignals": _keyword_hits(combined, _PARSE_SIGNAL_KEYWORDS["method"]),
            "datasetSignals": _keyword_hits(combined, _PARSE_SIGNAL_KEYWORDS["dataset"]),
            "implementationSignals": _keyword_hits(combined, _PARSE_SIGNAL_KEYWORDS["implementation"]),
            "metricSignals": _keyword_hits(combined, _PARSE_SIGNAL_KEYWORDS["metric"]),
            "gapSignals": _keyword_hits(combined, _PARSE_SIGNAL_KEYWORDS["gap"]),
        },
    }
    repo = _github_repo_from_url(url)
    if repo:
        record["githubRepo"] = repo
    if snippet:
        record["summary"] = snippet[:280]
    return record


def _parsed_source_type(kind: str, url: str) -> str:
    if kind == "paper":
        return "paper_or_pdf"
    if kind == "github" or "github.com" in url.lower():
        return "github_repository"
    if kind == "dataset":
        return "dataset_or_benchmark"
    return "web_page"


def _parse_signal_hits(text: str) -> list[str]:
    signals: list[str] = []
    for signal, keywords in _PARSE_SIGNAL_KEYWORDS.items():
        if _keyword_hits(text, keywords):
            signals.append(signal)
    return signals


def _keyword_hits(text: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    for keyword in keywords:
        pattern = r"\b" + re.escape(keyword.lower()).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, text) and keyword not in hits:
            hits.append(keyword)
    return hits[:8]


def _github_repo_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return ""
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return ""
    return f"{parts[0]}/{parts[1]}"


def _latest_missing_evidence_requests(result: dict[str, Any]) -> list[str]:
    for event in reversed(result.get("events") or []):
        fields = event.get("fields") if isinstance(event, dict) else {}
        requests = fields.get("missingEvidenceRequests") if isinstance(fields, dict) else None
        if isinstance(requests, list):
            return [str(item) for item in requests if str(item).strip()]
    return []


def _activate_flow_successors(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    source_node_id: str,
    route_outcome: str,
) -> list[dict[str, Any]]:
    activated: list[dict[str, Any]] = []
    acceptable = {route_outcome}
    if route_outcome in {"completed", "approved", "selected"}:
        acceptable.update({"completed", "done", "succeeded"})
    if route_outcome == "approved":
        acceptable.add("approved")
    if route_outcome == "needs_evidence":
        acceptable.add("needs_evidence")
    if route_outcome == "selected":
        acceptable.add("selected")

    node_index = {node["id"]: index for index, node in enumerate(nodes)}
    for edge in edges:
        if edge["source"] != source_node_id:
            continue
        edge_condition = _safe_text(edge.get("condition"), default="completed", max_length=160).lower()
        if edge_condition and edge_condition not in acceptable:
            continue
        target_index = node_index.get(edge["target"])
        if target_index is None:
            continue
        target = nodes[target_index]
        target_status = target["status"]
        feedback_reroute = (
            route_outcome == "needs_evidence"
            and edge_condition == "needs_evidence"
            and target_status == "done"
        )
        if target_status == "running" or (target_status in {"done", "failed"} and not feedback_reroute):
            continue
        next_status = "needs_evidence" if route_outcome == "needs_evidence" else "ready"
        if target.get("type") == "human" and route_outcome != "selected":
            next_status = "needs_input"
        nodes[target_index] = {**target, "status": next_status}
        activated.append(nodes[target_index])
    return activated


def _persist_research_flow_canvas_state(
    base_canvas: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    return save_research_flow_canvas(
        {
            "schemaVersion": base_canvas.get("schemaVersion", 1),
            "viewport": base_canvas.get("viewport") or {},
            "nodes": nodes,
            "edges": edges,
        },
        record_event=False,
    )


def _flow_execution_message(
    node: dict[str, Any],
    action_key: str,
    route_outcome: str,
    activated: list[dict[str, Any]],
) -> str:
    next_labels = [item["label"] for item in activated]
    suffix = f"；已激活：{'、'.join(next_labels)}" if next_labels else "；暂无可自动激活的后继节点"
    return f"{node['label']} 已执行真实科研动作 {action_key}，路由结果 {route_outcome}{suffix}。"


def _safe_summary_count(result: dict[str, Any] | None, key: str) -> int:
    if not isinstance(result, dict):
        return 0
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _record_research_flow_execution_event(
    event_code: str,
    *,
    outcome: str,
    session_id: str,
    node: dict[str, Any],
    action_key: str,
    fields: dict[str, Any],
) -> None:
    try:
        record_research_scene_event(
            event_code,
            phase="flow_canvas_execution",
            message=f"Research flow canvas node {node.get('id')} execution {outcome}",
            outcome=outcome,
            fields={
                "sessionId": session_id,
                "nodeId": node.get("id"),
                "nodeLabel": node.get("label"),
                "actionKey": action_key,
                **fields,
            },
            session_id=session_id,
            agent_key=action_key,
        )
    except Exception:
        pass


def _record_research_capability_event(session_id: str, event_code: str, fields: dict[str, Any]) -> None:
    try:
        _SERVICE.repository.append_event(
            session_id,
            {
                "eventCode": event_code,
                "timestamp": _utc_now(),
                "fields": fields,
            },
        )
    except Exception:
        pass
    try:
        record_research_scene_event(
            event_code,
            phase="capability",
            message=f"Research capability {fields.get('agentKey')} completed",
            outcome="succeeded",
            fields=fields,
            session_id=session_id,
            agent_key=str(fields.get("agentKey") or ""),
        )
    except Exception:
        pass


def _with_default_research_flow_canvas_migrations(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        return _default_research_flow_canvas()
    nodes = raw.get("nodes")
    edges = raw.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return raw

    migrated = {
        **raw,
        "nodes": [dict(node) for node in nodes if isinstance(node, dict)],
        "edges": [dict(edge) for edge in edges if isinstance(edge, dict)],
    }
    default_canvas = _default_research_flow_canvas()
    template_nodes = {node["id"]: node for node in default_canvas["nodes"]}
    template_edges = {edge["id"]: edge for edge in default_canvas["edges"]}
    node_ids = {str(node.get("id") or "") for node in migrated["nodes"]}
    has_legacy_direct_search_edge = any(
        str(edge.get("id") or "") == "edge_broad_deep"
        or (str(edge.get("source") or "") == "broad_search" and str(edge.get("target") or "") == "deep_search")
        for edge in migrated["edges"]
    )
    if "knowledge_store" not in node_ids:
        previous = next((node for node in migrated["nodes"] if str(node.get("id") or "") == "deep_search"), None)
        store_node = dict(template_nodes["knowledge_store"])
        if isinstance(previous, dict) and str(previous.get("status") or "") == "done":
            store_node["status"] = "done"
        if has_legacy_direct_search_edge:
            for node in migrated["nodes"]:
                if str(node.get("id") or "") == "broad_search":
                    continue
                x = _safe_number(node.get("x"), 0)
                if x >= 360:
                    node["x"] = x + 300
        insert_at = next(
            (index for index, node in enumerate(migrated["nodes"]) if str(node.get("id") or "") == "deep_search"),
            len(migrated["nodes"]),
        )
        migrated["nodes"].insert(insert_at, store_node)

    node_ids = {str(node.get("id") or "") for node in migrated["nodes"]}
    capability_insert_after = {
        "knowledge_lookup": "knowledge_store",
        "literature_project_parse": "deep_search",
        "semantic_cluster": "literature_project_parse",
        "novelty_reverse_check": "semantic_cluster",
    }
    for node_id in _RESEARCH_CAPABILITY_NODE_IDS:
        if node_id in node_ids:
            continue
        template = dict(template_nodes[node_id])
        template["status"] = _migrated_capability_status(node_id, migrated["nodes"])
        anchor_id = capability_insert_after[node_id]
        anchor_index = next(
            (index for index, node in enumerate(migrated["nodes"]) if str(node.get("id") or "") == anchor_id),
            len(migrated["nodes"]) - 1,
        )
        migrated["nodes"].insert(anchor_index + 1, template)
        node_ids.add(node_id)

    edge_ids = {str(edge.get("id") or "") for edge in migrated["edges"]}
    legacy_edge_ids = {
        "edge_broad_deep",
        "edge_store_deep",
        "edge_deep_review",
    }
    migrated["edges"] = [
        edge
        for edge in migrated["edges"]
        if str(edge.get("id") or "") not in legacy_edge_ids
        and not (str(edge.get("source") or "") == "broad_search" and str(edge.get("target") or "") == "deep_search")
        and not (str(edge.get("source") or "") == "knowledge_store" and str(edge.get("target") or "") == "deep_search")
        and not (str(edge.get("source") or "") == "deep_search" and str(edge.get("target") or "") == "evidence_review")
    ]
    edge_ids = {str(edge.get("id") or "") for edge in migrated["edges"]}
    required_edges = [
        template_edges["edge_broad_store"],
        template_edges["edge_store_lookup"],
        template_edges["edge_lookup_deep"],
        template_edges["edge_deep_parse"],
        template_edges["edge_parse_cluster"],
        template_edges["edge_cluster_novelty"],
        template_edges["edge_novelty_review"],
    ]
    node_ids = {str(node.get("id") or "") for node in migrated["nodes"]}
    for edge in required_edges:
        if edge["id"] in edge_ids or edge["source"] not in node_ids or edge["target"] not in node_ids:
            continue
        migrated["edges"].append(dict(edge))
        edge_ids.add(edge["id"])
    return migrated


def _migrated_capability_status(node_id: str, nodes: list[dict[str, Any]]) -> str:
    statuses = {str(node.get("id") or ""): str(node.get("status") or "") for node in nodes}
    downstream_review_status = statuses.get("evidence_review") or ""
    downstream_theme_status = statuses.get("theme_generation") or ""
    review_started = downstream_review_status in {"ready", "running", "done", "needs_evidence"}
    theme_started = downstream_theme_status in {"ready", "running", "done", "needs_input"}
    if node_id == "knowledge_lookup":
        if statuses.get("deep_search") in {"ready", "running", "done"} or review_started or theme_started:
            return "done"
        if statuses.get("knowledge_store") in {"ready", "running", "done"}:
            return "ready"
        return "idle"
    if node_id == "literature_project_parse":
        if review_started or theme_started:
            return "done"
        if statuses.get("deep_search") == "done":
            return "ready"
        return "idle"
    if node_id in {"semantic_cluster", "novelty_reverse_check"}:
        return "done" if review_started or theme_started else "idle"
    return "idle"


def _normalize_research_flow_canvas(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Research flow canvas payload must be an object.")
    nodes = raw.get("nodes")
    edges = raw.get("edges")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("Research flow canvas requires at least one node.")
    if not isinstance(edges, list):
        raise ValueError("Research flow canvas edges must be a list.")
    normalized_nodes = [_normalize_flow_canvas_node(item, index) for index, item in enumerate(nodes[:80])]
    node_ids = {node["id"] for node in normalized_nodes}
    if len(node_ids) != len(normalized_nodes):
        raise ValueError("Research flow canvas node ids must be unique.")
    normalized_edges = [_normalize_flow_canvas_edge(item, index, node_ids) for index, item in enumerate(edges[:160])]
    viewport = raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {}
    return {
        "schemaVersion": 1,
        "updatedAt": str(raw.get("updatedAt") or _utc_now()),
        "viewport": {
            "x": _safe_number(viewport.get("x"), 0),
            "y": _safe_number(viewport.get("y"), 0),
            "zoom": max(0.25, min(2, _safe_number(viewport.get("zoom"), 1))),
        },
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


def _normalize_flow_canvas_node(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Research flow canvas node must be an object.")
    node_id = _safe_token(item.get("id"), default=f"node_{index + 1}")
    status = _safe_token(item.get("status"), default="idle")
    node_type = _safe_token(item.get("type"), default="agent")
    return {
        "id": node_id,
        "label": _safe_text(item.get("label"), default=f"流程节点 {index + 1}", max_length=80),
        "type": node_type if node_type in _FLOW_CANVAS_NODE_TYPES else "agent",
        "status": status if status in _FLOW_CANVAS_STATUSES else "idle",
        "x": _safe_number(item.get("x"), 80 + index * 220),
        "y": _safe_number(item.get("y"), 120),
        "agentKey": _safe_text(item.get("agentKey"), max_length=64),
        "promptKey": _safe_text(item.get("promptKey"), max_length=64),
        "llmConfigId": _safe_text(item.get("llmConfigId"), max_length=128),
        "description": _safe_text(item.get("description"), max_length=1200),
        "routeCondition": _safe_text(item.get("routeCondition"), max_length=600),
    }


def _normalize_flow_canvas_edge(item: Any, index: int, node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Research flow canvas edge must be an object.")
    source = _safe_token(item.get("source"), default="")
    target = _safe_token(item.get("target"), default="")
    if source not in node_ids or target not in node_ids:
        raise ValueError("Research flow canvas edge must reference existing nodes.")
    condition = _safe_token(item.get("condition"), default="completed")
    if condition not in _FLOW_CANVAS_EDGE_CONDITIONS:
        condition = "completed"
    edge_type = _safe_token(item.get("type"), default="")
    return {
        "id": _safe_token(item.get("id"), default=f"edge_{index + 1}"),
        "source": source,
        "target": target,
        "label": _safe_text(item.get("label"), default="路由", max_length=80),
        "condition": condition,
        "type": edge_type if edge_type in _FLOW_CANVAS_EDGE_TYPES else _infer_flow_edge_type(condition),
    }


def _infer_flow_edge_type(condition: str) -> str:
    normalized = _safe_text(condition, default="completed", max_length=160).strip().lower()
    if normalized == "needs_evidence":
        return "evidence_loop"
    if normalized == "approved":
        return "approval_gate"
    if normalized == "selected":
        return "selection"
    if normalized == "failed":
        return "failure"
    if normalized == "blocked":
        return "blocked"
    return "success"


def _with_flow_canvas_validation(canvas: dict[str, Any]) -> dict[str, Any]:
    return {
        **canvas,
        "validation": _validate_research_flow_canvas(canvas),
    }


def _validate_research_flow_canvas(canvas: dict[str, Any]) -> dict[str, Any]:
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    issues: list[dict[str, Any]] = []
    node_by_id = {str(node.get("id") or ""): node for node in nodes if isinstance(node, dict)}
    incoming: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_by_id}
    outgoing: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_by_id}
    edge_ids: set[str] = set()
    edge_pairs: set[tuple[str, str, str]] = set()

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("id") or "")
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        condition = _safe_token(edge.get("condition"), default="completed")
        edge_type = _safe_token(edge.get("type"), default=_infer_flow_edge_type(condition))
        source = node_by_id.get(source_id)
        target = node_by_id.get(target_id)
        if edge_id in edge_ids:
            issues.append(
                _flow_canvas_validation_issue(
                    "error",
                    "duplicate_edge_id",
                    f"路由 ID 重复：{edge_id}",
                    edge_id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                )
            )
        edge_ids.add(edge_id)
        if source_id == target_id:
            issues.append(
                _flow_canvas_validation_issue(
                    "error",
                    "self_loop",
                    f"路由 {edge_id or source_id} 不能连接到自身。",
                    edge_id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                )
            )
        expected_edge_types = _FLOW_CANVAS_CONDITION_EDGE_TYPES.get(condition, set())
        if expected_edge_types and edge_type not in expected_edge_types:
            issues.append(
                _flow_canvas_validation_issue(
                    "error",
                    "edge_type_condition_mismatch",
                    f"路由 {edge_id or source_id} 的触发条件 {condition} 与箭头类型 {edge_type} 不一致。",
                    edge_id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                )
            )
        pair = (source_id, target_id, condition)
        if pair in edge_pairs:
            issues.append(
                _flow_canvas_validation_issue(
                    "warning",
                    "duplicate_edge_pair",
                    f"{source_id} 到 {target_id} 已存在同条件路由 {condition}。",
                    edge_id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                )
            )
        edge_pairs.add(pair)
        if source is not None:
            outgoing.setdefault(source_id, []).append(edge)
        if target is not None:
            incoming.setdefault(target_id, []).append(edge)
        if source is None or target is None:
            continue

        source_contract = _flow_contract_for_node(source)
        target_contract = _flow_contract_for_node(target)
        if source_contract is None:
            issues.append(
                _flow_canvas_validation_issue(
                    "warning",
                    "unknown_source_contract",
                    f"模块 {source.get('label') or source_id} 没有已知输出契约，无法完全验证路由 {edge_id or source_id}。",
                    edge_id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                )
            )
        else:
            source_outputs_by_condition = _flow_contract_outputs(source_contract)
            if condition not in source_outputs_by_condition:
                issues.append(
                    _flow_canvas_validation_issue(
                        "error",
                        "edge_condition_not_produced",
                        f"模块 {source.get('label') or source_id} 不会产生 {condition} 分支。",
                        edge_id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                    )
                )

        if source_contract is not None and target_contract is not None:
            source_outputs = _flow_outputs_for_condition(source_contract, condition)
            target_input_options = _flow_contract_input_options(target_contract)
            if target_input_options and not _flow_outputs_satisfy_inputs(source_outputs, target_input_options):
                issues.append(
                    _flow_canvas_validation_issue(
                        "error",
                        "edge_io_mismatch",
                        (
                            f"路由 {edge_id or source_id} 输出 {', '.join(sorted(source_outputs)) or '空'}，"
                            f"无法满足 {target.get('label') or target_id} 的输入契约。"
                        ),
                        edge_id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                    )
                )
        elif target_contract is not None and _flow_contract_input_options(target_contract):
            issues.append(
                _flow_canvas_validation_issue(
                    "warning",
                    "target_input_unverified",
                    f"模块 {target.get('label') or target_id} 有输入要求，但上游契约未知，无法完全验证。",
                    edge_id=edge_id,
                    source_id=source_id,
                    target_id=target_id,
                )
            )

    start_node_ids = {node_id for node_id, inbound in incoming.items() if not inbound}
    if nodes and not start_node_ids:
        issues.append(
            _flow_canvas_validation_issue(
                "error",
                "flow_missing_start_node",
                "科研流程画布没有起点模块，所有节点都依赖上游输入。",
            )
        )
    reachable = _reachable_flow_node_ids(start_node_ids, outgoing)
    for node_id, node in node_by_id.items():
        contract = _flow_contract_for_node(node)
        if contract is None:
            continue
        input_options = _flow_contract_input_options(contract)
        if input_options and not incoming.get(node_id):
            issues.append(
                _flow_canvas_validation_issue(
                    "warning",
                    "node_missing_required_input",
                    f"模块 {node.get('label') or node_id} 需要上游输入，但当前没有任何进入路由。",
                    node_id=node_id,
                )
            )
        if node_id not in reachable and start_node_ids:
            issues.append(
                _flow_canvas_validation_issue(
                    "warning",
                    "node_unreachable",
                    f"模块 {node.get('label') or node_id} 无法从起点流程到达。",
                    node_id=node_id,
                )
            )
        expected_outcomes = _flow_expected_outcomes(contract)
        if not contract.get("terminal") and expected_outcomes:
            existing_outcomes = {_safe_token(edge.get("condition"), default="completed") for edge in outgoing.get(node_id, [])}
            missing_outcomes = sorted(expected_outcomes - existing_outcomes)
            if missing_outcomes:
                issues.append(
                    _flow_canvas_validation_issue(
                        "warning",
                        "node_missing_outcome_route",
                        f"模块 {node.get('label') or node_id} 缺少分支路由：{', '.join(missing_outcomes)}。",
                        node_id=node_id,
                    )
                )
    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "valid": error_count == 0,
        "summary": {
            "errorCount": error_count,
            "warningCount": warning_count,
            "issueCount": len(issues),
        },
        "issues": issues,
    }


def _flow_canvas_validation_issue(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: str = "",
    edge_id: str = "",
    source_id: str = "",
    target_id: str = "",
) -> dict[str, Any]:
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if node_id:
        issue["nodeId"] = node_id
    if edge_id:
        issue["edgeId"] = edge_id
    if source_id:
        issue["source"] = source_id
    if target_id:
        issue["target"] = target_id
    return issue


def _flow_contract_for_node(node: dict[str, Any]) -> dict[str, Any] | None:
    return _RESEARCH_FLOW_MODULE_CONTRACTS.get(_flow_node_action_key(node))


def _flow_contract_outputs(contract: dict[str, Any]) -> dict[str, set[str]]:
    raw_outputs = contract.get("outputs") if isinstance(contract.get("outputs"), dict) else {}
    return {
        str(condition): {str(item) for item in outputs if str(item).strip()}
        for condition, outputs in raw_outputs.items()
        if isinstance(outputs, (set, list, tuple))
    }


def _flow_outputs_for_condition(contract: dict[str, Any], condition: str) -> set[str]:
    outputs = _flow_contract_outputs(contract)
    return set(outputs.get(condition) or outputs.get("completed") or set())


def _flow_contract_input_options(contract: dict[str, Any]) -> list[set[str]]:
    raw_inputs = contract.get("inputs") if isinstance(contract.get("inputs"), list) else []
    options: list[set[str]] = []
    for option in raw_inputs:
        if isinstance(option, (set, list, tuple)):
            normalized = {str(item) for item in option if str(item).strip()}
            if normalized:
                options.append(normalized)
    return options


def _flow_outputs_satisfy_inputs(outputs: set[str], input_options: list[set[str]]) -> bool:
    return any(required.issubset(outputs) for required in input_options)


def _flow_expected_outcomes(contract: dict[str, Any]) -> set[str]:
    raw_expected = contract.get("expectedOutcomes")
    if isinstance(raw_expected, (set, list, tuple)):
        return {str(item) for item in raw_expected if str(item).strip()}
    return set(_flow_contract_outputs(contract).keys())


def _reachable_flow_node_ids(start_node_ids: set[str], outgoing: dict[str, list[dict[str, Any]]]) -> set[str]:
    reachable: set[str] = set()
    stack = list(start_node_ids)
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        for edge in outgoing.get(node_id, []):
            target_id = str(edge.get("target") or "")
            if target_id and target_id not in reachable:
                stack.append(target_id)
    return reachable


def _format_flow_canvas_validation_error(validation: dict[str, Any]) -> str:
    errors = [issue for issue in validation.get("issues", []) if issue.get("severity") == "error"]
    details = "; ".join(str(issue.get("message") or issue.get("code") or "invalid flow") for issue in errors[:3])
    suffix = f"；另有 {len(errors) - 3} 个错误" if len(errors) > 3 else ""
    return f"Research flow canvas contract invalid: {details}{suffix}"


def _flow_canvas_validation_log_fields(validation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(validation, dict):
        return {}
    summary = validation.get("summary") if isinstance(validation.get("summary"), dict) else {}
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    codes = [str(issue.get("code") or "") for issue in issues if isinstance(issue, dict) and issue.get("severity") == "error"]
    return {
        "validationValid": bool(validation.get("valid")),
        "validationErrorCount": _safe_int(summary.get("errorCount")),
        "validationWarningCount": _safe_int(summary.get("warningCount")),
        "validationErrorCodes": codes[:8],
    }


def _detect_flow_canvas_mojibake(canvas: dict[str, Any]) -> dict[str, Any]:
    markers: list[dict[str, Any]] = []
    for node in canvas.get("nodes", []) if isinstance(canvas.get("nodes"), list) else []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        for field in _FLOW_CANVAS_TEXT_FIELDS:
            _append_mojibake_marker(markers, "node", node_id, field, node.get(field))
    for edge in canvas.get("edges", []) if isinstance(canvas.get("edges"), list) else []:
        if not isinstance(edge, dict):
            continue
        edge_id = str(edge.get("id") or "")
        for field in _FLOW_CANVAS_EDGE_TEXT_FIELDS:
            _append_mojibake_marker(markers, "edge", edge_id, field, edge.get(field))
    return {
        "markerCount": len(markers),
        "markers": markers[:12],
    }


def _append_mojibake_marker(
    markers: list[dict[str, Any]],
    kind: str,
    item_id: str,
    field: str,
    value: Any,
) -> None:
    text = str(value or "")
    if not text or not _MOJIBAKE_MARKER_RE.search(text):
        return
    markers.append(
        {
            "kind": kind,
            "id": item_id,
            "field": field,
            "preview": text[:80],
        }
    )


def _format_flow_canvas_mojibake_error(report: dict[str, Any]) -> str:
    markers = report.get("markers") if isinstance(report.get("markers"), list) else []
    first = markers[0] if markers and isinstance(markers[0], dict) else {}
    target = ".".join(part for part in [str(first.get("id") or ""), str(first.get("field") or "")] if part)
    suffix = f" at {target}" if target else ""
    return f"Research flow canvas contains mojibake text{suffix}; reload the canvas from UTF-8 source before saving."


def _flow_canvas_mojibake_log_fields(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    markers = report.get("markers") if isinstance(report.get("markers"), list) else []
    previews = []
    for marker in markers[:6]:
        if not isinstance(marker, dict):
            continue
        previews.append(
            {
                "kind": str(marker.get("kind") or ""),
                "id": str(marker.get("id") or ""),
                "field": str(marker.get("field") or ""),
                "preview": str(marker.get("preview") or "")[:80],
            }
        )
    return {
        "mojibakeMarkerCount": _safe_int(report.get("markerCount")),
        "mojibakeMarkers": previews,
    }


def _safe_text(value: Any, *, default: str = "", max_length: int = 500) -> str:
    text = str(value if value is not None else default).strip()
    return text[:max_length]


def _safe_token(value: Any, *, default: str) -> str:
    text = _safe_text(value, default=default, max_length=128)
    normalized = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)
    normalized = normalized.strip("_-")
    return normalized or default


def _safe_number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_research_agent_config() -> dict[str, Any]:
    workspace = get_workspace()
    raw = workspace.read_research_agent_config()
    config = normalize_research_agent_config(raw)
    return {
        **config,
        "configPath": str(workspace.get_research_agent_config_path()),
    }


def _list_llm_config_options() -> list[dict[str, Any]]:
    try:
        public_config = load_public_config()
        effective = build_effective_config(public_config)
    except Exception:
        return []
    lang = str(public_config.get("ui", {}).get("language", "zh")).strip() or "zh"
    options: list[dict[str, Any]] = []
    for profile_id in effective.llm.profiles:
        try:
            profile = effective.llm.get_profile(profile_id=profile_id)
            provider = effective.llm.get_provider(profile.provider_id)
        except Exception:
            continue
        options.append(
            {
                "configId": str(profile_id),
                "label": _profile_label(str(profile_id), lang),
                "model": profile.model,
                "providerKind": provider.kind,
            }
        )
    return options


def _record_research_config_event(
    event_code: str,
    *,
    phase: str,
    message: str,
    fields: dict[str, Any],
    agent_key: str = "",
    outcome: str = "succeeded",
    level: str = "info",
) -> None:
    try:
        record_research_scene_event(
            event_code,
            phase=phase,
            message=message,
            outcome=outcome,
            level=level,
            fields=fields,
            session_id=str(fields.get("sessionId") or ""),
            agent_key=agent_key or str(fields.get("agentKey") or ""),
        )
    except Exception:
        pass
