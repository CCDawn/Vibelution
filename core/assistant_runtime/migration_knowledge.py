"""Operator-authorized, offline migration of provable private formal knowledge.

The trusted caller owns source authorization and supplies SourcePaths plus exact
canonical central-registry/owner-ref snapshots. Hashes prove integrity, not
authorization. This bounded slice accepts original direct-reviewed items only;
revision/proposal chains it cannot prove stay archived and never become active.
No model action, host, session execution, grant, or cutover claim is introduced.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re

from core.infrastructure.atomic_io import atomic_write_json

from .migration_io import (FileSnapshot, MigrationIOError, check_path, path_identity,
    fingerprint_tree, pinned_target_directory, migration_target_lock, read_stable_file, strict_json, verify_snapshot)
from .migration_paths import SourcePaths

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_MAX_FILES, _MAX_BYTES, _MAX_FILE = 256, 16 * 1024 * 1024, 4 * 1024 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _fail(code):
    raise MigrationIOError("knowledge_" + code)


def _lease(lease):
    from .migration_profile import OfflineMigrationProfileLease
    if not isinstance(lease, OfflineMigrationProfileLease):
        _fail("profile_lease_required")
    try:
        lease.check()
    except RuntimeError:
        _fail("profile_lease_required")


def _rows(raw, key):
    if len(raw.splitlines()) > 4096:
        _fail("row_limit")
    rows, ids = [], set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = strict_json(line)
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not _TOKEN.fullmatch(row[key]):
            _fail("source_schema_invalid")
        if row[key] in ids:
            _fail("duplicate_source_id")
        ids.add(row[key])
        rows.append(row)
    return rows


def _private(row, agent):
    return (row.get("ownerType") == "agent" and row.get("ownerId") == agent
        and row.get("agentId") == agent and not row.get("teamId"))


def _empty_acl(base):
    acl = base.get("acl")
    return (isinstance(acl, dict) and isinstance(acl.get("grants"), dict)
        and not any(acl["grants"].values()) and not base.get("profile"))


def _source(resolved, central, owner_refs):
    if not isinstance(resolved, SourcePaths) or resolved.report.get("stage") != "source_snapshot":
        _fail("source_snapshot_required")
    scope = resolved.report.get("sourceScope")
    if (not isinstance(scope, dict) or set(scope) != {"projectId", "instanceId", "agentId"}
            or any(not isinstance(v, str) or not _TOKEN.fullmatch(v) for v in scope.values())):
        _fail("source_scope_invalid")
    private_sources = [r for r in resolved.report.get("sources", []) if r.get("category") == "private_knowledge"]
    candidates = [r for r in private_sources if r.get("status") == "available"]
    if len(candidates) != 1 or any(r.get("status") not in {"available", "missing"} for r in private_sources):
        _fail("private_source_ambiguous")
    row = candidates[0]
    ref = row["sourceRef"]
    root = resolved.paths.get(ref)
    snapshots = resolved.snapshots.get(ref)
    if (not isinstance(root, Path) or not snapshots or
            tuple(root.parts[-3:]) != ("agents", scope["agentId"], "knowledge")):
        _fail("source_root_invalid")
    check_path(root)
    workspace = root.parents[2]
    for snapshot, name in ((central, "source_registry.jsonl"), (owner_refs, "owner_refs.jsonl")):
        if (not isinstance(snapshot, FileSnapshot) or snapshot.path != workspace / "knowledge/sources/registry" / name):
            _fail("central_proof_required")
    all_snapshots = (*snapshots, central, owner_refs)
    if (any(not isinstance(s, FileSnapshot) or not isinstance(s.raw, bytes) for s in all_snapshots)
            or len(all_snapshots) + len(resolved.directoryproofs.get(ref, ())) > _MAX_FILES
            or sum(len(s.raw) for s in all_snapshots) > _MAX_BYTES):
        _fail("source_budget_exceeded")
    files = {}
    for snapshot in all_snapshots:
        if (not isinstance(snapshot.raw, bytes) or len(snapshot.raw) > _MAX_FILE
                or hashlib.sha256(snapshot.raw).hexdigest() != snapshot.sha256):
            _fail("source_proof_invalid")
        verify_snapshot(snapshot)
    for snapshot in snapshots:
        if not snapshot.path.is_relative_to(root):
            _fail("source_root_invalid")
        relative = snapshot.path.relative_to(root).as_posix()
        if relative in files:
            _fail("duplicate_source_path")
        files[relative] = snapshot
    entries = [{"path": name, "size": len(s.raw), "sha256": s.sha256} for name, s in files.items()]
    if sorted(entries, key=lambda r: r["path"]) != sorted(row.get("entries", []), key=lambda r: r["path"]):
        _fail("source_proof_invalid")
    if not resolved.directoryproofs.get(ref):
        _fail("source_proof_invalid")
    def verify():
        for s in all_snapshots:
            verify_snapshot(s)
        for directory, identity in resolved.directoryproofs[ref]:
            if not directory.is_relative_to(root):
                _fail("source_root_invalid")
            check_path(directory)
            if path_identity(directory) != identity:
                raise MigrationIOError("source_changed")
    verify()
    return scope, root, files, all_snapshots, verify


def _plan(scope, files, central, owner_refs):
    from core.web.services.team_knowledge import lifecycle
    from core.web.services import team_knowledge_service as s
    def load(name, key):
        if name not in files:
            _fail("source_proof_incomplete")
        return _rows(files[name].raw, key)
    payload = strict_json(files["knowledge_bases.json"].raw) if "knowledge_bases.json" in files else None
    if (not isinstance(payload, dict) or type(payload.get("schemaVersion")) is not int
            or payload["schemaVersion"] != 1 or not isinstance(payload.get("knowledgeBases"), list)):
        _fail("source_schema_invalid")
    bases = {r["knowledgeBaseId"]: r for r in _rows(
        b"\n".join(json.dumps(r).encode() for r in payload["knowledgeBases"]), "knowledgeBaseId")}
    items = load("items.jsonl", "knowledgeItemId")
    artifacts = {r["sourceArtifactId"]: r for r in load("source_artifacts.jsonl", "sourceArtifactId")}
    batches = {r["batchId"]: r for r in load("batches.jsonl", "batchId")}
    inbox = {r["inboxSourceId"]: r for r in load("inbox/source_index.jsonl", "inboxSourceId")}
    audit = load("audit.jsonl", "auditId")
    # Parse strictly, then retain only references selected by this private owner.
    central_ids = {a.get("centralSourceId") for a in artifacts.values()}
    central_rows = {r["centralSourceId"]: r for r in _rows(central.raw, "centralSourceId") if r["centralSourceId"] in central_ids}
    refs = [r for r in _rows(owner_refs.raw, "ownerRefId") if r.get("centralSourceId") in central_ids
        and _private(r, scope["agentId"])]
    if any(not _private(r, scope["agentId"]) for r in [*bases.values(), *items, *artifacts.values(), *batches.values(), *inbox.values()]):
        _fail("foreign_source_owner")
    states = lifecycle.item_lifecycle_states(items, artifacts, central_sources=central_rows, now=s.utc_now_iso())
    planned, excluded = [], []
    for item in items:
        iid, bid = item["knowledgeItemId"], item.get("knowledgeBaseId")
        base = bases.get(bid)
        reason = states[iid]
        if reason not in {"active", "superseded", "archived", "withdrawn", "expired",
                "source_unavailable", "source_withdrawn", "source_expired", "source_archived",
                "source_superseded", "source_revalidation_required"}:
            _fail("source_schema_invalid")
        if not base or base.get("status") != "active" or not _empty_acl(base):
            _fail("source_acl_unprovable")
        if reason != "active":
            excluded.append({"sourceKnowledgeItemId": iid, "reason": reason})
            continue
        if (item.get("ingestionMode") != "source_review_direct" or item.get("revision") != 1
                or item.get("supersedesKnowledgeItemId") or item.get("contentSha256") != lifecycle.content_sha256(item)):
            _fail("revision_chain_unsupported")
        source_ids = item.get("sourceArtifactIds")
        if not isinstance(source_ids, list) or len(source_ids) != 1:
            _fail("source_lineage_unprovable")
        artifact = artifacts.get(source_ids[0], {})
        source = inbox.get(artifact.get("inboxSourceId"), {})
        cid = artifact.get("centralSourceId")
        # Native ingestion creates a fresh source with no expiry. Do not turn
        # a time-limited authorization into perpetual active knowledge.
        if artifact.get("expiresAt") or central_rows.get(cid, {}).get("expiresAt"):
            _fail("source_expiry_unsupported")
        batch = batches.get(item.get("batchId"), {})
        reviewer = item.get("reviewedByAgentId")
        for record, fields in ((item, ("createdAt", "updatedAt", "reviewedAt", "appliedAt")),
                (source, ("capturedAt", "reviewedAt")), (batch, ("appliedAt",))):
            for field in fields:
                lifecycle._date(record.get(field))
        if (not isinstance(item.get("content"), str) or not item["content"].strip()
                or s._normalize_formal_knowledge_content(item["content"]) != item["content"]
                or not isinstance(item.get("title"), str) or not item["title"].strip()
                or artifact.get("knowledgeBaseId") != bid or source.get("status") != "accepted"
                or source.get("knowledgeBaseId") != bid or source.get("knowledgeItemId") != iid
                or source.get("centralSourceId") != cid or item.get("centralSourceIds") != [cid]
                or batch.get("knowledgeBaseId") != bid or batch.get("status") != "applied"
                or batch.get("sourceArtifactIds") != source_ids or batch.get("centralSourceIds") != [cid]
                or reviewer != scope["agentId"] or batch.get("reviewedByAgentId") != reviewer
                or batch.get("appliedAt") != item.get("appliedAt") or source.get("reviewedAt") != item.get("reviewedAt")
                or source.get("reviewedByAgentId") != reviewer or not item.get("reviewedAt")
                or artifact.get("sourceHash") != source.get("sourceHash")
                or central_rows.get(cid, {}).get("sourceHash") != artifact.get("sourceHash")
                or not any(r.get("centralSourceId") == cid and r.get("inboxSourceId") == source.get("inboxSourceId")
                    and r.get("decision") == "accepted" and r.get("sourceHash") == artifact.get("sourceHash") for r in refs)
                or not any(r.get("action") == "knowledge.item.direct_ingested" and r.get("actorAgentId") == reviewer
                    and r.get("payload", {}).get("knowledgeItemId") == iid for r in audit)
                or not any(r.get("action") == "knowledge.source_inbox.reviewed" and r.get("actorAgentId") == reviewer
                    and r.get("payload", {}).get("inboxSourceId") == source.get("inboxSourceId") for r in audit)):
            _fail("source_lineage_unprovable")
        planned.append(item)
    return planned, excluded, central_rows, refs


def _write_state(path, state):
    atomic_write_json(path, state, strict_replace=True, sort_keys=True)


def _validate_state(state, binding):
    phases = {"base_intent": set(), "collect_intent": {"knowledgeBaseId"},
        "review_intent": {"knowledgeBaseId", "inboxSourceId"}, "published": {"mapping"}}
    if (not isinstance(state, dict) or type(state.get("schemaVersion")) is not int
            or state["schemaVersion"] != 1 or state.get("phase") not in phases
            or set(state) != {"schemaVersion", "binding", "migrationId", "phase"} | phases[state["phase"]]
            or state.get("binding") != binding or not isinstance(state.get("migrationId"), str)
            or not _TOKEN.fullmatch(state["migrationId"])):
        _fail("origin_binding_conflict")
    for field in phases[state["phase"]] - {"mapping"}:
        if not isinstance(state[field], str) or not _TOKEN.fullmatch(state[field]):
            _fail("target_state_invalid")
    if state["phase"] == "published":
        mapping = state["mapping"]
        fields = {"sourceScope", "sourceKnowledgeBaseId", "sourceKnowledgeItemId", "knowledgeBaseId",
            "knowledgeItemId", "inboxSourceId", "sourceArtifactIds", "centralSourceIds", "operation"}
        if (not isinstance(mapping, dict) or set(mapping) != fields
                or any(mapping[key] != binding[key] for key in ("sourceScope", "sourceKnowledgeBaseId", "sourceKnowledgeItemId", "operation"))):
            _fail("target_state_invalid")
        for key in ("knowledgeBaseId", "knowledgeItemId", "inboxSourceId"):
            if not isinstance(mapping[key], str) or not _TOKEN.fullmatch(mapping[key]):
                _fail("target_state_invalid")
        for key in ("sourceArtifactIds", "centralSourceIds"):
            if (not isinstance(mapping[key], list) or len(mapping[key]) != 1
                    or any(not isinstance(v, str) or not _TOKEN.fullmatch(v) for v in mapping[key])):
                _fail("target_state_invalid")


def _archive(path, files, central_rows, refs, scope, central, owner_refs):
    from .migration_history import _write_new
    with pinned_target_directory(path, create=True):
        for name, snapshot in files.items():
            _write_new(path / "private" / name, snapshot.raw)
        # Global registries may contain other owners. Preserve selected rows
        # only, with full snapshot hashes in the separate proof binding.
        _write_new(path / "selected-central.json", json.dumps(list(central_rows.values()), sort_keys=True).encode())
        _write_new(path / "selected-owner-refs.json", json.dumps(refs, sort_keys=True).encode())
        _write_new(path / "manifest.json", json.dumps({"schemaVersion": 1, "sourceScope": scope,
            "readOnly": True, "untrustedContent": True, "originalReviewReplayed": False,
            "privateFiles": {name: snapshot.sha256 for name, snapshot in files.items()},
            "centralRegistrySha256": central.sha256, "ownerRefsSha256": owner_refs.sha256,
            "globalRegistryFiltered": True, "readyForCutover": False}, sort_keys=True).encode())


def _target_rows(s, owner, path_fn, key):
    path = path_fn(owner)
    return _rows(read_stable_file(path, _MAX_FILE).raw, key) if path.exists() else []


def _pin_target(stack, s, owner):
    """Reject existing target links/corruption before native lenient readers."""
    private = s._knowledge_root_for_owner(owner)
    for path in (private, private / "inbox/sources", s._central_source_registry_path().parent,
            s._central_source_accepted_dir()):
        stack.enter_context(pinned_target_directory(path, create=True))
    tree = fingerprint_tree(private, max_file_bytes=_MAX_FILE, max_files=_MAX_FILES, max_total_bytes=_MAX_BYTES)
    for directory, _identity in tree.directories:
        stack.enter_context(pinned_target_directory(directory))
    registry = private / "knowledge_bases.json"
    if registry.exists():
        payload = strict_json(read_stable_file(registry, _MAX_FILE).raw)
        if (not isinstance(payload, dict) or type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != 1
                or not isinstance(payload.get("knowledgeBases"), list)
                or any(not isinstance(row, dict) for row in payload["knowledgeBases"])):
            _fail("target_schema_invalid")
    for path_fn, key in ((s._items_path_for_owner, "knowledgeItemId"), (s._batches_path_for_owner, "batchId"),
            (s._source_artifacts_path_for_owner, "sourceArtifactId"), (s._owner_source_index_path, "inboxSourceId"),
            (s._audit_path_for_owner, "auditId")):
        _target_rows(s, owner, path_fn, key)
    for path, key in ((s._central_source_registry_path(), "centralSourceId"), (s._central_owner_refs_path(), "ownerRefId")):
        if path.exists():
            _rows(read_stable_file(path, _MAX_FILE).raw, key)


def _import_one(lease, s, owner, item, scope, proof, folder, verify, migration_id):
    origin = {"sourceScope": scope, "sourceKnowledgeBaseId": item["knowledgeBaseId"],
        "sourceKnowledgeItemId": item["knowledgeItemId"]}
    key = _digest(origin)
    binding = {**origin, "sourceContentSha256": item["contentSha256"], "sourceProofSha256": proof,
        "targetAgentId": lease.agent_id, "operation": "operator_authorized_migration"}
    state_path = folder / (key + ".json")
    state = strict_json(read_stable_file(state_path, _MAX_FILE).raw) if state_path.exists() else None
    if state is not None:
        _validate_state(state, binding)
    if state and state.get("phase") == "published":
        return state["mapping"], True
    description = "operator-authorized-migration:" + key
    def save(phase, **values):
        nonlocal state
        verify()
        _lease(lease)
        state = {"schemaVersion": 1, "binding": binding, "migrationId": migration_id,
            "phase": phase, **values}
        _write_state(state_path, state)
    bases = [b for b in s._knowledge_bases_for_owner(owner) if b.get("description") == description]
    if len(bases) > 1:
        _fail("target_conflict")
    if state is None:
        if bases:
            _fail("target_conflict")
        save("base_intent")
        s.create_agent_knowledge_base(lease.agent_id, name="Migrated private knowledge " + key[:16],
            description=description, actor_agent_id=lease.agent_id)
        bases = [b for b in s._knowledge_bases_for_owner(owner) if b.get("description") == description]
    if len(bases) != 1:
        _fail("outcome_unknown")
    base = bases[0]
    if not _private(base, lease.agent_id) or not _empty_acl(base) or base.get("status") != "active":
        _fail("target_acl_invalid")
    scoped = s._owner_scoped_knowledge_base_id(owner, base["knowledgeBaseId"])
    sources = _target_rows(s, owner, s._owner_source_index_path, "inboxSourceId")
    sources = [r for r in sources if (r.get("sourceRef") or {}).get("migrationOriginKey") == key]
    if state["phase"] == "base_intent":
        save("collect_intent", knowledgeBaseId=base["knowledgeBaseId"])
        s.collect_source_to_inbox("agent", lease.agent_id, source_type="manual_user_entry",
            source_ref={"migrationOriginKey": key, **binding, "contentTrust": "untrusted_migrated_content"},
            original_content=item["content"], title=item["title"], summary=str(item.get("summary") or ""),
            source_hash="sha256:" + _digest(binding), actor_agent_id=lease.agent_id,
            captured_by="operator_authorized_migration", _idempotency_key="migration:" + key)
        sources = [r for r in _target_rows(s, owner, s._owner_source_index_path, "inboxSourceId")
            if (r.get("sourceRef") or {}).get("migrationOriginKey") == key]
    if len(sources) != 1:
        _fail("outcome_unknown")
    source = sources[0]
    if not _private(source, lease.agent_id) or source.get("sourceHash") != "sha256:" + _digest(binding):
        _fail("target_conflict")
    if state["phase"] == "collect_intent":
        save("review_intent", knowledgeBaseId=base["knowledgeBaseId"], inboxSourceId=source["inboxSourceId"])
        s.review_owner_inbox_source("agent", lease.agent_id, source["inboxSourceId"], decision="accepted",
            reviewed_by_agent_id=lease.agent_id, resolution_note="Operator-authorized migration; original review is archived, not replayed.",
            ingest_on_accept=True, knowledge_base_id=scoped, knowledge_title=item["title"],
            knowledge_summary=str(item.get("summary") or ""), knowledge_content=item["content"])
    # Read persisted native objects, including after lost ACK. Never re-run a
    # review with unknown outcome: native direct ingestion is not transactional.
    source = next((r for r in _target_rows(s, owner, s._owner_source_index_path, "inboxSourceId")
        if r["inboxSourceId"] == source["inboxSourceId"]), {})
    target_items = _target_rows(s, owner, s._items_path_for_owner, "knowledgeItemId")
    target_item = next((r for r in target_items if r["knowledgeItemId"] == source.get("knowledgeItemId")), None)
    if source.get("status") != "accepted" or target_item is None:
        _fail("outcome_unknown")
    if (not _private(target_item, lease.agent_id) or target_item.get("knowledgeBaseId") != base["knowledgeBaseId"]
            or target_item.get("contentSha256") != item["contentSha256"]
            or hashlib.sha256(target_item.get("content", "").encode()).hexdigest() != item["contentSha256"]
            or target_item.get("reviewedByAgentId") != lease.agent_id):
        _fail("target_conflict")
    artifacts = {r["sourceArtifactId"]: r for r in _target_rows(s, owner, s._source_artifacts_path_for_owner, "sourceArtifactId")}
    if s._tk_lifecycle.lifecycle_states_for_base(owner, base, [target_item], artifacts).get(target_item["knowledgeItemId"]) != "active":
        _fail("target_lifecycle_invalid")
    mapping = {**origin, "knowledgeBaseId": base["knowledgeBaseId"], "knowledgeItemId": target_item["knowledgeItemId"],
        "inboxSourceId": source["inboxSourceId"], "sourceArtifactIds": target_item["sourceArtifactIds"],
        "centralSourceIds": target_item["centralSourceIds"], "operation": "operator_authorized_migration"}
    save("published", mapping=mapping)
    return mapping, False


def import_private_knowledge(lease, resolved: SourcePaths, *, central: FileSnapshot,
        owner_refs: FileSnapshot, migration_id: str) -> dict:
    """Activate only provable original private direct reviews under an offline lease.

    Pending, withdrawn, expired and superseded items never become active. An
    incomplete revision/proposal proof refuses the entire import. Each origin
    has a durable intent before native writes. Unknown outcomes fail closed;
    retries read the native IDs and never issue a second create/review.
    """
    _lease(lease)
    if not isinstance(migration_id, str) or not _TOKEN.fullmatch(migration_id):
        _fail("migration_id_invalid")
    try:
        scope, source_root, files, snapshots, verify = _source(resolved, central, owner_refs)
    except MigrationIOError:
        raise
    except Exception:
        _fail("source_proof_invalid")
    if Path(lease.root).is_relative_to(source_root) or source_root.is_relative_to(Path(lease.root)):
        _fail("source_target_overlap")
    try:
        from core.web.services import team_knowledge_service as s
        from core.web.services.personal_assistant_project.windows_read import _locked_source
        from . import native
        with ExitStack() as stack:
            # Keep every approved source file unwriteable/unreplaceable during
            # native admission; a byte snapshot alone does not freeze a source.
            for snapshot in snapshots:
                stack.enter_context(_locked_source(Path(snapshot.path.anchor), snapshot.path, directory=False))
            verify()
            planned, excluded, central_rows, refs = _plan(scope, files, central, owner_refs)
            proof = _digest({"files": {n: f.sha256 for n, f in files.items()},
                "central": central.sha256, "ownerRefs": owner_refs.sha256})
            owner = s._require_owner_context("agent", lease.agent_id)
            workspace = s._route_team_knowledge_workspace_path(seed=False)
            if (s.PROJECT_ROOT != lease.root or not workspace.is_relative_to(lease.root)
                    or s._knowledge_root_for_owner(owner) != workspace / "agents" / lease.agent_id / "knowledge"):
                _fail("target_binding_invalid")
            folder = lease.root / "knowledge_migrations"
            with native._LOCK, s._LOCK, pinned_target_directory(folder, create=True), migration_target_lock(folder):
                _lease(lease)
                verify()
                _pin_target(stack, s, owner)
                _archive(folder / "archives" / proof, files, central_rows, refs, scope, central, owner_refs)
                mappings, imported = [], 0
                for item in planned:
                    mapping, reused = _import_one(lease, s, owner, item, scope, proof, folder, verify, migration_id)
                    mappings.append(mapping)
                    imported += not reused
                verify()
                return {"schemaVersion": 1, "targetAgentId": lease.agent_id, "importedCount": imported,
                    "idempotent": imported == 0, "mappings": mappings, "excluded": excluded,
                    "sourceProofSha256": proof, "sourceQuiesced": False, "readyForCutover": False}
    except MigrationIOError:
        raise
    except Exception:
        _fail("native_operation_unavailable")


__all__ = ["import_private_knowledge"]
