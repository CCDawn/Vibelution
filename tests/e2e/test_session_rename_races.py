"""Rename retries and late acknowledgements preserve session identity and drafts."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import patch_json
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
    frontend_head = (serving.get("frontend") or {}).get("builtFromCommit")
    assert frontend_head
    # Launcher may reuse identical frontend sources after a tests-only commit.
    # Verify actual source equivalence instead of relabelling its provenance.
    def web_tree(commit):
        return subprocess.check_output(["git", "rev-parse", f"{commit}:web"], cwd=root, text=True).strip()
    frontend_tree, tested_tree = web_tree(frontend_head), web_tree(head)
    assert frontend_tree == tested_tree
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    evidence = common / "task-evidence" / "rename-races-round13-oct07"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "runtime-proof.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend, "serving": serving,
        "frontendSourceTree": frontend_tree, "testedWebTree": tested_tree,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _edit(page, title, replacement):
    from playwright.sync_api import expect

    page.get_by_role("tab").filter(has_text=title).click(button="right")
    page.get_by_role("menuitem", name="重命名会话", exact=True).click()
    editor = page.get_by_role("textbox", name="重命名会话", exact=True)
    expect(editor).to_be_focused()
    editor.fill(replacement)
    return editor


def _is_patch(request, sid):
    return request.method == "PATCH" and request.url.endswith(f"/api/sessions/{sid}")


def test_rename_failure_retries_from_restored_editor_without_losing_draft(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    title, renamed = f"重命名重试 {suffix}", f"重命名重试成功 {suffix}"
    sid = create_session(e2e_instance.port, title=title)
    draft = f"重命名失败也保留草稿 {suffix}"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    marker = "rename controlled failure"
    pattern = f"**/api/sessions/{sid}"

    def fail(route):
        if route.request.method == "PATCH":
            route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": marker}))
        else:
            route.continue_()

    page.route(pattern, fail)
    try:
        _edit(page, title, renamed).press("Enter")
        error = page.get_by_text(marker, exact=False).first
        expect(error).to_be_visible(timeout=15000)
        editor = page.get_by_role("textbox", name="重命名会话", exact=True)
        expect(editor).to_have_value(renamed)
        expect(composer).to_have_value(draft)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == title
        page.unroute(pattern, fail)
        with page.expect_response(lambda response: _is_patch(response.request, sid)) as saved:
            editor.press("Enter")
        assert saved.value.ok
        expect(editor).not_to_be_visible()
        expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
        expect(error).not_to_be_visible()
        expect(composer).to_have_value(draft)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == renamed
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        page.unroute(pattern, fail)


@pytest.mark.parametrize("success", [True, False], ids=["success", "failure"])
def test_blur_save_then_switch_keeps_response_bound_to_original_session(page, e2e_instance, success):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    titles = [f"异步重命名 {label} {suffix}" for label in "AB"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    drafts = [f"会话 {label} 的独立草稿 {suffix}" for label in "AB"]
    _ready_composer(page, e2e_instance, sessions[0]).press_sequentially(drafts[0], delay=2)
    _switch(page, titles[1], sessions[1]).press_sequentially(drafts[1], delay=2)
    _switch(page, titles[0], sessions[0])
    renamed = f"异步重命名完成 {suffix}"
    pending = []
    pattern = f"**/api/sessions/{sessions[0]}"

    def delay_ack(route):
        if route.request.method != "PATCH":
            route.continue_()
            return
        body = patch_json(e2e_instance.port, f"/api/sessions/{sessions[0]}", route.request.post_data_json) if success else {"detail": "late rename failure"}
        pending.append((route, body))

    page.route(pattern, delay_ack)
    try:
        _edit(page, titles[0], renamed)
        # Selecting B blurs A's editor; the existing contract submits that edit.
        with page.expect_request(lambda request: _is_patch(request, sessions[0])):
            composer_b = _switch(page, titles[1], sessions[1])
        expect(composer_b).to_have_value(drafts[1])
        assert len(pending) == 1
        route, body = pending.pop()
        assert route.request.post_data_json == {"title": renamed}
        if success:
            assert body["title"] == renamed
        with page.expect_response(lambda response: _is_patch(response.request, sessions[0])):
            route.fulfill(status=200 if success else 503, content_type="application/json", body=json.dumps(body))
        expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sessions[1]}")
        expect(composer_b).to_have_value(drafts[1])
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sessions[1]}")["title"] == titles[1]
        if success:
            # The sidebar labels the owning Agent, whose name stays unchanged.
            expect(_switch(page, titles[0], sessions[0])).to_have_value(drafts[0])
            expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
        else:
            # A belongs to another Agent tab group and is hidden while B is selected.
            # Return through the sidebar before checking its restored editor.
            _switch(page, titles[0], sessions[0])
            editor = page.get_by_role("textbox", name="重命名会话", exact=True)
            expect(editor).to_have_value(renamed)
            editor.press("Escape")
            expect(page.locator(COMPOSER).first).to_have_value(drafts[0])
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sessions[0]}")["title"] == (renamed if success else titles[0])
        _assert_no_turns(e2e_instance, sessions, drafts)
    finally:
        for route, _body in pending:
            route.abort()
        page.unroute(pattern, delay_ack)


def test_failed_rename_does_not_rollback_another_sessions_successful_title(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    titles = [f"并行重命名 {label} {suffix}" for label in "AB"]
    renamed = [f"新标题 {label} {suffix}" for label in "AB"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    drafts = [f"并行操作保留草稿 {label} {suffix}" for label in "AB"]
    _ready_composer(page, e2e_instance, sessions[0]).press_sequentially(drafts[0], delay=2)
    _switch(page, titles[1], sessions[1]).press_sequentially(drafts[1], delay=2)
    _switch(page, titles[0], sessions[0])
    pending = []
    pattern = f"**/api/sessions/{sessions[0]}"

    def delay_failure(route):
        if route.request.method == "PATCH":
            pending.append(route)
        else:
            route.continue_()

    page.route(pattern, delay_failure)
    try:
        with page.expect_request(lambda request: _is_patch(request, sessions[0])):
            _edit(page, titles[0], renamed[0]).press("Enter")
        _switch(page, titles[1], sessions[1])
        editor_b = _edit(page, titles[1], renamed[1])
        with page.expect_response(lambda response: _is_patch(response.request, sessions[1])) as saved:
            editor_b.press("Enter")
        assert saved.value.ok
        expect(page.get_by_role("tab").filter(has_text=renamed[1])).to_be_visible()
        assert len(pending) == 1
        route = pending.pop()
        def failed_telemetry(request):
            if not request.url.endswith("/api/runtime/browser-telemetry") or request.method != "POST":
                return False
            body = request.post_data_json or {}
            return body.get("eventCode") == "browser.user_action.session_rename_failed" and (body.get("fields") or {}).get("sessionId") == sessions[0]

        # Observe the mutation callback, not just the transport response. Check
        # B before navigating: a fresh detail read could otherwise mask rollback.
        with page.expect_request(failed_telemetry):
            route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "earlier rename failed"}))
        expect(page.get_by_role("tab").filter(has_text=renamed[1])).to_be_visible()
        expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sessions[1]}")
        expect(page.locator(COMPOSER).first).to_have_value(drafts[1])
        # Return to A to observe its completed error handling; its tab/editor
        # is hidden while B's Agent is selected.
        _switch(page, titles[0], sessions[0])
        editor_a = page.get_by_role("textbox", name="重命名会话", exact=True)
        expect(editor_a).to_have_value(renamed[0])
        editor_a.press("Escape")
        _switch(page, titles[1], sessions[1])
        expect(page.get_by_role("tab").filter(has_text=renamed[1])).to_be_visible()
        expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sessions[1]}")
        expect(page.locator(COMPOSER).first).to_have_value(drafts[1])
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sessions[1]}")["title"] == renamed[1]
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sessions[0]}")["title"] == titles[0]
        _assert_no_turns(e2e_instance, sessions, drafts)
    finally:
        for route in pending:
            route.abort()
        page.unroute(pattern, delay_failure)


def test_escape_cancels_rename_without_patch_and_composer_remains_editable(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"取消重命名 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    draft = "取消标题编辑保留的草稿"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    requests = []
    listener = lambda request: requests.append(request.url) if _is_patch(request, sid) else None
    page.on("request", listener)
    try:
        editor = _edit(page, title, "这次修改应当被取消")
        editor.press("Escape")
        expect(editor).not_to_be_visible()
        expect(page.get_by_role("tab").filter(has_text=title)).to_be_visible()
        composer.click()
        composer.press("Control+End")
        composer.press_sequentially("，继续输入", delay=2)
        expect(composer).to_have_value(draft + "，继续输入")
        assert requests == []
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == title
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        page.remove_listener("request", listener)


def test_enter_then_focus_composer_sends_only_one_rename_patch(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    title, renamed = f"一次重命名 {suffix}", f"只保存一次 {suffix}"
    sid = create_session(e2e_instance.port, title=title)
    composer = _ready_composer(page, e2e_instance, sid)
    pending = []
    requests = []
    pattern = f"**/api/sessions/{sid}"

    def delay_ack(route):
        if route.request.method == "PATCH":
            requests.append(route.request.post_data_json)
            pending.append((route, patch_json(e2e_instance.port, f"/api/sessions/{sid}", route.request.post_data_json)))
        else:
            route.continue_()

    page.route(pattern, delay_ack)
    try:
        editor = _edit(page, title, renamed)
        with page.expect_request(lambda request: _is_patch(request, sid)):
            editor.press("Enter")
        composer.click()
        composer.press_sequentially("等待保存时继续编辑草稿", delay=2)
        expect(editor).not_to_be_visible()
        assert requests == [{"title": renamed}]
        route, body = pending.pop()
        with page.expect_response(lambda response: _is_patch(response.request, sid)):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
        expect(composer).to_have_value("等待保存时继续编辑草稿")
        assert requests == [{"title": renamed}]
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == renamed
        _assert_no_turns(e2e_instance, [sid], ["等待保存时继续编辑草稿"])
    finally:
        for route, _body in pending:
            route.abort()
        page.unroute(pattern, delay_ack)
