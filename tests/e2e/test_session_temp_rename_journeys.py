"""Renaming a not-yet-created session tab must stick, including after a rejected create."""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns
from tests.e2e.test_session_cold_create_journeys import _create_settled, _fetch_route
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401
from tests.e2e.test_session_reload_recovery_journeys import (
    _create_event, _hold_creates, _start_create,
)

pytestmark = [pytest.mark.serial, pytest.mark.skipif(
    not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
)]


def _evidence(root):
    common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True,
    ).strip())
    target = common / "task-evidence" / "session-temp-rename-round21"
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture(scope="module", autouse=True)
def runtime_identity(e2e_instance):
    root = e2e_instance.project_root
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    backend = e2e_instance.health.get("backendCodeFingerprint") or {}
    serving = e2e_instance.health.get("serving") or {}
    assert backend.get("head") == head and backend.get("dirty") is False
    frontend_head = (serving.get("frontend") or {}).get("builtFromCommit")
    assert frontend_head
    trees = [subprocess.check_output(["git", "rev-parse", f"{commit}:web"], cwd=root, text=True).strip()
             for commit in (head, frontend_head)]
    assert trees[0] == trees[1]
    (_evidence(root) / f"runtime-proof-{head[:12]}.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend, "serving": serving,
        "testedWebTree": trees[0], "frontendSourceTree": trees[1],
    }, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def test_temp_session_rename_survives_rejected_create_and_is_saved(page, e2e_instance):
    from playwright.sync_api import expect

    source = create_session(e2e_instance.port, title=f"临时改名来源 {uuid.uuid4().hex[:8]}")
    _ready_composer(page, e2e_instance, source)
    pending = []
    hold = _hold_creates(page, pending)
    renamed = f"临时名{uuid.uuid4().hex[:6]}"
    draft = f"临时改名时保留的草稿 {renamed}"
    try:
        temp = _start_create(page, pending)
        page.locator(COMPOSER).first.press_sequentially(draft, delay=2)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        tab = page.locator(f'[id="agent-session-tab-session-{temp}"]')
        tab.click(button="right")
        page.get_by_role("menuitem", name="重命名会话", exact=True).click()
        editor = page.get_by_role("textbox", name="重命名会话", exact=True)
        expect(editor).to_be_focused()
        editor.fill(renamed)
        editor.press("Enter")
        expect(page.get_by_role("textbox", name="重命名会话", exact=True)).to_have_count(0)
        expect(tab).to_contain_text(renamed)
        expect(page.locator(COMPOSER).first).to_have_value(draft)

        rejected = pending.pop()
        with page.expect_request(lambda request: _create_event(request, "failed")):
            rejected.fulfill(status=409, content_type="application/json", body='{"detail":"受控创建拒绝"}')
        expect(page.get_by_role("textbox", name="重命名会话", exact=True)).to_have_count(0)
        expect(tab).to_contain_text(renamed)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", temp, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(draft, timeout=15000)
        expect(tab).to_contain_text(renamed)
        renamed = f"临时名{uuid.uuid4().hex[:6]}"
        tab.click(button="right")
        page.get_by_role("menuitem", name="重命名会话", exact=True).click()
        editor = page.get_by_role("textbox", name="重命名会话", exact=True)
        editor.fill(renamed)
        editor.press("Enter")
        expect(page.get_by_role("textbox", name="重命名会话", exact=True)).to_have_count(0)
        expect(tab).to_contain_text(renamed)
        assert _start_create(page, pending) == temp
        pending.pop().abort()
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", temp, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(draft, timeout=15000)
        expect(tab).to_contain_text(renamed)

        assert _start_create(page, pending) == temp
        retry = pending.pop()
        response = _fetch_route(retry)
        assert response.ok
        real_id = response.json()["id"]
        with page.expect_response(
            lambda saved: saved.request.method == "PATCH" and saved.url.endswith(f"/api/sessions/{real_id}"),
            timeout=15000,
        ) as saved, page.expect_request(_create_settled):
            retry.fulfill(response=response)
        assert saved.value.ok
        assert saved.value.json()["title"] == renamed
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", real_id)
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        expect(page.locator(f'[id="agent-session-tab-session-{temp}"]')).to_have_count(0)
        expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
        expect(page.get_by_text(re.compile("新建会话失败"))).to_have_count(0)
        _assert_no_turns(e2e_instance, [source, real_id], [draft])
    finally:
        for route in pending:
            route.abort()
        page.unroute("**/api/sessions", hold)
