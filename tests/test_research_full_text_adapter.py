import pytest

from core.research.evidence_adapters import PaperQA2AdapterError, PaperQA2FullTextAdapter


class _Parsed:
    def __init__(self):
        self.content = {
            "1": "First page evidence.",
            "2": ("Second page evidence.", []),
            "3": "   ",
        }
        self.metadata = type(
            "Metadata",
            (),
            {
                "parsing_libraries": ["pypdf (6.x)"],
                "total_parsed_text_length": 42,
                "count_parsed_media": 0,
                "name": "pdf|page_range=None",
            },
        )()


def test_paperqa2_adapter_preserves_page_locators_and_source_revision(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake deterministic pdf bytes")
    calls = []

    def parser(path, **kwargs):
        calls.append((path, kwargs))
        return _Parsed()

    adapter = PaperQA2FullTextAdapter(parser=parser, enabled=True)
    result = adapter.extract(source, source_id="pmid:27917138", parse_media=False)

    assert result["status"] == "completed"
    assert result["adapter"] == "paperqa2-pypdf"
    assert result["sourceRevision"].startswith("sha256:")
    assert result["summary"] == {"pageCount": 3, "evidencePageCount": 2, "characterCount": 42}
    assert [item["locator"] for item in result["pages"]] == [
        {"kind": "pdf_page", "page": 1},
        {"kind": "pdf_page", "page": 2},
    ]
    assert result["pages"][0]["text"] == "First page evidence."
    assert result["boundaries"]["writesCanonicalEvidence"] is False
    assert calls == [(str(source.resolve()), {"parse_media": False})]


def test_paperqa2_adapter_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("VIBELUTION_RESEARCH_PAPERQA2_ENABLED", raising=False)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    adapter = PaperQA2FullTextAdapter(parser=lambda *_args, **_kwargs: _Parsed())

    probe = adapter.probe()

    assert probe["status"] == "disabled"
    assert probe["available"] is False
    with pytest.raises(PaperQA2AdapterError, match="disabled"):
        adapter.extract(source, source_id="source-1")


def test_paperqa2_adapter_rejects_non_pdf_and_missing_source(tmp_path):
    adapter = PaperQA2FullTextAdapter(parser=lambda *_args, **_kwargs: _Parsed(), enabled=True)

    with pytest.raises(PaperQA2AdapterError, match="does not exist"):
        adapter.extract(tmp_path / "missing.pdf", source_id="source-1")
    text = tmp_path / "paper.txt"
    text.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(PaperQA2AdapterError, match="PDF"):
        adapter.extract(text, source_id="source-1")


def test_paperqa2_adapter_reports_missing_optional_dependency(monkeypatch):
    adapter = PaperQA2FullTextAdapter(enabled=True)
    monkeypatch.setattr(adapter, "_load_default_parser", lambda: (_ for _ in ()).throw(ImportError("missing")))

    probe = adapter.probe()

    assert probe["status"] == "degraded"
    assert probe["available"] is False
    assert probe["reason"] == "optional_dependency_unavailable"
