"""Real keyboard and delayed-response journeys for the session directory."""
from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_menu_journeys import no_model_submission  # noqa: F401

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


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
    evidence = common / "task-evidence" / "search-lifecycle-round7-oct06"
    evidence.mkdir(parents=True, exist_ok=True)
    proof = {"workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
             "port": e2e_instance.port, "head": head, "backend": backend,
             "serving": e2e_instance.health.get("serving")}
    (evidence / "runtime-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")


def _arrange(page, instance):
    suffix = uuid.uuid4().hex[:8]
    titles = [f"搜索操作 {suffix} {label}" for label in "AB"]
    sessions = [create_session(instance.port, title=title) for title in titles]
    initial = create_session(instance.port, title=f"搜索前独立会话 {uuid.uuid4().hex[:8]}")
    composer = _ready_composer(page, instance, initial)
    composer.press_sequentially("搜索过程中保留草稿", delay=2)
    page.get_by_role("button", name="全部会话", exact=True).click()
    dialog = page.get_by_role("dialog", name="搜索标题、摘要或会话编号", exact=True)
    return suffix, titles, sessions, initial, composer, dialog, dialog.get_by_role("searchbox")


def _tab_to(page, target):
    from playwright.sync_api import expect

    for _ in range(20):
        if target.evaluate("element => element === document.activeElement"):
            break
        page.keyboard.press("Tab")
    expect(target).to_be_focused()


def test_tab_arrow_enter_opens_the_visibly_selected_result(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, titles, sessions, initial, composer, dialog, search = _arrange(page, e2e_instance)
    search.fill(suffix)
    results = dialog.locator("button[data-index]")
    expect(results).to_have_count(2, timeout=15000)
    target_text = results.nth(0).inner_text()
    target_sid = sessions[next(i for i, title in enumerate(titles) if title in target_text)]
    _tab_to(page, results.nth(1))
    page.keyboard.press("ArrowUp")
    expect(results.nth(0)).to_have_attribute("data-active", "true")
    expect(results.nth(0)).to_be_focused()
    page.keyboard.press("Enter")
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={target_sid}", timeout=15000)
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", target_sid)
    _ready_composer(page, e2e_instance, initial)
    expect(composer).to_have_value("搜索过程中保留草稿")
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])


def test_enter_immediately_after_new_query_does_not_open_old_hits(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, composer, dialog, search = _arrange(page, e2e_instance)
    search.fill(suffix)
    expect(dialog.locator("button[data-index]")).to_have_count(2, timeout=15000)
    search.fill(f"不存在的新查询 {uuid.uuid4().hex[:8]}")
    search.press("Enter")
    expect(dialog).to_be_visible()
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={initial}")
    expect(dialog.locator("button[data-index]")).to_have_count(0, timeout=15000)
    search.press("Escape")
    expect(composer).to_have_value("搜索过程中保留草稿")
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])


def test_late_old_response_cannot_replace_new_query_or_open_a_session(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, _, dialog, search = _arrange(page, e2e_instance)
    old = fetch_json(e2e_instance.port, f"/api/sessions/query?q={quote(suffix)}&limit=50")
    pending = []

    def hold_old(route):
        if parse_qs(urlsplit(route.request.url).query).get("q") == [suffix]:
            pending.append(route)
        else:
            route.continue_()

    page.route("**/api/sessions/query?*", hold_old)
    with page.expect_request(lambda request: parse_qs(urlsplit(request.url).query).get("q") == [suffix]):
        search.fill(suffix)
    expect(search).to_have_value(suffix)
    assert len(pending) == 1
    search.fill(f"无结果新查询 {uuid.uuid4().hex[:8]}")
    expect(dialog.get_by_text("没有匹配的会话", exact=True)).to_be_visible(timeout=15000)
    pending[0].fulfill(status=200, content_type="application/json", body=json.dumps(old))
    search.press("Enter")
    expect(dialog.locator("button[data-index]")).to_have_count(0)
    expect(dialog).to_be_visible()
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={initial}")
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])


def test_tab_enter_loads_next_page_and_keeps_the_dialog_open(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, _, dialog, search = _arrange(page, e2e_instance)
    payload = fetch_json(e2e_instance.port, f"/api/sessions/query?q={quote(suffix)}&limit=50")
    pages = []

    def paginate(route):
        params = parse_qs(urlsplit(route.request.url).query)
        if params.get("q") != [suffix]:
            route.continue_()
            return
        cursor = params.get("cursor", [""])[0]
        pages.append(cursor)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            **payload, "items": payload["items"][1:] if cursor else payload["items"][:1],
            "nextCursor": "" if cursor else "next-page", "totalEstimate": 2,
        }))

    page.route("**/api/sessions/query?*", paginate)
    search.fill(suffix)
    expect(dialog.locator("button[data-index]")).to_have_count(1, timeout=15000)
    _tab_to(page, dialog.get_by_role("button", name="加载更多", exact=True))
    page.keyboard.press("Enter")
    expect(dialog.locator("button[data-index]")).to_have_count(2, timeout=15000)
    expect(dialog).to_be_visible()
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={initial}")
    assert pages == ["", "next-page"]
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])
