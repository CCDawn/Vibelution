"""Search recovery and keyboard filter journeys without model submissions."""
from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_menu_journeys import no_model_submission  # noqa: F401
from tests.e2e.test_session_search_keyboard import _arrange, _tab_to

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
    evidence = common / "task-evidence" / "search-recovery-round8-oct06"
    evidence.mkdir(parents=True, exist_ok=True)
    proof = {"workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
             "port": e2e_instance.port, "head": head, "backend": backend,
             "serving": e2e_instance.health.get("serving")}
    (evidence / "runtime-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.parametrize("failure_stage", ["initial", "next-page"])
def test_search_failure_is_visible_and_retry_preserves_results_and_draft(page, e2e_instance, failure_stage):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, composer, dialog, search = _arrange(page, e2e_instance)
    payload = fetch_json(e2e_instance.port, f"/api/sessions/query?q={quote(suffix)}&limit=50")
    failed = []
    recovered = False

    def respond(route):
        params = parse_qs(urlsplit(route.request.url).query)
        if params.get("q") != [suffix]:
            route.continue_()
            return
        cursor = params.get("cursor", [""])[0]
        if not recovered and (failure_stage == "initial" or cursor):
            failed.append(cursor)
            route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "测试搜索请求失败"}))
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            **payload, "items": payload["items"][1:] if cursor else payload["items"][:1],
            "nextCursor": "" if cursor else "next-page", "totalEstimate": 2,
        }))

    page.route("**/api/sessions/query?*", respond)
    search.fill(suffix)
    results = dialog.locator("button[data-index]")
    if failure_stage == "next-page":
        expect(results).to_have_count(1, timeout=15000)
        dialog.get_by_role("button", name="加载更多", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("测试搜索请求失败", timeout=20000)
    expect(dialog.get_by_text("没有匹配的会话", exact=True)).not_to_be_visible()
    expect(results).to_have_count(0 if failure_stage == "initial" else 1)
    assert failed and set(failed) == ({""} if failure_stage == "initial" else {"next-page"})
    recovered = True
    dialog.get_by_role("button", name="重试", exact=True).click()
    expect(results).to_have_count(1 if failure_stage == "initial" else 2, timeout=15000)
    expect(dialog.get_by_role("alert")).not_to_be_visible()
    expect(search).to_have_value(suffix)
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={initial}")
    search.press("Escape")
    expect(composer).to_have_value("搜索过程中保留草稿")
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])


def test_browser_composition_confirm_does_not_open_a_session(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, titles, sessions, initial, _, dialog, search = _arrange(page, e2e_instance)
    search.fill(suffix)
    results = dialog.locator("button[data-index]")
    expect(results).to_have_count(2, timeout=15000)
    target = sessions[next(i for i, title in enumerate(titles) if title in results.first.inner_text())]
    search.focus()
    # Browser composition event contract; this does not operate a Windows IME candidate window.
    search.evaluate("""element => {
        element.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}));
        element.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true}));
        element.dispatchEvent(new CompositionEvent('compositionend', {bubbles: true, data: '中文'}));
    }""")
    expect(dialog).to_be_visible()
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={initial}")
    search.press("Enter")
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={target}", timeout=15000)
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])


def test_close_reopen_and_clear_keep_query_and_draft_consistent(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, composer, dialog, search = _arrange(page, e2e_instance)
    search.fill(suffix)
    expect(dialog.locator("button[data-index]")).to_have_count(2, timeout=15000)
    search.press("Escape")
    expect(composer).to_have_value("搜索过程中保留草稿")
    page.get_by_role("button", name="全部会话", exact=True).click()
    expect(search).to_have_value(suffix)
    expect(search).to_be_focused()
    expect(dialog.locator("button[data-index]")).to_have_count(2)
    search.fill(f"无结果 {uuid.uuid4().hex[:8]}")
    expect(dialog.get_by_text("没有匹配的会话", exact=True)).to_be_visible(timeout=15000)
    search.fill("")
    expect(dialog.locator("button[data-index]").first).to_be_visible(timeout=15000)
    expect(search).to_have_value("")
    search.press("Escape")
    expect(composer).to_have_value("搜索过程中保留草稿")
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])


def test_keyboard_agent_and_team_filter_changes_reset_the_page_cursor(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, _, dialog, search = _arrange(page, e2e_instance)
    payload = fetch_json(e2e_instance.port, f"/api/sessions/query?q={quote(suffix)}&limit=50")
    requests = []

    def respond(route):
        params = parse_qs(urlsplit(route.request.url).query)
        if params.get("q") != [suffix]:
            route.continue_()
            return
        requests.append(params)
        cursor = params.get("cursor", [""])[0]
        filtered = bool(params.get("agentId") or params.get("teamId"))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            **payload, "items": payload["items"][1:] if cursor else payload["items"][:1],
            "nextCursor": "" if cursor or filtered else "next-page", "totalEstimate": 1 if filtered else 2,
        }))

    page.route("**/api/sessions/query?*", respond)
    search.fill(suffix)
    expect(dialog.locator("button[data-index]")).to_have_count(1, timeout=15000)
    dialog.get_by_role("button", name="加载更多", exact=True).click()
    expect(dialog.locator("button[data-index]")).to_have_count(2)
    assert requests[-1].get("cursor") == ["next-page"]
    selected = []
    for label, field in [("按 Agent 过滤", "agentId"), ("按团队过滤", "teamId")]:
        trigger = dialog.get_by_role("combobox", name=label, exact=True)
        _tab_to(page, trigger)
        page.keyboard.press("ArrowDown")
        options = page.get_by_role("option")
        expect(options.nth(1)).to_be_visible(timeout=15000)
        name = options.nth(1).inner_text()
        with page.expect_response(lambda response: parse_qs(urlsplit(response.url).query).get(field)):
            options.nth(1).press("Enter")
        expect(trigger).to_contain_text(name)
        expect(dialog.locator("button[data-index]")).to_have_count(1, timeout=15000)
        assert requests[-1].get(field) and not requests[-1].get("cursor")
        if field == "teamId":
            assert requests[-1].get("agentId")
        selected.append((trigger, name))
    search.press("Escape")
    page.get_by_role("button", name="全部会话", exact=True).click()
    expect(search).to_have_value(suffix)
    for trigger, name in selected:
        expect(trigger).to_contain_text(name)
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])
