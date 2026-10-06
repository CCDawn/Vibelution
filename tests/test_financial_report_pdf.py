from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader

from core.web.services.financial_report import pdf


def _reader(content: bytes) -> PdfReader:
    return PdfReader(BytesIO(content))


def _has_embedded_truetype_font(reader: PdfReader) -> bool:
    for page in reader.pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        for font_reference in resources.get("/Font", {}).values():
            font = font_reference.get_object()
            if not font.get("/ToUnicode"):
                continue
            descendants = font.get("/DescendantFonts", [font])
            for descendant_reference in descendants:
                descriptor = descendant_reference.get_object().get("/FontDescriptor")
                if descriptor and descriptor.get("/FontFile2"):
                    return True
    return False


def test_report_is_a_real_embedded_chinese_pdf_with_markdown_layout() -> None:
    long_token = "RISK" + "x" * 280 + "END"
    long_url = "https://research.example/" + "market-segment/" * 32 + "final"
    source = f"""# 三季度研究结论
营收增长，**净利润改善**；现金流保持稳定。超长标识 {long_token}，来源 {long_url}

- 经营性现金流改善
- 库存周转天数下降
1. 关注下一季毛利率
2. 持续核验应收账款

| 指标 | 本期 | 说明 |
| --- | ---: | :--- |
| 营收 | 120.5 亿元 | 同比增长 |
| 净利润 | 22 亿元 | 现金流覆盖 |

```text
结论字段 = "持续跟踪"
```"""

    content = pdf.render_pdf(
        source, title="600000 三季度报告", completed_at="2026-10-07 09:30"
    )
    reader = _reader(content)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert content.startswith(b"%PDF-")
    assert len(reader.pages) == 1
    assert "三季度研究结论" in extracted
    assert "净利润改善" in extracted
    assert "经营性现金流改善" in extracted
    assert "营收" in extracted and "120.5 亿元" in extracted
    unwrapped = "".join(extracted.split())
    assert long_token[:80] in unwrapped and long_token[-80:] in unwrapped
    assert "research.example" in extracted and "结论字段" in extracted
    assert _has_embedded_truetype_font(reader)


def test_report_adds_page_numbers_to_multi_page_output() -> None:
    source = "\n\n".join(
        f"## 第 {section} 组\n" + ("行业景气度与经营现金流需要持续核验。" * 14)
        for section in range(1, 100)
    )

    reader = _reader(
        pdf.render_pdf(source, title="多页分析", completed_at="2026-10-07")
    )

    assert len(reader.pages) > 1
    assert "第 1 页" in (reader.pages[0].extract_text() or "")
    assert "第 2 页" in (reader.pages[1].extract_text() or "")


def test_untrusted_html_and_markdown_links_remain_plain_pdf_text() -> None:
    source = "原文标签：<script>globalThis.pwned = true</script>\n[外链](https://example.test/report)"

    content = pdf.render_pdf(source, title="安全检查", completed_at="2026-10-07")
    reader = _reader(content)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    root = reader.trailer["/Root"]

    assert "<script>" in extracted and "globalThis.pwned = true" in extracted
    assert "https://example.test/report" in extracted
    assert root.get("/OpenAction") is None
    assert "/JavaScript" not in content.decode("latin1")
    assert all(not page.get("/Annots") for page in reader.pages)


def test_missing_local_cjk_font_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "_font_candidates", lambda: ())

    with pytest.raises(pdf.FinancialPdfUnavailable, match="中文字体"):
        pdf.render_pdf("中文报告", title="测试", completed_at="2026-10-07")


def test_emoji_fallback_is_embedded_and_extracts_as_exact_unicode() -> None:
    source = "市场观察 📊 🐂 🐻"

    reader = _reader(pdf.render_pdf(source, title="行情 📊", completed_at="2026-10-07"))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    font_names = {
        str(font_reference.get_object().get("/BaseFont", ""))
        for page in reader.pages
        for font_reference in page.get("/Resources", {}).get("/Font", {}).values()
    }

    assert "市场观察 📊 🐂 🐻" in extracted
    assert "行情 📊" in extracted
    assert any("SegoeUIEmoji" in font_name for font_name in font_names)
    assert _has_embedded_truetype_font(reader)


def test_uncovered_supplementary_glyph_still_fails_explicitly() -> None:
    with pytest.raises(pdf.FinancialPdfUnavailable, match="覆盖报告字符"):
        pdf.render_pdf("未覆盖字符 \U0010fffd", title="行情", completed_at="2026-10-07")


def test_rejects_reports_over_the_character_limit_before_font_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up = False

    def no_font_lookup():
        nonlocal looked_up
        looked_up = True
        return ()

    monkeypatch.setattr(pdf, "_font_candidates", no_font_lookup)
    with pytest.raises(pdf.FinancialPdfTooLarge, match="内容超过限制"):
        pdf.render_pdf(
            "x" * (pdf.MAX_PDF_TEXT_CHARS + 1), title="超限", completed_at="2026-10-07"
        )
    assert not looked_up


def test_page_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "MAX_PDF_PAGES", 1)
    source = "经营现金流持续核验。" * 4_000

    with pytest.raises(pdf.FinancialPdfTooLarge, match="页数超过限制"):
        pdf.render_pdf(source, title="页数边界", completed_at="2026-10-07")


def test_output_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "MAX_PDF_BYTES", 512)

    with pytest.raises(pdf.FinancialPdfTooLarge, match="PDF 超过大小限制"):
        pdf.render_pdf("有限大小报告", title="输出边界", completed_at="2026-10-07")
