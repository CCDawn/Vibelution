"""Lifecycle, restart-readback and HTTP checks against a real temporary store."""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_reports import router
from core.web.services.agent_directory import episodic_memory
from core.web.services.financial_report import validation
from tests.test_financial_report_validation import AGENT_ID, harness, _create_due, _rows


def verified(harness, monkeypatch):
    record = _create_due(harness, monkeypatch)
    harness["now"] = datetime.fromisoformat("2024-10-14T04:00:00+00:00")
    monkeypatch.setattr(validation, "_fetch_fresh_cn_series", lambda _s: (
        _rows(("2024-10-09", 100), ("2024-10-11", 110)),
        "https://gu.qq.com/sh600519/gp", "2024-10-14T04:00:00+00:00", "series-hash",
    ))
    return validation.check_validation(AGENT_ID, record["id"])


def test_revision_revocation_and_consumed_retries(harness, monkeypatch):
    record = verified(harness, monkeypatch)
    original_request = str(uuid4())
    first = validation.save_lesson(AGENT_ID, record["id"], "核对现金流", original_request)
    revision_request = str(uuid4())
    revised = validation.revise_lesson(AGENT_ID, record["id"], "核对现金流与估值", revision_request, first["id"])
    assert revised["lesson"]["text"] == "核对现金流与估值"
    assert {v["state"] for v in revised["lessonHistory"]} == {"active", "superseded"}
    assert validation.revise_lesson(AGENT_ID, record["id"], "核对现金流与估值", revision_request, first["id"])["lesson"] == revised["lesson"]
    with pytest.raises(validation.FinancialValidationError) as stale:
        validation.revise_lesson(AGENT_ID, record["id"], "过期页面", str(uuid4()), first["id"])
    assert stale.value.status_code == 409
    harness["memoryEnabled"] = False
    revoke_request = str(uuid4())
    revoked = validation.revoke_lesson(AGENT_ID, record["id"], revoke_request, revised["lesson"]["id"])
    assert revoked["lesson"] is None and revoked["lessonState"] == "revoked"
    assert validation.revoke_lesson(AGENT_ID, record["id"], revoke_request, revised["lesson"]["id"])["lesson"] is None
    harness["memoryEnabled"] = True
    for call in (
        lambda: validation.save_lesson(AGENT_ID, record["id"], "核对现金流", original_request),
        lambda: validation.revise_lesson(AGENT_ID, record["id"], "核对现金流与估值", revision_request, first["id"]),
    ):
        with pytest.raises(validation.FinancialValidationError):
            call()
    assert validation.reflection_context(AGENT_ID, "sh600519", analysis_cutoff="2024-10-15") == []
    restored = validation.save_lesson(AGENT_ID, record["id"], "用户显式重新确认", str(uuid4()))
    assert restored["id"] != first["id"]
    assert len(validation.list_validations(AGENT_ID)["items"][0]["lessonHistory"]) == 3


def test_canonical_read_and_retry_survive_metadata_write_failure(harness, monkeypatch):
    record = verified(harness, monkeypatch)
    request = str(uuid4())
    writer = validation._write_store
    monkeypatch.setattr(validation, "_write_store", lambda *_a: (_ for _ in ()).throw(OSError("injected metadata failure")))
    with pytest.raises(OSError):
        validation.save_lesson(AGENT_ID, record["id"], "已提交的教训", request)
    monkeypatch.setattr(validation, "_write_store", writer)
    # Every read reloads the actual JSONL, as it would after a process restart.
    listed = validation.list_validations(AGENT_ID)["items"][0]
    assert listed["lesson"]["text"] == "已提交的教训"
    assert validation.reflection_context(AGENT_ID, "sh600519", analysis_cutoff="2024-10-14")[0]["id"] == listed["lesson"]["id"]
    replay = validation.save_lesson(AGENT_ID, record["id"], "已提交的教训", request)
    assert replay["id"] == listed["lesson"]["id"]
    assert len(episodic_memory.list_episodic_events(AGENT_ID, include_superseded=True)) == 1
    assert validation.reflection_context(AGENT_ID, "sz000001", analysis_cutoff="2024-10-14") == []
    assert validation.reflection_context(AGENT_ID, "sh600519", analysis_cutoff="2024-10-13") == []


def test_old_lessons_remain_visible_after_201_newer_notes(harness, monkeypatch):
    record = verified(harness, monkeypatch)
    request = str(uuid4())
    lesson = validation.save_lesson(AGENT_ID, record["id"], "旧教训仍可检索", request)
    harness["now"] = datetime.fromisoformat("2024-10-15T04:00:00+00:00")
    with episodic_memory.episodic_transaction(AGENT_ID) as tx:
        for i in range(201):
            tx.append(text=f"new note {i}")
    assert validation.list_validations(AGENT_ID)["items"][0]["lesson"]["id"] == lesson["id"]
    assert validation.reflection_context(AGENT_ID, "sh600519", analysis_cutoff="2024-10-15")[0]["id"] == lesson["id"]
    assert validation.save_lesson(AGENT_ID, record["id"], lesson["text"], request) == lesson
    assert len(episodic_memory.list_episodic_events(AGENT_ID)) == 202


def test_legacy_history_migrates_and_arbitrary_refs_cannot_claim_provenance(harness, monkeypatch):
    record = verified(harness, monkeypatch)
    request = str(uuid4())
    raw_input = "已确认的旧版教训\n\n  先核对来源"
    first = validation.save_lesson(AGENT_ID, record["id"], raw_input, request)
    path = harness["episodePath"]
    event = json.loads(path.read_text(encoding="utf-8"))
    event.pop("financialLesson")
    path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    store_path = validation._store_path(AGENT_ID)
    with validation._locked_store(store_path, AGENT_ID) as store:
        entry = validation._find_entry(store, record["id"])
        entry["record"]["lesson"] = first
        entry["lessonTextHash"] = hashlib.sha256(raw_input.encode()).hexdigest()
        entry["lessonClientRequestId"] = request
        validation._save_locked(store_path, store)
    assert validation.list_validations(AGENT_ID)["items"][0]["lesson"] == first
    assert validation.save_lesson(AGENT_ID, record["id"], raw_input, request) == first
    fake = episodic_memory.append_episodic_event(AGENT_ID, text="未确认记录不能冒充教训", refs=first["refs"][:-1])
    assert fake["episodeId"] not in {item["id"] for item in validation.reflection_context(AGENT_ID, "sh600519", analysis_cutoff="2024-10-15")}
    revised = validation.revise_lesson(AGENT_ID, record["id"], "旧版升级后的教训", str(uuid4()), first["id"])
    assert len(revised["lessonHistory"]) == 2
    assert {v["state"] for v in revised["lessonHistory"]} == {"active", "superseded"}


def test_check_and_feedback_use_current_canonical_lesson(harness, monkeypatch):
    record = verified(harness, monkeypatch)
    first = validation.save_lesson(AGENT_ID, record["id"], "复盘中的有效教训", str(uuid4()))
    assert validation.check_validation(AGENT_ID, record["id"])["lesson"] == first
    prompt = validation.feedback_prompt(AGENT_ID, record["id"])["text"]
    raw = prompt.split(validation._FEEDBACK_BEGIN + "\n", 1)[1].split("\n" + validation._FEEDBACK_END, 1)[0]
    assert json.loads(raw)["validation"]["lesson"]["id"] == first["id"]
    validation.revoke_lesson(AGENT_ID, record["id"], str(uuid4()), first["id"])
    assert validation.check_validation(AGENT_ID, record["id"])["lessonState"] == "revoked"


def test_real_http_lifecycle_rejects_stale_and_extra_payload(harness, monkeypatch):
    record = verified(harness, monkeypatch)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        url = f"/api/financial-reports/{AGENT_ID}/validations/{record['id']}/lesson"
        saved = client.post(url, json={"text": "HTTP确认", "clientRequestId": str(uuid4())})
        assert saved.status_code == 200
        payload = {"text": "HTTP修订", "expectedLessonId": saved.json()["id"], "clientRequestId": str(uuid4())}
        revised = client.patch(url, json=payload)
        assert revised.status_code == 200
        assert revised.json()["lessonState"] == "active"
        assert client.patch(url, json={**payload, "clientRequestId": str(uuid4())}).status_code == 409
        assert client.patch(url, json={**payload, "extra": "forbidden"}).status_code == 422
        harness["memoryEnabled"] = False
        deleted = client.request("DELETE", url, json={"expectedLessonId": revised.json()["lesson"]["id"], "clientRequestId": str(uuid4())})
        assert deleted.status_code == 200 and deleted.json()["lesson"] is None
        listed = client.get(f"/api/financial-reports/{AGENT_ID}/validations")
        assert listed.status_code == 200 and listed.json()["items"][0]["lessonState"] == "revoked"
