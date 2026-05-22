import json

import pytest

from core.runtime_manager import evolution_store
from core.runtime_manager.work_run_store import WorkRunStore, normalize_run_id, normalize_run_kind


def test_work_run_store_tracks_active_and_latest_per_kind(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    chat = {"runId": "chat_1", "runKind": "chat_turn", "status": "running"}
    self_run = {"runId": "self_1", "runKind": "self_evolution_run", "status": "running"}

    store.persist_snapshot("chat_turn", chat, active_run_id="chat_1")
    store.persist_snapshot("self_evolution_run", self_run, active_run_id="self_1")

    assert store.load_active_snapshot("chat_turn")["runId"] == "chat_1"
    assert store.load_active_snapshot("self_evolution_run")["runId"] == "self_1"
    assert store.load_latest_snapshot("chat_turn")["status"] == "running"


def test_work_run_store_rejects_unsafe_kind_and_run_id(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    with pytest.raises(ValueError, match="Invalid work run kind"):
        normalize_run_kind("../bad")

    with pytest.raises(ValueError, match="Invalid work run kind"):
        normalize_run_kind("bad:kind")

    with pytest.raises(ValueError, match="missing runId"):
        store.persist_snapshot("chat_turn", {"status": "running"})

    assert store.load_snapshot("chat_turn", "../bad") is None


def test_work_run_store_rejects_filesystem_unsafe_run_kind_before_persisting(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    with pytest.raises(ValueError, match="Invalid work run kind"):
        store.persist_snapshot("bad:kind", {"runId": "run_ok", "status": "running"})

    assert not (tmp_path / ".runtime" / "work_runs").exists()


def test_work_run_store_rejects_colon_run_ids_without_persisting(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    for run_id in ("C:inside", "run:stream"):
        with pytest.raises(ValueError, match="Invalid work run id"):
            normalize_run_id(run_id)

    with pytest.raises(ValueError, match="Invalid work run id"):
        store.persist_snapshot(
            "chat_turn",
            {
                "runId": "C:inside",
                "runKind": "chat_turn",
                "status": "running",
            },
            active_run_id="C:inside",
        )

    runs_dir = tmp_path / ".runtime" / "work_runs" / "chat_turn" / "runs"
    assert not (runs_dir / "inside.json").exists()
    assert not (runs_dir / "C:inside.json").exists()


@pytest.mark.parametrize("run_id", ("run*bad", "run?bad", "run<bad", "run>bad", 'run"bad', "run|bad"))
def test_work_run_store_rejects_filesystem_unsafe_run_ids_without_persisting(tmp_path, run_id):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    with pytest.raises(ValueError, match="Invalid work run id"):
        normalize_run_id(run_id)

    with pytest.raises(ValueError, match="Invalid work run id"):
        store.persist_snapshot(
            "chat_turn",
            {
                "runId": run_id,
                "runKind": "chat_turn",
                "status": "running",
            },
            active_run_id=run_id,
        )

    assert not (tmp_path / ".runtime" / "work_runs" / "chat_turn").exists()


def test_work_run_store_records_rejected_run_id_failures(tmp_path, monkeypatch):
    from core.web.services import runtime_scene_service

    events = []

    def capture_event(component, phase, event_code, **kwargs):
        events.append((component, phase, event_code, kwargs))

    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", capture_event)

    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    with pytest.raises(ValueError, match="missing runId"):
        store.persist_snapshot("chat_turn", {"status": "queued"})

    with pytest.raises(ValueError, match="Invalid work run id"):
        store.persist_snapshot(
            "chat_turn",
            {
                "runId": "run:stream",
                "runKind": "chat_turn",
                "status": "running",
            },
        )

    assert events == [
        (
            "work_run",
            "state",
            "work_run.snapshot.rejected",
            {
                "message": "Work run snapshot rejected: missing runId.",
                "level": "warning",
                "outcome": "rejected",
                "fields": {
                    "runKind": "chat_turn",
                    "runId": "",
                    "status": "queued",
                    "reason": "missing_run_id",
                },
                "lifecycle": True,
            },
        ),
        (
            "work_run",
            "state",
            "work_run.snapshot.rejected",
            {
                "message": "Work run snapshot rejected: invalid runId.",
                "level": "warning",
                "outcome": "rejected",
                "fields": {
                    "runKind": "chat_turn",
                    "runId": "run:stream",
                    "status": "running",
                    "reason": "invalid_run_id",
                },
                "lifecycle": True,
            },
        )
    ]


def test_evolution_store_delegates_through_legacy_paths(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)

    payload = evolution_store.persist_run_snapshot(
        "supervised",
        {
            "runId": "supervised_1",
            "status": "queued",
            "startedAt": "2026-05-21T00:00:00Z",
            "updatedAt": "2026-05-21T00:00:00Z",
        },
        active_run_id="supervised_1",
    )

    assert payload["runId"] == "supervised_1"
    assert json.loads((runs_dir / "supervised_1.json").read_text(encoding="utf-8"))["status"] == "queued"
    assert evolution_store.load_active_run_snapshot("supervised")["runId"] == "supervised_1"
    assert evolution_store.load_latest_run_snapshot("supervised")["runId"] == "supervised_1"
