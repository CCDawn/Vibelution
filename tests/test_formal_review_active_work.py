import pytest
from core.runtime_manager import formal_review_work as work
from core.runtime_manager.work_run_store import WorkRunStore


def test_parallel_review_activity_and_terminal_cleanup(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path)
    monkeypatch.setattr(work, "_store", lambda: store)
    context = {"invocationId": "review:a", "questionStageBinding": {"workflowRunId": "real-run"}}
    with work.active_formal_review(context, purpose="reflection"):
        assert work.summary()["active"]["workflowRunId"] == "real-run"
        with work.active_formal_review({**context, "invocationId": "review:b"}, purpose="reflection"):
            assert len(work.summary()["activeItems"]) == 2
        assert len(work.summary()["activeItems"]) == 1
    assert work.summary()["activeItems"] == []
    assert work.summary()["latest"]["status"] == "completed"


def test_failed_review_releases_active_and_dead_process_is_not_active(tmp_path, monkeypatch):
    store = WorkRunStore(root=tmp_path)
    monkeypatch.setattr(work, "_store", lambda: store)
    with pytest.raises(RuntimeError):
        with work.active_formal_review({"invocationId": "review:x"}, purpose="reflection"):
            raise RuntimeError("provider failed")
    assert work.summary()["activeItems"] == []
    assert work.summary()["latest"]["status"] == "failed"
    assert work.is_live({"ownerPid": -1, "ownerCreateTime": 0}) is False
