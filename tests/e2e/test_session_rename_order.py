"""Real rename ordering, keyboard boundaries and independent session controls."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import patch_json, post_json
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401
from tests.e2e.test_session_rename_races import _edit, _is_patch

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
    frontend_head = (serving.get("frontend") or {}).get("builtFromCommit")
    assert frontend_head
    trees = [subprocess.check_output(["git", "rev-parse", f"{commit}:web"], cwd=root, text=True).strip() for commit in (head, frontend_head)]
    assert trees[0] == trees[1]
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    evidence = common / "task-evidence" / "rename-order-round14-oct07"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "runtime-proof.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend, "serving": serving,
        "testedWebTree": trees[0], "frontendSourceTree": trees[1],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _terminal(sid, phase):
    def matches(request):
        if request.method != "POST" or not request.url.endswith("/api/runtime/browser-telemetry"):
            return False
        body = request.post_data_json or {}
        return body.get("eventCode") == f"browser.user_action.session_rename_{phase}" and (body.get("fields") or {}).get("sessionId") == sid
    return matches


def _save(page, sid, editor):
    with page.expect_request(_terminal(sid, "succeeded")), page.expect_response(lambda response: _is_patch(response.request, sid)) as response:
        editor.press("Enter")
    assert response.value.ok
    return response.value.json()


@pytest.mark.parametrize("first_succeeds", [True, False], ids=["old-success", "old-failure"])
@pytest.mark.parametrize("latest_succeeds", [True, False], ids=["latest-success", "latest-failure"])
@pytest.mark.parametrize("old_response_first", [True, False], ids=["old-response-first", "latest-response-first"])
def test_rename_response_order_preserves_latest_intent(page, e2e_instance, first_succeeds, latest_succeeds, old_response_first):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    original, first, latest = [f"连续改名 {label} {suffix}" for label in ("原名", "首次", "最终")]
    sid = create_session(e2e_instance.port, title=original)
    draft = f"连续改名期间保留的草稿 {suffix}"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    pending = {}
    pattern = f"**/api/sessions/{sid}"

    def delay_ack(route):
        title = (route.request.post_data_json or {}).get("title") if route.request.method == "PATCH" else None
        if title in (first, latest):
            succeeds = first_succeeds if title == first else latest_succeeds
            marker = "superseded rename failure" if title == first else "latest rename failure"
            body = patch_json(e2e_instance.port, f"/api/sessions/{sid}", {"title": title}) if succeeds else {"detail": marker}
            pending[title] = (route, body, succeeds)
        else:
            route.continue_()

    page.route(pattern, delay_ack)
    try:
        with page.expect_request(lambda request: _is_patch(request, sid)):
            _edit(page, original, first).press("Enter")
        expect(page.get_by_role("tab").filter(has_text=first)).to_be_visible()
        with page.expect_request(lambda request: _is_patch(request, sid)):
            _edit(page, first, latest).press("Enter")
        expect(page.get_by_role("tab").filter(has_text=latest)).to_be_visible()
        assert len(pending) == 2
        for title in ((first, latest) if old_response_first else (latest, first)):
            route, body, succeeds = pending.pop(title)
            with page.expect_request(_terminal(sid, "succeeded" if succeeds else "failed")):
                route.fulfill(status=200 if succeeds else 503, content_type="application/json", body=json.dumps(body))
        # Inspect before navigation/reload can repair stale client state.
        editor = page.get_by_role("textbox", name="重命名会话", exact=True)
        if latest_succeeds:
            expect(editor).not_to_be_visible()
        else:
            expect(editor).to_have_value(latest)
            expect(page.get_by_text("latest rename failure", exact=False).first).to_be_visible()
            editor.press("Escape")
        expected = latest if latest_succeeds else first if first_succeeds else original
        expect(page.get_by_role("tab").filter(has_text=expected)).to_be_visible()
        expect(page.get_by_text("superseded rename failure", exact=False)).not_to_be_visible()
        expect(composer).to_have_value(draft)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == expected
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.get_by_role("tab").filter(has_text=expected)).to_be_visible()
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        for route, _, _ in pending.values():
            route.abort()
        page.unroute(pattern, delay_ack)


def test_failed_save_preserves_a_newer_unsaved_title_edit(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    original, attempted, unsaved = [f"保留标题草稿 {label} {suffix}" for label in ("原名", "失败尝试", "正在修改")]
    sid = create_session(e2e_instance.port, title=original)
    draft = "保存失败期间消息草稿也保持不变"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    pending = []
    pattern = f"**/api/sessions/{sid}"

    def hold(route):
        if route.request.method == "PATCH":
            pending.append(route)
        else:
            route.continue_()

    page.route(pattern, hold)
    try:
        with page.expect_request(lambda request: _is_patch(request, sid)):
            _edit(page, original, attempted).press("Enter")
        editor = _edit(page, attempted, unsaved)
        assert len(pending) == 1
        with page.expect_request(_terminal(sid, "failed")):
            pending.pop().fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "earlier attempt failed while editing"}))
        expect(editor).to_have_value(unsaved)
        expect(composer).to_have_value(draft)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == original
        editor.press("Escape")
        expect(page.get_by_role("tab").filter(has_text=original)).to_be_visible()
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        for route in pending:
            route.abort()
        page.unroute(pattern, hold)


@pytest.mark.parametrize("kind", ["trim", "limit"])
def test_keyboard_title_boundary_matches_server_and_reload(page, e2e_instance, kind):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    original = f"标题边界原名 {suffix}"
    sid = create_session(e2e_instance.port, title=original)
    draft = f"标题边界保留草稿 {suffix}"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    typed = f"   边界确认 {suffix}   " if kind == "trim" else f"长度限制 {suffix} " + "中文名称" * 40
    expected = typed[:120].strip()
    editor = _edit(page, original, "")
    editor.press_sequentially(typed, delay=1)
    expect(editor).to_have_value(typed[:120])
    assert _save(page, sid, editor)["title"] == expected
    expect(page.get_by_role("tab").filter(has_text=expected)).to_be_visible()
    assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == expected
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
    expect(page.get_by_role("tab").filter(has_text=expected)).to_be_visible()
    expect(page.locator(COMPOSER).first).to_have_value(draft)
    _assert_no_turns(e2e_instance, [sid], [draft])


def test_whitespace_title_stays_editable_without_a_patch(page, e2e_instance):
    from playwright.sync_api import expect

    original = f"空白标题 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=original)
    composer = _ready_composer(page, e2e_instance, sid)
    draft = "输入空白标题不能提交消息草稿"
    composer.press_sequentially(draft, delay=2)
    requests = []
    listener = lambda request: requests.append(request.url) if _is_patch(request, sid) else None
    page.on("request", listener)
    try:
        editor = _edit(page, original, "   ")
        editor.press("Enter")
        expect(editor).to_have_value("   ")
        expect(page.get_by_text("会话名称不能为空", exact=False).first).to_be_visible()
        assert requests == []
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == original
        editor.press("Escape")
        expect(composer).to_have_value(draft)
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        page.remove_listener("request", listener)


def test_late_rename_keeps_pin_sort_and_search_in_sync(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    original, renamed = f"置顶改名原名 {suffix}", f"置顶改名确认 {suffix}"
    sid = create_session(e2e_instance.port, title=original)
    draft = f"置顶排序搜索保留草稿 {suffix}"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    pending = []
    pattern = f"**/api/sessions/{sid}"

    def hold(route):
        if route.request.method == "PATCH":
            pending.append((route, patch_json(e2e_instance.port, f"/api/sessions/{sid}", route.request.post_data_json)))
        else:
            route.continue_()

    def pin_menu():
        page.get_by_role("tab").filter(has_text=renamed).click(button="right")

    page.route(pattern, hold)
    try:
        with page.expect_request(lambda request: _is_patch(request, sid)):
            _edit(page, original, renamed).press("Enter")
        pin_menu()
        with page.expect_response(lambda response: response.url.endswith(f"/api/sessions/{sid}/pin")) as pinned:
            page.get_by_role("menuitem", name="置顶会话", exact=True).click()
        assert pinned.value.ok
        pin_menu()
        expect(page.get_by_role("menuitem", name="取消置顶", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        page.get_by_role("combobox", name="会话排序方式", exact=True).click()
        page.get_by_role("option", name="按创建时间", exact=True).click()
        assert len(pending) == 1
        route, body = pending.pop()
        with page.expect_request(_terminal(sid, "succeeded")):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        pin_menu()
        expect(page.get_by_role("menuitem", name="取消置顶", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
        page.get_by_role("button", name="全部会话", exact=True).click()
        dialog = page.get_by_role("dialog", name="搜索标题、摘要或会话编号", exact=True)
        dialog.get_by_role("searchbox").fill(renamed)
        result = dialog.get_by_role("button").filter(has_text=renamed).first
        expect(result).to_be_visible(timeout=15000)
        result.click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == renamed
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        for route, _ in pending:
            route.abort()
        page.unroute(pattern, hold)
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unpin")
