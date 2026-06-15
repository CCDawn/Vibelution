"""Web service facade for Research theme discovery."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.research.agent_templates import (
    RESEARCH_AGENT_DEFAULT_LLM_CONFIG,
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
from core.chat.chat_task_types import trim_lines
from core.ui.chat_state import load_chat_state
from core.logging.logger import debug as _debug_logger
from config.public_config import build_effective_config, load_public_config
from . import agent_directory_service, agent_mode_binding_service, prompt_template_service, research_organization_service, session_service, team_service
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

_FLOW_CANVAS_KIND = "research_flow_canvas"
_ORGANIZATION_CANVAS_KIND = "research_agent_organization"
_FLOW_CANVAS_NODE_TYPES = {"agent", "tool", "human", "artifact", "decision", "evaluation"}
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
    "approved",
    "needs_evidence",
    "selected",
    "failed",
    "blocked",
}
_FLOW_CANVAS_CONDITION_EDGE_TYPES = {
    "completed": {"success", "human_handoff"},
    "approved": {"approval_gate"},
    "needs_evidence": {"evidence_loop"},
    "selected": {"selection"},
    "failed": {"failure"},
    "blocked": {"blocked"},
}
_MOJIBAKE_MARKER_RE = re.compile(r"(?:[ÃÂåæçèäéïã][\u0080-\u00bf]|�|\?{3,})")
_FLOW_CANVAS_TEXT_FIELDS = ("label", "description", "routeCondition")
_FLOW_CANVAS_EDGE_TEXT_FIELDS = ("label", "condition")
_FLOW_NODE_ACTION_ALIASES = {
    "research_ceo_entry": "research_ceo",
    "organization_advisor_entry": "organization_advisor",
    "capability_steward_entry": "capability_steward",
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
    "research_ceo": {
        "label": "科研 CEO",
        "inputs": [],
        "outputs": {
            "completed": {"research_goal", "organization_task", "proposal_request"},
        },
        "terminal": False,
    },
    "organization_advisor": {
        "label": "组织顾问",
        "inputs": [{"research_goal"}, {"organization_task"}, {"proposal_request"}],
        "outputs": {
            "completed": {"organization_proposal", "staffing_plan"},
        },
        "terminal": True,
    },
    "capability_steward": {
        "label": "能力管家",
        "inputs": [{"research_goal"}, {"organization_task"}, {"staffing_plan"}, {"policy_request"}],
        "outputs": {
            "completed": {"capability_policy", "prompt_policy", "tool_policy", "memory_policy"},
        },
        "terminal": True,
    },
    "broad": {
        "label": "广撒网探索",
        "inputs": [],
        "outputs": {
            "completed": {"sources", "research_leads", "knowledge_candidates"},
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
            "needs_evidence": {"sources", "evidence_context", "research_leads", "evidence_requests"},
            "completed": {"approved_evidence"},
        },
        "terminal": False,
        "expectedOutcomes": {"approved", "needs_evidence"},
    },
    "themes": {
        "label": "主题生成",
        "inputs": [{"approved_evidence"}],
        "outputs": {
            "selected": {"selected_theme"},
        },
        "terminal": False,
    },
    "human_choice": {
        "label": "人工选题确认",
        "inputs": [{"candidate_themes"}],
        "outputs": {"selected": {"selected_theme"}},
        "terminal": False,
        "expectedOutcomes": {"selected"},
    },
    "card": {
        "label": "正式主题卡",
        "inputs": [{"selected_theme"}],
        "outputs": {"completed": {"theme_card"}},
        "terminal": True,
    },
    "huawei_context_snapshot": {
        "label": "读取竞赛上下文",
        "inputs": [],
        "outputs": {"completed": {"workspace_context", "baseline_snapshot", "source_hash"}},
        "terminal": False,
    },
    "huawei_doctor": {
        "label": "运行环境体检",
        "inputs": [{"workspace_context"}, {"baseline_snapshot"}],
        "outputs": {
            "completed": {"harness_ok", "baseline_snapshot"},
            "blocked": {"harness_blocker"},
        },
        "terminal": False,
    },
    "huawei_baseline_gate": {
        "label": "基线一致性闸门",
        "inputs": [{"harness_blocker"}],
        "outputs": {"completed": {"harness_ok", "baseline_snapshot"}},
        "terminal": False,
    },
    "huawei_idea_board": {
        "label": "生成策略想法池",
        "inputs": [{"harness_ok"}, {"evidence_gap"}, {"learning_index"}, {"dataset_candidate"}],
        "outputs": {"completed": {"idea_board", "lane_plan"}},
        "terminal": False,
    },
    "huawei_prepare_epoch": {
        "label": "准备实验批次清单",
        "inputs": [{"idea_board"}, {"lane_plan"}],
        "outputs": {"completed": {"epoch_manifest", "worker_context"}},
        "terminal": False,
    },
    "huawei_dispatch_phase_a": {
        "label": "派发诊断阶段",
        "inputs": [{"epoch_manifest"}, {"worker_context"}],
        "outputs": {"completed": {"phase_a_results", "child_results"}},
        "terminal": False,
    },
    "huawei_collect_phase_a": {
        "label": "收集诊断证据",
        "inputs": [{"phase_a_results"}, {"child_results"}],
        "outputs": {
            "approved": {"phase_a_evidence"},
            "needs_evidence": {"evidence_gap"},
        },
        "terminal": False,
    },
    "huawei_phase_gate": {
        "label": "编辑实验放行闸门",
        "inputs": [{"phase_a_evidence"}],
        "outputs": {
            "approved": {"phase_b_ready"},
            "needs_evidence": {"evidence_gap"},
        },
        "terminal": False,
    },
    "huawei_dispatch_phase_b": {
        "label": "派发编辑实验",
        "inputs": [{"phase_b_ready"}],
        "outputs": {"completed": {"candidate_patch", "child_results"}},
        "terminal": False,
    },
    "huawei_local_benchmark": {
        "label": "运行本地基准",
        "inputs": [{"candidate_patch"}],
        "outputs": {"completed": {"proxy_evidence", "candidate_patch"}},
        "terminal": False,
    },
    "huawei_gate_child": {
        "label": "候选方案门控",
        "inputs": [{"proxy_evidence"}],
        "outputs": {
            "approved": {"accepted_candidate"},
            "needs_evidence": {"evidence_gap"},
            "failed": {"failed_attempt"},
        },
        "terminal": False,
    },
    "huawei_package_submission": {
        "label": "打包与提交映射",
        "inputs": [{"accepted_candidate"}],
        "outputs": {"completed": {"registered_submission", "submission_zip"}},
        "terminal": False,
    },
    "huawei_online_feedback": {
        "label": "线上反馈录入",
        "inputs": [{"registered_submission"}, {"submission_zip"}],
        "outputs": {
            "selected": {"online_score"},
            "needs_evidence": {"online_contradiction"},
        },
        "terminal": False,
    },
    "huawei_baseline_promotion": {
        "label": "基线晋升与冻结",
        "inputs": [{"online_score"}],
        "outputs": {"completed": {"baseline_update", "online_calibration"}},
        "terminal": False,
    },
    "huawei_dataset_learning": {
        "label": "数据集与经验回写",
        "inputs": [{"online_contradiction"}, {"failed_attempt"}, {"baseline_update"}, {"child_results"}],
        "outputs": {"completed": {"learning_index", "dataset_candidate"}},
        "terminal": False,
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
    return _legacy_research_flow_canvas()


def _legacy_research_flow_canvas() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "canvasKind": _FLOW_CANVAS_KIND,
        "updatedAt": _utc_now(),
        "viewport": {"x": 40, "y": 120, "zoom": 1},
        "nodes": [
            {
                "id": "research_ceo_entry",
                "label": "CEO Agent",
                "type": "agent",
                "status": "ready",
                "x": 80,
                "y": 160,
                "agentKey": "research_ceo",
                "promptKey": "research_ceo",
                "llmConfigId": "",
                "description": "默认科研团队入口。CEO 接收用户研究目标，拆成组织任务，并决定是否让顾问提出新增研究员方案。",
                "routeCondition": "用户提出科研目标后由 CEO 统筹",
            },
            {
                "id": "organization_advisor_entry",
                "label": "组织顾问 Agent",
                "type": "agent",
                "status": "idle",
                "x": 520,
                "y": 160,
                "agentKey": "organization_advisor",
                "promptKey": "organization_advisor",
                "llmConfigId": "",
                "description": "顾问根据 CEO 的组织任务设计临时科研组织，形成新增研究员、权限和通信边的提案。",
                "routeCondition": "CEO 需要扩充科研团队时委托顾问",
            },
            {
                "id": "capability_steward_entry",
                "label": "能力管家 Agent",
                "type": "agent",
                "status": "idle",
                "x": 960,
                "y": 160,
                "agentKey": "capability_steward",
                "promptKey": "capability_steward",
                "llmConfigId": "",
                "description": "能力管家统一审查科研 Agent 的提示词、工具权限和记忆策略，确保任务扩展时权限最小且沟通边正确。",
                "routeCondition": "CEO 或顾问需要配置/审查 Agent 能力边界时触发",
            },
        ],
        "edges": [
            {
                "id": "edge_ceo_advisor",
                "source": "research_ceo_entry",
                "target": "organization_advisor_entry",
                "label": "组织设计请求",
                "condition": "completed",
                "type": "success",
            },
            {
                "id": "edge_ceo_steward",
                "source": "research_ceo_entry",
                "target": "capability_steward_entry",
                "label": "能力策略请求",
                "condition": "completed",
                "type": "success",
            },
            {
                "id": "edge_advisor_steward",
                "source": "organization_advisor_entry",
                "target": "capability_steward_entry",
                "label": "权限与记忆审查",
                "condition": "completed",
                "type": "success",
            },
        ],
    }


def _research_organization_flow_canvas() -> dict[str, Any]:
    organization = research_organization_service.get_research_organization_canvas_graph()
    team = team_service.ensure_research_team_from_organization(organization)
    team_id = str(team.get("teamId") or "research-team").strip() or "research-team"
    agents = [
        item
        for item in organization.get("agents") or []
        if isinstance(item, dict) and str(item.get("status") or "active").strip() != "archived"
    ]
    node_ids = {_safe_token(item.get("agentId") or item.get("nodeId"), default="") for item in agents}
    nodes = _layout_research_org_flow_nodes([
        _research_org_agent_to_flow_node(item, index) for index, item in enumerate(agents)
    ])
    edges = [
        _research_org_edge_to_flow_edge(item, index)
        for index, item in enumerate(organization.get("edges") or [])
        if isinstance(item, dict)
        and str(item.get("status") or "active").strip() != "archived"
        and _safe_token(item.get("fromAgentId"), default="") in node_ids
        and _safe_token(item.get("toAgentId"), default="") in node_ids
    ]
    return _normalize_research_flow_canvas(
        {
            "schemaVersion": 1,
            "canvasKind": _FLOW_CANVAS_KIND,
            "updatedAt": str(organization.get("updatedAt") or _utc_now()),
            "organizationPath": str(organization.get("path") or ""),
            "projectBinding": {
                "projectKind": "team",
                "projectId": team_id,
                "teamId": team_id,
                "teamName": str(team.get("name") or "科研团队"),
                "source": "team",
                "organizationSource": "research_organization",
                "locked": True,
            },
            "viewport": {"x": 40, "y": 80, "zoom": 1},
            "nodes": nodes,
            "edges": edges,
        }
    )


def _research_org_agent_to_flow_node(agent_node: dict[str, Any], index: int) -> dict[str, Any]:
    agent = agent_node.get("agent") if isinstance(agent_node.get("agent"), dict) else {}
    agent_id = _safe_token(agent_node.get("agentId") or agent_node.get("nodeId"), default=f"research_agent_{index + 1}")
    role = _safe_token(agent_node.get("role") or agent.get("roleKey"), default="research_agent")
    display_name = _safe_text(
        agent_node.get("displayName") or agent.get("displayName"),
        default=f"科研 Agent {index + 1}",
        max_length=80,
    )
    function_label = _research_org_function_label(agent_node, agent)
    responsibilities = []
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if isinstance(metadata.get("responsibilities"), list):
        responsibilities = [str(item).strip() for item in metadata.get("responsibilities") if str(item).strip()]
    description = trim_lines(
        str(agent_node.get("description") or "; ".join(responsibilities) or function_label),
        max_lines=6,
    )
    return {
        "id": agent_id,
        "label": display_name,
        "type": "agent",
        "status": "ready" if str(agent_node.get("status") or "active").strip() == "active" else str(agent_node.get("status") or "idle"),
        "x": _safe_number(agent_node.get("x"), 160 + index * 420),
        "y": _safe_number(agent_node.get("y"), 220 + (index % 2) * 220),
        "agentId": agent_id,
        "agentKey": role,
        "promptKey": _safe_text(agent.get("promptTemplateId") or agent.get("templateId") or role, max_length=64),
        "llmConfigId": "",
        "description": description,
        "routeCondition": function_label,
    }


def _layout_research_org_flow_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not nodes:
        return nodes
    role_order = {
        "ceo": 0,
        "organization_advisor": 1,
        "capability_steward": 2,
    }
    ordered = sorted(
        enumerate(nodes),
        key=lambda item: (
            role_order.get(str(item[1].get("agentKey") or ""), 20 + item[0]),
            str(item[1].get("label") or ""),
        ),
    )
    layout: dict[str, tuple[float, float]] = {}
    if len(ordered) == 1:
        layout[str(ordered[0][1]["id"])] = (260.0, 260.0)
    elif len(ordered) == 2:
        for item, position in zip(ordered, [(220.0, 280.0), (760.0, 280.0)]):
            layout[str(item[1]["id"])] = position
    else:
        base_positions = [(240.0, 440.0), (780.0, 260.0), (1320.0, 440.0)]
        for index, item in enumerate(ordered[:3]):
            layout[str(item[1]["id"])] = base_positions[index]
        for index, item in enumerate(ordered[3:]):
            column = index % 4
            row = index // 4
            layout[str(item[1]["id"])] = (240.0 + column * 460.0, 760.0 + row * 240.0)
    return [
        {
            **node,
            "x": layout.get(str(node.get("id") or ""), (float(node.get("x") or 0), float(node.get("y") or 0)))[0],
            "y": layout.get(str(node.get("id") or ""), (float(node.get("x") or 0), float(node.get("y") or 0)))[1],
        }
        for node in nodes
    ]


def _research_org_edge_to_flow_edge(edge: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": _safe_token(edge.get("edgeId") or edge.get("id"), default=f"communication_edge_{index + 1}"),
        "source": _safe_token(edge.get("fromAgentId"), default=""),
        "target": _safe_token(edge.get("toAgentId"), default=""),
        "label": _safe_text(edge.get("label"), default="组织通信", max_length=80),
        "condition": "completed",
        "type": "success",
    }


def _research_org_function_label(agent_node: dict[str, Any], agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    explicit = _safe_text(metadata.get("functionalDisplayName"), max_length=80)
    if explicit and explicit.lower() not in {"new session", "new chat", "agent", "main agent", "primary"} and explicit not in {"新会话", "主 Agent", "主代理"}:
        return explicit
    key = f"{agent_node.get('role') or ''} {agent.get('roleKey') or ''} {agent.get('promptTemplateId') or ''}".lower()
    if "capability" in key:
        return "能力策略 Agent"
    if "organization" in key or "advisor" in key:
        return "科研组织顾问"
    if "ceo" in key:
        return "科研负责人"
    if "broad" in key:
        return "广搜 Agent"
    if "deep" in key:
        return "深搜 Agent"
    if "review" in key:
        return "证据审查 Agent"
    if "theme" in key:
        return "主题生成 Agent"
    if "card" in key:
        return "主题卡 Agent"
    return "科研 Agent"


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
    """Ensure enabled research agents point at active Agent Center instances."""

    workspace = get_workspace()
    project_root = _project_root_for_workspace(workspace)
    previous_session_root = session_service.PROJECT_ROOT
    previous_agent_root = agent_directory_service.PROJECT_ROOT
    previous_binding_root = agent_mode_binding_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = project_root
    agent_directory_service.PROJECT_ROOT = project_root
    agent_mode_binding_service.PROJECT_ROOT = project_root
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
            agent_instance_id = str(agent.get("agentInstanceId") or agent.get("agentId") or "").strip()
            archived_or_missing_agent_id = ""
            instance = agent_directory_service.get_agent(agent_instance_id, include_archived=False) if agent_instance_id else None
            if agent_instance_id and not instance:
                archived_or_missing_agent_id = agent_instance_id
            profile_id = str((instance or {}).get("profileId") or agent.get("profileId") or agent.get("llmConfigId") or "").strip() or "primary"
            if archived_or_missing_agent_id:
                if agent.get("enabled") is not False:
                    agent["enabled"] = False
                agent["agentStatus"] = "stale"
                agent["staleAgentId"] = archived_or_missing_agent_id
                changed = True
                _record_research_config_event(
                    "research.agent_instance.stale_disabled",
                    phase="agent_template_config",
                    message="Research agent config referenced a missing or archived AgentInstance; disabling the stale binding.",
                    fields={
                        "agentKey": key,
                        "staleAgentId": archived_or_missing_agent_id,
                        "profileId": profile_id,
                    },
                    agent_key=key,
                )
                continue
            if not instance:
                try:
                    session_detail = session_service.create_chat_session(
                        title=label,
                        llm_bindings=session_service.llm_bindings_for_profile_id(profile_id),
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
                            "profileId": profile_id,
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
                    instance = agent_directory_service.get_agent(agent_instance_id, include_archived=False) or instance
                    profile_id = str(agent.get("profileId") or profile_id).strip() or "primary"
                    expected_metadata = {
                        "researchAgentKey": key,
                        "researchTemplateId": str(agent.get("templateId") or "").strip(),
                        "researchPromptFilename": str(agent.get("promptFilename") or "").strip(),
                    }
                    instance_metadata = dict((instance or {}).get("metadata") or {})
                    needs_instance_update = (
                        agent_directory_service.agent_dialogue_model_id(instance) != agent_directory_service.agent_dialogue_model_id({"llmBindings": session_service.llm_bindings_for_profile_id(profile_id)})
                        or str((instance or {}).get("primaryMode") or "").strip() != "research"
                        or str((instance or {}).get("roleKey") or "").strip() != f"research_{key}"
                        or str((instance or {}).get("promptTemplateId") or "").strip() != f"prompt-research-{key}"
                        or str(instance_metadata.get("functionalDisplayName") or "").strip() != label
                        or any(instance_metadata.get(field) != value for field, value in expected_metadata.items())
                    )
                    updated_instance = (
                        agent_directory_service.update_agent_instance(
                            agent_instance_id,
                            display_name=label,
                            llm_bindings=session_service.llm_bindings_for_profile_id(profile_id),
                            primary_mode="research",
                            role_key=f"research_{key}",
                            prompt_template_id=f"prompt-research-{key}",
                            metadata=expected_metadata,
                            preserve_generated_display_name=True,
                        )
                        if needs_instance_update
                        else (instance or {})
                    )
                    if agent.get("agentInstanceId") != agent_instance_id:
                        agent["agentInstanceId"] = agent_instance_id
                        changed = True
                    if agent.get("agentId") != agent_instance_id:
                        agent["agentId"] = agent_instance_id
                        changed = True
                    if str(agent.get("roleKey") or "").strip() != f"research_{key}":
                        agent["roleKey"] = f"research_{key}"
                        changed = True
                    if str(agent.get("promptTemplateId") or "").strip() != f"prompt-research-{key}":
                        agent["promptTemplateId"] = f"prompt-research-{key}"
                        changed = True
                    direct_session_id = str(updated_instance.get("directSessionId") or agent.get("directSessionId") or "").strip()
                    if direct_session_id:
                        try:
                            if not _research_direct_session_is_current(
                                direct_session_id,
                                title=label,
                                profile_id=profile_id,
                                agent_id=agent_instance_id,
                                project_root=project_root,
                            ):
                                session_service.update_chat_session(
                                    direct_session_id,
                                    title=label,
                                )
                        except Exception as exc:
                            _debug_logger.warning(
                                f"Failed to update direct session title for research agent={label}, direct_session_id={direct_session_id}. error={exc}"
                            )
                        if agent.get("directSessionId") != direct_session_id:
                            agent["directSessionId"] = direct_session_id
                            changed = True
                except Exception as exc:
                    _debug_logger.warning(f"Failed to sync research agent template instances. error={exc}")
        if changed:
            next_config = {
                "schemaVersion": 1,
                "deletedDefaultAgents": list(agent_config.get("deletedDefaultAgents") or []),
                "agents": agents,
            }
            write_config = getattr(workspace, "write_research_agent_config", None)
            if callable(write_config):
                write_config(_research_agent_storage_payload(next_config))
            _sync_research_mode_binding(agents)
            _record_research_config_event(
                "research.agent_instance.synced",
                phase="agent_template_config",
                message="Research agent instances synced to conversation registry",
                fields={"agentCount": len(agents)},
            )
            return normalize_research_agent_config(next_config)
        _sync_research_mode_binding(agents)
        return {**agent_config, "agents": agents}
    finally:
        session_service.PROJECT_ROOT = previous_session_root
        agent_directory_service.PROJECT_ROOT = previous_agent_root
        agent_mode_binding_service.PROJECT_ROOT = previous_binding_root


def _research_direct_session_is_current(
    session_id: str,
    *,
    title: str,
    profile_id: str,
    agent_id: str,
    project_root: Path,
) -> bool:
    """Return whether a research direct session already matches the Agent binding."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    expected_title = trim_lines(title or "", max_lines=1).strip()
    expected_profile_id = str(profile_id or "").strip()
    expected_agent_id = str(agent_id or "").strip()
    try:
        payload = load_chat_state(project_root)
    except Exception:
        return False
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return False
    for item in conversations:
        if not isinstance(item, dict):
            continue
        if str(item.get("conversation_id") or "").strip() != normalized_session_id:
            continue
        current_agent_id = str(item.get("agent_id") or item.get("agentId") or "").strip()
        current_profile_id = str(item.get("agent_profile_id") or item.get("agentProfileId") or "").strip()
        return (
            (not expected_title or str(item.get("title") or "").strip() == expected_title)
            and (not expected_agent_id or current_agent_id == expected_agent_id)
            and (not current_profile_id or current_profile_id == expected_profile_id)
        )
    return False


def _sync_research_mode_binding(agents: list[dict[str, Any]]) -> None:
    active_agent_ids = [
        str(agent.get("agentId") or agent.get("agentInstanceId") or "").strip()
        for agent in agents
        if isinstance(agent, dict) and agent.get("enabled") is not False
    ]
    active_agent_ids = [agent_id for agent_id in active_agent_ids if agent_id]
    if not active_agent_ids:
        try:
            if _research_mode_binding_is_current(default_agent_id="", active_agent_ids=[], flow_bindings={}):
                return
            agent_mode_binding_service.update_mode_binding(
                "research",
                default_agent_id="",
                available_agent_ids=[],
                pool=[],
                flow_bindings={},
            )
        except Exception as exc:
            _record_research_config_event(
                "research.mode_binding.sync_failed",
                phase="agent_template_config",
                message="Research mode binding sync failed",
                outcome="failed",
                level="warning",
                fields={"agentCount": 0, "errorType": type(exc).__name__, "message": str(exc)},
            )
        return
    flow_bindings = {
        str(agent.get("key") or "").strip(): str(agent.get("agentId") or agent.get("agentInstanceId") or "").strip()
        for agent in agents
        if isinstance(agent, dict) and agent.get("enabled") is not False
    }
    flow_bindings = {key: value for key, value in flow_bindings.items() if key and value}
    try:
        if _research_mode_binding_is_current(
            default_agent_id=active_agent_ids[0],
            active_agent_ids=active_agent_ids,
            flow_bindings=flow_bindings,
        ):
            return
        agent_mode_binding_service.update_mode_binding(
            "research",
            default_agent_id=active_agent_ids[0],
            available_agent_ids=active_agent_ids,
            pool=active_agent_ids,
            flow_bindings=flow_bindings,
        )
    except Exception as exc:
        _record_research_config_event(
            "research.mode_binding.sync_failed",
            phase="agent_template_config",
            message="Research mode binding sync failed",
            outcome="failed",
            level="warning",
            fields={"agentCount": len(active_agent_ids), "errorType": type(exc).__name__, "message": str(exc)},
        )


def _research_mode_binding_is_current(
    *,
    default_agent_id: str,
    active_agent_ids: list[str],
    flow_bindings: dict[str, str],
) -> bool:
    try:
        load_bindings = getattr(agent_mode_binding_service, "_load_mode_bindings", None)
        raw_payload = load_bindings() if callable(load_bindings) else None
    except Exception:
        raw_payload = None
    if _research_mode_binding_payload_is_current(
        raw_payload,
        default_agent_id=default_agent_id,
        active_agent_ids=active_agent_ids,
        flow_bindings=flow_bindings,
    ):
        return True
    try:
        payload = agent_mode_binding_service.repair_mode_bindings()
    except Exception:
        return False
    return _research_mode_binding_payload_is_current(
        payload,
        default_agent_id=default_agent_id,
        active_agent_ids=active_agent_ids,
        flow_bindings=flow_bindings,
    )


def _research_mode_binding_payload_is_current(
    payload: Any,
    *,
    default_agent_id: str,
    active_agent_ids: list[str],
    flow_bindings: dict[str, str],
) -> bool:
    if not isinstance(payload, dict):
        return False
    bindings = payload.get("bindings")
    if not isinstance(bindings, list):
        return False
    research_binding = next(
        (
            item
            for item in bindings
            if isinstance(item, dict) and str(item.get("mode") or "").strip() == "research"
        ),
        None,
    )
    if not research_binding:
        return False
    current_available_agent_ids = [
        str(item or "").strip()
        for item in list(research_binding.get("availableAgentIds") or [])
        if str(item or "").strip()
    ]
    return (
        str(research_binding.get("defaultAgentId") or "").strip() == str(default_agent_id or "").strip()
        and all(agent_id in current_available_agent_ids for agent_id in active_agent_ids)
        and [str(item or "").strip() for item in list(research_binding.get("pool") or []) if str(item or "").strip()] == active_agent_ids
        and {
            str(key or "").strip(): str(value or "").strip()
            for key, value in dict(research_binding.get("flowBindings") or {}).items()
            if str(key or "").strip() and str(value or "").strip()
        } == flow_bindings
    )


def _research_agent_storage_payload(config: dict[str, Any]) -> dict[str, Any]:
    """Persist the research Agent index without legacy model-binding names."""

    agents: list[dict[str, Any]] = []
    for item in list(config.get("agents") or []):
        if not isinstance(item, dict):
            continue
        record = dict(item)
        profile_id = str(record.get("profileId") or record.get("llmConfigId") or "").strip()
        record.pop("llmConfigId", None)
        if profile_id:
            record["profileId"] = profile_id
        agents.append(record)
    return {
        "schemaVersion": 1,
        "deletedDefaultAgents": sorted(str(item) for item in list(config.get("deletedDefaultAgents") or [])),
        "agents": agents,
    }


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
    profile_id: str | None = None,
    *,
    label: str = "",
    prompt_filename: str = "",
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Update a research Agent through the unified AgentInstance stack."""

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
    config = _load_research_agent_config()
    agents = config["agents"]
    deleted_default_agents = set(config.get("deletedDefaultAgents") or [])
    deleted_default_agents.discard(normalized)
    existing_agent = next((agent for agent in agents if agent["key"] == normalized), None)
    existing_agent_id = str((existing_agent or {}).get("agentId") or (existing_agent or {}).get("agentInstanceId") or "").strip()
    existing_instance = agent_directory_service.get_agent(existing_agent_id, include_archived=False) if existing_agent_id else None

    selected_profile_id = str(
        profile_id
        or (existing_instance or {}).get("profileId")
        or (existing_agent or {}).get("profileId")
        or (existing_agent or {}).get("llmConfigId")
        or RESEARCH_AGENT_DEFAULT_LLM_CONFIG.get(normalized)
        or "primary"
    ).strip()
    if selected_profile_id:
        known_llm_configs = {item["configId"] for item in _list_llm_config_options()}
        if selected_profile_id not in known_llm_configs:
            _record_research_config_event(
                "research.agent_binding.update_failed",
                phase="agent_template_config",
                message="Research agent template binding update failed",
                outcome="failed",
                level="error",
                fields={
                    "agentKey": normalized,
                    "templateId": selected_template,
                    "profileId": selected_profile_id,
                    "reason": "unknown_llm_config",
                    "errorType": "ValueError",
                    "message": f"Unknown research LLM config: {profile_id}",
                },
                agent_key=normalized,
            )
            raise ValueError(f"Unknown research LLM config: {profile_id}")
    if not selected_profile_id:
        raise ValueError("Research agent requires an LLM config.")
    prompt_file = normalize_research_prompt_filename(
        prompt_filename or str((existing_agent or {}).get("promptFilename") or "") or research_prompt_filename_for_key(normalized),
        normalized,
    )
    next_label = str(label or (existing_agent or {}).get("label") or normalized.replace("_", " ").title()).strip()
    if not next_label:
        next_label = normalized
    next_enabled = bool((existing_agent or {}).get("enabled", True)) if enabled is None else bool(enabled)
    workspace = get_workspace()
    prompt_path = workspace.get_research_prompt_path(prompt_file)
    if not prompt_path.exists():
        workspace.write_research_prompt(prompt_file, research_default_prompt(normalized))
    prompt_template_id = f"prompt-research-{normalized}"
    prompt_source_path = _relative_project_path(prompt_path)
    prompt_content = workspace.read_research_prompt(prompt_file)
    try:
        prompt_template_service.update_prompt_template(
            prompt_template_id,
            name=next_label,
            category="research",
            source_path=prompt_source_path,
            content=prompt_content,
            metadata={"roleKey": f"research_{normalized}", "researchAgentKey": normalized},
            status="active",
        )
    except Exception as exc:
        _record_research_config_event(
            "research.agent_binding.update_failed",
            phase="agent_template_config",
            message="Research agent template binding update failed",
            outcome="failed",
            level="error",
                fields={
                    "agentKey": normalized,
                    "templateId": selected_template,
                    "profileId": selected_profile_id,
                    "errorType": type(exc).__name__,
                    "message": str(exc),
                    "reason": "prompt_template_update_failed",
            },
            agent_key=normalized,
        )
        raise ValueError(f"Failed to update research prompt template: {exc}") from exc

    if existing_instance:
        agent_instance = agent_directory_service.update_agent_instance(
            existing_agent_id,
            display_name=next_label,
            llm_bindings=session_service.llm_bindings_for_profile_id(selected_profile_id),
            primary_mode="research",
            role_key=f"research_{normalized}",
            prompt_template_id=prompt_template_id,
            metadata={
                "researchAgentKey": normalized,
                "researchTemplateId": selected_template,
                "researchPromptFilename": prompt_file,
                "agentMode": "research",
                "configSurface": "agent_config",
            },
            status="active" if next_enabled else None,
            preserve_generated_display_name=True,
        )
    else:
        previous_session_root = session_service.PROJECT_ROOT
        previous_agent_root = agent_directory_service.PROJECT_ROOT
        project_root = _project_root_for_workspace(workspace)
        session_service.PROJECT_ROOT = project_root
        agent_directory_service.PROJECT_ROOT = project_root
        try:
            session_detail = session_service.create_chat_session(
                title=next_label,
                llm_bindings=session_service.llm_bindings_for_profile_id(selected_profile_id),
                created_by="research_agent_pool",
            )
            created_agent_id = str(session_detail.get("agentId") or "").strip()
            agent_instance = agent_directory_service.update_agent_instance(
                created_agent_id,
                display_name=next_label,
                llm_bindings=session_service.llm_bindings_for_profile_id(selected_profile_id),
                primary_mode="research",
                role_key=f"research_{normalized}",
                prompt_template_id=prompt_template_id,
                metadata={
                    "researchAgentKey": normalized,
                    "researchTemplateId": selected_template,
                    "researchPromptFilename": prompt_file,
                    "agentMode": "research",
                    "configSurface": "agent_config",
                },
                status="active" if next_enabled else None,
                preserve_generated_display_name=True,
            )
        finally:
            session_service.PROJECT_ROOT = previous_session_root
            agent_directory_service.PROJECT_ROOT = previous_agent_root

    updated = existing_agent is not None
    research_agent_record = {
        "key": normalized,
        "label": next_label,
        "promptFilename": prompt_file,
        "templateId": selected_template,
        "profileId": str(agent_instance.get("profileId") or selected_profile_id).strip(),
        "activationSource": "manual_config",
        "roleKey": f"research_{normalized}",
        "promptTemplateId": prompt_template_id,
        "enabled": next_enabled,
        "agentId": str(agent_instance.get("agentId") or "").strip(),
        "agentInstanceId": str(agent_instance.get("agentId") or "").strip(),
        "directSessionId": str(agent_instance.get("directSessionId") or "").strip(),
        "primaryMode": "research",
    }
    next_agents = [agent for agent in agents if str(agent.get("key") or "").strip() != normalized]
    next_agents.append(research_agent_record)
    next_agents.sort(key=lambda agent: str(agent.get("key") or ""))
    write_config = getattr(workspace, "write_research_agent_config", None)
    if callable(write_config):
        if not write_config(_research_agent_storage_payload({"deletedDefaultAgents": deleted_default_agents, "agents": next_agents})):
            _record_research_config_event(
                "research.agent_binding.update_failed",
                phase="agent_template_config",
                message="Research agent template binding update failed",
                outcome="failed",
                level="error",
                fields={
                    "agentKey": normalized,
                    "templateId": selected_template,
                    "profileId": selected_profile_id,
                    "errorType": "ValueError",
                    "message": "Failed to write research agent config.",
                },
                agent_key=normalized,
            )
            raise ValueError("Failed to write research agent config.")
    _sync_research_mode_binding(next_agents)
    _record_research_config_event(
        "research.agent_binding.updated",
        phase="agent_template_config",
        message="Research agent binding updated through AgentInstance",
        fields={
            "agentKey": normalized,
            "agentId": research_agent_record["agentId"],
            "roleKey": research_agent_record["roleKey"],
            "promptTemplateId": prompt_template_id,
            "profileId": research_agent_record["profileId"],
            "templateId": selected_template,
            "created": not updated,
            "source": "AgentInstance",
        },
        agent_key=normalized,
    )
    return list_research_prompts()


def delete_research_agent_binding(key: str) -> dict[str, Any]:
    normalized = normalize_research_agent_key(key)
    config = _load_research_agent_config()
    agents = config["agents"]
    removed_agent = next((agent for agent in agents if agent["key"] == normalized), None)
    remaining = [agent for agent in agents if agent["key"] != normalized]
    if len(remaining) == len(agents):
        raise ValueError(f"Unknown research agent key: {key}")
    agent_instance_id = str((removed_agent or {}).get("agentInstanceId") or (removed_agent or {}).get("agentId") or "").strip()
    canvas = _load_saved_research_flow_canvas_for_binding_guard()
    referencing_nodes = [
        str(node.get("id") or "")
        for node in canvas.get("nodes", [])
        if isinstance(node, dict)
        and (
            str(node.get("agentKey") or "").strip() == normalized
            or (
                agent_instance_id
                and str(node.get("agentId") or node.get("agentInstanceId") or "").strip() == agent_instance_id
            )
        )
    ]
    if referencing_nodes:
        _record_research_config_event(
            "research.agent_binding.delete_failed",
            phase="agent_template_config",
            message="Research agent binding delete failed",
            outcome="failed",
            level="error",
            fields={
                "agentKey": normalized,
                "agentId": agent_instance_id,
                "reason": "still_used_by_flow_nodes",
                "referencingNodeCount": len(referencing_nodes),
                "referencingNodes": referencing_nodes[:12],
            },
            agent_key=normalized,
        )
        raise ValueError(f"Research agent {normalized} is still used by flow nodes: {', '.join(referencing_nodes[:5])}")
    deleted_default_agents = set(config.get("deletedDefaultAgents") or [])
    if normalized in RESEARCH_PROMPT_FILES:
        deleted_default_agents.add(normalized)
    workspace = get_workspace()
    if not workspace.write_research_agent_config(_research_agent_storage_payload({"deletedDefaultAgents": deleted_default_agents, "agents": remaining})):
        raise ValueError("Failed to delete research agent config.")
    _remove_research_agent_from_mode_binding(normalized, agent_instance_id)
    if agent_instance_id:
        try:
            agent_directory_service.archive_agent_instance(agent_instance_id)
        except Exception as exc:
            _debug_logger.warning(f"Failed to archive research agent instance={agent_instance_id}. error={exc}")
    _record_research_config_event(
        "research.agent_binding.deleted",
        phase="agent_template_config",
        message="Research agent template binding deleted",
        fields={"agentKey": normalized},
        agent_key=normalized,
    )
    return list_research_prompts()


def _load_saved_research_flow_canvas_for_binding_guard() -> dict[str, Any]:
    workspace = get_workspace()
    try:
        raw = workspace.read_research_flow_canvas()
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        return {"nodes": []}
    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        return {"nodes": []}
    return {"nodes": [node for node in nodes if isinstance(node, dict)]}


def _get_saved_research_flow_canvas(*, sync_agent_instances: bool = True) -> dict[str, Any]:
    workspace = get_workspace()
    raw = workspace.read_research_flow_canvas()
    raw_agent_config = _load_research_agent_config()
    agent_config = _ensure_research_agent_instances(raw_agent_config) if sync_agent_instances else raw_agent_config
    canvas = _normalize_research_flow_canvas(
        _with_research_flow_agent_ids(
            _with_default_research_flow_canvas_migrations(raw or _default_research_flow_canvas()),
            agent_config,
        )
    )
    return _with_flow_canvas_validation({
        **canvas,
        "path": str(workspace.get_research_flow_canvas_path()),
    })


def get_research_flow_canvas(*, sync_agent_instances: bool = True) -> dict[str, Any]:
    workspace = get_workspace()
    canvas = _research_organization_flow_canvas()
    _record_research_config_event(
        "research.flow_canvas.organization_synced",
        phase="flow_canvas",
        message="Research flow canvas synced from organization graph",
        fields={
            "path": str(workspace.get_research_flow_canvas_path()),
            "organizationPath": str(canvas.get("organizationPath") or ""),
            "nodeCount": len(canvas.get("nodes") or []),
            "edgeCount": len(canvas.get("edges") or []),
            "canvasKind": canvas.get("canvasKind"),
            "locked": True,
        },
    )
    return _with_flow_canvas_validation({
        **canvas,
        "path": str(workspace.get_research_flow_canvas_path()),
    })


def save_research_flow_canvas(
    payload: dict[str, Any],
    *,
    record_event: bool = True,
    sync_agent_instances: bool = True,
) -> dict[str, Any]:
    workspace = get_workspace()
    agent_binding_stats: dict[str, int] = {}
    mode_binding_stats: dict[str, int] = {}
    try:
        raw_agent_config = _load_research_agent_config()
        agent_config = _ensure_research_agent_instances(raw_agent_config) if sync_agent_instances else raw_agent_config
        if isinstance(payload, dict) and str(payload.get("canvasKind") or "").strip() == _ORGANIZATION_CANVAS_KIND:
            raise ValueError("Research organization graph must be saved through /api/research/organization, not /api/research/flow-canvas.")
        canvas = _normalize_research_flow_canvas(
            _with_research_flow_agent_ids(payload, agent_config, stats=agent_binding_stats)
        )
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
    mode_binding_stats = _sync_research_flow_canvas_mode_binding(canvas, agent_config)
    if record_event:
        _record_research_config_event(
            "research.flow_canvas.updated",
            phase="flow_canvas",
            message="Research flow canvas updated",
            fields={
                "path": str(workspace.get_research_flow_canvas_path()),
                "organizationPath": str(research_organization_service.get_workspace().get_research_organization_path()),
                "nodeCount": len(canvas["nodes"]),
                "edgeCount": len(canvas["edges"]),
                "agentBindingResolvedCount": int(agent_binding_stats.get("resolvedCount") or 0),
                "flowBindingSyncCount": int(mode_binding_stats.get("updatedCount") or 0),
                "locked": True,
                "source": "team",
                "organizationSource": "research_organization",
                "teamId": str((canvas.get("projectBinding") or {}).get("teamId") or "research-team")
                if isinstance(canvas.get("projectBinding"), dict)
                else "research-team",
                "lockedSaveReceived": True,
                "layoutOverriddenByOrganization": True,
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
    canvas = _get_saved_research_flow_canvas(sync_agent_instances=False)
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

    latest_canvas = _get_saved_research_flow_canvas(sync_agent_instances=False)
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
        canvas = _get_saved_research_flow_canvas(sync_agent_instances=False)
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
    except Exception as exc:
        _debug_logger.warning(f"Failed to sync research flow canvas status from payload. error={exc}")
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
    except Exception as exc:
        _debug_logger.warning(f"Failed to record research flow sync event. error={exc}")
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


def _flow_node_binding_key(node: dict[str, Any]) -> str:
    node_id = _safe_token(node.get("id"), default="")
    if node_id and node_id not in _FLOW_NODE_ACTION_ALIASES:
        return node_id
    return _flow_node_action_key(node)


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
            "canvasKind": base_canvas.get("canvasKind", _FLOW_CANVAS_KIND),
            "viewport": base_canvas.get("viewport") or {},
            "nodes": nodes,
            "edges": edges,
        },
        record_event=False,
        sync_agent_instances=False,
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
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to record research capability transition event session_id={session_id}, action={action_key}. error={exc}"
        )


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
    except Exception as exc:
        _debug_logger.warning(f"Failed to append research capability event to repository. event_code={event_code}. error={exc}")
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
    except Exception as exc:
        _debug_logger.warning(f"Failed to record research capability scene event. event_code={event_code}. error={exc}")


def _with_default_research_flow_canvas_migrations(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        return _default_research_flow_canvas()
    nodes = raw.get("nodes")
    edges = raw.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return raw
    canvas_kind = str(raw.get("canvasKind") or "").strip()
    if canvas_kind == _ORGANIZATION_CANVAS_KIND:
        return _default_research_flow_canvas()
    if canvas_kind == _FLOW_CANVAS_KIND:
        return raw

    normalized_nodes = [dict(node) for node in nodes if isinstance(node, dict)]
    normalized_edges = [dict(edge) for edge in edges if isinstance(edge, dict)]
    if _looks_like_legacy_default_research_flow_canvas(normalized_nodes) or any(
        str(node.get("type") or "agent").strip() != "agent" for node in normalized_nodes
    ):
        return {**raw, "canvasKind": _FLOW_CANVAS_KIND, "nodes": normalized_nodes, "edges": normalized_edges}
    organization_edge_markers = {"message", "report", "advice", "delegate", "observe"}
    organization_edge_types = {"reporting", "advisory", "collaboration", "delegation", "observation"}
    if any(
        str(edge.get("condition") or "").strip() in organization_edge_markers
        or str(edge.get("type") or "").strip() in organization_edge_types
        for edge in normalized_edges
    ):
        return _default_research_flow_canvas()
    if len(normalized_nodes) == 1 or normalized_edges:
        return {**raw, "canvasKind": _FLOW_CANVAS_KIND, "nodes": normalized_nodes, "edges": normalized_edges}
    return _default_research_flow_canvas()


def _looks_like_legacy_default_research_flow_canvas(nodes: list[dict[str, Any]]) -> bool:
    node_ids = {str(node.get("id") or "") for node in nodes}
    return {
        "broad_search",
        "knowledge_store",
        "knowledge_lookup",
        "deep_search",
        "literature_project_parse",
        "semantic_cluster",
        "novelty_reverse_check",
        "evidence_review",
        "theme_generation",
        "human_choice",
        "theme_card",
    }.issubset(node_ids)


def _with_research_flow_agent_ids(
    raw: dict[str, Any],
    agent_config: dict[str, Any] | None = None,
    *,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return raw
    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        return raw
    config = agent_config if isinstance(agent_config, dict) else _load_research_agent_config()
    by_key: dict[str, dict[str, Any]] = {}
    by_agent_id: dict[str, dict[str, Any]] = {}
    for agent in config.get("agents", []):
        if not isinstance(agent, dict):
            continue
        key = str(agent.get("key") or "").strip()
        agent_id = str(agent.get("agentId") or agent.get("agentInstanceId") or "").strip()
        if key and agent_id:
            by_key[key] = agent
            by_agent_id[agent_id] = agent
    research_binding = _read_research_mode_binding_for_workspace()
    flow_bindings = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in dict(research_binding.get("flowBindings") or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    if not by_key and not flow_bindings:
        return raw
    migrated_nodes: list[dict[str, Any]] = []
    changed = False
    resolved_count = 0
    for node in nodes:
        if not isinstance(node, dict):
            migrated_nodes.append(node)
            continue
        next_node = dict(node)
        agent_key = str(next_node.get("agentKey") or "").strip()
        prompt_key = str(next_node.get("promptKey") or "").strip()
        action_key = _flow_node_action_key(next_node)
        binding_key = _flow_node_binding_key(next_node)
        agent_id = str(next_node.get("agentId") or next_node.get("agentInstanceId") or "").strip()
        if not agent_id:
            for candidate_key in (binding_key, action_key, agent_key, prompt_key):
                if not candidate_key:
                    continue
                agent_id = flow_bindings.get(candidate_key) or str(
                    (by_key.get(candidate_key) or {}).get("agentId")
                    or (by_key.get(candidate_key) or {}).get("agentInstanceId")
                    or ""
                ).strip()
                if agent_id:
                    next_node["agentId"] = agent_id
                    changed = True
                    resolved_count += 1
                    break
        agent_record = by_agent_id.get(agent_id)
        if agent_record:
            record_key = str(agent_record.get("key") or "").strip()
            if record_key and not agent_key:
                next_node["agentKey"] = record_key
                changed = True
                resolved_count += 1
            if record_key and not prompt_key:
                next_node["promptKey"] = record_key
                changed = True
                resolved_count += 1
        migrated_nodes.append(next_node)
    if stats is not None:
        stats["resolvedCount"] = int(stats.get("resolvedCount") or 0) + resolved_count
    if not changed:
        return raw
    return {**raw, "nodes": migrated_nodes}


def _sync_research_flow_canvas_mode_binding(canvas: dict[str, Any], agent_config: dict[str, Any]) -> dict[str, int]:
    research_binding = _read_research_mode_binding_for_workspace()
    flow_bindings = dict(research_binding.get("flowBindings") or {})
    active_agent_ids: list[str] = []
    for agent in agent_config.get("agents", []):
        if not isinstance(agent, dict) or agent.get("enabled") is False:
            continue
        agent_id = str(agent.get("agentId") or agent.get("agentInstanceId") or "").strip()
        if agent_id:
            active_agent_ids.append(agent_id)
    updated_count = 0
    for node in canvas.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        action_key = _flow_node_binding_key(node)
        agent_id = str(node.get("agentId") or node.get("agentInstanceId") or "").strip()
        if not action_key or not agent_id:
            continue
        if str(flow_bindings.get(action_key) or "").strip() != agent_id:
            flow_bindings[action_key] = agent_id
            updated_count += 1
        active_agent_ids.append(agent_id)
    if updated_count <= 0:
        return {"updatedCount": 0}
    available_agent_ids = _dedupe_research_agent_ids(
        [
            *list(research_binding.get("availableAgentIds") or []),
            *list(research_binding.get("pool") or []),
            *active_agent_ids,
        ]
    )
    if not available_agent_ids:
        return {"updatedCount": updated_count}
    default_agent_id = str(research_binding.get("defaultAgentId") or "").strip()
    if default_agent_id not in available_agent_ids:
        default_agent_id = available_agent_ids[0]
    try:
        _update_research_mode_binding_for_workspace(
            default_agent_id=default_agent_id,
            available_agent_ids=available_agent_ids,
            pool=_dedupe_research_agent_ids([*list(research_binding.get("pool") or []), *active_agent_ids]),
            flow_bindings=flow_bindings,
        )
    except Exception as exc:
        _record_research_config_event(
            "research.flow_canvas.mode_binding_sync_failed",
            phase="flow_canvas",
            message="Research flow canvas mode binding sync failed",
            outcome="failed",
            level="warning",
            fields={
                "updatedCount": updated_count,
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
        return {"updatedCount": 0}
    return {"updatedCount": updated_count}


def _read_research_mode_binding_for_workspace() -> dict[str, Any]:
    workspace = get_workspace()
    project_root = _project_root_for_workspace(workspace)
    previous_agent_root = agent_directory_service.PROJECT_ROOT
    previous_binding_root = agent_mode_binding_service.PROJECT_ROOT
    agent_directory_service.PROJECT_ROOT = project_root
    agent_mode_binding_service.PROJECT_ROOT = project_root
    try:
        load_bindings = getattr(agent_mode_binding_service, "_load_mode_bindings", None)
        payload = load_bindings() if callable(load_bindings) else {}
        bindings = payload.get("bindings") if isinstance(payload, dict) else []
        if isinstance(bindings, list):
            for item in bindings:
                if isinstance(item, dict) and str(item.get("mode") or "").strip() == "research":
                    return dict(item)
        payload = agent_mode_binding_service.get_mode_bindings_payload()
        modes = payload.get("modes") if isinstance(payload.get("modes"), dict) else {}
        research = modes.get("research") if isinstance(modes.get("research"), dict) else {}
        return dict(research)
    except Exception:
        return {}
    finally:
        agent_directory_service.PROJECT_ROOT = previous_agent_root
        agent_mode_binding_service.PROJECT_ROOT = previous_binding_root


def _update_research_mode_binding_for_workspace(
    *,
    default_agent_id: str,
    available_agent_ids: list[str],
    pool: list[str],
    flow_bindings: dict[str, str],
) -> None:
    workspace = get_workspace()
    project_root = _project_root_for_workspace(workspace)
    previous_agent_root = agent_directory_service.PROJECT_ROOT
    previous_binding_root = agent_mode_binding_service.PROJECT_ROOT
    agent_directory_service.PROJECT_ROOT = project_root
    agent_mode_binding_service.PROJECT_ROOT = project_root
    try:
        agent_mode_binding_service.update_mode_binding(
            "research",
            default_agent_id=default_agent_id,
            available_agent_ids=available_agent_ids,
            pool=pool,
            flow_bindings=flow_bindings,
        )
    finally:
        agent_directory_service.PROJECT_ROOT = previous_agent_root
        agent_mode_binding_service.PROJECT_ROOT = previous_binding_root


def _remove_research_agent_from_mode_binding(agent_key: str, agent_id: str) -> None:
    research_binding = _read_research_mode_binding_for_workspace()
    normalized_key = str(agent_key or "").strip()
    removed_agent_id = str(agent_id or "").strip()
    if not research_binding or (not normalized_key and not removed_agent_id):
        return
    flow_bindings = {
        key: value
        for key, value in dict(research_binding.get("flowBindings") or {}).items()
        if str(key or "").strip() != normalized_key and (not removed_agent_id or str(value or "").strip() != removed_agent_id)
    }
    available_agent_ids = [
        value for value in list(research_binding.get("availableAgentIds") or [])
        if not removed_agent_id or str(value or "").strip() != removed_agent_id
    ]
    pool = [
        value for value in list(research_binding.get("pool") or [])
        if not removed_agent_id or str(value or "").strip() != removed_agent_id
    ]
    default_agent_id = str(research_binding.get("defaultAgentId") or "").strip()
    if removed_agent_id and default_agent_id == removed_agent_id:
        default_agent_id = available_agent_ids[0] if available_agent_ids else ""
    try:
        _update_research_mode_binding_for_workspace(
            default_agent_id=default_agent_id,
            available_agent_ids=_dedupe_research_agent_ids(available_agent_ids),
            pool=_dedupe_research_agent_ids(pool),
            flow_bindings=flow_bindings,
        )
    except Exception as exc:
        _record_research_config_event(
            "research.mode_binding.delete_sync_failed",
            phase="agent_template_config",
            message="Research mode binding delete sync failed",
            outcome="failed",
            level="warning",
            fields={
                "agentKey": normalized_key,
                "agentId": removed_agent_id,
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
            agent_key=normalized_key,
        )


def _dedupe_research_agent_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        agent_id = str(value or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        deduped.append(agent_id)
    return deduped


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
    canvas_kind = _safe_text(raw.get("canvasKind"), default=_FLOW_CANVAS_KIND, max_length=80)
    if canvas_kind != _FLOW_CANVAS_KIND:
        canvas_kind = _FLOW_CANVAS_KIND
    normalized_edges = [
        _normalize_flow_canvas_edge(item, index, node_ids, canvas_kind=canvas_kind)
        for index, item in enumerate(edges[:160])
    ]
    viewport = raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {}
    return {
        "schemaVersion": 1,
        "canvasKind": canvas_kind,
        "updatedAt": str(raw.get("updatedAt") or _utc_now()),
        **({"organizationPath": str(raw.get("organizationPath") or "")} if raw.get("organizationPath") else {}),
        **({"projectBinding": raw.get("projectBinding")} if isinstance(raw.get("projectBinding"), dict) else {}),
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
        "label": _safe_text(item.get("label"), default=f"Agent {index + 1}", max_length=80),
        "type": node_type if node_type in _FLOW_CANVAS_NODE_TYPES else "agent",
        "status": status if status in _FLOW_CANVAS_STATUSES else "idle",
        "x": _safe_number(item.get("x"), 80 + index * 220),
        "y": _safe_number(item.get("y"), 120),
        "agentId": _safe_text(item.get("agentId") or item.get("agentInstanceId"), max_length=128),
        "agentKey": _safe_text(item.get("agentKey"), max_length=64),
        "promptKey": _safe_text(item.get("promptKey"), max_length=64),
        "llmConfigId": "",
        "description": _safe_text(item.get("description"), max_length=1200),
        "routeCondition": _safe_text(item.get("routeCondition"), max_length=600),
    }


def _normalize_flow_canvas_edge(
    item: Any,
    index: int,
    node_ids: set[str],
    *,
    canvas_kind: str = _FLOW_CANVAS_KIND,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Research flow canvas edge must be an object.")
    source = _safe_token(item.get("source"), default="")
    target = _safe_token(item.get("target"), default="")
    if source not in node_ids or target not in node_ids:
        raise ValueError("Research flow canvas edge must reference existing nodes.")
    default_condition = "completed"
    condition = _safe_token(item.get("condition"), default=default_condition)
    if condition not in _FLOW_CANVAS_EDGE_CONDITIONS:
        condition = default_condition
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
    if normalized == "approved":
        return "approval_gate"
    if normalized == "needs_evidence":
        return "evidence_loop"
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
    organization_locked = (
        isinstance(canvas.get("projectBinding"), dict)
        and canvas["projectBinding"].get("locked") is True
        and canvas["projectBinding"].get("organizationSource") == "research_organization"
    )
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
        if organization_locked:
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

    if organization_locked:
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
    return f"Research organization canvas contains mojibake text{suffix}; reload the canvas from UTF-8 source before saving."


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


def _relative_project_path(path: Path) -> str:
    workspace = get_workspace()
    project_root = _project_root_for_workspace(workspace)
    try:
        return Path(path).resolve().relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def _project_root_for_workspace(workspace: Any) -> Path:
    explicit = getattr(workspace, "project_root", None)
    if explicit:
        return Path(explicit).resolve()
    root = Path(getattr(workspace, "root", session_service.PROJECT_ROOT)).resolve()
    return root.parent if root.name == "workspace" else root


def _load_research_agent_config() -> dict[str, Any]:
    workspace = get_workspace()
    read_config = getattr(workspace, "read_research_agent_config", None)
    raw = read_config() if callable(read_config) else {}
    config = normalize_research_agent_config(raw)
    get_config_path = getattr(workspace, "get_research_agent_config_path", None)
    config_path = get_config_path() if callable(get_config_path) else ""
    return {
        **config,
        "configPath": str(config_path),
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
    except Exception as exc:
        _debug_logger.warning(f"Failed to record research scene event generic for code={event_code}. error={exc}")
