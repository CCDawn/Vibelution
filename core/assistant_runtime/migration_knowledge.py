"""Operator-authorized, offline migration of provable private formal knowledge.

The trusted caller owns source authorization and supplies SourcePaths plus exact
canonical central-registry/owner-ref snapshots. Hashes prove integrity, not
authorization. This bounded slice accepts direct reviews and their provable,
single-source owner-reviewed revisions. Unsupported chains never become active.
No model action, host, session execution, grant, or cutover claim is introduced.
"""
from __future__ import annotations

from contextlib import ExitStack
from collections.abc import Callable
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
    proposals = {r["proposalId"]: r for r in load("refinement_proposals.jsonl", "proposalId")} if "refinement_proposals.jsonl" in files else {}
    # Parse strictly, then retain only references selected by this private owner.
    central_ids = {a.get("centralSourceId") for a in artifacts.values()}
    central_rows = {r["centralSourceId"]: r for r in _rows(central.raw, "centralSourceId") if r["centralSourceId"] in central_ids}
    refs = [r for r in _rows(owner_refs.raw, "ownerRefId") if r.get("centralSourceId") in central_ids
        and _private(r, scope["agentId"])]
    if any(not _private(r, scope["agentId"]) for r in [*bases.values(), *items, *artifacts.values(), *batches.values(), *inbox.values()]):
        _fail("foreign_source_owner")
    by_id = {r["knowledgeItemId"]: r for r in items}
    def receipt(action, actor, **fields):
        return any(r.get("action") == action and r.get("actorAgentId") == actor
            and _private(r.get("payload", {}), scope["agentId"])
            and all(r.get("payload", {}).get(k) == v for k, v in fields.items()) for r in audit)
    def chain_for(item):
        chain, seen = [], set()
        while True:
            iid = item["knowledgeItemId"]
            if iid in seen or len(chain) >= 128:
                _fail("revision_chain_unsupported")
            seen.add(iid)
            chain.append(item)
            parent = item.get("supersedesKnowledgeItemId")
            if item.get("ingestionMode") == "source_review_direct":
                if type(item.get("revision")) is not int or item["revision"] != 1 or parent:
                    _fail("revision_chain_unsupported")
                break
            previous = by_id.get(parent)
            if (not previous or type(item.get("revision")) is not int
                    or type(previous.get("revision")) is not int or item["revision"] != previous["revision"] + 1
                    or item.get("knowledgeBaseId") != previous.get("knowledgeBaseId")
                    or item.get("sourceArtifactIds") != previous.get("sourceArtifactIds")
                    or item.get("centralSourceIds") != previous.get("centralSourceIds")
                    or item.get("rootKnowledgeItemId") != previous.get("rootKnowledgeItemId")
                    or sum(r.get("supersedesKnowledgeItemId") == parent for r in items) != 1):
                _fail("revision_chain_unsupported")
            item = previous
        if any(r.get("rootKnowledgeItemId") != iid for r in chain):
            _fail("revision_chain_unsupported")
        return chain
    def prove_proposal(item, batch):
        proposal_ids = batch.get("proposalIds")
        if not isinstance(proposal_ids, list) or len(proposal_ids) != 1:
            _fail("proposal_lineage_unprovable")
        proposal = proposals.get(proposal_ids[0], {})
        pid, iid, bid = proposal.get("proposalId"), item["knowledgeItemId"], item["knowledgeBaseId"]
        reviewer = scope["agentId"]
        parent = by_id.get(item.get("supersedesKnowledgeItemId"), {})
        if (not _private(proposal, reviewer) or proposal.get("status") != "applied"
                or proposal.get("targetKnowledgeBaseId") != bid or proposal.get("batchId") != batch["batchId"]
                or proposal.get("knowledgeItemIds") != [iid] or proposal.get("proposedByAgentId") != reviewer
                or proposal.get("reviewedByAgentId") != reviewer or proposal.get("requiredReviewerAgentId")
                or item.get("requiredReviewerAgentId") or item.get("ingestionMode")
                or item.get("lifecycleStatus") != "applied"
                or proposal.get("expectedContentSha256") != lifecycle.content_sha256(parent)
                or not isinstance(proposal.get("revisionReason"), str)
                or not 0 < len(proposal["revisionReason"].strip()) <= 1000
                or any(proposal.get(k) != item.get(k) for k in ("sourceArtifactIds", "centralSourceIds",
                    "title", "summary", "content", "reviewedAt", "sourceLifecycleRevisions", "revision",
                    "rootKnowledgeItemId", "supersedesKnowledgeItemId", "revisionReason"))
                or not receipt("knowledge.proposal.created", reviewer, proposalId=pid, knowledgeBaseId=bid, status="pending")
                or not receipt("knowledge.proposal.reviewed", reviewer, proposalId=pid, batchId=batch["batchId"],
                    knowledgeBaseId=bid, status="applied")
                or not receipt("knowledge.batch.applied", reviewer, batchId=batch["batchId"], knowledgeBaseId=bid, status="applied")):
            _fail("proposal_lineage_unprovable")
        for field in ("createdAt", "updatedAt", "reviewedAt"):
            lifecycle._date(proposal.get(field))
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
        chain = chain_for(item)
        root_item = chain[-1]
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
        batch = batches.get(root_item.get("batchId"), {})
        reviewer = item.get("reviewedByAgentId")
        for record, fields in ((item, ("createdAt", "updatedAt", "reviewedAt", "appliedAt")),
                (source, ("capturedAt", "reviewedAt")), (batch, ("appliedAt",))):
            for field in fields:
                lifecycle._date(record.get(field))
        if (not isinstance(item.get("content"), str) or not item["content"].strip()
                or s._normalize_formal_knowledge_content(item["content"]) != item["content"]
                or not isinstance(item.get("title"), str) or not item["title"].strip()
                or artifact.get("knowledgeBaseId") != bid or source.get("status") != "accepted"
                or source.get("knowledgeBaseId") != bid or source.get("knowledgeItemId") != root_item["knowledgeItemId"]
                or source.get("centralSourceId") != cid or item.get("centralSourceIds") != [cid]
                or batch.get("knowledgeBaseId") != bid or batch.get("status") != "applied"
                or batch.get("sourceArtifactIds") != source_ids or batch.get("centralSourceIds") != [cid]
                or reviewer != scope["agentId"] or batch.get("reviewedByAgentId") != reviewer
                or batch.get("appliedAt") != root_item.get("appliedAt") or source.get("reviewedAt") != root_item.get("reviewedAt")
                or source.get("reviewedByAgentId") != reviewer or not item.get("reviewedAt")
                or artifact.get("sourceHash") != source.get("sourceHash")
                or central_rows.get(cid, {}).get("sourceHash") != artifact.get("sourceHash")
                or not any(r.get("centralSourceId") == cid and r.get("inboxSourceId") == source.get("inboxSourceId")
                    and r.get("decision") == "accepted" and r.get("sourceHash") == artifact.get("sourceHash") for r in refs)
                or not any(r.get("action") == "knowledge.item.direct_ingested" and r.get("actorAgentId") == reviewer
                    and r.get("payload", {}).get("knowledgeItemId") == root_item["knowledgeItemId"] for r in audit)
                or not any(r.get("action") == "knowledge.source_inbox.reviewed" and r.get("actorAgentId") == reviewer
                    and r.get("payload", {}).get("inboxSourceId") == source.get("inboxSourceId") for r in audit)):
            _fail("source_lineage_unprovable")
        for version in chain:
            version_batch = batches.get(version.get("batchId"), {})
            if (version.get("contentSha256") != lifecycle.content_sha256(version)
                    or not isinstance(version.get("content"), str) or not version["content"].strip()
                    or s._normalize_formal_knowledge_content(version["content"]) != version["content"]
                    or not isinstance(version.get("title"), str) or not version["title"].strip()
                    or version.get("status", "active") != "active" or version.get("reviewedByAgentId") != reviewer
                    or version.get("sourceLifecycleRevisions") != {source_ids[0]: artifact.get("lifecycleRevision", 0)}
                    or version_batch.get("knowledgeBaseId") != bid or version_batch.get("status") != "applied"
                    or version_batch.get("sourceArtifactIds") != source_ids or version_batch.get("centralSourceIds") != [cid]
                    or version_batch.get("reviewedByAgentId") != reviewer
                    or version_batch.get("appliedAt") != version.get("appliedAt")
                    or version.get("reviewedAt") != version.get("appliedAt")):
                _fail("source_lineage_unprovable")
            for field in ("createdAt", "updatedAt", "reviewedAt", "appliedAt"):
                lifecycle._date(version.get(field))
            if version is not root_item:
                prove_proposal(version, version_batch)
            elif version_batch.get("proposalIds") != [] or version_batch.get("ingestionMode") != "source_review_direct":
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


def _target(lease, state, s):
    """Bind native paths and owner identity to one unchanged routing authority."""
    from core.web.services import agent_directory_service as directory
    from core.infrastructure.developer_sandbox import existing_sandboxed_workspace_path
    try:
        state.verify_workspace()
        workspace = existing_sandboxed_workspace_path(lease.root, public_config=state.config)
    except (OSError, ValueError, TypeError):
        _fail("workspace_changed")
    if (s.PROJECT_ROOT != lease.root or directory.PROJECT_ROOT != lease.root
            or workspace.resolve() != state.path() or not workspace.is_relative_to(lease.root)):
        _fail("target_binding_invalid")
    check_path(workspace)
    agent = directory.get_agent(lease.agent_id, include_archived=True)
    if not agent or agent.get("workspacePath") != f"workspace/agents/{lease.agent_id}":
        _fail("target_binding_invalid")
    owner = s._require_owner_context("agent", lease.agent_id)
    if (s._route_team_knowledge_workspace_path(seed=False) != workspace
            or s._knowledge_root_for_owner(owner) != workspace / "agents" / lease.agent_id / "knowledge"
            or s._central_source_registry_path() != workspace / "knowledge/sources/registry/source_registry.jsonl"
            or s._central_owner_refs_path() != workspace / "knowledge/sources/registry/owner_refs.jsonl"
            or s._central_source_accepted_dir() != workspace / "knowledge/sources/accepted"):
        _fail("target_binding_invalid")
    try:
        state.verify_workspace()
    except (OSError, ValueError, TypeError):
        _fail("workspace_changed")
    return owner


def _promotion_allowed(s):
    from core.infrastructure.developer_sandbox import DeveloperSandboxWriteBlocked
    try:
        s._assert_central_source_write_allowed()
    except DeveloperSandboxWriteBlocked:
        _fail("native_promotion_blocked")


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
        # Routing may change while the durable intent is published. Recheck
        # before its following native operation can resolve a different path.
        verify()
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
        owner_refs: FileSnapshot, migration_id: str,
        authority_verify: Callable[[], None] | None = None) -> dict:
    """Activate provable direct reviews and bounded private revision chains.

    Pending, withdrawn, expired and superseded items never become active. An
    incomplete revision/proposal proof refuses the entire import. Each origin
    has a durable intent before native writes. Unknown outcomes fail closed;
    retries read the native IDs and never issue a second create/review.
    A trusted operator adapter may additionally pin its source authorization
    authority; its verifier runs at the same boundaries as the file proofs.
    """
    _lease(lease)
    if not isinstance(migration_id, str) or not _TOKEN.fullmatch(migration_id):
        _fail("migration_id_invalid")
    if authority_verify is not None and not callable(authority_verify):
        _fail("authority_verifier_invalid")
    try:
        if authority_verify is not None:
            authority_verify()
        scope, source_root, files, snapshots, verify = _source(resolved, central, owner_refs)
    except MigrationIOError:
        raise
    except Exception:
        _fail("source_proof_invalid")
    if Path(lease.root).is_relative_to(source_root) or source_root.is_relative_to(Path(lease.root)):
        _fail("source_target_overlap")
    try:
        from core.web.services import team_knowledge_service as s
        from core.web.services import agent_directory_service as directory
        from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
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
            try:
                from core.infrastructure import developer_sandbox
                # Native APIs resolve routing internally after our checks. Hold
                # the same existing authorities read-only until all native IO
                # and receipts finish, including their physical namespaces.
                config_path = Path(directory.CONFIG_PATH)
                stack.enter_context(_locked_source(Path(config_path.anchor), config_path, directory=False))
                active_path = developer_sandbox._active_state_path(lease.root)
                if active_path.exists():
                    stack.enter_context(_locked_source(Path(active_path.anchor), active_path, directory=False))
                state = ExistingStateSnapshot(lease.root, directory, pin_workspace=True)
            except (OSError, ValueError, TypeError):
                _fail("workspace_changed")
            source_verify = verify
            def verify():
                if authority_verify is not None:
                    authority_verify()
                source_verify()
                _lease(lease)
                try:
                    state.verify_workspace()
                except (OSError, ValueError, TypeError):
                    _fail("workspace_changed")
                # Even an empty plan must not reach seeded target resolvers or
                # create a migration archive while sandbox promotion is blocked.
                _promotion_allowed(s)
                _target(lease, state, s)
            verify()
            owner = _target(lease, state, s)
            folder = lease.root / "knowledge_migrations"
            with native._LOCK, s._LOCK, pinned_target_directory(folder, create=True), migration_target_lock(folder):
                _lease(lease)
                verify()
                _pin_target(stack, s, owner)
                verify()
                _archive(folder / "archives" / proof, files, central_rows, refs, scope, central, owner_refs)
                verify()
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
