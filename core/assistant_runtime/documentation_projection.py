"""Stateless, bounded nodes from the SDK's finite documentation response.

No HTTP, file, model, permission or schema reconstruction belongs in this view.
Pointers are data strings, never arbitrary schema keys in the result envelope.
"""
from __future__ import annotations

import hashlib
import json
import re

from pydantic import Field, field_validator

from core.infrastructure.tool_result import project_tool_result_for_model
from core.web.services.external_management.contracts import DocumentationDescribeQuery

_TARGET_CHARS = 3400
_PROTOCOL = (
    "本页只表示服务器已返回的有限文档，viewVersion=1。JSON Pointer 定位节点；offset/limit 按子节点或整段清洗后的字符跨度计数。"
    "默认 limit=512，实际页可能更小。nextOffset 是同一节点的续读位置，expected_document_digest 绑定 documentDigest。"
    "分页文本再次应用相同清洗，textFiltered 明示变化，value 长度可小于 limit；不能稳定呈现时明确报错，上游省略仍不可读取。"
)


class DocumentationNodeQuery(DocumentationDescribeQuery):
    document_pointer: str = Field(default="", max_length=1024, description="RFC 6901 JSON Pointer; empty means root.")
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=512, ge=1, le=512, description="最多子节点或整段清洗后的字符跨度；默认512，按预算缩小，页内再次清洗以textFiltered标记。")
    expected_document_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("document_pointer")
    @classmethod
    def valid_pointer(cls, value):
        if value and (not value.startswith("/") or re.search(r"~(?![01])", value)):
            raise ValueError("Invalid JSON Pointer")
        return value


def _clean_text(value: str) -> str:
    # A fixed non-workflow mapping key selects the same public text rules while
    # preventing JSON-looking string content from becoming a structured result.
    return json.loads(project_tool_result_for_model(json.dumps({"value": value}, ensure_ascii=False)))["value"]


def _stable_text(value: str) -> bool:
    try:
        value.encode("utf-8")
        return _clean_text(value) == value
    except UnicodeError:
        return False


def _size(project_id: str, response: dict) -> int:
    return len(json.dumps({"source": "launcher-assistant", "untrustedContent": True,
                           **response, "projectId": project_id}, ensure_ascii=False))


def _kind(value):
    if value is None: return "null"
    if type(value) is bool: return "boolean"
    if type(value) in (int, float): return "number"
    if isinstance(value, str): return "string"
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    raise ValueError("Not a JSON node")


def _child_pointer(parent: str, name: str) -> str:
    return parent + "/" + name.replace("~", "~0").replace("/", "~1")


def _node(document: dict, pointer: str):
    node = document
    for token in pointer.split("/")[1:] if pointer else ():
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and re.fullmatch(r"0|[1-9][0-9]*", key) and int(key) < len(node):
            node = node[int(key)]
        else:
            raise KeyError("Missing documentation node")
    return node


def _descriptor(pointer: str, value) -> dict:
    if len(pointer) > 1024:
        raise ValueError("DOCUMENTATION_NODE_TOO_LARGE")
    if not _stable_text(pointer):
        raise ValueError("DOCUMENTATION_POINTER_UNREPRESENTABLE")
    kind = _kind(value)
    row = {"pointer": pointer, "kind": kind}
    if kind in {"object", "array"}:
        row["childCount"] = len(value)
    elif kind == "string":
        cleaned = _clean_text(value)
        row["textFiltered"] = cleaned != value
        if len(cleaned) <= 128 and _stable_text(cleaned):
            row["value"] = cleaned
        else:
            row["childCount"] = len(cleaned)
    else:
        row["value"] = value
    return row


def _error(project_id: str, query: DocumentationNodeQuery, code: str, *, digest: str = "", upstream: bool = False) -> dict:
    # Do not echo unsafe/oversized names or upstream messages into an error.
    return {"ok": False, "status": "error", "viewVersion": 1, "source": "registered-openapi", "untrustedContent": True,
            "projectId": project_id if _stable_text(project_id) else "",
            "operationId": query.operation_id if _stable_text(query.operation_id) else "",
            "documentDigest": digest, "pointer": "", "nodeType": "unavailable", "offset": query.offset,
            "limit": 0, "total": 0, "nextOffset": None, "upstreamTruncated": upstream,
            "textFiltered": False, "code": code, "protocol": _PROTOCOL}


def project_documentation_node(document: dict, project_id: str, query: DocumentationNodeQuery) -> dict:
    """Page one returned JSON node; strings are cleaned before applying offsets."""
    upstream = document.get("truncated", False) if isinstance(document, dict) else False
    upstream = upstream if type(upstream) is bool else False
    if not isinstance(document, dict) or document.get("ok") is not True or document.get("status") != "ok":
        return _error(project_id, query, "DOCUMENTATION_READ_FAILED", upstream=upstream)
    operation = document.get("operation")
    if not isinstance(operation, dict) or operation.get("operationId") != query.operation_id:
        return _error(project_id, query, "DOCUMENTATION_IDENTITY_MISMATCH", upstream=upstream)
    try:
        canonical = json.dumps({key: value for key, value in document.items() if key != "observedAt"},
                               sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return _error(project_id, query, "DOCUMENTATION_INVALID", upstream=upstream)
    if query.expected_document_digest is not None and query.expected_document_digest != digest:
        return _error(project_id, query, "DOCUMENTATION_CHANGED", digest=digest, upstream=upstream)
    if not all(_stable_text(value) for value in (project_id, query.operation_id, query.document_pointer)):
        return _error(project_id, query, "DOCUMENTATION_POINTER_UNREPRESENTABLE", digest=digest, upstream=upstream)
    try:
        value = _node(document, query.document_pointer)
        kind = _kind(value)
    except (KeyError, ValueError):
        return _error(project_id, query, "DOCUMENTATION_NODE_UNAVAILABLE", digest=digest, upstream=upstream)
    response = {"ok": True, "status": "ok", "viewVersion": 1, "source": "registered-openapi", "untrustedContent": True,
                "projectId": project_id, "operationId": query.operation_id, "documentDigest": digest,
                "pointer": query.document_pointer, "nodeType": kind, "offset": query.offset,
                "limit": 0, "total": 0, "nextOffset": None, "upstreamTruncated": upstream,
                "textFiltered": False, "protocol": _PROTOCOL}
    if _size(project_id, response) > _TARGET_CHARS:
        return _error(project_id, query, "DOCUMENTATION_NODE_TOO_LARGE", digest=digest, upstream=upstream)

    if kind in {"object", "array"}:
        children = sorted(value.items()) if kind == "object" else list(enumerate(value))
        response.update(total=len(children), items=[])
        for key, child in children[query.offset:query.offset + query.limit]:
            try:
                descriptor = _descriptor(_child_pointer(query.document_pointer, str(key)), child)
            except ValueError as exc:
                if response["items"]: break
                code = str(exc) if str(exc) in {"DOCUMENTATION_NODE_TOO_LARGE", "DOCUMENTATION_POINTER_UNREPRESENTABLE"} else "DOCUMENTATION_INVALID"
                return _error(project_id, query, code, digest=digest, upstream=upstream)
            candidate = {**response, "items": [*response["items"], descriptor]}
            candidate["limit"] = len(candidate["items"])
            candidate["nextOffset"] = query.offset + candidate["limit"] if query.offset + candidate["limit"] < len(children) else None
            candidate["textFiltered"] = response["textFiltered"] or descriptor.get("textFiltered", False)
            if _size(project_id, candidate) > _TARGET_CHARS:
                if response["items"]: break
                return _error(project_id, query, "DOCUMENTATION_NODE_TOO_LARGE", digest=digest, upstream=upstream)
            response = candidate
        return response

    if kind == "string":
        # Never run text filtering separately on the original source chunks.
        cleaned = _clean_text(value)
        response.update(total=len(cleaned), textFiltered=cleaned != value)
        count = min(query.limit, max(0, len(cleaned) - query.offset))
        while True:
            span = cleaned[query.offset:query.offset + count]
            # Keep the ordinary page projection, including whitespace trimming.
            # Cursors consume the source span even if this stricter projection
            # removes its content; nothing removed before paging is recovered.
            text = _clean_text(span)
            candidate = {**response, "value": text, "limit": count,
                         "textFiltered": response["textFiltered"] or text != span,
                         "nextOffset": query.offset + count if query.offset + count < len(cleaned) else None}
            if _size(project_id, candidate) <= _TARGET_CHARS:
                if not _stable_text(text):
                    return _error(project_id, query, "DOCUMENTATION_TEXT_UNREPRESENTABLE", digest=digest, upstream=upstream)
                return candidate
            if count == 0: break
            count -= 1
        return _error(project_id, query, "DOCUMENTATION_NODE_TOO_LARGE", digest=digest, upstream=upstream)

    response["total"] = 1
    if query.offset == 0:
        response.update(value=value, limit=1)
    if _size(project_id, response) <= _TARGET_CHARS:
        return response
    return _error(project_id, query, "DOCUMENTATION_NODE_TOO_LARGE", digest=digest, upstream=upstream)
