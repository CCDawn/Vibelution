"""Read-only recovery and deleted cache lifetime without model submissions."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import _http_write_json, post_json
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_search_keyboard import _arrange

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


@pytest.fixture(autouse=True)
def no_model_submission(page):
    captured = []

    def guard(route):
        path = urlsplit(route.request.url).path
        if route.request.method == "POST" and any(
            path.endswith(ending) for ending in ("/messages", "/messages/edit-resubmit", "/guidance")
        ):
            captured.append(path)
            route.abort()
        else:
            route.continue_()

    page.route("**/api/sessions/**", guard)
    yield
    page.unroute("**/api/sessions/**", guard)
    assert captured == [], "Read-only journeys must not submit a model turn or guidance"


@pytest.fixture(scope="session", autouse=True)
def runtime_identity(e2e_instance):
    import subprocess
    from pathlib import Path

    root = e2e_instance.project_root
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    backend = e2e_instance.health.get("backendCodeFingerprint") or {}
    assert backend.get("head") == head and backend.get("dirty") is False
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    evidence = common / "task-evidence" / "session-readonly-round10-oct06"
    evidence.mkdir(parents=True, exist_ok=True)
    proof = {"workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
             "port": e2e_instance.port, "head": head, "backend": backend,
             "serving": e2e_instance.health.get("serving")}
    (evidence / "runtime-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")


def test_deleted_cached_detail_stays_blocked_after_clock_advance_and_reconnect(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, titles, sessions, initial, _, dialog, search = _arrange(page, e2e_instance)
    search.fill(suffix)
    results = dialog.locator("button[data-index]")
    expect(results).to_have_count(2, timeout=15000)
    target = sessions[0]
    results.filter(has_text=titles[0]).click()
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", target, timeout=15000)
    _ready_composer(page, e2e_instance, initial)
    page.get_by_role("button", name="全部会话", exact=True).click()
    search.fill(suffix)
    expect(results).to_have_count(2, timeout=15000)
    _http_write_json("DELETE", e2e_instance.port, f"/api/sessions/{target}", None)
    results.filter(has_text=titles[0]).click()
    error = page.locator('[data-vui="state-surface"][data-tone="error"]')
    expect(error).to_be_visible(timeout=15000)
    page.clock.install()
    page.context.set_offline(True)
    try:
        # Browser clock only: cross the existing 120-second optimistic TTL.
        page.clock.fast_forward(125_000)
        page.get_by_role("button", name="全部会话", exact=True).click()
        search.fill("expired deletion marker probe")
        search.press("Escape")
        expect(error).to_be_visible(timeout=15000)
        expect(page.locator(COMPOSER)).to_have_count(0)
    finally:
        page.context.set_offline(False)
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={target}")
    expect(error).to_be_visible()
    _ready_composer(page, e2e_instance, initial)
    expect(page.locator(COMPOSER).first).to_have_value("搜索过程中保留草稿")
    _assert_no_turns(e2e_instance, [initial, sessions[1]], ["搜索过程中保留草稿"])


def test_unarchive_and_reload_restore_input_without_losing_draft(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="归档恢复保留草稿")
    draft = "取消归档后继续编辑这份草稿"
    _ready_composer(page, e2e_instance, sid).press_sequentially(draft, delay=2)
    post_json(e2e_instance.port, f"/api/sessions/{sid}/archive")
    try:
        page.reload(wait_until="domcontentloaded")
        composer = page.locator(COMPOSER).first
        expect(composer).to_be_disabled(timeout=15000)
        expect(composer).to_have_value(draft)
        expect(page.get_by_role("button", name="发送", exact=True)).to_be_disabled()
        expect(page.get_by_role("group", name="试试从这里开始")).to_have_count(0)
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["readOnly"] is False
        page.reload(wait_until="domcontentloaded")
        expect(composer).to_be_enabled(timeout=15000)
        expect(composer).to_have_value(draft)
        composer.press_sequentially("，恢复正常", delay=2)
        expect(composer).to_have_value(draft + "，恢复正常")
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")


def test_archived_history_edit_action_is_disabled(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="只读历史消息编辑入口")
    post_json(e2e_instance.port, f"/api/sessions/{sid}/archive")
    detail = fetch_json(e2e_instance.port, f"/api/sessions/{sid}")
    assert detail["readOnly"] is True
    # Controlled browser transcript fixture; never writes a message to backend.
    detail = {**detail, "messages": [{"id": "readonly-fixture-user", "role": "user",
              "timestamp": "2026-10-06T12:00:00Z", "content": "历史消息只供查看"}],
              "provisionalTranscript": False}

    def project_history(route):
        path = urlsplit(route.request.url).path
        if path == f"/api/sessions/{sid}" or path == f"/api/sessions/{sid}/select":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(detail))
        elif path == f"/api/sessions/{sid}/events":
            route.fulfill(status=200, content_type="text/event-stream", body=": controlled fixture\n\n")
        else:
            route.fallback()

    page.route(f"**/api/sessions/{sid}**", project_history)
    try:
        page.goto(f"{e2e_instance.base_url}/chat?session={sid}", wait_until="domcontentloaded")
        message = page.get_by_text("历史消息只供查看", exact=True).first
        expect(message).to_be_visible(timeout=15000)
        message.hover()
        expect(page.get_by_role("button", name="编辑消息", exact=True).first).to_be_disabled()
        expect(page.locator('[data-conversation-inline-edit="1"]')).to_have_count(0)
        _assert_no_turns(e2e_instance, [sid], ["历史消息只供查看"])
    finally:
        page.unroute(f"**/api/sessions/{sid}**", project_history)
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")
