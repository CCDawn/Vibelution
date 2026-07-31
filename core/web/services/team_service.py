"""Team registry and organization canvas service."""

from __future__ import annotations

import json
import copy
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
from .team.canvas_primitives import (
    EDGE_TYPES,
    NODE_TYPES,
    TeamCanvasValidationError,
    _SAFE_ID_FRAGMENT,
    _issue,
    _normalize_edge as _normalize_edge_pure,
    _safe_float,
    _safe_token,
)
from .team.kind_helpers import (
    AI_SEARCH_TEAM_ID as _KIND_AI_SEARCH_TEAM_ID,
    KNOWLEDGE_EXPANSION_TEAM_ID as _KIND_KNOWLEDGE_EXPANSION_TEAM_ID,
    TEAM_ID_TO_KIND as _KIND_TEAM_ID_TO_KIND,
    TEAM_KIND_DEFAULTS as _KIND_TEAM_KIND_DEFAULTS,
    TEAM_SOURCE_TO_KIND as _KIND_TEAM_SOURCE_TO_KIND,
    TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID as _KIND_TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID,
    DERIVED_TEAM_KINDS as _KIND_DERIVED_TEAM_KINDS,
    _infer_team_kind,
    _infer_team_template_id,
    _team_default_chat_room_purpose,
    _team_kind_allows_member_agent_cascade,
)
from .team.ai_search_ranking import (
    _ai_search_source_page_keywords,
    _clean_ai_search_source_text,
    _rank_ai_search_source_page_references,
)
from .team import system_bootstrap as _system_bootstrap
from .team import system_teams as _system_teams
from .team import chat_room_links as _chat_room_links
from .team import canvas_normalize as _canvas_normalize
from .team import ai_search as _ai_search
from .team import research_organization as _research_organization
from .team import team_crud as _team_crud
from .team import team_repair as _team_repair
from .team import team_projection as _team_projection
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
    "checkedAtMonotonic": 0.0,
}
_TEAM_DETAIL_LOG_LOCK = threading.Lock()
_TEAM_DETAIL_LOG_STATE: dict[str, dict[str, Any]] = {}
TEAM_DETAIL_LOG_SLOW_THRESHOLD_MS = 250
TEAM_DETAIL_LOG_ROLLUP_REPEAT_THRESHOLD = 5
TEAM_DETAIL_LOG_ROLLUP_WINDOW_SECONDS = 5.0
TEAM_SYSTEM_BOOTSTRAP_READY_CACHE_TTL_SECONDS = 30.0
AI_SEARCH_SOURCE_PAGE_TIMEOUT_SECONDS = 8.0
AI_SEARCH_SOURCE_PAGE_MAX_BYTES = 400_000
AI_SEARCH_SOURCE_PAGE_USER_AGENT = "Vibelution-AI-Search/1.0"
EVOLUTION_SYSTEM_TEAM_IDS = {"self-evolution-team", "supervised-evolution-team"}
EVOLUTION_SYSTEM_TEAM_SPECS = (
    {
        "teamId": "self-evolution-team",
        "name": "自进化团队",
        "description": "由自进化固定角色自动同步的系统团队。",
        "purpose": "承接自进化执行、评审与旁路观察角色的团队通讯。",
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
TEAM_KIND_DEFAULTS = _KIND_TEAM_KIND_DEFAULTS
DERIVED_TEAM_KINDS = _KIND_DERIVED_TEAM_KINDS
TEAM_SOURCE_TO_KIND = _KIND_TEAM_SOURCE_TO_KIND
TEAM_ID_TO_KIND = _KIND_TEAM_ID_TO_KIND
RESEARCH_TEAM_MEMBER_ROLE_KEYS = {
    "research_coordination": "challenge_cup_coordinator",
    "source_finder": "source_finder",
    "source_extractor": "source_extractor",
    "source_relation_mapper": "source_relation_mapper",
    "source_ingestor": "source_ingestor",
    "experiment_planner": "challenge_cup_experiment_planner",
    "experiment_ledger": "challenge_cup_experiment_ledger",
    "iteration_planner": "challenge_cup_iteration_planner",
    "iteration_versioning": "challenge_cup_versioning",
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
        "role": "source_finder",
        "roleKey": "source_finder",
        "label": "资料寻找",
        "purpose": "搜索、获取并登记可追溯资料",
        "responsibilities": ["生成检索问题", "搜索和下载有效资料", "登记无效来源用于后续去重排除"],
    },
    {
        "role": "source_extractor",
        "roleKey": "source_extractor",
        "label": "资料提炼",
        "purpose": "提炼价值、复核质量并决定保留/排除",
        "responsibilities": ["逐条提炼候选资料", "保留有价值但不完整的资料并说明限制", "排除无有效内容来源"],
    },
    {
        "role": "source_relation_mapper",
        "roleKey": "source_relation_mapper",
        "label": "资料关系整理",
        "purpose": "整理候选资料之间的主题和证据关系",
        "responsibilities": ["生成候选关系", "标注断链缺口", "预览入库前关系边界"],
    },
    {
        "role": "source_ingestor",
        "roleKey": "source_ingestor",
        "label": "资料入库",
        "purpose": "最终审核并写入正式 Team Knowledge",
        "responsibilities": ["复核可入库资料", "执行正式知识库入库", "拒绝低置信或缺证据资料"],
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
)
KNOWLEDGE_EXPANSION_TEAM_AGENT_CREATED_BY = "knowledge_expansion_team"
KNOWLEDGE_EXPANSION_TEAM_ROLES: tuple[dict[str, Any], ...] = (
    {
        "role": "source_finder",
        "roleKey": "source_finder",
        "label": "资料寻找",
        "purpose": "本地资料导入、网络资料发现和可追溯登记",
        "responsibilities": ["扫描本地知识资料", "搜索公开资料线索", "把有效来源写回受控资料批次"],
    },
    {
        "role": "source_extractor",
        "roleKey": "source_extractor",
        "label": "资料提炼",
        "purpose": "提炼价值、复核质量并决定保留/排除",
        "responsibilities": ["提炼可入库摘要", "标注证据引用", "排除无有效内容来源并记录来源"],
    },
    {
        "role": "source_relation_mapper",
        "roleKey": "source_relation_mapper",
        "label": "资料关系整理",
        "purpose": "候选知识关系预览",
        "responsibilities": ["生成候选关系", "检查断链", "保持正式图谱写入边界"],
    },
    {
        "role": "source_ingestor",
        "roleKey": "source_ingestor",
        "label": "资料入库",
        "purpose": "最终审核并写入正式 Team Knowledge",
        "responsibilities": ["复核高置信资料", "执行正式知识库入库", "拒绝低置信或缺证据资料"],
    },
)
TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID = _KIND_TEMPLATE_MEMBER_PREFIX_TO_TEMPLATE_ID
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


def _try_acquire_team_lock() -> bool:
    try:
        return bool(_TEAM_LOCK.acquire(blocking=False))
    except TypeError:
        return bool(_TEAM_LOCK.acquire(False))


def _release_team_lock_if_acquired(acquired: bool) -> None:
    if acquired:
        _TEAM_LOCK.release()


request_system_team_bootstrap = _system_bootstrap.request_system_team_bootstrap
_run_system_team_bootstrap_discovery = _system_bootstrap._run_system_team_bootstrap_discovery
_system_team_bootstrap_required_steps = _system_bootstrap._system_team_bootstrap_required_steps
_system_team_bootstrap_state_snapshot_locked = _system_bootstrap._system_team_bootstrap_state_snapshot_locked
_run_system_team_bootstrap = _system_bootstrap._run_system_team_bootstrap
_record_system_team_bootstrap_event = _system_bootstrap._record_system_team_bootstrap_event

evolution_system_teams_missing = _system_teams.evolution_system_teams_missing
challenge_cup_research_team_agents_need_repair = _system_teams.challenge_cup_research_team_agents_need_repair
_challenge_cup_research_team_agent_direct_session_available = _system_teams._challenge_cup_research_team_agent_direct_session_available
ensure_challenge_cup_research_team_agents = _system_teams.ensure_challenge_cup_research_team_agents
knowledge_expansion_team_agents_need_repair = _system_teams.knowledge_expansion_team_agents_need_repair

list_archived_team_linked_chat_room_ids = _chat_room_links.list_archived_team_linked_chat_room_ids
sync_team_chat_room = _chat_room_links.sync_team_chat_room
_remove_team_member_agents_from_chat_rooms = _chat_room_links._remove_team_member_agents_from_chat_rooms
_team_chat_room_title = _chat_room_links._team_chat_room_title
_team_participant_contexts_by_agent_id = _chat_room_links._team_participant_contexts_by_agent_id
_sync_chat_room_root = _chat_room_links._sync_chat_room_root
_team_chat_room_purpose_for_update = _chat_room_links._team_chat_room_purpose_for_update
_ensure_team_chat_room_link = _chat_room_links._ensure_team_chat_room_link
_find_existing_team_chat_room_id = _chat_room_links._find_existing_team_chat_room_id
_find_historical_team_chat_room_id = _chat_room_links._find_historical_team_chat_room_id
_historical_team_chat_room_ids = _chat_room_links._historical_team_chat_room_ids
_ensure_historical_team_chat_room_links = _chat_room_links._ensure_historical_team_chat_room_links
_archive_duplicate_team_chat_rooms = _chat_room_links._archive_duplicate_team_chat_rooms
repair_archived_team_chat_rooms = _chat_room_links.repair_archived_team_chat_rooms
_repair_archived_team_linked_chat_room = _chat_room_links._repair_archived_team_linked_chat_room
_delete_team_linked_chat_rooms = _chat_room_links._delete_team_linked_chat_rooms
_team_chat_room_needs_sync = _chat_room_links._team_chat_room_needs_sync
_team_chat_room_participant_contexts_need_sync = _chat_room_links._team_chat_room_participant_contexts_need_sync
_normalized_participant_context_value = _chat_room_links._normalized_participant_context_value
_historical_team_chat_room_needs_sync = _chat_room_links._historical_team_chat_room_needs_sync
_sync_compact_team_chat_room_metadata = _chat_room_links._sync_compact_team_chat_room_metadata
_compact_chat_room = _chat_room_links._compact_chat_room
_record_compact_chat_room_sync_skipped_busy = _chat_room_links._record_compact_chat_room_sync_skipped_busy

get_team_canvas = _canvas_normalize.get_team_canvas
_team_canvas_with_validation = _canvas_normalize._team_canvas_with_validation
save_team_canvas = _canvas_normalize.save_team_canvas
_normalize_canvas = _canvas_normalize._normalize_canvas
_normalize_node = _canvas_normalize._normalize_node
_source_authority_ref = _canvas_normalize._source_authority_ref
_projection_edit_contract = _canvas_normalize._projection_edit_contract
_validate_canvas = _canvas_normalize._validate_canvas
_normalize_members = _canvas_normalize._normalize_members
_ensure_members_can_join_team = _canvas_normalize._ensure_members_can_join_team
_members_without_cross_team_conflicts = _canvas_normalize._members_without_cross_team_conflicts
_remove_agent_from_team_canvas = _canvas_normalize._remove_agent_from_team_canvas
_sync_members_from_canvas = _canvas_normalize._sync_members_from_canvas
_default_canvas_for_team = _canvas_normalize._default_canvas_for_team
_ai_search_canvas_for_team = _canvas_normalize._ai_search_canvas_for_team
_ai_search_canvas_edges = _canvas_normalize._ai_search_canvas_edges
_ai_search_canvas_needs_sync = _canvas_normalize._ai_search_canvas_needs_sync
_default_nodes_for_members = _canvas_normalize._default_nodes_for_members
_default_edges_for_team = _canvas_normalize._default_edges_for_team
_edges_from_role_chain = _canvas_normalize._edges_from_role_chain
_edges_from_role_links = _canvas_normalize._edges_from_role_links
_default_canvas_edges_missing_for_team = _canvas_normalize._default_canvas_edges_missing_for_team
_canvas_summary_for_team = _canvas_normalize._canvas_summary_for_team
_canvas_path_summary = _canvas_normalize._canvas_path_summary

list_ai_search_source_scope_runs = _ai_search.list_ai_search_source_scope_runs
start_ai_search_source_scope_run = _ai_search.start_ai_search_source_scope_run
_default_ai_search_source_scope = _ai_search._default_ai_search_source_scope
_ai_search_source_scope_needs_sync = _ai_search._ai_search_source_scope_needs_sync
_ensure_ai_search_source_scope_file = _ai_search._ensure_ai_search_source_scope_file
_load_ai_search_source_scope = _ai_search._load_ai_search_source_scope
_ai_search_source_scope_api_fields = _ai_search._ai_search_source_scope_api_fields
_select_ai_search_sources = _ai_search._select_ai_search_sources
_ai_search_query_for_source = _ai_search._ai_search_query_for_source
_execute_ai_search_query_card = _ai_search._execute_ai_search_query_card
_run_ai_web_search = _ai_search._run_ai_web_search
_run_ai_source_page_fallback = _ai_search._run_ai_source_page_fallback
_fetch_ai_search_source_page = _ai_search._fetch_ai_search_source_page
_parse_ai_search_source_page = _ai_search._parse_ai_search_source_page
_AiSearchSourcePageParser = _ai_search._AiSearchSourcePageParser
_ai_search_result_is_error = _ai_search._ai_search_result_is_error
_web_search_summary_text = _ai_search._web_search_summary_text
_references_from_web_search_result = _ai_search._references_from_web_search_result
_new_ai_search_run_id = _ai_search._new_ai_search_run_id
_load_ai_search_runs_index = _ai_search._load_ai_search_runs_index
_upsert_ai_search_run_summary = _ai_search._upsert_ai_search_run_summary
_ai_search_source_scope_path = _ai_search._ai_search_source_scope_path
_ai_search_runs_root = _ai_search._ai_search_runs_root
_ai_search_runs_index_path = _ai_search._ai_search_runs_index_path
_ai_search_run_path = _ai_search._ai_search_run_path

ensure_research_team_from_organization = _research_organization.ensure_research_team_from_organization
_members_from_research_organization = _research_organization._members_from_research_organization
_sync_research_team_member_agent_roles = _research_organization._sync_research_team_member_agent_roles
_canvas_from_research_organization = _research_organization._canvas_from_research_organization
_organization_reporting_edges = _research_organization._organization_reporting_edges
_resolve_report_to_agent_id = _research_organization._resolve_report_to_agent_id
_research_org_role = _research_organization._research_org_role
_normalize_report_to_reference = _research_organization._normalize_report_to_reference
_research_member_function_label = _research_organization._research_member_function_label
_research_member_responsibilities = _research_organization._research_member_responsibilities
_responsibility_values = _research_organization._responsibility_values

list_teams = _team_crud.list_teams
list_teams_compact = _team_crud.list_teams_compact
list_team_graph_references = _team_crud.list_team_graph_references
create_team = _team_crud.create_team
get_team = _team_crud.get_team
get_team_light = _team_crud.get_team_light
assert_team_exists = _team_crud.assert_team_exists
update_team = _team_crud.update_team
remove_agent_from_teams = _team_crud.remove_agent_from_teams
remove_agents_from_teams = _team_crud.remove_agents_from_teams
restore_removed_agents_to_teams = _team_crud.restore_removed_agents_to_teams
archive_team = _team_crud.archive_team
_archive_team_in_state = _team_crud._archive_team_in_state
send_team_message = _team_crud.send_team_message
list_agent_team_references = _team_crud.list_agent_team_references
_find_reusable_empty_team = _team_crud._find_reusable_empty_team
_new_team_id = _team_crud._new_team_id
_normalized_team_dedupe_key = _team_crud._normalized_team_dedupe_key
_summary = _team_crud._summary

_ensure_team_member_agents_can_archive = _team_repair._ensure_team_member_agents_can_archive
_archive_team_member_agents = _team_repair._archive_team_member_agents
_repair_archived_team_member_agents = _team_repair._repair_archived_team_member_agents
_repair_archived_team_member_agents_for_team = _team_repair._repair_archived_team_member_agents_for_team
_prune_missing_archived_team_members = _team_repair._prune_missing_archived_team_members
_repair_index_state = _team_repair._repair_index_state
_repair_index_shape = _team_repair._repair_index_shape
_repair_index_compact_contracts = _team_repair._repair_index_compact_contracts
_repair_team_contract_only = _team_repair._repair_team_contract_only
_repair_team = _team_repair._repair_team
_prune_unavailable_derived_team_members = _team_repair._prune_unavailable_derived_team_members
_stale_member_agent_ids = _team_repair._stale_member_agent_ids
_repair_members = _team_repair._repair_members

_team_to_api = _team_projection._team_to_api
_team_to_compact_reference = _team_projection._team_to_compact_reference
_team_to_graph_reference = _team_projection._team_to_graph_reference
_team_detail_to_api = _team_projection._team_detail_to_api
_team_to_api_without_canvas_summary = _team_projection._team_to_api_without_canvas_summary
_members_to_api = _team_projection._members_to_api
_get_team_record = _team_projection._get_team_record
_agent_reference_maps = _team_projection._agent_reference_maps
_load_lightweight_agent_references = _team_projection._load_lightweight_agent_references
_agent_reference_maps_from_agents = _team_projection._agent_reference_maps_from_agents
_merged_agent_reference_maps = _team_projection._merged_agent_reference_maps
_agent_reference = _team_projection._agent_reference







_knowledge_expansion_team_agent_direct_session_available = _system_teams._knowledge_expansion_team_agent_direct_session_available
ensure_knowledge_expansion_team_agents = _system_teams.ensure_knowledge_expansion_team_agents
ensure_evolution_system_teams = _system_teams.ensure_evolution_system_teams
ai_search_system_team_missing = _system_teams.ai_search_system_team_missing
ensure_ai_search_system_team = _system_teams.ensure_ai_search_system_team
_ensure_evolution_system_agents = _system_teams._ensure_evolution_system_agents
_ensure_ai_search_system_agents = _system_teams._ensure_ai_search_system_agents
_ensure_challenge_cup_research_team_role_agents = _system_teams._ensure_challenge_cup_research_team_role_agents
_ensure_challenge_cup_research_team_role_agent = _system_teams._ensure_challenge_cup_research_team_role_agent
_ensure_knowledge_expansion_team_role_agents = _system_teams._ensure_knowledge_expansion_team_role_agents
_ensure_knowledge_expansion_team_role_agent = _system_teams._ensure_knowledge_expansion_team_role_agent
_agent_direct_session_available = _system_teams._agent_direct_session_available
_find_challenge_cup_research_team_agent = _system_teams._find_challenge_cup_research_team_agent
_find_knowledge_expansion_team_agent = _system_teams._find_knowledge_expansion_team_agent
_challenge_cup_research_team_role_metadata = _system_teams._challenge_cup_research_team_role_metadata
_knowledge_expansion_team_role_metadata = _system_teams._knowledge_expansion_team_role_metadata
_challenge_cup_research_team_members_from_agents = _system_teams._challenge_cup_research_team_members_from_agents
_knowledge_expansion_team_members_from_agents = _system_teams._knowledge_expansion_team_members_from_agents
_challenge_cup_research_team_bound_agent_ids = _system_teams._challenge_cup_research_team_bound_agent_ids
_challenge_cup_research_team_duplicate_agent_ids = _system_teams._challenge_cup_research_team_duplicate_agent_ids
_knowledge_expansion_team_bound_agent_ids = _system_teams._knowledge_expansion_team_bound_agent_ids
_knowledge_expansion_team_duplicate_agent_ids = _system_teams._knowledge_expansion_team_duplicate_agent_ids
_purge_knowledge_expansion_team_agents = _system_teams._purge_knowledge_expansion_team_agents
_purge_challenge_cup_research_team_agents = _system_teams._purge_challenge_cup_research_team_agents
_purge_challenge_cup_research_team_agent = _system_teams._purge_challenge_cup_research_team_agent
_delete_orphan_agent_workspace = _system_teams._delete_orphan_agent_workspace
_safe_agent_workspace_name = _system_teams._safe_agent_workspace_name
_ensure_ai_search_role_agent = _system_teams._ensure_ai_search_role_agent
_find_agent_by_ai_search_role = _system_teams._find_agent_by_ai_search_role
_ai_search_role_metadata = _system_teams._ai_search_role_metadata
_ai_search_members_from_agents = _system_teams._ai_search_members_from_agents
_ensure_evolution_system_team_in_state = _system_teams._ensure_evolution_system_team_in_state
_system_members_from_agents = _system_teams._system_members_from_agents



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


def _normalize_required_id(value: str, message: str) -> str:
    normalized = _safe_token(value, default="", max_length=96)
    if not normalized:
        raise TeamServiceError(message)
    return normalized





def _format_validation_error(validation: dict[str, Any]) -> str:
    issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
    details = "; ".join(str(item.get("message") or item.get("code") or "") for item in issues[:3] if isinstance(item, dict))
    return f"Team canvas contract invalid: {details or 'unknown validation error'}"


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
