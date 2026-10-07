"""Conflict retries, manual cleanup recovery and independent browser tabs."""
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
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_cold_create_journeys import _create_settled, _fetch_route
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401
from tests.e2e.test_session_reload_recovery_journeys import (
    _create_event, _hold_creates, _session_exists, _start_create,
)

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


def _evidence(root):
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    target = common / "task-evidence" / "session-conflict-recovery-round19"
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
    }, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


@pytest.fixture(autouse=True)
def bounded_snapshot(page, e2e_instance):
    yield
    target = _evidence(e2e_instance.project_root) / f"browser-state-{uuid.uuid4().hex[:8]}"
    target.with_suffix(".json").write_text(json.dumps({
        "url": page.url, "tabs": page.get_by_role("tab").all_text_contents(),
        "threadId": page.locator(THREAD).first.get_attribute("data-agent-thread-id")
        if page.locator(THREAD).count() else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    page.screenshot(path=str(target.with_suffix(".png")))


@pytest.mark.parametrize("status", [409, 410])
def test_definitive_rejection_retry_preserves_draft_without_orphan_shell(page, e2e_instance, status):
    from playwright.sync_api import expect

    source = create_session(e2e_instance.port, title=f"冲突重试 {uuid.uuid4().hex[:8]}")
    _ready_composer(page, e2e_instance, source)
    pending = []
    hold = _hold_creates(page, pending)
    draft = f"明确拒绝{status}后仍需保留的草稿"
    try:
        old_temp = _start_create(page, pending)
        page.locator(COMPOSER).first.press_sequentially(draft, delay=2)
        rejected = pending.pop()
        old_key = rejected.request.header_value("Idempotency-Key")
        with page.expect_request(lambda request: _create_event(request, "failed")):
            rejected.fulfill(status=status, content_type="application/json", body='{"detail":"受控创建拒绝"}')
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        temp = _start_create(page, pending)
        retry = pending.pop()
        assert retry.request.header_value("Idempotency-Key") != old_key
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        response = _fetch_route(retry)
        assert response.ok
        real_id = response.json()["id"]
        with page.expect_request(_create_settled):
            retry.fulfill(response=response)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_id)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        expect(page.locator(f'[id="agent-session-tab-session-{old_temp}"]')).to_have_count(0)
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_id, timeout=15000)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        assert temp not in page.url
        _assert_no_turns(e2e_instance, [source, real_id], [draft])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions", hold)


def test_persistent_cleanup_failure_allows_real_manual_removal(page, e2e_instance):
    from playwright.sync_api import expect

    source = create_session(e2e_instance.port, title=f"再次移除 {uuid.uuid4().hex[:8]}")
    _ready_composer(page, e2e_instance, source)
    pending, failures = [], []
    real_id = ""
    hold = _hold_creates(page, pending)

    def reject_cleanup(route):
        if real_id and route.request.method == "DELETE" and urlsplit(route.request.url).path == f"/api/sessions/{real_id}":
            failures.append(real_id)
            route.fulfill(status=503, content_type="application/json", body='{"detail":"受控持续清理失败"}')
        else:
            route.fallback()

    page.route("**/api/sessions/**", reject_cleanup)
    try:
        temp = _start_create(page, pending)
        container = page.get_by_role("tab", selected=True).locator("..")
        container.get_by_role("button", name=re.compile("^移除会话记录")).click()
        with page.expect_request(lambda request: (request.post_data_json or {}).get("eventCode") ==
                                 "browser.user_action.session_delete_succeeded" if request.method == "POST"
                                 and request.url.endswith("/api/runtime/browser-telemetry") else False):
            container.get_by_role("button", name=re.compile("^再次点击确认移除会话记录")).click()
        route = pending.pop()
        response = _fetch_route(route)
        assert response.ok
        real_id = response.json()["id"]
        assert _session_exists(e2e_instance, real_id)
        with page.expect_request(lambda request: (request.post_data_json or {}).get("eventCode") ==
                                 "browser.user_action.session_discard_delete_failed" if request.method == "POST"
                                 and request.url.endswith("/api/runtime/browser-telemetry") else False):
            route.fulfill(response=response)
        assert failures == [real_id] * 3
        assert _session_exists(e2e_instance, real_id)
        expect(page.get_by_text("会话清理未完成，请再次移除会话记录。", exact=True)).to_be_visible()
        expect(page.locator(f'[id="agent-session-tab-session-{temp}"]')).to_have_count(0)
        page.unroute("**/api/sessions/**", reject_cleanup)
        tab = page.locator(f'[id="agent-session-tab-session-{real_id}"]')
        expect(tab).to_be_visible()
        container = tab.locator("..")
        container.get_by_role("button", name=re.compile("^移除会话记录")).click()
        with page.expect_request(lambda request: (request.post_data_json or {}).get("eventCode") ==
                                 "browser.user_action.session_delete_succeeded" if request.method == "POST"
                                 and request.url.endswith("/api/runtime/browser-telemetry") else False):
            container.get_by_role("button", name=re.compile("^再次点击确认移除会话记录")).click()
        assert not _session_exists(e2e_instance, real_id)
        expect(tab).to_have_count(0)
        expect(page.get_by_text("会话清理未完成，请再次移除会话记录。", exact=True)).to_have_count(0)
        _assert_no_turns(e2e_instance, [source], [])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions/**", reject_cleanup)
        page.unroute("**/api/sessions", hold)


def test_two_browser_tabs_recover_independent_creates_and_drafts(page, e2e_instance):
    from playwright.sync_api import expect

    source = create_session(e2e_instance.port, title=f"双浏览器标签 {uuid.uuid4().hex[:8]}")
    _ready_composer(page, e2e_instance, source)
    other = page.context.new_page()
    # A second tab shares localStorage, but owns its recovery key/sessionStorage.
    captured = []

    def guard(route):
        if route.request.method == "POST" and any(urlsplit(route.request.url).path.endswith(end)
                                                  for end in ("/messages", "/messages/edit-resubmit", "/guidance")):
            captured.append(route.request.url)
            route.abort()
        else:
            route.fallback()

    other.route("**/api/sessions/**", guard)
    _ready_composer(other, e2e_instance, source)
    pages, pending, holds = [page, other], [[], []], []
    temps, keys, real_ids = [], [], []
    drafts = ["浏览器标签甲独立草稿", "浏览器标签乙独立草稿"]
    try:
        for index, current in enumerate(pages):
            holds.append(_hold_creates(current, pending[index]))
            temps.append(_start_create(current, pending[index]))
            current.locator(COMPOSER).first.press_sequentially(drafts[index], delay=2)
        for index, current in enumerate(pages):
            route = pending[index].pop()
            keys.append(route.request.header_value("Idempotency-Key"))
            response = _fetch_route(route)
            assert response.ok
            real_ids.append(response.json()["id"])
            with current.expect_request(lambda request: _create_event(request, "failed")):
                route.abort("failed")
        assert len(set(keys)) == len(set(temps)) == len(set(real_ids)) == 2
        before = {row["id"] for row in fetch_json(e2e_instance.port, "/api/sessions")}
        for index, current in enumerate(pages):
            current.reload(wait_until="domcontentloaded")
            expect(current.locator(THREAD).first).to_have_attribute("data-agent-thread-id", temps[index], timeout=15000)
            expect(current.locator(COMPOSER).first).to_have_value(drafts[index])
            assert _start_create(current, pending[index]) == temps[index]
            route = pending[index].pop()
            assert route.request.header_value("Idempotency-Key") == keys[index]
            response = _fetch_route(route)
            assert response.ok and response.json()["id"] == real_ids[index]
            with current.expect_request(_create_settled):
                route.fulfill(response=response)
            expect(current.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_ids[index])
            expect(current.locator(COMPOSER).first).to_have_value(drafts[index])
        # Reload both again after both writes: catches stale whole-store overwrites.
        for index, current in enumerate(pages):
            current.reload(wait_until="domcontentloaded")
            expect(current.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_ids[index], timeout=15000)
            expect(current.locator(COMPOSER).first).to_have_value(drafts[index])
        assert {row["id"] for row in fetch_json(e2e_instance.port, "/api/sessions")} == before
        _assert_no_turns(e2e_instance, [source, *real_ids], drafts)
        assert captured == []
    finally:
        for index, current in enumerate(pages):
            for route in pending[index]:
                route.abort()
            if index < len(holds):
                current.unroute("**/api/sessions", holds[index])
        other.close()
