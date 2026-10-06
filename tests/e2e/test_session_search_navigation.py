"""Stale search results, in-flight pagination and browser history journeys."""
from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.api_write import _http_write_json, post_json
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_menu_journeys import no_model_submission  # noqa: F401
from tests.e2e.test_session_search_keyboard import _arrange

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
    evidence = common / "task-evidence" / "search-navigation-round9-oct06"
    evidence.mkdir(parents=True, exist_ok=True)
    proof = {"workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
             "port": e2e_instance.port, "head": head, "backend": backend,
             "serving": e2e_instance.health.get("serving")}
    (evidence / "runtime-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")


def _back_to_draft(page, instance, initial):
    from playwright.sync_api import expect

    page.go_back()
    expect(page).to_have_url(f"{instance.base_url}/chat?session={initial}")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", initial, timeout=15000)
    expect(page.locator(COMPOSER).first).to_have_value("搜索过程中保留草稿", timeout=15000)


@pytest.mark.parametrize("mutation", ["delete", "archive"])
def test_stale_result_cannot_offer_a_writable_session(page, e2e_instance, mutation):
    from playwright.sync_api import expect

    suffix, titles, sessions, initial, _, dialog, search = _arrange(page, e2e_instance)
    search.fill(suffix)
    results = dialog.locator("button[data-index]")
    expect(results).to_have_count(2, timeout=15000)
    target = sessions[next(i for i, title in enumerate(titles) if title in results.first.inner_text())]
    if mutation == "delete":
        _http_write_json("DELETE", e2e_instance.port, f"/api/sessions/{target}", None)
    else:
        post_json(e2e_instance.port, f"/api/sessions/{target}/archive")
        assert fetch_json(e2e_instance.port, f"/api/sessions/{target}")["readOnly"] is True
    try:
        results.first.click()
        expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={target}", timeout=15000)
        expect(dialog).not_to_be_visible()
        if mutation == "delete":
            expect(page.locator('[data-vui="state-surface"][data-tone="error"]')).to_be_visible(timeout=15000)
            expect(page.locator(COMPOSER)).to_have_count(0)
        else:
            expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", target, timeout=15000)
            composer = page.locator(COMPOSER)
            if composer.count():
                expect(composer.first).to_be_disabled()
            else:
                expect(page.get_by_text("只读", exact=False).first).to_be_visible()
        _ready_composer(page, e2e_instance, initial)
        expect(page.locator(COMPOSER).first).to_have_value("搜索过程中保留草稿")
        _assert_no_turns(e2e_instance, [initial, *[sid for sid in sessions if mutation != "delete" or sid != target]],
                         ["搜索过程中保留草稿"])
    finally:
        if mutation == "archive":
            post_json(e2e_instance.port, f"/api/sessions/{target}/unarchive")


def test_search_navigation_back_forward_keeps_each_draft(page, e2e_instance):
    from playwright.sync_api import expect

    suffix, titles, sessions, initial, _, dialog, search = _arrange(page, e2e_instance)
    search.press("Escape")
    # Thread switches replace the current history entry by contract. Keep the
    # original draft in an earlier browser entry before opening the search hit.
    _ready_composer(page, e2e_instance, sessions[1])
    page.get_by_role("button", name="全部会话", exact=True).click()
    search.fill(suffix)
    results = dialog.locator("button[data-index]")
    expect(results).to_have_count(2, timeout=15000)
    target = sessions[0]
    results.filter(has_text=titles[0]).click()
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", target, timeout=15000)
    composer = page.locator(COMPOSER).first
    expect(composer).to_have_value("")
    composer.press_sequentially("目标会话独立草稿", delay=2)
    _back_to_draft(page, e2e_instance, initial)
    page.go_forward()
    expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={target}")
    expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", target, timeout=15000)
    expect(composer).to_have_value("目标会话独立草稿", timeout=15000)
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿", "目标会话独立草稿"])


@pytest.mark.parametrize("change", ["query", "agent", "team"])
def test_pending_page_cannot_mix_into_changed_search(page, e2e_instance, change):
    from playwright.sync_api import expect

    suffix, _, sessions, initial, composer, dialog, search = _arrange(page, e2e_instance)
    payload = fetch_json(e2e_instance.port, f"/api/sessions/query?q={quote(suffix)}&limit=50")
    pending, calls = [], []
    new_query = f"新查询 {uuid.uuid4().hex[:8]}"

    def respond(route):
        params = parse_qs(urlsplit(route.request.url).query)
        if params.get("q") not in ([suffix], [new_query]):
            route.continue_()
            return
        calls.append(params)
        if params.get("cursor") == ["held-next-page"]:
            pending.append(route)
            return
        changed = params.get("q") == [new_query] or bool(params.get("agentId") or params.get("teamId"))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            **payload, "items": payload["items"][1:] if changed else payload["items"][:1],
            "nextCursor": "" if changed else "held-next-page", "totalEstimate": 1 if changed else 2,
        }))

    page.route("**/api/sessions/query?*", respond)
    search.fill(suffix)
    expect(dialog.locator("button[data-index]")).to_have_count(1, timeout=15000)
    more = dialog.get_by_role("button", name="加载更多", exact=True)
    with page.expect_request(lambda request: parse_qs(urlsplit(request.url).query).get("cursor") == ["held-next-page"]):
        more.click()
    loading = dialog.get_by_role("button", name="加载中…", exact=True)
    expect(loading).to_be_disabled()
    # Native disabled-button semantics reject a second activation.
    loading.evaluate("element => element.click()")
    if change == "query":
        search.fill(new_query)
    else:
        label = "按 Agent 过滤" if change == "agent" else "按团队过滤"
        dialog.get_by_role("combobox", name=label, exact=True).click()
        page.get_by_role("option").nth(1).click()
    expect(dialog.locator("button[data-index]")).to_have_count(1, timeout=15000)
    expect(dialog.locator("button[data-index]").first).to_contain_text(payload["items"][1]["title"])
    assert len(pending) == 1
    assert not calls[-1].get("cursor")
    pending[0].fulfill(status=200, content_type="application/json", body=json.dumps({
        **payload, "items": payload["items"][:1], "nextCursor": "", "totalEstimate": 2,
    }))
    page.wait_for_timeout(300)
    expect(dialog.locator("button[data-index]")).to_have_count(1)
    expect(dialog.locator("button[data-index]").first).to_contain_text(payload["items"][1]["title"])
    assert sum(params.get("cursor") == ["held-next-page"] for params in calls) == 1
    search.press("Escape")
    expect(composer).to_have_value("搜索过程中保留草稿")
    _assert_no_turns(e2e_instance, [initial, *sessions], ["搜索过程中保留草稿"])
