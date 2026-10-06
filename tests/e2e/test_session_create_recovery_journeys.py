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
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns, _switch
from tests.e2e.test_session_cold_create_journeys import _create_settled, _fetch_route
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


def _evidence(root):
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    target = common / "task-evidence" / "session-create-recovery-round17"
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


def test_lost_create_response_retry_reuses_server_session_and_draft(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title=f"丢响应来源 {uuid.uuid4().hex[:8]}")
    _ready_composer(page, e2e_instance, sid)
    pending = []
    hold = _hold_creates(page, pending)
    draft = "响应丢失后继续保留的未发送内容"
    try:
        temp_id = _start_create(page, pending)
        page.locator(COMPOSER).first.press_sequentially(draft, delay=2)
        route = pending.pop()
        first_key = route.request.header_value("Idempotency-Key")
        assert first_key
        response = _fetch_route(route)
        assert response.ok
        real_id = response.json()["id"]
        # Prove the POST was committed before discarding its response.
        assert fetch_json(e2e_instance.port, f"/api/sessions/{real_id}")["id"] == real_id
        before = {row["id"] for row in fetch_json(e2e_instance.port, "/api/sessions")}
        with page.expect_request(lambda request: _create_event(request, "failed")):
            route.abort("failed")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", temp_id)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        assert _start_create(page, pending) == temp_id
        retry = pending.pop()
        assert retry.request.header_value("Idempotency-Key") == first_key
        retried = _fetch_route(retry)
        assert retried.ok and retried.json()["id"] == real_id
        with page.expect_request(_create_settled):
            retry.fulfill(response=retried)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_id)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        assert {row["id"] for row in fetch_json(e2e_instance.port, "/api/sessions")} == before
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(COMPOSER).first).to_have_value(draft, timeout=30000)
        _assert_no_turns(e2e_instance, [sid, real_id], [draft])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions", hold)


@pytest.mark.parametrize("ack", ["success", "failure"])
def test_closed_temp_does_not_restore_session_or_error_after_late_ack(page, e2e_instance, ack):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    title_a, title_b = f"关闭来源 {suffix}", f"关闭后目标 {suffix}"
    a, b = [create_session(e2e_instance.port, title=title) for title in (title_a, title_b)]
    _ready_composer(page, e2e_instance, a)
    pending = []
    hold = _hold_creates(page, pending)
    try:
        temp_id = _start_create(page, pending)
        container = page.get_by_role("tab", selected=True).locator("..")
        container.get_by_role("button", name=re.compile("^移除会话记录")).click()
        with page.expect_request(lambda request: request.method == "POST"
                                 and request.url.endswith("/api/runtime/browser-telemetry")
                                 and (request.post_data_json or {}).get("eventCode") == "browser.user_action.session_delete_succeeded"):
            container.get_by_role("button", name=re.compile("^再次点击确认移除会话记录")).click()
        expect(page).not_to_have_url(re.compile(re.escape(temp_id)))
        _switch(page, title_b, b).press_sequentially("关闭后的目标草稿", delay=2)
        route = pending.pop()
        if ack == "success":
            response = _fetch_route(route)
            assert response.ok
            real_id = response.json()["id"]
            with page.expect_request(_create_settled):
                route.fulfill(response=response)
            # Await the actual compensating DELETE, not only optimistic tab removal.
            for _ in range(40):
                ids = {row["id"] for row in fetch_json(e2e_instance.port, "/api/sessions")}
                if real_id not in ids:
                    break
                page.wait_for_timeout(100)
            assert real_id not in ids
        else:
            with page.expect_request(lambda request: _create_event(request, "failed")):
                route.fulfill(status=503, content_type="application/json", body='{"detail":"受控创建失败"}')
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", b)
        expect(page.locator(COMPOSER).first).to_have_value("关闭后的目标草稿")
        expect(page.get_by_role("tab", selected=True)).to_contain_text(title_b)
        expect(page.get_by_text("受控创建失败", exact=False)).to_have_count(0)
        last = page.evaluate("JSON.parse(localStorage.getItem('vibelution.chat-agent-last-session.v1:vibelution:operator') || '{}')")
        assert temp_id not in last.values()
        page.get_by_role("button").filter(has=page.get_by_text(title_a, exact=True)).first.click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", a)
        expect(page.get_by_role("tab")).to_have_count(1)
        _assert_no_turns(e2e_instance, [a, b], ["关闭后的目标草稿"])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions", hold)


def test_catalog_failure_recovery_preserves_current_detail_tab_and_draft(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"目录恢复 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    failures = []
    broken = True

    def catalog(route):
        path = urlsplit(route.request.url).path
        if broken and route.request.method == "GET" and path in {"/api/sessions/bootstrap", "/api/sessions/query", "/api/agents"}:
            failures.append(path)
            route.fulfill(status=503, content_type="application/json", body='{"detail":"受控目录失败"}')
        else:
            route.fallback()

    page.route("**/api/**", catalog)
    try:
        composer = _ready_composer(page, e2e_instance, sid)
        assert failures
        expect(page.get_by_role("tab", selected=True)).to_contain_text(title)
        composer.press_sequentially("目录恢复期间保留草稿", delay=2)
        broken = False
        # Reconnect is the user's recovery action and triggers stale queries.
        page.context.set_offline(True)
        page.wait_for_timeout(100)
        with page.expect_response(lambda response: urlsplit(response.url).path in {"/api/sessions/bootstrap", "/api/sessions/query", "/api/agents"} and response.ok):
            page.context.set_offline(False)
        expect(page.get_by_role("tab", selected=True)).to_contain_text(title)
        expect(composer).to_have_value("目录恢复期间保留草稿")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid)
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(COMPOSER).first).to_have_value("目录恢复期间保留草稿", timeout=30000)
        _assert_no_turns(e2e_instance, [sid], ["目录恢复期间保留草稿"])
    finally:
        page.context.set_offline(False)
        page.unroute("**/api/**", catalog)
