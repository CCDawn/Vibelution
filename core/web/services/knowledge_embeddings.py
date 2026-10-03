"""Local FastEmbed adapter for knowledge-base dense text embeddings.

This module owns only model preparation and text encoding. Call ``prepare``
explicitly when downloading a model is allowed. Once prepared, ``encode`` can
rebuild the model after a process restart only from the adapter's manifest and
FastEmbed's local cache; it never enables remote downloads.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


DEFAULT_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
FASTEMBED_THREADS = 2
MAX_CACHED_MODELS = 1
MANIFEST_SCHEMA_VERSION = 1

_LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".cache"))
DEFAULT_CACHE_DIR = _LOCAL_APP_DATA / "Vibelution" / "cache" / "fastembed"
_MANIFEST_DIRECTORY = ".vibelution-fastembed"


class EmbeddingError(RuntimeError):
    """Base error for the local knowledge embedding adapter."""


class FastEmbedUnavailableError(EmbeddingError):
    """Raised when FastEmbed or one of its runtime dependencies is missing."""


class EmbeddingModelNotPreparedError(EmbeddingError):
    """Raised when encode is requested before explicit model preparation."""


class EmbeddingInputError(EmbeddingError):
    """Raised when an embedding request has invalid input values."""


class EmbeddingPreparationError(EmbeddingError):
    """Raised when an explicit FastEmbed model preparation fails."""


class EmbeddingOfflineCacheError(EmbeddingError):
    """Raised when a prepared cache cannot initialize without network access."""


class EmbeddingOutputError(EmbeddingError):
    """Raised when FastEmbed returns vectors outside the adapter contract."""


@dataclass(frozen=True)
class _PreparedModel:
    model_name: str
    cache_dir: Path
    cache_key: str
    dimension: int
    model: Any


_MODEL_CACHE: OrderedDict[tuple[str, str], _PreparedModel] = OrderedDict()
_MODEL_LOAD_FAILURES: OrderedDict[tuple[str, str], str] = OrderedDict()
_MODEL_CACHE_LOCK = threading.RLock()


def prepare(
    model_name: str = DEFAULT_MODEL_NAME,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare a FastEmbed model, downloading it only through this explicit call.

    The completed cache identity is recorded beside the FastEmbed cache so a
    later process can verify the local model and initialize it offline.
    """

    normalized_name, normalized_cache_dir, cache_key = _resolve_identity(model_name, cache_dir)
    key = (normalized_name, str(normalized_cache_dir))
    manifest_path = _manifest_path(normalized_cache_dir, cache_key)

    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            _MODEL_CACHE.move_to_end(key)
            return _status_payload(cached, is_prepared=True, loaded=True)

        manifest = _read_manifest(manifest_path, normalized_name, normalized_cache_dir, cache_key)
        if manifest is not None:
            try:
                model = _create_model(
                    normalized_name,
                    normalized_cache_dir,
                    local_files_only=True,
                )
                dimension = _model_dimension(model, normalized_name)
                if dimension != manifest["dimension"]:
                    raise EmbeddingOfflineCacheError(
                        f"Cached FastEmbed model {normalized_name!r} has an unexpected embedding dimension."
                    )
            except FastEmbedUnavailableError:
                raise
            except EmbeddingError:
                _remove_manifest(manifest_path)
            else:
                prepared = _remember_model(
                    key,
                    normalized_name,
                    normalized_cache_dir,
                    cache_key,
                    dimension,
                    model,
                )
                return _status_payload(prepared, is_prepared=True, loaded=True)

        normalized_cache_dir.mkdir(parents=True, exist_ok=True)
        model = _create_model(
            normalized_name,
            normalized_cache_dir,
            local_files_only=False,
        )
        dimension = _model_dimension(model, normalized_name)
        _write_manifest(
            manifest_path,
            model_name=normalized_name,
            cache_dir=normalized_cache_dir,
            cache_key=cache_key,
            dimension=dimension,
        )
        prepared = _remember_model(
            key,
            normalized_name,
            normalized_cache_dir,
            cache_key,
            dimension,
            model,
        )
        return _status_payload(prepared, is_prepared=True, loaded=True)


def encode(
    texts: Sequence[str],
    *,
    purpose: str = "passage",
    model_name: str = DEFAULT_MODEL_NAME,
    cache_dir: str | Path | None = None,
) -> list[list[float]]:
    """Encode text with a prepared model using query or passage semantics.

    This path only reads a previously prepared model manifest and, after a
    process restart, constructs FastEmbed with ``local_files_only=True``.
    It never downloads model weights.
    """

    normalized_name, normalized_cache_dir, cache_key = _resolve_identity(model_name, cache_dir)
    normalized_purpose = str(purpose or "").strip().lower()
    if normalized_purpose not in {"query", "passage"}:
        raise EmbeddingInputError("Embedding purpose must be 'query' or 'passage'.")
    normalized_texts = _normalize_texts(texts)
    key = (normalized_name, str(normalized_cache_dir))

    # Serialize model loading and inference to keep CPU and resident model use
    # bounded. FastEmbed itself is configured with a small fixed thread count.
    with _MODEL_CACHE_LOCK:
        prepared = _MODEL_CACHE.get(key)
        if prepared is None:
            manifest = _read_manifest(
                _manifest_path(normalized_cache_dir, cache_key),
                normalized_name,
                normalized_cache_dir,
                cache_key,
            )
            if manifest is None:
                raise EmbeddingModelNotPreparedError(
                    f"FastEmbed model {normalized_name!r} has not been prepared for this cache directory; "
                    "call prepare(model_name, cache_dir) explicitly first."
                )
            try:
                model = _create_model(
                    normalized_name,
                    normalized_cache_dir,
                    local_files_only=True,
                )
                dimension = _model_dimension(model, normalized_name)
                if dimension != manifest["dimension"]:
                    raise EmbeddingOfflineCacheError(
                        f"Prepared FastEmbed model {normalized_name!r} has an unexpected embedding dimension."
                    )
            except FastEmbedUnavailableError:
                _remember_load_failure(key, "fastembed_unavailable")
                raise
            except EmbeddingOfflineCacheError:
                _remember_load_failure(key, "offline_model_load_failed")
                raise
            except EmbeddingError as error:
                _remember_load_failure(key, "offline_model_load_failed")
                raise EmbeddingOfflineCacheError(
                    f"Prepared FastEmbed model {normalized_name!r} cannot be loaded from its local cache."
                ) from error
            prepared = _remember_model(
                key,
                normalized_name,
                normalized_cache_dir,
                cache_key,
                dimension,
                model,
            )
        else:
            _MODEL_CACHE.move_to_end(key)

        if not normalized_texts:
            return []

        encoder = getattr(prepared.model, f"{normalized_purpose}_embed", None)
        if not callable(encoder):
            raise EmbeddingOutputError(
                f"FastEmbed model {normalized_name!r} does not provide {normalized_purpose}_embed()."
            )
        try:
            raw_vectors = list(encoder(normalized_texts))
        except Exception as error:  # noqa: BLE001 - convert library failures at the adapter boundary
            raise EmbeddingOutputError(
                f"FastEmbed model {normalized_name!r} failed to encode {len(normalized_texts)} text(s)."
            ) from error

        if len(raw_vectors) != len(normalized_texts):
            raise EmbeddingOutputError(
                f"FastEmbed returned {len(raw_vectors)} vector(s) for {len(normalized_texts)} text(s)."
            )

        try:
            vectors = [_normalize_vector(vector) for vector in raw_vectors]
        except EmbeddingError:
            raise
        except Exception as error:  # noqa: BLE001 - keep encode failures within the adapter error contract
            raise EmbeddingOutputError("FastEmbed returned an unreadable embedding vector.") from error
        for vector in vectors:
            if len(vector) != prepared.dimension:
                raise EmbeddingOutputError(
                    f"FastEmbed returned dimension {len(vector)}; expected {prepared.dimension}."
                )
        return vectors


def readiness(
    model_name: str = DEFAULT_MODEL_NAME,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Report whether a model was prepared in memory or in the persistent cache.

    This read-only check does not import FastEmbed, initialize ONNX Runtime, or
    download model files.
    """

    normalized_name, normalized_cache_dir, cache_key = _resolve_identity(model_name, cache_dir)
    key = (normalized_name, str(normalized_cache_dir))
    with _MODEL_CACHE_LOCK:
        loaded = _MODEL_CACHE.get(key)
        if loaded is not None:
            _MODEL_CACHE.move_to_end(key)
            return _status_payload(loaded, is_prepared=True, loaded=True)

        manifest = _read_manifest(
            _manifest_path(normalized_cache_dir, cache_key),
            normalized_name,
            normalized_cache_dir,
            cache_key,
        )
        load_failure = _MODEL_LOAD_FAILURES.get(key)
        if load_failure:
            _MODEL_LOAD_FAILURES.move_to_end(key)
            return {
                "provider": "fastembed",
                "modelName": normalized_name,
                "modelIdentity": f"fastembed:{normalized_name}",
                "cacheDir": str(normalized_cache_dir),
                "cacheKey": cache_key,
                "dimension": int(manifest["dimension"]) if manifest else 0,
                "threads": FASTEMBED_THREADS,
                "prepared": manifest is not None,
                "ready": False,
                "loaded": False,
                "status": "load_failed",
                "reason": load_failure,
                "manifestPath": str(_manifest_path(normalized_cache_dir, cache_key)),
            }
        return {
            "provider": "fastembed",
            "modelName": normalized_name,
            "modelIdentity": f"fastembed:{normalized_name}",
            "cacheDir": str(normalized_cache_dir),
            "cacheKey": cache_key,
            "dimension": int(manifest["dimension"]) if manifest else 0,
            "threads": FASTEMBED_THREADS,
            "prepared": manifest is not None,
            "ready": manifest is not None,
            "loaded": False,
            "status": "cached" if manifest is not None else "not_prepared",
            "manifestPath": str(_manifest_path(normalized_cache_dir, cache_key)),
        }


def _resolve_identity(model_name: str, cache_dir: str | Path | None) -> tuple[str, Path, str]:
    normalized_name = str(model_name or "").strip()
    if not normalized_name:
        raise EmbeddingInputError("A FastEmbed model name is required.")
    try:
        normalized_cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else DEFAULT_CACHE_DIR
        normalized_cache_dir = normalized_cache_dir.resolve()
    except (OSError, TypeError, ValueError) as error:
        raise EmbeddingInputError("The FastEmbed cache directory is invalid.") from error
    identity = f"{normalized_name}\0{normalized_cache_dir}"
    cache_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return normalized_name, normalized_cache_dir, cache_key


def _normalize_texts(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes)):
        raise EmbeddingInputError("texts must be a sequence of strings, not one string.")
    try:
        values = list(texts)
    except TypeError as error:
        raise EmbeddingInputError("texts must be a sequence of strings.") from error
    if any(not isinstance(value, str) for value in values):
        raise EmbeddingInputError("Every value in texts must be a string.")
    return values


def _load_text_embedding_class() -> type[Any]:
    try:
        module = importlib.import_module("fastembed")
    except (ImportError, ModuleNotFoundError) as error:
        raise FastEmbedUnavailableError(
            "FastEmbed is unavailable. Install the project's FastEmbed dependency before preparing embeddings."
        ) from error
    text_embedding = getattr(module, "TextEmbedding", None)
    if text_embedding is None:
        raise FastEmbedUnavailableError("The installed FastEmbed package does not expose TextEmbedding.")
    return text_embedding


def _create_model(model_name: str, cache_dir: Path, *, local_files_only: bool) -> Any:
    try:
        embedding_class = _load_text_embedding_class()
        return embedding_class(
            model_name=model_name,
            cache_dir=str(cache_dir),
            threads=FASTEMBED_THREADS,
            local_files_only=local_files_only,
        )
    except FastEmbedUnavailableError:
        raise
    except Exception as error:  # noqa: BLE001 - translate FastEmbed setup failures
        if local_files_only:
            raise EmbeddingOfflineCacheError(
                f"FastEmbed model {model_name!r} could not be initialized from its local cache."
            ) from error
        raise EmbeddingPreparationError(
            f"FastEmbed model {model_name!r} could not be prepared in the requested cache directory."
        ) from error


def _model_dimension(model: Any, model_name: str) -> int:
    try:
        dimension = int(getattr(model, "embedding_size"))
    except (AttributeError, OverflowError, TypeError, ValueError) as error:
        raise EmbeddingPreparationError(
            f"FastEmbed model {model_name!r} does not expose a valid embedding dimension."
        ) from error
    if dimension < 1:
        raise EmbeddingPreparationError(
            f"FastEmbed model {model_name!r} returned an invalid embedding dimension."
        )
    return dimension


def _normalize_vector(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    if not isinstance(vector, (list, tuple)) or not vector:
        raise EmbeddingOutputError("FastEmbed returned an empty or non-vector embedding.")
    if any(isinstance(value, (list, tuple)) for value in vector):
        raise EmbeddingOutputError("FastEmbed returned a nested embedding instead of a single vector.")
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError, OverflowError) as error:
        raise EmbeddingOutputError("FastEmbed returned a non-numeric embedding value.") from error
    if any(not math.isfinite(value) for value in values):
        raise EmbeddingOutputError("FastEmbed returned a non-finite embedding value.")
    if not any(value != 0.0 for value in values):
        raise EmbeddingOutputError("FastEmbed returned an all-zero embedding.")
    return values


def _remember_model(
    key: tuple[str, str],
    model_name: str,
    cache_dir: Path,
    cache_key: str,
    dimension: int,
    model: Any,
) -> _PreparedModel:
    _MODEL_LOAD_FAILURES.pop(key, None)
    prepared = _PreparedModel(
        model_name=model_name,
        cache_dir=cache_dir,
        cache_key=cache_key,
        dimension=dimension,
        model=model,
    )
    _MODEL_CACHE[key] = prepared
    _MODEL_CACHE.move_to_end(key)
    while len(_MODEL_CACHE) > MAX_CACHED_MODELS:
        _MODEL_CACHE.popitem(last=False)
    return prepared


def _remember_load_failure(key: tuple[str, str], reason: str) -> None:
    _MODEL_LOAD_FAILURES[key] = reason
    _MODEL_LOAD_FAILURES.move_to_end(key)
    while len(_MODEL_LOAD_FAILURES) > MAX_CACHED_MODELS:
        _MODEL_LOAD_FAILURES.popitem(last=False)


def _manifest_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / _MANIFEST_DIRECTORY / f"{cache_key}.json"


def _read_manifest(path: Path, model_name: str, cache_dir: Path, cache_key: str) -> dict[str, Any] | None:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        return None
    if manifest.get("provider") != "fastembed":
        return None
    if manifest.get("modelName") != model_name or manifest.get("cacheDir") != str(cache_dir):
        return None
    if manifest.get("cacheKey") != cache_key:
        return None
    try:
        dimension = int(manifest.get("dimension") or 0)
    except (TypeError, ValueError):
        return None
    if dimension < 1:
        return None
    return {**manifest, "dimension": dimension}


def _write_manifest(
    path: Path,
    *,
    model_name: str,
    cache_dir: Path,
    cache_key: str,
    dimension: int,
) -> None:
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "provider": "fastembed",
        "modelName": model_name,
        "cacheDir": str(cache_dir),
        "cacheKey": cache_key,
        "dimension": dimension,
        "threads": FASTEMBED_THREADS,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(manifest, temporary, ensure_ascii=False, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _remove_manifest(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _status_payload(model: _PreparedModel, *, is_prepared: bool, loaded: bool) -> dict[str, Any]:
    return {
        "provider": "fastembed",
        "modelName": model.model_name,
        "modelIdentity": f"fastembed:{model.model_name}",
        "cacheDir": str(model.cache_dir),
        "cacheKey": model.cache_key,
        "dimension": model.dimension,
        "threads": FASTEMBED_THREADS,
        "prepared": is_prepared,
        "ready": is_prepared,
        "loaded": loaded,
        "status": "loaded" if loaded else "cached" if is_prepared else "not_prepared",
        "manifestPath": str(_manifest_path(model.cache_dir, model.cache_key)),
    }
