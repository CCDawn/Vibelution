"""Real image uploads and retries; message transport never reaches a model."""
from __future__ import annotations

from collections import Counter
import json
import time
import urllib.parse
import uuid

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.mock_llm.test_image_pipeline import (
    add_attachments,
    assert_chip_uploaded,
    build_png,
    tray_chip,
    wait_upload_failed_chip,
)
from tests.e2e.test_composer_drafts import COMPOSER, THREAD, _ready_composer

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


def test_failed_upload_withdraws_message_and_retries_only_failed_file(page, e2e_instance, tmp_path):
    from playwright.sync_api import expect

    sid = create_session(e2e_instance.port, title="mixed image upload recovery")
    composer = _ready_composer(page, e2e_instance, sid)
    good = tmp_path / "recovery-good.png"
    bad = tmp_path / "recovery-bad.png"
    good.write_bytes(build_png(rgb=(40, 160, 90)))
    bad.write_bytes(build_png(rgb=(180, 40, 40)))
    draft = "上传失败后需要保留的文字和两张图片"
    upload_pattern = f"**/api/sessions/{sid}/attachments"
    message_pattern = f"**/api/sessions/{sid}/messages"
    uploads = []
    uploaded = {}
    messages = []
    fail_bad = True

    def upload(route):
        request = route.request
        filename = urllib.parse.unquote(request.header_value("x-vibelution-filename") or "")
        if not filename:
            filename = request.post_data_json.get("filename", "")
        uploads.append(filename)
        if filename == bad.name and fail_bad:
            route.abort("internetdisconnected")
            return
        response = route.fetch()
        assert response.ok, f"Upload failed: HTTP {response.status}"
        uploaded[filename] = response.json()["artifactId"]
        route.fulfill(response=response)

    def block_message(route):
        messages.append(route.request.post_data_json)
        route.abort("internetdisconnected")

    page.route(upload_pattern, upload)
    page.route(message_pattern, block_message)
    try:
        add_attachments(page, [good, bad])
        composer.click()
        composer.press_sequentially(draft, delay=20)
        page.get_by_role("button", name="发送", exact=True).click()
        wait_upload_failed_chip(page, bad.name)
        assert_chip_uploaded(page, good.name)
        expect(composer).to_have_value(draft)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-status", "idle")
        assert not messages, "A mixed upload failure must not send a message"
        assert Counter(uploads) == {good.name: 1, bad.name: 1}
        good_artifact = uploaded[good.name]
        assert draft not in json.dumps(fetch_json(e2e_instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)

        fail_bad = False
        page.get_by_role("button", name=f"重试上传: {bad.name}", exact=True).click()
        assert_chip_uploaded(page, bad.name)
        expect(page.locator('[role="alert"]')).to_have_count(0)
        expect(composer).to_have_value(draft)
        assert not messages, "Retrying an attachment must not submit the draft"
        assert Counter(uploads) == {good.name: 1, bad.name: 2}
        assert uploaded[good.name] == good_artifact

        # Explicit resubmit reuses both real artifacts; block at the message
        # boundary so this test cannot invoke the operator's configured model.
        page.get_by_role("button", name="发送", exact=True).click()
        expect(page.locator('[role="alert"]').first).to_contain_text("没有发出", timeout=15000)
        assert len(messages) == 1
        assert messages[0]["content"] == draft
        assert set(messages[0]["attachmentIds"]) == set(uploaded.values())
        assert len(messages[0]["attachmentIds"]) == 2
        assert Counter(uploads) == {good.name: 1, bad.name: 2}
        expect(composer).to_have_value(draft)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        assert_chip_uploaded(page, good.name)
        assert_chip_uploaded(page, bad.name)
        assert draft not in json.dumps(fetch_json(e2e_instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)

        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(draft, timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
    finally:
        page.unroute(upload_pattern, upload)
        page.unroute(message_pattern, block_message)


def _assert_pending_upload_failure(page, instance, tmp_path, *, clear_draft=False, double_click=False):
    from playwright.sync_api import expect

    sid = create_session(instance.port, title="pending image upload recovery")
    composer = _ready_composer(page, instance, sid)
    image = tmp_path / "pending-upload.png"
    image.write_bytes(build_png())
    original = "上传等待期间的原始提交文字"
    newer = "上传等待时继续编辑的新文字"
    expected = original if double_click else ("" if clear_draft else newer)
    upload_pattern = f"**/api/sessions/{sid}/attachments"
    message_pattern = f"**/api/sessions/{sid}/messages"
    pending = []
    uploads = []
    messages = []

    def hold_upload(route):
        uploads.append(route.request.url)
        pending.append(route)

    def block_message(route):
        messages.append(route.request.url)
        route.abort("internetdisconnected")

    page.route(upload_pattern, hold_upload)
    page.route(message_pattern, block_message)
    try:
        add_attachments(page, [image])
        composer.fill(original)
        send = page.get_by_role("button", name="发送", exact=True)
        if double_click:
            send.dblclick()
        else:
            send.click()
        deadline = time.monotonic() + 10
        while not pending and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert len(uploads) == 1, "Only one image upload may be in flight"
        if not double_click:
            expect(composer).to_be_enabled()
            expect(composer).to_have_value("")
            composer.click()
            composer.press_sequentially(newer, delay=20)
            expect(composer).to_have_value(newer)
            if clear_draft:
                composer.press("ControlOrMeta+A")
                composer.press("Backspace")
                expect(composer).to_have_value("")

        pending.pop().abort("internetdisconnected")
        wait_upload_failed_chip(page, image.name)
        expect(composer).to_have_value(expected)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-status", "idle")
        assert len(uploads) == 1 and not messages
        assert original not in json.dumps(fetch_json(instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)

        page.reload(wait_until="domcontentloaded")
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        expect(page.locator(COMPOSER).first).to_have_value(expected, timeout=15000)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        rows = page.evaluate('() => JSON.parse(localStorage.getItem("vibelution.chat.drafts.v1") || "[]")')
        stored = {row.get("sessionId"): row.get("draft") for row in rows}
        assert stored.get(sid, "") == expected
    finally:
        for route in pending:
            route.abort("internetdisconnected")
        page.unroute(upload_pattern, hold_upload)
        page.unroute(message_pattern, block_message)


def test_pending_upload_failure_keeps_newer_text_after_reload(page, e2e_instance, tmp_path):
    _assert_pending_upload_failure(page, e2e_instance, tmp_path)


def test_pending_upload_failure_keeps_intentional_clear_after_reload(page, e2e_instance, tmp_path):
    _assert_pending_upload_failure(page, e2e_instance, tmp_path, clear_draft=True)


def test_double_click_with_pending_upload_does_not_duplicate_requests(page, e2e_instance, tmp_path):
    _assert_pending_upload_failure(page, e2e_instance, tmp_path, double_click=True)


def _assert_upload_completion_after_switch(page, instance, tmp_path, *, remove_pending=False):
    from playwright.sync_api import expect

    case_id = uuid.uuid4().hex[:8]
    title_a = f"等待上传 A {case_id}"
    title_b = f"独立编辑 B {case_id}"
    b = create_session(instance.port, title=title_b)
    a = create_session(instance.port, title=title_a)
    original = "会话 A 的图片提交文字"
    newer = "会话 B 的独立图片草稿"
    image_a = tmp_path / "session-a.png"
    image_b = tmp_path / "session-b.png"
    image_a.write_bytes(build_png(rgb=(180, 40, 40)))
    image_b.write_bytes(build_png(rgb=(40, 160, 90)))
    composer = _ready_composer(page, instance, a)
    pending = []
    uploads = []
    messages = []
    upload_pattern = "**/api/sessions/*/attachments"
    message_pattern = "**/api/sessions/*/messages"

    def hold_upload(route):
        uploads.append(route.request.url)
        pending.append(route)

    def block_message(route):
        messages.append({"url": route.request.url, "body": route.request.post_data_json})
        route.abort("internetdisconnected")

    def switch_session(title, sid):
        page.get_by_role("button").filter(has=page.get_by_text(title, exact=True)).first.click()
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", sid, timeout=30000)
        assert page.evaluate("() => window.__uploadIsolationDocument") == "same-document"
        return page.locator(COMPOSER).first

    def assert_preview_loaded(filename):
        preview = tray_chip(page, filename).locator("img").first
        expect(preview).to_be_visible()
        page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=preview.element_handle())
        # Names alone cannot detect a wrong preview URL. These solid-color
        # fixtures also verify the pixels still belong to the right file.
        rgb = preview.evaluate("img => { const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1; const ctx = canvas.getContext('2d'); ctx.drawImage(img, 0, 0, 1, 1); return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3); }")
        assert rgb == ([180, 40, 40] if filename == image_a.name else [40, 160, 90])

    page.evaluate("() => { window.__uploadIsolationDocument = 'same-document'; }")
    page.route(upload_pattern, hold_upload)
    page.route(message_pattern, block_message)
    try:
        add_attachments(page, [image_a])
        composer.fill(original)
        page.get_by_role("button", name="发送", exact=True).click()
        deadline = time.monotonic() + 10
        while not pending and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert len(uploads) == 1 and uploads[0].endswith(f"/api/sessions/{a}/attachments")
        if remove_pending:
            tray_chip(page, image_a.name).get_by_role("button", name="移除附件", exact=True).click()
            expect(tray_chip(page, image_a.name)).to_have_count(0)

        composer_b = switch_session(title_b, b)
        add_attachments(page, [image_b])
        composer_b.click()
        composer_b.press_sequentially(newer, delay=20)
        expect(composer_b).to_have_value(newer)
        assert_preview_loaded(image_b.name)

        route = pending.pop()
        response = route.fetch()
        assert response.ok, f"Upload failed: HTTP {response.status}"
        artifact_id = response.json()["artifactId"]
        route.fulfill(response=response)
        page.wait_for_function("({sid, draft}) => JSON.parse(localStorage.getItem('vibelution.chat.drafts.v1') || '[]').some(row => row.sessionId === sid && row.draft === draft)", arg={"sid": a, "draft": original})
        assert len(messages) == 1
        assert messages[0]["url"].endswith(f"/api/sessions/{a}/messages")
        assert messages[0]["body"]["content"] == original
        assert messages[0]["body"]["attachmentIds"] == ([] if remove_pending else [artifact_id])
        assert len(uploads) == 1, "B's unsent image must not be uploaded"
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-id", b)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0")
        expect(composer_b).to_have_value(newer)
        expect(tray_chip(page, image_a.name)).to_have_count(0)
        expect(tray_chip(page, image_b.name)).to_be_visible()
        assert_preview_loaded(image_b.name)
        expect(page.locator('[role="alert"]').filter(has_text="没有发出")).to_have_count(0)

        expect(switch_session(title_a, a)).to_have_value(original)
        expect(page.locator(THREAD).first).to_have_attribute("data-agent-thread-message-count", "0", timeout=15000)
        if remove_pending:
            expect(tray_chip(page, image_a.name)).to_have_count(0)
        else:
            assert_chip_uploaded(page, image_a.name)
            assert_preview_loaded(image_a.name)
        expect(tray_chip(page, image_b.name)).to_have_count(0)
        expect(switch_session(title_b, b)).to_have_value(newer)
        assert_preview_loaded(image_b.name)
        for sid in (a, b):
            detail = json.dumps(fetch_json(instance.port, f"/api/sessions/{sid}"), ensure_ascii=False)
            assert original not in detail and newer not in detail
    finally:
        for route in pending:
            route.abort("internetdisconnected")
        page.unroute(upload_pattern, hold_upload)
        page.unroute(message_pattern, block_message)


def test_upload_completion_keeps_original_session_and_attachment(page, e2e_instance, tmp_path):
    _assert_upload_completion_after_switch(page, e2e_instance, tmp_path)


def test_upload_completion_does_not_restore_removed_attachment_after_switch(page, e2e_instance, tmp_path):
    _assert_upload_completion_after_switch(page, e2e_instance, tmp_path, remove_pending=True)
