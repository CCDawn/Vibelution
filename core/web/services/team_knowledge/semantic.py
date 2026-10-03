"""Local full-body embeddings and RRF over already authorized current knowledge.

The canonical owner store owns bodies and validity. JSON index records are
rebuildable derived data and existing memory cleanup owns their deletion.
Only an explicit index build may prepare/download a model.
"""

from __future__ import annotations

import math
import threading
from typing import Any

from .. import knowledge_embeddings as embeddings
from .. import rag_vector_index_service as index
from .. import team_knowledge_service as knowledge
from . import lifecycle
from .search_ranking import _rank_bm25_search_results

CHUNK_CHARS = 320
CHUNK_OVERLAP = 64
RRF_K = 60
# BAAI/bge-small-zh-v1.5 emits 512-dimensional vectors. Keep this explicit
# fallback for readiness payloads that omit their measured model dimension.
DEFAULT_EMBEDDING_DIMENSION = 512
_BUILD_LOCK = threading.Lock()


def _cache_dir():
    return index._index_root() / "model-cache"


def _model_ready(state: dict) -> bool:
    if "ready" in state:
        return bool(state["ready"])
    if state.get("status") in {"load_failed", "failed", "unavailable", "not_prepared"}:
        return False
    return bool(state.get("cached") or state.get("loaded") or state.get("prepared") or state.get("status") in {"ready", "cached", "loaded"})


def _model_dimension(state: dict) -> int:
    try:
        dimension = int(state.get("dimension") or 0)
    except (AttributeError, TypeError, ValueError, OverflowError):
        dimension = 0
    return dimension if dimension > 0 else DEFAULT_EMBEDDING_DIMENSION


def _validated_model_chunks(raw_chunks: list[dict], expected_dimension: int) -> tuple[list[dict] | None, bool]:
    """Return chunks only when every stored vector matches the active model."""
    try:
        chunks = index._validated_chunks(raw_chunks or [])
    except (ValueError, TypeError, KeyError, OverflowError):
        return None, False
    if not chunks:
        return None, False
    if any(len(chunk["vector"]) != expected_dimension for chunk in chunks):
        return None, True
    return chunks, False


def _scope_candidates(owner: dict, base: dict, *, agent_id: str) -> list[dict]:
    return [row for row in index.list_indexable_knowledge_items(agent_id=agent_id)
            if row["ownerType"] == owner["ownerType"] and row["ownerId"] == owner["ownerId"]
            and row["knowledgeBaseId"] == base["knowledgeBaseId"]]


def _scope_index_coverage(candidates: list[dict], expected_dimension: int) -> tuple[int, int]:
    """Count current, comparable vectors and model-dimension mismatches."""
    indexed = 0
    dimension_mismatches = 0
    with index._LOCK:
        for candidate in candidates:
            record_id = index._record_id_for_item(candidate)
            record = index._read_json(index._item_record_path(record_id)) or {}
            if (record.get("status") != "indexed" or record.get("embeddingModel") != embeddings.DEFAULT_MODEL_NAME
                    or record.get("contentHash") != candidate.get("contentHash")):
                continue
            chunks, dimension_mismatch = _validated_model_chunks(record.get("chunks") or [], expected_dimension)
            if dimension_mismatch:
                dimension_mismatches += 1
            elif chunks:
                indexed += 1
    return indexed, dimension_mismatches


def _chunks(body: str) -> list[dict]:
    rows = []
    for start in range(0, len(body), CHUNK_CHARS - CHUNK_OVERLAP):
        end = min(len(body), start + CHUNK_CHARS)
        rows.append({"start": start, "end": end})
        if end == len(body):
            break
    return rows


def get_semantic_index_health(*, agent_id: str = "", internal: bool = False) -> dict:
    state = embeddings.readiness(cache_dir=_cache_dir())
    candidates = index.list_indexable_knowledge_items(agent_id=agent_id, internal=internal)
    records = {index._record_id_for_item(row): index._read_json(index._item_record_path(index._record_id_for_item(row))) for row in candidates}
    indexed = 0
    dimension_mismatches = 0
    expected_dimension = _model_dimension(state)
    for candidate in candidates:
        row = records.get(index._record_id_for_item(candidate), {})
        if (row.get("status") == "indexed" and row.get("embeddingModel") == embeddings.DEFAULT_MODEL_NAME
                and row.get("contentHash") == candidate["contentHash"]):
            chunks, dimension_mismatch = _validated_model_chunks(row.get("chunks") or [], expected_dimension)
            if dimension_mismatch:
                dimension_mismatches += 1
            elif chunks:
                indexed += 1
    ready = _model_ready(state)
    prepared = bool(state.get("prepared", state.get("cached", ready)))
    loaded = bool(state.get("loaded", state.get("status") == "loaded"))
    fully_indexed = bool(candidates) and indexed == len(candidates)
    reason = (state.get("reason") or ("model_not_prepared" if not prepared else "model_unavailable")) if not ready else (
        "embedding_dimension_mismatch" if dimension_mismatches else
        "missing_or_stale_vectors" if indexed < len(candidates) and candidates else
        "no_indexable_items" if not candidates else ""
    )
    return {"status": "ready" if ready and fully_indexed else "degraded" if ready and (indexed or dimension_mismatches) else "unavailable",
            "reason": reason,
            "embeddingModel": embeddings.DEFAULT_MODEL_NAME, "embeddingProvider": "fastembed",
            "modelPrepared": prepared, "modelLoaded": loaded,
            "indexedItemCount": indexed, "missingItemCount": len(candidates)-indexed,
            "dimensionMismatchCount": dimension_mismatches,
            "indexableItemCount": len(candidates), "vectorEnabled": ready and indexed > 0}


def build_knowledge_index(knowledge_base_id: str, *, agent_id: str, prepare_model: bool = False) -> dict[str, Any]:
    """Build an owner-scoped index only with canonical review permission."""
    owner, base = knowledge._require_base_with_owner(knowledge_base_id)
    knowledge._require_permission(owner, base, agent_id, "review")
    if owner["ownerType"] == "agent" and owner["ownerId"] != agent_id:
        raise knowledge.TeamKnowledgePermissionError("Private knowledge indexing requires its owner.")
    if str(base.get("status") or "active") != "active":
        raise knowledge.TeamKnowledgeError("An archived knowledge base cannot be indexed.")
    if not _BUILD_LOCK.acquire(blocking=False):
        raise knowledge.TeamKnowledgeError("A knowledge index build is already running.")
    try:
        cache = _cache_dir()
        if prepare_model:
            embeddings.prepare(cache_dir=cache)
        state = embeddings.readiness(cache_dir=cache)
        if not _model_ready(state):
            knowledge._record_event("knowledge.semantic_index.build.unavailable", owner, base["knowledgeBaseId"], actor_agent_id=agent_id,
                                    fields={"reason": state.get("reason") or "model_not_prepared", "indexedItemCount": 0})
            return {"status": "unavailable", "model": state, "indexedItemCount": 0, "failedItemCount": 0}
        expected_dimension = _model_dimension(state)
        with knowledge._LOCK:
            candidates = _scope_candidates(owner, base, agent_id=agent_id)
        failed = 0
        for metadata in candidates:
            try:
                _publish_item(knowledge_base_id, metadata, owner=owner, base=base, agent_id=agent_id,
                              expected_dimension=expected_dimension)
            except (ValueError, RuntimeError, knowledge.TeamKnowledgeError):
                failed += 1
        # Re-read the canonical scope after inference and publication. Holding
        # the knowledge lock blocks concurrent governed additions during this
        # snapshot; the nested index lock follows the publisher's lock order.
        with knowledge._LOCK:
            current_candidates = _scope_candidates(owner, base, agent_id=agent_id)
            indexed, dimension_mismatches = _scope_index_coverage(current_candidates, expected_dimension)
            missing = len(current_candidates) - indexed
            status = ("ready" if current_candidates and indexed == len(current_candidates) else
                      "degraded" if current_candidates and (indexed or dimension_mismatches or failed) else
                      "unavailable")
            reason = ("embedding_dimension_mismatch" if dimension_mismatches else
                      "missing_or_stale_vectors" if missing and current_candidates else
                      "no_indexable_items" if not current_candidates else "")
            knowledge._record_event("knowledge.semantic_index.built", owner, base["knowledgeBaseId"], actor_agent_id=agent_id,
                                    fields={"status": status, "reason": reason, "indexedItemCount": indexed,
                                            "failedItemCount": failed, "candidateItemCount": len(current_candidates),
                                            "initialCandidateItemCount": len(candidates), "missingItemCount": missing,
                                            "dimensionMismatchCount": dimension_mismatches,
                                            "embeddingModel": embeddings.DEFAULT_MODEL_NAME})
            return {"status": status,
                    "reason": reason, "indexedItemCount": indexed, "failedItemCount": failed,
                    "candidateItemCount": len(current_candidates), "initialCandidateItemCount": len(candidates),
                    "missingItemCount": missing, "dimensionMismatchCount": dimension_mismatches,
                    "embeddingModel": embeddings.DEFAULT_MODEL_NAME, "knowledgeBaseId": base["knowledgeBaseId"]}
    finally:
        _BUILD_LOCK.release()


def _publish_item(knowledge_base_id: str, metadata: dict, *, owner: dict, base: dict, agent_id: str,
                  expected_dimension: int | None = None) -> bool:
    item = knowledge.get_readable_knowledge_item(knowledge_base_id, metadata["knowledgeItemId"], agent_id=agent_id)
    body = str(item.get("content") or "")
    chunks = _chunks(body)
    texts = [str(item.get("title") or "")[:80] + "\n" + body[row["start"]:row["end"]] for row in chunks]
    vectors = embeddings.encode(texts, purpose="passage", cache_dir=_cache_dir())
    if len(vectors) != len(chunks) or not chunks:
        raise ValueError("Embedding output does not cover the complete knowledge body.")
    if expected_dimension is None:
        expected_dimension = _model_dimension(embeddings.readiness(cache_dir=_cache_dir()))
    if any(len(vector) != expected_dimension for vector in vectors):
        raise ValueError("Embedding output does not match the active model dimension.")
    for chunk, vector in zip(chunks, vectors):
        chunk["vector"] = vector
    with knowledge._LOCK:
        # A concurrent revision, ACL change, base archive, or withdrawal can
        # complete during inference. Re-read every publishing authority while
        # holding the canonical store lock before writing derived vectors.
        current_owner, current_base = knowledge._require_base_with_owner(knowledge_base_id)
        knowledge._require_permission(current_owner, current_base, agent_id, "review")
        if current_owner["ownerType"] == "agent" and current_owner["ownerId"] != agent_id:
            raise knowledge.TeamKnowledgePermissionError("Private knowledge indexing requires its owner.")
        if str(current_base.get("status") or "active") != "active":
            return False
        current = knowledge.get_readable_knowledge_item(
            knowledge_base_id, metadata["knowledgeItemId"], agent_id=agent_id,
        )
        artifacts = {
            row["sourceArtifactId"]: row
            for row in knowledge._source_artifacts_for_base(current_owner, current_base["knowledgeBaseId"])
        }
        current_items = knowledge._read_jsonl(knowledge._items_path_for_owner(current_owner))
        if lifecycle.lifecycle_states_for_base(current_owner, current_base, current_items, artifacts).get(current["knowledgeItemId"]) != "active":
            return False
        if index._content_hash(current) != metadata["contentHash"]:
            return False
        current_metadata = {
            **current,
            "ownerType": current_owner["ownerType"],
            "ownerId": current_owner["ownerId"],
            "contentHash": index._content_hash(current),
        }
        index.write_index_record(current_metadata, embedding_provider="fastembed", embedding_model=embeddings.DEFAULT_MODEL_NAME, chunks=chunks)
    return True


def sync_reviewed_item(knowledge_base_id: str, item: dict, *, agent_id: str) -> dict:
    """Refresh only the applied item, offline; approval remains canonical on index failure."""
    state = embeddings.readiness(cache_dir=_cache_dir())
    if not _model_ready(state):
        return {"status": "unavailable", "reason": "model_not_prepared"}
    try:
        owner, base = knowledge._require_base_with_owner(knowledge_base_id)
        knowledge._require_permission(owner, base, agent_id, "review")
        metadata = {**item, "ownerType": owner["ownerType"], "ownerId": owner["ownerId"], "contentHash": index._content_hash(item)}
        ok = _publish_item(knowledge_base_id, metadata, owner=owner, base=base, agent_id=agent_id,
                           expected_dimension=_model_dimension(state))
        return {"status": "indexed" if ok else "stale", "embeddingModel": embeddings.DEFAULT_MODEL_NAME}
    except (RuntimeError, ValueError, knowledge.TeamKnowledgeError):
        return {"status": "failed", "reason": "index_sync_failed"}


def rank_candidates(candidates: list[dict], query: str, *, mode: str) -> tuple[list[dict], dict]:
    """Cosine/RRF after ACL and lifecycle filtering, with truthful fallback status."""
    state = embeddings.readiness(cache_dir=_cache_dir())
    info = {"status": "unavailable", "requestedMode": mode, "effectiveMode": "bm25" if mode == "hybrid" else "semantic",
            "embeddingModel": embeddings.DEFAULT_MODEL_NAME, "indexedCandidateCount": 0, "missingCandidateCount": len(candidates),
            "dimensionMismatchCount": 0,
            "reason": (state.get("reason") or "model_not_prepared") if not _model_ready(state) else "missing_or_stale_vectors",
            "scope": "formal_knowledge", "impact": "keyword_retrieval_only" if mode == "hybrid" else "semantic_matching_unavailable"}
    lexical = [row for row in _rank_bm25_search_results(candidates, query) if float(row.get("bm25Score") or 0) > 0]
    offline_retryable = bool(state.get("prepared")) and state.get("status") == "load_failed"
    if not candidates or (not _model_ready(state) and not offline_retryable):
        return (lexical if mode == "hybrid" else []), info
    expected_dimension = _model_dimension(state)
    records = {index._record_id_for_item(row): index._read_json(index._item_record_path(index._record_id_for_item(row))) for row in candidates}
    current = []
    dimension_mismatches = 0
    for candidate in candidates:
        record = records.get(index._record_id_for_item(candidate), {})
        if (record.get("status") != "indexed" or record.get("embeddingModel") != embeddings.DEFAULT_MODEL_NAME
                or not candidate.get("_indexContentHash") or record.get("contentHash") != candidate["_indexContentHash"]):
            continue
        chunks, dimension_mismatch = _validated_model_chunks(record.get("chunks") or [], expected_dimension)
        if dimension_mismatch:
            dimension_mismatches += 1
        elif chunks:
            current.append((candidate, chunks))
    if not current:
        if dimension_mismatches:
            info.update(status="degraded", reason="embedding_dimension_mismatch",
                        dimensionMismatchCount=dimension_mismatches,
                        impact="semantic_matching_excludes_dimension_mismatched_vectors")
        return (lexical if mode == "hybrid" else []), info
    try:
        query_vector = embeddings.encode([query], purpose="query", cache_dir=_cache_dir())[0]
        if len(query_vector) != expected_dimension:
            info.update(status="degraded", reason="query_embedding_dimension_mismatch",
                        dimensionMismatchCount=dimension_mismatches,
                        effectiveMode="bm25" if mode == "hybrid" else "semantic",
                        impact="semantic_matching_unavailable_for_current_query")
            return (lexical if mode == "hybrid" else []), info
        norm = math.sqrt(sum(float(value) ** 2 for value in query_vector))
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError("Invalid query vector")
        query_vector = [float(value) / norm for value in query_vector]
    except (RuntimeError, ValueError, IndexError):
        info["errorType"] = "embedding_unavailable"
        info["reason"] = state.get("reason") or "embedding_inference_failed"
        return (lexical if mode == "hybrid" else []), info
    vector_ranked = []
    for candidate, chunks in current:
        matches = [(sum(a*b for a, b in zip(query_vector, row["vector"])), row) for row in chunks if len(row["vector"]) == len(query_vector)]
        if not matches:
            continue
        score, chunk = max(matches, key=lambda pair: pair[0])
        if score <= 0:
            continue
        body = str((candidate.get("_searchDocument") or {}).get("content") or "")
        vector_ranked.append({**candidate, "vectorScore": round(score, 6), "semanticScore": round(score, 6),
                              "matchReason": "vector", "searchMode": mode,
                              "matchedExcerpt": body[chunk["start"]:chunk["end"]], "matchedContentOffset": chunk["start"]})
    vector_ranked.sort(key=lambda row: (-row["vectorScore"], index._record_id_for_item(row)))
    ranking_status = "ready" if len(current) == len(candidates) else "degraded"
    reason = "embedding_dimension_mismatch" if dimension_mismatches else "missing_or_stale_vectors" if len(current) < len(candidates) else ""
    impact = ("semantic_matching_excludes_dimension_mismatched_vectors" if dimension_mismatches else
              "semantic_matching_covers_indexed_candidates_only" if len(current) < len(candidates) else "")
    info.update(status=ranking_status, effectiveMode=mode,
                indexedCandidateCount=len(current), missingCandidateCount=len(candidates)-len(current),
                dimensionMismatchCount=dimension_mismatches, reason=reason, impact=impact)
    if mode == "semantic":
        return vector_ranked, info
    scores, combined = {}, {}
    for ranking in (vector_ranked, lexical):
        for rank, row in enumerate(ranking, 1):
            key = index._record_id_for_item(row)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            combined[key] = {**row, **combined.get(key, {})}
    fused = [{**combined[key], "semanticScore": round(value, 8), "rrfScore": round(value, 8),
              "searchMode": "hybrid", "matchReason": "hybrid_rrf"} for key, value in scores.items()]
    fused.sort(key=lambda row: (-row["rrfScore"], index._record_id_for_item(row)))
    return fused, info
