"""Read-waste trim regressions for the knowledge retrieval chain.

Covers the pure-performance guarantees:
- parsed-file reads (items JSONL / knowledge_bases.json registry) are memoized
  per (path, mtime, size) and any file change serves a fresh parse;
- one unified search across multiple bases parses each registry once;
- a search that scans zero bases (ACL-excluded / no active base) still returns
  the exact pre-trim response shape via the early exit;
- per-item search-document products are memoized under a content key (repeat
  queries reuse them, content changes produce a fresh key, LRU budgets evict);
- an empty query (metadata filters only) takes the fast path that skips
  per-item document/index-hash construction while returning byte-equal output.
Scoring and ranking semantics are unchanged: identical inputs must produce
identical results cold and warm.
"""

import json
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    memory_graph_service,
    rag_vector_index_service,
    team_knowledge_service as knowledge,
    team_service,
)
from core.web.services.team_knowledge import read_cache, retrieval, search_ranking
from core.web.services.unified_knowledge_search_service import search_unified_memory
from tests.test_team_knowledge_service import (
    _create_central_source_artifact,
    isolate_developer_sandbox_config,  # noqa: F401 - autouse sandbox isolation
    knowledge_env,  # noqa: F401 - shared knowledge fixture
)


@pytest.fixture(autouse=True)
def _fresh_read_cache():
    read_cache.reset_knowledge_read_cache_for_tests()
    yield
    read_cache.reset_knowledge_read_cache_for_tests()


def _indexed_item(env, *, title="Shipping policy", content="Delivery takes 23 days."):
    source = _create_central_source_artifact(
        env["base"]["knowledgeBaseId"],
        owner_type="team",
        owner_id=env["team"]["teamId"],
        actor_agent_id=env["member"]["agentId"],
        reviewer_agent_id=env["lead"]["agentId"],
        title=title,
    )
    proposal = knowledge.create_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        source_artifact_ids=[source["sourceArtifactId"]],
        proposed_by_agent_id=env["member"]["agentId"],
        title=title,
        content=content,
    )
    return knowledge.review_refinement_proposal(
        env["base"]["knowledgeBaseId"],
        proposal["proposalId"],
        status="applied",
        reviewed_by_agent_id=env["lead"]["agentId"],
    )["item"]


def test_repeat_search_results_are_identical_cold_and_cached(knowledge_env):
    env = knowledge_env
    _indexed_item(env)
    query = dict(agent_id=env["member"]["agentId"], query="delivery days", search_mode="bm25")

    first = knowledge.search_knowledge_items(**query)
    second = knowledge.search_knowledge_items(**query)

    assert first["summary"]["scannedKnowledgeBaseCount"] == 1
    assert first["summary"]["resultCount"] >= 1
    for payload in (first, second):
        payload.pop("updatedAt", None)
    assert first == second

    owner, _ = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    items_path = knowledge._items_path_for_owner(owner)
    signature = read_cache.jsonl_signature(items_path)
    assert signature is not None
    assert read_cache.cached_jsonl(items_path, signature) is not None


def test_rewritten_items_file_invalidates_parse_cache_on_next_search(knowledge_env):
    env = knowledge_env
    _indexed_item(env)
    owner, _ = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    items_path = knowledge._items_path_for_owner(owner)

    before = knowledge.search_knowledge_items(agent_id=env["member"]["agentId"], query="meteor zebra", search_mode="exact")
    assert before["summary"]["resultCount"] == 0

    rows = knowledge._read_jsonl(items_path)
    rows[0]["content"] = "meteor zebra restock window"
    knowledge._write_jsonl(items_path, rows)

    after_store_write = knowledge.search_knowledge_items(agent_id=env["member"]["agentId"], query="meteor zebra", search_mode="exact")
    assert after_store_write["summary"]["resultCount"] == 1

    rows = knowledge._read_jsonl(items_path)
    rows[0]["content"] = "plain restock window"
    items_path.write_text(
        "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    assert knowledge.search_knowledge_items(agent_id=env["member"]["agentId"], query="meteor zebra", search_mode="exact")[
        "summary"
    ]["resultCount"] == 0


def test_registry_is_parsed_once_across_bases_and_repeat_searches(knowledge_env, monkeypatch):
    env = knowledge_env
    _indexed_item(env)
    second_base = knowledge.create_knowledge_base(
        env["team"]["teamId"], name="Second Base", actor_agent_id=env["lead"]["agentId"]
    )
    owner, _ = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    registry_path = knowledge._knowledge_bases_path_for_owner(owner)
    read_cache.reset_knowledge_read_cache_for_tests()
    read_counts = {"registry": 0}
    original_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if Path(self) == registry_path:
            read_counts["registry"] += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    scoped_ids = [env["base"]["scopedKnowledgeBaseId"], second_base["scopedKnowledgeBaseId"]]
    first = search_unified_memory(
        agent_id=env["member"]["agentId"],
        query="delivery",
        query_mode="bm25",
        allowed_knowledge_base_ids=scoped_ids,
    )
    assert read_counts["registry"] == 1
    second = search_unified_memory(
        agent_id=env["member"]["agentId"],
        query="delivery",
        query_mode="bm25",
        allowed_knowledge_base_ids=scoped_ids,
    )
    assert read_counts["registry"] == 1
    assert first["summary"]["scannedKnowledgeBaseCount"] == 2
    assert first["results"] == second["results"]
    assert {row["knowledgeBaseId"] for row in first["results"]} == {env["base"]["knowledgeBaseId"]}


def test_read_jsonl_and_registry_serve_isolated_rows_callers_cannot_poison(knowledge_env):
    env = knowledge_env
    _indexed_item(env)
    owner, _ = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])

    items_path = knowledge._items_path_for_owner(owner)
    first_items = knowledge._read_jsonl(items_path)
    first_items[0]["title"] = "poisoned title"
    first_items.append({"knowledgeItemId": "injected"})

    second_items = knowledge._read_jsonl(items_path)
    assert second_items[0]["title"] != "poisoned title"
    assert all(row.get("knowledgeItemId") != "injected" for row in second_items)

    registry_path = knowledge._knowledge_bases_path_for_owner(owner)
    first_state = knowledge._load_bases_state_for_owner(owner)
    first_state["knowledgeBases"].append({"knowledgeBaseId": "injected"})

    second_state = knowledge._load_bases_state_for_owner(owner)
    assert all(row.get("knowledgeBaseId") != "injected" for row in second_state["knowledgeBases"])
    assert registry_path.exists()


def _assert_empty_search_shape(payload, *, agent_id):
    assert set(payload) == {"schemaVersion", "agentId", "filters", "summary", "results", "updatedAt"}
    assert payload["agentId"] == agent_id
    assert payload["results"] == []
    assert payload["summary"] == {"resultCount": 0, "scannedKnowledgeBaseCount": 0}
    assert payload["filters"]["searchMode"] in {"exact", "bm25", "semantic", "hybrid"}


def test_zero_scanned_bases_early_exit_keeps_exact_and_hybrid_shapes(knowledge_env):
    env = knowledge_env
    _indexed_item(env)

    outsider_query = dict(agent_id=env["outsider"]["agentId"], query="delivery", private_memory_enabled=False)
    exact = knowledge.search_knowledge_items(**outsider_query, search_mode="exact")
    _assert_empty_search_shape(exact, agent_id=env["outsider"]["agentId"])

    hybrid = knowledge.search_knowledge_items(**outsider_query, search_mode="hybrid")
    assert set(hybrid) == {"schemaVersion", "agentId", "semanticRetrieval", "filters", "summary", "results", "updatedAt"}
    assert hybrid["results"] == []
    assert hybrid["summary"] == {"resultCount": 0, "scannedKnowledgeBaseCount": 0}
    assert hybrid["semanticRetrieval"]["indexedCandidateCount"] == 0
    assert hybrid["semanticRetrieval"]["missingCandidateCount"] == 0
    assert hybrid["semanticRetrieval"]["status"] in {"unavailable", "degraded"}

    # Archiving via a direct registry rewrite (established test pattern) also
    # proves the registry parse cache invalidates on mtime-only file changes.
    owner, _ = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    registry_path = knowledge._knowledge_bases_path_for_owner(owner)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    for row in payload.get("knowledgeBases") or []:
        if row.get("knowledgeBaseId") == env["base"]["knowledgeBaseId"]:
            row["status"] = "archived"
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after_archive = knowledge.search_knowledge_items(
        agent_id=env["member"]["agentId"], query="delivery", search_mode="exact"
    )
    _assert_empty_search_shape(after_archive, agent_id=env["member"]["agentId"])


def test_zero_scanned_bases_hybrid_reports_same_retrieval_contract_as_full_scan_path(knowledge_env, monkeypatch):
    """The early exit must report the identical empty-candidate semantic contract."""

    from core.web.services.team_knowledge import semantic

    env = knowledge_env
    _indexed_item(env)
    monkeypatch.setattr(
        semantic.embeddings, "readiness", lambda **_: {"status": "ready", "prepared": True, "ready": True}
    )
    reference_info = dict(
        semantic.rank_candidates([], "unrelated wording", mode="hybrid")[1]
    )

    payload = knowledge.search_knowledge_items(
        agent_id=env["outsider"]["agentId"],
        query="unrelated wording",
        search_mode="hybrid",
        private_memory_enabled=False,
    )
    assert payload["summary"]["scannedKnowledgeBaseCount"] == 0
    assert payload["semanticRetrieval"] == reference_info


# ---------------------------------------------------------------------------
# Search-document memo (content-keyed derived products)
# ---------------------------------------------------------------------------


def test_search_document_products_are_memoized_across_queries(knowledge_env, monkeypatch):
    env = knowledge_env
    _indexed_item(env, title="Memo probe", content="quantum widget assembly runs daily")
    builds = {"count": 0}
    original_builder = search_ranking._knowledge_item_search_document

    def counting_builder(item, artifacts):
        builds["count"] += 1
        return original_builder(item, artifacts)

    monkeypatch.setattr(search_ranking, "_knowledge_item_search_document", counting_builder)

    first = knowledge.search_knowledge_items(
        agent_id=env["member"]["agentId"], query="quantum widget", search_mode="bm25"
    )
    assert first["summary"]["resultCount"] == 1
    assert builds["count"] == 1  # cold: exactly one document build for one item

    second = knowledge.search_knowledge_items(
        agent_id=env["member"]["agentId"], query="widget assembly", search_mode="bm25"
    )
    assert second["summary"]["resultCount"] == 1
    # Warm: same corpus, different query -> memo hit, no document rebuild.
    assert builds["count"] == 1


def test_search_memo_keys_follow_item_content_changes(knowledge_env):
    env = knowledge_env
    _indexed_item(env)  # default content "Delivery takes 23 days."
    warm = knowledge.search_knowledge_items(
        agent_id=env["member"]["agentId"], query="meteor zebra", search_mode="exact"
    )
    assert warm["summary"]["resultCount"] == 0

    owner, _ = knowledge._require_base_with_owner(env["base"]["knowledgeBaseId"])
    items_path = knowledge._items_path_for_owner(owner)
    rows = knowledge._read_jsonl(items_path)
    rows[0]["content"] = "meteor zebra restock window"
    knowledge._write_jsonl(items_path, rows)

    # A stale memo (old content) would keep this at 0; the content change must
    # produce a fresh key and therefore a fresh search document.
    after = knowledge.search_knowledge_items(
        agent_id=env["member"]["agentId"], query="meteor zebra", search_mode="exact"
    )
    assert after["summary"]["resultCount"] == 1


def test_search_memo_entry_cap_evicts_lru_not_recently_touched(monkeypatch):
    monkeypatch.setattr(read_cache, "_SEARCH_MEMO_MAX_ENTRIES", 3)
    monkeypatch.setattr(read_cache, "_SEARCH_MEMO_MAX_TOTAL_CHARS", 10_000_000)
    for index in range(3):
        read_cache.store_search_memo(f"key-{index}", {"marker": index}, estimated_chars=10)

    assert read_cache.cached_search_memo("key-0") is not None  # LRU touch
    read_cache.store_search_memo("key-3", {"marker": 3}, estimated_chars=10)

    stats = read_cache.search_memo_stats()
    assert stats["entries"] == 3
    assert read_cache.cached_search_memo("key-0") is not None  # protected by touch
    assert read_cache.cached_search_memo("key-1") is None  # least recently used
    assert read_cache.cached_search_memo("key-2") is not None
    assert read_cache.cached_search_memo("key-3") is not None


def test_search_memo_char_budget_evicts_until_under_budget(monkeypatch):
    monkeypatch.setattr(read_cache, "_SEARCH_MEMO_MAX_ENTRIES", 100)
    monkeypatch.setattr(read_cache, "_SEARCH_MEMO_MAX_TOTAL_CHARS", 25)
    read_cache.store_search_memo("small-a", {"marker": "a"}, estimated_chars=10)
    read_cache.store_search_memo("small-b", {"marker": "b"}, estimated_chars=10)
    read_cache.store_search_memo("big-c", {"marker": "c"}, estimated_chars=30)

    stats = read_cache.search_memo_stats()
    assert stats["entries"] == 1  # only the newest (oversized) entry survives
    assert stats["estimatedChars"] == 30
    assert read_cache.cached_search_memo("small-a") is None
    assert read_cache.cached_search_memo("small-b") is None
    assert read_cache.cached_search_memo("big-c") is not None


def test_search_memo_serves_defensive_document_copies():
    stored = {"document": {"title": "original", "tags": ["t"]}, "marker": 1}
    read_cache.store_search_memo("defensive", stored, estimated_chars=10)
    served = read_cache.cached_search_memo("defensive")
    assert served is not None
    served["document"]["title"] = "poisoned"
    assert read_cache.cached_search_memo("defensive")["document"]["title"] == "original"


def test_search_memo_key_and_products_tolerate_lone_surrogates():
    """Surrogate-bearing content must not crash the key hash or tokenization."""

    item = {"title": "bad \ud83d title", "summary": "", "content": "body \udfff text", "tags": []}
    key_a = search_ranking._search_document_memo_key(item, {})
    key_b = search_ranking._search_document_memo_key({**item, "content": "changed"}, {})
    assert isinstance(key_a, str) and key_a != key_b

    products = search_ranking._knowledge_item_search_products(item, {})
    assert products["document"]["title"] == "bad \ud83d title"
    assert isinstance(products["tokens"], tuple)


def test_memoized_and_unmemoized_search_payloads_are_identical(knowledge_env, monkeypatch):
    """Warm (memo-hit) and cold (forced-miss) searches must be byte-equal.

    Forcing every memo lookup to miss reproduces the pre-memo computation, so
    equality here pins the hard invariant: memoization is equivalence, not an
    approximation (scores, ordering, and every response field included).
    """

    env = knowledge_env
    _indexed_item(env, title="Gamma ledger", content="gamma ledger entries mention meteor zebra windows")
    _indexed_item(env, title="Delta notes", content="delta notes about widget assembly lines")
    original_cached = read_cache.cached_search_memo

    for mode in ("exact", "bm25", "hybrid"):
        monkeypatch.setattr(read_cache, "cached_search_memo", lambda _key: None)
        cold = _search_without_timestamp(
            agent_id=env["member"]["agentId"], query="meteor zebra widget", search_mode=mode
        )
        monkeypatch.setattr(read_cache, "cached_search_memo", original_cached)
        warm = _search_without_timestamp(
            agent_id=env["member"]["agentId"], query="meteor zebra widget", search_mode=mode
        )
        assert warm == cold, f"memoized search diverged for mode={mode}"


# ---------------------------------------------------------------------------
# Empty-query fast path
# ---------------------------------------------------------------------------


def _search_without_timestamp(**kwargs):
    payload = retrieval.search_knowledge_items(**kwargs)
    payload.pop("updatedAt", None)
    return payload


def test_empty_query_fast_path_matches_full_scan_for_every_mode(knowledge_env, monkeypatch):
    env = knowledge_env
    _indexed_item(env, title="Alpha policy", content="alpha body text")
    _indexed_item(env, title="Beta runbook", content="beta body text")

    variants = []
    for mode in ("exact", "bm25", "semantic", "hybrid"):
        variants.append({"agent_id": env["member"]["agentId"], "query": "", "search_mode": mode})
    # Scoped empty-query listing and metadata-only filters stay legal features.
    variants.append({
        "agent_id": env["member"]["agentId"], "query": "", "search_mode": "exact",
        "knowledge_base_id": env["base"]["knowledgeBaseId"],
    })
    variants.append({
        "agent_id": env["member"]["agentId"], "query": "", "search_mode": "bm25",
        "tags": ["nosuchtag"],
    })
    variants.append({
        "agent_id": env["member"]["agentId"], "query": "", "search_mode": "exact",
        "limit": 1,
    })

    for variant in variants:
        monkeypatch.setattr(retrieval, "_EMPTY_QUERY_FAST_PATH", False)
        reference = _search_without_timestamp(**variant)
        monkeypatch.setattr(retrieval, "_EMPTY_QUERY_FAST_PATH", True)
        fast = _search_without_timestamp(**variant)
        assert fast == reference, f"fast path diverged for {variant}"


def test_empty_query_fast_path_skips_document_and_index_hash_construction(knowledge_env, monkeypatch):
    env = knowledge_env
    _indexed_item(env)

    def _forbidden(*args, **kwargs):
        raise AssertionError("empty query must not build search documents or index hashes")

    monkeypatch.setattr(search_ranking, "_knowledge_item_search_document", _forbidden)
    monkeypatch.setattr(search_ranking, "_knowledge_item_search_products", _forbidden)
    monkeypatch.setattr(rag_vector_index_service, "_content_hash", _forbidden)

    for mode in ("exact", "bm25", "semantic", "hybrid"):
        payload = retrieval.search_knowledge_items(
            agent_id=env["member"]["agentId"], query="", search_mode=mode
        )
        assert payload["summary"]["resultCount"] == 1
        assert all(row.get("matchReason") == "no_query" for row in payload["results"])
