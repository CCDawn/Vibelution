"""Real vectors are derived data; canonical ACL, hashes and validity stay authoritative."""

import math
import os
from pathlib import Path

import pytest

from core.web.services.team_knowledge import semantic as semantic
from core.web.services import rag_vector_index_service as index
from core.web.services import team_service
from core.web.services import team_knowledge_service as knowledge
from tests.test_knowledge_lifecycle import _item, knowledge_env, isolate_developer_sandbox_config


def _adapter(monkeypatch):
    # Tests using tiny vectors must opt into that model dimension explicitly.
    monkeypatch.setattr(semantic, "DEFAULT_EMBEDDING_DIMENSION", 2)
    monkeypatch.setattr(semantic.embeddings, "readiness", lambda **_: {"status": "ready", "cached": True})
    monkeypatch.setattr(semantic.embeddings, "encode", lambda texts, **_: [[1.0, 0.0] for _ in texts])


def test_index_build_is_review_scoped_and_embeds_the_full_tail(knowledge_env, monkeypatch):
    env = knowledge_env
    item, _ = _item(env)
    owner, base = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    rows = knowledge._read_jsonl(knowledge._items_path_for_owner(owner))
    rows[0]["content"] = "A" * 1900 + "TAIL-ZEBRA"
    knowledge._write_jsonl(knowledge._items_path_for_owner(owner), rows)
    seen = []
    _adapter(monkeypatch)
    monkeypatch.setattr(semantic.embeddings, "encode", lambda texts, **_: seen.extend(texts) or [[1.0, 0.0] for _ in texts])
    with pytest.raises(knowledge.TeamKnowledgePermissionError):
        semantic.build_knowledge_index(base["knowledgeBaseId"], agent_id=env["outsider"]["agentId"])
    assert not seen
    result = semantic.build_knowledge_index(base["knowledgeBaseId"], agent_id=env["lead"]["agentId"])
    assert result["indexedItemCount"] == 1
    assert any("TAIL-ZEBRA" in text for text in seen)
    records = index._load_all_index_records()
    assert len(records) == 1 and records[0]["chunks"][-1]["end"] == len(rows[0]["content"])
    assert "content" not in records[0] and "text" not in records[0]["chunks"][0]
    assert math.isclose(sum(v*v for v in records[0]["chunks"][0]["vector"]), 1)


def test_semantic_query_requires_real_current_vectors_and_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "PROJECT_ROOT", tmp_path)
    _adapter(monkeypatch)
    candidate = {"knowledgeItemId": "one", "knowledgeBaseId": "kb", "ownerType": "agent", "ownerId": "owner",
                 "contentHash": "sha256:current", "_indexContentHash": "sha256:current", "_searchDocument": {"content": "plane"}}
    index.write_index_record(candidate, embedding_provider="fastembed", embedding_model=semantic.embeddings.DEFAULT_MODEL_NAME)
    ranked, info = semantic.rank_candidates([candidate], "aircraft", mode="semantic")
    assert ranked == [] and info["status"] == "unavailable"
    index.write_index_record(candidate, embedding_provider="fastembed", embedding_model=semantic.embeddings.DEFAULT_MODEL_NAME,
                             chunks=[{"start": 0, "end": 5, "vector": [1.0, 0.0]}])
    ranked, info = semantic.rank_candidates([candidate], "aircraft", mode="semantic")
    assert ranked[0]["vectorScore"] == 1 and info["status"] == "ready"
    stale = {**candidate, "_indexContentHash": "sha256:changed"}
    assert semantic.rank_candidates([stale], "aircraft", mode="semantic")[0] == []
    monkeypatch.setattr(semantic.embeddings, "readiness", lambda **_: {"status": "unavailable", "cached": False})
    monkeypatch.setattr(semantic.embeddings, "prepare", lambda **_: pytest.fail("Queries must not download weights"))
    assert semantic.rank_candidates([candidate], "aircraft", mode="semantic")[0] == []


def test_health_marks_non_bge_dimension_vectors_degraded(knowledge_env, monkeypatch):
    env = knowledge_env
    _item(env)
    monkeypatch.setattr(semantic.embeddings, "readiness", lambda **_: {"status": "ready", "dimension": 512})
    candidate = index.list_indexable_knowledge_items(agent_id=env["lead"]["agentId"])[0]
    index.write_index_record(candidate, embedding_provider="fastembed", embedding_model=semantic.embeddings.DEFAULT_MODEL_NAME,
                             chunks=[{"start": 0, "end": 1, "vector": [1.0, 0.0]}])

    health = semantic.get_semantic_index_health(agent_id=env["lead"]["agentId"])

    assert semantic.DEFAULT_EMBEDDING_DIMENSION == 512
    assert health["status"] == "degraded"
    assert health["reason"] == "embedding_dimension_mismatch"
    assert health["indexedItemCount"] == 0
    assert health["missingItemCount"] == 1
    assert health["dimensionMismatchCount"] == 1


def test_health_reports_known_offline_model_load_failure(knowledge_env, monkeypatch):
    env = knowledge_env
    _item(env)
    monkeypatch.setattr(
        semantic.embeddings,
        "readiness",
        lambda **_: {
            "prepared": True,
            "ready": False,
            "loaded": False,
            "status": "load_failed",
            "reason": "offline_model_load_failed",
            "dimension": 512,
        },
    )

    health = semantic.get_semantic_index_health(agent_id=env["lead"]["agentId"])

    assert health["status"] == "unavailable"
    assert health["reason"] == "offline_model_load_failed"
    assert health["modelPrepared"] is True
    assert health["modelLoaded"] is False
    assert health["vectorEnabled"] is False


def test_semantic_query_retries_a_known_load_failure_offline(knowledge_env, monkeypatch):
    env = knowledge_env
    _item(env)
    _adapter(monkeypatch)
    candidate = index.list_indexable_knowledge_items(agent_id=env["lead"]["agentId"])[0]
    candidate["_indexContentHash"] = candidate["contentHash"]
    candidate["_searchDocument"] = {"content": "current local knowledge"}
    index.write_index_record(
        candidate,
        embedding_provider="fastembed",
        embedding_model=semantic.embeddings.DEFAULT_MODEL_NAME,
        chunks=[{"start": 0, "end": len("current local knowledge"), "vector": [1.0, 0.0]}],
    )
    monkeypatch.setattr(
        semantic.embeddings,
        "readiness",
        lambda **_: {
            "prepared": True,
            "ready": False,
            "loaded": False,
            "status": "load_failed",
            "reason": "offline_model_load_failed",
            "dimension": 2,
        },
    )
    purposes = []

    def retry_encode(texts, *, purpose="passage", **_):
        purposes.append(purpose)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(semantic.embeddings, "encode", retry_encode)

    ranked, info = semantic.rank_candidates([candidate], "find the current local knowledge", mode="semantic")

    assert purposes == ["query"]
    assert [row["knowledgeItemId"] for row in ranked] == [candidate["knowledgeItemId"]]
    assert info["status"] == "ready"


def test_query_dimension_mismatch_marks_candidates_missing(knowledge_env, monkeypatch):
    env = knowledge_env
    _item(env)
    _adapter(monkeypatch)
    candidate = index.list_indexable_knowledge_items(agent_id=env["lead"]["agentId"])[0]
    candidate["_indexContentHash"] = candidate["contentHash"]
    candidate["_searchDocument"] = {"content": "a current formal knowledge item"}
    index.write_index_record(candidate, embedding_provider="fastembed", embedding_model=semantic.embeddings.DEFAULT_MODEL_NAME,
                             chunks=[{"start": 0, "end": 1, "vector": [1.0, 0.0, 0.0]}])

    ranked, info = semantic.rank_candidates([candidate], "question", mode="semantic")

    assert ranked == []
    assert info["status"] == "degraded"
    assert info["reason"] == "embedding_dimension_mismatch"
    assert info["indexedCandidateCount"] == 0
    assert info["missingCandidateCount"] == 1
    assert info["dimensionMismatchCount"] == 1

    index.write_index_record(candidate, embedding_provider="fastembed", embedding_model=semantic.embeddings.DEFAULT_MODEL_NAME,
                             chunks=[{"start": 0, "end": 1, "vector": [1.0, 0.0]}])
    monkeypatch.setattr(semantic.embeddings, "encode", lambda texts, *, purpose="passage", **_: [[1.0, 0.0, 0.0] for _ in texts])

    ranked, info = semantic.rank_candidates([candidate], "question", mode="semantic")

    assert ranked == []
    assert info["status"] == "degraded"
    assert info["reason"] == "query_embedding_dimension_mismatch"
    assert info["indexedCandidateCount"] == 0
    assert info["missingCandidateCount"] == 1


def test_vector_records_reject_nonfinite_vectors():
    with pytest.raises(ValueError, match="finite"):
        index.write_index_record({"knowledgeItemId": "one"}, chunks=[{"start": 0, "end": 1, "vector": [float("nan"), 1.0]}])


def test_hybrid_without_model_reports_lexical_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(semantic.embeddings, "readiness", lambda **_: {"status": "unavailable", "cached": False})
    candidate = {"knowledgeItemId": "one", "_searchDocument": {"content": "aircraft"}}
    ranked, info = semantic.rank_candidates([candidate], "aircraft", mode="hybrid")
    assert ranked[0]["matchReason"] == "bm25"
    assert info["status"] == "unavailable" and info["effectiveMode"] == "bm25"


def test_withdrawal_during_inference_prevents_index_publication(knowledge_env, monkeypatch):
    env = knowledge_env
    item, source = _item(env)
    _adapter(monkeypatch)

    def withdraw(texts, **_):
        from core.web.services.team_knowledge import lifecycle
        lifecycle.set_knowledge_source_lifecycle(env["base"]["knowledgeBaseId"], source["sourceArtifactId"],
            status="withdrawn", reason="Evidence was recalled during embedding", actor_agent_id=env["lead"]["agentId"])
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(semantic.embeddings, "encode", withdraw)
    result = semantic.build_knowledge_index(env["base"]["knowledgeBaseId"], agent_id=env["lead"]["agentId"])
    assert result["indexedItemCount"] == 0
    assert not index._load_all_index_records()


@pytest.mark.parametrize("sync_only", [False, True], ids=["build", "reviewed-sync"])
def test_review_revocation_during_inference_prevents_index_publication(knowledge_env, monkeypatch, sync_only):
    env = knowledge_env
    item, _ = _item(env)
    base_id = env["base"]["knowledgeBaseId"]
    reviewer_id = env["lead"]["agentId"]
    _adapter(monkeypatch)

    def revoke_review_while_embedding(texts, **_):
        team_service.update_team(
            env["team"]["teamId"],
            members=[
                {"agentId": reviewer_id, "role": "member"},
                {"agentId": env["member"]["agentId"], "role": "member"},
            ],
        )
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(semantic.embeddings, "encode", revoke_review_while_embedding)

    if sync_only:
        result = semantic.sync_reviewed_item(base_id, item, agent_id=reviewer_id)
        assert result["status"] == "failed"
    else:
        result = semantic.build_knowledge_index(base_id, agent_id=reviewer_id)
        assert result["indexedItemCount"] == 0

    assert not index._load_all_index_records()
    readable = knowledge.get_readable_knowledge_item(base_id, item["knowledgeItemId"], agent_id=reviewer_id)
    assert readable["content"] == item["content"]


def test_index_build_rechecks_candidates_after_concurrent_knowledge_add(knowledge_env, monkeypatch):
    env = knowledge_env
    _item(env)
    _adapter(monkeypatch)
    added = False

    def add_item_during_embedding(texts, *, purpose="passage", **_):
        nonlocal added
        if purpose == "passage" and not added:
            added = True
            # Reviewed knowledge is allowed to land while the build is busy;
            # its normal sync path stays offline and cannot hide the race.
            monkeypatch.setattr(semantic.embeddings, "readiness", lambda **_: {"status": "unavailable", "cached": False})
            _item(env)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(semantic.embeddings, "encode", add_item_during_embedding)

    result = semantic.build_knowledge_index(env["base"]["knowledgeBaseId"], agent_id=env["lead"]["agentId"])

    assert added
    assert result["status"] == "degraded"
    assert result["candidateItemCount"] == 2
    assert result["indexedItemCount"] == 1
    assert result["missingItemCount"] == 1


def test_reviewed_revision_survives_semantic_index_sync_failure(knowledge_env, monkeypatch):
    from core.web.services.team_knowledge import governance, lifecycle, retrieval

    env = knowledge_env
    old_item, source = _item(env)
    base_id = env["base"]["knowledgeBaseId"]
    actor_id = env["lead"]["agentId"]
    _adapter(monkeypatch)

    built = semantic.build_knowledge_index(base_id, agent_id=actor_id)
    assert built["status"] == "ready"
    assert built["indexedItemCount"] == 1
    old_record_id = index._record_id_for_item(old_item)
    old_record_path = index._item_record_path(old_record_id)
    assert index._read_json(old_record_path)["status"] == "indexed"

    proposal = governance.create_refinement_proposal(
        base_id,
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=env["member"]["agentId"],
        title="Revised shipping policy",
        content="Delivery now takes 18 days after the carrier contract review.",
        supersedes_knowledge_item_id=old_item["knowledgeItemId"],
        expected_content_sha256=lifecycle.content_sha256(old_item),
        revision_reason="The carrier schedule changed.",
    )

    def fail_vector_publish(*_args, **_kwargs):
        raise ValueError("injected vector publication failure")

    monkeypatch.setattr(semantic, "_publish_item", fail_vector_publish)
    applied = governance.review_refinement_proposal(
        base_id,
        proposal["proposalId"],
        status="applied",
        reviewed_by_agent_id=actor_id,
    )
    new_item = applied["item"]
    assert applied["semanticIndex"]["status"] == "failed"
    assert new_item["knowledgeItemId"] != old_item["knowledgeItemId"]
    new_record = index._read_json(index._item_record_path(index._record_id_for_item(new_item))) or {}
    assert new_record.get("status") != "indexed"

    readable = retrieval.get_readable_knowledge_item(
        base_id, new_item["knowledgeItemId"], agent_id=actor_id,
    )
    assert readable["content"] == new_item["content"]

    bm25 = retrieval.search_knowledge_items(
        agent_id=actor_id, knowledge_base_id=base_id,
        query="18 days carrier contract", search_mode="bm25",
    )
    assert [row["knowledgeItemId"] for row in bm25["results"]] == [new_item["knowledgeItemId"]]

    hybrid = retrieval.search_knowledge_items(
        agent_id=actor_id, knowledge_base_id=base_id,
        query="18 days carrier contract", search_mode="hybrid",
    )
    assert [row["knowledgeItemId"] for row in hybrid["results"]] == [new_item["knowledgeItemId"]]
    assert hybrid["semanticRetrieval"]["effectiveMode"] == "bm25"
    assert hybrid["semanticRetrieval"]["status"] == "unavailable"
    assert hybrid["semanticRetrieval"]["reason"] == "missing_or_stale_vectors"
    assert hybrid["semanticRetrieval"]["missingCandidateCount"] == 1
    assert hybrid["semanticRetrieval"]["impact"] == "keyword_retrieval_only"

    old_content_query = retrieval.search_knowledge_items(
        agent_id=actor_id, knowledge_base_id=base_id,
        query="23 days", search_mode="hybrid",
    )
    assert index._read_json(old_record_path)["status"] == "indexed"
    assert old_item["knowledgeItemId"] not in {
        row["knowledgeItemId"] for row in old_content_query["results"]
    }


def test_semantic_ranking_scans_beyond_the_result_limit(knowledge_env, monkeypatch):
    from core.web.services.team_knowledge import retrieval

    env = knowledge_env
    item, _ = _item(env)
    owner, base = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    rows = [{**item, "knowledgeItemId": f"kitem-{n:03}", "rootKnowledgeItemId": f"kitem-{n:03}",
             "title": f"Record {n}", "content": "opaque reference"} for n in range(121)]
    knowledge._write_jsonl(knowledge._items_path_for_owner(owner), rows)
    target = rows[-1]
    _adapter(monkeypatch)
    index.write_index_record({**target, "contentHash": index._content_hash(target)},
        embedding_provider="fastembed", embedding_model=semantic.embeddings.DEFAULT_MODEL_NAME,
        chunks=[{"start": 0, "end": len(target["content"]), "vector": [1.0, 0.0]}])

    result = retrieval.search_knowledge_items(agent_id=env["lead"]["agentId"], knowledge_base_id=base["knowledgeBaseId"],
        query="different wording", search_mode="semantic", limit=1)
    assert [row["knowledgeItemId"] for row in result["results"]] == [target["knowledgeItemId"]]
    assert result["semanticRetrieval"]["missingCandidateCount"] == 120
    assert result["semanticRetrieval"]["status"] == "degraded"


@pytest.mark.skipif(not os.environ.get("VIBELUTION_KNOWLEDGE_MODEL_CACHE"), reason="Explicit prepared model required")
def test_real_chinese_tail_semantics_and_offline_approval_sync(knowledge_env, monkeypatch):
    from core.web.services.team_knowledge import governance, retrieval, lifecycle

    env = knowledge_env
    cache = Path(os.environ["VIBELUTION_KNOWLEDGE_MODEL_CACHE"])
    monkeypatch.setattr(semantic, "_cache_dir", lambda: cache)
    item, source = _item(env)
    owner, base = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    body = "会议记录：项目按计划推进，各团队定期汇报。" * 130 + "\n使用自动保存与备份，可以减少意外掉电导致文件损坏的风险。"
    proposal = governance.create_refinement_proposal(base["knowledgeBaseId"], source_artifact_ids=[source["sourceArtifactId"]],
                  proposed_by_agent_id=env["member"]["agentId"], title="工作指引", content=body)
    applied = governance.review_refinement_proposal(base["knowledgeBaseId"], proposal["proposalId"],
                  status="applied", reviewed_by_agent_id=env["lead"]["agentId"])
    assert applied["semanticIndex"]["status"] == "indexed"
    actor = env["lead"]["agentId"]
    result = retrieval.search_knowledge_items(agent_id=actor, knowledge_base_id=base["knowledgeBaseId"],
                  query="工作时突然断电，怎样避免文档丢失？", search_mode="semantic", limit=1)
    assert result["results"][0]["knowledgeItemId"] == applied["item"]["knowledgeItemId"]
    assert "自动保存" in result["results"][0]["matchedExcerpt"]
    assert result["results"][0]["matchedContentOffset"] > 2000
    assert result["semanticRetrieval"]["indexedCandidateCount"] == 1
    assert not retrieval.search_knowledge_items(agent_id=env["outsider"]["agentId"], knowledge_base_id=base["knowledgeBaseId"],
                  query="工作时突然断电", search_mode="semantic")["results"]
    lifecycle.set_knowledge_source_lifecycle(base["knowledgeBaseId"], source["sourceArtifactId"], status="withdrawn",
                  reason="内容修订", actor_agent_id=actor)
    assert not retrieval.search_knowledge_items(agent_id=actor, knowledge_base_id=base["knowledgeBaseId"],
                  query="工作时突然断电", search_mode="semantic")["results"]
