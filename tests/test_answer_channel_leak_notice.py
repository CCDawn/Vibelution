# -*- coding: utf-8 -*-
"""Persist-side user-visible notice for answer-channel leak retries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.web.services.session import signals_format


class _StubService:
    def __init__(self, lang: str = "zh") -> None:
        self._lang = lang

    def get_web_language(self) -> str:
        return self._lang

    def text_for(self, lang, *, zh: str, en: str) -> str:
        return zh if (lang or self._lang) == "zh" else en


@pytest.fixture()
def stub_service(monkeypatch):
    stub = _StubService()
    monkeypatch.setattr(signals_format, "_service", lambda: stub)
    return stub


def _result(**leak):
    return {"answer_channel_leak": leak}


def test_notice_appended_when_retry_was_used(stub_service):
    text = signals_format._append_answer_channel_leak_notice(
        "重试后的干净回答。",
        result=_result(leakRetried=True, leakRecovered=True, leakMarkers=[]),
        lang="zh",
    )
    assert text.startswith("重试后的干净回答。")
    assert "检测到模型把内部格式泄漏为答复，已自动重试一次" in text


def test_notice_appended_for_released_second_leak(stub_service):
    text = signals_format._append_answer_channel_leak_notice(
        "<analysis>仍未恢复的泄漏</analysis>",
        result=_result(leakRetried=True, leakRecovered=False, leakMarkers=["analysis_tag"]),
        lang="zh",
    )
    assert "<analysis>" in text
    assert "已自动重试一次" in text


def test_no_notice_for_pure_stage1_recovery(stub_service):
    text = signals_format._append_answer_channel_leak_notice(
        "正式回答。",
        result=_result(leakRetried=False, leakRecovered=True, leakMarkers=["analysis_tag"]),
        lang="zh",
    )
    assert text == "正式回答。"


def test_no_notice_without_leak_metadata(stub_service):
    text = signals_format._append_answer_channel_leak_notice("正常回答。", result={}, lang="zh")
    assert text == "正常回答。"
    assert signals_format._append_answer_channel_leak_notice("", result=None, lang="zh") == ""


def test_notice_idempotent_and_english(stub_service):
    result = _result(leakRetried=True, leakRecovered=False, leakMarkers=["summary_tag"])
    once = signals_format._append_answer_channel_leak_notice("回答。", result=result, lang="en")
    assert "one automatic retry was used" in once
    twice = signals_format._append_answer_channel_leak_notice(once, result=result, lang="en")
    assert twice == once
