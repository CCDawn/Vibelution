"""Live archive recovery and search reopen without model submissions."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import post_json
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401
from tests.e2e.test_session_search_keyboard import _arrange

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


@pytest.fixture(scope="session", autouse=True)
def runtime_identity(e2e_instance):
    root = e2e_instance.project_root
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    backend = e2e_instance.health.get("backendCodeFingerprint") or {}
    assert backend.get("head") == head and backend.get("dirty") is False
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    evidence = common / "task-evidence" / "archive-search-round11-oct07"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "runtime-proof.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend,
        "serving": e2e_instance.health.get("serving"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("delay_select", [False, True], ids=["live-recovery", "late-archived-select"])
def test_unarchive_menu_restores_input_without_reload(page, e2e_instance, delay_select):
    from playwright.sync_api import expect

    title = f"即时取消归档 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    draft = "取消归档不用刷新也能继续编辑"
    _ready_composer(page, e2e_instance, sid).press_sequentially(draft, delay=2)
    post_json(e2e_instance.port, f"/api/sessions/{sid}/archive")
    old_detail = fetch_json(e2e_instance.port, f"/api/sessions/{sid}")
    pending = []

    def hold_select(route):
        pending.append(route)

    if delay_select:
        page.route(f"**/api/sessions/{sid}/select", hold_select)
    try:
        if delay_select:
            with page.expect_request(lambda request: request.url.endswith(f"/api/sessions/{sid}/select")):
                page.reload(wait_until="domcontentloaded")
        else:
            page.reload(wait_until="domcontentloaded")
        composer = page.locator(COMPOSER).first
        expect(composer).to_be_disabled(timeout=15000)
        expect(composer).to_have_value(draft)
        if delay_select:
            assert len(pending) == 1
        page.get_by_role("button", name="显示已归档会话", exact=True).click()
        row = page.get_by_role("tab").filter(has_text=title)
        expect(row).to_be_visible(timeout=15000)
        row.click(button="right")
        expect(page.get_by_role("menu", name="会话操作", exact=True)).to_contain_text("取消归档")
        with page.expect_response(lambda response: response.url.endswith(f"/api/sessions/{sid}/unarchive")) as saved:
            page.get_by_role("menuitem", name="取消归档", exact=True).click()
        assert saved.value.ok
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["readOnly"] is False
        expect(composer).to_be_enabled(timeout=15000)
        expect(composer).to_have_value(draft)
        if delay_select:
            with page.expect_response(lambda response: response.url.endswith(f"/api/sessions/{sid}/select")):
                pending.pop().fulfill(status=200, content_type="application/json", body=json.dumps(old_detail))
            page.wait_for_timeout(300)
            expect(composer).to_be_enabled()
        composer.press("Control+End")
        composer.press_sequentially("，继续", delay=2)
        expect(composer).to_have_value(draft + "，继续")
        expect(page.get_by_role("button", name="发送", exact=True)).to_be_enabled()
        expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sid}")
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        for route in pending:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(old_detail))
        if delay_select:
            page.unroute(f"**/api/sessions/{sid}/select", hold_select)
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")


def test_failed_unarchive_keeps_readonly_and_restores_menu_state(page, e2e_instance):
    from playwright.sync_api import expect

    title = f"取消归档失败恢复 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    draft = "失败后仍应保留这份草稿"
    _ready_composer(page, e2e_instance, sid).press_sequentially(draft, delay=2)
    post_json(e2e_instance.port, f"/api/sessions/{sid}/archive")
    page.reload(wait_until="domcontentloaded")
    composer = page.locator(COMPOSER).first
    expect(composer).to_be_disabled(timeout=15000)
    page.get_by_role("button", name="显示已归档会话", exact=True).click()
    row = page.get_by_role("tab").filter(has_text=title)
    expect(row).to_be_visible(timeout=15000)

    def fail_command(route):
        route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "controlled unarchive failure"}))

    page.route(f"**/api/sessions/{sid}/unarchive", fail_command)
    try:
        row.click(button="right")
        page.get_by_role("menuitem", name="取消归档", exact=True).click()
        expect(page.get_by_text("controlled unarchive failure", exact=False).first).to_be_visible(timeout=15000)
        expect(composer).to_be_disabled()
        expect(composer).to_have_value(draft)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["readOnly"] is True
        row.click(button="right")
        expect(page.get_by_role("menuitem", name="取消归档", exact=True)).to_be_enabled(timeout=15000)
        page.keyboard.press("Escape")
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        page.unroute(f"**/api/sessions/{sid}/unarchive", fail_command)
        post_json(e2e_instance.port, f"/api/sessions/{sid}/unarchive")


def test_pending_pagination_close_reopen_retains_query_and_deduplicates_results(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, composer, dialog, search = _arrange(page, e2e_instance)
    payload = fetch_json(e2e_instance.port, f"/api/sessions/query?q={quote(suffix)}&limit=50")
    cursors, pending = [], []

    def paginate(route):
        params = parse_qs(urlsplit(route.request.url).query)
        if params.get("q") != [suffix]:
            route.continue_()
            return
        cursor = params.get("cursor", [""])[0]
        cursors.append(cursor)
        if cursor:
            pending.append(route)
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                **payload, "items": payload["items"][:1], "nextCursor": "next-page", "totalEstimate": 2,
            }))

    page.route("**/api/sessions/query?*", paginate)
    try:
        search.fill(suffix)
        expect(dialog.locator("button[data-index]")).to_have_count(1, timeout=15000)
        with page.expect_request(lambda request: "cursor=next-page" in request.url):
            dialog.get_by_role("button", name="加载更多", exact=True).click()
        expect(dialog.get_by_role("button", name="加载中…", exact=True)).to_be_disabled()
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        page.get_by_role("button", name="全部会话", exact=True).click()
        expect(search).to_have_value(suffix)
        expect(dialog.locator("button[data-index]")).to_have_count(1)
        expect(dialog.get_by_role("button", name="加载中…", exact=True)).to_be_disabled()
        assert len(pending) == 1
        pending.pop().fulfill(status=200, content_type="application/json", body=json.dumps({
            **payload, "items": payload["items"][1:], "nextCursor": "", "totalEstimate": 2,
        }))
        expect(dialog.locator("button[data-index]")).to_have_count(2, timeout=15000)
        expect(dialog.get_by_role("button", name="加载中…", exact=True)).to_have_count(0)
        search.fill(f"新查询无结果 {uuid.uuid4().hex[:8]}")
        expect(dialog.locator("button[data-index]")).to_have_count(0, timeout=15000)
        expect(dialog.get_by_text("没有匹配的会话", exact=True)).to_be_visible(timeout=15000)
        search.press("Escape")
        expect(composer).to_have_value("搜索过程中保留草稿")
        assert cursors == ["", "next-page"]
        _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions/query?*", paginate)
