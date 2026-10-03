"""Governed revisions and source validity must remain consistent on every read."""

import hashlib
import os

import pytest

from core.web.services import team_knowledge_service as knowledge
from core.web.services.team_knowledge import lifecycle
from core.web.services.team_knowledge import governance
from tests.test_team_knowledge_service import (
    _create_central_source_artifact,
    isolate_developer_sandbox_config,
    knowledge_env,
)


def _item(env):
    source = _create_central_source_artifact(
        env["base"]["knowledgeBaseId"], owner_type="team", owner_id=env["team"]["teamId"],
        actor_agent_id=env["member"]["agentId"], reviewer_agent_id=env["lead"]["agentId"],
    )
    proposal = knowledge.create_refinement_proposal(
        env["base"]["knowledgeBaseId"], source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=env["member"]["agentId"], title="Shipping policy",
        content="Delivery takes 23 days.",
    )
    item = knowledge.review_refinement_proposal(
        env["base"]["knowledgeBaseId"], proposal["proposalId"], status="applied",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]
    return item, source


def test_revision_records_parent_hash_and_rejects_stale_target(knowledge_env):
    env = knowledge_env
    item, _ = _item(env)
    owner, base = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    expected = hashlib.sha256(item["content"].encode()).hexdigest()
    fields = lifecycle.prepare_revision_fields(
        owner, base, item["knowledgeItemId"], expected_content_sha256=expected, reason="Correct delivery time",
    )
    assert fields["revision"] == 2
    assert fields["rootKnowledgeItemId"] == item["knowledgeItemId"]
    with pytest.raises(knowledge.TeamKnowledgeError, match="changed"):
        lifecycle.prepare_revision_fields(
            owner, base, item["knowledgeItemId"], expected_content_sha256="0" * 64, reason="Correction",
        )


def test_superseded_version_does_not_resurrect_when_replacement_is_withdrawn():
    old = {"knowledgeItemId": "old", "knowledgeBaseId": "kb", "sourceArtifactIds": ["source-a"]}
    new = {
        "knowledgeItemId": "new", "knowledgeBaseId": "kb", "sourceArtifactIds": ["source-b"],
        "supersedesKnowledgeItemId": "old", "rootKnowledgeItemId": "old", "revision": 2,
    }
    states = lifecycle.item_lifecycle_states(
        [old, new], {"source-a": {}, "source-b": {"status": "withdrawn"}}, now="2026-10-04T00:00:00Z",
    )
    assert states == {"old": "superseded", "new": "source_withdrawn"}


def test_source_expiry_is_live_and_an_invalid_dependency_blocks_item():
    item = {"knowledgeItemId": "item", "sourceArtifactIds": ["valid", "expired"]}
    states = lifecycle.item_lifecycle_states(
        [item], {"valid": {}, "expired": {"expiresAt": "2026-10-03T00:00:00Z"}},
        now="2026-10-04T00:00:00Z",
    )
    assert states["item"] == "source_expired"


def test_source_withdrawal_requires_review_permission_and_preserves_body(knowledge_env):
    env = knowledge_env
    item, source = _item(env)
    with pytest.raises(knowledge.TeamKnowledgePermissionError):
        lifecycle.set_knowledge_source_lifecycle(
            env["base"]["knowledgeBaseId"], source["sourceArtifactId"], status="withdrawn",
            reason="Source corrected", actor_agent_id=env["member"]["agentId"],
        )
    result = lifecycle.set_knowledge_source_lifecycle(
        env["base"]["knowledgeBaseId"], source["sourceArtifactId"], status="withdrawn",
        reason="Source corrected", actor_agent_id=env["lead"]["agentId"],
    )
    assert result["sourceArtifact"]["status"] == "withdrawn"
    owner, _ = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    assert knowledge._require_item(owner, env["base"]["knowledgeBaseId"], item["knowledgeItemId"])["content"] == item["content"]


def test_original_source_is_hash_checked_and_owner_scoped(knowledge_env):
    env = knowledge_env
    item, source = _item(env)
    payload = lifecycle.read_knowledge_source_snapshot(
        env["base"]["knowledgeBaseId"], item["knowledgeItemId"], source["sourceArtifactId"],
        agent_id=env["lead"]["agentId"],
    )
    assert payload["content"] == "Governed test source content."
    assert payload["contentSha256"] == hashlib.sha256(payload["content"].encode()).hexdigest()
    with pytest.raises(knowledge.TeamKnowledgePermissionError):
        lifecycle.read_knowledge_source_snapshot(
            env["base"]["knowledgeBaseId"], item["knowledgeItemId"], source["sourceArtifactId"],
            agent_id=env["outsider"]["agentId"],
        )


def test_source_snapshot_rejects_body_tampering(knowledge_env):
    env = knowledge_env
    item, source = _item(env)
    central = knowledge._find_central_source_by_id_locked(source["centralSourceId"])
    path = knowledge._project_path_from_relative(central["centralPath"])
    path.write_text("Injected replacement", encoding="utf-8")
    with pytest.raises(knowledge.TeamKnowledgeError, match="integrity check failed"):
        lifecycle.read_knowledge_source_snapshot(
            env["base"]["knowledgeBaseId"], item["knowledgeItemId"], source["sourceArtifactId"],
            agent_id=env["lead"]["agentId"],
        )


def test_source_snapshot_rejects_path_redirection(knowledge_env):
    env = knowledge_env
    item, source = _item(env)
    rows = knowledge._read_jsonl(knowledge._central_source_registry_path())
    rows[0]["centralPath"] = "workspace/agents/other/private.txt"
    knowledge._write_jsonl(knowledge._central_source_registry_path(), rows)
    with pytest.raises(knowledge.TeamKnowledgeError, match="governed source directory"):
        lifecycle.read_knowledge_source_snapshot(
            env["base"]["knowledgeBaseId"], item["knowledgeItemId"], source["sourceArtifactId"],
            agent_id=env["lead"]["agentId"],
        )


def test_disabled_private_memory_is_denied_before_body_read(monkeypatch):
    from core.web.services.knowledge_read_service import KnowledgeReadPermissionError, read_knowledge_item

    monkeypatch.setattr(knowledge, "_require_base_with_owner", lambda _: ({"ownerType": "agent"}, {}))
    def unexpected_read(*args, **kwargs):
        pytest.fail("Disabled private memory must not read a body")
    monkeypatch.setattr(knowledge, "get_readable_knowledge_item", unexpected_read)
    with pytest.raises(KnowledgeReadPermissionError):
        read_knowledge_item(knowledge_base_id="kb", knowledge_item_id="item", agent_id="owner", private_memory_enabled=False)


def test_two_revision_proposals_cannot_both_apply_and_history_is_bounded(knowledge_env):
    env = knowledge_env
    item, source = _item(env)
    args = dict(source_artifact_ids=[source["sourceArtifactId"]], proposed_by_agent_id=env["member"]["agentId"],
                title=item["title"], summary="Corrected policy", content="Delivery takes 17 days.",
                supersedes_knowledge_item_id=item["knowledgeItemId"],
                expected_content_sha256=lifecycle.content_sha256(item), revision_reason="Carrier changed")
    first = governance.create_refinement_proposal(env["base"]["knowledgeBaseId"], **args)
    second = governance.create_refinement_proposal(env["base"]["knowledgeBaseId"], **args)
    new = governance.review_refinement_proposal(env["base"]["knowledgeBaseId"], first["proposalId"],
                 status="applied", reviewed_by_agent_id=env["lead"]["agentId"])["item"]
    assert new["revision"] == 2 and new["content"] == args["content"]
    with pytest.raises(knowledge.TeamKnowledgeIdempotencyConflictError):
        governance.review_refinement_proposal(env["base"]["knowledgeBaseId"], second["proposalId"],
                 status="applied", reviewed_by_agent_id=env["lead"]["agentId"])
    history = lifecycle.list_knowledge_item_versions(env["base"]["knowledgeBaseId"], new["knowledgeItemId"],
                 agent_id=env["lead"]["agentId"], limit=1)
    assert history["versionCount"] == 2 and history["hasMore"] and history["nextOffset"] == 1
    assert "content" not in history["versions"][0]
    governance.review_refinement_proposal(env["base"]["knowledgeBaseId"], second["proposalId"],
                 status="rejected", reviewed_by_agent_id=env["lead"]["agentId"])


def test_withdrawn_source_blocks_pending_proposal_review(knowledge_env):
    env = knowledge_env
    _, source = _item(env)
    proposal = governance.create_refinement_proposal(env["base"]["knowledgeBaseId"],
                 source_artifact_ids=[source["sourceArtifactId"]], proposed_by_agent_id=env["member"]["agentId"],
                 title="Pending", content="Pending body")
    lifecycle.set_knowledge_source_lifecycle(env["base"]["knowledgeBaseId"], source["sourceArtifactId"],
                 status="withdrawn", reason="Corrected source", actor_agent_id=env["lead"]["agentId"])
    with pytest.raises(knowledge.TeamKnowledgeError, match="active governed"):
        governance.review_refinement_proposal(env["base"]["knowledgeBaseId"], proposal["proposalId"],
                 status="applied", reviewed_by_agent_id=env["lead"]["agentId"])


@pytest.mark.parametrize("state", ["withdrawn", "expired"])
def test_inactive_source_excluded_from_every_retrieval_but_kept_in_management(knowledge_env, state, monkeypatch):
    from core.web.services.team_knowledge import semantic as knowledge_semantic_service
    from core.web.services import rag_retrieval_service, rag_vector_index_service, unified_knowledge_search_service

    env = knowledge_env
    base_id = env["base"]["knowledgeBaseId"]
    actor = env["lead"]["agentId"]

    # Make the positive semantic controls independent of machine-local model
    # caches so later empty results prove lifecycle filtering, not no vectors.
    monkeypatch.setattr(knowledge_semantic_service, "DEFAULT_EMBEDDING_DIMENSION", 2)
    monkeypatch.setattr(
        knowledge_semantic_service.embeddings,
        "readiness",
        lambda **_: {"status": "ready", "cached": True, "dimension": 2},
    )
    monkeypatch.setattr(
        knowledge_semantic_service.embeddings,
        "encode",
        lambda texts, **_: [[1.0, 0.0] for _ in texts],
    )
    item, source = _item(env)
    built = knowledge_semantic_service.build_knowledge_index(base_id, agent_id=actor)
    assert built["status"] == "ready"
    assert built["indexedItemCount"] == 1

    for mode in ("semantic", "hybrid"):
        positive = knowledge.search_knowledge_items(
            agent_id=actor, knowledge_base_id=base_id, query="Delivery", search_mode=mode,
        )
        assert [row["knowledgeItemId"] for row in positive["results"]] == [item["knowledgeItemId"]]
        rag_positive = rag_retrieval_service.retrieve_rag_contexts(
            agent_id=actor, knowledge_base_id=base_id, query="Delivery", retrieval_mode=mode,
        )
        assert any(
            (row.get("source") or {}).get("knowledgeItemId") == item["knowledgeItemId"]
            for row in rag_positive["contexts"]
        ), mode

    lifecycle.set_knowledge_source_lifecycle(base_id, source["sourceArtifactId"], status=state,
                 reason="Source changed", actor_agent_id=actor)
    with pytest.raises(knowledge.TeamKnowledgeNotFoundError):
        knowledge.get_readable_knowledge_item(base_id, item["knowledgeItemId"], agent_id=actor)
    assert knowledge.list_knowledge_items(base_id, agent_id=actor)["items"][0]["knowledgeState"] == "source_" + state
    for mode in ("exact", "bm25", "semantic", "hybrid"):
        assert not knowledge.search_knowledge_items(agent_id=actor, knowledge_base_id=base_id, query="Delivery", search_mode=mode)["results"]
    for mode in ("exact", "bm25", "semantic", "hybrid", "regex", "rag"):
        unified = unified_knowledge_search_service.search_unified_memory(
            agent_id=actor, knowledge_base_id=base_id, query="Delivery", query_mode=mode,
        )
        assert not unified["results"], mode
    for mode in rag_retrieval_service.SUPPORTED_RETRIEVAL_MODES:
        rag = rag_retrieval_service.retrieve_rag_contexts(
            agent_id=actor, knowledge_base_id=base_id, query="Delivery", retrieval_mode=mode,
        )
        assert not rag["contexts"], mode
    assert not rag_vector_index_service.list_indexable_knowledge_items(agent_id=actor)


def test_source_snapshot_rejects_ancestor_symlink(knowledge_env, tmp_path):
    env = knowledge_env
    item, source = _item(env)
    central = knowledge._find_central_source_by_id_locked(source["centralSourceId"])
    path = knowledge._project_path_from_relative(central["centralPath"])
    relocated = tmp_path / "relocated-snapshot"
    path.parent.rename(relocated)
    try:
        os.symlink(relocated, path.parent, target_is_directory=True)
    except OSError:
        relocated.rename(path.parent)
        pytest.skip("Creating directory symlinks requires Windows permission")
    with pytest.raises(knowledge.TeamKnowledgeError, match="governed source directory"):
        lifecycle.read_knowledge_source_snapshot(env["base"]["knowledgeBaseId"], item["knowledgeItemId"],
                       source["sourceArtifactId"], agent_id=env["lead"]["agentId"])


def test_source_reactivation_requires_a_fresh_reviewed_revision(knowledge_env):
    from core.web.services.team_knowledge import retrieval
    env = knowledge_env
    item, source = _item(env)
    base_id, actor = env["base"]["knowledgeBaseId"], env["lead"]["agentId"]
    for state in ("withdrawn", "active"):
        lifecycle.set_knowledge_source_lifecycle(base_id, source["sourceArtifactId"], status=state,
                     reason="Source revalidated", actor_agent_id=actor)
    with pytest.raises(knowledge.TeamKnowledgeNotFoundError):
        retrieval.get_readable_knowledge_item(base_id, item["knowledgeItemId"], agent_id=actor)
    proposal = governance.create_refinement_proposal(base_id, source_artifact_ids=[source["sourceArtifactId"]],
                     proposed_by_agent_id=env["member"]["agentId"], title=item["title"], content="Reviewed correction",
                     supersedes_knowledge_item_id=item["knowledgeItemId"], expected_content_sha256=lifecycle.content_sha256(item),
                     revision_reason="Source revalidated")
    applied = governance.review_refinement_proposal(base_id, proposal["proposalId"], status="applied", reviewed_by_agent_id=actor)
    assert retrieval.get_readable_knowledge_item(base_id, applied["item"]["knowledgeItemId"], agent_id=actor)["content"] == "Reviewed correction"


@pytest.mark.parametrize(
    ("sync_raises", "expected_semantic_index"),
    [
        (False, {"status": "unavailable", "reason": "model_not_prepared"}),
        (True, {"status": "failed", "reason": "index_sync_failed"}),
    ],
)
def test_direct_source_ingestion_captures_lifecycle_and_syncs_index_outside_lock(
    knowledge_env, monkeypatch, sync_raises, expected_semantic_index,
):
    import threading

    from core.web.services.team_knowledge import semantic as knowledge_semantic_service

    env = knowledge_env
    base_id = env["base"]["knowledgeBaseId"]
    content = "Directly reviewed inbox content becomes versioned formal knowledge."
    inbox = knowledge.collect_source_to_inbox(
        "team",
        env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": "direct lifecycle acceptance"},
        original_content="Evidence retained in the accepted owner source.",
        original_filename="direct-lifecycle.txt",
        title="Direct lifecycle source",
        actor_agent_id=env["member"]["agentId"],
    )
    sync_calls = []

    def fake_sync(knowledge_base_id, item, *, agent_id):
        lock_available = threading.Event()

        def probe_lock():
            acquired = knowledge._LOCK.acquire(timeout=1)
            if acquired:
                knowledge._LOCK.release()
                lock_available.set()

        probe = threading.Thread(target=probe_lock, daemon=True)
        probe.start()
        probe.join(timeout=1.5)
        assert not probe.is_alive(), "semantic indexing must not hold the knowledge write lock"
        assert lock_available.is_set(), "semantic indexing must run after the knowledge write lock is released"
        sync_calls.append((knowledge_base_id, item, agent_id))
        if sync_raises:
            raise RuntimeError("injected index sync failure")
        return {"status": "unavailable", "reason": "model_not_prepared"}

    monkeypatch.setattr(knowledge_semantic_service, "sync_reviewed_item", fake_sync)
    reviewed = knowledge.review_owner_inbox_source(
        "team",
        env["team"]["teamId"],
        inbox["inboxSourceId"],
        decision="accepted",
        reviewed_by_agent_id=env["lead"]["agentId"],
        ingest_on_accept=True,
        knowledge_base_id=base_id,
        knowledge_title="Direct lifecycle item",
        knowledge_content=content,
    )

    direct = reviewed["directIngestion"]
    item = direct["item"]
    source_artifact_id = direct["sourceArtifact"]["sourceArtifactId"]
    owner, _ = knowledge._require_base_with_owner(base_id)
    stored = knowledge._require_item(owner, base_id, item["knowledgeItemId"])

    assert direct["semanticIndex"] == expected_semantic_index
    assert len(sync_calls) == 1
    assert sync_calls[0][0] == base_id
    assert sync_calls[0][1]["knowledgeItemId"] == item["knowledgeItemId"]
    assert sync_calls[0][2] == env["lead"]["agentId"]
    assert stored["revision"] == 1
    assert stored["rootKnowledgeItemId"] == item["knowledgeItemId"]
    assert stored["contentSha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert stored["sourceLifecycleRevisions"] == {source_artifact_id: 0}


def test_graph_aggregate_does_not_return_invalid_bodies(knowledge_env):
    from core.web.services import memory_graph_service as graph
    env = knowledge_env
    item, source = _item(env)
    owner, base = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    stored = knowledge._read_jsonl(knowledge._items_path_for_owner(owner))
    assert graph._items_for_base_full_detail(owner, base, stored)[0]["content"] == item["content"]
    lifecycle.set_knowledge_source_lifecycle(base["knowledgeBaseId"], source["sourceArtifactId"], status="withdrawn",
                      reason="Source invalid", actor_agent_id=env["lead"]["agentId"])
    assert not graph._items_for_base_full_detail(owner, base, stored)
