"""Team domain constants and curated role/source catalogs.

Claim scope: immutable team IDs display names, status enums, thresholds,
system-role catalogs, and AI-search source-scope groups.
Kind maps remain in kind_helpers; mutable locks/state stay on team_service.
"""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import CURRENT_RESEARCH_TEAM_ROLE_CONTRACT

from .kind_helpers import (
    AI_SEARCH_TEAM_ID,
    KNOWLEDGE_EXPANSION_TEAM_ID,
)

SCHEMA_VERSION = 1
CANVAS_KIND = "team_organization_canvas"
RESEARCH_TEAM_DISPLAY_NAME = "挑战杯ai科研团队"
AI_SEARCH_TEAM_DISPLAY_NAME = "AI 搜索范围团队"
KNOWLEDGE_EXPANSION_TEAM_DISPLAY_NAME = "知识库内容扩充团队"
DEFAULT_TEAM_STATUS = "active"
TEAM_STATUSES = {"active", "archived"}
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
_LEGACY_RESEARCH_TEAM_MEMBER_ROLE_KEYS = {
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
RESEARCH_TEAM_MEMBER_ROLE_KEYS = {
    **_LEGACY_RESEARCH_TEAM_MEMBER_ROLE_KEYS,
    **{
        role.product_role_id: role.product_role_id
        for role in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_agents
    },
}
CHALLENGE_CUP_RESEARCH_TEAM_ID = "research-team"
CHALLENGE_CUP_RESEARCH_TEAM_AGENT_CREATED_BY = "challenge_cup_team"
CHALLENGE_CUP_RESEARCH_TEAM_DIALOGUE_MODEL_REF = (
    "opencode_go/deepseek-v4-flash"
)
CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT = (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.to_dict()
)
CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_VERSION = int(
    CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT["teamRoleContractVersion"]
)
CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT_FINGERPRINT = str(
    CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT["roleContractFingerprint"]
)
CHALLENGE_CUP_RESEARCH_TEAM_PARTICIPANT_POLICY_VERSION = int(
    CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT["participantPolicyVersion"]
)
CHALLENGE_CUP_RESEARCH_TEAM_LEGACY_READ_MODE = str(
    CHALLENGE_CUP_RESEARCH_TEAM_ROLE_CONTRACT["legacyReadMode"]
)

_CHALLENGE_CUP_ROLE_RESPONSIBILITIES: dict[str, list[str]] = {
    "challenge_cup_search": ["把知识缺口转为检索问题", "登记有效与无效来源", "保持来源可追溯"],
    "challenge_cup_extractor": ["提取证据与反证", "标注引用和限制", "拒绝不可定位内容"],
    "challenge_cup_knowledge_manager": ["治理证据关系与作用域", "维护 lineage", "控制知识候选提升边界"],
    "challenge_cup_execution_steward": ["提交冻结协议", "观察受控运行", "登记不可变 artifact locator"],
    "challenge_cup_experiment_revision": ["生成和修订假说", "修订实验协议", "提出迭代与停止建议"],
    "challenge_cup_evaluator": ["独立审查指标与稳健性", "登记负结果", "约束主张边界"],
}

CHALLENGE_CUP_RESEARCH_TEAM_ROLES: tuple[dict[str, Any], ...] = tuple(
    {
        "role": role.product_role_id,
        "roleKey": role.product_role_id,
        "label": role.label,
        "purpose": role.purpose,
        "responsibilities": list(
            _CHALLENGE_CUP_ROLE_RESPONSIBILITIES.get(role.product_role_id, ())
        ),
        "legacyRoleAliases": list(role.legacy_role_aliases),
    }
    for role in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_agents
)

CHALLENGE_CUP_RESEARCH_TEAM_LEGACY_ROLE_OWNERS: dict[str, dict[str, Any]] = {}
for product_role in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.product_agents:
    for alias_priority, alias in enumerate(product_role.legacy_role_aliases):
        CHALLENGE_CUP_RESEARCH_TEAM_LEGACY_ROLE_OWNERS[alias] = {
            "ownerType": "product_agent",
            "ownerId": product_role.product_role_id,
            "aliasPriority": alias_priority,
        }
for system_capability in CURRENT_RESEARCH_TEAM_ROLE_CONTRACT.system_capabilities:
    for alias_priority, alias in enumerate(system_capability.legacy_role_aliases):
        CHALLENGE_CUP_RESEARCH_TEAM_LEGACY_ROLE_OWNERS[alias] = {
            "ownerType": "system_capability",
            "ownerId": system_capability.capability_id,
            "aliasPriority": alias_priority,
        }
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
