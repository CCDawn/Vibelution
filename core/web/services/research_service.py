"""Web service facade for Research theme discovery."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.research.agent_templates import (
    RESEARCH_AGENT_TEMPLATES,
    RESEARCH_PROMPT_FILES,
    ensure_research_prompt_defaults,
    research_default_prompt,
    normalize_research_agent_config,
)
from core.research import ResearchThemeDiscoveryService
from core.infrastructure.workspace_manager import get_workspace
from config.public_config import build_effective_config, load_public_config
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
                "id": "deep_search",
                "label": "定向深搜",
                "type": "agent",
                "status": "idle",
                "x": 380,
                "y": 120,
                "agentKey": "deep",
                "promptKey": "deep",
                "llmConfigId": "research_deep",
                "description": "围绕上一阶段发现的关键缺口、论文、GitHub 项目和数据集补充证据。",
                "routeCondition": "广搜完成且存在候选证据线索",
            },
            {
                "id": "evidence_review",
                "label": "证据审查",
                "type": "agent",
                "status": "needs_review",
                "x": 680,
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
                "x": 980,
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
                "x": 980,
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
                "x": 1280,
                "y": 220,
                "agentKey": "card",
                "promptKey": "card",
                "llmConfigId": "research_card",
                "description": "产出赛题要求的科学假设与研究计划结构，包括数据集、方法、实验、指标和参考文献。",
                "routeCondition": "用户确认主题后生成",
            },
        ],
        "edges": [
            {"id": "edge_broad_deep", "source": "broad_search", "target": "deep_search", "label": "候选线索", "condition": "completed"},
            {"id": "edge_deep_review", "source": "deep_search", "target": "evidence_review", "label": "证据包", "condition": "completed"},
            {"id": "edge_review_deep", "source": "evidence_review", "target": "deep_search", "label": "缺证据补搜", "condition": "needs_evidence"},
            {"id": "edge_review_themes", "source": "evidence_review", "target": "theme_generation", "label": "证据通过", "condition": "approved"},
            {"id": "edge_themes_choice", "source": "theme_generation", "target": "human_choice", "label": "候选主题", "condition": "completed"},
            {"id": "edge_choice_card", "source": "human_choice", "target": "theme_card", "label": "选定主题", "condition": "selected"},
        ],
    }


def list_theme_discovery_sessions() -> dict[str, Any]:
    return _SERVICE.list_sessions()


def create_theme_discovery_session(payload: dict[str, Any]) -> dict[str, Any]:
    return _SERVICE.create_session(payload)


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
    return _SERVICE.run_broad_search(session_id)


def run_deep_theme_search(session_id: str, evidence_requests: list[str] | None = None) -> dict[str, Any]:
    return _SERVICE.run_deep_search(session_id, evidence_requests=evidence_requests)


def extract_theme_discovery_evidence(session_id: str) -> dict[str, Any]:
    return _SERVICE.extract_evidence(session_id)


def generate_candidate_themes(session_id: str) -> dict[str, Any]:
    return _SERVICE.generate_themes(session_id)


def run_theme_discovery_draft(session_id: str) -> dict[str, Any]:
    return _SERVICE.run_draft(session_id)


def select_candidate_theme(session_id: str, theme_id: str) -> dict[str, Any]:
    return _SERVICE.select_theme(session_id, theme_id)


def generate_theme_card(session_id: str, theme_id: str) -> dict[str, Any]:
    return _SERVICE.generate_theme_card(session_id, theme_id)


def approve_theme_card(session_id: str, card_id: str) -> dict[str, Any]:
    return _SERVICE.approve_theme_card(session_id, card_id)


def list_research_prompts() -> dict[str, Any]:
    workspace = get_workspace()
    ensure_research_prompt_defaults(workspace)
    agent_config = _load_research_agent_config()
    llm_configs = _list_llm_config_options()
    prompts: list[dict[str, Any]] = []
    for key, filename in RESEARCH_PROMPT_FILES.items():
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


def save_research_prompt(key: str, content: str) -> dict[str, Any]:
    normalized = str(key or "").strip().lower()
    if normalized not in RESEARCH_PROMPT_FILES:
        raise ValueError(f"Unknown research prompt key: {key}")
    workspace = get_workspace()
    filename = RESEARCH_PROMPT_FILES[normalized]
    if not workspace.write_research_prompt(filename, str(content or "")):
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


def save_research_agent_binding(key: str, template_id: str, llm_config_id: str | None = None) -> dict[str, Any]:
    normalized = str(key or "").strip().lower()
    if normalized not in RESEARCH_PROMPT_FILES:
        raise ValueError(f"Unknown research agent key: {key}")
    known_templates = {item["templateId"] for item in RESEARCH_AGENT_TEMPLATES}
    selected_template = str(template_id or "").strip()
    if selected_template not in known_templates:
        raise ValueError(f"Unknown research agent template: {template_id}")
    selected_llm_config = str(llm_config_id or "").strip()
    if selected_llm_config:
        known_llm_configs = {item["configId"] for item in _list_llm_config_options()}
        if selected_llm_config not in known_llm_configs:
            raise ValueError(f"Unknown research LLM config: {llm_config_id}")
    config = _load_research_agent_config()
    agents = config["agents"]
    for agent in agents:
        if agent["key"] == normalized:
            agent["templateId"] = selected_template
            if selected_llm_config:
                agent["llmConfigId"] = selected_llm_config
            break
    workspace = get_workspace()
    if not workspace.write_research_agent_config({"schemaVersion": 1, "agents": agents}):
        raise ValueError("Failed to write research agent template config.")
    _record_research_config_event(
        "research.agent_binding.updated",
        phase="agent_template_config",
        message="Research agent template binding updated",
        fields={
            "agentKey": normalized,
            "templateId": selected_template,
            "llmConfigId": selected_llm_config,
        },
        agent_key=normalized,
    )
    return list_research_prompts()


def get_research_flow_canvas() -> dict[str, Any]:
    workspace = get_workspace()
    raw = workspace.read_research_flow_canvas()
    canvas = _normalize_research_flow_canvas(raw or _default_research_flow_canvas())
    return {
        **canvas,
        "path": str(workspace.get_research_flow_canvas_path()),
    }


def save_research_flow_canvas(payload: dict[str, Any]) -> dict[str, Any]:
    workspace = get_workspace()
    canvas = _normalize_research_flow_canvas(payload)
    canvas["updatedAt"] = _utc_now()
    if not workspace.write_research_flow_canvas(canvas):
        raise ValueError("Failed to write research flow canvas.")
    _record_research_config_event(
        "research.flow_canvas.updated",
        phase="flow_canvas",
        message="Research flow canvas updated",
        fields={
            "path": str(workspace.get_research_flow_canvas_path()),
            "nodeCount": len(canvas["nodes"]),
            "edgeCount": len(canvas["edges"]),
        },
    )
    return {
        **canvas,
        "path": str(workspace.get_research_flow_canvas_path()),
    }


def get_research_agent_bindings() -> dict[str, Any]:
    return _load_research_agent_config()


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
    return {
        "id": _safe_token(item.get("id"), default=f"edge_{index + 1}"),
        "source": source,
        "target": target,
        "label": _safe_text(item.get("label"), default="路由", max_length=80),
        "condition": _safe_text(item.get("condition"), max_length=160),
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
) -> None:
    try:
        record_research_scene_event(
            event_code,
            phase=phase,
            message=message,
            outcome="succeeded",
            fields=fields,
            session_id=str(fields.get("sessionId") or ""),
            agent_key=agent_key or str(fields.get("agentKey") or ""),
        )
    except Exception:
        pass
