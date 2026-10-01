"""Bounded financial-report Q&A against an operator-configured RAGFlow chat.

The upstream finance pack owns indexing, assistant prompts and model settings.
This adapter has no ingestion, deployment, trade, or model fallback capability.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

PREFIX = "VIBELUTION_FINANCE_RAGFLOW_"
REQUIRED_CONFIG = tuple(PREFIX + key for key in ("BASE_URL", "API_KEY", "CHAT_ID"))
MAX_SOCKET_TIMEOUT_SECONDS = 120
MAX_RESPONSE_BYTES = 2_000_000
MAX_RESULT_CHARS = 3_200
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TICKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,19}\Z")
_PERIOD = re.compile(r"20\d{2}(?:FY|Q[1-4]|H[12])\Z")
_CITATION = re.compile(r"\[(?:ID:)?(\d+)\]")
_MESSAGES = {
    "not_configured": "财报服务尚未配置；请配置已部署的 RAGFlow 财报助手。",
    "invalid_config": "财报服务配置无效；请检查服务地址、助手 ID、密钥和超时设置。",
    "invalid_request": "请提供问题、一个明确的证券代码及报告期（如 2025FY 或 2025Q3）。",
    "timeout": "财报服务请求超时；本次没有可验证的答案，不会自动重试。",
    "unavailable": "财报服务暂不可用；本次没有可验证的答案。",
    "authentication_failed": "财报服务鉴权失败；请由管理员检查凭据与访问权限。",
    "upstream_error": "财报服务返回错误；本次没有可验证的答案。",
    "invalid_response": "财报服务返回了不符合约定的响应；未展示未经验证的答案。",
    "insufficient_evidence": "证据不足，无法在指定公司和报告范围内回答。",
}


class FinanceError(ValueError):
    def __init__(self, status: str):
        self.status = status
        super().__init__(_MESSAGES[status])


@dataclass(frozen=True)
class _Config:
    origin: str
    api_key: str = field(repr=False)
    chat_id: str
    timeout: float


def _load_config() -> _Config:
    values = [os.environ.get(name, "").strip() for name in REQUIRED_CONFIG]
    if not all(values):
        raise FinanceError("not_configured")
    origin, key, chat_id = values
    try:
        url = urlsplit(origin)
        port = url.port
        timeout = float(os.environ.get(PREFIX + "TIMEOUT_SECONDS", "60"))
        valid = (
            url.scheme in {"http", "https"}
            and url.hostname
            and not (url.username or url.password or url.query or url.fragment)
            and url.path in {"", "/"}
            and (
                url.scheme == "https"
                or url.hostname in {"localhost", "127.0.0.1", "::1"}
            )
            and (port is None or 1 <= port <= 65535)
            and not any(ord(c) < 33 or ord(c) > 126 for c in origin)
            and not any(ord(c) < 32 or ord(c) > 126 for c in key)
            and bool(_ID.fullmatch(chat_id))
            and math.isfinite(timeout)
            and 1 <= timeout <= MAX_SOCKET_TIMEOUT_SECONDS
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise FinanceError("invalid_config")
    return _Config(origin.rstrip("/"), key, chat_id, timeout)


def financial_report_availability() -> dict:
    """Configuration-only probe: no network, secrets, or readiness claims."""
    try:
        _load_config()
    except FinanceError as exc:
        return {
            "available": False,
            "dependency": "financial_report_service",
            "status": exc.status,
            "blockReason": str(exc),
            "requiredConfig": list(REQUIRED_CONFIG),
            "connectivityVerified": False,
        }
    return {
        "available": True,
        "dependency": "financial_report_service",
        "status": "configured",
        "blockReason": "",
        "requiredConfig": list(REQUIRED_CONFIG),
        "connectivityVerified": False,
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not send credentials or questions to a redirected destination.
        raise FinanceError("upstream_error")


def _completion(config: _Config, question: str, scope: dict) -> dict:
    payload = {
        "model": "model",
        "stream": False,
        "messages": [{"role": "user", "content": question}],
        "extra_body": {
            "reference": True,
            "reference_metadata": {
                "include": True,
                "fields": [
                    "source_id",
                    "ticker",
                    "company",
                    "report_period",
                    "source_url",
                    "input_track",
                ],
            },
            "metadata_condition": {
                "logic": "and",
                "conditions": [
                    {"name": name, "comparison_operator": "=", "value": value}
                    for name, value in scope.items()
                ],
            },
        },
    }
    request = Request(
        config.origin + f"/api/v1/openai/{config.chat_id}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        deadline = time.monotonic() + config.timeout
        with build_opener(_NoRedirect).open(
            request, timeout=config.timeout
        ) as response:
            raw = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise FinanceError("timeout")
                chunk = response.read1(min(65_536, MAX_RESPONSE_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise FinanceError("invalid_response")
            if time.monotonic() >= deadline:
                raise FinanceError("timeout")
        result = json.loads(raw)
    except HTTPError as exc:
        exc.close()
        status = (
            "authentication_failed"
            if exc.code in {401, 403}
            else (
                "unavailable"
                if exc.code == 429 or exc.code >= 500
                else "upstream_error"
            )
        )
        raise FinanceError(status) from None
    except TimeoutError:
        raise FinanceError("timeout") from None
    except URLError as exc:
        raise FinanceError(
            "timeout" if isinstance(exc.reason, TimeoutError) else "unavailable"
        ) from None
    except (OSError, HTTPException):
        raise FinanceError("unavailable") from None
    except FinanceError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise FinanceError("invalid_response") from None
    if not isinstance(result, dict):
        raise FinanceError("invalid_response")
    if result.get("code", 0) != 0 or result.get("error"):
        raise FinanceError("upstream_error")
    return result


def _text(value, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise FinanceError("invalid_response")
    return value.strip()


def _source_url(value) -> str | None:
    """Only emit ordinary HTTPS document links; never fetch references."""
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(c.isspace() for c in value)
    ):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme == "https"
            and url.hostname
            and not url.username
            and not url.password
            and not any(ord(c) < 32 for c in value)
        ):
            return value
    except ValueError:
        pass
    return None


def _answer(result: dict, scope: dict) -> dict:
    try:
        message = result["choices"][0]["message"]
        content = _text(message["content"], 16_000)
        answer = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError, RecursionError):
        raise FinanceError("invalid_response") from None
    if not isinstance(answer, dict):
        raise FinanceError("invalid_response")
    if answer.get("status") == "insufficient_evidence":
        if answer.get("value") is not None or answer.get("evidence") != []:
            raise FinanceError("invalid_response")
        raise FinanceError("insufficient_evidence")
    if answer.get("status") != "answer" or answer.get("unit") not in (
        "CNY",
        "CNY/share",
        "%",
    ):
        raise FinanceError("invalid_response")
    value = _text(answer.get("value"), 100)
    try:
        if not Decimal(value).is_finite():
            raise FinanceError("invalid_response")
    except InvalidOperation:
        raise FinanceError("invalid_response") from None
    explanation = _text(answer.get("explanation"), 3000)
    formula = answer.get("formula", "")
    if not isinstance(formula, str) or len(formula) > 1000:
        raise FinanceError("invalid_response")
    refs = message.get("reference")
    indexes = {int(n) for n in _CITATION.findall(explanation)}
    if (
        not isinstance(refs, list)
        or len(refs) > 100
        or not indexes
        or max(indexes) >= len(refs)
    ):
        raise FinanceError("insufficient_evidence")
    # A server ignoring the metadata filter must fail closed, even if its
    # out-of-scope chunks are not cited. Never return these raw references.
    for ref in refs:
        meta = ref.get("document_metadata") if isinstance(ref, dict) else None
        if not isinstance(meta, dict) or any(
            meta.get(k) != v for k, v in scope.items()
        ):
            raise FinanceError("insufficient_evidence")
    pages = {}
    for index in sorted(indexes):
        ref = refs[index]
        meta = ref["document_metadata"]
        sid = meta.get("source_id")
        positions = ref.get("positions")
        if (
            not isinstance(sid, str)
            or not _ID.fullmatch(sid)
            or meta.get("input_track") != "full_original_pdf"
            or not isinstance(positions, list)
        ):
            raise FinanceError("insufficient_evidence")
        valid_pages = {
            p[0]
            for p in positions
            if isinstance(p, list) and p and type(p[0]) is int and 1 <= p[0] <= 100_000
        }
        if not valid_pages:
            raise FinanceError("insufficient_evidence")
        for page in valid_pages:
            citation = pages.setdefault(
                (sid, page),
                {
                    "source_id": sid,
                    "page": page,
                    "source_url": _source_url(meta.get("source_url")),
                    "reference_indexes": [],
                    **scope,
                },
            )
            citation["reference_indexes"].append(index)
    evidence = answer.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 16:
        raise FinanceError("insufficient_evidence")
    citations = []
    seen = set()
    for item in evidence:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("source_id"), str)
            or type(item.get("page")) is not int
        ):
            raise FinanceError("insufficient_evidence")
        key = (item["source_id"], item["page"])
        if key not in pages:
            raise FinanceError("insufficient_evidence")
        if key not in seen:
            citations.append(pages[key])
            seen.add(key)
    if indexes != {
        index for citation in citations for index in citation["reference_indexes"]
    }:
        raise FinanceError("insufficient_evidence")
    return {
        "ok": True,
        "status": "answer",
        "scope": scope,
        "answer": {
            "value": value,
            "unit": answer["unit"],
            "explanation": explanation,
            "formula": formula,
        },
        "citations": citations,
        "evidenceTrust": "untrusted_source_data",
        "verification": "scope_and_citation_structure_only",
    }


def financial_report_query_tool(question: str, ticker: str, report_period: str) -> str:
    """Return a JSON answer with verified-scope citations, or a safe failure.

    Invoke only through Key_Tools / ToolPolicy / ToolExecutor. Only this question
    and its explicit scope reach the configured server; no chat history is sent.
    """
    scope = {}
    try:
        if (
            not isinstance(question, str)
            or not 1 <= len(question.strip()) <= 2000
            or not isinstance(ticker, str)
            or not _TICKER.fullmatch(ticker)
            or not isinstance(report_period, str)
            or not _PERIOD.fullmatch(report_period)
        ):
            raise FinanceError("invalid_request")
        try:
            question.encode("utf-8")
        except UnicodeError:
            raise FinanceError("invalid_request") from None
        scope = {"ticker": ticker, "report_period": report_period}
        config = _load_config()
        result = _answer(_completion(config, question.strip(), scope), scope)
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        try:
            encoded.encode("utf-8")
        except UnicodeError:
            raise FinanceError("invalid_response") from None
        if len(encoded) > MAX_RESULT_CHARS:
            raise FinanceError("invalid_response")
        return encoded
    except FinanceError as exc:
        return json.dumps(
            {
                "ok": False,
                "status": exc.status,
                "scope": scope,
                "answer": None,
                "citations": [],
                "message": str(exc),
                "timedOut": exc.status == "timeout",
            },
            ensure_ascii=False,
        )
