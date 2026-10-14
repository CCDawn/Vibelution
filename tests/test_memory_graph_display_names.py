"""Display grouping must not promote pipeline metadata into knowledge facts."""
from copy import deepcopy

import pytest

from core.web.services.memory.display_names import choose_display_topic, reference_display_name


def _item(title="", *, domain="", tags=(), status="synced"):
    return {"title": title, "tags": list(tags), "metadata": {
        "officialResearchGraph": {"targetDomain": domain, "status": status}}}


@pytest.mark.parametrize("domain", ["神经预测编码", "Number Theory and Riemann Hypothesis"])
def test_readable_canonical_domain_precedes_tags_and_title(domain):
    assert choose_display_topic(_item("Landauer energy", domain=domain, tags=["finance-2024"]), {})[:2] == (
        domain, "official_target_domain")


@pytest.mark.parametrize("tag,label", [
    ("financial_reports_v1", "财报与公司研究"), ("finance-2024FY", "财报与公司研究"),
    ("project-api", "平台操作规范"), ("agent-operations", "平台操作规范"),
    ("虚构验收", "虚构验收资料"), ("睡眠研究", "睡眠研究"),
    ("Number Theory", "Number Theory"),
])
def test_semantic_tags_and_known_aliases_ignore_nonsemantic_tags(tag, label):
    item = _item("Riemann zeta function", domain="team_knowledge_expansion",
                 tags=["2024FY", "HL-417602", "backfill", "agent-inbox", tag])
    assert choose_display_topic(item, {})[:2] == (label, "tag")


def test_semantic_alias_priority_does_not_depend_on_ingestion_tag_order():
    assert choose_display_topic(_item(tags=["vibelution", "project-api", "agent-inbox"]), {})[0] == "平台操作规范"
    assert choose_display_topic(_item(tags=["虹岚", "虚构验收", "HL-417602"]), {})[0] == "虚构验收资料"


@pytest.mark.parametrize("title,label", [
    ("Riemann zeta and zero-free regions", "数论与黎曼猜想"),
    ("De Bruijn and Odlyzko bounds", "数论与黎曼猜想"),
    ("Landauer and physical limits to computation", "计算物理与能耗"),
    ("CMOS, Dennard and computational capacity", "计算物理与能耗"),
    ("Photonic optical computing: Margolus and Bremermann", "计算物理与能耗"),
    ("Sleep and synaptic plasticity in neuron models", "神经科学与睡眠"),
    ("Autism and autistic traits in ASD", "自闭症研究"),
    ("Machine learning with neural network and reinforcement learning", "算法与机器学习"),
    ("On Optimal Family of Codes for Archival DNA Storage", "DNA与信息存储"),
    ("Cell Reprogramming: The Many Roads to Success", "细胞重编程与生物工程"),
    ("AQP4 Regulates Glymphatic Clearance", "神经科学与睡眠"),
])
def test_pipeline_domains_and_batch_tags_fall_through_to_title_keywords(title, label):
    item = _item(title, domain="team_knowledge_expansion", tags=["backfill", "HL-417602", "2024FY"])
    assert choose_display_topic(item, {"name": "Knowledge Expansion Library"}) == (
        label, "title_keywords", "按标题关键词匹配，仅用于展示分组，不新建知识事实。")


@pytest.mark.parametrize("code", [
    "2024FY", "2024fy", "2024-10-15", "20241015-deadbeef", "HL-417602", "hl417602", "AAPL", "600519.SH",
    "candidate-123", "kb:deadbeef", "item-42", "01a0e91e-14b7-7b23-88d2-1d504db1d402",
])
def test_codes_are_neither_domains_nor_semantic_tags(code):
    assert choose_display_topic(_item(domain=code, tags=[code]), {"name": "知识资料"})[:2] == (
        "知识资料", "knowledge_base")


@pytest.mark.parametrize("title", ["NASDAQ market data", "asdasd analysis", "neuronal mechanisms"])
def test_keyword_boundaries_prevent_substring_matches(title):
    assert choose_display_topic(_item(title), {"name": "Knowledge Expansion Library"})[:2] == (
        "科研文献", "knowledge_base")


def test_unsynced_domain_is_not_promoted_and_inputs_are_unchanged():
    item = _item("Sleep in mammals", domain="其他领域", status="pending")
    base = {"name": "财报资料"}
    before = deepcopy((item, base))
    assert choose_display_topic(item, base)[:2] == ("神经科学与睡眠", "title_keywords")
    assert (item, base) == before


@pytest.mark.parametrize("name,label", [
    ("Financial Reports", "财报与公司研究"), ("Knowledge Expansion Library", "科研文献"),
    ("平台操作知识", "平台操作知识"), ("Number Theory", "Number Theory"), ("kb-001", "未分类知识"),
])
def test_base_fallback_is_readable(name, label):
    assert choose_display_topic({}, {"name": name})[:2] == (label, "knowledge_base")


def test_explicit_reference_title_is_preserved():
    assert reference_display_name("paper_note", "candidate-123", "Riemann zeta", "A note on zeta") == (
        "A note on zeta", "使用引用记录已有标题。")


def test_explicit_natural_title_does_not_depend_on_source_identifier():
    assert reference_display_name("source", "Study of x_y", "Other title", "Study of x_y")[0] == "Study of x_y"


@pytest.mark.parametrize("source_type,label", [
    ("candidate", "已审核入库记录"), ("review_record", "入库审核记录"), ("source", "研究来源"),
    ("paper_note", "论文笔记"), ("mechanism", "机制记录"), ("neuro_mechanism", "神经机制记录"),
])
def test_target_title_is_context_not_a_fabricated_reference_title(source_type, label):
    actual_label, summary = reference_display_name(source_type, "candidate-20261015-deadbeef", "Riemann zeta")
    assert actual_label == label
    assert "关联知识：Riemann zeta" in summary
    assert "未提供引用自身标题" in summary
    assert "candidate-" not in actual_label + summary


@pytest.mark.parametrize("title", ["candidate-123", "https://example.org/paper", "20261015-deadbeef", ""])
def test_missing_or_encoded_reference_title_falls_back_without_fabrication(title):
    label, summary = reference_display_name("review_record", "candidate-123", "", title)
    assert label == "入库审核记录"
    assert "未提供引用自身标题" in summary
    assert title not in label if title else True
