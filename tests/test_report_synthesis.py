"""Deep-research report synthesis skeleton: assembly and citation integrity."""

from __future__ import annotations

from core.research.report_synthesis import (
    MAX_ITEMS_PER_REPORT,
    build_report_skeleton,
    check_citation_integrity,
    normalize_report_items,
    render_skeleton_markdown,
)


def _items() -> list[dict]:
    return [
        {
            "itemId": "ki-1",
            "title": "图神经网络综述",
            "summary": "GNN 在材料筛选中应用广泛。",
            "sourceRefs": ["https://example.com/gnn-survey", "paper://doi/10.1/x"],
            "section": "证据",
        },
        {
            "itemId": "ki-2",
            "title": "假说评审标准",
            "summary": "评审聚焦机制可解释性。",
            "sourceRefs": [],
            "section": "方法",
        },
        {"itemId": "ki-1", "title": "重复条目应被去重", "summary": "", "sourceRefs": []},
        {"itemId": "", "title": "空 id 丢弃", "summary": ""},
        {"itemId": "ki-3", "title": "未知分区归入证据", "summary": "默认分区。", "sourceRefs": ["src-1"], "section": "不存在分区"},
    ]


def test_normalize_dedupes_and_defaults():
    items = normalize_report_items(_items())
    assert [item["itemId"] for item in items] == ["ki-1", "ki-2", "ki-3"]
    # Unknown sections survive normalization; the skeleton maps them to 证据.
    assert items[2]["section"] == "不存在分区"
    skeleton = build_report_skeleton(_items(), report_id="rep", topic="t")
    evidence = next(s for s in skeleton["sections"] if s["section"] == "证据")
    assert any(entry["itemId"] == "ki-3" for entry in evidence["entries"])


def test_skeleton_groups_sections_and_builds_citation_index():
    skeleton = build_report_skeleton(_items(), report_id="rep-1", topic="材料筛选")
    section_names = [section["section"] for section in skeleton["sections"]]
    assert section_names == ["方法", "证据"]
    assert skeleton["citationIndex"]["KI-ki-1"]["sourceRefs"] == [
        "https://example.com/gnn-survey",
        "paper://doi/10.1/x",
    ]


def test_markdown_render_anchors_every_item():
    skeleton = build_report_skeleton(_items(), report_id="rep-1", topic="材料筛选")
    markdown = render_skeleton_markdown(skeleton)
    assert "# 材料筛选" in markdown
    assert "[KI-ki-1] 图神经网络综述" in markdown
    assert "（来源：https://example.com/gnn-survey, paper://doi/10.1/x）" in markdown
    assert "（无来源标注）" in markdown


def test_citation_integrity_flags_unsourced_items():
    skeleton = build_report_skeleton(_items(), report_id="rep-1", topic="t")
    problems = check_citation_integrity(skeleton)
    assert problems == ["KI-ki-2 has no source reference"]


def test_item_cap_bounds_the_report():
    bulk = [
        {"itemId": f"ki-{index}", "title": f"t{index}", "summary": "s", "sourceRefs": ["x"]}
        for index in range(MAX_ITEMS_PER_REPORT + 10)
    ]
    skeleton = build_report_skeleton(bulk, report_id="rep", topic="t")
    assert skeleton["itemCount"] == MAX_ITEMS_PER_REPORT
