"""Real image uploads and retries; message transport never reaches a model."""
from __future__ import annotations

from collections import Counter
import json
import time
import urllib.parse

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.mock_llm.test_image_pipeline import (
    add_attachments,
    assert_chip_uploaded,
    build_png,
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
