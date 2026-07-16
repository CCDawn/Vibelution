"""Disabled-by-default PaperQA2 page extraction adapter.

The adapter directly uses ``paperqa_pypdf.parse_pdf_to_pages`` when the optional
``paper-qa`` research dependency is installed. It returns candidate page text;
it never writes ClaimEvidence or formal research state by itself.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable


FEATURE_FLAG = "VIBELUTION_RESEARCH_PAPERQA2_ENABLED"


class PaperQA2AdapterError(RuntimeError):
    """Raised when the optional full-text adapter cannot safely execute."""


class PaperQA2FullTextAdapter:
    def __init__(self, *, parser: Callable[..., Any] | None = None, enabled: bool | None = None) -> None:
        self._parser = parser
        self.enabled = _env_enabled(FEATURE_FLAG) if enabled is None else bool(enabled)

    def probe(self) -> dict[str, Any]:
        if not self.enabled:
            return _probe("disabled", available=False, reason="feature_flag_disabled")
        try:
            parser = self._parser or self._load_default_parser()
        except ImportError:
            return _probe("degraded", available=False, reason="optional_dependency_unavailable")
        return {
            **_probe("available", available=True, reason=""),
            "parser": f"{parser.__module__}.{getattr(parser, '__name__', parser.__class__.__name__)}",
        }

    def extract(
        self,
        source_path: str | os.PathLike[str],
        *,
        source_id: str,
        parse_media: bool = False,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise PaperQA2AdapterError(f"PaperQA2 adapter is disabled; enable {FEATURE_FLAG} after review.")
        path = Path(source_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise PaperQA2AdapterError(f"Source PDF does not exist: {path}")
        if path.suffix.lower() != ".pdf":
            raise PaperQA2AdapterError("PaperQA2 full-text extraction accepts PDF files only.")
        normalized_source_id = str(source_id or "").strip()
        if not normalized_source_id:
            raise PaperQA2AdapterError("sourceId is required.")
        try:
            parser = self._parser or self._load_default_parser()
        except ImportError as exc:
            raise PaperQA2AdapterError("PaperQA2 optional dependency is unavailable.") from exc
        try:
            parsed = parser(str(path), parse_media=parse_media)
        except Exception as exc:
            raise PaperQA2AdapterError(f"PaperQA2 PDF parsing failed: {type(exc).__name__}") from exc
        content = getattr(parsed, "content", None)
        if not isinstance(content, dict):
            raise PaperQA2AdapterError("PaperQA2 parser returned an unsupported content shape.")
        pages = []
        for raw_page, raw_content in content.items():
            page = _positive_page(raw_page)
            text = raw_content[0] if isinstance(raw_content, tuple) else raw_content
            normalized_text = str(text or "").strip()
            if not normalized_text:
                continue
            pages.append(
                {
                    "pageEvidenceId": f"page-{page}-{hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()[:12]}",
                    "sourceId": normalized_source_id,
                    "locator": {"kind": "pdf_page", "page": page},
                    "text": normalized_text,
                    "textHash": _sha256_bytes(normalized_text.encode("utf-8")),
                    "evidenceStatus": "candidate_full_text",
                    "formalKnowledgeWriteAllowed": False,
                }
            )
        pages.sort(key=lambda item: item["locator"]["page"])
        metadata = getattr(parsed, "metadata", None)
        total_chars = int(getattr(metadata, "total_parsed_text_length", 0) or 0)
        if total_chars <= 0:
            total_chars = sum(len(item["text"]) for item in pages)
        result = {
            "schemaVersion": 1,
            "status": "completed",
            "adapter": "paperqa2-pypdf",
            "sourceId": normalized_source_id,
            "sourcePath": str(path),
            "sourceRevision": _sha256_file(path),
            "pages": pages,
            "summary": {
                "pageCount": len(content),
                "evidencePageCount": len(pages),
                "characterCount": total_chars,
            },
            "parserMetadata": {
                "libraries": list(getattr(metadata, "parsing_libraries", []) or []),
                "mediaCount": int(getattr(metadata, "count_parsed_media", 0) or 0),
                "mode": str(getattr(metadata, "name", "") or ""),
            },
            "boundaries": {
                "writesCanonicalEvidence": False,
                "writesFormalKnowledge": False,
                "requiresClaimExtraction": True,
                "requiresHumanReview": True,
            },
        }
        _record_event(
            "research_evidence.full_text_extracted",
            {
                "sourceId": normalized_source_id,
                "pageCount": len(content),
                "evidencePageCount": len(pages),
                "sourceRevision": result["sourceRevision"],
            },
        )
        return result

    @staticmethod
    def _load_default_parser():
        from paperqa_pypdf import parse_pdf_to_pages

        return parse_pdf_to_pages


def _probe(status: str, *, available: bool, reason: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "componentId": "paperqa2",
        "status": status,
        "available": available,
        "reason": reason,
        "featureFlag": FEATURE_FLAG,
        "writesCanonicalResearchState": False,
    }


def _positive_page(value: Any) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError) as exc:
        raise PaperQA2AdapterError(f"Invalid PDF page locator: {value!r}") from exc
    if page < 1:
        raise PaperQA2AdapterError(f"Invalid PDF page locator: {value!r}")
    return page


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _env_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _record_event(event_code: str, fields: dict[str, Any]) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "research_evidence",
            "full_text_adapter",
            event_code,
            message=event_code,
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return
