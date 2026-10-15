"""Pure display labels; never create or rewrite canonical knowledge facts."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_TAG_LABELS = {
    "financial_reports_v1": "财报与公司研究",
    "project-api": "平台操作规范",
    "agent-operations": "平台操作规范",
    "虚构验收": "虚构验收资料",
}
_BASE_ALIASES = {
    "financial reports": "财报与公司研究",
    "knowledge expansion library": "科研文献",
}
_INTERNAL_NAMES = {
    "backfill", "team_knowledge_expansion", "agent-lifecycle", "agent-inbox",
    "source_collection", "paper_note", "review_record", "candidate", "research_ref",
    "synced", "official_synced", "approved", "active", "pending", "knowledge_item",
}
_IDENTIFIER = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[0-9a-f]{12,}|(?:candidate|cand|kb|item|knowledge[_-]?item|source|src|artifact|"
    r"batch|review|proposal|record|team|agent|paper[_-]?note|mechanism)[_:\-].+)\Z",
    re.IGNORECASE,
)
_DATE_OR_CODE = re.compile(
    r"^(?:\d{4}(?:[-/.]\d{1,2}){0,2}(?:[T _-].*)?|\d{8}(?:[_-].*)?"
    r"|\d{4}(?i:FY|Q[1-4])|(?i:FY|Q[1-4])\d{4}|[A-Za-z]{1,8}[-_.]?\d{2,}"
    r"|(?i:SH|SZ|HK)[.:]?\d{4,6}|\d{4,6}(?:[.:](?i:SH|SZ|HK))?|[A-Z]{2,5})\Z"
)
_TITLE_GROUPS = (
    ("数论与黎曼猜想", ("zeta", "Riemann", "zero-free", "De Bruijn", "Odlyzko")),
    ("计算物理与能耗", ("Landauer", "CMOS", "Dennard", "computational capacity",
     "physical limits to computation", "photonic", "optical computing", "Margolus", "Bremermann", "qubits", "quantum gates", "Amdahl", "parallel computing")),
    ("DNA与信息存储", ("DNA storage", "DNA data storage", "DNA-based data storage", "DNA-based Data Storage Systems", "DNA as a storage", "DNA as a digital information storage", "Archival DNA Storage")),
    ("细胞重编程与生物工程", ("reprogramming", "pluripotent", "stem cells")),
    ("自闭症研究", ("autism", "autistic", "ASD")),
    ("神经科学与睡眠", ("sleep", "synaptic", "plasticity", "neuron", "neurons", "glymphatic", "CSF", "brain", "astrocyte")),
    ("算法与机器学习", ("machine learning", "neural network", "reinforcement learning")),
)
_TITLE_PATTERNS = tuple(
    (label, re.compile(r"(?<!\w)(?:" + "|".join(re.escape(word) for word in words) + r")(?!\w)", re.IGNORECASE))
    for label, words in _TITLE_GROUPS
)


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _readable_name(value: Any) -> str:
    text = _text(value)
    if not text or text.casefold() in _INTERNAL_NAMES:
        return ""
    if re.search(r"(?:https?://|www\.|^[a-z][a-z0-9+.-]*://)", text, re.IGNORECASE):
        return ""
    if "\\" in text or _IDENTIFIER.fullmatch(text) or _DATE_OR_CODE.fullmatch(text):
        return ""
    # Machine slugs are useful identifiers, but do not name a reading topic.
    if re.fullmatch(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+|[a-z0-9]+(?:-[a-z0-9]+)+", text):
        return ""
    if not re.search(r"[\u3400-\u9fffA-Za-z]", text):
        return ""
    return text


def _tag_label(value: Any) -> str:
    tag = _text(value)
    known = _TAG_LABELS.get(tag.casefold())
    if known:
        return known
    if tag.casefold().startswith("finance-"):
        return "财报与公司研究"
    return _readable_name(tag)


def choose_display_topic(item: Mapping[str, Any], base: Mapping[str, Any]) -> tuple[str, str, str]:
    """Choose a readable grouping with its evidence basis and display-only reason."""
    metadata = item.get("metadata")
    official = metadata.get("officialResearchGraph") if isinstance(metadata, Mapping) else None
    if isinstance(official, Mapping) and official.get("status") == "synced":
        domain = _readable_name(official.get("targetDomain"))
        if domain:
            return domain, "official_target_domain", "按已同步的可读科研领域展示分组。"

    tags = item.get("tags")
    if isinstance(tags, (list, tuple)):
        # Prefer known semantic labels over generic product names or batch tags,
        # regardless of which tag the ingestion process emitted first.
        for tag in tags:
            text = _text(tag).casefold()
            if text in _TAG_LABELS or text.startswith("finance-"):
                return _tag_label(tag), "tag", "按已有语义标签展示分组，未表示全部分类。"
        for tag in tags:
            label = _tag_label(tag)
            if label:
                return label, "tag", "按已有语义标签展示分组，未表示全部分类。"

    title = _text(item.get("title"))
    for label, pattern in _TITLE_PATTERNS:
        if pattern.search(title):
            return label, "title_keywords", "按标题关键词匹配，仅用于展示分组，不新建知识事实。"

    base_name = _text(base.get("name") or base.get("baseName"))
    alias = _BASE_ALIASES.get(base_name.casefold())
    readable_base = _readable_name(base_name)
    if alias or readable_base:
        return alias or readable_base, "knowledge_base", "无可读主题分类，按所属知识库展示分组。"
    return "未分类知识", "knowledge_base", "无可读主题或知识库名称，使用通用展示分组。"


def reference_display_name(
    sourceType: str, sourceId: str, targetTitle: str, explicitTitle: str = "",
) -> tuple[str, str]:
    """Name a reference without treating its target's title as its own title.

    sourceId is identity context only. No lookup or canonical title is inferred.
    """
    title = _readable_name(explicitTitle)
    if title:
        return title, "使用引用记录已有标题。"
    source_type = _text(sourceType).casefold()
    labels = {
        "candidate": "已审核入库记录",
        "review_record": "入库审核记录",
        "source": "研究来源",
        "source_artifact": "来源资料",
        "paper_note": "论文笔记",
        "mechanism": "机制记录",
        "neuro_mechanism": "神经机制记录",
        "mechanism_mapping": "机制映射记录",
    }
    label = labels.get(source_type, "科研关联记录")
    target = _readable_name(targetTitle)
    if target:
        return label, f"关联知识：{target}。未提供引用自身标题；该知识标题仅作为阅读上下文。"
    return label, "未提供引用自身标题或可读关联知识标题，按记录类型显示。"


def document_display_name(title: Any, *, source: bool = False) -> str:
    return _readable_name(title) or ("来源资料（尚缺标题）" if source else "知识条目（尚缺标题）")
