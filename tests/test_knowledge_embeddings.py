from collections import OrderedDict

import pytest

from core.web.services import knowledge_embeddings


@pytest.fixture(autouse=True)
def _clear_embedding_cache(monkeypatch):
    monkeypatch.setattr(knowledge_embeddings, "_MODEL_CACHE", OrderedDict())
    if hasattr(knowledge_embeddings, "_MODEL_LOAD_FAILURES"):
        monkeypatch.setattr(knowledge_embeddings, "_MODEL_LOAD_FAILURES", OrderedDict())


def _fake_text_embedding_class(calls, *, query_vectors=None, passage_vectors=None):
    class FakeTextEmbedding:
        def __init__(self, *, model_name, cache_dir, threads, local_files_only):
            calls.append(
                {
                    "model_name": model_name,
                    "cache_dir": cache_dir,
                    "threads": threads,
                    "local_files_only": local_files_only,
                }
            )
            self.embedding_size = 3

        def query_embed(self, texts):
            calls.append({"purpose": "query", "texts": list(texts)})
            vectors = query_vectors
            if vectors is None:
                vectors = [[1.0, 0.0, 0.0] for _ in texts]
            return iter(vectors)

        def passage_embed(self, texts):
            calls.append({"purpose": "passage", "texts": list(texts)})
            vectors = passage_vectors
            if vectors is None:
                vectors = [[0.0, 1.0, 0.0] for _ in texts]
            return iter(vectors)

    return FakeTextEmbedding


def test_encode_requires_an_explicitly_prepared_model(tmp_path, monkeypatch):
    def unexpected_import():
        pytest.fail("encode must not import or initialize FastEmbed without a cache manifest")

    monkeypatch.setattr(knowledge_embeddings, "_load_text_embedding_class", unexpected_import)

    with pytest.raises(knowledge_embeddings.EmbeddingModelNotPreparedError, match="call prepare"):
        knowledge_embeddings.encode(
            ["知识检索"],
            purpose="query",
            cache_dir=tmp_path / "cache",
        )


def test_prepare_and_encode_use_purpose_specific_fastembed_methods(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(calls),
    )
    cache_dir = tmp_path / "model-cache"

    status = knowledge_embeddings.prepare(cache_dir=cache_dir)
    queries = knowledge_embeddings.encode(["查找知识"], purpose="query", cache_dir=cache_dir)
    passages = knowledge_embeddings.encode(["知识内容"], purpose="passage", cache_dir=cache_dir)

    assert status["provider"] == "fastembed"
    assert status["modelName"] == "BAAI/bge-small-zh-v1.5"
    assert status["dimension"] == 3
    assert status["threads"] == 2
    assert status["prepared"] is True
    assert status["loaded"] is True
    assert calls[0]["local_files_only"] is False
    assert calls[0]["threads"] == 2
    assert calls[0]["cache_dir"] == str(cache_dir.resolve())
    assert calls[1]["purpose"] == "query"
    assert calls[2]["purpose"] == "passage"
    assert queries == [[1.0, 0.0, 0.0]]
    assert passages == [[0.0, 1.0, 0.0]]
    assert all(type(value) is float for vector in queries + passages for value in vector)


def test_prepared_manifest_rebuilds_model_offline_after_process_restart(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(calls),
    )
    cache_dir = tmp_path / "model-cache"

    knowledge_embeddings.prepare(cache_dir=cache_dir)
    monkeypatch.setattr(knowledge_embeddings, "_MODEL_CACHE", OrderedDict())

    status = knowledge_embeddings.readiness(cache_dir=cache_dir)
    assert len(calls) == 1
    vectors = knowledge_embeddings.encode(["本地缓存"], purpose="query", cache_dir=cache_dir)

    assert status["prepared"] is True
    assert status["ready"] is True
    assert status["loaded"] is False
    assert status["status"] == "cached"
    assert calls[1]["local_files_only"] is True
    assert vectors == [[1.0, 0.0, 0.0]]


def test_encode_never_falls_back_to_download_when_offline_cache_is_unavailable(tmp_path, monkeypatch):
    initial_calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(initial_calls),
    )
    cache_dir = tmp_path / "model-cache"
    knowledge_embeddings.prepare(cache_dir=cache_dir)
    monkeypatch.setattr(knowledge_embeddings, "_MODEL_CACHE", OrderedDict())

    calls = []

    class MissingCachedModel:
        def __init__(self, *, model_name, cache_dir, threads, local_files_only):
            calls.append(local_files_only)
            if not local_files_only:
                pytest.fail("encode must never retry with network-enabled model loading")
            raise OSError("model files are absent")

    monkeypatch.setattr(knowledge_embeddings, "_load_text_embedding_class", lambda: MissingCachedModel)

    with pytest.raises(knowledge_embeddings.EmbeddingOfflineCacheError):
        knowledge_embeddings.encode(["本地查询"], purpose="query", cache_dir=cache_dir)

    assert calls == [True]


def test_offline_load_failure_is_reported_without_blocking_offline_retry(tmp_path, monkeypatch):
    initial_calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(initial_calls),
    )
    cache_dir = tmp_path / "model-cache"
    knowledge_embeddings.prepare(cache_dir=cache_dir)
    monkeypatch.setattr(knowledge_embeddings, "_MODEL_CACHE", OrderedDict())

    load_attempts = []
    loader_calls = []

    class BrokenCachedModel:
        def __init__(self, *, model_name, cache_dir, threads, local_files_only):
            load_attempts.append(local_files_only)
            if not local_files_only:
                pytest.fail("An implicit model load must never enable downloads")
            raise OSError("model files are temporarily unavailable")

    def load_broken_cached_model():
        loader_calls.append(True)
        return BrokenCachedModel

    monkeypatch.setattr(knowledge_embeddings, "_load_text_embedding_class", load_broken_cached_model)
    with pytest.raises(knowledge_embeddings.EmbeddingOfflineCacheError):
        knowledge_embeddings.encode(["本地查询"], purpose="query", cache_dir=cache_dir)

    status = knowledge_embeddings.readiness(cache_dir=cache_dir)
    assert status["prepared"] is True
    assert status["ready"] is False
    assert status["loaded"] is False
    assert status["status"] == "load_failed"
    assert load_attempts == [True]
    assert loader_calls == [True]

    retry_calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(retry_calls),
    )
    vectors = knowledge_embeddings.encode(["再次本地查询"], purpose="query", cache_dir=cache_dir)

    assert vectors == [[1.0, 0.0, 0.0]]
    assert retry_calls[0]["local_files_only"] is True
    recovered = knowledge_embeddings.readiness(cache_dir=cache_dir)
    assert recovered["prepared"] is True
    assert recovered["ready"] is True
    assert recovered["loaded"] is True


def test_explicit_prepare_can_recover_after_known_offline_load_failure(tmp_path, monkeypatch):
    initial_calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(initial_calls),
    )
    cache_dir = tmp_path / "model-cache"
    knowledge_embeddings.prepare(cache_dir=cache_dir)
    monkeypatch.setattr(knowledge_embeddings, "_MODEL_CACHE", OrderedDict())

    load_modes = []

    class RecoverableModel:
        def __init__(self, *, model_name, cache_dir, threads, local_files_only):
            load_modes.append(local_files_only)
            if local_files_only:
                raise OSError("local weights need an explicit refresh")
            self.embedding_size = 3

        def query_embed(self, texts):
            return iter([[1.0, 0.0, 0.0] for _ in texts])

    monkeypatch.setattr(knowledge_embeddings, "_load_text_embedding_class", lambda: RecoverableModel)
    with pytest.raises(knowledge_embeddings.EmbeddingOfflineCacheError):
        knowledge_embeddings.encode(["本地查询"], purpose="query", cache_dir=cache_dir)
    assert knowledge_embeddings.readiness(cache_dir=cache_dir)["ready"] is False

    status = knowledge_embeddings.prepare(cache_dir=cache_dir)

    assert load_modes == [True, True, False]
    assert status["prepared"] is True and status["loaded"] is True
    assert knowledge_embeddings.readiness(cache_dir=cache_dir)["ready"] is True


def test_prepare_separates_model_and_cache_identities_with_bounded_memory(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(calls),
    )
    first_cache = tmp_path / "first-cache"
    second_cache = tmp_path / "second-cache"

    first = knowledge_embeddings.prepare("model-a", first_cache)
    second = knowledge_embeddings.prepare("model-a", second_cache)
    third = knowledge_embeddings.prepare("model-b", first_cache)

    assert len({first["cacheKey"], second["cacheKey"], third["cacheKey"]}) == 3
    assert len(knowledge_embeddings._MODEL_CACHE) <= knowledge_embeddings.MAX_CACHED_MODELS
    assert knowledge_embeddings.readiness("model-a", first_cache)["prepared"] is True
    assert knowledge_embeddings.readiness("model-a", first_cache)["loaded"] is False
    assert knowledge_embeddings.readiness("model-b", first_cache)["loaded"] is True


def test_prepare_reports_a_missing_fastembed_dependency(tmp_path, monkeypatch):
    def missing_dependency():
        raise knowledge_embeddings.FastEmbedUnavailableError("FastEmbed is unavailable.")

    monkeypatch.setattr(knowledge_embeddings, "_load_text_embedding_class", missing_dependency)

    with pytest.raises(knowledge_embeddings.FastEmbedUnavailableError, match="unavailable"):
        knowledge_embeddings.prepare(cache_dir=tmp_path / "cache")


@pytest.mark.parametrize(
    ("vectors", "message"),
    [
        ([], r"vector\(s\)"),
        ([[float("nan"), 0.0, 0.0]], "non-finite"),
        ([[0.0, 0.0, 0.0]], "all-zero"),
        ([[0.0, 1.0]], "dimension 2"),
    ],
)
def test_encode_rejects_invalid_fastembed_vectors(tmp_path, monkeypatch, vectors, message):
    calls = []
    monkeypatch.setattr(
        knowledge_embeddings,
        "_load_text_embedding_class",
        lambda: _fake_text_embedding_class(calls, query_vectors=vectors),
    )
    cache_dir = tmp_path / "model-cache"
    knowledge_embeddings.prepare(cache_dir=cache_dir)

    with pytest.raises(knowledge_embeddings.EmbeddingOutputError, match=message):
        knowledge_embeddings.encode(["query"], purpose="query", cache_dir=cache_dir)


def test_encode_rejects_unsupported_purpose(tmp_path):
    with pytest.raises(knowledge_embeddings.EmbeddingInputError, match="query.*passage"):
        knowledge_embeddings.encode(["query"], purpose="similarity", cache_dir=tmp_path / "cache")
