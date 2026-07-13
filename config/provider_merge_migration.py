"""Previewed, verified and reversible schema-v2 Provider consolidation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import tomllib
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config.llm_credentials import canonicalize_credential_ref
from config.llm_identity import make_model_key, validate_provider_id
from config.operator_config_transaction import (
    TransactionParticipant,
    append_toml_table,
    apply_operator_config_transaction,
    prepare_operator_config_transaction,
    remove_toml_table_tree,
    replace_toml_scalar,
)
from config.paths import resolve_config_backup_dir
from config.public_config import CONFIG_PATH, load_public_config, public_config_hash
from core.llm.provider_discovery.service import discover_provider_models
from core.web.services.config_service import run_draft_llm_test
from core.web.services.model_reference_service import (
    ModelReferenceRewritePlan,
    build_model_reference_rewrite_plan,
    scan_model_references,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PREVIEW_TTL_SECONDS = 600.0
_PREVIEWS: dict[str, tuple[float, "ProviderMergePreview"]] = {}
_PREVIEW_LOCK = threading.Lock()
_REQUIRED_UPSTREAM_IDS = frozenset(
    {"gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"}
)


class ProviderMergeError(ValueError):
    """Base class for bounded Provider merge failures."""


class ProviderMergeConflictError(ProviderMergeError):
    """Raised when preview state no longer matches durable state."""


class ProviderMergeVerificationError(ProviderMergeError):
    """Raised when discovery or the bounded model call cannot be verified."""


@dataclass(frozen=True)
class ProviderMergePreview:
    preview_id: str
    status: str
    base_hash: str
    canonical_provider_id: str
    duplicate_provider_ids: tuple[str, ...]
    model_ref_map: dict[str, str]
    models_to_add: tuple[dict[str, Any], ...]
    live_references: tuple[dict[str, Any], ...]
    historical_references: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, str], ...]
    required_probe_model_ref: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            "previewId": payload["preview_id"],
            "status": payload["status"],
            "baseHash": payload["base_hash"],
            "canonicalProviderId": payload["canonical_provider_id"],
            "duplicateProviderIds": list(payload["duplicate_provider_ids"]),
            "modelRefMap": payload["model_ref_map"],
            "modelsToAdd": [
                {
                    "modelKey": str(item.get("modelKey") or ""),
                    "sourceProviderId": str(item.get("sourceProviderId") or ""),
                }
                for item in payload["models_to_add"]
            ],
            "liveReferences": list(payload["live_references"][:50]),
            "historicalReferences": list(payload["historical_references"][:50]),
            "liveReferenceCount": len(payload["live_references"]),
            "historicalReferenceCount": len(payload["historical_references"]),
            "conflicts": list(payload["conflicts"]),
            "requiredProbeModelRef": payload["required_probe_model_ref"],
        }


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_atomic_write(path: Path, payload: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _purge_expired_previews(now: float) -> None:
    for preview_id, (expires_at, _) in list(_PREVIEWS.items()):
        if expires_at <= now:
            _PREVIEWS.pop(preview_id, None)


def _provider_contract(provider: dict[str, Any]) -> dict[str, Any]:
    discovery = provider.get("discovery")
    return {
        "base_url": str(provider.get("base_url") or "").strip(),
        "driver": str(provider.get("driver") or "").strip().lower(),
        "service_class": str(provider.get("service_class") or "").strip().lower(),
        "auth_kind": str(provider.get("auth_kind") or "api_key").strip().lower(),
        "requires_credential": provider.get("requires_credential", True) is not False,
        "protocols": provider.get("protocols")
        if isinstance(provider.get("protocols"), dict)
        else {},
        "discovery_adapter": str(
            discovery.get("adapter") if isinstance(discovery, dict) else "manual"
        )
        .strip()
        .lower(),
    }


def _target_model_key(
    canonical_models: dict[str, Any], duplicate_key: str, duplicate_model: dict[str, Any]
) -> tuple[str, bool]:
    upstream_id = str(duplicate_model.get("upstream_id") or "").strip()
    if not upstream_id:
        raise ProviderMergeConflictError("duplicate model upstream_id is required")
    for model_key, model in canonical_models.items():
        if isinstance(model, dict) and str(model.get("upstream_id") or "").strip() == upstream_id:
            return str(model_key), False
    candidate = make_model_key(upstream_id)
    if candidate in canonical_models:
        raise ProviderMergeConflictError(
            f"canonical model key collision: {candidate}"
        )
    return candidate, True


def _public_reference_patches(
    text: str, source: dict[str, Any], mapping: dict[str, str]
) -> str:
    candidate = text
    llm = source.get("llm") if isinstance(source.get("llm"), dict) else {}
    profiles = llm.get("profiles") if isinstance(llm.get("profiles"), dict) else {}
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        current = str(profile.get("model_ref") or "").strip()
        if current in mapping:
            candidate = replace_toml_scalar(
                candidate,
                ("llm", "profiles", str(profile_id)),
                "model_ref",
                current,
                mapping[current],
            )
    tools = source.get("tools") if isinstance(source.get("tools"), dict) else {}
    image2 = tools.get("image2") if isinstance(tools.get("image2"), dict) else {}
    image_model = str(image2.get("default_model_ref") or "").strip()
    if image_model in mapping:
        candidate = replace_toml_scalar(
            candidate,
            ("tools", "image2"),
            "default_model_ref",
            image_model,
            mapping[image_model],
        )
    git = source.get("git") if isinstance(source.get("git"), dict) else {}
    git_model = str(git.get("commit_message_model_ref") or "").strip()
    if git_model in mapping:
        candidate = replace_toml_scalar(
            candidate,
            ("git",),
            "commit_message_model_ref",
            git_model,
            mapping[git_model],
        )
    return candidate


def _verification_text(text: str, preview: ProviderMergePreview) -> str:
    candidate = text
    for item in preview.models_to_add:
        candidate = append_toml_table(
            candidate,
            (
                "llm",
                "providers",
                preview.canonical_provider_id,
                "models",
                str(item["modelKey"]),
            ),
            dict(item["pinnedModel"]),
        )
    tomllib.loads(candidate)
    return candidate


def _final_text(
    text: str,
    source_public: dict[str, Any],
    preview: ProviderMergePreview,
) -> str:
    candidate = _verification_text(text, preview)
    candidate = _public_reference_patches(
        candidate, source_public, preview.model_ref_map
    )
    for provider_id in preview.duplicate_provider_ids:
        candidate = remove_toml_table_tree(
            candidate, ("llm", "providers", provider_id)
        )
    tomllib.loads(candidate)
    return candidate


def _all_reference_rows(plan: ModelReferenceRewritePlan) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    live: list[dict[str, Any]] = []
    for rewrite in plan.file_rewrites:
        live.extend(dict(item) for item in rewrite.references)
    return live, [dict(item) for item in plan.historical_references]


def preview_provider_merge(
    *,
    canonical_provider_id: str,
    duplicate_provider_ids: list[str] | tuple[str, ...],
    credential_decisions: dict[str, str] | None = None,
    config_path: Path | str = CONFIG_PATH,
    project_root: Path | str = PROJECT_ROOT,
) -> ProviderMergePreview:
    canonical_id = validate_provider_id(canonical_provider_id)
    duplicate_ids = tuple(
        sorted({validate_provider_id(item) for item in duplicate_provider_ids})
    )
    if not duplicate_ids or canonical_id in duplicate_ids:
        raise ProviderMergeConflictError("duplicate Provider ids are required")
    source = load_public_config(Path(config_path).resolve())
    llm = source.get("llm") if isinstance(source.get("llm"), dict) else {}
    if int(llm.get("schema_version") or 1) != 2:
        raise ProviderMergeConflictError("Provider merge requires llm schema v2")
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    canonical = providers.get(canonical_id)
    if not isinstance(canonical, dict):
        raise ProviderMergeConflictError("canonical Provider does not exist")
    decisions = {
        str(key): str(value).strip().lower()
        for key, value in dict(credential_decisions or {}).items()
    }
    canonical_models = dict(canonical.get("models") or {})
    model_ref_map: dict[str, str] = {}
    models_to_add: list[dict[str, Any]] = []
    conflicts: list[dict[str, str]] = []
    canonical_contract = _provider_contract(canonical)
    canonical_credential = canonicalize_credential_ref(
        str(canonical.get("credential_ref") or "none")
    )
    staged_models = dict(canonical_models)
    for duplicate_id in duplicate_ids:
        duplicate = providers.get(duplicate_id)
        if not isinstance(duplicate, dict):
            conflicts.append(
                {"code": "provider_missing", "providerId": duplicate_id}
            )
            continue
        if _provider_contract(duplicate) != canonical_contract:
            conflicts.append(
                {"code": "provider_contract_mismatch", "providerId": duplicate_id}
            )
            continue
        duplicate_credential = canonicalize_credential_ref(
            str(duplicate.get("credential_ref") or "none")
        )
        if duplicate_credential != canonical_credential:
            decision = decisions.get(duplicate_id, "")
            if decision != "use_canonical":
                conflicts.append(
                    {
                        "code": "credential_decision_required",
                        "providerId": duplicate_id,
                    }
                )
                continue
        duplicate_models = (
            duplicate.get("models") if isinstance(duplicate.get("models"), dict) else {}
        )
        for duplicate_key, duplicate_model in sorted(duplicate_models.items()):
            if not isinstance(duplicate_model, dict):
                continue
            try:
                target_key, should_add = _target_model_key(
                    staged_models, str(duplicate_key), duplicate_model
                )
            except ProviderMergeConflictError as exc:
                conflicts.append(
                    {
                        "code": "model_key_collision",
                        "providerId": duplicate_id,
                        "detail": str(exc),
                    }
                )
                continue
            model_ref_map[f"{duplicate_id}/{duplicate_key}"] = (
                f"{canonical_id}/{target_key}"
            )
            if should_add:
                pinned = dict(duplicate_model)
                models_to_add.append(
                    {"modelKey": target_key, "pinnedModel": pinned, "sourceProviderId": duplicate_id}
                )
                staged_models[target_key] = pinned
    plan = build_model_reference_rewrite_plan(
        model_ref_map, public_config=source, project_root=Path(project_root)
    )
    file_live, historical = _all_reference_rows(plan)
    public_live: list[dict[str, Any]] = []
    for legacy_ref in model_ref_map:
        impact = scan_model_references(
            legacy_ref, public_config=source, project_root=Path(project_root)
        )
        public_live.extend(
            item
            for item in impact["liveReferences"]
            if item.get("source") == "public_config"
        )
    live = public_live + file_live
    luna_key = next(
        (
            key
            for key, model in staged_models.items()
            if isinstance(model, dict)
            and str(model.get("upstream_id") or "") == "gpt-5.6-luna"
        ),
        "",
    )
    if not luna_key:
        conflicts.append({"code": "required_luna_missing", "providerId": canonical_id})
    stable = json.dumps(
        {
            "baseHash": public_config_hash(source),
            "canonical": canonical_id,
            "duplicates": duplicate_ids,
            "mapping": model_ref_map,
            "models": models_to_add,
            "conflicts": conflicts,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    preview_id = "provider-merge-preview-" + hashlib.sha256(
        stable.encode("utf-8")
    ).hexdigest()[:24]
    preview = ProviderMergePreview(
        preview_id=preview_id,
        status="READY" if not conflicts else "NEEDS_REVIEW",
        base_hash=public_config_hash(source),
        canonical_provider_id=canonical_id,
        duplicate_provider_ids=duplicate_ids,
        model_ref_map=model_ref_map,
        models_to_add=tuple(models_to_add),
        live_references=tuple(live),
        historical_references=tuple(historical),
        conflicts=tuple(conflicts),
        required_probe_model_ref=f"{canonical_id}/{luna_key}" if luna_key else "",
    )
    now = time.monotonic()
    with _PREVIEW_LOCK:
        _purge_expired_previews(now)
        _PREVIEWS[preview_id] = (now + _PREVIEW_TTL_SECONDS, preview)
    return preview


def _stored_preview(preview_id: str) -> ProviderMergePreview:
    now = time.monotonic()
    with _PREVIEW_LOCK:
        _purge_expired_previews(now)
        stored = _PREVIEWS.get(str(preview_id or "").strip())
    if stored is None:
        raise ProviderMergeConflictError("unknown or expired Provider merge preview")
    return stored[1]


def _reference_participant(plan: ModelReferenceRewritePlan) -> TransactionParticipant:
    written: list[Any] = []

    def apply() -> None:
        for rewrite in plan.file_rewrites:
            if not rewrite.path.exists() or rewrite.path.read_bytes() != rewrite.before_bytes:
                raise ProviderMergeConflictError("model reference hash drift")
        for rewrite in plan.file_rewrites:
            _strict_atomic_write(rewrite.path, rewrite.after_bytes)
            written.append(rewrite)

    def verify() -> None:
        for rewrite in plan.file_rewrites:
            if rewrite.path.read_bytes() != rewrite.after_bytes:
                raise ProviderMergeVerificationError("model reference rewrite verification failed")

    def rollback() -> None:
        for rewrite in reversed(written):
            _strict_atomic_write(rewrite.path, rewrite.before_bytes)

    return TransactionParticipant(
        name="provider_merge_model_references",
        apply=apply,
        verify=verify,
        rollback=rollback,
    )


def _write_merge_manifest(
    *,
    migration_id: str,
    preview: ProviderMergePreview,
    config_path: Path,
    config_before: bytes,
    config_after: bytes,
    plan: ModelReferenceRewritePlan,
    status: str,
) -> Path:
    backup_dir = resolve_config_backup_dir(config_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    payloads = [(config_path, config_before, config_after)] + [
        (item.path, item.before_bytes, item.after_bytes) for item in plan.file_rewrites
    ]
    for index, (target, before, after) in enumerate(payloads):
        before_name = f"provider-merge-{migration_id}-{index:03d}.before.bin"
        after_name = f"provider-merge-{migration_id}-{index:03d}.after.bin"
        _strict_atomic_write(backup_dir / before_name, before)
        _strict_atomic_write(backup_dir / after_name, after)
        records.append(
            {
                "target": str(target.resolve()),
                "beforeBackup": before_name,
                "afterBackup": after_name,
                "beforeSha256": _sha256(before),
                "afterSha256": _sha256(after),
            }
        )
    manifest_path = backup_dir / f"provider-merge-{migration_id}.json"
    _strict_atomic_write(
        manifest_path,
        (
            json.dumps(
                {
                    "schemaVersion": 1,
                    "migrationId": migration_id,
                    "previewId": preview.preview_id,
                    "status": status,
                    "baseHash": preview.base_hash,
                    "appliedHash": public_config_hash(tomllib.loads(config_after.decode("utf-8"))),
                    "files": records,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    return manifest_path


def apply_provider_merge(
    preview_id: str,
    *,
    expected_base_hash: str,
    confirmed: bool,
    config_path: Path | str = CONFIG_PATH,
    project_root: Path | str = PROJECT_ROOT,
) -> dict[str, Any]:
    if not confirmed:
        raise ProviderMergeConflictError("Provider merge confirmation is required")
    preview = _stored_preview(preview_id)
    if preview.status != "READY":
        raise ProviderMergeConflictError("Provider merge preview has unresolved conflicts")
    path = Path(config_path).resolve()
    source_bytes = path.read_bytes()
    source_public = tomllib.loads(source_bytes.decode("utf-8"))
    current_hash = public_config_hash(source_public)
    if current_hash != preview.base_hash or current_hash != str(expected_base_hash or ""):
        raise ProviderMergeConflictError("operator config changed after Provider merge preview")
    verification_text = _verification_text(source_bytes.decode("utf-8"), preview)
    verification_public = tomllib.loads(verification_text)
    scratch_catalog = resolve_config_backup_dir(path) / f"{preview.preview_id}-catalog.json"
    try:
        discovered = discover_provider_models(
            verification_public,
            preview.canonical_provider_id,
            catalog_path=scratch_catalog,
        )
    finally:
        scratch_catalog.unlink(missing_ok=True)
    observed = {item.upstream_id for item in discovered.models}
    if not _REQUIRED_UPSTREAM_IDS.issubset(observed):
        raise ProviderMergeVerificationError(
            "canonical Provider discovery is incomplete"
        )
    probe = run_draft_llm_test(
        verification_public, model_id=preview.required_probe_model_ref
    )
    if not bool(probe.get("ok")):
        status = str(probe.get("status") or probe.get("statusCode") or "unknown")
        raise ProviderMergeVerificationError(
            f"canonical Provider callability probe failed: status={status}"
        )
    plan = build_model_reference_rewrite_plan(
        preview.model_ref_map,
        public_config=verification_public,
        project_root=Path(project_root),
    )
    final_text = _final_text(source_bytes.decode("utf-8"), source_public, preview)
    final_bytes = final_text.encode("utf-8")
    prepared = prepare_operator_config_transaction(
        operation_kind="provider_merge",
        expected_base_hash=preview.base_hash,
        config_path=path,
        mutate_text=lambda _text: final_text,
    )
    migration_id = "provider-merge-" + uuid.uuid4().hex
    manifest_path = _write_merge_manifest(
        migration_id=migration_id,
        preview=preview,
        config_path=path,
        config_before=source_bytes,
        config_after=final_bytes,
        plan=plan,
        status="applied",
    )
    try:
        result = apply_operator_config_transaction(
            prepared, participants=[_reference_participant(plan)]
        )
    except Exception:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "rolled_back"
        _strict_atomic_write(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        raise
    with _PREVIEW_LOCK:
        _PREVIEWS.pop(preview.preview_id, None)
    return {
        "migrationId": migration_id,
        "status": "applied",
        "hash": result["hash"],
        "updatedReferenceCount": sum(len(item.references) for item in plan.file_rewrites),
    }


def rollback_provider_merge(
    migration_id: str,
    *,
    expected_current_hash: str,
    config_path: Path | str = CONFIG_PATH,
    project_root: Path | str = PROJECT_ROOT,
) -> dict[str, Any]:
    del project_root
    path = Path(config_path).resolve()
    backup_dir = resolve_config_backup_dir(path)
    manifest_path = backup_dir / f"provider-merge-{migration_id}.json"
    if not manifest_path.exists():
        raise ProviderMergeConflictError("unknown Provider merge migration")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("migrationId") != migration_id or manifest.get("status") != "applied":
        raise ProviderMergeConflictError("Provider merge is not rollback eligible")
    current = load_public_config(path)
    current_hash = public_config_hash(current)
    if current_hash != str(expected_current_hash or "") or current_hash != manifest.get("appliedHash"):
        raise ProviderMergeConflictError("operator config changed after Provider merge")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ProviderMergeConflictError("invalid Provider merge manifest")
    payloads: list[tuple[Path, bytes, bytes]] = []
    for record in records:
        target = Path(str(record.get("target") or ""))
        before = (backup_dir / str(record.get("beforeBackup") or "")).read_bytes()
        after = (backup_dir / str(record.get("afterBackup") or "")).read_bytes()
        if _sha256(before) != record.get("beforeSha256") or _sha256(after) != record.get("afterSha256"):
            raise ProviderMergeConflictError("Provider merge backup hash mismatch")
        if not target.exists() or _sha256(target.read_bytes()) != record.get("afterSha256"):
            raise ProviderMergeConflictError("Provider merge target hash drift")
        payloads.append((target, before, after))
    config_before = payloads[0][1]
    reference_payloads = payloads[1:]
    restored: list[tuple[Path, bytes]] = []

    def apply_references() -> None:
        for target, before, after in reference_payloads:
            if target.read_bytes() != after:
                raise ProviderMergeConflictError("Provider merge target hash drift")
            _strict_atomic_write(target, before)
            restored.append((target, after))

    def verify_references() -> None:
        for target, before, _ in reference_payloads:
            if target.read_bytes() != before:
                raise ProviderMergeVerificationError("Provider merge rollback verification failed")

    def rollback_references() -> None:
        for target, after in reversed(restored):
            _strict_atomic_write(target, after)

    participant = TransactionParticipant(
        name="provider_merge_reference_rollback",
        apply=apply_references,
        verify=verify_references,
        rollback=rollback_references,
    )
    prepared = prepare_operator_config_transaction(
        operation_kind="provider_merge_rollback",
        expected_base_hash=current_hash,
        config_path=path,
        mutate_text=lambda _text: config_before.decode("utf-8"),
    )
    result = apply_operator_config_transaction(prepared, participants=[participant])
    manifest["status"] = "rolled_back"
    _strict_atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {"migrationId": migration_id, "status": "rolled_back", "hash": result["hash"]}


__all__ = [
    "ProviderMergeConflictError",
    "ProviderMergeError",
    "ProviderMergePreview",
    "ProviderMergeVerificationError",
    "apply_provider_merge",
    "preview_provider_merge",
    "rollback_provider_merge",
]
