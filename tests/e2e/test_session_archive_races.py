"""Archive retries, repeated actions and late responses without model turns."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import post_json
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns, _switch
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


@pytest.fixture(scope="session", autouse=True)
def runtime_identity(e2e_instance):
    root = e2e_instance.project_root
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    backend = e2e_instance.health.get("backendCodeFingerprint") or {}
    serving = e2e_instance.health.get("serving") or {}
    assert backend.get("head") == head and backend.get("dirty") is False
    assert (serving.get("frontend") or {}).get("builtFromCommit") == head
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    evidence = common / "task-evidence" / "archive-races-round12-oct07"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "runtime-proof.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend, "serving": serving,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _show_archived(page):
    toggle = page.get_by_role("button", name="显示已归档会话", exact=True)
    if toggle.is_visible():
        toggle.click()


def _open_action(page, title, action):
    from playwright.sync_api import expect

    row = page.get_by_role("tab").filter(has_text=title)
    expect(row).to_be_visible(timeout=15000)
    row.click(button="right")
    item = page.get_by_role("menuitem", name=action, exact=True)
    expect(item).to_be_enabled(timeout=15000)
    return item


def _command(page, sid, title, archive):
    endpoint = "archive" if archive else "unarchive"
    with page.expect_response(lambda response: response.url.endswith(f"/api/sessions/{sid}/{endpoint}")) as saved:
        _open_action(page, title, "归档会话" if archive else "取消归档").click()
    assert saved.value.ok


def _arrange_archived(page, instance):
    from playwright.sync_api import expect

    title = f"归档竞态 {uuid.uuid4().hex[:8]}"
    sid = create_session(instance.port, title=title)
    draft = f"保留未提交草稿 {uuid.uuid4().hex[:8]}"
    _ready_composer(page, instance, sid).press_sequentially(draft, delay=2)
    post_json(instance.port, f"/api/sessions/{sid}/archive")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(COMPOSER).first).to_be_disabled(timeout=15000)
    expect(page.locator(COMPOSER).first).to_have_value(draft)
    _show_archived(page)
    return title, sid, draft


def test_unarchive_retry_clears_previous_error_and_preserves_draft(page, e2e_instance):
    from playwright.sync_api import expect

    title, sid, draft = _arrange_archived(page, e2e_instance)
    marker = "archive retry controlled failure"

    def fail_command(route):
        route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": marker}))

    page.route(f"**/api/sessions/{sid}/unarchive", fail_command)
    try:
        _open_action(page, title, "取消归档").click()
        error = page.get_by_text(marker, exact=False).first
        expect(error).to_be_visible(timeout=15000)
        expect(page.locator(COMPOSER).first).to_be_disabled()
        # Retry the same menu action against the real backend after the fault.
        page.unroute(f"**/api/sessions/{sid}/unarchive", fail_command)
        _command(page, sid, title, False)
        expect(page.locator(COMPOSER).first).to_be_enabled(timeout=15000)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        expect(error).not_to_be_visible(timeout=15000)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["readOnly"] is False
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        page.unroute(f"**/api/sessions/{sid}/unarchive", fail_command)
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")


def test_repeated_archive_unarchive_keeps_draft_and_correct_input_state(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"连续归档切换 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    draft = "连续操作期间未提交的文字"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    _show_archived(page)
    try:
        for archive in (True, False, True, False):
            _command(page, sid, title, archive)
            if archive:
                expect(composer).to_be_disabled(timeout=15000)
            else:
                expect(composer).to_be_enabled(timeout=15000)
            expect(composer).to_have_value(draft)
            assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["readOnly"] is archive
            expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sid}")
        composer.press("Control+End")
        composer.press_sequentially("，继续编辑", delay=2)
        expect(composer).to_have_value(draft + "，继续编辑")
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")


@pytest.mark.parametrize("archive", [True, False], ids=["archive", "unarchive"])
def test_late_archive_command_does_not_steal_another_session_or_its_draft(page, e2e_instance, archive):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    titles = [f"异步归档会话 {label} {suffix}" for label in "AB"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    drafts = [f"只属于会话 {label} 的草稿 {suffix}" for label in "AB"]
    _ready_composer(page, e2e_instance, sessions[0]).press_sequentially(drafts[0], delay=2)
    _switch(page, titles[1], sessions[1]).press_sequentially(drafts[1], delay=2)
    _switch(page, titles[0], sessions[0])
    if not archive:
        post_json(e2e_instance.port, f"/api/sessions/{sessions[0]}/archive")
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(COMPOSER).first).to_be_disabled(timeout=15000)
    _show_archived(page)
    endpoint = "archive" if archive else "unarchive"
    pending = []

    def delay_ack(route):
        # Apply the real backend command through the existing protected helper,
        # then withhold the browser acknowledgement. No in-flight route.fetch
        # outlives the test's request context.
        response = post_json(e2e_instance.port, f"/api/sessions/{sessions[0]}/{endpoint}")
        pending.append((route, response))

    pattern = f"**/api/sessions/{sessions[0]}/{endpoint}"
    page.route(pattern, delay_ack)
    try:
        with page.expect_request(lambda request: request.url.endswith(f"/api/sessions/{sessions[0]}/{endpoint}")):
            _open_action(page, titles[0], "归档会话" if archive else "取消归档").click()
        composer_b = _switch(page, titles[1], sessions[1])
        expect(composer_b).to_have_value(drafts[1])
        assert len(pending) == 1
        with page.expect_response(lambda response: response.url.endswith(f"/api/sessions/{sessions[0]}/{endpoint}")):
            route, response = pending.pop()
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))
        expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sessions[1]}")
        expect(composer_b).to_be_enabled()
        expect(composer_b).to_have_value(drafts[1])
        composer_a = _switch(page, titles[0], sessions[0])
        if archive:
            expect(composer_a).to_be_disabled(timeout=15000)
        else:
            expect(composer_a).to_be_enabled(timeout=15000)
        expect(composer_a).to_have_value(drafts[0])
        _assert_no_turns(e2e_instance, sessions, drafts)
    finally:
        for route, response in pending:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))
        page.unroute(pattern, delay_ack)
        post_json(e2e_instance.port, f"/api/sessions/{sessions[0]}/unarchive")


def test_unarchive_cancels_old_detail_get_and_late_body_cannot_restore_readonly(page, e2e_instance):
    from playwright.sync_api import expect

    title, sid, draft = _arrange_archived(page, e2e_instance)
    pending, detail_requests = [], []
    held_once = False

    def delay_old_detail(route):
        nonlocal held_once
        request = route.request
        if request.method != "GET" or urlsplit(request.url).path != f"/api/sessions/{sid}":
            route.fallback()
            return
        detail_requests.append(request)
        if held_once:
            route.fallback()
            return
        held_once = True
        parts = urlsplit(request.url)
        response = fetch_json(e2e_instance.port, f"{parts.path}?{parts.query}")
        assert response["readOnly"] is True
        pending.append((route, response))

    pattern = f"**/api/sessions/{sid}?*"
    page.route(pattern, delay_old_detail)
    try:
        with page.expect_request(lambda request: request.method == "GET" and urlsplit(request.url).path == f"/api/sessions/{sid}"):
            page.reload(wait_until="domcontentloaded")
        _show_archived(page)
        action = _open_action(page, title, "取消归档")
        assert len(pending) == 1
        old_request = detail_requests[0]
        with page.expect_event("requestfailed", predicate=lambda request: request == old_request, timeout=15000):
            action.click()
            expect(page.locator(COMPOSER).first).to_be_enabled(timeout=15000)
            expect(page.locator(COMPOSER).first).to_have_value(draft)
            assert len(detail_requests) >= 2, "Canonical detail must be fetched after cancelling the old request"
            route, response = pending.pop()
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))
        page.wait_for_timeout(250)
        expect(page.locator(COMPOSER).first).to_be_enabled()
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        for route, response in pending:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))
        page.unroute(pattern, delay_old_detail)
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")
