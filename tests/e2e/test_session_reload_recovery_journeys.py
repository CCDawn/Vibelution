"""Create recovery at real server/browser acknowledgement boundaries; no model turns."""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json, InstanceRegistryError
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_cold_create_journeys import _create_settled, _fetch_route
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


def _evidence(root):
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    target = common / "task-evidence" / "session-reload-recovery-round18"
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture(scope="session", autouse=True)
def runtime_identity(e2e_instance):
    root = e2e_instance.project_root
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    backend = e2e_instance.health.get("backendCodeFingerprint") or {}
    serving = e2e_instance.health.get("serving") or {}
    assert backend.get("head") == head and backend.get("dirty") is False
    frontend_head = (serving.get("frontend") or {}).get("builtFromCommit")
    assert frontend_head
    trees = [subprocess.check_output(["git", "rev-parse", f"{commit}:web"], cwd=root, text=True).strip()
             for commit in (head, frontend_head)]
    assert trees[0] == trees[1]
    (_evidence(root) / f"runtime-proof-{head[:12]}.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend, "serving": serving,
        "testedWebTree": trees[0], "frontendSourceTree": trees[1],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(autouse=True)
def bounded_snapshot(page, e2e_instance):
    yield
    # Small bounded state, no headers, drafts or transcript content.
    target = _evidence(e2e_instance.project_root) / f"browser-state-{uuid.uuid4().hex[:8]}"
    target.with_suffix(".json").write_text(json.dumps({
        "url": page.url, "tabs": page.get_by_role("tab").all_text_contents(),
        "threadId": page.locator(THREAD).first.get_attribute("data-agent-thread-id")
        if page.locator(THREAD).count() else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    page.screenshot(path=str(target.with_suffix(".png")))


def _create_event(request, outcome):
    return (request.method == "POST" and request.url.endswith("/api/runtime/browser-telemetry")
            and (request.post_data_json or {}).get("eventCode") == f"browser.user_action.session_create_{outcome}")


def _start_create(page, pending):
    from playwright.sync_api import expect

    with page.expect_request(lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/sessions"):
        page.get_by_role("button", name="在当前 Agent 下新建会话", exact=True).click()
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", re.compile("temp-session-"))
    assert len(pending) == 1
    return page.locator(THREAD).first.get_attribute("data-agent-thread-id")


def _hold_creates(page, pending):
    def hold(route):
        if route.request.method == "POST":
            pending.append(route)
        else:
            route.continue_()
    page.route("**/api/sessions", hold)
    return hold


def test_lost_response_then_reload_restores_create_intent_and_draft(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title=f"刷新恢复来源 {uuid.uuid4().hex[:8]}")
    _ready_composer(page, e2e_instance, sid)
    pending = []
    hold = _hold_creates(page, pending)
    draft = "刷新前输入的创建草稿"
    try:
        temp_id = _start_create(page, pending)
        page.locator(COMPOSER).first.press_sequentially(draft, delay=2)
        route = pending.pop()
        key = route.request.header_value("Idempotency-Key")
        assert key
        response = _fetch_route(route)
        assert response.ok
        real_id = response.json()["id"]
        assert fetch_json(e2e_instance.port, f"/api/sessions/{real_id}")["id"] == real_id
        before = {row["id"] for row in fetch_json(e2e_instance.port, "/api/sessions")}
        with page.expect_request(lambda request: _create_event(request, "failed")):
            route.abort("failed")
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        # A genuine document reload loses all module maps and React refs.
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", temp_id, timeout=15000)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        assert _start_create(page, pending) == temp_id
        retry = pending.pop()
        assert retry.request.header_value("Idempotency-Key") == key
        retried = _fetch_route(retry)
        assert retried.ok and retried.json()["id"] == real_id
        with page.expect_request(_create_settled):
            retry.fulfill(response=retried)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_id)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        assert {row["id"] for row in fetch_json(e2e_instance.port, "/api/sessions")} == before
        _assert_no_turns(e2e_instance, [sid, real_id], [draft])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions", hold)


def test_same_agent_later_tab_selection_survives_delayed_create_ack(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    source = create_session(e2e_instance.port, title=f"同Agent来源 {suffix}")
    aid = fetch_json(e2e_instance.port, f"/api/sessions/{source}")["agentId"]
    _ready_composer(page, e2e_instance, source)
    # Arrange both tabs through real user creation, independently of directory
    # pagination/freshness; neither title nor server list is a tab identity.
    tabs = []
    for _ in range(2):
        with page.expect_request(_create_settled), page.expect_response(
            lambda response: response.request.method == "POST" and urlsplit(response.url).path == "/api/sessions"
        ) as created_response:
            page.get_by_role("button", name="在当前 Agent 下新建会话", exact=True).click()
        tab_id = created_response.value.json()["id"]
        assert fetch_json(e2e_instance.port, f"/api/sessions/{tab_id}")["agentId"] == aid
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", tab_id)
        tabs.append(tab_id)
    a, b = tabs
    page.locator(f'[id="agent-session-tab-session-{a}"]').click()
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", a)
    pending = []
    hold = _hold_creates(page, pending)
    try:
        _start_create(page, pending)
        page.locator(COMPOSER).first.press_sequentially("新建中的草稿", delay=2)
        page.locator(f'[id="agent-session-tab-session-{b}"]').click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", b)
        page.locator(COMPOSER).first.press_sequentially("后选会话草稿", delay=2)
        route = pending.pop()
        response = _fetch_route(route)
        assert response.ok
        created = response.json()
        with page.expect_request(_create_settled):
            route.fulfill(response=response)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", b)
        expect(page.locator(COMPOSER).first).to_have_value("后选会话草稿")
        expect(page.locator(f'[id="agent-session-tab-session-{b}"]')).to_have_attribute("aria-selected", "true")
        last = page.evaluate("JSON.parse(localStorage.getItem('vibelution.chat-agent-last-session.v1:vibelution:operator') || '{}')")
        assert last[aid] == b
        page.locator(f'[id="agent-session-tab-session-{created["id"]}"]').click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", created["id"])
        expect(page.locator(COMPOSER).first).to_have_value("新建中的草稿")
        _assert_no_turns(e2e_instance, [a, b, created["id"]], ["新建中的草稿", "后选会话草稿"])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions", hold)


def test_closed_create_retries_transient_compensating_delete_failure(page, e2e_instance):
    from playwright.sync_api import expect

    a = create_session(e2e_instance.port, title=f"关闭清理恢复 {uuid.uuid4().hex[:8]}")
    _ready_composer(page, e2e_instance, a)
    pending, delete_failures = [], []
    real_id = ""
    hold = _hold_creates(page, pending)

    def fail_first_cleanup(route):
        if real_id and route.request.method == "DELETE" and urlsplit(route.request.url).path == f"/api/sessions/{real_id}" and not delete_failures:
            delete_failures.append(real_id)
            route.fulfill(status=503, content_type="application/json", body='{"detail":"受控清理暂时失败"}')
        else:
            route.fallback()

    page.route("**/api/sessions/**", fail_first_cleanup)
    try:
        temp_id = _start_create(page, pending)
        container = page.get_by_role("tab", selected=True).locator("..")
        container.get_by_role("button", name=re.compile("^移除会话记录")).click()
        with page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/api/runtime/browser-telemetry")
                                 and (request.post_data_json or {}).get("eventCode") == "browser.user_action.session_delete_succeeded"):
            container.get_by_role("button", name=re.compile("^再次点击确认移除会话记录")).click()
        route = pending.pop()
        response = _fetch_route(route)
        assert response.ok
        real_id = response.json()["id"]
        assert fetch_json(e2e_instance.port, f"/api/sessions/{real_id}")["id"] == real_id
        with page.expect_request(_create_settled):
            route.fulfill(response=response)
        for _ in range(50):
            exists = _session_exists(e2e_instance, real_id)
            if delete_failures and not exists:
                break
            page.wait_for_timeout(100)
        assert delete_failures == [real_id], "The transient cleanup failure must actually occur"
        assert not exists, "Closed create must recover from transient cleanup failure"
        page.reload(wait_until="domcontentloaded")
        _ready_composer(page, e2e_instance, a)
        expect(page.get_by_role("tab")).to_have_count(1, timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", a)
        assert temp_id not in page.url
        _assert_no_turns(e2e_instance, [a], [])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions/**", fail_first_cleanup)
        page.unroute("**/api/sessions", hold)


def _session_exists(instance, session_id):
    try:
        fetch_json(instance.port, f"/api/sessions/{session_id}")
        return True
    except InstanceRegistryError as error:
        if "HTTP 404" in str(error):
            return False
        raise
