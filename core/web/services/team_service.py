"""Team registry and organization canvas service."""

from __future__ import annotations

import json
import re
import shutil
import threading
from html.parser import HTMLParser
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx

from core.chat.chat_task_types import trim_lines
from core.infrastructure import developer_sandbox

from . import agent_directory_service, chat_room_service, project_agent_bus_service
from .runtime_scene_service import record_runtime_scene_event
from .team_conversation_contract import build_team_conversation_projection
from core.logging.logger import debug as _debug_logger


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
CANVAS_KIND = "team_organization_canvas"
RESEARCH_TEAM_DISPLAY_NAME = "挑战杯ai科研团队"
AI_SEARCH_TEAM_ID = "ai-search-team"
AI_SEARCH_TEAM_DISPLAY_NAME = "AI 搜索范围团队"
KNOWLEDGE_EXPANSION_TEAM_ID = "knowledge-expansion-team"
KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME = "知识库内容扩充团队"
DEFAULT_TEAM_STATUS = "active"
TEAM_STATUSES = {"active", "archived"}
NODE_TYPES = {"role", "agent", "group", "user", "external"}
EDGE_TYPES = {"reports_to", "communication", "collaborates_with", "delegates_to", "observes", "supports"}
_TEAM_LOCK = threading.RLock()
_TEAM_SYSTEM_BOOTSTRAP_LOCK = threading.Lock()
_TEAM_SYSTEM_BOOTSTRAP_THREAD: threading.Thread | None = None
_TEAM_SYSTEM_BOOTSTRAP_STATE: dict[str, Any] = {
    "schemaVersion": SCHEMA_VERSION,
    "status": "idle",
    "requiredSteps": [],
    "reason": "",
    "startedAt": "",
    "finishedAt": "",
    "lastError": "",
    "elapsedMs": 0,
    "attempt": 0,
}
_TEAM_DETAIL_LOG_LOCK = threading.Lock()
_TEAM_DETAIL_LOG_STATE: dict[str, dict[str, Any]] = {}
TEAM_DETAIL_LOG_SLOW_THRESHOLD_MS = 250
TEAM_DETAIL_LOG_ROLLUP_REPEAT_THRESHOLD = 5
TEAM_DETAIL_LOG_ROLLUP_WINDOW_SECONDS = 5.0
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
AI_SEARCH_SOURCE_PAGE_TIMEOUT_SECONDS = 8.0
AI_SEARCH_SOURCE_PAGE_MAX_BYTES = 400_000
AI_SEARCH_SOURCE_PAGE_USER_AGENT = "Vibelution-AI-Search/1.0"
EVOLUTION_SYSTEM_TEAM_IDS = {"self-evolution-team", "supervised-evolution-team"}
EVOLUTION_SYSTEM_TEAM_SPECS = (
    {
        "teamId": "self-evolution-team",
        "name": "自进化团队",
        "description": "由自进化固定角色自动同步的系统团队。",
        "purpose": "承接自进化执行、评审与总结角色的团队通讯。",
        "source": "self_evolution",
        "teamKind": "self_evolution",
        "teamCategory": "自进化系统团队",
        "teamSource": "self_evolution",
        "chatRoomPurpose": "self_evolution",
    },
    {
        "teamId": "supervised-evolution-team",
        "name": "监督进化团队",
        "description": "由监督进化固定角色自动同步的系统团队。",
        "purpose": "承接监督进化基线、候选、评审、审计与裁决角色的团队通讯。",
        "source": "supervised_evolution",
        "teamKind": "supervised_evolution",
        "teamCategory": "监督进化系统团队",
        "teamSource": "supervised_evolution",
        "chatRoomPurpose": "supervised_evolution",
    },
)
TEAM_KIND_DEFAULTS = {
    "custom": {"teamCategory": "自定义团队", "teamSource": "manual", "chatRoomPurpose": "discussion"},
    "research": {"teamCategory": "科研组织团队", "teamSource": "research_organization", "chatRoomPurpose": "research_coordination"},
    "knowledge_expansion": {"teamCategory": "知识库扩充团队", "teamSource": "knowledge_expansion", "chatRoomPurpose": "knowledge_expansion"},
    "ai_search": {"teamCategory": "AI 搜索系统团队", "teamSource": "ai_search", "chatRoomPurpose": "ai_search"},
    "self_evolution": {"teamCategory": "自进化系统团队", "teamSource": "self_evolution", "chatRoomPurpose": "self_evolution"},
    "supervised_evolution": {"teamCategory": "监督进化系统团队", "teamSource": "supervised_evolution", "chatRoomPurpose": "supervised_evolution"},
    "template_demo": {"teamCategory": "演示业务团队", "teamSource": "team_template", "chatRoomPurpose": "meeting"},
}
TEAM_SOURCE_TO_KIND = {
    "manual": "custom",
    "research_organization": "research",
    "knowledge_expansion": "knowledge_expansion",
    "ai_search": "ai_search",
    "self_evolution": "self_evolution",
    "supervised_evolution": "supervised_evolution",
    "team_template": "template_demo",
}
TEAM_ID_TO_KIND = {
    "research-team": "research",
    KNOWLEDGE_EXPANSION_TEAM_ID: "knowledge_expansion",
    AI_SEARCH_TEAM_ID: "ai_search",
    "self-evolution-team": "self_evolution",
    "supervised-evolution-team": "supervised_evolution",
}
RESEARCH_TEAM_MEMBER_ROLE_KEYS = {
    "research_coordination": "challenge_cup_coordinator",
    "data_discovery": "challenge_cup_data_discovery",
    "source_acquisition": "challenge_cup_source_acquisition",
    "content_extraction": "challenge_cup_content_extraction",
    "source_quality": "challenge_cup_source_quality",
    "candidate_graph": "candidate_graph",
    "experiment_planner": "challenge_cup_experiment_planner",
    "experiment_ledger": "challenge_cup_experiment_ledger",
    "iteration_planner": "challenge_cup_iteration_planner",
    "iteration_versioning": "challenge_cup_versioning",
    "knowledge_steward": "knowledge_steward",
}
CHALLENGE_CUP_RESEARCH_TEAM_ID = "research-team"
CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY = "challenge_cup_team"
CHALLENGE_CUP_RESEARCH_TEAM_ROLES: tuple[dict[str, Any], ...] = (
    {
        "role": "research_coordination",
        "roleKey": "challenge_cup_coordinator",
        "label": "科研协调",
        "purpose": "阶段调度与分工",
        "responsibilities": ["判断当前阶段", "组织返工转移", "把任务交接给功能 Agent"],
    },
    {
        "role": "data_discovery",
        "roleKey": "challenge_cup_data_discovery",
        "label": "资料发现",
        "purpose": "搜索问题与来源范围",
        "responsibilities": ["生成检索问题", "发现公开资料线索", "标注来源缺口"],
    },
    {
        "role": "source_acquisition",
        "roleKey": "challenge_cup_source_acquisition",
        "label": "来源获取",
        "purpose": "网页、论文和数据集元信息",
        "responsibilities": ["打开可验证来源", "记录 DOI/URL/来源元数据", "把可读来源交给提炼"],
    },
    {
        "role": "content_extraction",
        "roleKey": "challenge_cup_content_extraction",
        "label": "内容提炼",
        "purpose": "摘要、页码与证据片段",
        "responsibilities": ["提炼证据片段", "生成候选摘要", "标注页码和引用锚点"],
    },
    {
        "role": "source_quality",
        "roleKey": "challenge_cup_source_quality",
        "label": "资料质量评估",
        "purpose": "筛选、复审与退回",
        "responsibilities": ["审查候选资料", "判断通过或退回", "整理补资料要求"],
    },
    {
        "role": "candidate_graph",
        "roleKey": "candidate_graph",
        "label": "资料关系生成",
        "purpose": "入库关系与断链预览",
        "responsibilities": ["生成候选关系", "标注断链缺口", "预览图谱边界"],
    },
    {
        "role": "experiment_planner",
        "roleKey": "challenge_cup_experiment_planner",
        "label": "实验规划",
        "purpose": "实验计划账本",
        "responsibilities": ["生成实验计划草稿", "对齐 dataset/metric/baseline", "标注 smoke gate 和人工门禁"],
    },
    {
        "role": "experiment_ledger",
        "roleKey": "challenge_cup_experiment_ledger",
        "label": "实验证据",
        "purpose": "实验结果证据登记",
        "responsibilities": ["登记 baseline 工件", "登记 smoke/full-run 结果", "整理实验结果入库申请"],
    },
    {
        "role": "iteration_planner",
        "roleKey": "challenge_cup_iteration_planner",
        "label": "迭代决策",
        "purpose": "Research Loop 决策账本",
        "responsibilities": ["创建 Research Loop", "登记迭代证据", "生成下一轮修复/接受/归档决策"],
    },
    {
        "role": "iteration_versioning",
        "roleKey": "challenge_cup_versioning",
        "label": "版本治理",
        "purpose": "候选版本与拒绝归档",
        "responsibilities": ["维护 versionHistory", "记录 supersedes/derived_from", "归档 rejectionArchive"],
    },
    {
        "role": "knowledge_steward",
        "roleKey": "knowledge_steward",
        "label": "知识库管理员",
        "purpose": "知识库管理员入库审核",
        "responsibilities": ["审查入库门槛", "接收入库审核请求", "防止未审资料进入正式知识"],
    },
)
KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY = "knowledge_expansion_team"
KNOWLEDGE_EXPANSION_TEAM_ROLES: tuple[dict[str, Any], ...] = (
    {
        "role": "source_intake",
        "roleKey": "knowledge_expansion_source_intake",
        "label": "资料发现与导入",
        "purpose": "本地资料导入与网络资料发现",
        "responsibilities": ["扫描本地知识资料", "搜索公开资料线索", "把来源写回受控资料批次"],
    },
    {
        "role": "content_extraction",
        "roleKey": "knowledge_expansion_content_extraction",
        "label": "资料提炼",
        "purpose": "摘要、证据片段与候选资料提炼",
        "responsibilities": ["提炼可入库摘要", "标注证据引用", "把结构化结果写回团队批次"],
    },
    {
        "role": "source_quality",
        "roleKey": "knowledge_expansion_source_quality",
        "label": "资料质检",
        "purpose": "可信度、完整性与入库风险审查",
        "responsibilities": ["判断资料是否通过", "标注风险和缺口", "退回低质量来源"],
    },
    {
        "role": "candidate_graph",
        "roleKey": "knowledge_expansion_candidate_graph",
        "label": "候选关系生成",
        "purpose": "候选知识关系预览",
        "responsibilities": ["生成候选关系", "检查断链", "保持正式图谱写入边界"],
    },
    {
        "role": "knowledge_steward",
        "roleKey": "knowledge_steward",
        "label": "知识库管理员",
        "purpose": "入库审核与正式 Team Knowledge 写入",
        "responsibilities": ["复核高置信资料", "执行正式知识库入库", "拒绝低置信或缺证据资料"],
    },
)
TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID = {
    "medical-demo": "medical-consultation-demo",
    "heletech-demo": "heletech-maternal-digital-health-demo",
}
AI_SEARCH_SYSTEM_ROLES: tuple[dict[str, Any], ...] = (
    {
        "role": "ai_search_scope_lead",
        "label": "搜索范围负责人",
        "purpose": "维护搜索边界、可信度分层和默认启用规则。",
        "responsibilities": ["维护白名单边界", "定义 Tier 规则", "决定默认启用范围"],
        "expertise": ["搜索范围治理", "可信来源分层", "一键搜索策略"],
    },
    {
        "role": "global_primary_sources",
        "label": "全球官方源维护",
        "purpose": "维护 OpenAI、Anthropic、Google DeepMind、Meta、Microsoft、NVIDIA 等全球一手源。",
        "responsibilities": ["维护全球官方入口", "识别模型与产品更新", "保留一手证据链接"],
        "expertise": ["全球 AI 实验室", "官方博客", "研究公告"],
    },
    {
        "role": "cn_primary_sources",
        "label": "中国 AI 源维护",
        "purpose": "维护 DeepSeek、通义、智谱、Kimi、文心、豆包、腾讯混元等中国主流 AI 源。",
        "responsibilities": ["维护中文官方入口", "跟踪国产模型更新", "标注语言与地区覆盖"],
        "expertise": ["中国 AI 生态", "中文官方源", "模型平台动态"],
    },
    {
        "role": "signal_quality_gate",
        "label": "信号源质检",
        "purpose": "管理新闻、社区和社交信号，要求所有信号回链到一手证据后再进入结论。",
        "responsibilities": ["社区信号去噪", "新闻源可信度标注", "要求一手源回链"],
        "expertise": ["来源质检", "去重", "证据回链"],
    },
)
AI_SEARCH_SOURCE_SCOPE_SCHEMA_VERSION = 1
AI_SEARCH_SOURCE_SCOPE_CURATED_AT = "2026-06-11"
AI_SEARCH_SOURCE_SCOPE_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "groupId": "global_official",
        "label": "全球官方源",
        "tier": "tier1",
        "evidenceRole": "primary",
        "enabledByDefault": True,
        "ownerRole": "global_primary_sources",
        "description": "全球主流 AI 实验室、模型平台和基础设施厂商的一手公告入口。",
        "sources": (
            {"sourceId": "openai_news", "name": "OpenAI News", "url": "https://openai.com/news/", "region": "global", "language": "en", "sourceType": "official_news", "tags": ("model", "product", "research", "safety")},
            {"sourceId": "anthropic_news", "name": "Anthropic News", "url": "https://www.anthropic.com/news", "region": "global", "language": "en", "sourceType": "official_news", "tags": ("model", "product", "safety", "policy")},
            {"sourceId": "google_deepmind_blog", "name": "Google DeepMind Blog", "url": "https://deepmind.google/blog/", "region": "global", "language": "en", "sourceType": "official_blog", "tags": ("research", "model", "science")},
            {"sourceId": "google_ai_updates", "name": "Google AI Updates", "url": "https://blog.google/innovation-and-ai/technology/ai/", "region": "global", "language": "en", "sourceType": "official_news", "tags": ("product", "model", "developer")},
            {"sourceId": "meta_ai_blog", "name": "AI at Meta Blog", "url": "https://ai.meta.com/blog/", "region": "global", "language": "en", "sourceType": "official_blog", "tags": ("llama", "research", "product")},
            {"sourceId": "microsoft_ai_blog", "name": "Microsoft AI Blog", "url": "https://microsoft.ai/blog/", "region": "global", "language": "en", "sourceType": "official_blog", "tags": ("copilot", "agent", "platform")},
            {"sourceId": "nvidia_ai_blog", "name": "NVIDIA AI Blog", "url": "https://blogs.nvidia.com/blog/category/generative-ai/", "region": "global", "language": "en", "sourceType": "official_blog", "tags": ("infrastructure", "model", "agent")},
            {"sourceId": "huggingface_blog", "name": "Hugging Face Blog", "url": "https://huggingface.co/blog", "region": "global", "language": "en", "sourceType": "platform_blog", "tags": ("open_source", "model", "dataset")},
            {"sourceId": "mistral_news", "name": "Mistral AI News", "url": "https://mistral.ai/news/", "region": "eu", "language": "en", "sourceType": "official_news", "tags": ("model", "product", "enterprise")},
            {"sourceId": "xai_news", "name": "xAI News", "url": "https://x.ai/news", "region": "global", "language": "en", "sourceType": "official_news", "tags": ("model", "product")},
            {"sourceId": "cohere_blog", "name": "Cohere Blog", "url": "https://cohere.com/blog", "region": "global", "language": "en", "sourceType": "official_blog", "tags": ("enterprise", "model", "research")},
            {"sourceId": "stability_news", "name": "Stability AI News", "url": "https://stability.ai/news-updates", "region": "global", "language": "en", "sourceType": "official_news", "tags": ("image", "audio", "open_model")},
        ),
    },
    {
        "groupId": "cn_official",
        "label": "中国官方源",
        "tier": "tier1",
        "evidenceRole": "primary",
        "enabledByDefault": True,
        "ownerRole": "cn_primary_sources",
        "description": "中国主流大模型厂商、实验室和模型平台的一手公告入口。",
        "sources": (
            {"sourceId": "deepseek_api_updates", "name": "DeepSeek API Updates", "url": "https://api-docs.deepseek.com/updates", "region": "cn", "language": "en", "sourceType": "official_changelog", "tags": ("model", "api", "developer")},
            {"sourceId": "deepseek_home", "name": "DeepSeek", "url": "https://www.deepseek.com/en/", "region": "cn", "language": "en", "sourceType": "official_site", "tags": ("model", "research")},
            {"sourceId": "qwen_blog", "name": "Qwen Blog", "url": "https://qwen.ai/blog", "region": "cn", "language": "en", "sourceType": "official_blog", "tags": ("model", "open_source", "developer")},
            {"sourceId": "tongyi_lab", "name": "通义实验室", "url": "https://tongyi.aliyun.com/", "region": "cn", "language": "zh", "sourceType": "official_site", "tags": ("qwen", "model", "product")},
            {"sourceId": "zhipu_news", "name": "智谱 AI 新闻", "url": "https://www.zhipuai.cn/en/news?tab=2", "region": "cn", "language": "zh", "sourceType": "official_news", "tags": ("glm", "product", "ecosystem")},
            {"sourceId": "moonshot_blog", "name": "Moonshot AI / Kimi Blog", "url": "https://platform.kimi.ai/blog", "region": "cn", "language": "en", "sourceType": "official_blog", "tags": ("kimi", "model", "api")},
            {"sourceId": "bytedance_seed_blog", "name": "ByteDance Seed Blog", "url": "https://seed.bytedance.com/zh/blog", "region": "cn", "language": "zh", "sourceType": "official_blog", "tags": ("model", "research", "multimodal")},
            {"sourceId": "volcengine_doubao", "name": "豆包大模型", "url": "https://www.volcengine.com/product/doubao", "region": "cn", "language": "zh", "sourceType": "official_product", "tags": ("doubao", "model", "platform")},
            {"sourceId": "tencent_hunyuan", "name": "Tencent Hunyuan Research", "url": "https://hy.tencent.com/", "region": "cn", "language": "zh", "sourceType": "official_site", "tags": ("hunyuan", "model", "research")},
            {"sourceId": "baidu_wenxin", "name": "文心", "url": "https://wenxin.baidu.com/", "region": "cn", "language": "zh", "sourceType": "official_product", "tags": ("ernie", "product", "model")},
            {"sourceId": "minimax_news", "name": "MiniMax News", "url": "https://www.minimax.io/news", "region": "cn", "language": "en", "sourceType": "official_news", "tags": ("model", "multimodal", "product")},
        ),
    },
    {
        "groupId": "trusted_indices",
        "label": "可信研究与新闻索引",
        "tier": "tier2",
        "evidenceRole": "secondary",
        "enabledByDefault": True,
        "ownerRole": "signal_quality_gate",
        "description": "用于补充发现论文、开源模型和产业动态；结论仍需回链 Tier1 或论文原文。",
        "sources": (
            {"sourceId": "arxiv_cs_ai_recent", "name": "arXiv cs.AI Recent", "url": "https://arxiv.org/list/cs.AI/recent", "region": "global", "language": "en", "sourceType": "paper_index", "tags": ("paper", "research")},
            {"sourceId": "arxiv_cs_cl_recent", "name": "arXiv cs.CL Recent", "url": "https://arxiv.org/list/cs.CL/recent", "region": "global", "language": "en", "sourceType": "paper_index", "tags": ("paper", "language_model")},
            {"sourceId": "huggingface_papers", "name": "Hugging Face Papers", "url": "https://huggingface.co/papers", "region": "global", "language": "en", "sourceType": "paper_index", "tags": ("paper", "model", "community")},
            {"sourceId": "papers_with_code", "name": "Papers with Code", "url": "https://paperswithcode.com/", "region": "global", "language": "en", "sourceType": "paper_index", "tags": ("paper", "benchmark", "code")},
            {"sourceId": "mit_tech_review_ai", "name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/", "region": "global", "language": "en", "sourceType": "news", "tags": ("analysis", "policy", "industry")},
            {"sourceId": "techcrunch_ai", "name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/", "region": "global", "language": "en", "sourceType": "news", "tags": ("startup", "product", "funding")},
        ),
    },
    {
        "groupId": "community_signals",
        "label": "社区信号",
        "tier": "tier3",
        "evidenceRole": "signal",
        "enabledByDefault": False,
        "ownerRole": "signal_quality_gate",
        "description": "只用于发现线索和热度异常；任何结论必须回链一手公告、论文或代码仓库。",
        "sources": (
            {"sourceId": "hacker_news_ai", "name": "Hacker News AI Search", "url": "https://hn.algolia.com/?q=AI", "region": "global", "language": "en", "sourceType": "community_search", "tags": ("discussion", "startup", "engineering")},
            {"sourceId": "reddit_localllama", "name": "Reddit LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/", "region": "global", "language": "en", "sourceType": "community", "tags": ("open_model", "community", "signal")},
            {"sourceId": "github_trending_python", "name": "GitHub Trending Python", "url": "https://github.com/trending/python?since=daily", "region": "global", "language": "en", "sourceType": "code_signal", "tags": ("open_source", "code", "trend")},
            {"sourceId": "product_hunt_ai", "name": "Product Hunt AI", "url": "https://www.producthunt.com/topics/artificial-intelligence", "region": "global", "language": "en", "sourceType": "product_signal", "tags": ("product", "startup", "signal")},
        ),
    },
)


class TeamServiceError(ValueError):
    """Raised when a team request is invalid."""


class TeamNotFoundError(TeamServiceError):
    """Raised when a team does not exist."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _perf_counter() -> float:
    return perf_counter()


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


def list_teams(*, include_archived: bool = False) -> dict[str, Any]:
    agent_refs = _agent_reference_maps()
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_state(state, agent_refs=agent_refs)
        changed = _repair_archived_team_member_agents(state, reason="list_teams", strict=False, agent_refs=agent_refs) or changed
        if changed:
            _save_index(state)
    teams = [
        _team_to_api(item, agent_refs=agent_refs)
        for item in list(state.get("teams") or [])
        if isinstance(item, dict) and (include_archived or str(item.get("status") or DEFAULT_TEAM_STATUS) != "archived")
    ]
    teams.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teams": teams,
        "summary": _summary(teams),
        "updatedAt": str(state.get("updatedAt") or ""),
        "storage": {"teamsPath": _relative_path(_teams_index_path()), "teamRoot": _relative_path(_teams_root())},
    }


def list_teams_compact(*, include_archived: bool = False) -> dict[str, Any]:
    """Return Team references without canvas reads or linked room hydration."""

    _sync_chat_room_root()
    compact_rooms_by_id = {
        str(room.get("roomId") or "").strip(): room
        for room in chat_room_service.list_chat_rooms_compact()
        if isinstance(room, dict) and str(room.get("roomId") or "").strip()
    }
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_compact_contracts(state, compact_rooms_by_id=compact_rooms_by_id)
        if changed:
            _save_index(state)
    teams = [
        _team_to_compact_reference(item, compact_rooms_by_id=compact_rooms_by_id)
        for item in list(state.get("teams") or [])
        if isinstance(item, dict) and (include_archived or str(item.get("status") or DEFAULT_TEAM_STATUS) != "archived")
    ]
    teams.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teams": teams,
        "summary": _summary(teams),
        "updatedAt": str(state.get("updatedAt") or ""),
        "storage": {"teamsPath": _relative_path(_teams_index_path()), "teamRoot": _relative_path(_teams_root())},
    }


def list_archived_team_linked_chat_room_ids() -> set[str]:
    """Return room IDs linked to archived teams without loading chat-room catalog data."""

    with _TEAM_LOCK:
        state = _load_index()
        return {
            str(item.get("linkedChatRoomId") or "").strip()
            for item in list(state.get("teams") or [])
            if isinstance(item, dict)
            and str(item.get("status") or DEFAULT_TEAM_STATUS).strip().lower() == "archived"
            and str(item.get("linkedChatRoomId") or "").strip()
        }


def list_team_graph_references(*, include_archived: bool = False) -> dict[str, Any]:
    """Return lightweight Team references for read-only graph surfaces."""

    state = _load_index()
    teams = [
        _team_to_graph_reference(item)
        for item in list(state.get("teams") or [])
        if isinstance(item, dict) and (include_archived or str(item.get("status") or DEFAULT_TEAM_STATUS) != "archived")
    ]
    teams.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teams": teams,
        "summary": _summary(teams),
        "updatedAt": str(state.get("updatedAt") or ""),
        "storage": {"teamsPath": _relative_path(_teams_index_path()), "teamRoot": _relative_path(_teams_root())},
    }


def evolution_system_teams_missing() -> bool:
    """Return whether the system Team bootstrap is required for the list surface."""

    with _TEAM_LOCK:
        state = _load_index()
        if _repair_index_shape(state):
            _save_index(state)
        active_team_ids = {
            str(item.get("teamId") or "").strip()
            for item in list(state.get("teams") or [])
            if isinstance(item, dict)
            and str(item.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived"
        }
    return not EVOLUTION_SYSTEM_TEAM_IDS.issubset(active_team_ids)


def create_team(
    *,
    name: str,
    description: str = "",
    purpose: str = "",
    members: list[dict[str, Any]] | None = None,
    team_kind: str = "custom",
    team_category: str = "",
    team_source: str = "manual",
    team_template_id: str = "",
) -> dict[str, Any]:
    normalized_name = trim_lines(name or "", max_lines=1).strip()
    if not normalized_name:
        raise TeamServiceError("Team name is required.")
    now = utc_now_iso()
    with _TEAM_LOCK:
        state = _load_index()
        normalized_members = _normalize_members(members or [], require_active=True)
        reusable_team = _find_reusable_empty_team(
            state,
            normalized_name=normalized_name,
            team_kind=team_kind,
            team_source=team_source,
            team_template_id=team_template_id,
            requested_member_count=len(normalized_members),
        )
        if reusable_team is not None:
            reused_team_id = str(reusable_team.get("teamId") or "").strip()
            _record_team_event(
                "team.create.reused_empty_team",
                reusable_team,
                fields={"name": normalized_name, "memberCount": 0},
            )
            return get_team(reused_team_id)
        existing_ids = {
            str(item.get("teamId") or "").strip()
            for item in list(state.get("teams") or [])
            if isinstance(item, dict)
        }
        team_id = _new_team_id(normalized_name, existing_ids)
        _ensure_members_can_join_team(normalized_members, state, team_id)
        team = {
            "teamId": team_id,
            "name": normalized_name,
            "description": trim_lines(description or "", max_lines=8).strip(),
            "purpose": trim_lines(purpose or "", max_lines=4).strip(),
            "status": DEFAULT_TEAM_STATUS,
            "members": normalized_members,
            "linkedChatRoomId": "",
            "canvasPath": _relative_path(_team_canvas_path(team_id)),
            "createdAt": now,
            "updatedAt": now,
        }
        _apply_team_contract(
            team,
            team_kind=team_kind,
            team_category=team_category,
            team_source=team_source,
            team_template_id=team_template_id,
        )
        state.setdefault("teams", []).append(team)
        state["updatedAt"] = now
        _save_index(state)
        canvas = _default_canvas_for_team(team)
        _write_json(_team_canvas_path(team_id), canvas)
        _ensure_team_chat_room_link(team)
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    _record_team_event("team.created", team, fields={"memberCount": len(normalized_members)})
    return get_team(team_id)


def ensure_research_team_from_organization(organization: dict[str, Any]) -> dict[str, Any]:
    """Ensure the locked research organization has a stable Team reference."""

    team_id = "research-team"
    now = utc_now_iso()
    members = _members_from_research_organization(organization)
    if _sync_research_team_member_agent_roles(members):
        agent_directory_service.repair_agent_directory()
    with _TEAM_LOCK:
        state = _load_index()
        if _repair_index_state(state):
            state["updatedAt"] = now
        _ensure_members_can_join_team(members, state, team_id)
        team = _find_team(state, team_id)
        created = team is None
        if team is None:
            team = {
                "teamId": team_id,
                "name": RESEARCH_TEAM_DISPLAY_NAME,
                "description": "由科研组织架构自动同步的系统团队。",
                "purpose": "实时展示科研团队成员、职能与组织通信关系。",
                "status": DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": _relative_path(_team_canvas_path(team_id)),
                "createdAt": now,
                "updatedAt": now,
            }
            _apply_team_contract(team, team_kind="research", team_source="research_organization")
            state.setdefault("teams", []).append(team)
        else:
            team["name"] = RESEARCH_TEAM_DISPLAY_NAME
            team["description"] = "由科研组织架构自动同步的系统团队。"
            team["purpose"] = "实时展示科研团队成员、职能与组织通信关系。"
            team["status"] = DEFAULT_TEAM_STATUS
            team["members"] = members
            team["canvasPath"] = _relative_path(_team_canvas_path(team_id))
            team["updatedAt"] = now
            _apply_team_contract(team, team_kind="research", team_source="research_organization")
        state["updatedAt"] = str(team.get("updatedAt") or now)
        _save_index(state)
        canvas = _canvas_from_research_organization(organization, team)
        _write_json(_team_canvas_path(team_id), canvas)
        _ensure_team_chat_room_link(team)
        state["updatedAt"] = str(team.get("updatedAt") or now)
        _save_index(state)
    _record_team_event(
        "team.research_organization_synced",
        team,
        fields={
            "created": created,
            "memberCount": len(members),
            "nodeCount": len(canvas.get("nodes") or []),
            "edgeCount": len(canvas.get("edges") or []),
            "source": "research_organization",
        },
    )
    return get_team(team_id)


def challenge_cup_research_team_agents_need_repair() -> bool:
    """Return whether the Challenge Cup research Team has stale Agent bindings."""

    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, CHALLENGE_CUP_RESEARCH_TEAM_ID)
        if not team:
            return True
        agent_refs = _agent_reference_maps()
        active_agents = agent_refs.get("active_by_id") or {}
        expected_roles = {
            str(role.get("role") or "").strip()
            for role in CHALLENGE_CUP_RESEARCH_TEAM_ROLES
            if str(role.get("role") or "").strip()
        }
        member_agent_ids_by_role: dict[str, str] = {}
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            role = str(member.get("role") or "").strip()
            agent_id = str(member.get("agentId") or "").strip()
            if agent_id and agent_id not in active_agents:
                return True
            if role in expected_roles:
                if not agent_id:
                    return True
                agent = active_agents.get(agent_id)
                if not agent:
                    return True
                metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
                if (
                    str(metadata.get("challengeCupTeamId") or "").strip() != CHALLENGE_CUP_RESEARCH_TEAM_ID
                    or str(metadata.get("challengeCupTeamRole") or "").strip() != role
                    or not _challenge_cup_research_team_agent_direct_session_available(agent)
                ):
                    return True
                member_agent_ids_by_role[role] = agent_id
        if set(member_agent_ids_by_role) != expected_roles:
            return True
        canvas_path = _team_canvas_path(CHALLENGE_CUP_RESEARCH_TEAM_ID)
        if not canvas_path.exists():
            return True
        canvas = _read_json(canvas_path)
        canvas_agent_ids_by_role: dict[str, str] = {}
        for node in list(canvas.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            role = str(node.get("role") or "").strip()
            agent_id = str(node.get("agentId") or "").strip()
            if agent_id and agent_id not in active_agents:
                return True
            if role in expected_roles:
                if not agent_id or member_agent_ids_by_role.get(role) != agent_id:
                    return True
                canvas_agent_ids_by_role[role] = agent_id
        if set(canvas_agent_ids_by_role) != expected_roles:
            return True
    return False


def _challenge_cup_research_team_agent_direct_session_available(agent: dict[str, Any]) -> bool:
    try:
        from . import session_service
    except Exception:
        return bool(str(agent.get("directSessionId") or "").strip())
    previous_root = session_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = Path(PROJECT_ROOT).resolve()
    try:
        return _agent_direct_session_available(agent, session_service=session_service)
    finally:
        session_service.PROJECT_ROOT = previous_root


def ensure_challenge_cup_research_team_agents(*, purge_stale: bool = True) -> dict[str, Any]:
    """Rebuild the Challenge Cup research Team around complete stage Agents."""

    project_root = Path(PROJECT_ROOT).resolve()
    ensured_agents = _ensure_challenge_cup_research_team_role_agents()
    members = _challenge_cup_research_team_members_from_agents(ensured_agents)
    expected_agent_ids = {
        str(agent.get("agentId") or "").strip()
        for agent in ensured_agents
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }
    old_agent_ids = _challenge_cup_research_team_bound_agent_ids()
    extra_agent_ids = _challenge_cup_research_team_duplicate_agent_ids(expected_agent_ids)
    purge_candidates = sorted((old_agent_ids | extra_agent_ids) - expected_agent_ids)
    purge_results = _purge_challenge_cup_research_team_agents(purge_candidates, project_root=project_root) if purge_stale else []

    now = utc_now_iso()
    agent_refs = _merged_agent_reference_maps(_load_lightweight_agent_references(), ensured_agents)
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_shape(state)
        for existing_team in list(state.get("teams") or []):
            if not isinstance(existing_team, dict):
                continue
            if str(existing_team.get("teamId") or "").strip() == CHALLENGE_CUP_RESEARCH_TEAM_ID:
                continue
            changed = _repair_team(existing_team, agent_refs=agent_refs) or changed
        team = _find_team(state, CHALLENGE_CUP_RESEARCH_TEAM_ID)
        created = team is None
        if team is None:
            team = {
                "teamId": CHALLENGE_CUP_RESEARCH_TEAM_ID,
                "name": RESEARCH_TEAM_DISPLAY_NAME,
                "description": "挑战杯神经算法科研团队的系统团队。",
                "purpose": "组织知识搜集、实验和迭代阶段的功能 Agent。",
                "status": DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": _relative_path(_team_canvas_path(CHALLENGE_CUP_RESEARCH_TEAM_ID)),
                "createdAt": now,
                "updatedAt": now,
            }
            _apply_team_contract(team, team_kind="research", team_source="research_organization")
            state.setdefault("teams", []).append(team)
            changed = True
        else:
            if team.get("name") != RESEARCH_TEAM_DISPLAY_NAME:
                team["name"] = RESEARCH_TEAM_DISPLAY_NAME
                changed = True
            if str(team.get("description") or "").strip() != "挑战杯神经算法科研团队的系统团队。":
                team["description"] = "挑战杯神经算法科研团队的系统团队。"
                changed = True
            if str(team.get("purpose") or "").strip() != "组织知识搜集、实验和迭代阶段的功能 Agent。":
                team["purpose"] = "组织知识搜集、实验和迭代阶段的功能 Agent。"
                changed = True
            if team.get("members") != members:
                team["members"] = members
                changed = True
            team["status"] = DEFAULT_TEAM_STATUS
            team["canvasPath"] = _relative_path(_team_canvas_path(CHALLENGE_CUP_RESEARCH_TEAM_ID))
            _apply_team_contract(team, team_kind="research", team_source="research_organization")
        if changed:
            team["updatedAt"] = now
            state["updatedAt"] = now
            _save_index(state)
        canvas = _default_canvas_for_team(team)
        _write_json(_team_canvas_path(CHALLENGE_CUP_RESEARCH_TEAM_ID), canvas)
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        team["updatedAt"] = now
        state["updatedAt"] = now
        _save_index(state)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "created": created,
        "memberCount": len(members),
        "agentCount": len(ensured_agents),
        "directSessionCount": sum(1 for agent in ensured_agents if str(agent.get("directSessionId") or "").strip()),
        "purgedAgentIds": [str(item.get("agentId") or "") for item in purge_results if item.get("deleted")],
        "purgeResults": purge_results,
        "roles": [
            {
                "role": str(role.get("role") or ""),
                "roleKey": str(role.get("roleKey") or ""),
                "label": str(role.get("label") or ""),
            }
            for role in CHALLENGE_CUP_RESEARCH_TEAM_ROLES
        ],
        "team": get_team(CHALLENGE_CUP_RESEARCH_TEAM_ID),
    }
    _record_team_event(
        "team.challenge_cup_agents_repaired",
        result["team"],
        fields={
            "created": created,
            "memberCount": result["memberCount"],
            "agentCount": result["agentCount"],
            "directSessionCount": result["directSessionCount"],
            "purgedAgentCount": len(result["purgedAgentIds"]),
        },
    )
    return result


def knowledge_expansion_team_agents_need_repair() -> bool:
    """Return whether the knowledge-expansion Team has stale Agent bindings."""

    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, KNOWLEDGE_EXPANSION_TEAM_ID)
        if not team:
            return True
        agent_refs = _agent_reference_maps()
        active_agents = agent_refs.get("active_by_id") or {}
        expected_roles = {
            str(role.get("role") or "").strip()
            for role in KNOWLEDGE_EXPANSION_TEAM_ROLES
            if str(role.get("role") or "").strip()
        }
        member_agent_ids_by_role: dict[str, str] = {}
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            role = str(member.get("role") or "").strip()
            agent_id = str(member.get("agentId") or "").strip()
            if agent_id and agent_id not in active_agents:
                return True
            if role in expected_roles:
                if not agent_id:
                    return True
                agent = active_agents.get(agent_id)
                if not agent:
                    return True
                metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
                if (
                    str(metadata.get("knowledgeExpansionTeamId") or "").strip() != KNOWLEDGE_EXPANSION_TEAM_ID
                    or str(metadata.get("knowledgeExpansionTeamRole") or "").strip() != role
                    or not _knowledge_expansion_team_agent_direct_session_available(agent)
                ):
                    return True
                member_agent_ids_by_role[role] = agent_id
        if set(member_agent_ids_by_role) != expected_roles:
            return True
        canvas_path = _team_canvas_path(KNOWLEDGE_EXPANSION_TEAM_ID)
        if not canvas_path.exists():
            return True
        canvas = _read_json(canvas_path)
        canvas_agent_ids_by_role: dict[str, str] = {}
        for node in list(canvas.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            role = str(node.get("role") or "").strip()
            agent_id = str(node.get("agentId") or "").strip()
            if agent_id and agent_id not in active_agents:
                return True
            if role in expected_roles:
                if not agent_id or member_agent_ids_by_role.get(role) != agent_id:
                    return True
                canvas_agent_ids_by_role[role] = agent_id
        if set(canvas_agent_ids_by_role) != expected_roles:
            return True
    return False


def _knowledge_expansion_team_agent_direct_session_available(agent: dict[str, Any]) -> bool:
    try:
        from . import session_service
    except Exception:
        return bool(str(agent.get("directSessionId") or "").strip())
    previous_root = session_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = Path(PROJECT_ROOT).resolve()
    try:
        return _agent_direct_session_available(agent, session_service=session_service)
    finally:
        session_service.PROJECT_ROOT = previous_root


def ensure_knowledge_expansion_team_agents(*, purge_stale: bool = True) -> dict[str, Any]:
    """Ensure the dedicated knowledge-expansion Team and role Agents exist."""

    ensured_agents = _ensure_knowledge_expansion_team_role_agents()
    members = _knowledge_expansion_team_members_from_agents(ensured_agents)
    now = utc_now_iso()
    agent_refs = _merged_agent_reference_maps(_load_lightweight_agent_references(), ensured_agents)
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_shape(state)
        for existing_team in list(state.get("teams") or []):
            if not isinstance(existing_team, dict):
                continue
            if str(existing_team.get("teamId") or "").strip() == KNOWLEDGE_EXPANSION_TEAM_ID:
                continue
            changed = _repair_team(existing_team, agent_refs=agent_refs) or changed
        team = _find_team(state, KNOWLEDGE_EXPANSION_TEAM_ID)
        created = team is None
        if team is None:
            team = {
                "teamId": KNOWLEDGE_EXPANSION_TEAM_ID,
                "name": KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME,
                "description": "用于把本地和网络资料提炼为团队正式知识的系统团队。",
                "purpose": "组织资料发现、本地导入、资料提炼、质检、候选关系和知识库管理员入库。",
                "status": DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": _relative_path(_team_canvas_path(KNOWLEDGE_EXPANSION_TEAM_ID)),
                "createdAt": now,
                "updatedAt": now,
            }
            _apply_team_contract(team, team_kind="knowledge_expansion", team_source="knowledge_expansion")
            state.setdefault("teams", []).append(team)
            changed = True
        else:
            if team.get("name") != KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME:
                team["name"] = KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME
                changed = True
            if str(team.get("description") or "").strip() != "用于把本地和网络资料提炼为团队正式知识的系统团队。":
                team["description"] = "用于把本地和网络资料提炼为团队正式知识的系统团队。"
                changed = True
            expected_purpose = "组织资料发现、本地导入、资料提炼、质检、候选关系和知识库管理员入库。"
            if str(team.get("purpose") or "").strip() != expected_purpose:
                team["purpose"] = expected_purpose
                changed = True
            if team.get("members") != members:
                team["members"] = members
                changed = True
            team["status"] = DEFAULT_TEAM_STATUS
            team["canvasPath"] = _relative_path(_team_canvas_path(KNOWLEDGE_EXPANSION_TEAM_ID))
            _apply_team_contract(team, team_kind="knowledge_expansion", team_source="knowledge_expansion")
        if changed:
            team["updatedAt"] = now
            state["updatedAt"] = now
            _save_index(state)
        canvas = _default_canvas_for_team(team)
        _write_json(_team_canvas_path(KNOWLEDGE_EXPANSION_TEAM_ID), canvas)
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        team["updatedAt"] = now
        state["updatedAt"] = now
        _save_index(state)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": KNOWLEDGE_EXPANSION_TEAM_ID,
        "created": created,
        "memberCount": len(members),
        "agentCount": len(ensured_agents),
        "directSessionCount": sum(1 for agent in ensured_agents if str(agent.get("directSessionId") or "").strip()),
        "purgedAgentIds": [],
        "purgeResults": [],
        "roles": [
            {
                "role": str(role.get("role") or ""),
                "roleKey": str(role.get("roleKey") or ""),
                "label": str(role.get("label") or ""),
            }
            for role in KNOWLEDGE_EXPANSION_TEAM_ROLES
        ],
        "team": get_team(KNOWLEDGE_EXPANSION_TEAM_ID),
    }
    _record_team_event(
        "team.knowledge_expansion_agents_repaired",
        result["team"],
        fields={
            "created": created,
            "memberCount": result["memberCount"],
            "agentCount": result["agentCount"],
            "directSessionCount": result["directSessionCount"],
        },
    )
    return result


def ensure_evolution_system_teams() -> dict[str, Any]:
    """Ensure self-evolution and supervised-evolution roles are visible as Teams."""

    ensured_agents = _ensure_evolution_system_agents()
    agent_refs = _merged_agent_reference_maps(
        _load_lightweight_agent_references(),
        [agent for agents in ensured_agents.values() for agent in list(agents or []) if isinstance(agent, dict)],
    )
    teams: list[dict[str, Any]] = []
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_state(state, agent_refs=agent_refs)
        for spec in EVOLUTION_SYSTEM_TEAM_SPECS:
            team, team_changed = _ensure_evolution_system_team_in_state(
                state,
                spec,
                ensured_agents,
                agent_refs=agent_refs,
            )
            changed = changed or team_changed
            if team:
                teams.append(dict(team))
        if changed:
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teams": [get_team(str(team.get("teamId") or "")) for team in teams],
        "updatedAt": utc_now_iso(),
    }


def ai_search_system_team_missing() -> bool:
    """Return whether the AI search scope Team should be materialized for the list surface."""

    expected_roles = {str(role.get("role") or "").strip() for role in AI_SEARCH_SYSTEM_ROLES}
    with _TEAM_LOCK:
        state = _load_index()
        if _repair_index_shape(state):
            _save_index(state)
        team = _find_team(state, AI_SEARCH_TEAM_ID)
        if not team or str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
            return True
        if str(team.get("teamKind") or _infer_team_kind(team)).strip() != "ai_search":
            return True
        if str(team.get("sourceScopePath") or "").strip() != _relative_path(_ai_search_source_scope_path()):
            return True
        if _ai_search_source_scope_needs_sync(_ai_search_source_scope_path()):
            return True
        member_roles = {
            str(member.get("role") or "").strip()
            for member in list(team.get("members") or [])
            if isinstance(member, dict) and str(member.get("agentId") or "").strip()
        }
        return not expected_roles.issubset(member_roles)


def request_system_team_bootstrap(*, reason: str = "team_list") -> dict[str, Any]:
    """Start a bounded background repair for missing system Teams.

    Team list reads must stay fast. This helper only performs lightweight
    missing checks inline, then lets the expensive Team/Agent/ChatRoom writes
    happen outside the request path.
    """

    global _TEAM_SYSTEM_BOOTSTRAP_THREAD
    normalized_reason = _safe_token(reason or "team_list", default="team_list", max_length=80)
    with _TEAM_SYSTEM_BOOTSTRAP_LOCK:
        if _TEAM_SYSTEM_BOOTSTRAP_THREAD and _TEAM_SYSTEM_BOOTSTRAP_THREAD.is_alive():
            return _system_team_bootstrap_state_snapshot_locked()
    try:
        required_steps = _system_team_bootstrap_required_steps()
    except Exception as exc:
        with _TEAM_SYSTEM_BOOTSTRAP_LOCK:
            _TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "failed",
                    "requiredSteps": [],
                    "reason": normalized_reason,
                    "finishedAt": utc_now_iso(),
                    "lastError": f"{type(exc).__name__}: {exc}",
                    "elapsedMs": 0,
                }
            )
            snapshot = _system_team_bootstrap_state_snapshot_locked()
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.check_failed",
            outcome="failed",
            fields={"reason": normalized_reason, "errorType": type(exc).__name__},
        )
        return snapshot
    if not required_steps:
        with _TEAM_SYSTEM_BOOTSTRAP_LOCK:
            _TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "ready",
                    "requiredSteps": [],
                    "reason": normalized_reason,
                    "finishedAt": utc_now_iso(),
                    "lastError": "",
                    "elapsedMs": 0,
                }
            )
            return _system_team_bootstrap_state_snapshot_locked()

    with _TEAM_SYSTEM_BOOTSTRAP_LOCK:
        if _TEAM_SYSTEM_BOOTSTRAP_THREAD and _TEAM_SYSTEM_BOOTSTRAP_THREAD.is_alive():
            return _system_team_bootstrap_state_snapshot_locked()
        attempt = int(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("attempt") or 0) + 1
        request_id = f"system-team-bootstrap-{attempt}"
        started_at = utc_now_iso()
        _TEAM_SYSTEM_BOOTSTRAP_STATE.update(
            {
                "status": "running",
                "requiredSteps": list(required_steps),
                "reason": normalized_reason,
                "startedAt": started_at,
                "finishedAt": "",
                "lastError": "",
                "elapsedMs": 0,
                "attempt": attempt,
                "requestId": request_id,
            }
        )
        _TEAM_SYSTEM_BOOTSTRAP_THREAD = threading.Thread(
            target=_run_system_team_bootstrap,
            args=(request_id, list(required_steps), normalized_reason),
            name="vibelution-team-system-bootstrap",
            daemon=True,
        )
        thread = _TEAM_SYSTEM_BOOTSTRAP_THREAD
        snapshot = _system_team_bootstrap_state_snapshot_locked()
    thread.start()
    return snapshot


def _system_team_bootstrap_required_steps() -> list[str]:
    required_steps: list[str] = []
    if evolution_system_teams_missing():
        required_steps.append("evolution_system_teams")
    if ai_search_system_team_missing():
        required_steps.append("ai_search_system_team")
    if challenge_cup_research_team_agents_need_repair():
        required_steps.append("challenge_cup_research_team_agents")
    if knowledge_expansion_team_agents_need_repair():
        required_steps.append("knowledge_expansion_team_agents")
    return required_steps


def _system_team_bootstrap_state_snapshot_locked() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": str(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("status") or "idle"),
        "requiredSteps": list(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("requiredSteps") or []),
        "reason": str(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("reason") or ""),
        "startedAt": str(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("startedAt") or ""),
        "finishedAt": str(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("finishedAt") or ""),
        "lastError": str(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("lastError") or ""),
        "elapsedMs": int(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("elapsedMs") or 0),
        "attempt": int(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("attempt") or 0),
        "requestId": str(_TEAM_SYSTEM_BOOTSTRAP_STATE.get("requestId") or ""),
    }


def _run_system_team_bootstrap(request_id: str, required_steps: list[str], reason: str) -> None:
    started_at = _perf_counter()
    _record_system_team_bootstrap_event(
        "team.system_bootstrap.started",
        outcome="started",
        fields={"requestId": request_id, "requiredSteps": list(required_steps), "reason": reason},
    )
    try:
        if "evolution_system_teams" in required_steps:
            ensure_evolution_system_teams()
        if "ai_search_system_team" in required_steps:
            ensure_ai_search_system_team()
        if "challenge_cup_research_team_agents" in required_steps:
            ensure_challenge_cup_research_team_agents(purge_stale=True)
        if "knowledge_expansion_team_agents" in required_steps:
            ensure_knowledge_expansion_team_agents(purge_stale=True)
        remaining_steps = _system_team_bootstrap_required_steps()
        elapsed_ms = _elapsed_ms(started_at)
        status = "ready" if not remaining_steps else "needs_retry"
        outcome = "succeeded" if not remaining_steps else "blocked"
        with _TEAM_SYSTEM_BOOTSTRAP_LOCK:
            _TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": status,
                    "requiredSteps": list(remaining_steps),
                    "reason": reason,
                    "finishedAt": utc_now_iso(),
                    "lastError": "",
                    "elapsedMs": elapsed_ms,
                    "requestId": request_id,
                }
            )
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.finished",
            outcome=outcome,
            fields={
                "requestId": request_id,
                "requiredSteps": list(required_steps),
                "remainingSteps": list(remaining_steps),
                "reason": reason,
                "elapsedMs": elapsed_ms,
            },
        )
    except Exception as exc:
        elapsed_ms = _elapsed_ms(started_at)
        with _TEAM_SYSTEM_BOOTSTRAP_LOCK:
            _TEAM_SYSTEM_BOOTSTRAP_STATE.update(
                {
                    "status": "failed",
                    "requiredSteps": list(required_steps),
                    "reason": reason,
                    "finishedAt": utc_now_iso(),
                    "lastError": f"{type(exc).__name__}: {exc}",
                    "elapsedMs": elapsed_ms,
                    "requestId": request_id,
                }
            )
        _record_system_team_bootstrap_event(
            "team.system_bootstrap.failed",
            outcome="failed",
            fields={
                "requestId": request_id,
                "requiredSteps": list(required_steps),
                "reason": reason,
                "elapsedMs": elapsed_ms,
                "errorType": type(exc).__name__,
            },
        )


def ensure_ai_search_system_team() -> dict[str, Any]:
    """Ensure the AI search source-scope team is visible in the Team workspace."""

    ensured_agents = _ensure_ai_search_system_agents()
    agent_refs = _merged_agent_reference_maps(_load_lightweight_agent_references(), ensured_agents)
    members = _ai_search_members_from_agents(ensured_agents)
    now = utc_now_iso()
    with _TEAM_LOCK:
        state = _load_index()
        changed = _repair_index_state(state, agent_refs=agent_refs)
        members = _members_without_cross_team_conflicts(members, state, AI_SEARCH_TEAM_ID, source="ai_search")
        team = _find_team(state, AI_SEARCH_TEAM_ID)
        created = team is None
        if team is None:
            team = {
                "teamId": AI_SEARCH_TEAM_ID,
                "name": AI_SEARCH_TEAM_DISPLAY_NAME,
                "description": "由 AI 最新动态搜索范围白名单自动同步的系统团队。",
                "purpose": "维护 AI 最新动态一键搜索的来源范围、可信度分层、默认启用策略与信号源质检。",
                "status": DEFAULT_TEAM_STATUS,
                "members": members,
                "linkedChatRoomId": "",
                "canvasPath": _relative_path(_team_canvas_path(AI_SEARCH_TEAM_ID)),
                "sourceScopePath": _relative_path(_ai_search_source_scope_path()),
                "systemTeamKind": "ai_search",
                "teamKind": "ai_search",
                "teamCategory": "AI 搜索系统团队",
                "teamSource": "ai_search",
                "teamTemplateId": "",
                "createdAt": now,
                "updatedAt": now,
            }
            state.setdefault("teams", []).append(team)
            changed = True
        else:
            expected = {
                "name": AI_SEARCH_TEAM_DISPLAY_NAME,
                "description": "由 AI 最新动态搜索范围白名单自动同步的系统团队。",
                "purpose": "维护 AI 最新动态一键搜索的来源范围、可信度分层、默认启用策略与信号源质检。",
                "status": DEFAULT_TEAM_STATUS,
                "members": members,
                "canvasPath": _relative_path(_team_canvas_path(AI_SEARCH_TEAM_ID)),
                "sourceScopePath": _relative_path(_ai_search_source_scope_path()),
                "systemTeamKind": "ai_search",
                "teamKind": "ai_search",
                "teamCategory": "AI 搜索系统团队",
                "teamSource": "ai_search",
                "teamTemplateId": "",
            }
            for key, value in expected.items():
                if team.get(key) != value:
                    team[key] = value
                    changed = True
            if changed:
                team["updatedAt"] = now
        if _apply_team_contract(team, team_kind="ai_search", team_source="ai_search"):
            changed = True
        canvas_path = _team_canvas_path(AI_SEARCH_TEAM_ID)
        if created or _ai_search_canvas_needs_sync(canvas_path, team):
            _write_json(canvas_path, _ai_search_canvas_for_team(team))
            changed = True
        source_scope_changed = _ensure_ai_search_source_scope_file()
        if source_scope_changed:
            changed = True
        if _team_chat_room_needs_sync(team, agent_refs=agent_refs):
            _ensure_team_chat_room_link(team, agent_refs=agent_refs)
            changed = True
        if changed:
            canvas = _ai_search_canvas_for_team(team)
            source_scope = _load_ai_search_source_scope()
            team["updatedAt"] = str(team.get("updatedAt") or now)
            state["updatedAt"] = team["updatedAt"]
            _save_index(state)
            _record_team_event(
                "team.ai_search_system_synced",
                team,
                fields={
                    "created": created,
                    "memberCount": len(members),
                    "nodeCount": len(canvas.get("nodes") or []),
                    "edgeCount": len(canvas.get("edges") or []),
                    "sourceScopePath": _relative_path(_ai_search_source_scope_path()),
                    "sourceScopeChanged": source_scope_changed,
                    "sourceGroupCount": len(source_scope.get("groups") or []),
                    "sourceCount": int((source_scope.get("summary") or {}).get("sourceCount") or 0),
                    "source": "ai_search",
                },
            )
    return get_team(AI_SEARCH_TEAM_ID)


def list_ai_search_source_scope_runs(team_id: str, *, limit: int = 6) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    if normalized_team_id != AI_SEARCH_TEAM_ID:
        raise TeamServiceError("AI search runs are only available for the AI search scope Team.")
    ensure_ai_search_system_team()
    index = _load_ai_search_runs_index()
    runs = [
        item for item in list(index.get("runs") or [])
        if isinstance(item, dict)
    ]
    runs.sort(key=lambda item: str(item.get("createdAt") or item.get("updatedAt") or ""), reverse=True)
    limited_runs = runs[: max(1, min(int(limit or 6), 20))]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": AI_SEARCH_TEAM_ID,
        "runs": limited_runs,
        "summary": {
            "runCount": len(runs),
            "visibleRunCount": len(limited_runs),
        },
        "storage": {
            "runsPath": _relative_path(_ai_search_runs_index_path()),
            "runsRoot": _relative_path(_ai_search_runs_root()),
        },
        "updatedAt": str(index.get("updatedAt") or ""),
    }


def start_ai_search_source_scope_run(
    team_id: str,
    *,
    topic: str = "",
    source_limit: int = 8,
    max_results_per_query: int = 3,
    include_signals: bool = False,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    if normalized_team_id != AI_SEARCH_TEAM_ID:
        raise TeamServiceError("AI search runs can only be started from the AI search scope Team.")
    ensure_ai_search_system_team()
    scope = _load_ai_search_source_scope()
    query_topic = trim_lines(topic or "AI 最新动态", max_lines=1).strip() or "AI 最新动态"
    bounded_source_limit = max(1, min(int(source_limit or 8), 12))
    bounded_max_results = max(1, min(int(max_results_per_query or 3), 10))
    selected_sources = _select_ai_search_sources(scope, source_limit=bounded_source_limit, include_signals=include_signals)
    if not selected_sources:
        raise TeamServiceError("AI search source scope has no enabled sources to search.")
    now = utc_now_iso()
    run_id = _new_ai_search_run_id()
    queries = [
        _ai_search_query_for_source(source, topic=query_topic, run_id=run_id, index=index)
        for index, source in enumerate(selected_sources, start=1)
    ]
    run = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "teamId": AI_SEARCH_TEAM_ID,
        "title": f"{query_topic} 一键搜索",
        "topic": query_topic,
        "status": "running",
        "createdAt": now,
        "updatedAt": now,
        "sourceScope": {
            "scopeId": str(scope.get("scopeId") or ""),
            "sourceScopePath": _relative_path(_ai_search_source_scope_path()),
            "defaultEnabledTiers": list((scope.get("policy") or {}).get("defaultEnabledTiers") or []),
            "requiresPrimaryEvidenceForConclusion": bool((scope.get("policy") or {}).get("requiresPrimaryEvidenceForConclusion")),
        },
        "queryPlan": {
            "queryCount": len(queries),
            "sourceLimit": bounded_source_limit,
            "maxResultsPerQuery": bounded_max_results,
            "includeSignals": bool(include_signals),
            "queries": queries,
        },
        "cards": [],
        "errors": [],
        "summary": {
            "cardCount": 0,
            "succeededCount": 0,
            "failedCount": 0,
            "degradedCount": 0,
            "referenceCount": 0,
        },
        "storage": {
            "runPath": _relative_path(_ai_search_run_path(run_id)),
            "runsPath": _relative_path(_ai_search_runs_index_path()),
        },
    }
    _record_team_event(
        "team.ai_search_run.started",
        {"teamId": AI_SEARCH_TEAM_ID, "name": AI_SEARCH_TEAM_DISPLAY_NAME, "teamKind": "ai_search", "teamSource": "ai_search"},
        fields={
            "runId": run_id,
            "topic": query_topic,
            "queryCount": len(queries),
            "sourceLimit": bounded_source_limit,
            "includeSignals": bool(include_signals),
        },
    )
    cards: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for query in queries:
        card = _execute_ai_search_query_card(query, max_results=bounded_max_results)
        cards.append(card)
        if card["status"] == "failed":
            errors.append({"queryId": query["queryId"], "sourceId": query["sourceId"], "message": card["summary"]})
    succeeded_count = sum(1 for card in cards if card.get("status") == "succeeded")
    failed_count = len(cards) - succeeded_count
    degraded_count = sum(1 for card in cards if bool(card.get("degraded")))
    reference_count = sum(len(list(card.get("references") or [])) for card in cards)
    status = "failed" if failed_count == len(cards) else "partial" if failed_count else "completed"
    run.update(
        {
            "status": status,
            "updatedAt": utc_now_iso(),
            "cards": cards,
            "errors": errors,
            "summary": {
                "cardCount": len(cards),
                "succeededCount": succeeded_count,
                "failedCount": failed_count,
                "degradedCount": degraded_count,
                "referenceCount": reference_count,
            },
        }
    )
    _write_json(_ai_search_run_path(run_id), run)
    _upsert_ai_search_run_summary(run)
    if degraded_count:
        _record_team_event(
            "team.ai_search_run.fallback_used",
            {"teamId": AI_SEARCH_TEAM_ID, "name": AI_SEARCH_TEAM_DISPLAY_NAME, "teamKind": "ai_search", "teamSource": "ai_search"},
            fields={
                "runId": run_id,
                "topic": query_topic,
                "degradedCount": degraded_count,
                "searchModes": sorted({str(card.get("searchMode") or "").strip() for card in cards if bool(card.get("degraded"))}),
                "sourceIds": [str(card.get("sourceId") or "").strip() for card in cards if bool(card.get("degraded"))],
            },
        )
    _record_team_event(
        "team.ai_search_run.completed",
        {"teamId": AI_SEARCH_TEAM_ID, "name": AI_SEARCH_TEAM_DISPLAY_NAME, "teamKind": "ai_search", "teamSource": "ai_search"},
        fields={
            "runId": run_id,
            "topic": query_topic,
            "status": status,
            "queryCount": len(queries),
            "succeededCount": succeeded_count,
            "failedCount": failed_count,
            "degradedCount": degraded_count,
            "referenceCount": reference_count,
            "runPath": _relative_path(_ai_search_run_path(run_id)),
        },
    )
    return run


def get_team(team_id: str) -> dict[str, Any]:
    started_at = _perf_counter()
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    agent_refs = _agent_reference_maps()
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        changed = _repair_team(team, agent_refs=agent_refs)
        changed = _repair_archived_team_member_agents_for_team(
            team,
            state,
            reason="get_team",
            strict=False,
            agent_refs=agent_refs,
        ) or changed
        if changed:
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
    detail = _team_detail_to_api(team, agent_refs=agent_refs)
    _record_team_detail_loaded(detail, started_at)
    return detail


def assert_team_exists(team_id: str) -> str:
    """Validate that a Team exists without hydrating or repairing its full detail."""

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
    return normalized_team_id


def update_team(
    team_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    purpose: str | None = None,
    status: str | None = None,
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if name is not None:
            normalized_name = trim_lines(name or "", max_lines=1).strip()
            if not normalized_name:
                raise TeamServiceError("Team name is required.")
            team["name"] = normalized_name
        if description is not None:
            team["description"] = trim_lines(description or "", max_lines=8).strip()
        if purpose is not None:
            team["purpose"] = trim_lines(purpose or "", max_lines=4).strip()
        if status is not None:
            normalized_status = str(status or "").strip().lower() or DEFAULT_TEAM_STATUS
            if normalized_status not in TEAM_STATUSES:
                raise TeamServiceError(f"Unsupported team status: {status}")
            if normalized_status == "archived" and str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
                return _archive_team_in_state(state, team)
            team["status"] = normalized_status
        if members is not None:
            normalized_members = _normalize_members(members, require_active=True)
            _ensure_members_can_join_team(normalized_members, state, normalized_team_id)
            team["members"] = normalized_members
        team["updatedAt"] = utc_now_iso()
        team["canvasPath"] = _relative_path(_team_canvas_path(normalized_team_id))
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    _record_team_event("team.updated", team, fields={"memberCount": len(team.get("members") or [])})
    return get_team(normalized_team_id)


def remove_agent_from_teams(agent_id: str) -> dict[str, Any]:
    """Remove one unavailable Agent from active Team membership and linked rooms."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise TeamServiceError("Agent id is required.")
    cleanup = remove_agents_from_teams([normalized_agent_id])
    return {
        "agentId": normalized_agent_id,
        "changedTeamIds": list(cleanup.get("changedTeamIds") or []),
    }


def remove_agents_from_teams(agent_ids: list[str] | None) -> dict[str, Any]:
    """Remove multiple unavailable Agents from active Team membership in one index update."""

    requested = [str(item or "").strip() for item in list(agent_ids or []) if str(item or "").strip()]
    normalized_agent_ids: list[str] = []
    seen_agent_ids: set[str] = set()
    for agent_id in requested:
        if agent_id in seen_agent_ids:
            continue
        seen_agent_ids.add(agent_id)
        normalized_agent_ids.append(agent_id)
    if not normalized_agent_ids:
        return {"agentIds": [], "changedTeamIds": [], "removedByAgentId": {}}
    changed_team_ids: list[str] = []
    removed_by_agent_id: dict[str, list[str]] = {agent_id: [] for agent_id in normalized_agent_ids}
    agent_id_set = set(normalized_agent_ids)
    with _TEAM_LOCK:
        state = _load_index()
        teams = [item for item in list(state.get("teams") or []) if isinstance(item, dict)]
        now = utc_now_iso()
        for team in teams:
            if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
                continue
            members = [dict(item) for item in list(team.get("members") or []) if isinstance(item, dict)]
            removed_agent_ids_for_team = {
                str(member.get("agentId") or "").strip()
                for member in members
                if str(member.get("agentId") or "").strip() in agent_id_set
            }
            next_members = [
                member
                for member in members
                if str(member.get("agentId") or "").strip() not in agent_id_set
            ]
            if next_members == members:
                continue
            team_id = str(team.get("teamId") or "").strip()
            team["members"] = next_members
            team["updatedAt"] = now
            team["canvasPath"] = _relative_path(_team_canvas_path(team_id))
            for removed_agent_id in sorted(removed_agent_ids_for_team):
                _remove_agent_from_team_canvas(team, removed_agent_id)
                removed_by_agent_id.setdefault(removed_agent_id, []).append(team_id)
            _sync_chat_room_root()
            _ensure_team_chat_room_link(team)
            changed_team_ids.append(team_id)
        if changed_team_ids:
            state["updatedAt"] = now
            _save_index(state)
    for team_id in changed_team_ids:
        removed_agent_ids = [
            agent_id
            for agent_id, team_ids in removed_by_agent_id.items()
            if team_id in set(team_ids)
        ]
        _record_team_event(
            "team.agent_membership.removed",
            {"teamId": team_id, "status": DEFAULT_TEAM_STATUS},
            fields={"agentIds": removed_agent_ids, "agentCount": len(removed_agent_ids)},
        )
    return {
        "agentIds": normalized_agent_ids,
        "changedTeamIds": changed_team_ids,
        "removedByAgentId": {
            agent_id: list(team_ids)
            for agent_id, team_ids in removed_by_agent_id.items()
            if team_ids
        },
    }


def _remove_agent_from_team_canvas(team: dict[str, Any], agent_id: str) -> None:
    team_id = str(team.get("teamId") or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not team_id or not normalized_agent_id:
        return
    canvas_path = _team_canvas_path(team_id)
    raw = _read_json(canvas_path) if canvas_path.exists() else _default_canvas_for_team(team)
    if not isinstance(raw, dict):
        raw = _default_canvas_for_team(team)
    removed_node_ids = {
        str(node.get("id") or "").strip()
        for node in list(raw.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("agentId") or "").strip() == normalized_agent_id
    }
    nodes = [
        dict(node)
        for node in list(raw.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("agentId") or "").strip() != normalized_agent_id
    ]
    if not nodes:
        nodes = _default_nodes_for_members(team.get("members") or [])
    edges = [
        dict(edge)
        for edge in list(raw.get("edges") or [])
        if isinstance(edge, dict)
        and str(edge.get("source") or "").strip() not in removed_node_ids
        and str(edge.get("target") or "").strip() not in removed_node_ids
    ]
    canvas = {
        **raw,
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": team_id,
        "updatedAt": str(team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(canvas_path),
        "nodes": nodes,
        "edges": edges,
    }
    _write_json(canvas_path, canvas)


def archive_team(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
            member_changed = _repair_archived_team_member_agents_for_team(
                team,
                state,
                reason="archive_team_already_archived",
                strict=True,
            )
            room_changed = _repair_archived_team_linked_chat_room(team, reason="archive_team_already_archived")
            if member_changed or room_changed:
                state["updatedAt"] = utc_now_iso()
                _save_index(state)
            return get_team(normalized_team_id)
        return _archive_team_in_state(state, team)


def _archive_team_in_state(state: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    team_id = str(team.get("teamId") or "").strip()
    team_kind = str(team.get("teamKind") or _infer_team_kind(team)).strip() or "custom"
    if team_kind in {"research", "ai_search", "self_evolution", "supervised_evolution"}:
        _record_team_archive_rejected(team, reason="system_team")
        raise TeamServiceError("System Team cannot be archived with cascade Agent deletion.")
    if team_kind not in {"custom", "template_demo"}:
        _record_team_archive_rejected(team, reason="unsupported_team_kind")
        raise TeamServiceError(f"Team kind cannot be archived with cascade Agent deletion: {team_kind}")

    agent_ids = _unique_active_member_agent_ids(team)
    _ensure_team_member_agents_can_archive(team, agent_ids)
    deleted_room_ids = _delete_team_linked_chat_rooms(team, reason="team_archive", strict_busy=True)
    room_cleanup = _remove_team_member_agents_from_chat_rooms(team, agent_ids)

    now = utc_now_iso()
    team["status"] = "archived"
    team["updatedAt"] = now
    team["canvasPath"] = _relative_path(_team_canvas_path(team_id))
    state["updatedAt"] = now
    _save_index(state)

    archived_agent_ids = _archive_team_member_agents(team, agent_ids, reason="team_archive")

    _record_team_event(
        "team.archived_with_agents",
        team,
        fields={
            "archivedAgentIds": archived_agent_ids,
            "archivedAgentCount": len(archived_agent_ids),
            "deletedLinkedChatRoomIds": deleted_room_ids,
            "deletedLinkedChatRoomCount": len(deleted_room_ids),
            "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
            "removedFromRoomCount": len(list(room_cleanup.get("changedRoomIds") or [])),
            "roomCleanupByAgentId": dict(room_cleanup.get("removedByAgentId") or {}),
        },
    )
    return get_team(team_id)


def send_team_message(
    team_id: str,
    *,
    content: str,
    interrupt_mode: str = "none",
    wake_target: bool = True,
    created_by: str = "user",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    team = _get_team_record(team_id)
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        raise TeamServiceError("Archived teams cannot receive new messages.")
    normalized_content = trim_lines(content or "", max_lines=40).strip()
    if not normalized_content:
        raise TeamServiceError("Team message content is required.")
    target_agent_ids = _active_member_agent_ids(team)
    if not target_agent_ids:
        raise TeamServiceError("Team has no active Agent members.")
    _sync_project_bus_root()
    event = project_agent_bus_service.send_project_agent_bus_message(
        content=normalized_content,
        target_scope="agents",
        target_agent_ids=target_agent_ids,
        interrupt_mode=interrupt_mode,
        wake_target=wake_target,
        created_by=created_by,
        metadata={
            **(metadata or {}),
            "teamId": team["teamId"],
            "teamName": str(team.get("name") or ""),
            "source": "team",
        },
    )
    _record_team_event(
        "team.message.sent",
        team,
        fields={
            "projectBusEventId": event.get("eventId"),
            "targetAgentIds": event.get("targetAgentIds") or [],
            "deliveryCount": len(event.get("deliveries") or []),
            "interruptMode": interrupt_mode,
            "wakeTarget": bool(wake_target),
        },
    )
    return event


def sync_team_chat_room(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    agent_refs = _agent_reference_maps()
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if _repair_team(team, agent_refs=agent_refs):
            state["updatedAt"] = utc_now_iso()
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        state["updatedAt"] = team["updatedAt"]
        _save_index(state)
    return get_team(normalized_team_id)


def get_team_canvas(team_id: str) -> dict[str, Any]:
    agent_refs = _agent_reference_maps()
    team = _get_team_record(team_id, agent_refs=agent_refs)
    return _team_canvas_with_validation(
        team,
        agents_by_id=agent_refs["by_id"],
        active_agents_by_id=agent_refs["active_by_id"],
    )


def _team_canvas_with_validation(
    team: dict[str, Any],
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    canvas_path = _team_canvas_path(team["teamId"])
    raw = _read_json(canvas_path) if canvas_path.exists() else {}
    canvas = _normalize_canvas(
        raw or _default_canvas_for_team(team),
        team,
        agents_by_id=agents_by_id,
        active_agents_by_id=active_agents_by_id,
    )
    validation = _validate_canvas(canvas, team_id=team["teamId"], active_agents_by_id=active_agents_by_id)
    if raw != canvas:
        _write_json(canvas_path, canvas)
    return {**canvas, "validation": validation}


def save_team_canvas(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    agent_refs = _agent_reference_maps()
    team = get_team(team_id)
    canvas = _normalize_canvas(
        payload,
        team,
        agents_by_id=agent_refs["by_id"],
        active_agents_by_id=agent_refs["active_by_id"],
    )
    validation = _validate_canvas(canvas, team_id=team["teamId"], active_agents_by_id=agent_refs["active_by_id"])
    if not validation["valid"]:
        raise TeamServiceError(_format_validation_error(validation))
    canvas["updatedAt"] = utc_now_iso()
    with _TEAM_LOCK:
        state = _load_index()
        stored = _find_team(state, team["teamId"])
        current_members = stored.get("members") if isinstance(stored, dict) and isinstance(stored.get("members"), list) else team.get("members") or []
        next_members = _sync_members_from_canvas(current_members, canvas)
        _ensure_members_can_join_team(next_members, state, team["teamId"])
        _write_json(_team_canvas_path(team["teamId"]), canvas)
        if stored is not None:
            stored["updatedAt"] = canvas["updatedAt"]
            stored["canvasPath"] = _relative_path(_team_canvas_path(team["teamId"]))
            stored["members"] = next_members
            _ensure_team_chat_room_link(stored, agent_refs=agent_refs)
            state["updatedAt"] = canvas["updatedAt"]
            _save_index(state)
    _record_team_event(
        "team.canvas.updated",
        team,
        fields={"nodeCount": len(canvas["nodes"]), "edgeCount": len(canvas["edges"]), "valid": validation["valid"]},
    )
    return {**canvas, "validation": validation}


def list_agent_team_references() -> dict[str, list[dict[str, Any]]]:
    references: dict[str, list[dict[str, Any]]] = {}
    for team in list_teams(include_archived=True).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        status = str(team.get("status") or DEFAULT_TEAM_STATUS).strip()
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            agent_id = str(member.get("agentId") or "").strip()
            if not agent_id:
                continue
            references.setdefault(agent_id, []).append(
                {
                    "kind": "team",
                    "sourceId": team_id,
                    "sourceLabel": str(team.get("name") or team_id),
                    "field": str(member.get("memberId") or ""),
                    "route": "/teams",
                    "status": "stale" if str(member.get("agentStatus") or "") != "active" or status == "archived" else "active",
                }
            )
    return references


def _normalize_canvas(
    raw: dict[str, Any],
    team: dict[str, Any],
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TeamServiceError("Team canvas payload must be an object.")
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    edges = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    if not nodes:
        nodes = _default_nodes_for_members(team.get("members") or [])
    normalized_nodes = [
        _normalize_node(
            item,
            index,
            agents_by_id=agents_by_id,
            active_agents_by_id=active_agents_by_id,
        )
        for index, item in enumerate(nodes[:120])
    ]
    node_ids = [node["id"] for node in normalized_nodes]
    if len(node_ids) != len(set(node_ids)):
        raise TeamServiceError("Team canvas node ids must be unique.")
    node_id_set = set(node_ids)
    normalized_edges = [_normalize_edge(item, index, node_id_set) for index, item in enumerate(edges[:240])]
    viewport = raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": team["teamId"],
        "updatedAt": str(raw.get("updatedAt") or team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(_team_canvas_path(team["teamId"])),
        "viewport": {
            "x": _safe_float(viewport.get("x"), 0.0),
            "y": _safe_float(viewport.get("y"), 0.0),
            "zoom": min(2.0, max(0.45, _safe_float(viewport.get("zoom"), 1.0))),
        },
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


def _normalize_node(
    item: Any,
    index: int,
    *,
    agents_by_id: dict[str, dict[str, Any]] | None = None,
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TeamServiceError("Team canvas node must be an object.")
    agent_id = _safe_token(item.get("agentId"), default="", max_length=128)
    node_id = _safe_token(item.get("id") or agent_id, default=f"node-{index + 1}", max_length=128)
    if agent_id and agents_by_id is not None:
        agent = agents_by_id.get(agent_id)
    else:
        agent = agent_directory_service.get_agent(agent_id, include_archived=True) if agent_id else None
    if agent_id and active_agents_by_id is not None:
        active_agent = active_agents_by_id.get(agent_id)
    else:
        active_agent = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
    node_type = _safe_token(item.get("type"), default="role", max_length=40)
    status = "bound" if active_agent else "stale" if agent_id else "unbound"
    agent_source_ref = _source_authority_ref("agent", agent_id) if agent_id else None
    agent_projection_edit = _projection_edit_contract("agent", agent_id) if agent_id else None
    return {
        "id": node_id,
        "label": trim_lines(item.get("label") or (agent or {}).get("displayName") or f"角色 {index + 1}", max_lines=1).strip(),
        "type": node_type if node_type in NODE_TYPES else "role",
        "status": status,
        "x": _safe_float(item.get("x"), 120.0 + index * 220.0),
        "y": _safe_float(item.get("y"), 120.0),
        "agentId": agent_id,
        "agentCode": str((agent or {}).get("agentCode") or "").strip(),
        "agentName": str((agent or {}).get("displayName") or "").strip(),
        "agentSourceRef": agent_source_ref,
        "agentProjectionEdit": agent_projection_edit,
        "agentProjectionCanWrite": False,
        "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
        "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
        "responsibilities": [
            trim_lines(value, max_lines=2).strip()
            for value in list(item.get("responsibilities") or [])[:8]
            if str(value or "").strip()
        ],
    }


def _normalize_edge(item: Any, index: int, node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TeamServiceError("Team canvas edge must be an object.")
    source = _safe_token(item.get("source"), default="", max_length=96)
    target = _safe_token(item.get("target"), default="", max_length=96)
    if source not in node_ids or target not in node_ids:
        raise TeamServiceError("Team canvas edge must reference existing nodes.")
    edge_type = _safe_token(item.get("type"), default="collaborates_with", max_length=40)
    return {
        "id": _safe_token(item.get("id"), default=f"edge-{index + 1}", max_length=96),
        "source": source,
        "target": target,
        "label": trim_lines(item.get("label") or "", max_lines=1).strip(),
        "type": edge_type if edge_type in EDGE_TYPES else "collaborates_with",
    }


def _source_authority_ref(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.agent_kernel.source_authority import source_ref

    return source_ref(kind, source_id, metadata)


def _projection_edit_contract(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.agent_kernel.source_authority import projection_edit_contract

    return projection_edit_contract(kind, source_id, metadata)


def _validate_canvas(
    canvas: dict[str, Any],
    *,
    team_id: str = "",
    active_agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    node_ids: set[str] = set()
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            issues.append(_issue("error", "missing_node_id", "画布节点缺少 id。"))
            continue
        if node_id in node_ids:
            issues.append(_issue("error", "duplicate_node_id", f"节点 id 重复：{node_id}", node_id=node_id))
        node_ids.add(node_id)
        agent_id = str(node.get("agentId") or "").strip()
        if agent_id and active_agents_by_id is not None:
            active_agent = active_agents_by_id.get(agent_id)
        else:
            active_agent = agent_directory_service.get_agent(agent_id, include_archived=False) if agent_id else None
        if agent_id and not active_agent:
            issues.append(_issue("warning", "stale_agent_ref", f"节点绑定的 Agent 不可用：{agent_id}", node_id=node_id))
        if agent_id:
            conflict = _find_active_team_for_agent(agent_id, excluding_team_id=team_id)
            if conflict:
                issues.append(
                    _issue(
                        "error",
                        "agent_team_conflict",
                        f"Agent 已属于团队 {conflict.get('name') or conflict.get('teamId')}，不能同时加入当前团队。",
                        node_id=node_id,
                    )
                )
    for edge in edges:
        edge_id = str(edge.get("id") or "").strip()
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source not in node_ids or target not in node_ids:
            issues.append(_issue("error", "missing_edge_endpoint", "组织关系线引用了不存在的节点。", edge_id=edge_id, source=source, target=target))
    errors = [item for item in issues if item.get("severity") == "error"]
    warnings = [item for item in issues if item.get("severity") == "warning"]
    return {
        "valid": not errors,
        "summary": {"errorCount": len(errors), "warningCount": len(warnings), "issueCount": len(issues)},
        "issues": issues,
    }


def _normalize_members(items: list[dict[str, Any]], *, require_active: bool) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=not require_active)
        if not agent:
            if require_active:
                raise TeamServiceError(f"Team member Agent is not active: {agent_id}")
            continue
        seen.add(agent_id)
        members.append(
            {
                "memberId": _safe_token(item.get("memberId"), default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or "").strip(),
                "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
                "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
                "responsibilities": [
                    trim_lines(value, max_lines=2).strip()
                    for value in list(item.get("responsibilities") or [])[:8]
                    if str(value or "").strip()
                ],
                "agentStatus": "active",
            }
        )
    return members


def _ensure_members_can_join_team(members: list[dict[str, Any]], state: dict[str, Any], team_id: str) -> None:
    for member in members:
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        conflict = _find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=team_id)
        if conflict:
            conflict_label = str(conflict.get("name") or conflict.get("teamId") or "").strip()
            _record_team_membership_conflict(team_id, agent_id, conflict)
            raise TeamServiceError(f"Agent already belongs to Team {conflict_label}: {agent_id}")


def _ensure_evolution_system_agents() -> dict[str, list[dict[str, Any]]]:
    project_root = Path(PROJECT_ROOT).resolve()
    ensured: dict[str, list[dict[str, Any]]] = {"self_evolution": [], "supervised_evolution": []}
    try:
        from . import self_evolution_control_service

        previous_root = self_evolution_control_service.PROJECT_ROOT
        self_evolution_control_service.PROJECT_ROOT = project_root
        try:
            ensured["self_evolution"] = list(self_evolution_control_service.ensure_self_evolution_agent_instances())
        finally:
            self_evolution_control_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        _record_system_team_sync_failed("self_evolution", exc)
    try:
        from . import supervised_agent_service

        previous_root = supervised_agent_service.PROJECT_ROOT
        supervised_agent_service.PROJECT_ROOT = project_root
        try:
            ensured["supervised_evolution"] = list(supervised_agent_service.ensure_supervised_agent_instances())
        finally:
            supervised_agent_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        _record_system_team_sync_failed("supervised_evolution", exc)
    return ensured


def _ensure_ai_search_system_agents() -> list[dict[str, Any]]:
    project_root = Path(PROJECT_ROOT).resolve()
    ensured: list[dict[str, Any]] = []
    try:
        from . import session_service

        previous_root = session_service.PROJECT_ROOT
        session_service.PROJECT_ROOT = project_root
        try:
            for role in AI_SEARCH_SYSTEM_ROLES:
                agent = _ensure_ai_search_role_agent(role, session_service=session_service)
                if agent:
                    ensured.append(agent)
        finally:
            session_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        _record_system_team_sync_failed("ai_search", exc)
    return ensured


def _ensure_challenge_cup_research_team_role_agents() -> list[dict[str, Any]]:
    project_root = Path(PROJECT_ROOT).resolve()
    ensured: list[dict[str, Any]] = []
    try:
        from . import session_service

        previous_root = session_service.PROJECT_ROOT
        session_service.PROJECT_ROOT = project_root
        try:
            for role in CHALLENGE_CUP_RESEARCH_TEAM_ROLES:
                agent = _ensure_challenge_cup_research_team_role_agent(role, session_service=session_service)
                if agent:
                    ensured.append(agent)
        finally:
            session_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        _record_system_team_sync_failed("challenge_cup_research_team", exc)
        raise
    return ensured


def _ensure_challenge_cup_research_team_role_agent(role: dict[str, Any], *, session_service: Any) -> dict[str, Any] | None:
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    if not role_name or not role_key:
        return None

    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        agent_directory_service.repair_agent_directory()
        existing = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID, include_archived=False)
    else:
        existing = _find_challenge_cup_research_team_agent(role_name)

    if existing and not _agent_direct_session_available(existing, session_service=session_service):
        session_service.ensure_agent_direct_session(
            agent_id=str(existing.get("agentId") or ""),
            title=label,
            created_by=CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
        )
        existing = agent_directory_service.get_agent(str(existing.get("agentId") or ""), include_archived=False)

    if not existing or not str(existing.get("directSessionId") or "").strip():
        session_detail = session_service.create_chat_session(
            title=label,
            llm_bindings=session_service.default_session_llm_bindings(),
            created_by=CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY,
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise TeamServiceError(f"Challenge Cup role Agent was not created for role: {role_name}")

    if str(existing.get("status") or "active").strip() == "archived":
        existing = agent_directory_service.reactivate_agent_instance(
            str(existing.get("agentId") or ""),
            reason="challenge_cup_research_team_required",
            metadata=_challenge_cup_research_team_role_metadata(role),
        )

    agent_id = str(existing.get("agentId") or "").strip()
    if not agent_id:
        return None
    expected_metadata = _challenge_cup_research_team_role_metadata(role)
    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        prompt_template_id = agent_directory_service.KNOWLEDGE_STEWARD_PROMPT_TEMPLATE_ID
    else:
        prompt_template_id = (
            agent_directory_service.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS.get(role_key, "")
            or "prompt-chat-default"
        )
    tool_policy = None
    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        tool_policy = agent_directory_service._knowledge_steward_tool_policy()
    elif role_key in agent_directory_service.RESEARCH_SOURCE_ROLE_TOOL_PROFILES:
        tool_policy = agent_directory_service.default_research_source_tool_policy(
            str(existing.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    else:
        tool_policy = agent_directory_service.default_research_role_tool_policy(
            str(existing.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    update_kwargs: dict[str, Any] = {
        "display_name": label,
        "primary_mode": "research",
        "role_key": role_key,
        "metadata": expected_metadata,
        "status": "active",
    }
    if prompt_template_id:
        update_kwargs["prompt_template_id"] = prompt_template_id
    if tool_policy is not None:
        update_kwargs["tool_policy"] = tool_policy
    existing = agent_directory_service.update_agent_instance(agent_id, **update_kwargs)
    return existing


def _ensure_knowledge_expansion_team_role_agents() -> list[dict[str, Any]]:
    project_root = Path(PROJECT_ROOT).resolve()
    ensured: list[dict[str, Any]] = []
    try:
        from . import session_service

        previous_root = session_service.PROJECT_ROOT
        session_service.PROJECT_ROOT = project_root
        try:
            for role in KNOWLEDGE_EXPANSION_TEAM_ROLES:
                agent = _ensure_knowledge_expansion_team_role_agent(role, session_service=session_service)
                if agent:
                    ensured.append(agent)
        finally:
            session_service.PROJECT_ROOT = previous_root
    except Exception as exc:
        _record_system_team_sync_failed("knowledge_expansion_team", exc)
        raise
    return ensured


def _ensure_knowledge_expansion_team_role_agent(role: dict[str, Any], *, session_service: Any) -> dict[str, Any] | None:
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    if not role_name or not role_key:
        return None

    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        agent_directory_service.repair_agent_directory()
        existing = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID, include_archived=False)
    else:
        existing = _find_knowledge_expansion_team_agent(role_name)

    if existing and not _agent_direct_session_available(existing, session_service=session_service):
        session_service.ensure_agent_direct_session(
            agent_id=str(existing.get("agentId") or ""),
            title=label,
            created_by=KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY,
        )
        existing = agent_directory_service.get_agent(str(existing.get("agentId") or ""), include_archived=False)

    if not existing or not str(existing.get("directSessionId") or "").strip():
        session_detail = session_service.create_chat_session(
            title=label,
            llm_bindings=session_service.default_session_llm_bindings(),
            created_by=KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY,
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise TeamServiceError(f"Knowledge expansion role Agent was not created for role: {role_name}")

    if str(existing.get("status") or "active").strip() == "archived":
        existing = agent_directory_service.reactivate_agent_instance(
            str(existing.get("agentId") or ""),
            reason="knowledge_expansion_team_required",
            metadata=_knowledge_expansion_team_role_metadata(role),
        )

    agent_id = str(existing.get("agentId") or "").strip()
    if not agent_id:
        return None
    expected_metadata = _knowledge_expansion_team_role_metadata(role)
    prompt_template_id = (
        agent_directory_service.KNOWLEDGE_EXPANSION_ROLE_PROMPT_TEMPLATE_IDS.get(role_key, "")
        or "prompt-chat-default"
    )
    if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        tool_policy = agent_directory_service._knowledge_steward_tool_policy()
    elif role_key in agent_directory_service.RESEARCH_SOURCE_ROLE_KEYS:
        tool_policy = agent_directory_service.default_research_source_tool_policy(
            str(existing.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    else:
        tool_policy = agent_directory_service.default_research_role_tool_policy(
            str(existing.get("toolPolicyId") or f"tool-{agent_id}"),
            role_key=role_key,
        )
    update_kwargs: dict[str, Any] = {
        "display_name": label,
        "primary_mode": "research",
        "role_key": role_key,
        "metadata": expected_metadata,
        "status": "active",
        "tool_policy": tool_policy,
    }
    if prompt_template_id:
        update_kwargs["prompt_template_id"] = prompt_template_id
    return agent_directory_service.update_agent_instance(agent_id, **update_kwargs)


def _agent_direct_session_available(agent: dict[str, Any], *, session_service: Any) -> bool:
    session_id = str(agent.get("directSessionId") or "").strip()
    if not session_id:
        return False
    try:
        return bool(session_service.get_session_detail(session_id))
    except Exception:
        return False


def _find_challenge_cup_research_team_agent(role_name: str) -> dict[str, Any] | None:
    normalized_role = str(role_name or "").strip()
    if not normalized_role:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if (
            str(metadata.get("challengeCupTeamId") or "").strip() == CHALLENGE_CUP_RESEARCH_TEAM_ID
            and str(metadata.get("challengeCupTeamRole") or "").strip() == normalized_role
            and int(metadata.get("challengeCupTeamManagedVersion") or 0) >= 1
        ):
            return agent
    return None


def _find_knowledge_expansion_team_agent(role_name: str) -> dict[str, Any] | None:
    normalized_role = str(role_name or "").strip()
    if not normalized_role:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if (
            str(metadata.get("knowledgeExpansionTeamId") or "").strip() == KNOWLEDGE_EXPANSION_TEAM_ID
            and str(metadata.get("knowledgeExpansionTeamRole") or "").strip() == normalized_role
            and int(metadata.get("knowledgeExpansionTeamManagedVersion") or 0) >= 1
        ):
            return agent
    return None


def _challenge_cup_research_team_role_metadata(role: dict[str, Any]) -> dict[str, Any]:
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    responsibilities = [
        str(item or "").strip()
        for item in list(role.get("responsibilities") or [])
        if str(item or "").strip()
    ]
    return {
        "agentMode": "research",
        "configSurface": "team",
        "fixedRole": True,
        "showInSessionIndex": True,
        "directSessionVisibility": "active_session",
        "challengeCupTeamId": CHALLENGE_CUP_RESEARCH_TEAM_ID,
        "challengeCupTeamManagedVersion": 1,
        "challengeCupTeamRole": role_name,
        "challengeCupTeamRoleKey": role_key,
        "researchTeamRole": role_name,
        "researchTeamRoleKey": role_key,
        "researchAgentKey": role_key,
        "functionalDisplayName": label,
        "managedDomain": "challenge_cup_neuro_algorithm",
        "responsibilities": responsibilities,
    }


def _knowledge_expansion_team_role_metadata(role: dict[str, Any]) -> dict[str, Any]:
    role_name = str(role.get("role") or "").strip()
    role_key = str(role.get("roleKey") or role_name).strip()
    label = str(role.get("label") or role_name).strip() or role_name
    responsibilities = [
        str(item or "").strip()
        for item in list(role.get("responsibilities") or [])
        if str(item or "").strip()
    ]
    return {
        "agentMode": "research",
        "configSurface": "team",
        "fixedRole": True,
        "showInSessionIndex": True,
        "directSessionVisibility": "active_session",
        "knowledgeExpansionTeamId": KNOWLEDGE_EXPANSION_TEAM_ID,
        "knowledgeExpansionTeamManagedVersion": 1,
        "knowledgeExpansionTeamRole": role_name,
        "knowledgeExpansionTeamRoleKey": role_key,
        "researchTeamRole": role_name,
        "researchTeamRoleKey": role_key,
        "researchAgentKey": role_key,
        "functionalDisplayName": label,
        "managedDomain": "team_knowledge_expansion",
        "responsibilities": responsibilities,
    }


def _challenge_cup_research_team_members_from_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agents_by_role: dict[str, dict[str, Any]] = {}
    for agent in agents:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("challengeCupTeamRole") or "").strip()
        if role:
            agents_by_role[role] = agent
    members: list[dict[str, Any]] = []
    for index, role in enumerate(CHALLENGE_CUP_RESEARCH_TEAM_ROLES, start=1):
        role_name = str(role.get("role") or "").strip()
        agent = agents_by_role.get(role_name)
        agent_id = str((agent or {}).get("agentId") or "").strip()
        if not agent_id:
            continue
        members.append(
            {
                "memberId": f"challenge-cup-{index:02d}-{role_name}",
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or role.get("label") or "").strip(),
                "role": role_name,
                "purpose": str(role.get("purpose") or role.get("label") or "").strip(),
                "responsibilities": [
                    str(item or "").strip()
                    for item in list(role.get("responsibilities") or [])
                    if str(item or "").strip()
                ],
                "agentStatus": "active",
            }
        )
    return members


def _knowledge_expansion_team_members_from_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agents_by_role: dict[str, dict[str, Any]] = {}
    for agent in agents:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("knowledgeExpansionTeamRole") or "").strip()
        if role:
            agents_by_role[role] = agent
    members: list[dict[str, Any]] = []
    for index, role in enumerate(KNOWLEDGE_EXPANSION_TEAM_ROLES, start=1):
        role_name = str(role.get("role") or "").strip()
        agent = agents_by_role.get(role_name)
        agent_id = str((agent or {}).get("agentId") or "").strip()
        if not agent_id:
            continue
        members.append(
            {
                "memberId": f"knowledge-expansion-{index:02d}-{role_name}",
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or role.get("label") or "").strip(),
                "role": role_name,
                "purpose": str(role.get("purpose") or role.get("label") or "").strip(),
                "responsibilities": [
                    str(item or "").strip()
                    for item in list(role.get("responsibilities") or [])
                    if str(item or "").strip()
                ],
                "agentStatus": "active",
            }
        )
    return members


def _challenge_cup_research_team_bound_agent_ids() -> set[str]:
    agent_ids: set[str] = set()
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, CHALLENGE_CUP_RESEARCH_TEAM_ID)
        if team:
            for member in list(team.get("members") or []):
                if isinstance(member, dict):
                    agent_id = str(member.get("agentId") or "").strip()
                    if agent_id:
                        agent_ids.add(agent_id)
        canvas_path = _team_canvas_path(CHALLENGE_CUP_RESEARCH_TEAM_ID)
        canvas = _read_json(canvas_path) if canvas_path.exists() else {}
        for node in list(canvas.get("nodes") or []):
            if isinstance(node, dict):
                agent_id = str(node.get("agentId") or "").strip()
                if agent_id:
                    agent_ids.add(agent_id)
    return agent_ids


def _challenge_cup_research_team_duplicate_agent_ids(expected_agent_ids: set[str]) -> set[str]:
    duplicates: set[str] = set()
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id in expected_agent_ids:
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("challengeCupTeamId") or "").strip() == CHALLENGE_CUP_RESEARCH_TEAM_ID:
            duplicates.add(agent_id)
    return duplicates


def _purge_challenge_cup_research_team_agents(agent_ids: list[str], *, project_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        from . import session_service
    except Exception:
        session_service = None
    previous_root = getattr(session_service, "PROJECT_ROOT", None) if session_service else None
    if session_service:
        session_service.PROJECT_ROOT = project_root
    try:
        for agent_id in agent_ids:
            result = _purge_challenge_cup_research_team_agent(agent_id, session_service=session_service)
            if result:
                results.append(result)
    finally:
        if session_service and previous_root is not None:
            session_service.PROJECT_ROOT = previous_root
    return results


def _purge_challenge_cup_research_team_agent(agent_id: str, *, session_service: Any | None) -> dict[str, Any] | None:
    normalized_agent_id = str(agent_id or "").strip()
    if not _safe_agent_workspace_name(normalized_agent_id):
        return None
    agent = agent_directory_service.get_agent(normalized_agent_id, include_archived=True)
    if not agent:
        orphan_result = _delete_orphan_agent_workspace(normalized_agent_id)
        return {
            "agentId": normalized_agent_id,
            "deleted": bool(orphan_result.get("deleted")),
            "orphan": True,
            **orphan_result,
        }
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if bool(metadata.get("protected")) or str(agent.get("agentId") or "") == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID:
        return {"agentId": normalized_agent_id, "deleted": False, "skipped": "protected"}
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    if direct_session_id and session_service:
        try:
            session_service.mark_direct_session_agent_deleted(
                direct_session_id,
                agent_id=normalized_agent_id,
                agent_display_name=str(agent.get("displayName") or ""),
                previous_status=str(agent.get("status") or ""),
            )
        except Exception:
            pass
    try:
        if str(agent.get("status") or "active").strip() != "archived":
            agent_directory_service.archive_agent_instance(normalized_agent_id, repair_mode_bindings=True)
        result = agent_directory_service.purge_archived_agent_instance(normalized_agent_id)
        result["orphan"] = False
        return result
    except Exception as exc:
        return {"agentId": normalized_agent_id, "deleted": False, "orphan": False, "error": str(exc)}


def _delete_orphan_agent_workspace(agent_id: str) -> dict[str, Any]:
    normalized_agent_id = str(agent_id or "").strip()
    if not _safe_agent_workspace_name(normalized_agent_id):
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [normalized_agent_id]}
    agents_root = developer_sandbox.seeded_sandbox_workspace_path(_project_root(), "agents").resolve()
    target = (agents_root / normalized_agent_id).resolve()
    if agents_root not in target.parents:
        return {"deleted": False, "deletedPaths": [], "skippedPaths": [str(target)]}
    if not target.exists():
        return {"deleted": False, "deletedPaths": [], "skippedPaths": []}
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"deleted": True, "deletedPaths": [str(target)], "skippedPaths": []}


def _safe_agent_workspace_name(value: str) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized) and _SAFE_ID_FRAGMENT.sub("", normalized) == normalized and normalized not in {".", ".."}


def _ensure_ai_search_role_agent(role: dict[str, Any], *, session_service: Any) -> dict[str, Any] | None:
    role_key = str(role.get("role") or "").strip()
    label = str(role.get("label") or role_key).strip() or role_key
    if not role_key:
        return None
    existing = _find_agent_by_ai_search_role(role_key)
    if not existing:
        session_detail = session_service.create_chat_session(
            title=label,
            llm_bindings=session_service.default_session_llm_bindings(),
            created_by="ai_search_team",
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise RuntimeError(f"AI search role Agent was not created for role: {role_key}")
    if str(existing.get("status") or "active").strip() == "archived":
        existing = agent_directory_service.reactivate_agent_instance(
            str(existing.get("agentId") or ""),
            reason="ai_search_team_required",
            metadata={"protected": True, "fixedRole": True},
        )
    metadata = dict(existing.get("metadata") or {})
    expected_metadata = _ai_search_role_metadata(role)
    needs_update = (
        str(existing.get("displayName") or "").strip() != label
        or str(existing.get("primaryMode") or "").strip() != "research"
        or str(existing.get("roleKey") or "").strip() != role_key
        or str(existing.get("promptTemplateId") or "").strip() != "prompt-chat-default"
        or any(metadata.get(key) != value for key, value in expected_metadata.items())
    )
    if needs_update:
        existing = agent_directory_service.update_agent_instance(
            str(existing.get("agentId") or ""),
            display_name=label,
            primary_mode="research",
            role_key=role_key,
            prompt_template_id="prompt-chat-default",
            metadata=expected_metadata,
            status="active",
        )
    return existing


def _find_agent_by_ai_search_role(role_key: str) -> dict[str, Any] | None:
    normalized = str(role_key or "").strip()
    if not normalized:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True, detail="summary"):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("aiSearchRole") or "").strip() == normalized:
            return agent
    return None


def _ai_search_role_metadata(role: dict[str, Any]) -> dict[str, Any]:
    role_key = str(role.get("role") or "").strip()
    label = str(role.get("label") or role_key).strip() or role_key
    purpose = str(role.get("purpose") or "").strip()
    responsibilities = [str(item or "").strip() for item in list(role.get("responsibilities") or []) if str(item or "").strip()]
    expertise = [str(item or "").strip() for item in list(role.get("expertise") or []) if str(item or "").strip()]
    return {
        "agentMode": "ai_search",
        "configSurface": "team",
        "fixedRole": True,
        "protected": True,
        "aiSearchRole": role_key,
        "aiSearchRoleLabel": label,
        "functionalDisplayName": label,
        "managedDomain": "ai_latest_news_source_scope",
        "personaProfile": {
            "personality": "证据优先、克制、偏好一手来源和可复盘边界。",
            "communicationStyle": "先说明来源可信度，再给纳入、默认启用或仅作信号的判断。",
            "background": "维护 AI 最新动态一键搜索的来源范围名单，避免搜索结果被噪声和非一手信息污染。",
            "expertise": expertise,
        },
        "taskProfile": {
            "mission": purpose,
            "responsibilities": "；".join(responsibilities) or purpose,
            "preferredTasks": "维护 AI 动态搜索源白名单、标注地区/语言/Tier/evidenceRole/enabledByDefault，并发现缺源或噪声源。",
            "avoidTasks": "不要把新闻、社区或社交信号直接当结论；不要自动发布、删除来源或写入正式知识库。",
            "successCriteria": "每个来源都有稳定 id、入口 URL、可信度层级、证据角色、默认启用状态和人工说明。",
            "deliverables": "搜索范围名单更新建议、缺源清单、信号源质检结论和一手证据回链要求。",
            "constraints": "本团队只维护搜索范围和来源质量，不执行真实发布、远程写入或知识库审批。",
        },
    }


def _ai_search_members_from_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agents_by_role: dict[str, dict[str, Any]] = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role_key = str(metadata.get("aiSearchRole") or agent.get("roleKey") or "").strip()
        if role_key:
            agents_by_role[role_key] = agent
    members: list[dict[str, Any]] = []
    for index, role in enumerate(AI_SEARCH_SYSTEM_ROLES, start=1):
        role_key = str(role.get("role") or "").strip()
        agent = agents_by_role.get(role_key)
        agent_id = str((agent or {}).get("agentId") or "").strip()
        if not agent_id:
            continue
        members.append(
            {
                "memberId": f"ai-search-{index}",
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or role.get("label") or "").strip(),
                "role": role_key,
                "purpose": str(role.get("label") or "").strip(),
                "responsibilities": list(role.get("responsibilities") or []),
                "agentStatus": "active",
            }
        )
    return members


def _ensure_evolution_system_team_in_state(
    state: dict[str, Any],
    spec: dict[str, str],
    ensured_agents: dict[str, list[dict[str, Any]]],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    team_id = str(spec.get("teamId") or "").strip()
    source = str(spec.get("source") or "").strip()
    if not team_id or not source:
        return None, False
    members = _system_members_from_agents(ensured_agents.get(source) or [], source=source)
    members = _members_without_cross_team_conflicts(members, state, team_id, source=source)
    now = utc_now_iso()
    team = _find_team(state, team_id)
    created = team is None
    changed = created
    if team is None:
        team = {
            "teamId": team_id,
            "name": str(spec.get("name") or team_id).strip(),
            "description": str(spec.get("description") or "").strip(),
            "purpose": str(spec.get("purpose") or "").strip(),
            "status": DEFAULT_TEAM_STATUS,
            "members": members,
            "linkedChatRoomId": "",
            "canvasPath": _relative_path(_team_canvas_path(team_id)),
            "systemTeamKind": source,
            "teamKind": str(spec.get("teamKind") or source).strip(),
            "teamCategory": str(spec.get("teamCategory") or "").strip(),
            "teamSource": str(spec.get("teamSource") or source).strip(),
            "teamTemplateId": "",
            "createdAt": now,
            "updatedAt": now,
        }
        _apply_team_contract(
            team,
            team_kind=str(spec.get("teamKind") or source),
            team_category=str(spec.get("teamCategory") or ""),
            team_source=str(spec.get("teamSource") or source),
        )
        state.setdefault("teams", []).append(team)
    else:
        expected = {
            "name": str(spec.get("name") or team_id).strip(),
            "description": str(spec.get("description") or "").strip(),
            "purpose": str(spec.get("purpose") or "").strip(),
            "status": DEFAULT_TEAM_STATUS,
            "members": members,
            "canvasPath": _relative_path(_team_canvas_path(team_id)),
            "systemTeamKind": source,
            "teamKind": str(spec.get("teamKind") or source).strip(),
            "teamCategory": str(spec.get("teamCategory") or "").strip(),
            "teamSource": str(spec.get("teamSource") or source).strip(),
            "teamTemplateId": "",
        }
        for key, value in expected.items():
            if team.get(key) != value:
                team[key] = value
                changed = True
        if _apply_team_contract(
            team,
            team_kind=str(spec.get("teamKind") or source),
            team_category=str(spec.get("teamCategory") or ""),
            team_source=str(spec.get("teamSource") or source),
        ):
            changed = True
        if changed:
            team["updatedAt"] = now
    canvas_path = _team_canvas_path(team_id)
    if changed or not canvas_path.exists() or _default_canvas_edges_missing_for_team(team, canvas_path):
        _write_json(canvas_path, _default_canvas_for_team(team))
    if _team_chat_room_needs_sync(team, agent_refs=agent_refs):
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        changed = True
    if changed:
        _record_team_event(
            "team.system_evolution_synced",
            team,
            fields={"created": created, "source": source, "memberCount": len(members)},
        )
    return team, changed


def _system_members_from_agents(agents: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, agent in enumerate(agents[:120]):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if str(agent.get("status") or "active").strip() == "archived":
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(agent.get("roleKey") or "").strip()
        role_label = ""
        if source == "self_evolution":
            role = str(metadata.get("selfEvolutionRole") or role).strip()
            role_label = str(metadata.get("selfEvolutionRoleLabel") or "").strip()
        elif source == "supervised_evolution":
            role = str(metadata.get("supervisedRole") or role).strip()
            role_label = str(metadata.get("supervisedRoleLabel") or "").strip()
        seen.add(agent_id)
        members.append(
            {
                "memberId": _safe_token(f"{source}-{role or index + 1}", default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or role_label or agent_id).strip(),
                "role": role,
                "purpose": role_label,
                "agentStatus": "active",
            }
        )
    return members


def _members_without_cross_team_conflicts(
    members: list[dict[str, Any]],
    state: dict[str, Any],
    team_id: str,
    *,
    source: str,
) -> list[dict[str, Any]]:
    available: list[dict[str, Any]] = []
    for member in members:
        agent_id = str(member.get("agentId") or "").strip()
        conflict = _find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=team_id)
        if conflict:
            _record_system_team_membership_conflict(team_id, agent_id, conflict, source=source)
            continue
        available.append(member)
    return available


def _find_active_team_for_agent(agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
    state = _load_index()
    return _find_active_team_for_agent_in_state(state, agent_id, excluding_team_id=excluding_team_id)


def _find_active_team_for_agent_in_state(state: dict[str, Any], agent_id: str, *, excluding_team_id: str = "") -> dict[str, Any] | None:
    normalized_agent_id = str(agent_id or "").strip()
    normalized_excluding_team_id = str(excluding_team_id or "").strip()
    if not normalized_agent_id:
        return None
    for team in list(state.get("teams") or []):
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("teamId") or "").strip()
        if team_id == normalized_excluding_team_id:
            continue
        if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
            continue
        for member in list(team.get("members") or []):
            if isinstance(member, dict) and str(member.get("agentId") or "").strip() == normalized_agent_id:
                return team
    return None


def _unique_active_member_agent_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    agent_ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        agent = _agent_reference(agent_id, include_archived=True, agent_refs=agent_refs)
        if not agent or str(agent.get("status") or "active").strip() == "archived":
            continue
        seen.add(agent_id)
        agent_ids.append(agent_id)
    return agent_ids


def _team_kind_allows_member_agent_cascade(team: dict[str, Any]) -> bool:
    return str(team.get("teamKind") or _infer_team_kind(team)).strip() in {"custom", "template_demo"}


def _ensure_team_member_agents_can_archive(team: dict[str, Any], agent_ids: list[str]) -> None:
    for agent_id in agent_ids:
        try:
            agent_directory_service.ensure_agent_archive_allowed(agent_id)
        except agent_directory_service.AgentDirectoryError as exc:
            _record_team_archive_rejected(team, reason="agent_archive_rejected", agent_id=agent_id, error=exc)
            raise TeamServiceError(str(exc)) from exc


def _archive_team_member_agents(team: dict[str, Any], agent_ids: list[str], *, reason: str) -> list[str]:
    archived_agent_ids: list[str] = []
    for agent_id in agent_ids:
        archived_agent = agent_directory_service.archive_agent_instance(agent_id)
        archived_agent_ids.append(str(archived_agent.get("agentId") or agent_id).strip())
    if archived_agent_ids and reason != "team_archive":
        _record_archived_team_member_cascade_repaired(team, archived_agent_ids, reason=reason)
    return archived_agent_ids


def _remove_team_member_agents_from_chat_rooms(team: dict[str, Any], agent_ids: list[str]) -> dict[str, Any]:
    if not agent_ids:
        return {"agentIds": [], "changedRoomIds": [], "removedByAgentId": {}}
    try:
        return chat_room_service.remove_agents_from_chat_rooms(
            agent_ids,
            allow_empty_rooms=True,
            include_chat_rooms=False,
            repair_participants=False,
        )
    except chat_room_service.ChatRoomBusyError as exc:
        _record_team_archive_rejected(team, reason="chat_room_busy", error=exc)
        raise TeamServiceError(str(exc)) from exc
    except chat_room_service.ChatRoomValidationError as exc:
        _record_team_archive_rejected(team, reason="chat_room_cleanup_rejected", error=exc)
        raise TeamServiceError(str(exc)) from exc


def _repair_archived_team_member_agents(
    state: dict[str, Any],
    *,
    reason: str,
    strict: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    changed = False
    for team in list(state.get("teams") or []):
        if isinstance(team, dict):
            changed = _repair_archived_team_member_agents_for_team(
                team,
                state,
                reason=reason,
                strict=strict,
                agent_refs=agent_refs,
            ) or changed
    return changed


def _repair_archived_team_member_agents_for_team(
    team: dict[str, Any],
    state: dict[str, Any],
    *,
    reason: str,
    strict: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
        return False
    if not _team_kind_allows_member_agent_cascade(team):
        return False
    changed = _prune_missing_archived_team_members(team, agent_refs=agent_refs)
    agent_ids = _unique_active_member_agent_ids(team, agent_refs=agent_refs)
    if not agent_ids:
        if changed:
            team["updatedAt"] = utc_now_iso()
            state["updatedAt"] = team["updatedAt"]
        return changed
    try:
        _ensure_team_member_agents_can_archive(team, agent_ids)
    except TeamServiceError:
        if strict:
            raise
        return changed
    try:
        _remove_team_member_agents_from_chat_rooms(team, agent_ids)
    except TeamServiceError:
        if strict:
            raise
        return changed
    _archive_team_member_agents(team, agent_ids, reason=reason)
    team["updatedAt"] = utc_now_iso()
    state["updatedAt"] = team["updatedAt"]
    return True


def _prune_missing_archived_team_members(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    kept_members: list[dict[str, Any]] = []
    removed_agent_ids: list[str] = []
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        if _agent_reference(agent_id, include_archived=True, agent_refs=agent_refs):
            kept_members.append(member)
            continue
        removed_agent_ids.append(agent_id)
    if not removed_agent_ids:
        return False
    team["members"] = kept_members
    _record_team_event(
        "team.archived_missing_members_pruned",
        team,
        fields={
            "removedAgentIds": removed_agent_ids,
            "removedAgentCount": len(removed_agent_ids),
        },
    )
    return True


def _sync_members_from_canvas(current_members: list[dict[str, Any]], canvas: dict[str, Any]) -> list[dict[str, Any]]:
    by_agent = {
        str(member.get("agentId") or "").strip(): dict(member)
        for member in current_members
        if isinstance(member, dict) and str(member.get("agentId") or "").strip()
    }
    for index, node in enumerate(canvas.get("nodes") or []):
        agent_id = str(node.get("agentId") or "").strip()
        if not agent_id:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=True)
        if not agent:
            continue
        member = by_agent.get(agent_id) or {"memberId": f"member-{index + 1}", "agentId": agent_id}
        member.update(
            {
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or "").strip(),
                "role": str(node.get("role") or member.get("role") or "").strip(),
                "purpose": str(node.get("purpose") or member.get("purpose") or "").strip(),
                "agentStatus": "active" if str(agent.get("status") or "active") != "archived" else "stale",
            }
        )
        if isinstance(node.get("responsibilities"), list):
            member["responsibilities"] = [
                trim_lines(value, max_lines=2).strip()
                for value in list(node.get("responsibilities") or [])[:8]
                if str(value or "").strip()
            ]
        by_agent[agent_id] = member
    return list(by_agent.values())


def _members_from_research_organization(organization: dict[str, Any]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(list(organization.get("agents") or [])[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen or str(item.get("status") or "active").strip() == "archived":
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            continue
        seen.add(agent_id)
        function_label = _research_member_function_label(item, agent)
        responsibilities = _research_member_responsibilities(item, agent)
        members.append(
            {
                "memberId": _safe_token(item.get("nodeId") or agent_id, default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or item.get("agentCode") or "").strip(),
                "agentName": str(agent.get("displayName") or item.get("displayName") or "").strip(),
                "role": str(item.get("role") or ((agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {}).get("researchOrgRole") or "").strip(),
                "purpose": function_label,
                "responsibilities": responsibilities,
                "agentStatus": "active",
            }
        )
    return members


def _sync_research_team_member_agent_roles(members: list[dict[str, Any]]) -> bool:
    changed = False
    for member in members:
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        role = _safe_token(member.get("role"), default="", max_length=96)
        role_key = RESEARCH_TEAM_MEMBER_ROLE_KEYS.get(role)
        if not agent_id or not role_key:
            continue
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        expected_metadata = {
            "agentMode": "research",
            "configSurface": "team",
            "researchTeamRole": role,
            "researchTeamRoleKey": role_key,
        }
        current_policy = agent_directory_service.resolve_tool_policy_for_agent(agent_id)
        if role_key == agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
            expected_policy = agent_directory_service._knowledge_steward_tool_policy()
        elif role_key in agent_directory_service.RESEARCH_SOURCE_ROLE_TOOL_PROFILES:
            expected_policy = agent_directory_service.default_research_source_tool_policy(
                str(agent.get("toolPolicyId") or f"tool-{agent_id}"),
                role_key=role_key,
            )
        else:
            expected_policy = agent_directory_service.default_research_role_tool_policy(
                str(agent.get("toolPolicyId") or f"tool-{agent_id}"),
                role_key=role_key,
            )
        needs_update = (
            str(agent.get("primaryMode") or "").strip() != "research"
            or str(agent.get("roleKey") or "").strip() != role_key
            or any(metadata.get(key) != value for key, value in expected_metadata.items())
            or list(current_policy.get("allowedTools") or []) != list(expected_policy.get("allowedTools") or [])
            or current_policy.get("mutationAccess") != expected_policy.get("mutationAccess")
            or list(current_policy.get("writeScopes") or []) != list(expected_policy.get("writeScopes") or [])
        )
        if not needs_update:
            continue
        agent_directory_service.update_agent_instance(
            agent_id,
            primary_mode="research",
            role_key=role_key,
            tool_policy=expected_policy,
            metadata=expected_metadata,
            status="active",
        )
        changed = True
    return changed


def _canvas_from_research_organization(organization: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    members_by_agent_id = {
        str(member.get("agentId") or "").strip(): member
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("agentId") or "").strip()
    }
    nodes: list[dict[str, Any]] = []
    for index, item in enumerate(list(organization.get("agents") or [])[:120]):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        member = members_by_agent_id.get(agent_id)
        if not member:
            continue
        nodes.append(
            {
                "id": _safe_token(agent_id, default=f"node-{index + 1}", max_length=96),
                "label": str(item.get("displayName") or member.get("agentName") or agent_id).strip(),
                "type": "agent",
                "status": "bound",
                "x": _safe_float(item.get("x"), 120.0 + index * 220.0),
                "y": _safe_float(item.get("y"), 120.0),
                "agentId": agent_id,
                "agentCode": str(item.get("agentCode") or member.get("agentCode") or "").strip(),
                "agentName": str(member.get("agentName") or item.get("displayName") or "").strip(),
                "role": str(member.get("role") or "").strip(),
                "purpose": str(member.get("purpose") or "").strip(),
                "responsibilities": list(member.get("responsibilities") or [])[:8],
            }
        )
    node_ids = {str(node.get("id") or "") for node in nodes}
    edges: list[dict[str, Any]] = _organization_reporting_edges(organization, nodes)
    for index, item in enumerate(list(organization.get("edges") or [])[:240]):
        if not isinstance(item, dict) or str(item.get("status") or "active").strip() == "archived":
            continue
        source = _safe_token(item.get("fromAgentId") or item.get("source"), default="", max_length=96)
        target = _safe_token(item.get("toAgentId") or item.get("target"), default="", max_length=96)
        if source not in node_ids or target not in node_ids:
            continue
        edges.append(
            {
                "id": _safe_token(item.get("edgeId") or item.get("id"), default=f"edge-{index + 1}", max_length=96),
                "source": source,
                "target": target,
                "label": trim_lines(item.get("label") or "组织通信", max_lines=1).strip(),
                "type": "communication",
            }
        )
    return _normalize_canvas(
        {
            "schemaVersion": SCHEMA_VERSION,
            "canvasKind": CANVAS_KIND,
            "teamId": team["teamId"],
            "updatedAt": str(organization.get("updatedAt") or team.get("updatedAt") or utc_now_iso()),
            "path": _relative_path(_team_canvas_path(team["teamId"])),
            "viewport": {"x": 40, "y": 80, "zoom": 1},
            "nodes": nodes,
            "edges": edges,
        },
        team,
    )


def _organization_reporting_edges(organization: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_ids = {str(node.get("id") or "").strip() for node in nodes if str(node.get("id") or "").strip()}
    if len(node_ids) < 2:
        return []
    source_items = [
        item for item in list(organization.get("agents") or [])
        if isinstance(item, dict)
        and str(item.get("status") or "active").strip() != "archived"
        and str(item.get("agentId") or "").strip() in node_ids
    ]
    nodes_by_agent_id = {str(node.get("agentId") or "").strip(): node for node in nodes}
    items_by_agent_id = {str(item.get("agentId") or "").strip(): item for item in source_items}
    role_index: dict[str, str] = {}
    label_index: dict[str, str] = {}
    for item in source_items:
        agent_id = str(item.get("agentId") or "").strip()
        role = _research_org_role(item)
        if role and role not in role_index:
            role_index[role] = agent_id
        for value in (
            item.get("agentCode"),
            item.get("displayName"),
            item.get("role"),
            _research_member_function_label(item, item.get("agent") if isinstance(item.get("agent"), dict) else {}),
        ):
            normalized = _normalize_report_to_reference(value)
            if normalized and normalized not in label_index:
                label_index[normalized] = agent_id
    ceo_agent_id = role_index.get("ceo") or role_index.get("research_ceo") or label_index.get("ceo")
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in source_items:
        target_agent_id = str(item.get("agentId") or "").strip()
        if not target_agent_id:
            continue
        role = _research_org_role(item)
        if role in {"ceo", "research_ceo"}:
            continue
        source_agent_id = _resolve_report_to_agent_id(item, role_index=role_index, label_index=label_index, fallback_agent_id=ceo_agent_id or "")
        if not source_agent_id or source_agent_id == target_agent_id or source_agent_id not in node_ids:
            continue
        pair = (source_agent_id, target_agent_id)
        if pair in seen:
            continue
        seen.add(pair)
        source_node = nodes_by_agent_id.get(source_agent_id) or {}
        target_node = nodes_by_agent_id.get(target_agent_id) or {}
        edges.append(
            {
                "id": _safe_token(f"reports-{source_agent_id}-{target_agent_id}", default=f"reports-{len(edges) + 1}", max_length=96),
                "source": source_agent_id,
                "target": target_agent_id,
                "label": trim_lines(
                    f"{source_node.get('label') or source_agent_id} 管理 {target_node.get('label') or target_agent_id}",
                    max_lines=1,
                ).strip(),
                "type": "reports_to",
            }
        )
    return edges


def _resolve_report_to_agent_id(
    item: dict[str, Any],
    *,
    role_index: dict[str, str],
    label_index: dict[str, str],
    fallback_agent_id: str,
) -> str:
    agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    role_contract = metadata.get("roleContract") if isinstance(metadata.get("roleContract"), dict) else {}
    candidates = [
        item.get("reportToAgentId"),
        item.get("reportsToAgentId"),
        role_contract.get("reportToAgentId"),
        role_contract.get("reportsToAgentId"),
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    report_to = _normalize_report_to_reference(item.get("reportTo") or role_contract.get("reportTo") or "CEO")
    if report_to in role_index:
        return role_index[report_to]
    if report_to in label_index:
        return label_index[report_to]
    aliases = {
        "chiefexecutiveofficer": "ceo",
        "ceoagent": "ceo",
        "organizationadvisor": "organization_advisor",
        "organizationadvisoragent": "organization_advisor",
        "capabilitysteward": "capability_steward",
        "capabilitystewardagent": "capability_steward",
    }
    alias = aliases.get(report_to)
    if alias and alias in role_index:
        return role_index[alias]
    return fallback_agent_id


def _research_org_role(item: dict[str, Any]) -> str:
    agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return str(item.get("role") or metadata.get("researchOrgRole") or metadata.get("systemRole") or "").strip()


def _normalize_report_to_reference(value: Any) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]+", "", str(value or "").strip().lower())
    return normalized


def _research_member_function_label(item: dict[str, Any], agent: dict[str, Any]) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    label = str(metadata.get("functionalDisplayName") or "").strip()
    if label:
        return trim_lines(label, max_lines=1).strip()
    responsibilities = metadata.get("responsibilities")
    if isinstance(responsibilities, list):
        joined = "；".join(str(value).strip() for value in responsibilities[:2] if str(value).strip())
        if joined:
            return trim_lines(joined, max_lines=1).strip()
    return trim_lines(item.get("role") or "科研协作", max_lines=1).strip()


def _research_member_responsibilities(item: dict[str, Any], agent: dict[str, Any]) -> list[str]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    embedded_agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
    embedded_metadata = embedded_agent.get("metadata") if isinstance(embedded_agent.get("metadata"), dict) else {}
    sources = [
        item.get("responsibilities"),
        (item.get("teamMembership") if isinstance(item.get("teamMembership"), dict) else {}).get("responsibilities"),
        embedded_metadata.get("responsibilities"),
        (embedded_metadata.get("teamMembership") if isinstance(embedded_metadata.get("teamMembership"), dict) else {}).get("responsibilities"),
        (embedded_metadata.get("taskProfile") if isinstance(embedded_metadata.get("taskProfile"), dict) else {}).get("responsibilities"),
        metadata.get("responsibilities"),
        (metadata.get("teamMembership") if isinstance(metadata.get("teamMembership"), dict) else {}).get("responsibilities"),
        (metadata.get("taskProfile") if isinstance(metadata.get("taskProfile"), dict) else {}).get("responsibilities"),
        (agent.get("taskProfile") if isinstance(agent.get("taskProfile"), dict) else {}).get("responsibilities"),
    ]
    responsibilities: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for value in _responsibility_values(source):
            normalized = trim_lines(value, max_lines=2).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            responsibilities.append(normalized)
            if len(responsibilities) >= 8:
                return responsibilities
    return responsibilities


def _responsibility_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[；;\n]+", value) if item.strip()]
    return []


def _active_member_agent_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        if not _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs):
            continue
        seen.add(agent_id)
        ids.append(agent_id)
    return ids


def _active_member_session_ids(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[str]:
    session_ids: list[str] = []
    seen: set[str] = set()
    for agent_id in _active_member_agent_ids(team, agent_refs=agent_refs):
        agent = _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs)
        session_id = str((agent or {}).get("directSessionId") or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        session_ids.append(session_id)
    return session_ids


def _team_chat_room_title(team: dict[str, Any]) -> str:
    name = str(team.get("name") or team.get("teamId") or "Team").strip()
    return f"{name} 团队群聊"


def _team_participant_contexts_by_agent_id(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    team_id = str(team.get("teamId") or "").strip()
    team_name = str(team.get("name") or "").strip()
    team_purpose = trim_lines(team.get("purpose") or "", max_lines=4).strip()
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        agent = _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs) or {}
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        responsibilities = []
        if isinstance(member.get("responsibilities"), list):
            responsibilities.extend(str(item).strip() for item in member.get("responsibilities") if str(item).strip())
        if isinstance(metadata.get("responsibilities"), list):
            responsibilities.extend(str(item).strip() for item in metadata.get("responsibilities") if str(item).strip())
        contexts[agent_id] = {
            "teamId": team_id,
            "teamName": team_name,
            "teamPurpose": team_purpose,
            "teamRole": trim_lines(member.get("role") or "", max_lines=1).strip(),
            "teamMemberPurpose": trim_lines(member.get("purpose") or "", max_lines=4).strip(),
            "teamResponsibilities": responsibilities[:8],
        }
    return contexts


def _sync_chat_room_root() -> None:
    if chat_room_service.PROJECT_ROOT != PROJECT_ROOT:
        chat_room_service.PROJECT_ROOT = PROJECT_ROOT


def _apply_team_contract(
    team: dict[str, Any],
    *,
    team_kind: str = "",
    team_category: str = "",
    team_source: str = "",
    team_template_id: str = "",
) -> bool:
    inferred_kind = _infer_team_kind(team, fallback=team_kind)
    defaults = TEAM_KIND_DEFAULTS.get(inferred_kind, TEAM_KIND_DEFAULTS["custom"])
    expected = {
        "teamKind": inferred_kind,
        "teamCategory": trim_lines(team_category or team.get("teamCategory") or defaults["teamCategory"], max_lines=1).strip(),
        "teamSource": str(team_source or team.get("teamSource") or defaults["teamSource"]).strip(),
        "teamTemplateId": str(team_template_id or team.get("teamTemplateId") or "").strip(),
    }
    if expected["teamSource"] in TEAM_SOURCE_TO_KIND:
        expected["teamKind"] = TEAM_SOURCE_TO_KIND[expected["teamSource"]]
    if expected["teamKind"] != "template_demo":
        expected["teamTemplateId"] = ""
    elif not expected["teamTemplateId"]:
        expected["teamTemplateId"] = _infer_team_template_id(team)
    changed = False
    for key, value in expected.items():
        if team.get(key) != value:
            team[key] = value
            changed = True
    return changed


def _infer_team_kind(team: dict[str, Any], *, fallback: str = "") -> str:
    explicit = str(fallback or team.get("teamKind") or "").strip()
    if explicit in TEAM_KIND_DEFAULTS:
        return explicit
    source = str(team.get("teamSource") or team.get("systemTeamKind") or "").strip()
    if source in TEAM_SOURCE_TO_KIND:
        return TEAM_SOURCE_TO_KIND[source]
    team_id = str(team.get("teamId") or "").strip()
    if team_id in TEAM_ID_TO_KIND:
        return TEAM_ID_TO_KIND[team_id]
    if _infer_team_template_id(team):
        return "template_demo"
    return "custom"


def _infer_team_template_id(team: dict[str, Any]) -> str:
    template_id = str(team.get("teamTemplateId") or "").strip()
    if template_id:
        return template_id
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        member_id = str(member.get("memberId") or "").strip()
        for prefix, candidate in TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID.items():
            if member_id.startswith(f"{prefix}-"):
                return candidate
    return ""


def _team_default_chat_room_purpose(team: dict[str, Any]) -> str:
    kind = _infer_team_kind(team)
    if kind == "template_demo":
        template_id = str(team.get("teamTemplateId") or _infer_team_template_id(team)).strip()
        if template_id == "medical-consultation-demo":
            return "medical_triage"
        if template_id == "heletech-maternal-digital-health-demo":
            return "meeting"
    return str(TEAM_KIND_DEFAULTS.get(kind, TEAM_KIND_DEFAULTS["custom"]).get("chatRoomPurpose") or "discussion")


def _team_chat_room_purpose_for_update(team: dict[str, Any], current_purpose: Any) -> str:
    normalized_current = str(current_purpose or "").strip()
    expected = _team_default_chat_room_purpose(team)
    if not normalized_current:
        return expected
    if normalized_current == "discussion" and _infer_team_kind(team) != "custom":
        return expected
    return normalized_current


def _ensure_team_chat_room_link(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> str:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        return str(team.get("linkedChatRoomId") or "").strip()
    session_ids = _active_member_session_ids(team, agent_refs=agent_refs)
    _sync_chat_room_root()
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    title = _team_chat_room_title(team)
    config = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamPurpose": str(team.get("purpose") or "").strip(),
        "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
        "teamCategory": str(team.get("teamCategory") or TEAM_KIND_DEFAULTS["custom"]["teamCategory"]).strip(),
        "teamSource": str(team.get("teamSource") or TEAM_KIND_DEFAULTS["custom"]["teamSource"]).strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
    }
    participant_contexts = _team_participant_contexts_by_agent_id(team, agent_refs=agent_refs)
    linked_room = chat_room_service.get_chat_room_detail(linked_room_id) if linked_room_id else None
    if linked_room:
        room_config = {
            **dict(linked_room.get("config") or {}),
            **config,
        }
        room = chat_room_service.update_chat_room(
                linked_room_id,
                title=title,
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode=str(linked_room.get("mode") or "round_robin"),
                purpose=_team_chat_room_purpose_for_update(team, linked_room.get("purpose")),
                config=room_config,
            )
    else:
        reusable_room_id = _find_existing_team_chat_room_id(str(team.get("teamId") or "").strip())
        if reusable_room_id:
            reusable_room = chat_room_service.get_chat_room_detail(reusable_room_id) or {}
            room_config = {
                **dict(reusable_room.get("config") or {}),
                **config,
            }
            room = chat_room_service.update_chat_room(
                reusable_room_id,
                title=title,
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode=str(reusable_room.get("mode") or "round_robin"),
                purpose=_team_chat_room_purpose_for_update(team, reusable_room.get("purpose")),
                config=room_config,
            )
        else:
            historical_room_id = _find_historical_team_chat_room_id(str(team.get("teamId") or "").strip(), preferred_room_id=linked_room_id)
            room = chat_room_service.create_chat_room(
                room_id=historical_room_id,
                title=title,
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode="round_robin",
                purpose=_team_default_chat_room_purpose(team),
                config=config,
            )
    team["linkedChatRoomId"] = str(room.get("roomId") or "").strip()
    _archive_duplicate_team_chat_rooms(team["linkedChatRoomId"], str(team.get("teamId") or "").strip())
    _ensure_historical_team_chat_room_links(
        team,
        title=title,
        session_ids=session_ids,
        participant_contexts=participant_contexts,
        config=config,
    )
    team["updatedAt"] = utc_now_iso()
    _record_team_event(
        "team.chat_room.synced",
        team,
        fields={
            "linkedChatRoomId": team["linkedChatRoomId"],
            "memberSessionCount": len(session_ids),
        },
    )
    return team["linkedChatRoomId"]


def _find_existing_team_chat_room_id(team_id: str) -> str:
    normalized_team_id = str(team_id or "").strip()
    if not normalized_team_id:
        return ""
    rooms = [
        room for room in chat_room_service.list_chat_rooms()
        if str((room.get("config") or {}).get("source") or "").strip() == "team"
        and str((room.get("config") or {}).get("teamId") or "").strip() == normalized_team_id
    ]
    rooms.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return str((rooms[0] if rooms else {}).get("roomId") or "").strip()


def _find_historical_team_chat_room_id(team_id: str, *, preferred_room_id: str = "") -> str:
    candidates = _historical_team_chat_room_ids(team_id)
    preferred = str(preferred_room_id or "").strip()
    if preferred and preferred in candidates:
        return preferred
    return candidates[-1] if candidates else ""


def _historical_team_chat_room_ids(team_id: str) -> list[str]:
    normalized_team_id = _safe_token(team_id, default="", max_length=96)
    if not normalized_team_id:
        return []
    rounds_path = _teams_root() / normalized_team_id / "research_stage_rounds" / "index.json"
    if not rounds_path.exists():
        return []
    try:
        payload = json.loads(rounds_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    candidates: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("linkedChatRoomId", "coordinationRoomId", "roomId"):
                room_id = str(value.get(key) or "").strip()
                if room_id.startswith("room-") and room_id not in candidates:
                    candidates.append(room_id)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(payload)
    return candidates


def _ensure_historical_team_chat_room_links(
    team: dict[str, Any],
    *,
    title: str,
    session_ids: list[str],
    participant_contexts: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> list[str]:
    team_id = str(team.get("teamId") or "").strip()
    current_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not team_id or not current_room_id:
        return []
    created_room_ids: list[str] = []
    updated_room_ids: list[str] = []
    for room_id in _historical_team_chat_room_ids(team_id):
        if not room_id or room_id == current_room_id:
            continue
        room_config = {
            **config,
            "historicalTeamRoom": True,
            "teamRoomRole": "historical",
            "currentLinkedChatRoomId": current_room_id,
        }
        existing_room = chat_room_service.get_chat_room_detail(room_id)
        if existing_room:
            try:
                chat_room_service.update_chat_room(
                    room_id,
                    title=f"{title}（历史）",
                    participant_session_ids=session_ids,
                    participant_contexts_by_agent_id=participant_contexts,
                    allow_empty_participants=True,
                    mode=str(existing_room.get("mode") or "round_robin"),
                    purpose=_team_chat_room_purpose_for_update(team, existing_room.get("purpose")),
                    config={
                        **dict(existing_room.get("config") or {}),
                        **room_config,
                    },
                )
            except Exception:
                continue
            updated_room_ids.append(room_id)
            continue
        try:
            chat_room_service.create_chat_room(
                room_id=room_id,
                title=f"{title}（历史）",
                participant_session_ids=session_ids,
                participant_contexts_by_agent_id=participant_contexts,
                allow_empty_participants=True,
                mode="round_robin",
                purpose=_team_default_chat_room_purpose(team),
                config=room_config,
            )
        except Exception:
            continue
        created_room_ids.append(room_id)
    if created_room_ids or updated_room_ids:
        _record_team_event(
            "team.chat_room.history_synced",
            team,
            fields={
                "linkedChatRoomId": current_room_id,
                "historicalRoomIds": created_room_ids,
                "historicalRoomCount": len(created_room_ids),
                "historicalUpdatedRoomIds": updated_room_ids,
                "historicalUpdatedRoomCount": len(updated_room_ids),
            },
        )
    return created_room_ids


def _archive_duplicate_team_chat_rooms(keep_room_id: str, team_id: str) -> None:
    normalized_keep_room_id = str(keep_room_id or "").strip()
    normalized_team_id = str(team_id or "").strip()
    if not normalized_keep_room_id or not normalized_team_id:
        return
    historical_room_ids = set(_historical_team_chat_room_ids(normalized_team_id))
    historical_room_ids.discard(normalized_keep_room_id)
    duplicates = [
        room for room in chat_room_service.list_chat_rooms()
        if str(room.get("roomId") or "").strip() != normalized_keep_room_id
        and str(room.get("roomId") or "").strip() not in historical_room_ids
        and str((room.get("config") or {}).get("source") or "").strip() == "team"
        and str((room.get("config") or {}).get("teamId") or "").strip() == normalized_team_id
        and str(room.get("status") or "").strip() not in {"running", "stopping"}
    ]
    for room in duplicates:
        try:
            chat_room_service.delete_chat_room(str(room.get("roomId") or ""))
        except Exception:
            continue
    if duplicates:
        _record_team_event(
            "team.chat_room.duplicates_archived",
            {"teamId": normalized_team_id, "linkedChatRoomId": normalized_keep_room_id},
            fields={
                "linkedChatRoomId": normalized_keep_room_id,
                "duplicateRoomCount": len(duplicates),
            },
        )


def repair_archived_team_chat_rooms() -> dict[str, Any]:
    """Delete linked team chat rooms for Teams that are already archived."""

    _sync_chat_room_root()
    with _TEAM_LOCK:
        state = _load_index()
        changed = False
        deleted_room_ids: list[str] = []
        for team in list(state.get("teams") or []):
            if not isinstance(team, dict):
                continue
            if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
                continue
            before = str(team.get("linkedChatRoomId") or "").strip()
            deleted = _delete_team_linked_chat_rooms(team, reason="archived_team_repair")
            if deleted:
                deleted_room_ids.extend(deleted)
            if deleted or before != str(team.get("linkedChatRoomId") or "").strip():
                changed = True
        if changed:
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
    return {
        "deleted": bool(deleted_room_ids),
        "deletedRoomIds": deleted_room_ids,
        "deletedRoomCount": len(deleted_room_ids),
    }


def _repair_archived_team_linked_chat_room(team: dict[str, Any], *, reason: str) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() != "archived":
        return False
    before = str(team.get("linkedChatRoomId") or "").strip()
    deleted = _delete_team_linked_chat_rooms(team, reason=reason)
    after = str(team.get("linkedChatRoomId") or "").strip()
    return bool(deleted) or before != after


def _delete_team_linked_chat_rooms(team: dict[str, Any], *, reason: str, strict_busy: bool = False) -> list[str]:
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        return []
    _sync_chat_room_root()
    room_ids: list[str] = []
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if linked_room_id:
        room_ids.append(linked_room_id)
    for room in chat_room_service.list_chat_rooms_compact():
        if not isinstance(room, dict):
            continue
        room_id = str(room.get("roomId") or "").strip()
        room_config = dict(room.get("config") or {})
        if (
            room_id
            and room_id not in room_ids
            and str(room_config.get("source") or "").strip() == "team"
            and str(room_config.get("teamId") or "").strip() == team_id
        ):
            room_ids.append(room_id)

    deleted_room_ids: list[str] = []
    missing_room_ids: list[str] = []
    for room_id in room_ids:
        try:
            chat_room_service.delete_chat_room(room_id)
        except chat_room_service.ChatRoomNotFoundError:
            missing_room_ids.append(room_id)
            continue
        except chat_room_service.ChatRoomBusyError as exc:
            _record_team_event(
                "team.chat_room.archive_delete_rejected",
                team,
                fields={"linkedChatRoomId": room_id, "reason": reason, "errorType": type(exc).__name__},
            )
            if strict_busy:
                raise TeamServiceError("Team chat room has an active round and cannot be deleted while archiving.") from exc
            continue
        deleted_room_ids.append(room_id)

    if linked_room_id and linked_room_id in {*deleted_room_ids, *missing_room_ids}:
        team["linkedChatRoomId"] = ""
    if deleted_room_ids or missing_room_ids:
        _record_team_event(
            "team.chat_room.deleted_for_archive",
            team,
            fields={
                "deletedLinkedChatRoomIds": deleted_room_ids,
                "deletedLinkedChatRoomCount": len(deleted_room_ids),
                "clearedMissingLinkedChatRoomIds": missing_room_ids,
                "clearedMissingLinkedChatRoomCount": len(missing_room_ids),
                "reason": reason,
            },
        )
    return deleted_room_ids


def _team_chat_room_needs_sync(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        return False
    active_member_agent_ids = _active_member_agent_ids(team, agent_refs=agent_refs)
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not linked_room_id:
        return True
    _sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id)
    if not linked_room:
        return True
    participant_agent_ids = [
        str(participant.get("agentId") or "").strip()
        for participant in list(linked_room.get("participants") or [])
        if isinstance(participant, dict) and str(participant.get("agentId") or "").strip()
    ]
    if participant_agent_ids != active_member_agent_ids:
        return True
    historical_room_ids = [
        room_id
        for room_id in _historical_team_chat_room_ids(str(team.get("teamId") or "").strip())
        if room_id and room_id != linked_room_id
    ]
    if any(
        _historical_team_chat_room_needs_sync(
            team,
            room_id=room_id,
            current_room_id=linked_room_id,
            active_member_agent_ids=active_member_agent_ids,
        )
        for room_id in historical_room_ids
    ):
        return True
    team_kind = _infer_team_kind(team)
    if team_kind == "custom":
        return False
    config = linked_room.get("config") if isinstance(linked_room.get("config"), dict) else {}
    expected_pairs = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamKind": str(team.get("teamKind") or team_kind).strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
    }
    if any(str(config.get(key) or "").strip() != value for key, value in expected_pairs.items() if value):
        return True
    return str(linked_room.get("purpose") or "").strip() != _team_chat_room_purpose_for_update(team, linked_room.get("purpose"))


def _historical_team_chat_room_needs_sync(
    team: dict[str, Any],
    *,
    room_id: str,
    current_room_id: str,
    active_member_agent_ids: list[str],
) -> bool:
    room = chat_room_service.get_chat_room_compact(room_id)
    if not room:
        return True
    participant_agent_ids = [
        str(participant.get("agentId") or "").strip()
        for participant in list(room.get("participants") or [])
        if isinstance(participant, dict) and str(participant.get("agentId") or "").strip()
    ]
    if participant_agent_ids != active_member_agent_ids:
        return True
    if str(room.get("title") or "").strip() != f"{_team_chat_room_title(team)}（历史）":
        return True
    if str(room.get("purpose") or "").strip() != _team_chat_room_purpose_for_update(team, room.get("purpose")):
        return True
    config = room.get("config") if isinstance(room.get("config"), dict) else {}
    expected_pairs = {
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
        "teamRoomRole": "historical",
        "currentLinkedChatRoomId": current_room_id,
    }
    if any(str(config.get(key) or "").strip() != value for key, value in expected_pairs.items() if value):
        return True
    return config.get("historicalTeamRoom") is not True


def _sync_compact_team_chat_room_metadata(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    if str(team.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
        return False
    if _infer_team_kind(team) == "custom":
        return False
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not linked_room_id:
        return False
    if compact_rooms_by_id is None:
        _sync_chat_room_root()
        linked_room = chat_room_service.get_chat_room_compact(linked_room_id)
    else:
        linked_room = compact_rooms_by_id.get(linked_room_id)
    if not linked_room:
        return False
    next_purpose = _team_chat_room_purpose_for_update(team, linked_room.get("purpose"))
    current_purpose = str(linked_room.get("purpose") or "").strip()
    config = {
        **dict(linked_room.get("config") or {}),
        "source": "team",
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamPurpose": str(team.get("purpose") or "").strip(),
        "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
    }
    needs_config = any(str((linked_room.get("config") or {}).get(key) or "").strip() != value for key, value in config.items() if value)
    if current_purpose == next_purpose and not needs_config:
        return False
    try:
        chat_room_service.update_chat_room(
            linked_room_id,
            purpose=next_purpose,
            config=config,
        )
    except chat_room_service.ChatRoomBusyError as exc:
        _record_compact_chat_room_sync_skipped_busy(team, linked_room_id, exc)
        return False
    return True


def _team_to_api(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    repaired = dict(team)
    _repair_team(repaired, agent_refs=agent_refs)
    repaired["members"] = _members_to_api(repaired.get("members"))
    canvas_summary = _canvas_summary_for_team(repaired, agent_refs=agent_refs)
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    _sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    conversation_projection = build_team_conversation_projection(
        team=repaired,
        linked_room=linked_room,
    ).to_api()
    return {
        **repaired,
        "memberCount": len(repaired.get("members") or []),
        "canvas": canvas_summary,
        **_ai_search_source_scope_api_fields(repaired),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": _compact_chat_room(linked_room),
        "conversation": conversation_projection,
    }


def _team_to_compact_reference(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    repaired = dict(team)
    _apply_team_contract(repaired)
    team_id = _safe_token(team.get("teamId"), default="", max_length=96)
    members = _members_to_api(repaired.get("members"))
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    if compact_rooms_by_id is None:
        _sync_chat_room_root()
        linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    else:
        linked_room = compact_rooms_by_id.get(linked_room_id) if linked_room_id else None
    return {
        "teamId": team_id,
        "name": str(repaired.get("name") or team_id or "Team").strip(),
        "description": str(repaired.get("description") or "").strip(),
        "purpose": str(repaired.get("purpose") or "").strip(),
        "status": str(repaired.get("status") or DEFAULT_TEAM_STATUS).strip() or DEFAULT_TEAM_STATUS,
        "teamKind": str(repaired.get("teamKind") or "").strip(),
        "teamCategory": str(repaired.get("teamCategory") or "").strip(),
        "teamSource": str(repaired.get("teamSource") or "").strip(),
        "teamTemplateId": str(repaired.get("teamTemplateId") or "").strip(),
        "sourceScopePath": str(repaired.get("sourceScopePath") or "").strip(),
        "members": members,
        "memberCount": len(members),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": _compact_chat_room(linked_room),
        "canvasPath": str(repaired.get("canvasPath") or (_relative_path(_team_canvas_path(team_id)) if team_id else "")).strip(),
        "createdAt": str(repaired.get("createdAt") or "").strip(),
        "updatedAt": str(repaired.get("updatedAt") or "").strip(),
    }


def _team_to_graph_reference(team: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(team)
    _apply_team_contract(repaired)
    team_id = _safe_token(repaired.get("teamId"), default="", max_length=96)
    members = _members_to_api(repaired.get("members"))
    return {
        "teamId": team_id,
        "name": str(repaired.get("name") or team_id or "Team").strip(),
        "description": str(repaired.get("description") or "").strip(),
        "purpose": str(repaired.get("purpose") or "").strip(),
        "status": str(repaired.get("status") or DEFAULT_TEAM_STATUS).strip() or DEFAULT_TEAM_STATUS,
        "teamKind": str(repaired.get("teamKind") or "").strip(),
        "teamCategory": str(repaired.get("teamCategory") or "").strip(),
        "teamSource": str(repaired.get("teamSource") or "").strip(),
        "teamTemplateId": str(repaired.get("teamTemplateId") or "").strip(),
        "members": members,
        "memberCount": len(members),
        "linkedChatRoomId": str(repaired.get("linkedChatRoomId") or "").strip(),
        "canvasPath": str(repaired.get("canvasPath") or (_relative_path(_team_canvas_path(team_id)) if team_id else "")).strip(),
        "createdAt": str(repaired.get("createdAt") or "").strip(),
        "updatedAt": str(repaired.get("updatedAt") or "").strip(),
    }


def _team_detail_to_api(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    agent_refs = agent_refs or _agent_reference_maps()
    return {
        **_team_to_api_without_canvas_summary(team, agent_refs=agent_refs),
        "canvas": _team_canvas_with_validation(
            team,
            agents_by_id=agent_refs["by_id"],
            active_agents_by_id=agent_refs["active_by_id"],
        ),
    }


def _team_to_api_without_canvas_summary(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    repaired = dict(team)
    _repair_team(repaired, agent_refs=agent_refs)
    repaired["members"] = _members_to_api(repaired.get("members"))
    team_id = str(repaired.get("teamId") or "").strip()
    linked_room_id = str(repaired.get("linkedChatRoomId") or "").strip()
    _sync_chat_room_root()
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    conversation_projection = build_team_conversation_projection(
        team=repaired,
        linked_room=linked_room,
    ).to_api()
    return {
        **repaired,
        "memberCount": len(repaired.get("members") or []),
        "canvas": _canvas_path_summary(repaired, team_id=team_id),
        **_ai_search_source_scope_api_fields(repaired),
        "linkedChatRoomId": linked_room_id if linked_room else "",
        "linkedChatRoom": _compact_chat_room(linked_room),
        "conversation": conversation_projection,
    }


def _members_to_api(members: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, member in enumerate(list(members or [])):
        if not isinstance(member, dict) or not str(member.get("agentId") or "").strip():
            continue
        payload = {
            "memberId": _safe_token(member.get("memberId"), default=f"member-{index + 1}", max_length=96),
            "agentId": str(member.get("agentId") or "").strip(),
            "agentCode": str(member.get("agentCode") or "").strip(),
            "agentName": str(member.get("agentName") or "").strip(),
            "role": trim_lines(member.get("role") or "", max_lines=1).strip(),
            "purpose": trim_lines(member.get("purpose") or "", max_lines=4).strip(),
            "agentStatus": str(member.get("agentStatus") or "active").strip() or "active",
        }
        responsibilities = [
            trim_lines(value, max_lines=2).strip()
            for value in list(member.get("responsibilities") or [])[:8]
            if str(value or "").strip()
        ]
        if responsibilities:
            payload["responsibilities"] = responsibilities
        result.append(payload)
    return result


def _get_team_record(
    team_id: str,
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    with _TEAM_LOCK:
        state = _load_index()
        team = _find_team(state, normalized_team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        if _repair_team(team, agent_refs=agent_refs):
            state["updatedAt"] = utc_now_iso()
            _save_index(state)
        return dict(team)


def _canvas_summary_for_team(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        return {"path": "", "nodeCount": 0, "edgeCount": 0, "validation": _validate_canvas({"nodes": [], "edges": []}, team_id=team_id)}
    canvas_path = _team_canvas_path(team_id)
    raw = _read_json(canvas_path) if canvas_path.exists() else {}
    agent_refs = agent_refs or _agent_reference_maps()
    try:
        canvas = _normalize_canvas(
            raw or _default_canvas_for_team(team),
            team,
            agents_by_id=agent_refs["by_id"],
            active_agents_by_id=agent_refs["active_by_id"],
        )
        validation = _validate_canvas(canvas, team_id=team_id, active_agents_by_id=agent_refs["active_by_id"])
    except TeamServiceError as exc:
        canvas = {"nodes": [], "edges": []}
        validation = {
            "valid": False,
            "summary": {"errorCount": 1, "warningCount": 0, "issueCount": 1},
            "issues": [_issue("error", "invalid_canvas", str(exc))],
        }
    return {
        "path": str(team.get("canvasPath") or _relative_path(canvas_path)),
        "nodeCount": len(canvas.get("nodes") or []),
        "edgeCount": len(canvas.get("edges") or []),
        "validation": validation,
    }


def _canvas_path_summary(team: dict[str, Any], *, team_id: str = "") -> dict[str, Any]:
    normalized_team_id = str(team_id or team.get("teamId") or "").strip()
    canvas_path = _team_canvas_path(normalized_team_id) if normalized_team_id else Path("")
    return {
        "path": str(team.get("canvasPath") or (_relative_path(canvas_path) if normalized_team_id else "")),
        "nodeCount": 0,
        "edgeCount": 0,
        "validation": {"valid": True, "summary": {"errorCount": 0, "warningCount": 0, "issueCount": 0}, "issues": []},
    }


def _agent_reference_maps() -> dict[str, dict[str, dict[str, Any]]]:
    agents = _load_lightweight_agent_references()
    return _agent_reference_maps_from_agents(agents)


def _load_lightweight_agent_references() -> list[dict[str, Any]]:
    """Read Agent identity fields without running Agent repair or API hydration."""

    path = developer_sandbox.seeded_sandbox_workspace_path(_project_root(), "agents", "agents.json")
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    agents: list[dict[str, Any]] = []
    for item in list(payload.get("agents") or []):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        agents.append(
            {
                "agentId": agent_id,
                "agentCode": str(item.get("agentCode") or "").strip(),
                "displayName": str(item.get("displayName") or "").strip(),
                "directSessionId": str(item.get("directSessionId") or "").strip(),
                "status": str(item.get("status") or "active").strip() or "active",
                "metadata": dict(metadata),
                "createdAt": str(item.get("createdAt") or "").strip(),
                "updatedAt": str(item.get("updatedAt") or "").strip(),
            }
        )
    return agents


def _agent_reference_maps_from_agents(agents: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    active_by_id: dict[str, dict[str, Any]] = {}
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        copied = dict(agent)
        by_id[agent_id] = copied
        if str(agent.get("status") or "active").strip() != "archived":
            active_by_id[agent_id] = copied
    return {"by_id": by_id, "active_by_id": active_by_id}


def _merged_agent_reference_maps(*agent_groups: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    merged: dict[str, dict[str, Any]] = {}
    for agents in agent_groups:
        for agent in list(agents or []):
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("agentId") or "").strip()
            if agent_id:
                merged[agent_id] = dict(agent)
    return _agent_reference_maps_from_agents(list(merged.values()))


def _agent_reference(
    agent_id: str,
    *,
    include_archived: bool,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return None
    if agent_refs is not None:
        key = "by_id" if include_archived else "active_by_id"
        agent = (agent_refs.get(key) or {}).get(normalized_agent_id)
        return dict(agent) if isinstance(agent, dict) else None
    return agent_directory_service.get_agent(normalized_agent_id, include_archived=include_archived)


def _repair_index_state(
    state: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    changed = False
    if state.get("schemaVersion") != SCHEMA_VERSION:
        state["schemaVersion"] = SCHEMA_VERSION
        changed = True
    if not isinstance(state.get("teams"), list):
        state["teams"] = []
        changed = True
    for team in state.get("teams") or []:
        if isinstance(team, dict):
            changed = _repair_team(team, agent_refs=agent_refs) or changed
    return changed


def _repair_index_shape(state: dict[str, Any]) -> bool:
    changed = False
    if state.get("schemaVersion") != SCHEMA_VERSION:
        state["schemaVersion"] = SCHEMA_VERSION
        changed = True
    if not isinstance(state.get("teams"), list):
        state["teams"] = []
        changed = True
    return changed


def _repair_index_compact_contracts(
    state: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    changed = _repair_index_shape(state)
    for team in state.get("teams") or []:
        if not isinstance(team, dict):
            continue
        if _repair_team_contract_only(team, compact_rooms_by_id=compact_rooms_by_id):
            changed = True
    return changed


def _repair_team_contract_only(
    team: dict[str, Any],
    *,
    compact_rooms_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    changed = False
    team_id = _safe_token(team.get("teamId"), default="", max_length=96)
    if team.get("teamId") != team_id:
        team["teamId"] = team_id
        changed = True
    expected_path = _relative_path(_team_canvas_path(team_id)) if team_id else ""
    if team.get("canvasPath") != expected_path:
        team["canvasPath"] = expected_path
        changed = True
    if _infer_team_kind(team) == "ai_search":
        expected_source_scope_path = _relative_path(_ai_search_source_scope_path())
        if team.get("sourceScopePath") != expected_source_scope_path:
            team["sourceScopePath"] = expected_source_scope_path
            changed = True
        if _ensure_ai_search_source_scope_file():
            changed = True
    if "linkedChatRoomId" not in team:
        team["linkedChatRoomId"] = ""
        changed = True
    if _apply_team_contract(team):
        changed = True
    if _sync_compact_team_chat_room_metadata(team, compact_rooms_by_id=compact_rooms_by_id):
        changed = True
    return changed


def _repair_team(
    team: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> bool:
    changed = False
    team_id = _safe_token(team.get("teamId"), default="", max_length=96)
    if team.get("teamId") != team_id:
        team["teamId"] = team_id
        changed = True
    if not str(team.get("name") or "").strip():
        team["name"] = team_id or "Team"
        changed = True
    if str(team.get("status") or DEFAULT_TEAM_STATUS) not in TEAM_STATUSES:
        team["status"] = DEFAULT_TEAM_STATUS
        changed = True
    expected_path = _relative_path(_team_canvas_path(team_id)) if team_id else ""
    if team.get("canvasPath") != expected_path:
        team["canvasPath"] = expected_path
        changed = True
    if _infer_team_kind(team) == "ai_search":
        expected_source_scope_path = _relative_path(_ai_search_source_scope_path())
        if team.get("sourceScopePath") != expected_source_scope_path:
            team["sourceScopePath"] = expected_source_scope_path
            changed = True
        if _ensure_ai_search_source_scope_file():
            changed = True
    if "linkedChatRoomId" not in team:
        team["linkedChatRoomId"] = ""
        changed = True
    if _apply_team_contract(team):
        changed = True
    members = team.get("members") if isinstance(team.get("members"), list) else []
    repaired_members = _repair_members(members, agent_refs=agent_refs)
    if repaired_members != members:
        team["members"] = repaired_members
        changed = True
    if _infer_team_kind(team) == "research":
        _sync_research_team_member_agent_roles(repaired_members)
    if _team_chat_room_needs_sync(team, agent_refs=agent_refs):
        _ensure_team_chat_room_link(team, agent_refs=agent_refs)
        changed = True
    return changed


def _repair_members(
    members: list[Any],
    *,
    agent_refs: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(members):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        agent = _agent_reference(agent_id, include_archived=True, agent_refs=agent_refs)
        active = _agent_reference(agent_id, include_archived=False, agent_refs=agent_refs) if agent_id else None
        repaired.append(
            {
                "memberId": _safe_token(item.get("memberId"), default=f"member-{index + 1}", max_length=96),
                "agentId": agent_id,
                "agentCode": str((agent or {}).get("agentCode") or item.get("agentCode") or "").strip(),
                "agentName": str((agent or {}).get("displayName") or item.get("agentName") or "").strip(),
                "role": trim_lines(item.get("role") or "", max_lines=1).strip(),
                "purpose": trim_lines(item.get("purpose") or "", max_lines=4).strip(),
                "responsibilities": [
                    trim_lines(value, max_lines=2).strip()
                    for value in list(item.get("responsibilities") or [])[:8]
                    if str(value or "").strip()
                ],
                "agentStatus": "active" if active else "stale",
            }
        )
    return repaired


def _default_canvas_for_team(team: dict[str, Any]) -> dict[str, Any]:
    nodes = _default_nodes_for_members(team.get("members") or [])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": team["teamId"],
        "updatedAt": str(team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(_team_canvas_path(team["teamId"])),
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": nodes,
        "edges": _default_edges_for_team(team, nodes),
    }


def _ai_search_canvas_for_team(team: dict[str, Any]) -> dict[str, Any]:
    members_by_role = {
        str(member.get("role") or "").strip(): member
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("role") or "").strip()
    }
    positions = {
        "ai_search_scope_lead": (120, 210),
        "global_primary_sources": (420, 80),
        "cn_primary_sources": (420, 340),
        "signal_quality_gate": (720, 210),
    }
    nodes: list[dict[str, Any]] = []
    for index, role in enumerate(AI_SEARCH_SYSTEM_ROLES, start=1):
        role_key = str(role.get("role") or "").strip()
        member = members_by_role.get(role_key) or {}
        x, y = positions.get(role_key, (120 + index * 220, 210))
        nodes.append(
            {
                "id": f"ai-search-{index}",
                "label": str(member.get("agentName") or role.get("label") or role_key).strip(),
                "type": "agent" if str(member.get("agentId") or "").strip() else "role",
                "status": str(member.get("agentStatus") or ("bound" if member.get("agentId") else "unbound")).strip(),
                "x": x,
                "y": y,
                "agentId": str(member.get("agentId") or "").strip(),
                "agentCode": str(member.get("agentCode") or "").strip(),
                "agentName": str(member.get("agentName") or "").strip(),
                "role": role_key,
                "purpose": str(role.get("label") or "").strip(),
                "responsibilities": list(role.get("responsibilities") or []),
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "canvasKind": CANVAS_KIND,
        "teamId": AI_SEARCH_TEAM_ID,
        "updatedAt": str(team.get("updatedAt") or utc_now_iso()),
        "path": _relative_path(_team_canvas_path(AI_SEARCH_TEAM_ID)),
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": nodes,
        "edges": _ai_search_canvas_edges(),
    }


def _ai_search_canvas_edges() -> list[dict[str, Any]]:
    return [
        {"id": "ai-search-scope-global", "source": "ai-search-1", "target": "ai-search-2", "type": "communication", "label": "全球源边界"},
        {"id": "ai-search-scope-cn", "source": "ai-search-1", "target": "ai-search-3", "type": "communication", "label": "中国源边界"},
        {"id": "ai-search-global-quality", "source": "ai-search-2", "target": "ai-search-4", "type": "supports", "label": "一手源回链"},
        {"id": "ai-search-cn-quality", "source": "ai-search-3", "target": "ai-search-4", "type": "supports", "label": "一手源回链"},
        {"id": "ai-search-quality-scope", "source": "ai-search-4", "target": "ai-search-1", "type": "supports", "label": "启用规则回写"},
    ]


def _ai_search_canvas_needs_sync(canvas_path: Path, team: dict[str, Any]) -> bool:
    if not canvas_path.exists():
        return True
    try:
        canvas = _read_json(canvas_path)
    except Exception:
        return True
    expected_roles = {str(role.get("role") or "").strip() for role in AI_SEARCH_SYSTEM_ROLES}
    node_roles = {
        str(node.get("role") or "").strip()
        for node in list(canvas.get("nodes") or [])
        if isinstance(node, dict)
    }
    expected_agent_ids_by_role = {
        str(member.get("role") or "").strip(): str(member.get("agentId") or "").strip()
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("role") or "").strip()
    }
    canvas_agent_ids_by_role = {
        str(node.get("role") or "").strip(): str(node.get("agentId") or "").strip()
        for node in list(canvas.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("role") or "").strip()
    }
    expected_edges = {str(edge.get("id") or "").strip() for edge in _ai_search_canvas_edges()}
    edge_ids = {
        str(edge.get("id") or "").strip()
        for edge in list(canvas.get("edges") or [])
        if isinstance(edge, dict)
    }
    agents_match = all(
        not expected_agent_id or canvas_agent_ids_by_role.get(role_key) == expected_agent_id
        for role_key, expected_agent_id in expected_agent_ids_by_role.items()
    )
    return not expected_roles.issubset(node_roles) or not expected_edges.issubset(edge_ids) or not agents_match


def _default_ai_search_source_scope() -> dict[str, Any]:
    groups = [dict(group) for group in AI_SEARCH_SOURCE_SCOPE_GROUPS]
    normalized_groups: list[dict[str, Any]] = []
    for group in groups:
        sources = []
        for source in list(group.get("sources") or []):
            source_payload = dict(source)
            source_payload["tier"] = str(source_payload.get("tier") or group.get("tier") or "").strip()
            source_payload["evidenceRole"] = str(source_payload.get("evidenceRole") or group.get("evidenceRole") or "").strip()
            source_payload["enabledByDefault"] = bool(group.get("enabledByDefault"))
            source_payload["ownerRole"] = str(group.get("ownerRole") or "").strip()
            source_payload["tags"] = list(source_payload.get("tags") or [])
            sources.append(source_payload)
        normalized_groups.append(
            {
                **group,
                "sources": sources,
                "sourceCount": len(sources),
            }
        )
    source_count = sum(int(group.get("sourceCount") or 0) for group in normalized_groups)
    enabled_count = sum(
        1
        for group in normalized_groups
        for source in list(group.get("sources") or [])
        if bool(source.get("enabledByDefault"))
    )
    return {
        "schemaVersion": AI_SEARCH_SOURCE_SCOPE_SCHEMA_VERSION,
        "scopeId": "ai-latest-news-source-scope-v1",
        "teamId": AI_SEARCH_TEAM_ID,
        "title": "AI 最新动态搜索范围白名单",
        "description": "一键搜索 AI 最新动态时优先使用的来源范围；Tier3 只作线索，结论必须回链一手证据。",
        "curatedAt": AI_SEARCH_SOURCE_SCOPE_CURATED_AT,
        "policy": {
            "defaultEnabledTiers": ["tier1", "tier2"],
            "signalTiers": ["tier3"],
            "requiresPrimaryEvidenceForConclusion": True,
            "dedupeBy": ["canonicalUrl", "sourceId", "title"],
            "writesFormalKnowledge": False,
        },
        "summary": {
            "groupCount": len(normalized_groups),
            "sourceCount": source_count,
            "enabledByDefaultCount": enabled_count,
            "signalOnlyCount": source_count - enabled_count,
        },
        "groups": normalized_groups,
        "storage": {
            "path": _relative_path(_ai_search_source_scope_path()),
        },
    }


def _ai_search_source_scope_needs_sync(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        scope = _read_json(path)
    except Exception:
        return True
    if int(scope.get("schemaVersion") or 0) != AI_SEARCH_SOURCE_SCOPE_SCHEMA_VERSION:
        return True
    if str(scope.get("teamId") or "").strip() != AI_SEARCH_TEAM_ID:
        return True
    groups = scope.get("groups") if isinstance(scope.get("groups"), list) else []
    if not groups:
        return True
    group_ids = {
        str(group.get("groupId") or "").strip()
        for group in groups
        if isinstance(group, dict)
    }
    expected_group_ids = {
        str(group.get("groupId") or "").strip()
        for group in AI_SEARCH_SOURCE_SCOPE_GROUPS
    }
    return not expected_group_ids.issubset(group_ids)


def _ensure_ai_search_source_scope_file() -> bool:
    path = _ai_search_source_scope_path()
    if not _ai_search_source_scope_needs_sync(path):
        return False
    _write_json(path, _default_ai_search_source_scope())
    return True


def _load_ai_search_source_scope() -> dict[str, Any]:
    path = _ai_search_source_scope_path()
    if _ai_search_source_scope_needs_sync(path):
        return _default_ai_search_source_scope()
    try:
        scope = _read_json(path)
    except Exception:
        return _default_ai_search_source_scope()
    scope["storage"] = {
        **dict(scope.get("storage") or {}),
        "path": _relative_path(path),
    }
    return scope


def _ai_search_source_scope_api_fields(team: dict[str, Any]) -> dict[str, Any]:
    if _infer_team_kind(team) != "ai_search":
        return {}
    return {
        "sourceScopePath": _relative_path(_ai_search_source_scope_path()),
        "sourceScope": _load_ai_search_source_scope(),
    }


def _select_ai_search_sources(scope: dict[str, Any], *, source_limit: int, include_signals: bool) -> list[dict[str, Any]]:
    groups = [
        group for group in list(scope.get("groups") or [])
        if isinstance(group, dict)
        and (bool(group.get("enabledByDefault")) or include_signals)
    ]
    selected: list[dict[str, Any]] = []
    group_sources: list[list[dict[str, Any]]] = []
    for group in groups:
        sources = [
            {
                **source,
                "groupId": str(group.get("groupId") or "").strip(),
                "groupLabel": str(group.get("label") or "").strip(),
                "groupTier": str(group.get("tier") or "").strip(),
                "groupEvidenceRole": str(group.get("evidenceRole") or "").strip(),
            }
            for source in list(group.get("sources") or [])
            if isinstance(source, dict)
            and (bool(source.get("enabledByDefault")) or include_signals)
        ]
        if sources:
            group_sources.append(sources)
    cursor = 0
    while len(selected) < source_limit and group_sources:
        next_group_sources: list[list[dict[str, Any]]] = []
        for sources in group_sources:
            if cursor < len(sources) and len(selected) < source_limit:
                selected.append(sources[cursor])
            if cursor + 1 < len(sources):
                next_group_sources.append(sources)
        cursor += 1
        group_sources = next_group_sources
    return selected


def _ai_search_query_for_source(source: dict[str, Any], *, topic: str, run_id: str, index: int) -> dict[str, Any]:
    url = str(source.get("url") or "").strip()
    domain = urlparse(url).netloc or urlparse(f"https://{url}").netloc
    query_parts = [
        topic,
        str(source.get("name") or "").strip(),
        "latest AI model product research update",
    ]
    if domain:
        query_parts.append(f"site:{domain}")
    query = " ".join(part for part in query_parts if part).strip()
    return {
        "queryId": f"{run_id}-q{index:02d}",
        "query": query,
        "sourceId": str(source.get("sourceId") or "").strip(),
        "sourceName": str(source.get("name") or "").strip(),
        "sourceUrl": url,
        "sourceType": str(source.get("sourceType") or "").strip(),
        "groupId": str(source.get("groupId") or "").strip(),
        "groupLabel": str(source.get("groupLabel") or "").strip(),
        "tier": str(source.get("tier") or source.get("groupTier") or "").strip(),
        "evidenceRole": str(source.get("evidenceRole") or source.get("groupEvidenceRole") or "").strip(),
        "enabledByDefault": bool(source.get("enabledByDefault")),
    }


def _execute_ai_search_query_card(query: dict[str, Any], *, max_results: int) -> dict[str, Any]:
    now = utc_now_iso()
    query_text = str(query.get("query") or "").strip()
    search_mode = "web_search"
    degraded = False
    fallback_reason = ""
    try:
        result_text = _run_ai_web_search(query_text, max_results=max_results)
    except Exception as exc:
        result_text = f"[错误] 搜索执行异常: {type(exc).__name__}: {exc}"
    failed = _ai_search_result_is_error(result_text)
    if failed:
        fallback_reason = _web_search_summary_text(result_text) or str(result_text or "").strip()
        fallback_text = _run_ai_source_page_fallback(query, max_results=max_results, primary_error=fallback_reason)
        fallback_failed = _ai_search_result_is_error(fallback_text)
        if fallback_failed:
            result_text = f"{result_text}\n\n{fallback_text}".strip()
        else:
            result_text = fallback_text
            failed = False
            degraded = True
            search_mode = "source_page_fallback"
    references = [] if failed else _references_from_web_search_result(result_text)
    return {
        "cardId": f"{query.get('queryId')}-card",
        "queryId": str(query.get("queryId") or "").strip(),
        "sourceId": str(query.get("sourceId") or "").strip(),
        "sourceName": str(query.get("sourceName") or "").strip(),
        "sourceUrl": str(query.get("sourceUrl") or "").strip(),
        "sourceType": str(query.get("sourceType") or "").strip(),
        "groupId": str(query.get("groupId") or "").strip(),
        "groupLabel": str(query.get("groupLabel") or "").strip(),
        "tier": str(query.get("tier") or "").strip(),
        "evidenceRole": str(query.get("evidenceRole") or "").strip(),
        "query": query_text,
        "status": "failed" if failed else "succeeded",
        "searchMode": search_mode,
        "degraded": degraded,
        "fallbackReason": fallback_reason,
        "summary": _web_search_summary_text(result_text),
        "resultText": result_text,
        "references": references,
        "createdAt": now,
        "updatedAt": now,
    }


def _run_ai_web_search(query: str, *, max_results: int) -> str:
    from tools.web_search_tool import web_search

    return web_search(query=query, max_results=max_results)


def _run_ai_source_page_fallback(query: dict[str, Any], *, max_results: int, primary_error: str) -> str:
    source_url = str(query.get("sourceUrl") or "").strip()
    if not source_url:
        return "[错误] 主搜索工具失败，且该来源没有可扫描的官方页面 URL。"
    source_name = str(query.get("sourceName") or query.get("sourceId") or source_url).strip()
    try:
        page = _fetch_ai_search_source_page(source_url)
    except Exception as exc:
        return f"[错误] 主搜索工具失败，官方源页面扫描也失败: {type(exc).__name__}: {exc}"
    final_url = str(page.get("url") or source_url).strip()
    references = _rank_ai_search_source_page_references(
        list(page.get("links") or []),
        topic=str(query.get("query") or ""),
        source_name=source_name,
        base_url=final_url,
        max_results=max_results,
    )
    if not references:
        page_title = _clean_ai_search_source_text(str(page.get("title") or source_name or final_url), max_length=160)
        references = [{"title": page_title or final_url, "url": final_url}]
    title = _clean_ai_search_source_text(str(page.get("title") or source_name), max_length=180)
    description = _clean_ai_search_source_text(str(page.get("description") or ""), max_length=360)
    summary_lines = [
        "[降级] 主搜索工具不可用，已改用官方源页面扫描。",
        f"来源: {source_name}",
        f"页面: {title or final_url}",
    ]
    if description:
        summary_lines.append(f"摘要: {description}")
    summary_lines.append(f"主搜索失败原因: {trim_lines(primary_error, max_lines=2)[:260]}")
    summary_lines.append("候选动态:")
    for reference in references[:max_results]:
        summary_lines.append(f"- {reference['title']} ({reference['url']})")
    reference_lines = ["", "**参考来源：**"]
    for index, reference in enumerate(references[:max_results], start=1):
        reference_lines.append(f"{index}. [{reference['title']}]({reference['url']})")
    return "\n".join(summary_lines + reference_lines)


def _fetch_ai_search_source_page(source_url: str) -> dict[str, Any]:
    normalized_url = str(source_url or "").strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("source URL must use http or https")
    headers = {"User-Agent": AI_SEARCH_SOURCE_PAGE_USER_AGENT}
    with httpx.Client(follow_redirects=True, timeout=AI_SEARCH_SOURCE_PAGE_TIMEOUT_SECONDS, headers=headers) as client:
        response = client.get(normalized_url)
        response.raise_for_status()
    content = response.content[:AI_SEARCH_SOURCE_PAGE_MAX_BYTES]
    encoding = response.encoding or "utf-8"
    html = content.decode(encoding, errors="replace")
    parsed_page = _parse_ai_search_source_page(html, str(response.url))
    parsed_page["url"] = str(response.url)
    return parsed_page


def _parse_ai_search_source_page(html: str, base_url: str) -> dict[str, Any]:
    parser = _AiSearchSourcePageParser(base_url=base_url)
    parser.feed(str(html or ""))
    parser.close()
    return {
        "title": _clean_ai_search_source_text(parser.title_text(), max_length=180),
        "description": _clean_ai_search_source_text(parser.description, max_length=360),
        "links": parser.normalized_links(),
    }


class _AiSearchSourcePageParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._in_title = False
        self._title_parts: list[str] = []
        self._current_href = ""
        self._current_anchor_parts: list[str] = []
        self.description = ""
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        if normalized_tag == "title":
            self._in_title = True
            return
        if normalized_tag == "meta" and not self.description:
            name = attr_map.get("name") or attr_map.get("property")
            if name.lower() in {"description", "og:description", "twitter:description"}:
                self.description = attr_map.get("content", "")
            return
        if normalized_tag == "a":
            self._current_href = attr_map.get("href", "").strip()
            self._current_anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "title":
            self._in_title = False
            return
        if normalized_tag == "a" and self._current_href:
            title = _clean_ai_search_source_text(" ".join(self._current_anchor_parts), max_length=180)
            self.links.append({"title": title or self._current_href, "url": urljoin(self.base_url, self._current_href)})
            self._current_href = ""
            self._current_anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._current_href:
            self._current_anchor_parts.append(data)

    def title_text(self) -> str:
        return " ".join(self._title_parts)

    def normalized_links(self) -> list[dict[str, str]]:
        seen: set[str] = set()
        links: list[dict[str, str]] = []
        for link in self.links:
            url = str(link.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            links.append({"title": str(link.get("title") or url).strip(), "url": url})
        return links


def _rank_ai_search_source_page_references(
    links: list[dict[str, str]],
    *,
    topic: str,
    source_name: str,
    base_url: str,
    max_results: int,
) -> list[dict[str, str]]:
    topic_terms = _ai_search_source_page_keywords(f"{topic} {source_name}")
    positive_terms = {
        "ai", "agent", "agents", "model", "models", "research", "release", "releases", "news", "blog",
        "product", "developer", "paper", "benchmark", "eval", "safety", "open-source", "open_source",
        "新闻", "动态", "发布", "模型", "研究", "论文", "产品", "开发者", "开源", "安全", "评测",
    }
    skip_terms = {
        "privacy", "terms", "cookie", "login", "signin", "signup", "sign-up", "careers", "jobs",
        "contact", "about", "subscribe", "rss", "twitter", "linkedin", "facebook", "instagram",
        "隐私", "条款", "登录", "注册", "招聘", "联系",
    }
    ranked: list[tuple[int, int, dict[str, str]]] = []
    for index, raw_link in enumerate(links):
        url = urljoin(base_url, str(raw_link.get("url") or "").strip())
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        title = _clean_ai_search_source_text(str(raw_link.get("title") or url), max_length=180)
        combined = f"{title} {parsed.netloc} {parsed.path} {parsed.query}".lower()
        if any(term in combined for term in skip_terms):
            continue
        score = 0
        for term in topic_terms:
            if term and term in combined:
                score += 4
        for term in positive_terms:
            if term in combined:
                score += 3
        if parsed.netloc == urlparse(base_url).netloc:
            score += 1
        if score <= 0:
            continue
        ranked.append((score, -index, {"title": title or url, "url": url}))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    references: list[dict[str, str]] = []
    seen: set[str] = set()
    for _score, _index, reference in ranked:
        url = reference["url"]
        if url in seen:
            continue
        seen.add(url)
        references.append(reference)
        if len(references) >= max_results:
            break
    return references


def _ai_search_source_page_keywords(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", str(text or "").lower()):
        if token not in tokens:
            tokens.append(token)
    return tokens[:16]


def _clean_ai_search_source_text(text: str, *, max_length: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:max_length]


def _ai_search_result_is_error(result_text: str) -> bool:
    normalized = str(result_text or "").strip()
    return normalized.startswith("[错误]") or "dependency unavailable" in normalized.lower() or "依赖不可用" in normalized


def _web_search_summary_text(result_text: str) -> str:
    text = str(result_text or "").strip()
    if not text:
        return ""
    marker = "\n\n**参考来源：**"
    summary = text.split(marker, 1)[0].strip()
    return trim_lines(summary, max_lines=6)[:1200]


def _references_from_web_search_result(result_text: str) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for match in re.finditer(r"^\s*\d+\.\s+\[([^\]]+)\]\(([^)]+)\)", str(result_text or ""), flags=re.MULTILINE):
        title = match.group(1).strip()
        url = match.group(2).strip()
        if title or url:
            references.append({"title": title, "url": url})
    return references[:10]


def _new_ai_search_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"ai-search-run-{stamp}-{uuid4().hex[:8]}"


def _load_ai_search_runs_index() -> dict[str, Any]:
    path = _ai_search_runs_index_path()
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "teamId": AI_SEARCH_TEAM_ID, "updatedAt": "", "runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": SCHEMA_VERSION, "teamId": AI_SEARCH_TEAM_ID, "updatedAt": "", "runs": []}
    if not isinstance(data, dict):
        return {"schemaVersion": SCHEMA_VERSION, "teamId": AI_SEARCH_TEAM_ID, "updatedAt": "", "runs": []}
    if not isinstance(data.get("runs"), list):
        data["runs"] = []
    return data


def _upsert_ai_search_run_summary(run: dict[str, Any]) -> None:
    index = _load_ai_search_runs_index()
    run_id = str(run.get("runId") or "").strip()
    summary = {
        "runId": run_id,
        "teamId": AI_SEARCH_TEAM_ID,
        "title": str(run.get("title") or "").strip(),
        "topic": str(run.get("topic") or "").strip(),
        "status": str(run.get("status") or "").strip(),
        "createdAt": str(run.get("createdAt") or "").strip(),
        "updatedAt": str(run.get("updatedAt") or "").strip(),
        "queryCount": int((run.get("queryPlan") or {}).get("queryCount") or 0),
        "cardCount": int((run.get("summary") or {}).get("cardCount") or 0),
        "succeededCount": int((run.get("summary") or {}).get("succeededCount") or 0),
        "failedCount": int((run.get("summary") or {}).get("failedCount") or 0),
        "degradedCount": int((run.get("summary") or {}).get("degradedCount") or 0),
        "referenceCount": int((run.get("summary") or {}).get("referenceCount") or 0),
        "runPath": _relative_path(_ai_search_run_path(run_id)) if run_id else "",
        "cards": list(run.get("cards") or [])[:12],
    }
    runs = [
        item for item in list(index.get("runs") or [])
        if isinstance(item, dict) and str(item.get("runId") or "").strip() != run_id
    ]
    runs.insert(0, summary)
    index.update(
        {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": AI_SEARCH_TEAM_ID,
            "updatedAt": str(run.get("updatedAt") or utc_now_iso()),
            "runs": runs[:50],
        }
    )
    _write_json(_ai_search_runs_index_path(), index)


def _default_nodes_for_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        nodes.append(
            {
                "id": f"node-{index + 1}",
                "label": str(member.get("agentName") or agent_id),
                "type": "agent",
                "status": str(member.get("agentStatus") or "active"),
                "x": 120 + index * 220,
                "y": 120,
                "agentId": agent_id,
                "agentCode": str(member.get("agentCode") or ""),
                "agentName": str(member.get("agentName") or ""),
                "role": str(member.get("role") or ""),
                "purpose": str(member.get("purpose") or ""),
            }
        )
    if nodes:
        return nodes
    return [
        {
            "id": "team-lead",
            "label": "团队负责人",
            "type": "role",
            "status": "unbound",
            "x": 220,
            "y": 120,
            "agentId": "",
            "agentCode": "",
            "agentName": "",
            "role": "lead",
            "purpose": "",
        }
    ]


def _default_edges_for_team(team: dict[str, Any], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes_by_role: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        role = str(node.get("role") or "").strip()
        if role and role not in nodes_by_role:
            nodes_by_role[role] = node
    if _infer_team_kind(team) == "self_evolution":
        return _edges_from_role_chain(
            nodes_by_role,
            [
                ("executor", "reviewer", "执行交付评审"),
                ("reviewer", "summarizer", "评审结果总结"),
            ],
        )
    if _infer_team_kind(team) == "supervised_evolution":
        return _edges_from_role_chain(
            nodes_by_role,
            [
                ("baseline", "reviewer", "基线方案评审"),
                ("candidate", "reviewer", "候选方案评审"),
                ("reviewer", "auditor", "评审进入审计"),
                ("auditor", "judge", "审计进入裁决"),
            ],
        )
    if _infer_team_kind(team) == "ai_search":
        return _edges_from_role_chain(
            nodes_by_role,
            [
                ("ai_search_scope_lead", "global_primary_sources", "全球源边界"),
                ("ai_search_scope_lead", "cn_primary_sources", "中国源边界"),
                ("global_primary_sources", "signal_quality_gate", "一手源回链"),
                ("cn_primary_sources", "signal_quality_gate", "一手源回链"),
                ("signal_quality_gate", "ai_search_scope_lead", "启用规则回写"),
            ],
        )
    return []


def _edges_from_role_chain(
    nodes_by_role: dict[str, dict[str, Any]],
    links: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for index, (source_role, target_role, label) in enumerate(links, start=1):
        source = nodes_by_role.get(source_role)
        target = nodes_by_role.get(target_role)
        if not source or not target:
            continue
        source_id = str(source.get("id") or "").strip()
        target_id = str(target.get("id") or "").strip()
        if not source_id or not target_id:
            continue
        edges.append(
            {
                "id": _safe_token(f"{source_role}-{target_role}", default=f"edge-{index}", max_length=96),
                "source": source_id,
                "target": target_id,
                "label": label,
                "type": "communication",
            }
        )
    return edges


def _default_canvas_edges_missing_for_team(team: dict[str, Any], canvas_path: Path) -> bool:
    if _infer_team_kind(team) not in {"self_evolution", "supervised_evolution", "ai_search"}:
        return False
    if not canvas_path.exists():
        return True
    try:
        canvas = _read_json(canvas_path)
    except Exception:
        return True
    return not list(canvas.get("edges") or [])


def _load_index() -> dict[str, Any]:
    path = _teams_index_path()
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "teams": []}
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        _debug_logger.warning(f"Failed to read Team index. path={path} error={type(exc).__name__}: {exc}")
        return {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "teams": []}
    return data if isinstance(data, dict) else {"schemaVersion": SCHEMA_VERSION, "updatedAt": utc_now_iso(), "teams": []}


def _save_index(state: dict[str, Any]) -> None:
    _write_json(_teams_index_path(), state)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _teams_root() -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(_project_root(), "teams")


def _teams_index_path() -> Path:
    return _teams_root() / "teams.json"


def _team_canvas_path(team_id: str) -> Path:
    return _teams_root() / _safe_token(team_id, default="team", max_length=96) / "canvas.json"


def _ai_search_source_scope_path() -> Path:
    return _teams_root() / AI_SEARCH_TEAM_ID / "source_scope.json"


def _ai_search_runs_root() -> Path:
    return _teams_root() / AI_SEARCH_TEAM_ID / "search_runs"


def _ai_search_runs_index_path() -> Path:
    return _ai_search_runs_root() / "index.json"


def _ai_search_run_path(run_id: str) -> Path:
    return _ai_search_runs_root() / f"{_safe_token(run_id, default='run', max_length=96)}.json"


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_project_bus_root() -> None:
    if project_agent_bus_service.PROJECT_ROOT != PROJECT_ROOT:
        project_agent_bus_service.PROJECT_ROOT = PROJECT_ROOT


def _relative_path(path: Path) -> str:
    resolved = path.resolve()
    workspace_root = developer_sandbox.formal_workspace_path(_project_root()).resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        pass
    sandbox_root = developer_sandbox.sandbox_workspace_path(_project_root())
    if sandbox_root is not None:
        try:
            return f"workspace/{resolved.relative_to(sandbox_root.resolve()).as_posix()}"
        except ValueError:
            pass
    try:
        return str(resolved.relative_to(_project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _find_team(state: dict[str, Any], team_id: str) -> dict[str, Any] | None:
    for item in list(state.get("teams") or []):
        if isinstance(item, dict) and str(item.get("teamId") or "").strip() == team_id:
            return item
    return None


def _normalized_team_dedupe_key(
    *,
    name: str,
    team_kind: str,
    team_source: str,
    team_template_id: str,
) -> tuple[str, str, str, str]:
    probe = {
        "name": name,
        "teamKind": team_kind,
        "teamSource": team_source,
        "teamTemplateId": team_template_id,
    }
    _apply_team_contract(
        probe,
        team_kind=team_kind,
        team_source=team_source,
        team_template_id=team_template_id,
    )
    return (
        str(probe.get("teamSource") or TEAM_KIND_DEFAULTS["custom"]["teamSource"]).strip().lower(),
        str(probe.get("teamKind") or "custom").strip().lower(),
        str(probe.get("teamTemplateId") or "").strip().lower(),
        str(name or "").strip().lower(),
    )


def _find_reusable_empty_team(
    state: dict[str, Any],
    *,
    normalized_name: str,
    team_kind: str,
    team_source: str,
    team_template_id: str,
    requested_member_count: int,
) -> dict[str, Any] | None:
    if requested_member_count:
        return None
    requested_key = _normalized_team_dedupe_key(
        name=normalized_name,
        team_kind=team_kind,
        team_source=team_source,
        team_template_id=team_template_id,
    )
    candidates: list[dict[str, Any]] = []
    for item in list(state.get("teams") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or DEFAULT_TEAM_STATUS).strip() == "archived":
            continue
        if len(list(item.get("members") or [])):
            continue
        item_key = _normalized_team_dedupe_key(
            name=str(item.get("name") or "").strip(),
            team_kind=str(item.get("teamKind") or ""),
            team_source=str(item.get("teamSource") or ""),
            team_template_id=str(item.get("teamTemplateId") or ""),
        )
        if item_key == requested_key:
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""))
    return candidates[0]


def _new_team_id(name: str, existing_ids: set[str]) -> str:
    base = _safe_token(name, default="team", max_length=48).lower()
    candidate = base
    index = 2
    while candidate in existing_ids:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _normalize_required_id(value: str, message: str) -> str:
    normalized = _safe_token(value, default="", max_length=96)
    if not normalized:
        raise TeamServiceError(message)
    return normalized


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: str = "",
    edge_id: str = "",
    source: str = "",
    target: str = "",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "nodeId": node_id,
        "edgeId": edge_id,
        "source": source,
        "target": target,
    }


def _format_validation_error(validation: dict[str, Any]) -> str:
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    details = "; ".join(str(item.get("message") or item.get("code") or "") for item in issues[:3] if isinstance(item, dict))
    return f"Team canvas contract invalid: {details or 'unknown validation error'}"


def _summary(teams: list[dict[str, Any]]) -> dict[str, Any]:
    active = [team for team in teams if str(team.get("status") or DEFAULT_TEAM_STATUS) != "archived"]
    return {
        "teamCount": len(teams),
        "activeTeamCount": len(active),
        "memberCount": sum(len(team.get("members") or []) for team in active),
        "staleMemberCount": sum(
            1
            for team in active
            for member in list(team.get("members") or [])
            if isinstance(member, dict) and str(member.get("agentStatus") or "") != "active"
        ),
    }


def _compact_chat_room(room: dict[str, Any] | None) -> dict[str, Any] | None:
    if not room:
        return None
    return {
        "roomId": str(room.get("roomId") or "").strip(),
        "title": str(room.get("title") or "").strip(),
        "status": str(room.get("status") or "").strip(),
        "mode": str(room.get("mode") or "").strip(),
        "purpose": str(room.get("purpose") or "").strip(),
        "participantCount": len(list(room.get("participants") or [])),
        "updatedAt": str(room.get("updatedAt") or "").strip(),
    }


def _record_team_event(event_code: str, team: dict[str, Any], *, fields: dict[str, Any] | None = None) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            event_code,
            message=f"Team {team.get('teamId')} {event_code}",
            outcome="succeeded",
            fields={
                "teamId": team.get("teamId"),
                "teamName": team.get("name"),
                "status": team.get("status"),
                "teamKind": team.get("teamKind"),
                "teamCategory": team.get("teamCategory"),
                "teamSource": team.get("teamSource"),
                "teamTemplateId": team.get("teamTemplateId"),
                **(fields or {}),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to emit team loaded event. error={exc}")


def _record_system_team_bootstrap_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "system_bootstrap",
            event_code,
            message=event_code,
            outcome=outcome,
            fields=fields or {},
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to emit system Team bootstrap event. error={exc}")


def _team_detail_log_fields(team: dict[str, Any], started_at: float) -> dict[str, Any]:
    canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
    return {
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamKind": str(team.get("teamKind") or "").strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
        "linkedChatRoomId": str(team.get("linkedChatRoomId") or "").strip(),
        "memberCount": len(list(team.get("members") or [])),
        "canvasNodeCount": len(list(canvas.get("nodes") or [])),
        "canvasEdgeCount": len(list(canvas.get("edges") or [])),
        "elapsedMs": _elapsed_ms(started_at),
    }


def _team_detail_log_signature(fields: dict[str, Any]) -> tuple[Any, ...]:
    return (
        fields.get("teamKind"),
        fields.get("teamSource"),
        fields.get("teamTemplateId"),
        fields.get("linkedChatRoomId"),
        fields.get("memberCount"),
        fields.get("canvasNodeCount"),
        fields.get("canvasEdgeCount"),
    )


def _emit_team_detail_loaded(fields: dict[str, Any], *, reason: str) -> None:
    record_runtime_scene_event(
        "team_service",
        "team_detail",
        "team.detail.loaded",
        message="Team detail loaded.",
        outcome="observed",
        fields={**fields, "logReason": reason},
    )


def _emit_team_detail_rollup(team_id: str, state: dict[str, Any], *, now: float) -> None:
    repeat_count = int(state.get("repeatCount") or 0)
    if repeat_count <= 0:
        return
    fields = dict(state.get("lastFields") or {})
    record_runtime_scene_event(
        "team_service",
        "team_detail",
        "team.detail.loaded_rollup",
        message="Repeated team detail loads suppressed.",
        outcome="observed",
        fields={
            "teamId": team_id,
            "teamName": str(fields.get("teamName") or ""),
            "teamKind": str(fields.get("teamKind") or ""),
            "teamSource": str(fields.get("teamSource") or ""),
            "linkedChatRoomId": str(fields.get("linkedChatRoomId") or ""),
            "memberCount": fields.get("memberCount", 0),
            "canvasNodeCount": fields.get("canvasNodeCount", 0),
            "canvasEdgeCount": fields.get("canvasEdgeCount", 0),
            "repeatCount": repeat_count,
            "windowSeconds": round(max(0.0, now - float(state.get("windowStartedAt") or now)), 3),
            "maxElapsedMs": state.get("maxElapsedMs", 0),
            "lastElapsedMs": fields.get("elapsedMs", 0),
            "rollupReason": "same_signature_repeated",
        },
    )
    state["repeatCount"] = 0
    state["windowStartedAt"] = now
    state["lastRollupAt"] = now


def _record_team_detail_loaded(team: dict[str, Any], started_at: float) -> None:
    try:
        fields = _team_detail_log_fields(team, started_at)
        team_id = str(fields.get("teamId") or "").strip()
        if not team_id:
            return
        now = _perf_counter()
        signature = _team_detail_log_signature(fields)
        elapsed_ms = int(fields.get("elapsedMs") or 0)
        with _TEAM_DETAIL_LOG_LOCK:
            state = _TEAM_DETAIL_LOG_STATE.get(team_id)
            if state is None:
                _TEAM_DETAIL_LOG_STATE[team_id] = {
                    "signature": signature,
                    "repeatCount": 0,
                    "windowStartedAt": now,
                    "lastRollupAt": 0.0,
                    "maxElapsedMs": elapsed_ms,
                    "lastFields": fields,
                }
                _emit_team_detail_loaded(fields, reason="initial")
                return

            previous_signature = state.get("signature")
            if previous_signature != signature:
                _emit_team_detail_rollup(team_id, state, now=now)
                state.update(
                    {
                        "signature": signature,
                        "repeatCount": 0,
                        "windowStartedAt": now,
                        "maxElapsedMs": elapsed_ms,
                        "lastFields": fields,
                    }
                )
                _emit_team_detail_loaded(fields, reason="changed")
                return

            state["lastFields"] = fields
            state["maxElapsedMs"] = max(int(state.get("maxElapsedMs") or 0), elapsed_ms)
            if elapsed_ms >= TEAM_DETAIL_LOG_SLOW_THRESHOLD_MS:
                _emit_team_detail_rollup(team_id, state, now=now)
                state["maxElapsedMs"] = elapsed_ms
                _emit_team_detail_loaded(fields, reason="slow")
                return

            state["repeatCount"] = int(state.get("repeatCount") or 0) + 1
            if (
                int(state.get("repeatCount") or 0) >= TEAM_DETAIL_LOG_ROLLUP_REPEAT_THRESHOLD
            ):
                _emit_team_detail_rollup(team_id, state, now=now)
    except Exception as exc:
        _debug_logger.warning(f"Failed to record team detail loaded telemetry. error={exc}")


def _record_team_membership_conflict(team_id: str, agent_id: str, conflict: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            "team.membership_conflict_rejected",
            message="Team member assignment rejected because the Agent already belongs to another active Team",
            outcome="blocked",
            fields={
                "teamId": team_id,
                "agentId": agent_id,
                "conflictTeamId": conflict.get("teamId"),
                "conflictTeamName": conflict.get("name"),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record team membership conflict for team={team_id}. error={exc}")


def _record_team_archive_rejected(
    team: dict[str, Any],
    *,
    reason: str,
    agent_id: str = "",
    error: Exception | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            "team.archive_rejected",
            message="Team archive rejected before cascading Agent archive.",
            outcome="blocked",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "reason": str(reason or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "errorType": type(error).__name__ if error else "",
                "message": str(error) if error else "",
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record team archive rejected for team={team.get('teamId')}. error={exc}")


def _record_archived_team_member_cascade_repaired(
    team: dict[str, Any],
    archived_agent_ids: list[str],
    *,
    reason: str,
) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team_repair",
            "team.archived_agent_cascade_repaired",
            message="Archived Team had active member Agents; cascading archive repair applied.",
            outcome="repaired",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
                "archivedAgentIds": archived_agent_ids,
                "archivedAgentCount": len(archived_agent_ids),
                "reason": str(reason or "").strip(),
            },
        )
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to record archived team member cascade repaired for team={team.get('teamId')}. error={exc}"
        )


def _record_compact_chat_room_sync_skipped_busy(team: dict[str, Any], linked_room_id: str, exc: Exception) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team_compact_repair",
            "team.compact_chat_room_sync_skipped_busy",
            message="Team compact repair skipped linked chat room metadata sync because the room has an active round.",
            level="warning",
            outcome="skipped",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or _infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
                "linkedChatRoomId": str(linked_room_id or "").strip(),
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to record compact chat room sync skipped busy for team={team.get('teamId')}, linked_room_id={linked_room_id}. error={exc}"
        )


def _record_system_team_membership_conflict(team_id: str, agent_id: str, conflict: dict[str, Any], *, source: str) -> None:
    try:
        record_runtime_scene_event(
            "team_service",
            "team",
            "team.system_membership_conflict",
            message="System Team member was not synced because the Agent already belongs to another active Team",
            outcome="blocked",
            fields={
                "teamId": team_id,
                "agentId": agent_id,
                "source": source,
                "conflictTeamId": conflict.get("teamId"),
                "conflictTeamName": conflict.get("name"),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record system team membership conflict for team={team_id}. error={exc}")


def _record_system_team_sync_failed(source: str, exc: Exception) -> None:
    try:
        normalized_source = str(source or "").strip()
        event_code = "team.ai_search_system_sync_failed" if normalized_source == "ai_search" else "team.system_evolution_sync_failed"
        message = "AI search system Team sync failed" if normalized_source == "ai_search" else "System evolution Team sync failed"
        record_runtime_scene_event(
            "team_service",
            "team",
            event_code,
            message=message,
            level="warning",
            outcome="failed",
            fields={
                "source": normalized_source,
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record system team sync failure source={source}. error={exc}")
