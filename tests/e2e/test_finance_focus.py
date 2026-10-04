"""Finance start/recovery focus through real browser actions, with no model turn."""
from __future__ import annotations

import json
import re

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import post_json
from tests.e2e.helpers.instance_registry import fetch_json

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]

COMPOSER = 'textarea[aria-label="发送消息"]'
PERIOD = "2024Q4"


def _workspace(page, instance):
    from playwright.sync_api import expect

    assistant = post_json(instance.port, "/api/financial-assistants", {"displayName": "炒股智能体"})["assistant"]
    assert assistant["modelStatus"] == "configured_unverified", "Isolated assistant needs an existing configured model; no connectivity probe is performed"
    sid = create_session(instance.port, title="finance focus regression", agent_id=assistant["agentId"])
    page.goto(f"{instance.base_url}/finance?session={sid}", wait_until="domcontentloaded")
    expect(page.locator('div[data-agent-thread-id]').first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
    start = page.get_by_role("button", name="开始研究", exact=True)
    expect(start).to_be_enabled(timeout=30000)
    page.get_by_role("textbox", name="报告期", exact=True).fill(PERIOD)
    return sid, start


def _assert_unsubmitted(page, instance, sid, requests):
    from playwright.sync_api import expect

    expect(page.locator(COMPOSER).first).to_have_value(re.compile(re.escape(PERIOD)))
    expect(page.locator('[role="alert"]').first).to_contain_text("没有发出", timeout=15000)
    assert len(requests) == 1
    assert PERIOD in requests[0].request.post_data_json["content"]
    assert PERIOD not in json.dumps(fetch_json(instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)
    expect(page.locator('div[data-agent-thread-id]').first).to_have_attribute("data-agent-thread-message-count", "0")


def test_research_double_click_submits_once_and_recovers_focus(page, e2e_instance):
    from playwright.sync_api import expect

    sid, start = _workspace(page, e2e_instance)
    requests = []

    def hold(route):
        requests.append(route)

    page.route(f"**/api/sessions/{sid}/messages", hold)
    try:
        start.dblclick()
        expect(page.locator(COMPOSER).first).to_be_visible()
        page.wait_for_timeout(500)
        assert len(requests) == 1
        requests[0].abort("internetdisconnected")
        _assert_unsubmitted(page, e2e_instance, sid, requests)
        expect(page.locator(COMPOSER).first).to_be_enabled()
        expect(page.locator(COMPOSER).first).to_be_focused(timeout=10000)
        page.wait_for_timeout(1000)
        assert len(requests) == 1
    finally:
        for route in requests:
            try:
                route.abort("internetdisconnected")
            except Exception:
                pass
        page.unroute(f"**/api/sessions/{sid}/messages", hold)


def test_failed_research_does_not_steal_newer_inspector_focus(page, e2e_instance):
    from playwright.sync_api import expect

    sid, start = _workspace(page, e2e_instance)
    requests = []

    def hold(route):
        requests.append(route)

    page.route(f"**/api/sessions/{sid}/messages", hold)
    try:
        start.click()
        expect(page.locator(COMPOSER).first).to_be_visible()
        page.wait_for_timeout(500)
        assert len(requests) == 1
        sources = page.get_by_role("tab", name="引用与资料", exact=True)
        sources.click()
        expect(sources).to_be_focused()
        requests[0].abort("internetdisconnected")
        _assert_unsubmitted(page, e2e_instance, sid, requests)
        page.wait_for_timeout(1000)
        expect(sources).to_be_focused()
    finally:
        for route in requests:
            try:
                route.abort("internetdisconnected")
            except Exception:
                pass
        page.unroute(f"**/api/sessions/{sid}/messages", hold)
