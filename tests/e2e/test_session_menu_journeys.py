"""Real session menu actions preserve titles, drafts and keyboard navigation."""
from __future__ import annotations

import uuid

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


def _row(page, title):
    return page.get_by_role("button").filter(has=page.get_by_text(title, exact=True)).first


@pytest.fixture(autouse=True)
def no_model_submission(page):
    captured = []

    def block(route):
        if route.request.method == "POST":
            captured.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    page.route("**/api/sessions/*/messages", block)
    yield
    page.unroute("**/api/sessions/*/messages", block)
    assert captured == [], "Menu navigation must not submit a model message"


def test_rename_long_session_title_survives_reload_without_losing_draft(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    original = f"重命名前的会话 {suffix}"
    renamed = f"重命名后的中文长标题用于检查会话目录刷新持久化 {suffix}" * 2
    sid = create_session(e2e_instance.port, title=original)
    draft = f"重命名不能清空未发送文字 {suffix}"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=3)
    page.get_by_role("tab").filter(has_text=original).click(button="right")
    page.get_by_role("menuitem", name="重命名会话", exact=True).click()
    editor = page.get_by_role("textbox", name="重命名会话", exact=True)
    expect(editor).to_be_focused()
    editor.fill(renamed)
    editor.press("Enter")
    expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
    expect(composer).to_have_value(draft)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
    expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
    expect(page.locator(COMPOSER).first).to_have_value(draft, timeout=15000)
    assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == renamed
    _assert_no_turns(e2e_instance, [sid], [draft])


def test_escape_closes_session_menu_and_returns_focus_to_session_row(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"取消会话操作 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    composer = _ready_composer(page, e2e_instance, sid)
    draft = "关闭右键菜单后草稿继续存在"
    composer.press_sequentially(draft, delay=3)
    row = page.get_by_role("tab").filter(has_text=title)
    row.click(button="right")
    expect(page.get_by_role("menu", name="会话操作", exact=True)).to_be_visible()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    expect(page.get_by_role("menu", name="会话操作", exact=True)).not_to_be_visible()
    expect(row).to_be_focused()
    expect(composer).to_have_value(draft)
    page.keyboard.press("Enter")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid)
    _assert_no_turns(e2e_instance, [sid], [draft])


def test_escape_closes_create_menu_and_directory_search_restoring_trigger_focus(page, e2e_instance):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="键盘关闭搜索与新建菜单")
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially("搜索和菜单不能提交这段文字", delay=3)
    create = page.get_by_role("button", name="新建任务", exact=True).first
    create.click()
    expect(page.get_by_role("menu")).to_be_visible()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    expect(page.get_by_role("menu")).not_to_be_visible()
    expect(create).to_be_focused()
    search = page.get_by_role("button", name="搜索 Agent 或团队", exact=True)
    search.click()
    editor = page.get_by_role("textbox", name="搜索 Agent 或团队", exact=True)
    expect(editor).to_be_focused()
    editor.press_sequentially("没有匹配的索引", delay=3)
    editor.press("Escape")
    expect(editor).not_to_be_visible()
    expect(search).to_be_focused()
    expect(composer).to_have_value("搜索和菜单不能提交这段文字")


def test_dense_sidebar_at_narrow_width_accepts_actual_pointer_switches(page, e2e_instance, tmp_path):
    from playwright.sync_api import expect

    for index in range(10):
        create_session(e2e_instance.port, title=f"密集侧栏准备会话 {index}")
    suffix = uuid.uuid4().hex[:8]
    titles = [f"窄窗口长标题与鼠标命中检查 {label} {suffix}" * 2 for label in "ABC"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    page.set_viewport_size({"width": 900, "height": 640})
    composer = _ready_composer(page, e2e_instance, sessions[0])
    draft = "窄窗口下切换后应恢复的草稿"
    composer.press_sequentially(draft, delay=3)
    for index in [1, 2, 0]:
        row = _row(page, titles[index])
        if not row.is_visible():
            page.locator("#chat-conversation-index-toggle").click()
        expect(row).to_be_visible()
        row.scroll_into_view_if_needed()
        row.hover()
        box = row.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.up()
        try:
            expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[index], timeout=15000)
        except AssertionError:
            page.screenshot(path=str(tmp_path / "narrow-pointer-failure.png"))
            raise
        expect(composer).to_have_value(draft if index == 0 else "")
    _assert_no_turns(e2e_instance, sessions, [draft])


def test_catalog_search_switch_preserves_unsent_drafts(page, e2e_instance):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    titles = [f"目录搜索目标 {label} {suffix}" for label in "AB"]
    sessions = [create_session(e2e_instance.port, title=title) for title in titles]
    composer = _ready_composer(page, e2e_instance, sessions[0])
    drafts = [f"搜索切换保留草稿 {label} {suffix}" for label in "AB"]
    composer.press_sequentially(drafts[0], delay=3)
    edited = {0}
    for index in [1, 0, 1]:
        page.get_by_role("button", name="全部会话", exact=True).click()
        dialog = page.get_by_role("dialog", name="搜索标题、摘要或会话编号", exact=True)
        expect(dialog).to_be_visible()
        search = dialog.get_by_role("searchbox")
        search.fill(titles[index])
        result = dialog.get_by_role("button").filter(has_text=titles[index]).first
        expect(result).to_be_visible(timeout=15000)
        result.click()
        expect(dialog).not_to_be_visible()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sessions[index], timeout=15000)
        expect(composer).to_have_value(drafts[0] if index == 0 else (drafts[1] if index in edited else ""))
        if index == 1:
            composer.press("ControlOrMeta+A")
            composer.press_sequentially(drafts[1], delay=3)
        edited.add(index)
    _assert_no_turns(e2e_instance, sessions, drafts)
