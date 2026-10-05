import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.web.routes import financial_jobs
from core.web.services import financial_job_service as financial_jobs_facade
from core.web.services import financial_team_service
from core.web.services.financial_jobs import service as financial_jobs_impl
from core.web.services.financial_jobs.errors import (
    FinancialJobNotFoundError,
    FinancialJobStoreError,
)
from core.web.services.financial_jobs.store import FinancialResearchJobStore

ASSISTANT_ID = "finance-agent-http-test"
BATCH_ID = "4b1e9a2c-0e5c-4bb5-bd8f-82351a5784d3"


def _client():
    app = FastAPI()
    app.include_router(financial_jobs.router, prefix="/api")
    return TestClient(app)


def _batch(status="completed"):
    return {
        "batchId": BATCH_ID,
        "scheduleId": None,
        "assistantAgentId": ASSISTANT_ID,
        "status": status,
        "triggeredAt": "2026-10-06T12:00:00+08:00",
        "updatedAt": "2026-10-06T12:00:00+08:00",
        "researchDate": "2026-10-06",
        "periodDays": 30,
        "depth": "standard",
        "symbols": ["sh600000"],
        "terminalReason": None,
        "items": [
            {
                "symbol": "sh600000",
                "status": "completed",
                "runId": None,
                "startedAt": "2026-10-06T12:00:00+08:00",
                "completedAt": "2026-10-06T12:00:00+08:00",
                "terminalReason": None,
                "turnRefs": [],
            }
        ],
    }


def _daily_request(**overrides):
    payload = {
        "symbols": ["600000"],
        "periodDays": 30,
        "depth": "standard",
        "execution": {
            "kind": "daily",
            "timezone": "Asia/Shanghai",
            "timeOfDay": "18:00",
        },
    }
    payload.update(overrides)
    return payload


def test_financial_job_http_error_maps_team_errors_without_facade_attribute_lookup():
    missing = financial_jobs._http_error(
        financial_team_service.FinancialTeamNotFoundError("missing team")
    )
    conflict = financial_jobs._http_error(
        financial_team_service.FinancialTeamRunNotReadyError("not ready")
    )
    job_missing = financial_jobs._http_error(FinancialJobNotFoundError("missing job"))

    assert isinstance(missing, HTTPException)
    assert missing.status_code == 404
    assert conflict.status_code == 409
    assert job_missing.status_code == 404


def test_http_create_get_and_patch_use_private_schedule_service_without_get_provision(
    tmp_path, monkeypatch
):
    store = FinancialResearchJobStore(
        path_resolver=lambda owner: tmp_path / f"{owner}-jobs.json"
    )
    provision_calls = []
    monkeypatch.setattr(financial_jobs_impl, "default_store", lambda: store)
    monkeypatch.setattr(
        financial_team_service, "get_financial_team", lambda _assistant_id: {"teamId": "team"}
    )
    monkeypatch.setattr(
        financial_team_service,
        "provision_financial_team",
        lambda assistant_id: provision_calls.append(assistant_id),
    )
    client = _client()
    base = f"/api/financial-jobs/{ASSISTANT_ID}/schedules"

    first_get = client.get(base)
    assert first_get.status_code == 200
    assert first_get.json() == {"assistantAgentId": ASSISTANT_ID, "schedules": []}
    assert provision_calls == []

    created = client.post(
        base,
        headers={"Idempotency-Key": "http-create-schedule-key-01"},
        json=_daily_request(),
    )
    assert created.status_code == 200
    schedule = created.json()["schedule"]
    assert schedule["symbols"] == ["sh600000"]
    assert schedule["execution"]["timezone"] == "Asia/Shanghai"
    assert schedule["enabled"] is True
    assert schedule["nextRunAt"].endswith("+08:00")
    assert created.json()["batch"] is None
    assert provision_calls == [ASSISTANT_ID]

    paused = client.patch(
        f"{base}/{schedule['scheduleId']}", json={"enabled": False}
    )
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False
    assert paused.json()["nextRunAt"] is None

    after_patch = client.get(base)
    assert after_patch.status_code == 200
    assert after_patch.json()["schedules"][0]["enabled"] is False
    assert provision_calls == [ASSISTANT_ID]


@pytest.mark.parametrize(
    "payload,headers",
    [
        (_daily_request(symbols=["830001"]), {"Idempotency-Key": "http-invalid-stock-01"}),
        ({**_daily_request(), "prompt": "forbidden field"}, {"Idempotency-Key": "http-extra-field-01"}),
        (_daily_request(), {}),
    ],
)
def test_http_create_rejects_invalid_stock_extra_fields_and_missing_idempotency(
    payload, headers, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        financial_team_service, "get_financial_team", lambda _assistant_id: {"teamId": "team"}
    )
    monkeypatch.setattr(
        financial_jobs_impl,
        "default_store",
        lambda: FinancialResearchJobStore(
            path_resolver=lambda owner: tmp_path / f"{owner}-jobs.json"
        ),
    )
    response = _client().post(
        f"/api/financial-jobs/{ASSISTANT_ID}/schedules",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


def test_http_batch_get_stop_and_retry_map_to_service_results(monkeypatch):
    client = _client()
    base = f"/api/financial-jobs/{ASSISTANT_ID}/batches/{BATCH_ID}"
    monkeypatch.setattr(
        financial_jobs_facade,
        "get_financial_research_batch",
        lambda *_args: _batch("completed"),
    )
    monkeypatch.setattr(
        financial_jobs_facade,
        "stop_financial_research_batch",
        lambda *_args: _batch("stopped"),
    )
    monkeypatch.setattr(
        financial_jobs_facade,
        "retry_financial_research_batch",
        lambda *_args: _batch("partial"),
    )

    assert client.get(base).json()["status"] == "completed"
    assert client.post(f"{base}/stop").json()["status"] == "stopped"
    assert client.post(f"{base}/retry").json()["status"] == "partial"


def test_http_batch_errors_keep_404_409_and_safe_500_mapping(monkeypatch):
    client = _client()
    base = f"/api/financial-jobs/{ASSISTANT_ID}/batches/{BATCH_ID}"
    monkeypatch.setattr(
        financial_jobs_facade,
        "get_financial_research_batch",
        lambda *_args: (_ for _ in ()).throw(FinancialJobNotFoundError("missing batch")),
    )
    missing = client.get(base)
    assert missing.status_code == 404

    monkeypatch.setattr(
        financial_jobs_facade,
        "stop_financial_research_batch",
        lambda *_args: (_ for _ in ()).throw(
            financial_team_service.FinancialTeamConflictError("conflict")
        ),
    )
    conflict = client.post(f"{base}/stop")
    assert conflict.status_code == 409

    monkeypatch.setattr(
        financial_jobs_facade,
        "retry_financial_research_batch",
        lambda *_args: (_ for _ in ()).throw(FinancialJobStoreError("private storage error")),
    )
    failure = client.post(f"{base}/retry")
    assert failure.status_code == 500
    assert failure.json()["detail"] == "研究任务暂时无法安全读取"
