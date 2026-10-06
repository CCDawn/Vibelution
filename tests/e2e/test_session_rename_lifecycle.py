"""Rename responses must respect later lifecycle actions and user navigation."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import patch_json
from tests.e2e.helpers.instance_registry import InstanceRegistryError, fetch_json
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer
from tests.e2e.test_composer_navigation_journeys import _assert_no_turns, _switch
from tests.e2e.test_session_archive_races import _command, _show_archived
from tests.e2e.test_session_readonly_recovery import no_model_submission  # noqa: F401
from tests.e2e.test_session_rename_order import _save, _terminal
from tests.e2e.test_session_rename_races import _edit as _base_edit, _is_patch

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
    evidence = common / "task-evidence" / "rename-lifecycle-round15-oct07"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"runtime-proof-{head[:12]}.json").write_text(json.dumps({
        "workspaceRoot": str(root), "instanceId": e2e_instance.instance_id,
        "port": e2e_instance.port, "head": head, "backend": backend, "serving": serving,
        "testedWebTree": trees[0], "frontendSourceTree": trees[1],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _edit(page, title, replacement):
    try:
        return _base_edit(page, title, replacement)
    except Exception:
        common = Path(subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True,
        ).strip())
        evidence = common / "task-evidence" / "rename-lifecycle-round15-oct07"
        name = f"rename-surface-{uuid.uuid4().hex[:8]}"
        (evidence / f"{name}.json").write_text(json.dumps({
            "url": page.url, "expectedTitle": title,
            "tabs": page.get_by_role("tab").all_text_contents(),
            "threadSessionId": page.locator(THREAD).first.get_attribute("data-agent-thread-id"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        page.screenshot(path=str(evidence / f"{name}.png"))
        raise


def _hold_rename(page, instance, sid, succeeds):
    pending = []

    def hold(route):
        if route.request.method == "PATCH":
            body = patch_json(instance.port, f"/api/sessions/{sid}", route.request.post_data_json) if succeeds else {"detail": "late rename failed"}
            pending.append((route, body))
        else:
            route.continue_()

    page.route(f"**/api/sessions/{sid}", hold)
    return pending, hold


def _release(page, sid, pending, succeeds):
    assert len(pending) == 1
    route, body = pending.pop()
    with page.expect_request(_terminal(sid, "succeeded" if succeeds else "failed")):
        route.fulfill(status=200 if succeeds else 503, content_type="application/json", body=json.dumps(body))


@pytest.mark.parametrize("succeeds", [True, False], ids=["late-success", "late-failure"])
def test_rename_ack_after_archive_preserves_readonly_and_draft(page, e2e_instance, succeeds):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    original, renamed = f"改名后归档 {suffix}", f"归档前提交的新名称 {suffix}"
    sid = create_session(e2e_instance.port, title=original)
    draft = f"归档后仍保留的消息草稿 {suffix}"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    pending, hold = _hold_rename(page, e2e_instance, sid, succeeds)
    try:
        with page.expect_request(lambda request: _is_patch(request, sid)):
            _edit(page, original, renamed).press("Enter")
        _show_archived(page)
        _command(page, sid, renamed, True)
        expect(composer).to_be_disabled(timeout=15000)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["readOnly"] is True
        _release(page, sid, pending, succeeds)
        # An old successful DTO contains readOnly=false; it cannot undo archive.
        expect(composer).to_be_disabled()
        expect(composer).to_have_value(draft)
        expect(page).to_have_url(f"{e2e_instance.base_url}/chat?session={sid}")
        if not succeeds:
            editor = page.get_by_role("textbox", name="重命名会话", exact=True)
            if editor.is_visible():
                editor.press("Escape")
        expected = renamed if succeeds else original
        expect(page.get_by_role("tab").filter(has_text=expected)).to_be_visible()
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.locator(COMPOSER).first).to_be_disabled()
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        for route, _ in pending:
            route.abort()
        page.unroute(f"**/api/sessions/{sid}", hold)


@pytest.mark.parametrize("succeeds", [True, False], ids=["late-success", "late-failure"])
def test_rename_ack_after_delete_does_not_revive_editor_or_session(page, e2e_instance, succeeds):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    survivor_title = f"删除期间保留的会话 {suffix}"
    survivor = create_session(e2e_instance.port, title=survivor_title)
    original, renamed = f"待删除会话 {suffix}", f"待删除会话的新名称 {suffix}"
    sid = create_session(e2e_instance.port, title=original)
    _ready_composer(page, e2e_instance, sid)
    pending, hold = _hold_rename(page, e2e_instance, sid, succeeds)
    try:
        with page.expect_request(lambda request: _is_patch(request, sid)):
            _edit(page, original, renamed).press("Enter")
        page.get_by_role("button", name=f"移除会话记录 {renamed}", exact=True).click()
        with page.expect_response(lambda response: response.request.method == "DELETE" and response.url.endswith(f"/api/sessions/{sid}")) as removed:
            page.get_by_role("button", name=f"再次点击确认移除会话记录 {renamed}", exact=True).click()
        assert removed.value.ok
        draft = f"删除其他会话不能影响这段文字 {suffix}"
        composer = _switch(page, survivor_title, survivor)
        composer.press_sequentially(draft, delay=2)
        _release(page, sid, pending, succeeds)
        expect(page.get_by_role("textbox", name="重命名会话", exact=True)).not_to_be_visible()
        expect(page.get_by_role("button", name="在当前 Agent 下新建会话", exact=True)).to_be_visible()
        expect(page.get_by_role("tab").filter(has_text=renamed)).not_to_be_visible()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", survivor)
        expect(composer).to_have_value(draft)
        expect(page.get_by_text("late rename failed", exact=False)).not_to_be_visible()
        with pytest.raises(InstanceRegistryError, match="404"):
            fetch_json(e2e_instance.port, f"/api/sessions/{sid}")
        # A stale cached DTO cannot bypass a direct missing-session route.
        page.goto(f"{e2e_instance.base_url}/chat?session={sid}", wait_until="domcontentloaded")
        expect(page.locator('[data-vui="state-surface"][data-tone="error"]')).to_be_visible(timeout=15000)
        expect(page.locator(COMPOSER)).to_have_count(0)
        expect(_switch(page, survivor_title, survivor)).to_have_value(draft)
        _assert_no_turns(e2e_instance, [survivor], [draft])
    finally:
        for route, _ in pending:
            route.abort()
        page.unroute(f"**/api/sessions/{sid}", hold)


@pytest.mark.parametrize("latest_succeeds", [True, False], ids=["latest-success", "latest-failure"])
def test_three_renames_with_session_switch_keep_titles_and_drafts_independent(page, e2e_instance, latest_succeeds):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    title_a, title_b = f"快速改名 A {suffix}", f"快速改名 B {suffix}"
    a, b = [create_session(e2e_instance.port, title=title) for title in (title_a, title_b)]
    names = [f"A 的第 {index} 个名称 {suffix}" for index in range(1, 4)]
    draft_a, draft_b = f"A 的独立草稿 {suffix}", f"B 的独立草稿 {suffix}"
    _ready_composer(page, e2e_instance, a).press_sequentially(draft_a, delay=2)
    pending = {}

    def hold(route):
        if route.request.method == "PATCH":
            title = route.request.post_data_json["title"]
            succeeds = title == names[0] or title == names[2] and latest_succeeds
            body = patch_json(e2e_instance.port, f"/api/sessions/{a}", {"title": title}) if succeeds else {"detail": f"rename attempt {names.index(title) + 1} failed"}
            pending[title] = (route, body, succeeds)
        else:
            route.continue_()

    page.route(f"**/api/sessions/{a}", hold)
    try:
        with page.expect_request(lambda request: _is_patch(request, a)):
            _edit(page, title_a, names[0]).press("Enter")
        _switch(page, title_b, b).press_sequentially(draft_b, delay=2)
        renamed_b = f"B 的确认名称 {suffix}"
        assert _save(page, b, _edit(page, title_b, renamed_b))["title"] == renamed_b
        expect(_switch(page, title_a, a)).to_have_value(draft_a)
        for before, after in zip(names, names[1:]):
            with page.expect_request(lambda request: _is_patch(request, a)):
                _edit(page, before, after).press("Enter")
        assert len(pending) == 3
        for title in reversed(names):
            route, body, succeeds = pending.pop(title)
            with page.expect_request(_terminal(a, "succeeded" if succeeds else "failed")):
                route.fulfill(status=200 if succeeds else 503, content_type="application/json", body=json.dumps(body))
        editor = page.get_by_role("textbox", name="重命名会话", exact=True)
        if latest_succeeds:
            expect(editor).not_to_be_visible()
        else:
            expect(editor).to_have_value(names[2])
            expect(page.get_by_text("rename attempt 3 failed", exact=False).first).to_be_visible()
            editor.press("Escape")
        expected_a = names[2] if latest_succeeds else names[0]
        expect(page.get_by_role("tab").filter(has_text=expected_a)).to_be_visible()
        assert fetch_json(e2e_instance.port, f"/api/sessions/{a}")["title"] == expected_a
        assert fetch_json(e2e_instance.port, f"/api/sessions/{b}")["title"] == renamed_b
        expect(_switch(page, title_b, b)).to_have_value(draft_b)
        expect(page.get_by_role("tab").filter(has_text=renamed_b)).to_be_visible()
        expect(_switch(page, title_a, a)).to_have_value(draft_a)
        _assert_no_turns(e2e_instance, [a, b], [draft_a, draft_b])
    finally:
        for route, _, _ in pending.values():
            route.abort()
        page.unroute(f"**/api/sessions/{a}", hold)


@pytest.mark.parametrize("recovery", ["retry", "reload"])
def test_committed_rename_with_lost_response_recovers_to_server_truth(page, e2e_instance, recovery):
    from playwright.sync_api import expect

    suffix = uuid.uuid4().hex[:8]
    original, renamed = f"丢失响应原名 {suffix}", f"服务端已保存的名称 {suffix}"
    sid = create_session(e2e_instance.port, title=original)
    draft = f"断网后的消息草稿 {suffix}"
    composer = _ready_composer(page, e2e_instance, sid)
    composer.press_sequentially(draft, delay=2)
    committed = []

    def lose_response(route):
        if route.request.method == "PATCH":
            committed.append(patch_json(e2e_instance.port, f"/api/sessions/{sid}", route.request.post_data_json))
            route.abort("connectionreset")
        else:
            route.continue_()

    page.route(f"**/api/sessions/{sid}", lose_response)
    try:
        with page.expect_request(_terminal(sid, "failed")):
            _edit(page, original, renamed).press("Enter")
        assert len(committed) == 1 and committed[0]["title"] == renamed
        editor = page.get_by_role("textbox", name="重命名会话", exact=True)
        expect(editor).to_have_value(renamed)
        expect(composer).to_have_value(draft)
        assert fetch_json(e2e_instance.port, f"/api/sessions/{sid}")["title"] == renamed
        page.unroute(f"**/api/sessions/{sid}", lose_response)
        if recovery == "retry":
            assert _save(page, sid, editor)["title"] == renamed
            expect(editor).not_to_be_visible()
            expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.get_by_role("tab").filter(has_text=renamed)).to_be_visible()
        expect(page.locator(COMPOSER).first).to_have_value(draft)
        _assert_no_turns(e2e_instance, [sid], [draft])
    finally:
        page.unroute(f"**/api/sessions/{sid}", lose_response)
