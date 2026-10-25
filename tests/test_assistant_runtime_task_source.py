"""Delegated text comes only from exact native user-event spans."""
from __future__ import annotations

import copy
import json

import pytest

from core.assistant_runtime.dispatch import DispatchError


MARKER = "E3_RECEIPT_3E159D2DFC294ED1"
RUNTIME = {"agentId": "assistant-a", "sessionId": "assistant-session", "turnId": "turn-a"}


@pytest.fixture
def source(monkeypatch):
    from core.assistant_runtime import native
    value = {**RUNTIME, "eventId": "user-a", "content": "请派遣：\n只回复 " + MARKER + "\n任务结束。"}
    monkeypatch.setattr(native, "read_task_source", lambda runtime, **kwargs: copy.deepcopy(value), raising=False)
    return value


def resolve(**kwargs):
    from core.assistant_runtime.task_source import resolve_task
    return resolve_task(RUNTIME, **kwargs)


def test_one_character_marker_rewrite_is_rejected(source):
    with pytest.raises(DispatchError, match="task_source"):
        resolve(task="只回复 " + MARKER[:-1] + "4")


def test_native_anchor_selection_preserves_exact_marker_and_stores_only_reference(source):
    task, reference = resolve(task_source={"start_after": "请派遣：", "end_before": "任务结束。"})
    assert task == "只回复 " + MARKER
    encoded = json.dumps(reference, ensure_ascii=False)
    assert MARKER not in encoded and "请派遣" not in encoded and "只回复" not in encoded
    assert reference["agentId"] == RUNTIME["agentId"] and reference["eventId"] == "user-a"


@pytest.mark.parametrize("content,selector", [
    ("a<start>x<start>z<end>", {"start_after": "<start>", "end_before": "<end>"}),
    ("aaab", {"start_after": "aa"}),
    ("begin x", {"start_after": "missing"}),
    ("end then start", {"start_after": "start", "end_before": "end"}),
    ("begin  end", {"start_after": "begin", "end_before": "end"}),
    ("x" * 64001, {}),
], ids=["duplicate", "overlap", "missing", "reversed", "empty", "oversize"])
def test_missing_ambiguous_reversed_empty_or_oversize_source_denied(source, content, selector):
    source["content"] = content
    with pytest.raises(DispatchError):
        resolve(task_source=selector)


def test_unicode_offsets_and_original_reference_survive_new_turn(source):
    source["content"] = "🧭开始：\n组合字符 e\u0301 和汉字 " + MARKER + "\n结束🧭"
    selector = {"start_after": "开始：", "end_before": "结束🧭"}
    task, reference = resolve(task_source=selector)
    original = copy.deepcopy(source)
    source.update(turnId="turn-new", eventId="user-new", content="新的请求")
    # Native recovery is pinned to the original Journal event, never current text.
    from core.assistant_runtime import native
    from unittest.mock import patch
    with patch.object(native, "read_task_source", return_value=original) as read:
        from core.assistant_runtime.task_source import resolve_task
        recovered, same = resolve_task({**RUNTIME, "turnId": "turn-new"}, task_source=selector, source_ref=reference)
    assert recovered == task and same == reference
    assert read.call_args.kwargs["source_ref"] == reference


@pytest.mark.parametrize("change", ["selector", "hash", "offset", "identity", "extra"])
def test_changed_selector_or_corrupt_reference_never_falls_back(source, change):
    _, reference = resolve(task_source={})
    selector = {}
    if change == "selector":
        selector = {"start_after": "请派遣："}
    elif change == "hash":
        reference["contentHash"] = "0" * 64
    elif change == "offset":
        reference["end"] += 1000
    elif change == "identity":
        reference["agentId"] = "other"
    else:
        reference["content"] = "must never be accepted"
    with pytest.raises(DispatchError):
        resolve(task_source=selector, source_ref=reference)
