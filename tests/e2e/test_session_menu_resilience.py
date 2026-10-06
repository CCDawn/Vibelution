"""Failure, cancellation and keyboard journeys for session menus."""
from __future__ import annotations

import json
import uuid

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_menu_journeys import no_model_submission  # noqa: F401

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


@pytest.fixture(scope="session", autouse=True)
def runtime_identity(e2e_instance):
    from pathlib import Path
    import subprocess

    root = e2e_instance.project_root
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    health = e2e_instance.health
    backend = health.get("backendCodeFingerprint") or {}
    assert backend.get("head") == head
    assert backend.get("dirty") is False
    proof = {
        "head": head, "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "backend": backend, "serving": health.get("serving"),
        "servingBuildKey": health.get("servingBuildKey"), "servingRelease": health.get("servingRelease"),
    }
    evidence = common / "task-evidence" / "session-resilience-round6-oct06"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "runtime-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")


def _begin_rename(page, title):
    from playwright.sync_api import expect

    page.get_by_role("tab").filter(has_text=title).click(button="right")
    page.get_by_role("menuitem", name="重命名会话", exact=True).click()
    editor = page.get_by_role("textbox", name="重命名会话", exact=True)
    expect(editor).to_be_focused()
    return editor


def test_cancel_and_empty_rename_never_write_or_lose_draft(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"取消与空名称检查 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    composer = _ready_composer(page, e2e_instance, sid)
    draft = "取消命名仍然保留草稿"
    composer.press_sequentially(draft, delay=3)
    patches = []
    page.on("request", lambda request: patches.append(request.url) if request.method == "PATCH" else None)
    editor = _begin_rename(page, title)
    editor.fill("不应该保存的名称")
    editor.press("Escape")
    expect(editor).not_to_be_visible()
    editor = _begin_rename(page, title)
    editor.fill("第二次取消的名称")
    page.get_by_role("button", name="取消重命名", exact=True).click()
    expect(editor).not_to_be_visible()
    editor = _begin_rename(page, title)
    editor.fill("   ")
    editor.press("Enter")
    expect(editor).to_be_visible()
    expect(page.get_by_text("会话名称不能为空", exact=True)).to_be_visible()
    editor.press("Escape")
    expect(composer).to_have_value(draft)
    assert patches == []
    assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == title
    _assert_no_turns(e2e_instance, [sid], [draft])


def test_failed_rename_can_retry_without_losing_name_or_draft(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    title, renamed = f"失败重试原名 {suffix}", f"失败重试新名 {suffix}"
    sid = create_session(e2e_instance.port, title=title)
    composer = _ready_composer(page, e2e_instance, sid)
    draft = "失败保存不能丢掉未发送内容"
    composer.press_sequentially(draft, delay=3)
    failed = []

    def fail_once(route):
        if route.request.method == "PATCH":
            failed.append(route.request.url)
            route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "测试保存失败，请重试"}))
        else:
            route.continue_()

    pattern = f"**/api/sessions/{sid}"
    page.route(pattern, fail_once)
    editor = _begin_rename(page, title)
    editor.fill(renamed)
    editor.press("Enter")
    expect(editor).to_have_value(renamed, timeout=15000)
    expect(page.get_by_role("alert")).to_contain_text("测试保存失败，请重试")
    expect(composer).to_have_value(draft)
    assert failed == [f"{e2e_instance.base_url}/api/sessions/{sid}"]
    assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == title
    page.unroute(pattern, fail_once)
    with page.expect_response(lambda response: response.request.method == "PATCH" and response.url.endswith(f"/api/sessions/{sid}")) as saved:
        editor.press("Enter")
    assert saved.value.ok
    expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
    expect(composer).to_have_value(draft)
    assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == renamed
    _assert_no_turns(e2e_instance, [sid], [draft])


def test_refresh_during_pending_rename_restores_confirmed_title_and_draft(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"保存中刷新原名 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    composer = _ready_composer(page, e2e_instance, sid)
    draft = "保存中刷新也不能丢掉草稿"
    composer.press_sequentially(draft, delay=3)
    pending = []

    def hold_patch(route):
        if route.request.method == "PATCH":
            pending.append(route)
        else:
            route.continue_()

    pattern = f"**/api/sessions/{sid}"
    page.route(pattern, hold_patch)
    editor = _begin_rename(page, title)
    editor.fill("尚未保存的临时名称")
    editor.press("Enter")
    expect(page.get_by_role("tab").filter(has_text="尚未保存的临时名称")).to_be_visible()
    assert len(pending) == 1
    assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == title
    page.reload(wait_until="domcontentloaded")
    page.unroute(pattern, hold_patch)
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
    expect(page.get_by_role("tab").filter(has_text=title)).to_be_visible()
    expect(page.locator(COMPOSER).first).to_have_value(draft, timeout=15000)
    _assert_no_turns(e2e_instance, [sid], [draft])


def test_outside_click_closes_menu_and_focuses_composer(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"菜单外部点击 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    composer = _ready_composer(page, e2e_instance, sid)
    page.get_by_role("tab").filter(has_text=title).click(button="right")
    expect(page.get_by_role("menu", name="会话操作", exact=True)).to_be_visible()
    composer.click()
    expect(page.get_by_role("menu", name="会话操作", exact=True)).not_to_be_visible()
    expect(composer).to_be_focused()
    page.keyboard.type("菜单外部点击后直接继续输入")
    expect(composer).to_have_value("菜单外部点击后直接继续输入")
    _assert_no_turns(e2e_instance, [sid], ["菜单外部点击后直接继续输入"])


def test_search_empty_clear_and_tab_enter_open_the_focused_result(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    titles = [f"键盘搜索同组 {suffix} {label}" for label in "AB"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    initial = create_session(e2e_instance.port, title=f"搜索前独立草稿会话 {uuid.uuid4().hex[:8]}")
    composer = _ready_composer(page, e2e_instance, initial)
    draft = "搜索键盘切换保留草稿"
    composer.press_sequentially(draft, delay=3)
    page.get_by_role("button", name="全部会话", exact=True).click()
    dialog = page.get_by_role("dialog", name="搜索标题、摘要或会话编号", exact=True)
    search = dialog.get_by_role("searchbox")
    search.fill(f"不存在的唯一标记 {suffix}")
    expect(dialog.locator("button[data-index]")).to_have_count(0, timeout=15000)
    search.press("ArrowDown")
    search.press("Enter")
    expect(dialog).to_be_visible()
    search.fill("")
    expect(dialog.locator("button[data-index]").first).to_be_visible(timeout=15000)
    search.fill(suffix)
    results = dialog.locator("button[data-index]")
    expect(results).to_have_count(2, timeout=15000)
    target = results.nth(1)
    target_text = target.inner_text()
    target_index = next(i for i, title in enumerate(titles) if title in target_text)
    for _ in range(20):
        if target.evaluate("element => element === document.activeElement"):
            break
        page.keyboard.press("Tab")
    expect(target).to_be_focused()
    page.keyboard.press("Enter")
    expect(dialog).not_to_be_visible()
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sessions[target_index]}", timeout=15000)
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[target_index], timeout=15000)
    expect(composer).to_have_value("")
    composer = _ready_composer(page, e2e_instance, initial)
    expect(composer).to_have_value(draft)
    _assert_no_turns(e2e_instance, [initial, *sessions], [draft])
