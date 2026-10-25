"""Exact delegated spans; native Journal is the only stored text authority."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .dispatch import DispatchError


class TaskSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_after: str = Field(default="", max_length=256)
    end_before: str = Field(default="", max_length=256)


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal[1] = 1
    agentId: str = Field(min_length=1, max_length=160)
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)
    eventId: str = Field(min_length=1, max_length=160)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    contentHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    spanHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selectorHash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _invalid(code="TASK_SOURCE_INVALID"):
    raise DispatchError("无法确认原生用户消息中的任务原文；请使用 task_source 的唯一短锚点，不要改写任务。", code=code)


def _unique(content: str, anchor: str) -> int:
    position = content.find(anchor)
    if position < 0 or content.find(anchor, position + 1) >= 0:
        _invalid()
    return position


def resolve_task(runtime: dict, *, task: str | None = None, task_source: dict | None = None,
                 source_ref: dict | None = None) -> tuple[str, dict]:
    """Resolve a fresh span or verify a frozen span without persisting its text."""
    if (task is None) == (task_source is None):
        _invalid()
    if task is not None and (not isinstance(task, str) or not task.strip() or len(task) > 64000):
        _invalid()
    try:
        selector = TaskSelector.model_validate(task_source).model_dump() if task_source is not None else None
        frozen = SourceReference.model_validate(source_ref).model_dump() if source_ref is not None else None
    except ValidationError:
        _invalid()
    selector_hash = _hash(json.dumps({"task_source": selector} if selector is not None else {"task": task},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    if frozen is not None and frozen["selectorHash"] != selector_hash:
        _invalid("DISPATCH_CONFLICT")
    from . import native
    try:
        source = native.read_task_source(runtime, source_ref=frozen)
    except (native.AssistantSessionError, OSError, ValueError, RuntimeError):
        _invalid("TASK_SOURCE_UNAVAILABLE")
    content = source.get("content")
    if not isinstance(content, str) or not content:
        _invalid()
    if not isinstance(runtime, dict) or any(source.get(key) != runtime.get(key) for key in ("agentId", "sessionId")):
        _invalid()
    if frozen is not None:
        if (any(source.get(key) != frozen[key] for key in ("agentId", "sessionId", "turnId", "eventId"))
            or frozen["contentHash"] != _hash(content) or not 0 <= frozen["start"] < frozen["end"] <= len(content)):
            _invalid("DISPATCH_CONFLICT")
        span = content[frozen["start"]:frozen["end"]]
        if _hash(span) != frozen["spanHash"] or not span or len(span) > 64000 or span != span.strip():
            _invalid("DISPATCH_CONFLICT")
        return span, frozen
    if source.get("turnId") != runtime.get("turnId"):
        _invalid()
    if selector is not None:
        start = _unique(content, selector["start_after"]) + len(selector["start_after"]) if selector["start_after"] else 0
        end = _unique(content, selector["end_before"]) if selector["end_before"] else len(content)
    else:
        start = content.find(task)
        if start < 0:
            _invalid("TASK_SOURCE_MISMATCH")
        end = start + len(task)
    if end <= start:
        _invalid()
    raw = content[start:end]
    span = raw.strip()
    if not span or len(span) > 64000:
        _invalid()
    start += len(raw) - len(raw.lstrip())
    end = start + len(span)
    try:
        reference = SourceReference.model_validate({"schemaVersion": 1,
            **{key: source.get(key) for key in ("agentId", "sessionId", "turnId", "eventId")},
            "start": start, "end": end, "contentHash": _hash(content), "spanHash": _hash(span),
            "selectorHash": selector_hash}).model_dump()
    except ValidationError:
        _invalid()
    return span, reference
