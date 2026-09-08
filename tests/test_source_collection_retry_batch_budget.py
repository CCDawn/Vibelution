import pytest

from core.web.services.team_workflow.source_collection import stage_session


def _batch(key, *leads):
    return {"batchFingerprint": key, "leadFingerprints": list(leads), "newAcceptedLeadCount": len(leads)}


def test_retry_inherits_only_its_linked_batches_without_double_counting():
    first = {"taskId": "first", "sourceCollectionWritebackBatches": [_batch("b1", "doi:1")]}
    retry = {"taskId": "retry", "retrySourceTaskId": "first", "sourceCollectionWritebackBatches": [_batch("b1", "doi:1"), _batch("b2", "doi:2")]}
    unrelated = {"taskId": "other", "sourceCollectionWritebackBatches": [_batch("other", "doi:3")]}
    inherited = stage_session._source_collection_retry_writeback_batches(retry, [first, retry, unrelated])
    assert [item["batchFingerprint"] for item in inherited] == ["b1", "b2"]
    inherited[0]["leadFingerprints"].append("changed")
    assert first["sourceCollectionWritebackBatches"][0]["leadFingerprints"] == ["doi:1"]


def test_same_task_fresh_session_preserves_batches():
    task = {"taskId": "same", "retrySourceTaskId": "same", "sourceCollectionWritebackBatches": [_batch("b1", "doi:1")]}
    assert stage_session._source_collection_retry_writeback_batches(task, [task]) == task["sourceCollectionWritebackBatches"]


def test_retry_with_missing_budget_parent_cannot_reset_its_budget():
    with pytest.raises(ValueError, match="retry budget lineage"):
        stage_session._source_collection_retry_writeback_batches({"taskId": "retry", "retrySourceTaskId": "missing"}, [])


def test_retry_cannot_accept_more_leads_after_original_budget_is_spent():
    from core.web.services.team_workflow.source_collection.writeback_materialize import _enforce_source_collection_finding_writeback_batch_limits as enforce
    original = {"taskId": "first", "stageId": "finding", "agentRole": "source_finder", "writebackContract": {"searchEnvelope": {
        "maxLeadsPerWriteback": 1, "maxWritebackBatches": 1, "effectiveAcceptedLeadLimit": 1,
    }}}
    lead = {"title": "Known source", "locator": "https://example.test/1"}
    enforce(original, [lead])
    retry = {**original, "taskId": "retry", "sourceCollectionWritebackBatches": stage_session._source_collection_retry_writeback_batches(original, [original])}
    enforce(retry, [lead])
    assert len(retry["sourceCollectionWritebackBatches"]) == 1
    with pytest.raises(Exception, match="检索批次已达上限"):
        enforce(retry, [{"title": "New source", "locator": "https://example.test/2"}])
