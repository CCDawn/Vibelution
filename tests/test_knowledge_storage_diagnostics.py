"""Read degradation remains observable without exposing knowledge contents."""

from pathlib import Path

from core.web.services import team_knowledge_service
from core.web.services.team_knowledge import store


def test_jsonl_diagnostics_count_corruption_and_reset_between_calls(tmp_path):
    path = tmp_path / "items.jsonl"
    path.write_text('{"id":"good"}\ninvalid-private-content\n[]\n', encoding="utf-8")
    with store.capture_jsonl_read_diagnostics() as diagnostics:
        assert store._read_jsonl(path) == [{"id": "good"}]
        assert diagnostics[str(path)] == {"corruptLineCount": 2, "readErrorCount": 0}
    with store.capture_jsonl_read_diagnostics() as fresh:
        assert fresh == {}
    assert path.read_text(encoding="utf-8").endswith("[]\n")


def test_jsonl_diagnostics_record_read_failure(tmp_path, monkeypatch):
    path = tmp_path / "items.jsonl"
    path.write_text('{"id":"good"}', encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError()))
    with store.capture_jsonl_read_diagnostics() as diagnostics:
        assert store._read_jsonl(path) == []
    assert diagnostics[str(path)] == {"corruptLineCount": 0, "readErrorCount": 1}


def test_operations_health_exposes_counts_without_raw_paths_or_contents(tmp_path, monkeypatch):
    path = tmp_path / "items.jsonl"
    path.write_text('{"id":"good"}\nprivate-invalid-input\n', encoding="utf-8")

    def compute(**kwargs):
        store._read_jsonl(path)
        store._read_jsonl(path)
        return {"summary": {"knowledgeBaseCount": 1}}

    monkeypatch.setattr(team_knowledge_service, "_compute_knowledge_operations_health", compute)
    payload = team_knowledge_service._build_knowledge_operations_health(agent_id="reader")
    assert payload["summary"]["corruptJsonlLineCount"] == 1
    assert payload["findings"][0]["findingType"] == "storage_read_degraded"
    assert payload["summary"]["findingCount"] == 1
    assert payload["storageHealth"] == {
        "status": "degraded", "corruptJsonlLineCount": 1, "readErrorCount": 0,
    }
    assert str(tmp_path) not in str(payload)
    assert "private-invalid-input" not in str(payload)
