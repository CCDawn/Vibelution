import json
import os
import threading
from datetime import datetime, timezone

import pytest

from core.runtime_manager import evolution_store, work_run_store
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


def test_work_run_store_records_partial_as_terminal_warning(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    events = []
    monkeypatch.setattr(
        work_run_store,
        "_record_work_run_event",
        lambda phase, event_code, **kwargs: events.append((phase, event_code, kwargs)),
    )

    store.persist_snapshot(
        "chat_room_round",
        {
            "runId": "round_partial",
            "runKind": "chat_room_round",
            "status": "partial",
            "currentPhase": "partial",
            "finishedAt": "2026-07-10T03:00:00Z",
        },
        active_run_id="round_partial",
    )

    assert store.load_active_snapshot("chat_room_round") is None
    assert store.load_latest_snapshot("chat_room_round")["status"] == "partial"
    assert events[-1][0:2] == ("state", "work_run.snapshot.persisted")
    assert events[-1][2]["status"] == "partial"
    assert events[-1][2]["level"] == "warning"
    assert events[-1][2]["lifecycle"] is True


def test_work_run_store_records_failed_snapshot_persistence_as_successful_io(
    tmp_path,
    monkeypatch,
):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    events = []
    monkeypatch.setattr(
        work_run_store,
        "_record_work_run_event",
        lambda phase, event_code, **kwargs: events.append((phase, event_code, kwargs)),
    )

    store.persist_snapshot(
        "self_evolution_autonomous_loop",
        {
            "runId": "self_failed",
            "runKind": "self_evolution_autonomous_loop",
            "status": "failed",
            "phase": "evolving_failed",
            "finishedAt": "2026-08-01T06:57:41Z",
            "error": {"type": "AutonomousLoopRuntimeError"},
        },
    )

    event = events[-1]
    assert event[0:2] == ("state", "work_run.snapshot.persisted")
    assert event[2]["status"] == "failed"
    assert event[2]["outcome"] == "succeeded"
    assert event[2]["level"] == "info"
    assert event[2]["lifecycle"] is True


def test_work_run_store_skips_identical_snapshot_write_and_event(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    writes = []
    events = []
    original_atomic_write_json = work_run_store._atomic_write_json

    def capture_write(path, payload):
        writes.append(path)
        original_atomic_write_json(path, payload)

    def capture_event(phase, event_code, **kwargs):
        events.append((phase, event_code, kwargs))

    monkeypatch.setattr(work_run_store, "_atomic_write_json", capture_write)
    monkeypatch.setattr(work_run_store, "_record_work_run_event", capture_event)

    snapshot = {
        "runId": "run_dedupe",
        "runKind": "chat_turn",
        "status": "running",
        "currentPhase": "running",
        "runtimeStatus": "running",
        "updatedAt": "2026-06-06T18:20:00Z",
    }

    store.persist_snapshot("chat_turn", snapshot, active_run_id="run_dedupe")
    store.persist_snapshot("chat_turn", snapshot, active_run_id="run_dedupe")

    assert writes == [
        store.runs_dir("chat_turn") / "run_dedupe.json",
        store.index_path("chat_turn"),
    ]
    assert [event[1] for event in events] == ["work_run.snapshot.persisted"]
    assert store.load_active_snapshot("chat_turn")["runId"] == "run_dedupe"
    assert store.load_latest_snapshot("chat_turn")["runId"] == "run_dedupe"


def test_work_run_store_repairs_index_for_existing_identical_snapshot(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    writes = []
    original_atomic_write_json = work_run_store._atomic_write_json

    def capture_write(path, payload):
        writes.append(path)
        original_atomic_write_json(path, payload)

    monkeypatch.setattr(work_run_store, "_atomic_write_json", capture_write)

    snapshot = {
        "runId": "run_index_repair",
        "runKind": "chat_turn",
        "status": "running",
    }
    snapshot_path = store.runs_dir("chat_turn") / "run_index_repair.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

    store.persist_snapshot("chat_turn", snapshot, active_run_id="run_index_repair")

    assert writes == [store.index_path("chat_turn")]
    assert store.load_run_index("chat_turn")["activeRunId"] == "run_index_repair"
    assert store.load_run_index("chat_turn")["latestRunId"] == "run_index_repair"


def test_work_run_store_lists_snapshots_for_kind(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    store.persist_snapshot("chat_turn", {"runId": "chat_1", "status": "completed"})
    store.persist_snapshot("chat_turn", {"runId": "chat_2", "status": "running"})
    store.persist_snapshot("self_evolution_run", {"runId": "self_1", "status": "running"})

    snapshots = store.list_snapshots("chat_turn")

    assert [item["runId"] for item in snapshots] == ["chat_1", "chat_2"]


def test_work_run_store_quarantines_nul_snapshot_and_falls_back_to_valid_latest(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat_ok",
            "status": "completed",
            "updatedAt": "2026-06-08T00:01:00Z",
        },
    )
    corrupt_path = store.runs_dir("chat_turn") / "chat_bad.json"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"\x00" * 128)
    store.save_run_index(
        "chat_turn",
        active_run_id="chat_bad",
        latest_run_id="chat_bad",
        recent_run_ids=["chat_bad", "chat_ok"],
        emit_event=False,
    )

    assert store.load_snapshot("chat_turn", "chat_bad") is None

    assert not corrupt_path.exists()
    quarantined = list(corrupt_path.parent.glob("chat_bad.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"\x00" * 128
    assert store.load_latest_snapshot("chat_turn")["runId"] == "chat_ok"
    assert [item["runId"] for item in store.list_snapshots("chat_turn")] == ["chat_ok"]


def test_work_run_store_quarantines_nul_index_and_rebuilds_on_next_persist(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    index_path = store.index_path("chat_turn")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"\x00" * 64)

    index = store.load_run_index("chat_turn")

    assert index["activeRunId"] == ""
    assert index["latestRunId"] == ""
    assert index["recentRunIds"] == []
    assert not index_path.exists()
    quarantined = list(index_path.parent.glob("index.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"\x00" * 64

    store.persist_snapshot("chat_turn", {"runId": "chat_rebuilt", "status": "running"}, active_run_id="chat_rebuilt")

    rebuilt = json.loads(index_path.read_text(encoding="utf-8"))
    assert rebuilt["activeRunId"] == "chat_rebuilt"
    assert rebuilt["latestRunId"] == "chat_rebuilt"
    assert rebuilt["recentRunIds"] == ["chat_rebuilt"]


def test_work_run_store_lists_recent_snapshots_from_index_without_full_scan(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    for index in range(5):
        store.persist_snapshot(
            "chat_turn",
            {
                "runId": f"chat_{index}",
                "status": "completed",
                "updatedAt": f"2026-06-08T00:0{index}:00Z",
            },
        )
    stale_path = store.runs_dir("chat_turn") / "chat_0.json"
    stale_path.unlink()
    scanned = []
    original_load_json = work_run_store._load_json

    def capture_load(path):
        scanned.append(path.name)
        return original_load_json(path)

    monkeypatch.setattr(work_run_store, "_load_json", capture_load)

    snapshots = store.list_snapshots("chat_turn", limit=3)

    assert [item["runId"] for item in snapshots] == ["chat_4", "chat_3", "chat_2"]
    assert set(scanned) <= {"index.json", "chat_4.json", "chat_3.json", "chat_2.json"}


def test_work_run_store_lists_lifecycle_candidates_without_loading_stale_history(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    runs_dir = store.runs_dir("chat_turn")
    runs_dir.mkdir(parents=True, exist_ok=True)
    fresh_at = datetime.now(timezone.utc).isoformat()
    snapshots = {
        "active_old": {"runId": "active_old", "runKind": "chat_turn", "status": "running", "updatedAt": "2020-01-01T00:00:00Z"},
        "recent_restored": {"runId": "recent_restored", "runKind": "chat_turn", "status": "running", "updatedAt": fresh_at},
        "parallel_fresh": {"runId": "parallel_fresh", "runKind": "chat_turn", "status": "running", "updatedAt": fresh_at},
        "history_stale": {"runId": "history_stale", "runKind": "chat_turn", "status": "running", "updatedAt": "2020-01-01T00:00:00Z"},
    }
    for run_id, payload in snapshots.items():
        (runs_dir / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    for run_id in ("active_old", "recent_restored", "history_stale"):
        os.utime(runs_dir / f"{run_id}.json", (1, 1))
    store.save_run_index(
        "chat_turn",
        active_run_id="active_old",
        latest_run_id="recent_restored",
        recent_run_ids=["recent_restored"],
        emit_event=False,
    )
    loaded = []
    original_load_json = work_run_store._load_json

    def capture_load(path):
        loaded.append(path.name)
        return original_load_json(path)

    monkeypatch.setattr(work_run_store, "_load_json", capture_load)

    candidates = store.list_lifecycle_candidate_snapshots("chat_turn")

    assert {item["runId"] for item in candidates} == {"active_old", "recent_restored", "parallel_fresh"}
    assert loaded.count("active_old.json") == 1
    assert "history_stale.json" not in loaded


def test_work_run_store_lifecycle_candidate_scan_propagates_directory_errors(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    store.ensure_kind_dirs("chat_turn")
    monkeypatch.setattr(work_run_store.os, "scandir", lambda _path: (_ for _ in ()).throw(PermissionError("locked")))

    with pytest.raises(PermissionError, match="locked"):
        store.list_lifecycle_candidate_snapshots("chat_turn")


def test_work_run_store_repairs_recent_index_for_existing_identical_snapshot(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")
    snapshot = {
        "runId": "chat_recent_repair",
        "runKind": "chat_turn",
        "status": "completed",
        "updatedAt": "2026-06-08T00:00:00Z",
    }
    snapshot_path = store.runs_dir("chat_turn") / "chat_recent_repair.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    store.index_path("chat_turn").write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-06-08T00:00:00Z",
                "activeRunId": "",
                "latestRunId": "chat_recent_repair",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store.persist_snapshot("chat_turn", snapshot)

    assert store.load_run_index("chat_turn")["recentRunIds"] == ["chat_recent_repair"]


def test_work_run_store_delete_snapshot_removes_recent_run_id(tmp_path):
    store = WorkRunStore(root=tmp_path / ".runtime" / "work_runs")

    store.persist_snapshot("chat_turn", {"runId": "chat_1", "status": "completed", "updatedAt": "2026-06-08T00:01:00Z"})
    store.persist_snapshot("chat_turn", {"runId": "chat_2", "status": "completed", "updatedAt": "2026-06-08T00:02:00Z"})

    store.delete_snapshot("chat_turn", "chat_2")

    index = store.load_run_index("chat_turn")
    assert index["latestRunId"] == "chat_1"
    assert index["recentRunIds"] == ["chat_1"]


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


def test_evolution_store_delegates_to_work_run_store(tmp_path, monkeypatch):
    store = work_run_store.WorkRunStore(root=tmp_path / "evolution")
    monkeypatch.setattr(evolution_store, "_WORK_RUN_STORE", store)

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
    assert json.loads((tmp_path / "evolution" / "supervised" / "runs" / "supervised_1.json").read_text(encoding="utf-8"))["status"] == "queued"
    assert evolution_store.load_active_run_snapshot("supervised")["runId"] == "supervised_1"
    assert evolution_store.load_latest_run_snapshot("supervised")["runId"] == "supervised_1"


def _running_snapshot(run_id: str) -> dict:
    return {"runId": run_id, "runKind": "source_collection_run", "status": "running", "currentPhase": "running"}


def _terminal_snapshot(run_id: str) -> dict:
    return {
        "runId": run_id,
        "runKind": "source_collection_run",
        "status": "completed",
        "currentPhase": "completed",
        "finishedAt": "2026-09-01T00:00:00Z",
    }


def test_work_run_store_terminal_persist_keeps_other_run_active(tmp_path):
    store = WorkRunStore(root=tmp_path / "work_runs")
    kind = "source_collection_run"

    store.persist_snapshot(kind, _running_snapshot("run_a"), active_run_id="run_a")
    store.persist_snapshot(kind, _running_snapshot("run_b"), active_run_id="run_b")

    assert store.load_active_run_ids(kind) == ["run_a", "run_b"]

    # Run A finishes and persists its terminal state with the legacy
    # ``active_run_id=""`` form; run B must keep its active mark.
    store.persist_snapshot(kind, _terminal_snapshot("run_a"), active_run_id="")

    assert store.load_active_run_ids(kind) == ["run_b"]
    assert store.load_active_snapshot(kind)["runId"] == "run_b"
    assert store.load_active_snapshot_for_run(kind, "run_a") is None
    assert store.load_active_snapshot_for_run(kind, "run_b")["runId"] == "run_b"
    index = store.load_run_index(kind)
    assert index["activeRunId"] == "run_b"
    assert index["activeRunIds"] == ["run_b"]


def test_work_run_store_active_set_converges_after_all_runs_finish(tmp_path):
    store = WorkRunStore(root=tmp_path / "work_runs")
    kind = "source_collection_run"

    store.persist_snapshot(kind, _running_snapshot("run_a"), active_run_id="run_a")
    store.persist_snapshot(kind, _running_snapshot("run_b"), active_run_id="run_b")
    store.persist_snapshot(kind, _terminal_snapshot("run_a"), active_run_id="")
    store.persist_snapshot(kind, _terminal_snapshot("run_b"), active_run_id="run_b")

    assert store.load_active_run_ids(kind) == []
    assert store.load_active_snapshot(kind) is None
    assert store.load_active_snapshots(kind) == []
    index = store.load_run_index(kind)
    assert index["activeRunId"] == ""
    assert index["activeRunIds"] == []
    # Latest projection still resolves after convergence.
    assert store.load_latest_snapshot(kind)["runId"] == "run_b"


def test_work_run_store_concurrent_persist_keeps_both_active_marks(tmp_path):
    store = WorkRunStore(root=tmp_path / "work_runs")
    kind = "source_collection_run"
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def persist(run_id: str) -> None:
        try:
            barrier.wait(timeout=10)
            store.persist_snapshot(kind, _running_snapshot(run_id), active_run_id=run_id)
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            errors.append(exc)

    threads = [threading.Thread(target=persist, args=(run_id,)) for run_id in ("run_a", "run_b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(store.load_active_run_ids(kind)) == ["run_a", "run_b"]
    assert store.load_active_snapshot_for_run(kind, "run_a") is not None
    assert store.load_active_snapshot_for_run(kind, "run_b") is not None
    assert store.load_snapshot(kind, "run_a")["runId"] == "run_a"
    assert store.load_snapshot(kind, "run_b")["runId"] == "run_b"


def test_work_run_store_reads_legacy_single_active_field(tmp_path):
    store = WorkRunStore(root=tmp_path / "work_runs")
    kind = "source_collection_run"
    runs_dir = store.runs_dir(kind)
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "legacy_run.json").write_text(
        json.dumps({"runId": "legacy_run", "runKind": kind, "status": "running"}),
        encoding="utf-8",
    )
    store.index_path(kind).write_text(
        json.dumps(
            {
                "version": 1,
                "updatedAt": "2026-06-08T00:00:00Z",
                "activeRunId": "legacy_run",
                "latestRunId": "legacy_run",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Index has no ``activeRunIds`` field; readers must fall back to the
    # legacy single-value field without changing behavior.
    assert store.load_active_run_ids(kind) == ["legacy_run"]
    assert store.load_active_snapshot(kind)["runId"] == "legacy_run"
    assert store.load_active_snapshots(kind)[-1]["runId"] == "legacy_run"
    assert store.load_active_snapshot_for_run(kind, "legacy_run")["runId"] == "legacy_run"
    assert store.load_active_snapshot_for_run(kind, "other_run") is None

    # A legacy single-value save keeps defining the whole active set.
    store.save_run_index(kind, active_run_id="", latest_run_id="legacy_run", emit_event=False)
    assert store.load_active_run_ids(kind) == []
    assert store.load_active_snapshot(kind) is None


def test_work_run_store_list_lifecycle_candidates_include_all_active_runs(tmp_path):
    store = WorkRunStore(root=tmp_path / "work_runs")
    kind = "source_collection_run"

    store.persist_snapshot(kind, _running_snapshot("run_a"), active_run_id="run_a")
    store.persist_snapshot(kind, _running_snapshot("run_b"), active_run_id="run_b")

    candidates = {item["runId"] for item in store.list_lifecycle_candidate_snapshots(kind)}
    assert {"run_a", "run_b"} <= candidates
