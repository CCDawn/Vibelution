"""Internal subprocess boundary for explicit offline personal snapshot activation.

The source-role parent resolves routing. The native-role child consumes only
that frozen authority and rechecks every proof; it must never resolve source
routing through native storage facades. No credentials or source bytes go into
the child environment or the public diagnostic report.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def _initial_channel(port, token):
    """Connect only to the main-owned, per-child loopback capability."""
    import http.client
    import re
    from core.assistant_runtime.migration_io import MigrationIOError
    if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
        raise MigrationIOError("initial_channel_invalid")
    channel = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    channel.connect()
    return channel


def _initial_call(channel, token, method, path):
    from core.assistant_runtime.migration_io import MigrationIOError, strict_json
    try:
        channel.request(method, path, body=b"{}" if method == "POST" else None,
                        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = channel.getresponse()
        raw = response.read(16385)
        if response.status != 200 or len(raw) > 16384:
            raise ValueError("invalid response")
        return strict_json(raw)
    except Exception:
        raise MigrationIOError("initial_channel_unavailable") from None


def initial_binding(port, token):
    from core.assistant_runtime.migration_io import MigrationIOError
    channel = _initial_channel(port, token)
    try:
        value = _initial_call(channel, token, "GET", "/binding")
    finally:
        channel.close()
    keys = {"schemaVersion", "registeredProjectId", "revision", "projectRoot", "sourceConfig",
            "targetProfile", "targetConfig", "operationId"}
    if (type(value) is not dict or set(value) != keys or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or type(value["revision"]) is not int or value["revision"] < 0
            or any(not isinstance(value[k], str) or not value[k] for k in keys - {"schemaVersion", "revision"})):
        raise MigrationIOError("initial_channel_binding_invalid")
    return value


def _initial_receipts_or_claim(target, operation_id, category):
    """Conservative read-only detection: any previous artifact forbids dispatch."""
    import hashlib
    from core.assistant_runtime.migration_io import check_path, read_stable_file, strict_json
    digest = hashlib.sha256(operation_id.encode("ascii")).hexdigest()
    candidates = [target / "initial_migration_claims" / operation_id,
                  target / "history_sources/migrations" / operation_id,
                  target / "history_sources/migrations" / (".pending-" + operation_id),
                  target / "episodic_migrations" / (digest + ".json"),
                  target / "affairs_migrations" / (digest + ".json")]
    if category == "knowledge":
        # Archives can be shared by unrelated completed imports. Only this
        # operation's immutable plan/receipt proves that this operation ran.
        from core.assistant_runtime.migration_knowledge import _operation_paths, _validate_state
        folder = target / "knowledge_migrations"
        candidates.extend(_operation_paths(folder, operation_id))
        if folder.exists() or folder.is_symlink():
            check_path(folder)
            # Older imports may have written origin state without a plan. Do
            # not infer absence from a damaged or unfinished origin record.
            states = list(folder.glob("*.json"))
            if len(states) > 4096:
                return True
            for state_path in states:
                check_path(state_path)
                state = strict_json(read_stable_file(state_path, 4 * 1024 * 1024).raw)
                if not isinstance(state, dict) or not isinstance(state.get("binding"), dict):
                    return True
                _validate_state(state, state["binding"])
                if state["migrationId"] == operation_id or state["phase"] != "published":
                    return True
    found = False
    for path in candidates:
        ancestor = path.parent
        while not ancestor.exists() and not ancestor.is_symlink():
            ancestor = ancestor.parent
        check_path(ancestor)
        if path.exists() or path.is_symlink():
            check_path(path)
            found = True
            # Read exact-ID receipts for reconciliation evidence only. Both a
            # mismatched receipt and a matching one forbid another dispatch.
            if path in (candidates[3], candidates[4]):
                receipt = strict_json(read_stable_file(path, 16384).raw)
                if type(receipt) is not dict or receipt.get("migrationId") != operation_id:
                    return True
            if path == candidates[1] and path.is_dir():
                manifest = path / "manifest.json"
                if manifest.exists() or manifest.is_symlink():
                    receipt = strict_json(read_stable_file(manifest, 16 * 1024 * 1024).raw)
                    if type(receipt) is not dict or receipt.get("migrationId") != operation_id:
                        return True
    return found


def prepare_initial_model_config(source_config, target, destination, operation_id, registry_digest):
    """Create a credential-free v2 model identity snapshot, or fail closed."""
    import re
    import tomllib
    from config.llm_projection import project_v2_llm_for_runtime
    from config.models import LLMConfig
    from config.toml_writer import dumps_public_config
    from core.assistant_runtime.migration_history import _write_new
    from core.assistant_runtime.migration_io import (MigrationIOError, check_path, migration_target_lock,
        pinned_source_files, pinned_target_directory, read_stable_file, validate_path, verify_snapshot)
    target = check_path(target)
    destination = validate_path(destination)
    if (not isinstance(operation_id, str) or re.fullmatch(r"initial-[a-f0-9]{40}", operation_id) is None
            or not isinstance(registry_digest, str) or re.fullmatch(r"[a-f0-9]{64}", registry_digest) is None
            or destination != target / (".initial-migration-models-v1-" + operation_id + "-" + registry_digest + ".toml")):
        raise MigrationIOError("initial_model_config_invalid")
    source = read_stable_file(source_config, 16 * 1024 * 1024)
    try:
        raw = tomllib.loads(source.raw.decode("utf-8"))
        llm = raw["llm"]
        if type(llm) is not dict or type(llm.get("schema_version")) is not int or llm["schema_version"] != 2:
            raise ValueError("unsupported schema")
        old_providers, old_profiles = llm["providers"], llm["profiles"]
        aliases = llm.get("model_aliases", {})
        if (type(old_providers) is not dict or not old_providers or type(old_profiles) is not dict
                or not old_profiles or type(aliases) is not dict):
            raise ValueError("invalid models")
        identifier = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
        reference = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,255}\Z")
        if (any(not isinstance(k, str) or not identifier.fullmatch(k) for k in (*old_providers, *old_profiles))
                or any(not isinstance(k, str) or not reference.fullmatch(k) or not isinstance(v, str)
                       or not reference.fullmatch(v) for k, v in aliases.items())):
            raise ValueError("invalid model identity")
        providers = {}
        for name, provider in old_providers.items():
            if type(provider) is not dict or type(provider.get("models")) is not dict:
                raise ValueError("invalid provider")
            models = {}
            for key, model in provider["models"].items():
                if (not isinstance(key, str) or not identifier.fullmatch(key) or type(model) is not dict
                        or type(model.get("enabled", True)) is not bool):
                    raise ValueError("invalid model")
                # A fixed local upstream is enough for reference resolution;
                # original URLs, credentials and arbitrary metadata stay out.
                models[key] = {"upstream_id": "offline", "enabled": model.get("enabled", True)}
            providers[name] = {"service_class": "local_runtime", "vendor": "custom", "driver": "openai",
                "base_url": "http://127.0.0.1:9/v1", "auth_kind": "none", "credential_ref": "none",
                "requires_credential": False, "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
                "models": models}
        profiles = {}
        for name, profile in old_profiles.items():
            if type(profile) is not dict:
                raise ValueError("invalid profile")
            model_ref, fallback = profile.get("model_ref", ""), profile.get("fallback", "")
            if (not isinstance(model_ref, str) or not isinstance(fallback, str)
                    or model_ref and not reference.fullmatch(model_ref)
                    or fallback and not identifier.fullmatch(fallback)):
                raise ValueError("invalid profile identity")
            profiles[name] = {"model_ref": model_ref, "fallback": fallback}
        snapshot = {"llm": {"schema_version": 2, "providers": providers,
                            "profiles": profiles, "model_aliases": dict(aliases)}}
        encoded = dumps_public_config(snapshot).encode("utf-8")
        if len(encoded) > 16 * 1024 * 1024:
            raise ValueError("snapshot too large")
        def effective(value):
            return LLMConfig.model_validate(project_v2_llm_for_runtime({"llm": value})["llm"])
        original = effective(llm)
        sanitized = effective(tomllib.loads(encoded.decode("utf-8"))["llm"])
        if (list(original.model_library) != list(sanitized.model_library)
                or list(original.profiles) != list(sanitized.profiles)
                or original.declared_fallback_profile_ids() != sanitized.declared_fallback_profile_ids()
                or original.model_aliases != sanitized.model_aliases
                or any(original.model_library[key].get("enabled", True) != sanitized.model_library[key].get("enabled", True)
                       for key in original.model_library)):
            raise ValueError("model library mismatch")
        if any(original.resolve_model_ref(alias) != sanitized.resolve_model_ref(alias) for alias in original.model_aliases):
            raise ValueError("model alias mismatch")
        def resolve(config, name):
            candidates = [name] if name else []
            if "primary" not in candidates:
                candidates.append("primary")
            for candidate in candidates:
                try:
                    value, _ = config.get_model_library_entry_for_profile(config.get_profile(profile_id=candidate))
                    if value:
                        return str(value).strip()
                except Exception:
                    continue
            return next((str(key).strip() for key, value in config.model_library.items()
                         if isinstance(value, dict) and str(key).strip()), "")
        names = [*original.profiles, "", "__initial_missing_profile__"]
        if any(resolve(original, name) != resolve(sanitized, name) for name in names):
            raise ValueError("profile mapping mismatch")
    except Exception:
        raise MigrationIOError("initial_model_config_invalid") from None
    # Auxiliary config only. It grants no migration authority and is never
    # overwritten; incomplete or conflicting existing files fail closed.
    with pinned_source_files((source,)), pinned_target_directory(target), migration_target_lock(target):
        verify_snapshot(source)
        _write_new(destination, encoded)
        verify_snapshot(source)
    return destination


def verify_initial_personal_receipts(target, operation_id, *, allow_partial=False):
    """Read-only original-ID receipt check. Caller must hold host-owner lock."""
    import hashlib
    from pathlib import PurePosixPath
    from core.assistant_runtime.initial_migration_binding import read_initial_intent, target_identity
    from core.assistant_runtime.migration_io import MigrationIOError, check_path, fingerprint_tree, read_stable_file, strict_json
    from core.assistant_runtime.migration_history import _confirmation_exists
    from core.assistant_runtime import migration_affairs, migration_episodic
    intent = read_initial_intent(target, operation_id)
    if intent is None or intent["category"] != "personal":
        raise MigrationIOError("initial_receipts_unknown")
    td, directory = target_identity(target, intent["targetAgentId"], intent["targetSessionId"])
    if td != intent["targetIdentityDigest"] or directory != intent["targetDirectory"]:
        raise MigrationIOError("initial_receipts_unknown")
    claim = strict_json(read_stable_file(target / "initial_migration_claims" / operation_id / "claim.json", 16384).raw)
    if (type(claim) is not dict or type(claim.get("schemaVersion")) is not int
            or claim != {"schemaVersion": 1, "operationId": operation_id, "category": "personal"}):
        raise MigrationIOError("initial_receipts_unknown")
    archive = check_path(target / "history_sources/migrations" / operation_id)
    if not _confirmation_exists(archive):
        raise MigrationIOError("initial_receipts_unknown")
    tree = fingerprint_tree(archive)
    files = {item.path.relative_to(archive).as_posix(): item for item in tree}
    manifest = strict_json(files["manifest.json"].raw)
    keys = {"schemaVersion", "migrationId", "sourceScope", "readOnly", "untrustedContent",
            "activePluginStateImported", "sourceComplete", "snapshotCompleteAtScan", "entries", "readyForCutover"}
    if (type(manifest) is not dict or set(manifest) != keys or type(manifest["schemaVersion"]) is not int
            or manifest["schemaVersion"] != 2 or manifest["migrationId"] != operation_id
            or manifest["sourceScope"] != intent["sourceScope"] or manifest["readOnly"] is not True
            or manifest["untrustedContent"] is not True or manifest["activePluginStateImported"] is not False
            or manifest["sourceComplete"] is not False or type(manifest["snapshotCompleteAtScan"]) is not bool
            or manifest["readyForCutover"] is not False or type(manifest["entries"]) is not list):
        raise MigrationIOError("initial_receipts_unknown")
    entries = {}
    for row in manifest["entries"]:
        if (type(row) is not dict or set(row) != {"sourceRef", "category", "path", "sha256", "size"}
                or not isinstance(row["path"], str) or not isinstance(row["category"], str)
                or not isinstance(row["sourceRef"], str) or not isinstance(row["sha256"], str)
                or type(row["size"]) is not int or row["size"] < 0):
            raise MigrationIOError("initial_receipts_unknown")
        relative = PurePosixPath(row["path"])
        if (relative.is_absolute() or not relative.parts or any(part in (".", "..") for part in relative.parts)
                or relative.as_posix() != row["path"] or row["path"] in entries):
            raise MigrationIOError("initial_receipts_unknown")
        item = files.get(row["path"])
        if item is None or item.sha256 != row["sha256"] or len(item.raw) != row["size"]:
            raise MigrationIOError("initial_receipts_unknown")
        entries[row["path"]] = (row, item)
    if set(files) != {"manifest.json", *entries}:
        raise MigrationIOError("initial_receipts_unknown")
    expected_directories = {Path('.'), Path('.confirmed')}
    for name in files:
        expected_directories.update(Path(name).parents)
    pending = archive / '.confirmation.pending'
    if pending.exists() or pending.is_symlink():
        check_path(pending)
        if not pending.is_dir() or any(pending.iterdir()):
            raise MigrationIOError("initial_receipts_unknown")
        expected_directories.add(Path('.confirmation.pending'))
    if {path.relative_to(archive) for path, _ in tree.directories} != expected_directories:
        raise MigrationIOError("initial_receipts_unknown")
    episodes = [(row, item) for row, item in entries.values() if row["category"] == "episodic_memory"]
    affairs = [(row, item) for path, (row, item) in entries.items()
               if row["category"] == "personal_affairs" and path.endswith("/affairs/items.jsonl")]
    if len(episodes) != 1 or len(affairs) != 1:
        raise MigrationIOError("initial_receipts_unknown")
    digest = hashlib.sha256(operation_id.encode("ascii")).hexdigest()
    confirmed = 0
    for name, count_name, item, count in (
            ("episodic_migrations", "episodeCount", episodes[0][1],
             len(migration_episodic._parse_rows(episodes[0][1].raw, intent["sourceScope"]["agentId"]))),
            ("affairs_migrations", "itemCount", affairs[0][1], len(migration_affairs._parse_rows(affairs[0][1].raw)))):
        receipt_path = target / name / (digest + ".json")
        if allow_partial and not receipt_path.exists() and not receipt_path.is_symlink():
            continue
        receipt = strict_json(read_stable_file(receipt_path, 16384).raw)
        expected = {"schemaVersion": 1, "migrationId": operation_id, "sourceScope": intent["sourceScope"],
                    "sourceSha256": item.sha256, "targetAgentId": intent["targetAgentId"],
                    count_name: count, "published": True}
        if (type(receipt) is not dict or type(receipt.get("schemaVersion")) is not int
                or receipt != expected or type(receipt.get(count_name)) is not int):
            raise MigrationIOError("initial_receipts_unknown")
        confirmed += 1
    if confirmed == 0:
        raise MigrationIOError("initial_receipts_unknown")
    return True


def verify_initial_knowledge_receipts(target, operation_id):
    """Bind the knowledge operation proof to the approved native intent and claim.

    Caller holds the target host-owner lock. This proves historical knowledge
    completion only; main must separately confirm outer success and Job drain.
    """
    from core.assistant_runtime.initial_migration_binding import read_initial_intent, target_identity
    from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file, strict_json
    from core.assistant_runtime.migration_knowledge import verify_knowledge_completion
    intent = read_initial_intent(target, operation_id)
    if intent is None or intent["category"] != "knowledge":
        raise MigrationIOError("initial_receipts_unknown")
    td, directory = target_identity(target, intent["targetAgentId"], intent["targetSessionId"])
    if td != intent["targetIdentityDigest"] or directory != intent["targetDirectory"]:
        raise MigrationIOError("initial_receipts_unknown")
    claim = strict_json(read_stable_file(target / "initial_migration_claims" / operation_id / "claim.json", 16384).raw)
    if (type(claim) is not dict or type(claim.get("schemaVersion")) is not int
            or claim != {"schemaVersion": 1, "operationId": operation_id, "category": "knowledge"}):
        raise MigrationIOError("initial_receipts_unknown")
    proof = verify_knowledge_completion(target, operation_id)
    if (type(proof) is not dict or type(proof.get("schemaVersion")) is not int or proof["schemaVersion"] != 1
            or proof.get("operationId") != operation_id or proof.get("sourceScope") != intent["sourceScope"]
            or proof.get("targetAgentId") != intent["targetAgentId"] or proof.get("sourceQuiesced") is not False
            or proof.get("readyForCutover") is not False):
        raise MigrationIOError("initial_receipts_unknown")
    return True


def storage_authority(project, source_config, projects_home=None, *, legacy_home=None):
    """Snapshot identity and the selected route, including an absent marker."""
    from vibelution_storage import (PROJECT_IDENTITY_RELATIVE_PATH, instance_id_for_project,
        resolve_project_storage_paths, storage_migration_state_path)
    from core.assistant_runtime.migration_io import MigrationIOError, check_path, read_stable_file, strict_json, verify_snapshot
    from dataclasses import replace
    from core.assistant_runtime.history_preview import _project_source_paths
    project = check_path(Path(project))
    if project.resolve(strict=True) != project:
        raise MigrationIOError("source_project_identity_invalid")
    if source_config is None:
        raise MigrationIOError("source_config_required")
    identity = read_stable_file(project / PROJECT_IDENTITY_RELATIVE_PATH, 64 * 1024)
    payload = strict_json(identity.raw)
    if (not isinstance(payload, dict) or type(payload.get("schemaVersion")) is not int
            or payload["schemaVersion"] != 1 or not isinstance(payload.get("projectId"), str)):
        raise MigrationIOError("source_project_identity_invalid")
    canonical = resolve_project_storage_paths(project, projects_home=projects_home)
    if (payload["projectId"].strip().lower() != canonical.project_id
            or canonical.instance_id != instance_id_for_project(project)):
        raise MigrationIOError("source_project_identity_changed")
    marker_path = storage_migration_state_path(canonical)
    marker_present = marker_path.exists() or marker_path.is_symlink()
    marker = read_stable_file(marker_path, 64 * 1024) if marker_present else None
    active = _project_source_paths(project, source_config, projects_home=canonical.projects_home, legacy_home=legacy_home)
    if not marker_present and active.migrated:
        raise MigrationIOError("source_storage_route_invalid")
    # Preview already checks its process-wide resolver. The offline processes
    # have different DATA_HOME values, so re-evaluate the same explicit route.
    if active.project_id != canonical.project_id or active.instance_id != canonical.instance_id:
        raise MigrationIOError("source_storage_route_invalid")
    def verify():
        verify_snapshot(identity)
        if marker is not None:
            verify_snapshot(marker)
        elif marker_path.exists() or marker_path.is_symlink():
            raise MigrationIOError("source_storage_route_changed")
        current = _project_source_paths(project, source_config, projects_home=canonical.projects_home, legacy_home=legacy_home)
        if current != active:
            raise MigrationIOError("source_storage_route_changed")
        verify_snapshot(identity)
        if marker is not None:
            verify_snapshot(marker)
        elif marker_path.exists() or marker_path.is_symlink():
            raise MigrationIOError("source_storage_route_changed")
    verify()
    # Preserve the registered spelling used in the preview's existing digest.
    return replace(active, project_root=project), (identity, *((marker,) if marker is not None else ())), verify


def _capture(project, workspace, scope, grant_path, *, categories=None):
    from core.assistant_runtime.migration_inventory import declared_assistant_identities
    from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file, strict_json
    from core.assistant_runtime.migration_paths import resolve_source_paths, source_snapshot
    registry = read_stable_file(workspace / "agents/agents.json", 16 * 1024 * 1024)
    raw = strict_json(registry.raw)
    if not isinstance(raw, dict):
        raise MigrationIOError("invalid_source_registry")
    if not any(row["agentId"] == scope["agentId"] for row in declared_assistant_identities(raw.get("agents"))):
        raise MigrationIOError("assistant_identity_unavailable")
    row = next(row for row in raw["agents"] if row.get("agentId") == scope["agentId"])
    policies = raw.get("memoryPolicies", {})
    if not isinstance(policies, dict):
        raise MigrationIOError("invalid_memory_policy_snapshot")
    grant = read_stable_file(grant_path, 64 * 1024) if grant_path is not None else None
    captured = source_snapshot(resolve_source_paths(project_root=project, workspace=workspace,
        project_id=scope["projectId"], instance_id=scope["instanceId"], agent_row=row,
        memory_policy=policies.get(row.get("memoryPolicyId")),
        grants=strict_json(grant.raw) if grant is not None else None, categories=categories),
        categories=categories)
    return captured, (registry, grant) if grant is not None else (registry,)


def _snapshot_proof(snapshot):
    return {"path": str(snapshot.path), "sha256": snapshot.sha256, "identity": list(snapshot.identity)}


def _source_proof(captured, authorities):
    def chains(values):
        return {ref: [[str(path), list(identity)] for path, identity in chain] for ref, chain in values.items()}
    return {"report": captured.report, "identities": chains(captured._identities),
        "directories": chains(captured.directoryproofs),
        "files": {ref: [_snapshot_proof(item) for item in snapshots]
                  for ref, snapshots in captured.snapshots.items()},
        "authorities": [_snapshot_proof(item) for item in authorities]}


def _verify_file_proofs(proofs):
    from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file
    for proof in proofs:
        current = read_stable_file(Path(proof["path"]), 16 * 1024 * 1024)
        if _snapshot_proof(current) != proof:
            raise MigrationIOError("source_authority_changed")


def _target(target_profile, target_config):
    from core.assistant_runtime.migration_io import MigrationIOError, check_path, read_stable_file
    target = check_path(target_profile).resolve()
    config = read_stable_file(target_config, 16 * 1024 * 1024)
    if not target.is_dir() or not config.path.resolve().is_relative_to(target):
        raise MigrationIOError("activation_target_config_outside_profile")
    return target, config


def _isolated_environment(target, config):
    # Use a small OS-only allowlist instead of attempting to enumerate every
    # provider credential or inherited Python/runtime override.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "SYSTEMDRIVE",
               "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    private = target / ".offline-activation"
    env.update({"VIBELUTION_PROCESS_ROLE": "launcher_assistant",
        "VIBELUTION_ASSISTANT_NATIVE_ROOT": str(target), "VIBELUTION_DATA_HOME": str(target / "data"),
        "VIBELUTION_CONFIG_PATH": str(config), "VIBELUTION_CONFIG_HOME": str(config.parent),
        "VIBELUTION_PROJECTS_HOME": str(target / "projects"),
        "HOME": str(private / "user"), "USERPROFILE": str(private / "user"),
        "APPDATA": str(private / "user/AppData/Roaming"),
        "LOCALAPPDATA": str(private / "user/AppData/Local"),
        "TEMP": str(private / "tmp"), "TMP": str(private / "tmp"), "TMPDIR": str(private / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    return env


def _assert_source_target_disjoint(target, roots):
    from core.assistant_runtime.migration_io import MigrationIOError
    target = Path(target).resolve()
    for root in roots:
        resolved = Path(root).resolve()
        if target.is_relative_to(resolved) or resolved.is_relative_to(target):
            raise MigrationIOError('history_source_target_overlap')


def activate_in_subprocess(*, paths, workspace, agent_id, source_config, target_profile,
        target_config, migration_id, path_grants, authority_snapshots, authority_verify, category="personal",
        baseline_migration_id=None, initial_control=None):
    import re
    import subprocess
    from core.assistant_runtime.migration_active import _selected, _verify_captured
    from core.assistant_runtime import migration_affairs, migration_episodic
    from core.assistant_runtime.migration_io import MigrationIOError, verify_snapshot
    from core.assistant_runtime.migration_paths import _identity_chain
    from config.paths import default_data_home, resolve_configured_data_home
    from vibelution_storage import storage_migration_state_path
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", migration_id):
        raise MigrationIOError("migration_id_invalid")
    if category not in {"personal", "knowledge", "affairs_conflicts", "affairs_sync"}:
        raise MigrationIOError("activation_category_invalid")
    if category in {"affairs_conflicts", "affairs_sync"}:
        if (not isinstance(baseline_migration_id, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", baseline_migration_id)
                or baseline_migration_id == migration_id):
            raise MigrationIOError("affairs_conflict_baseline_invalid")
    elif baseline_migration_id is not None:
        raise MigrationIOError("affairs_conflict_baseline_invalid")
    target, config = _target(target_profile, target_config)
    scope = {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": agent_id}
    grant_path = path_grants.absolute() if path_grants is not None else None
    captured, selected_authorities = _capture(paths.project_root, workspace, scope, grant_path)
    if category == "personal":
        migration_episodic._parse_rows(_selected(captured, "episodic_memory").raw, agent_id)
        migration_affairs._parse_rows(_selected(captured, "personal_affairs").raw)
        knowledge_authorities = ()
    elif category in {"affairs_conflicts", "affairs_sync"}:
        migration_affairs._parse_rows(_selected(captured, "personal_affairs").raw)
        knowledge_authorities = ()
    else:
        from core.assistant_runtime.migration_io import read_stable_file
        if captured.report.get("categoryStatus", {}).get("private_knowledge") != "available":
            raise MigrationIOError("active_source_unavailable")
        registry_root = workspace / "knowledge/sources/registry"
        knowledge_authorities = tuple(read_stable_file(registry_root / name, 4 * 1024 * 1024)
            for name in ("source_registry.jsonl", "owner_refs.jsonl"))
    authorities = (*authority_snapshots, *selected_authorities, *knowledge_authorities)
    # Refuse overlap before native bootstrap, including external grants and
    # authority files that might otherwise be placed inside the target.
    _assert_source_target_disjoint(target, (paths.project_root, paths.data, workspace.parent, workspace,
        *captured.paths.values(), *(item.path for item in authorities)))
    _verify_captured(captured, authorities, authority_verify)
    # Include absence and ancestor identity, so creating/replacing a routing
    # authority cannot hide behind an unchanged selected source directory.
    route_paths = (paths.project_root, workspace, paths.runtime / 'developer-mode/active.json',
                   storage_migration_state_path(paths))
    route_proof = [[str(path), [[str(node), list(identity)] for node, identity in _identity_chain(path)]]
                   for path in route_paths]
    legacy_home = resolve_configured_data_home(config_path=source_config) or default_data_home().resolve()
    marker_path = storage_migration_state_path(paths)
    marker_present = marker_path.exists() or marker_path.is_symlink()
    authority_verify()
    request = {"schemaVersion": 1, "project": str(paths.project_root), "workspace": str(workspace),
        "scope": scope, "grant": str(grant_path) if grant_path is not None else None,
        "target": str(target), "config": _snapshot_proof(config), "migrationId": migration_id, "category": category,
        "baselineMigrationId": baseline_migration_id, "projectsHome": str(paths.projects_home),
        "sourceConfig": str(source_config), "legacyHome": str(legacy_home),
        "storageMarkerPresent": marker_present, "storageData": str(paths.data), "storageRuntime": str(paths.runtime),
        "route": route_proof, "source": _source_proof(captured, authorities)}
    if initial_control is not None:
        request["initialControl"] = initial_control
    encoded = json.dumps(request, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 8 * 1024 * 1024:
        raise MigrationIOError("activation_proof_too_large")
    verify_snapshot(config)
    environment = _isolated_environment(target, config.path)
    if initial_control is not None:
        environment["VIBELUTION_INITIAL_MIGRATION_CHILD"] = "1"
    try:
        process = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--offline-child"],
            input=encoded, cwd=ROOT,
            env=environment, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    except (subprocess.TimeoutExpired, OSError):
        # The native import may have committed. Never replay an uncertain
        # outcome; an operator can explicitly reconcile using this migration ID.
        raise MigrationIOError("activation_outcome_unknown") from None
    try:
        from core.assistant_runtime.migration_io import strict_json
        if len(process.stdout) > 64 * 1024:
            raise ValueError("oversized child report")
        result = strict_json(process.stdout)
        if not isinstance(result, dict):
            raise ValueError("invalid child report")
    except ValueError:
        raise MigrationIOError("activation_outcome_unknown") from None
    if process.returncode != 0:
        if result == {"ok": False, "code": "TARGET_PROFILE_BUSY"}:
            raise TimeoutError("profile busy")
        reason = result.get("reason")
        if result.get("code") == "SOURCE_MIGRATION_UNAVAILABLE" and isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,96}", reason):
            raise MigrationIOError(reason)
        raise MigrationIOError("activation_outcome_unknown")
    if (result.get("status") not in {"complete", "partial"} or result.get("readyForCutover") is not False
            or result.get("migrationId") != migration_id or result.get("sourceScope") != scope):
        raise MigrationIOError("activation_outcome_unknown")
    try:
        _verify_captured(captured, authorities, authority_verify)
        verify_snapshot(config)
    except (MigrationIOError, OSError, ValueError):
        # A confirmed child receipt remains useful even when the source moves
        # immediately after a native commit. Keep the per-category evidence.
        mark_reconciliation(result, migration_id, "source_authority_changed")
    return result


def mark_reconciliation(result, migration_id, reason):
    """Preserve committed categories while refusing a complete activation claim."""
    result.update(status="partial", migrationId=migration_id, requiresReconciliation=True,
                  sourceQuiesced=False, readyForCutover=False)
    result.setdefault("reason", reason)
    if reason in {"source_changed", "source_authority_changed", "source_routing_changed",
                  "source_storage_route_changed", "source_project_identity_changed", "source_snapshot_changed"}:
        result["sourceValidation"] = "changed"
    elif reason in {"activation_outcome_unknown", "affairs_sync_outcome_unknown"}:
        result["outcomeUnknown"] = True
    return result


def _install_audit(target):
    """Deny network, process escapes and Python writes beyond the target."""
    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen", "os.system",
                     "os.exec", "os.posix_spawn", "os.spawn", "os.startfile"}:
            raise PermissionError("offline_activation_operation_denied")
        if event == "open":
            path, _mode, flags = args
            if isinstance(path, int) or not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return
            paths = (path,)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.chown", "os.utime", "os.truncate"}:
            paths = (args[0],)
        elif event in {"os.rename", "os.link", "os.symlink"}:
            paths = args[:2]
        else:
            return
        for path in paths:
            if isinstance(path, int):
                raise PermissionError("offline_activation_write_denied")
            raw = os.fsdecode(path)
            if event == "open" and os.path.normcase(raw) == os.path.normcase(os.devnull):
                continue
            # Native Windows knowledge storage uses extended local paths. Strip
            # only the drive-letter spelling; device and UNC aliases remain
            # outside the approved local target and are denied.
            if os.name == "nt" and raw.startswith("\\\\?\\"):
                local = raw[4:]
                if len(local) < 3 or not local[0].isalpha() or local[1:3] != ":\\":
                    raise PermissionError("offline_activation_write_denied")
                raw = local
            if not Path(raw).resolve().is_relative_to(target):
                raise PermissionError("offline_activation_write_denied")
    sys.addaudithook(audit)


def _child():
    # All imports which freeze native identity happen after environment setup
    # and the Python I/O audit hook. The request travels over stdin, not disk.
    target = Path(os.environ["VIBELUTION_ASSISTANT_NATIVE_ROOT"]).resolve()
    initial_child = os.environ.pop("VIBELUTION_INITIAL_MIGRATION_CHILD", "") == "1"
    if not initial_child:
        _install_audit(target)
    sys.path.insert(0, str(ROOT))
    from core.assistant_runtime.migration_io import MigrationIOError, strict_json
    from contextlib import ExitStack
    result, request, activation_started, channel, claim_started = None, None, False, None, False
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise MigrationIOError("activation_proof_too_large")
        request = strict_json(raw)
        initial = request.get("initialControl")
        if (initial is not None) != initial_child:
            raise MigrationIOError("initial_channel_invalid")
        if initial_child:
            if (type(initial) is not dict or set(initial) != {"binding", "port", "token"}
                    or type(initial["binding"]) is not dict):
                raise MigrationIOError("initial_channel_invalid")
            channel = _initial_channel(initial["port"], initial["token"])
            _install_audit(target)
        if (request.get("schemaVersion") != 1 or request["target"] != str(target)
                or request.get("category") not in {"personal", "knowledge", "affairs_conflicts", "affairs_sync"}):
            raise MigrationIOError("activation_request_invalid")
        _target(target, Path(request["config"]["path"]))
        _verify_file_proofs([request["config"]])
        from core.assistant_runtime.migration_paths import _identity_chain
        def verify_route():
            _verify_file_proofs(request["source"]["authorities"])
            actual, _, verify_storage = storage_authority(Path(request["project"]),
                Path(request["sourceConfig"]), Path(request["projectsHome"]), legacy_home=Path(request["legacyHome"]))
            from vibelution_storage import storage_migration_state_path
            marker_path = storage_migration_state_path(actual)
            if ((marker_path.exists() or marker_path.is_symlink()) != request["storageMarkerPresent"]
                    or actual.data != Path(request["storageData"]) or actual.runtime != Path(request["storageRuntime"])):
                raise MigrationIOError("source_storage_route_changed")
            if (actual.project_id != request["scope"]["projectId"]
                    or actual.instance_id != request["scope"]["instanceId"]):
                raise MigrationIOError("source_project_identity_changed")
            from scripts.assistant_migration_inventory import _bound_route
            workspace, _, _, verify_workspace = _bound_route(actual, Path(request["sourceConfig"]),
                                                            formal_home=Path(request["workspace"]).parent)
            if workspace != Path(request["workspace"]):
                raise MigrationIOError("source_routing_changed")
            _assert_source_target_disjoint(target, (actual.project_root, actual.data, workspace.parent, workspace))
            verify_workspace()
            verify_storage()
            for path, chain in request["route"]:
                current = [[str(node), list(identity)] for node, identity in _identity_chain(Path(path))]
                if current != chain:
                    raise MigrationIOError("source_routing_changed")
        verify_route()
        captured, selected = _capture(Path(request["project"]), Path(request["workspace"]),
            request["scope"], Path(request["grant"]) if request["grant"] else None)
        from core.assistant_runtime.migration_io import read_stable_file
        authorities = tuple(read_stable_file(Path(row["path"]), 16 * 1024 * 1024)
                            for row in request["source"]["authorities"])
        if _source_proof(captured, authorities) != request["source"]:
            raise MigrationIOError("source_snapshot_changed")
        from core.assistant_runtime.migration_active import activate_personal_snapshot
        from core.assistant_runtime.migration_profile import offline_migration_profile
        def prepare_private_dirs():
            for key in ("HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "VIBELUTION_PROJECTS_HOME"):
                Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
        if initial is None:
            prepare_private_dirs()
        from core.assistant_runtime.migration_io import pinned_source_files
        # Acquire the target owner before source guards, so a busy profile
        # returns immediately without holding source files. The source guards
        # remain held for every archive confirmation or native data write.
        with ExitStack() as initial_guards:
            admitted_intent = []
            def before_bootstrap(locked_root):
                nonlocal claim_started
                from core.assistant_runtime.initial_migration_binding import (read_initial_intent,
                    source_identity, authority_identity, target_identity)
                from core.assistant_runtime.migration_io import pinned_target_directory
                from scripts.assistant_migration_inventory import _bound_route
                if initial is None:
                    return
                if locked_root != target:
                    raise MigrationIOError("initial_migration_binding_changed")
                bound = initial["binding"]
                intent = read_initial_intent(target, request["migrationId"])
                if (intent is None or intent["registeredProjectId"] != bound["registeredProjectId"]
                        or intent["revision"] > bound["revision"] or intent["category"] != request["category"]
                        or intent["sourceScope"] != request["scope"]
                        or bound["operationId"] != request["migrationId"]
                        or Path(bound["projectRoot"]) != Path(request["project"])
                        or Path(bound["sourceConfig"]) != Path(request["sourceConfig"])
                        or Path(bound["targetProfile"]) != target
                        or Path(bound["targetConfig"]) != Path(request["config"]["path"])
                        or Path(bound["targetConfig"]) != target / (".initial-migration-models-v1-"
                            + request["migrationId"] + "-" + intent["registryDigest"] + ".toml")):
                    raise MigrationIOError("initial_migration_binding_changed")
                admitted_intent.append(intent)
                actual, storage, verify_storage = storage_authority(Path(request["project"]),
                    Path(request["sourceConfig"]), Path(request["projectsHome"]), legacy_home=Path(request["legacyHome"]))
                workspace, _, routing, verify_workspace = _bound_route(actual, Path(request["sourceConfig"]),
                                                                    formal_home=Path(request["workspace"]).parent)
                registry = next((x for x in selected if x.path == workspace / "agents/agents.json"), None)
                if registry is None or workspace != Path(request["workspace"]):
                    raise MigrationIOError("initial_migration_binding_changed")
                snapshots = (*routing, registry, *storage)
                all_source = tuple(item for rows in captured.snapshots.values() for item in rows)
                target_config = read_stable_file(Path(request["config"]["path"]), 16 * 1024 * 1024)
                if _snapshot_proof(target_config) != request["config"]:
                    raise MigrationIOError("initial_migration_binding_changed")
                initial_guards.enter_context(pinned_source_files((*authorities, *all_source, target_config)))
                verify_storage()
                verify_workspace()
                verify_route()
                sd, project_id, workspace_id = source_identity(request["scope"], actual.project_root, workspace)
                td, target_id = target_identity(target, intent["targetAgentId"], intent["targetSessionId"])
                if (sd != intent["sourceIdentityDigest"] or project_id != intent["projectDirectory"]
                        or workspace_id != intent["workspaceDirectory"] or authority_identity(snapshots) != intent["registryDigest"]
                        or td != intent["targetIdentityDigest"] or target_id != intent["targetDirectory"]):
                    raise MigrationIOError("initial_migration_binding_changed")
                if _initial_receipts_or_claim(target, request["migrationId"], request["category"]):
                    raise MigrationIOError("activation_outcome_unknown")
                permit = _initial_call(channel, initial["token"], "POST", "/permit")
                if (type(permit) is not dict or set(permit) != {"schemaVersion", "granted"}
                        or type(permit["schemaVersion"]) is not int or permit["schemaVersion"] != 1
                        or permit["granted"] is not True):
                    raise MigrationIOError("initial_permit_denied")
                verify_route()
                # A directory creation is the one-way claim. A crash during
                # metadata publication still leaves a permanent unknown claim.
                with pinned_target_directory(target / "initial_migration_claims", create=True) as claims:
                    try:
                        (claims / request["migrationId"]).mkdir()
                    except FileExistsError:
                        raise MigrationIOError("activation_outcome_unknown") from None
                    claim_started = True
                    from core.assistant_runtime.migration_history import _write_new
                    _write_new(claims / request["migrationId"] / "claim.json", json.dumps({
                        "schemaVersion": 1, "operationId": request["migrationId"],
                        "category": request["category"]}, sort_keys=True, separators=(",", ":")).encode("ascii"))
                prepare_private_dirs()
                verify_route()
            if initial is not None:
                import inspect
                if "before_bootstrap" not in inspect.signature(offline_migration_profile).parameters:
                    raise MigrationIOError("initial_profile_hook_unavailable")
                profile = offline_migration_profile(before_bootstrap=before_bootstrap)
            else:
                profile = offline_migration_profile()
            with profile as lease, pinned_source_files(authorities):
                verify_route()
                if initial is not None:
                    from core.assistant_runtime.initial_migration_binding import read_initial_intent
                    intent = read_initial_intent(target, request["migrationId"])
                    if (not admitted_intent or intent != admitted_intent[0]
                            or (lease.agent_id, lease.session_id) != (intent["targetAgentId"], intent["targetSessionId"])):
                        raise MigrationIOError("initial_migration_binding_changed")
                activation_started = True
                if request["category"] == "personal":
                    result = activate_personal_snapshot(lease, captured, migration_id=request["migrationId"],
                        source_roots=(Path(request["project"]), Path(request["workspace"])),
                        authority_snapshots=authorities, authority_verify=verify_route)
                elif request["category"] in {"affairs_conflicts", "affairs_sync"}:
                    from core.assistant_runtime.migration_active import _selected, _verify_captured
                    from core.assistant_runtime.migration_affairs import _parse_rows
                    from core.assistant_runtime.migration_affairs_conflicts import prepare_affairs_conflicts
                    from core.assistant_runtime.migration_source_archive import import_source_snapshots
                    _parse_rows(_selected(captured, "personal_affairs").raw)
                    _verify_captured(captured, authorities, verify_route)
                    archive = import_source_snapshots(captured, lease.root, request["migrationId"],
                        source_roots=(Path(request["project"]), Path(request["workspace"])),
                        authority_snapshots=authorities, authority_verify=verify_route,
                        categories=frozenset({"personal_affairs"}) if request["category"] == "affairs_sync" else None)
                    conflicts = prepare_affairs_conflicts(lease,
                        baseline_migration_id=request.get("baselineMigrationId"),
                        snapshot_migration_id=request["migrationId"], sync_id=request["migrationId"],
                        source_scope=request["scope"])
                    result = {"status": "complete", "archive": archive, "conflicts": conflicts,
                        "sourceScope": request["scope"], "sourceQuiesced": False, "readyForCutover": False}
                    _verify_captured(captured, authorities, verify_route)
                    if request["category"] == "affairs_sync":
                        from core.assistant_runtime.migration_affairs_sync import reconcile_affairs
                        # The selected ledger stays pinned through the target
                        # write, not merely checked before and after it.
                        with pinned_source_files((_selected(captured, "personal_affairs"),)):
                            _verify_captured(captured, authorities, verify_route)
                            result["sync"] = reconcile_affairs(lease, sync_id=request["migrationId"],
                                source_scope=request["scope"])
                            if result["sync"]["conflictCount"]:
                                result["status"] = "partial"
                            _verify_captured(captured, authorities, verify_route)
                else:
                    from core.assistant_runtime.migration_knowledge import import_private_knowledge
                    registry_root = Path(request["workspace"]) / "knowledge/sources/registry"
                    selected = {item.path: item for item in authorities}
                    knowledge = import_private_knowledge(lease, captured,
                        central=selected[registry_root / "source_registry.jsonl"],
                        owner_refs=selected[registry_root / "owner_refs.jsonl"],
                        migration_id=request["migrationId"], authority_verify=verify_route)
                    result = {"status": "complete", "knowledge": knowledge, "sourceScope": request["scope"],
                        "sourceQuiesced": False, "readyForCutover": False}
                result["migrationId"] = request["migrationId"]
        verify_route()
        _verify_file_proofs([request["config"]])
    except TimeoutError:
        if result is not None and result.get("status") in {"complete", "partial"}:
            mark_reconciliation(result, request["migrationId"], "activation_outcome_unknown")
        elif activation_started or claim_started:
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": "activation_outcome_unknown"}
        else:
            result = {"ok": False, "code": "TARGET_PROFILE_BUSY"}
    except MigrationIOError as error:
        if result is not None and result.get("status") in {"complete", "partial"}:
            mark_reconciliation(result, request["migrationId"], str(error))
        elif (activation_started and request.get("category") == "knowledge"
                and str(error) == "knowledge_native_promotion_blocked"):
            # The adapter checks this policy before any knowledge/receipt
            # write while the target config and sandbox routing are pinned.
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": str(error)}
        elif claim_started or activation_started and request.get("category") == "knowledge":
            # Native KB ingestion is not transactional: a failure may follow
            # committed writes even if the adapter could not return a receipt.
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": "activation_outcome_unknown"}
        else:
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": str(error)}
    except Exception:
        if result is not None and result.get("status") in {"complete", "partial"}:
            mark_reconciliation(result, request["migrationId"], "activation_outcome_unknown")
        else:
            result = {"ok": False, "code": "SOURCE_MIGRATION_UNAVAILABLE", "reason": "activation_outcome_unknown"}
    finally:
        if channel is not None:
            channel.close()
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("ok") is False else 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--offline-child"]:
        raise SystemExit("Use assistant_migration_inventory.py --activate-personal or --activate-knowledge")
    raise SystemExit(_child())
