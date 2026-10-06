"""Cold session entry and delayed create acknowledgements, without model turns."""
from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns, _switch
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


def _evidence(root):
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    target = common / "task-evidence" / "session-cold-round16-oct07"
    target.mkdir(parents=True, exist_ok=True)
    return target


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
    (_evidence(root) / f"runtime-proof-{head[:12]}.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend, "serving": serving,
        "testedWebTree": trees[0], "frontendSourceTree": trees[1],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot(page, instance, label, trace=None):
    name = f"{label}-{uuid.uuid4().hex[:8]}"
    target = _evidence(instance.project_root)
    (target / f"{name}.json").write_text(json.dumps({
        "url": page.url,
        "tabs": page.get_by_role("tab").all_text_contents(),
        "tabLabels": page.get_by_role("tab").evaluate_all("els => els.map(el => el.getAttribute('aria-label'))"),
        "threadSessionId": page.locator(THREAD).first.get_attribute("data-agent-thread-id") if page.locator(THREAD).count() else None,
        "network": trace or [],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    page.screenshot(path=str(target / f"{name}.png"))


@pytest.mark.parametrize("slow_catalog", [False, True], ids=["fresh-context", "detail-before-catalog"])
def test_cold_direct_session_entry_has_correct_tab_and_draft(page, e2e_instance, slow_catalog):
    from playwright.sync_api import expect

    title = f"冷启动标签 {uuid.uuid4().hex[:8]}"
    sid = create_session(e2e_instance.port, title=title)
    # The shared page fixture first opens home. Use a second, genuinely empty
    # browser context so neither home navigation nor cached catalogs warm Chat.
    context = page.context.browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    cold = context.new_page()
    pending, submissions = [], []
    trace = []
    started = time.monotonic()

    def record(kind, request, status=None):
        path = urlsplit(request.url).path
        if len(trace) < 100 and path.startswith("/api/") and "telemetry" not in path:
            trace.append({"kind": kind, "path": path, "method": request.method,
                          "status": status, "elapsedMs": round((time.monotonic() - started) * 1000)})

    cold.on("request", lambda request: record("request", request))
    cold.on("response", lambda response: record("response", response.request, response.status))
    cold.on("requestfailed", lambda request: record("failed", request))

    def transport(route):
        path = urlsplit(route.request.url).path
        if route.request.method == "POST" and any(path.endswith(ending) for ending in ("/messages", "/messages/edit-resubmit", "/guidance")):
            submissions.append(path)
            route.abort()
        elif slow_catalog and route.request.method == "GET" and path in {"/api/sessions/bootstrap", "/api/sessions/query", "/api/agents"}:
            pending.append(route)
        else:
            route.continue_()

    cold.route("**/api/**", transport)
    draft = f"冷启动未提交草稿 {uuid.uuid4().hex[:8]}"
    try:
        composer = _ready_composer(cold, e2e_instance, sid)
        expect(cold.get_by_role("tab").filter(has_text=title)).to_be_visible(timeout=10000)
        expect(cold.get_by_role("tab", selected=True)).to_contain_text(title)
        if slow_catalog:
            assert pending, "The catalog delay must actually intercept requests"
        composer.press_sequentially(draft, delay=2)
        slow_catalog = False
        for route in pending:
            route.fulfill(response=_fetch_route(route))
        pending.clear()
        expect(composer).to_have_value(draft)
        expect(cold.get_by_role("tab", selected=True)).to_contain_text(title)
        cold.reload(wait_until="domcontentloaded")
        expect(cold.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(cold.locator(COMPOSER).first).to_have_value(draft)
        expect(cold.get_by_role("tab", selected=True)).to_contain_text(title)
        _assert_no_turns(e2e_instance, [sid], [draft])
        assert submissions == []
    except Exception:
        _snapshot(cold, e2e_instance, "cold-entry-failure", trace)
        raise
    finally:
        for route in pending:
            route.abort()
        context.close()


def _create_settled(request):
    if request.method != "POST" or not request.url.endswith("/api/runtime/browser-telemetry"):
        return False
    payload = request.post_data_json or {}
    return payload.get("eventCode") == "browser.user_action.session_create_succeeded"


def _fetch_route(route):
    try:
        return route.fetch()
    except Exception:
        # Playwright transport errors include request headers. Never persist
        # the control token when the injected delay or context is interrupted.
        raise AssertionError("Delayed request could not be fetched") from None


@pytest.mark.parametrize("leave_before_ack", [False, True], ids=["stay-on-temp", "switch-agent-before-ack"])
def test_delayed_create_preserves_typed_draft_and_current_route(page, e2e_instance, leave_before_ack):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    title_a, title_b = f"新建来源 A {suffix}", f"切换目标 B {suffix}"
    a, b = [create_session(e2e_instance.port, title=title) for title in (title_a, title_b)]
    _ready_composer(page, e2e_instance, a)
    pending = []

    def hold_create(route):
        if route.request.method == "POST":
            pending.append(route)
        else:
            route.continue_()

    page.route("**/api/sessions", hold_create)
    created_draft, other_draft = f"新会话保存前输入 {suffix}", f"另一个 Agent 的草稿 {suffix}"
    try:
        with page.expect_request(lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/sessions"):
            page.get_by_role("button", name="在当前 Agent 下新建会话", exact=True).click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", re.compile(r"temp-session-"))
        temp_id = page.locator(THREAD).first.get_attribute("data-agent-thread-id")
        composer = page.locator(COMPOSER).first
        expect(composer).to_be_enabled()
        composer.press_sequentially(created_draft, delay=2)
        if leave_before_ack:
            _switch(page, title_b, b).press_sequentially(other_draft, delay=2)
        assert len(pending) == 1
        route = pending.pop()
        response = _fetch_route(route)
        assert response.ok
        body = response.json()
        real_id = body["id"]
        with page.expect_request(_create_settled):
            route.fulfill(response=response)
        if leave_before_ack:
            expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={b}")
            expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", b)
            expect(page.locator(COMPOSER).first).to_have_value(other_draft)
            # The current Agent's tabs must remain B's after A's response.
            expect(page.get_by_role("tab", selected=True)).to_contain_text(title_b)
            # Clicking the Agent returns to its last-viewed create shell,
            # whose remembered identity must now be the real session.
            page.get_by_role("button").filter(has=page.get_by_text(title_a, exact=True)).first.click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_id)
        expect(page.locator(COMPOSER).first).to_have_value(created_draft)
        assert temp_id not in page.url
        expect(page.get_by_role("tab", selected=True)).to_contain_text(body["title"])
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_id, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(created_draft)
        expect(_switch(page, title_b, b)).to_have_value(other_draft if leave_before_ack else "")
        _assert_no_turns(e2e_instance, [a, b, real_id], [created_draft, other_draft])
        assert fetch_json(e2e_instance.port, f"/api/sessions/{real_id}")["agentId"] == body["agentId"]
    except Exception:
        _snapshot(page, e2e_instance, "create-ack-failure")
        raise
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions", hold_create)
