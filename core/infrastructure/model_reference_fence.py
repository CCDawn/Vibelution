"""Operator-config-domain fence shared by reference writers and removals.

Only entry acquires a lock or resolves operator configuration. Import is pure.
SQLite callers must enter on the writer execution thread and retain the fence
through COMMIT/ROLLBACK; submitting work while holding it would self-deadlock.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import threading
import tomllib

from core.infrastructure.file_lock import cross_process_file_lock

_LOCAL = threading.local()


class PublicModelReferenceResolver:
    """Pure public metadata view of the native, case-sensitive alias graph."""

    def __init__(self, public_config):
        from config.models import LLMConfig
        from config.llm_identity import make_model_ref
        llm = public_config.get("llm", {})
        self.providers = llm.get("providers", {})
        aliases = llm.get("model_aliases", {})
        if (not isinstance(self.providers, dict) or not isinstance(aliases, dict) or len(aliases) > 10_000
                or any(not isinstance(key, str) or not 1 <= len(key) <= 320 or key != key.strip()
                       or not isinstance(value, str) or not 1 <= len(value.strip()) <= 320
                       for key, value in aliases.items())):
            raise ValueError("Public model alias metadata is unavailable")
        self.aliases = dict(aliases)
        self.models = set()
        for provider, record in self.providers.items():
            if not isinstance(record, dict) or not isinstance(record.get("models", {}), dict):
                raise ValueError("Public provider metadata is unavailable")
            for key, entry in record.get("models", {}).items():
                if not isinstance(entry, dict):
                    raise ValueError("Public model metadata is unavailable")
                self.models.add(make_model_ref(provider, key))
        self._resolver = LLMConfig.model_construct(model_aliases=self.aliases)
        self._canonical_cache = {}
        # Validate structure/cycles, but an unused alias is not a live model
        # binding. Native unpin leaves alias records in place, including ones
        # whose former qualified target no longer exists.
        for alias in self.aliases:
            self.canonical(alias, require_existing=False)

    def canonical(self, raw, *, require_existing=True):
        from config.llm_identity import make_model_ref, split_model_ref
        if not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 320:
            raise ValueError("Invalid model reference metadata")
        requested = raw.strip()
        canonical = self._canonical_cache.get(requested)
        if canonical is None:
            resolved = self._resolver.resolve_model_ref(requested)
            canonical = make_model_ref(*split_model_ref(resolved))
            self._canonical_cache[requested] = canonical
        if require_existing and canonical not in self.models:
            raise ValueError("Unresolved public model reference")
        return canonical

    def available(self, canonical):
        if canonical not in self.models:
            return False
        provider, key = canonical.split("/", 1)
        record = self.providers[provider]
        return record.get("enabled", True) is True and record["models"][key].get("enabled", True) is True


@dataclass
class ModelReferenceFenceLease:
    config_path: Path
    _key: str
    _thread: int
    _active: bool = True

    def assert_owned(self):
        if (not self._active or threading.get_ident() != self._thread
                or getattr(_LOCAL, "depths", {}).get(self._key, 0) < 1):
            raise RuntimeError("Model reference fence is not owned by this thread")


@contextmanager
def model_reference_fence(config_path: Path | None = None):
    from config.paths import resolve_config_path
    path = Path(resolve_config_path() if config_path is None else config_path)
    if not path.is_absolute():
        raise ValueError("Operator configuration path must be absolute")
    path = path.resolve()
    key = os.path.normcase(str(path))
    depths = getattr(_LOCAL, "depths", None)
    if depths is None:
        depths = _LOCAL.depths = {}
    lease = ModelReferenceFenceLease(path, key, threading.get_ident())
    if depths.get(key, 0):
        depths[key] += 1
        try:
            yield lease
        finally:
            lease._active = False
            depths[key] -= 1
        return
    # Config order is Fence -> Config. Native metadata order is owner State /
    # Store -> Fence, and SQLite acquires Fence on its execution thread before
    # BEGIN. A deleting owner must never enter State/Store or queue a writer.
    with cross_process_file_lock(Path(str(path) + ".model-references"), timeout=10):
        depths[key] = 1
        try:
            yield lease
        finally:
            lease._active = False
            depths.pop(key, None)


model_reference_writer_fence = model_reference_fence


def model_reference_fence_owned(config_path=None):
    path = _config_path(config_path)
    return getattr(_LOCAL, "depths", {}).get(os.path.normcase(str(path)), 0) > 0


def _config_path(config_path=None):
    from config.paths import resolve_config_path
    return Path(resolve_config_path() if config_path is None else config_path).resolve()


def _retirement_path(config_path):
    key = hashlib.sha256(os.path.normcase(str(config_path)).encode("utf-8")).hexdigest()
    return config_path.parent / ".model-reference-retirements" / (key + ".json")


def _retirements(config_path):
    from core.assistant_runtime.migration_io import read_stable_file, strict_json
    path = _retirement_path(config_path)
    try:
        path.lstat()
    except FileNotFoundError:
        return {"schemaVersion": 2, "revision": 0, "retiredModels": {}, "retiredAliases": {}}
    data = strict_json(read_stable_file(path, 2 * 1024 * 1024).raw)
    if (not isinstance(data, dict)
            or type(data.get("schemaVersion")) is not int or data["schemaVersion"] not in {1, 2}
            or set(data) != ({"schemaVersion", "revision", "retiredModels"} if data["schemaVersion"] == 1
                             else {"schemaVersion", "revision", "retiredModels", "retiredAliases"})
            or type(data["revision"]) is not int or data["revision"] < 0
            or not isinstance(data["retiredModels"], dict) or len(data["retiredModels"]) > 10_000):
        raise ValueError("Model reference retirement authority is unavailable")
    for model, record in data["retiredModels"].items():
        if (not isinstance(model, str) or not 1 <= len(model) <= 320
                or not isinstance(record, dict) or set(record) != {"configHash", "reason"}
                or not isinstance(record["configHash"], str) or len(record["configHash"]) != 64
                or any(char not in "0123456789abcdef" for char in record["configHash"])
                or record["reason"] not in {"guarded_model_change", "guarded_provider_change"}):
            raise ValueError("Invalid model reference retirement proof")
    aliases = data.setdefault("retiredAliases", {})
    if (not isinstance(aliases, dict) or len(aliases) > 10_000
            or any(not isinstance(alias, str) or not 1 <= len(alias) <= 320 or alias != alias.strip()
                   or not isinstance(targets, list) or not targets or len(targets) > 10_000
                   or any(not isinstance(model, str) or model not in data["retiredModels"] for model in targets)
                   or len(set(targets)) != len(targets) for alias, targets in aliases.items())
            or sum(len(targets) for targets in aliases.values()) > 20_000):
        raise ValueError("Invalid retired model alias lineage")
    return data


def record_model_retirements(model_ids, *, config_hash, reason, config_path=None):
    """Write-ahead safety metadata; caller must retain the reference fence."""
    from core.infrastructure.atomic_io import atomic_write_json
    path = _config_path(config_path)
    if getattr(_LOCAL, "depths", {}).get(os.path.normcase(str(path)), 0) < 1:
        raise RuntimeError("Model reference fence is required for retirement")
    data = _retirements(path)
    from core.assistant_runtime.migration_io import read_stable_file
    snapshot = read_stable_file(path, 16 * 1024 * 1024)
    if snapshot.sha256 != config_hash:
        raise ValueError("Model retirement config changed before lineage capture")
    resolver = PublicModelReferenceResolver(tomllib.loads(snapshot.raw.decode("utf-8")))
    affected = set(model_ids)
    if not affected.issubset(resolver.models):
        raise ValueError("Unknown model retirement target")
    for model in affected:
        data["retiredModels"][model] = {"configHash": config_hash, "reason": reason}
    for alias in resolver.aliases:
        canonical = resolver.canonical(alias, require_existing=False)
        if canonical in affected:
            data["retiredAliases"][alias] = sorted(set(data["retiredAliases"].get(alias, [])) | {canonical})
    if (len(data["retiredModels"]) > 10_000 or len(data["retiredAliases"]) > 10_000
            or sum(len(targets) for targets in data["retiredAliases"].values()) > 20_000):
        raise ValueError("Model retirement authority exceeds limit")
    data["schemaVersion"] = 2
    data["revision"] += 1
    import json
    if len(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Model retirement authority exceeds byte limit")
    # Durable before configuration removal, so a queued writer cannot pass
    # after deletion. Failed commits leave harmless evidence: current config
    # is always re-read before a matching addition is rejected.
    atomic_write_json(_retirement_path(path), data, strict_replace=True)
    _retirements(path)


def unavailable_retired_models(config_path=None):
    """Only retired IDs consult live config; opaque legacy IDs keep semantics."""
    from core.assistant_runtime.migration_io import read_stable_file
    path = _config_path(config_path)
    if getattr(_LOCAL, "depths", {}).get(os.path.normcase(str(path)), 0) < 1:
        raise RuntimeError("Model reference fence is required for writer validation")
    data = _retirements(path)
    retired, historical_aliases = data["retiredModels"], data["retiredAliases"]
    if not retired:
        return frozenset()
    config = tomllib.loads(read_stable_file(path, 16 * 1024 * 1024).raw.decode("utf-8"))
    resolver = PublicModelReferenceResolver(config)
    unavailable = set()
    # Return raw identifiers that a queued native writer can introduce. This
    # includes current aliases and the persisted pre-removal lineage, so a
    # cleared alias can never fall back to an unmarked opaque legacy ID.
    for raw in set(retired) | set(resolver.aliases) | set(historical_aliases):
        try:
            canonical = resolver.canonical(raw, require_existing=False)
        except ValueError:
            if raw in historical_aliases or raw in retired:
                unavailable.add(raw)
        else:
            if not resolver.available(canonical) and (canonical in retired or raw in historical_aliases or raw in retired):
                unavailable.add(raw)
    return frozenset(unavailable)


def assert_model_reference_additions(before, after, *, config_path=None):
    """Reject only newly introduced owner/field references to retired models."""
    blocked = unavailable_retired_models(config_path)
    if any((value[-1] if isinstance(value, tuple) else value) in blocked for value in set(after) - set(before)):
        raise ValueError("Referenced model was removed or disabled before this writer committed")


def metadata_binding_reference_keys(payload, *, surface):
    """Declared model metadata only; never walk Prompt/task/body fields."""
    result = set()
    def binding(row, owner):
        if not isinstance(row, dict):
            return
        for field in ("modelId", "dialogueModelId", "agentTemplateLabel"):
            if isinstance(row.get(field), str) and row[field].strip():
                result.add((owner, field, row[field].strip()))
        slots = row.get("llmBindings", {})
        if isinstance(slots, dict):
            for slot, value in slots.items():
                if isinstance(value, dict) and isinstance(value.get("modelId"), str) and value["modelId"].strip():
                    result.add((owner, "llmBindings." + str(slot), value["modelId"].strip()))
    if not isinstance(payload, dict):
        return result
    if surface == "agents":
        for index, row in enumerate(payload.get("agents", []) or []):
            binding(row, str(row.get("agentId", index)) if isinstance(row, dict) else str(index))
    elif surface == "rooms":
        for index, room in enumerate(payload.get("rooms", []) or []):
            if isinstance(room, dict):
                for participant_index, row in enumerate(room.get("participants", []) or []):
                    binding(row, f"{room.get('roomId', index)}:{participant_index}")
    elif surface == "team_policy":
        binding(payload.get("promptCachePolicy"), "prompt_cache")
    elif surface == "supervised":
        binding(payload.get("currentAgentBinding"), "current")
        for key, value in (payload.get("agentBindings", {}) or {}).items():
            binding(value, str(key))
    else:
        raise ValueError("Unknown canonical model reference surface")
    return result


def commit_reference_metadata(path, payload, *, surface, write):
    """Final JSON commit gate; caller already holds its native owner lock.

    Agent owner order is State -> Fence. This helper never calls Agent state,
    queues SQLite work or takes another subsystem lock. The removal path must
    use raw metadata readers and must not acquire State while holding Fence.
    """
    from core.assistant_runtime.migration_io import read_stable_file, strict_json
    with model_reference_fence():
        if unavailable_retired_models():
            path = Path(path)
            try:
                path.lstat()
            except FileNotFoundError:
                before = {}
            else:
                before = strict_json(read_stable_file(path, 16 * 1024 * 1024).raw)
                if not isinstance(before, dict):
                    raise ValueError("Reference writer source metadata is unavailable")
            assert_model_reference_additions(metadata_binding_reference_keys(before, surface=surface),
                metadata_binding_reference_keys(payload, surface=surface))
        return write()
