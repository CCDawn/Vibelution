"""Conservative offline reconciliation of independently reviewed legacy knowledge.

Proven source revisions apply only when the target baseline remains untouched.
Missing or withdrawn source rows, target edits, and missing baseline proofs are
conflicts. This does not claim full convergence or source quiescence. The caller
must hold the offline target profile and provide trusted source proof.

The evidence hashes and OS ownership lock detect inconsistent or interrupted
local state. They are not signatures and cannot detect an external actor who
can coherently rewrite or remove every evidence file and native audit record.
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

from . import migration_knowledge as k
from .migration_io import (MigrationIOError, fingerprint_tree, migration_target_lock, pinned_target_directory,
                           read_stable_file, strict_json)


def _receipt_mappings(plan, receipt):
    """Validate full or explicitly terminal partial receipts."""
    if not isinstance(receipt, dict) or set(receipt) not in (
            {"planSha256", "mappings"}, {"planSha256", "mappings", "skippedSourceKnowledgeItemIds"},
            {"planSha256", "mappings", "skippedSourceKnowledgeItemIds", "terminalSha256"}):
        k._fail("sync_receipt_invalid")
    mappings = receipt["mappings"]
    skipped = receipt.get("skippedSourceKnowledgeItemIds", [])
    ids = plan["sourceKnowledgeItemIds"]
    if (receipt["planSha256"] != k._digest(plan) or not isinstance(mappings, list)
            or any(not isinstance(row, dict) for row in mappings) or not isinstance(skipped, list)
            or skipped != ids[len(mappings):] or (skipped and plan["schemaVersion"] != 3)
            or not skipped and "terminalSha256" in receipt
            or [row.get("sourceKnowledgeItemId") for row in mappings] != ids[:len(mappings)]):
        k._fail("sync_receipt_invalid")
    return mappings, skipped


def _validate_skip_terminal(folder, plan, terminal, skipped, count, *, receipt=None):
    """Verify the original operation's skipped-item evidence after later syncs."""
    item_dir = folder / "sync_items" / k._digest(plan["syncId"])
    base = {"planSha256": k._digest(plan), "completedCount": count, "skippedSourceKnowledgeItemIds": skipped}
    if not isinstance(terminal, dict) or type(terminal.get("schemaVersion")) is not int:
        k._fail("sync_receipt_invalid")
    if terminal["schemaVersion"] == 1:
        if terminal != {"schemaVersion": 1, **base} or receipt and "terminalSha256" in receipt:
            k._fail("sync_receipt_invalid")
        # Legacy terminals never had certificates. Their presence means a
        # newer terminal or receipt was damaged or downgraded.
        certificates = [item_dir / (k._digest(iid) + ".not-started.json") for iid in skipped]
        if any(path.exists() or path.is_symlink() for path in
               (*certificates, *(path.with_name(path.name + ".lock") for path in certificates))):
            k._fail("sync_receipt_invalid")
    elif terminal["schemaVersion"] == 2:
        if (set(terminal) != {"schemaVersion", *base, "targetEvidenceSha256", "proofs"}
                or any(terminal.get(name) != value for name, value in base.items())
                or not isinstance(terminal.get("targetEvidenceSha256"), str)
                or not k._SHA256.fullmatch(terminal["targetEvidenceSha256"])
                or not isinstance(terminal.get("proofs"), list) or len(terminal["proofs"]) != len(skipped)
                or receipt is not None and receipt.get("terminalSha256") != k._digest(terminal)):
            k._fail("sync_receipt_invalid")
        archived = _archived_items(folder, plan)
        for offset, iid in enumerate(skipped):
            item = archived.get(iid)
            if not item:
                k._fail("sync_receipt_invalid")
            origin = {"sourceScope": plan["sourceScope"], "sourceKnowledgeBaseId": item["knowledgeBaseId"],
                      "sourceKnowledgeItemId": iid}
            proof = {"schemaVersion": 1, "syncId": plan["syncId"], "planSha256": k._digest(plan),
                     "sourceKnowledgeItemId": iid, "index": count + offset, "originKey": k._digest(origin),
                     "targetEvidenceSha256": terminal["targetEvidenceSha256"]}
            actual = strict_json(read_stable_file(item_dir / (k._digest(iid) + ".not-started.json"), k._MAX_FILE).raw)
            if (not isinstance(actual, dict) or type(actual.get("schemaVersion")) is not int
                    or type(actual.get("index")) is not int or actual != proof
                    or terminal["proofs"][offset] != {"sourceKnowledgeItemId": iid, "proofSha256": k._digest(proof)}):
                k._fail("sync_receipt_invalid")
    else:
        k._fail("sync_receipt_invalid")
    # These paths belong exclusively to this original sync ID. Later syncs
    # may legitimately create target state for the same source item, but can
    # never create an intent or completion in this operation's directory.
    for iid in skipped:
        stem = k._digest(iid)
        paths = (item_dir / (stem + ".intent.json"), item_dir / (stem + ".complete.json"))
        if any(path.exists() or path.is_symlink()
               for path in (*paths, *(path.with_name(path.name + ".lock") for path in paths))):
            k._fail("sync_receipt_invalid")


def _validate_partial_terminal(folder, plan, mappings, skipped, receipt=None):
    if not skipped:
        return
    count = len(mappings)
    item_dir = folder / "sync_items" / k._digest(plan["syncId"])
    terminal = strict_json(read_stable_file(item_dir / "terminal.json", k._MAX_FILE).raw)
    progress = strict_json(read_stable_file(item_dir / "progress.json", k._MAX_FILE).raw)
    if (not isinstance(terminal, dict) or type(terminal.get("schemaVersion")) is not int
            or type(terminal.get("completedCount")) is not int
            or not isinstance(progress, dict) or type(progress.get("schemaVersion")) is not int
            or type(progress.get("nextIndex")) is not int
            or progress != {"schemaVersion": 1, "planSha256": k._digest(plan),
                            "nextIndex": count, "phase": "ready"}):
        k._fail("sync_receipt_invalid")
    _validate_skip_terminal(folder, plan, terminal, skipped, count, receipt=receipt)
    updates = {row["sourceKnowledgeItemId"]: row["parentKey"] for row in plan["updates"]}
    for index, mapping in enumerate(mappings):
        iid = mapping["sourceKnowledgeItemId"]
        stem = k._digest(iid)
        intent = {"schemaVersion": 1, "syncId": plan["syncId"], "planSha256": k._digest(plan),
                  "sourceKnowledgeItemId": iid, "index": index, "parentKey": updates.get(iid)}
        actual = strict_json(read_stable_file(item_dir / (stem + ".intent.json"), k._MAX_FILE).raw)
        done = strict_json(read_stable_file(item_dir / (stem + ".complete.json"), k._MAX_FILE).raw)
        origin = {name: mapping.get(name) for name in ("sourceScope", "sourceKnowledgeBaseId", "sourceKnowledgeItemId")}
        state = read_stable_file(folder / (k._digest(origin) + ".json"), k._MAX_FILE)
        if (not isinstance(actual, dict) or type(actual.get("schemaVersion")) is not int
                or type(actual.get("index")) is not int or not isinstance(done, dict)
                or type(done.get("schemaVersion")) is not int
                or actual != intent or done != {"schemaVersion": 1, "intentSha256": k._digest(intent),
                                                "mapping": mapping, "stateSha256": state.sha256}):
            k._fail("sync_receipt_invalid")


def _prior_addition_unchanged(lease, s, owner, folder, history, scope, key, item, *, check_target=True, visited=None):
    """Follow the original sync receipt and archived source; do not trust state alone."""
    try:
        visited = set() if visited is None else visited
        if key in visited or len(visited) >= 128:
            return False
        visited.add(key)
        state = strict_json(read_stable_file(folder / (key + ".json"), k._MAX_FILE).raw)
        k._validate_state(state, state["binding"])
        mid = state["migrationId"]
        stem = k._digest(mid)
        operations = folder / "sync_operations"
        plan = strict_json(read_stable_file(operations / (stem + ".plan.json"), k._MAX_FILE).raw)
        receipt = strict_json(read_stable_file(operations / (stem + ".complete.json"), k._MAX_FILE).raw)
        proof = state["binding"]["sourceProofSha256"]
        if (state["phase"] != "published" or state["binding"]["sourceScope"] != scope
                or state["binding"]["targetAgentId"] != lease.agent_id or state["binding"]["sourceKnowledgeItemId"] != item["knowledgeItemId"]
                or plan.get("syncId") != mid or plan.get("baselinePlanSha256") != history["planSha256"]
                or plan.get("sourceProofSha256") != proof or plan.get("sourceScope") != scope
                or plan.get("targetAgentId") != lease.agent_id
                or not isinstance(plan.get("sourceKnowledgeItemIds"), list)
                or state["mapping"] not in receipt["mappings"]
                or k._archive_entries(folder / "archives" / proof) != plan.get("archiveEntries")):
            return False
        prior_mappings, skipped = _receipt_mappings(plan, receipt)
        _validate_partial_terminal(folder, plan, prior_mappings, skipped, receipt)
        archived = k._rows(read_stable_file(folder / "archives" / proof / "private/items.jsonl", k._MAX_FILE).raw,
                           "knowledgeItemId")
        original = next((row for row in archived if row["knowledgeItemId"] == item["knowledgeItemId"]), None)
        if original != item or not isinstance(plan.get("updates"), list):
            return False
        update = next((row for row in plan["updates"] if isinstance(row, dict)
                       and row.get("sourceKnowledgeItemId") == item["knowledgeItemId"]), None)
        if update:
            parent_key = update.get("parentKey")
            if not isinstance(parent_key, str) or not k._SHA256.fullmatch(parent_key):
                return False
            parent_state = strict_json(read_stable_file(folder / (parent_key + ".json"), k._MAX_FILE).raw)
            k._validate_state(parent_state, parent_state["binding"])
            parent_id = parent_state["mapping"]["sourceKnowledgeItemId"]
            source_by_id = {row["knowledgeItemId"]: row for row in archived}
            parent_source = source_by_id.get(parent_id)
            cursor = source_by_id.get(item.get("supersedesKnowledgeItemId"))
            seen = set()
            while cursor and cursor["knowledgeItemId"] != parent_id:
                if cursor["knowledgeItemId"] in seen or len(seen) >= 128:
                    return False
                seen.add(cursor["knowledgeItemId"])
                cursor = source_by_id.get(cursor.get("supersedesKnowledgeItemId"))
            target = next((row for row in k._target_rows(s, owner, s._items_path_for_owner, "knowledgeItemId")
                           if row["knowledgeItemId"] == state["mapping"]["knowledgeItemId"]), None)
            if not cursor or not target or target.get("supersedesKnowledgeItemId") != parent_state["mapping"]["knowledgeItemId"]:
                return False
            if parent_key in history["originKeys"]:
                index = history["originKeys"].index(parent_key)
                if history["mappings"][index] != parent_state["mapping"]:
                    return False
                initial_path = folder / "archives" / history["sourceProofSha256"] / "private/items.jsonl"
                initial = k._rows(read_stable_file(initial_path, k._MAX_FILE).raw, "knowledgeItemId")
                if not parent_source or not any(row == parent_source for row in initial):
                    return False
            elif not parent_source or not _prior_addition_unchanged(lease, s, owner, folder, history, scope,
                    parent_key, parent_source, check_target=False, visited=visited):
                return False
        return not check_target or k._target_matches_baseline(lease, s, owner, folder, key, state)
    except (KeyError, TypeError, ValueError, OSError, MigrationIOError):
        return False


def _apply_revision(lease, s, owner, folder, item, scope, proof, sync_id, parent_key, verify):
    """Apply one preplanned revision; never called a second time for an intent."""
    parent_state = strict_json(read_stable_file(folder / (parent_key + ".json"), k._MAX_FILE).raw)
    if not k._target_matches_baseline(lease, s, owner, folder, parent_key, parent_state):
        k._fail("sync_target_conflict")
    parent_mapping = parent_state["mapping"]
    parent = next((row for row in k._target_rows(s, owner, s._items_path_for_owner, "knowledgeItemId")
                   if row["knowledgeItemId"] == parent_mapping["knowledgeItemId"]), None)
    if parent is None:
        k._fail("sync_target_conflict")
    scoped = s._owner_scoped_knowledge_base_id(owner, parent_mapping["knowledgeBaseId"])
    verify()
    proposal = s.create_refinement_proposal(scoped, source_artifact_ids=parent_mapping["sourceArtifactIds"],
        proposed_by_agent_id=lease.agent_id, title=item["title"], summary=str(item.get("summary") or ""),
        content=item["content"], tags=parent.get("tags") or [],
        supersedes_knowledge_item_id=parent["knowledgeItemId"], expected_content_sha256=parent["contentSha256"],
        revision_reason="Operator-authorized legacy knowledge synchronization")
    verify()
    result = s.review_refinement_proposal(scoped, proposal["proposalId"], status="applied",
        reviewed_by_agent_id=lease.agent_id, resolution_note="Legacy source revision; source proof is archived.",
        _migration_lease=lease, _migration_parent_sha256=k._digest(parent))
    target = result.get("item")
    if (not isinstance(target, dict) or target.get("contentSha256") != item["contentSha256"]
            or target.get("supersedesKnowledgeItemId") != parent["knowledgeItemId"]):
        k._fail("sync_outcome_unknown")
    origin = {"sourceScope": scope, "sourceKnowledgeBaseId": item["knowledgeBaseId"],
              "sourceKnowledgeItemId": item["knowledgeItemId"]}
    key = k._digest(origin)
    state_path = folder / (key + ".json")
    if state_path.exists() or state_path.is_symlink():
        k._fail("sync_outcome_unknown")
    mapping = {**origin, "knowledgeBaseId": parent_mapping["knowledgeBaseId"],
               "knowledgeItemId": target["knowledgeItemId"], "inboxSourceId": parent_mapping["inboxSourceId"],
               "sourceArtifactIds": target["sourceArtifactIds"], "centralSourceIds": target["centralSourceIds"],
               "operation": "operator_authorized_migration"}
    base = next(row for row in s._knowledge_bases_for_owner(owner) if row["knowledgeBaseId"] == mapping["knowledgeBaseId"])
    source = next(row for row in k._target_rows(s, owner, s._owner_source_index_path, "inboxSourceId")
                  if row["inboxSourceId"] == mapping["inboxSourceId"])
    all_items = [row for row in k._target_rows(s, owner, s._items_path_for_owner, "knowledgeItemId")
                 if row.get("knowledgeBaseId") == mapping["knowledgeBaseId"]]
    artifacts = {row["sourceArtifactId"]: row for row in k._target_rows(s, owner, s._source_artifacts_path_for_owner, "sourceArtifactId")}
    verify()
    baseline = k._target_baseline(s, owner, base, source, target, artifacts, mapping, sync_id, base_items=all_items)
    with pinned_target_directory(folder / "target_baselines", create=True):
        k._immutable(folder / "target_baselines" / (key + ".json"), baseline)
    verify()
    k._write_state(state_path, {"schemaVersion": 1, "binding": k._item_binding(item, scope, proof, lease.agent_id),
        "migrationId": sync_id, "phase": "published", "mapping": mapping})
    return mapping


def _archived_items(folder, plan):
    """Verify the originally committed archive, independently of a live source."""
    proof = plan["sourceProofSha256"]
    if not isinstance(proof, str) or not k._SHA256.fullmatch(proof):
        k._fail("sync_operation_conflict")
    archive = folder / "archives" / proof
    entries = k._archive_entries(archive)
    if entries != plan["archiveEntries"]:
        k._fail("sync_operation_conflict")
    hashes = {row["path"]: row["sha256"] for row in entries}
    private = {name.removeprefix("private/"): value for name, value in hashes.items() if name.startswith("private/")}
    manifest = strict_json(read_stable_file(archive / "manifest.json", k._MAX_FILE).raw)
    if (not isinstance(manifest, dict) or set(manifest) != {"schemaVersion", "sourceScope", "readOnly",
            "untrustedContent", "originalReviewReplayed", "privateFiles", "centralRegistrySha256",
            "ownerRefsSha256", "globalRegistryFiltered", "readyForCutover"}
            or type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1
            or manifest["sourceScope"] != plan["sourceScope"] or manifest["privateFiles"] != private
            or manifest["readOnly"] is not True or manifest["untrustedContent"] is not True
            or manifest["originalReviewReplayed"] is not False or manifest["globalRegistryFiltered"] is not True
            or manifest["readyForCutover"] is not False
            or set(hashes) != {"private/" + name for name in private} | {
                "selected-central.json", "selected-owner-refs.json", "manifest.json"}
            or k._digest({"files": private, "central": manifest["centralRegistrySha256"],
                          "ownerRefs": manifest["ownerRefsSha256"]}) != proof):
        k._fail("sync_operation_conflict")
    rows = k._rows(read_stable_file(archive / "private/items.jsonl", k._MAX_FILE).raw, "knowledgeItemId")
    return {row["knowledgeItemId"]: row for row in rows}


def _published_item(lease, s, owner, folder, plan, item):
    origin = {"sourceScope": plan["sourceScope"], "sourceKnowledgeBaseId": item["knowledgeBaseId"],
              "sourceKnowledgeItemId": item["knowledgeItemId"]}
    key = k._digest(origin)
    snapshot = read_stable_file(folder / (key + ".json"), k._MAX_FILE)
    state = strict_json(snapshot.raw)
    k._validate_state(state, k._item_binding(item, plan["sourceScope"], plan["sourceProofSha256"], lease.agent_id))
    if (state["phase"] != "published" or state["migrationId"] != plan["syncId"]
            or not k._target_matches_baseline(lease, s, owner, folder, key, state)):
        k._fail("sync_outcome_unknown")
    return state["mapping"], snapshot.sha256


def _assert_unstarted(s, owner, folder, plan, items, ids, *, check_orphan_bases=True):
    """Fail closed on any durable trace of a supposedly unstarted action."""
    updates = {row["sourceKnowledgeItemId"]: row["parentKey"] for row in plan["updates"]}
    bases = s._knowledge_bases_for_owner(owner)
    sources = k._target_rows(s, owner, s._owner_source_index_path, "inboxSourceId")
    if any(row.get("sourceRef") is not None and not isinstance(row.get("sourceRef"), dict) for row in sources):
        k._fail("sync_outcome_unknown")
    targets = k._target_rows(s, owner, s._items_path_for_owner, "knowledgeItemId")
    proposals = k._target_rows(s, owner, s._proposals_path_for_owner, "proposalId")
    audit = k._target_rows(s, owner, s._audit_path_for_owner, "auditId")
    if any(row.get("payload") is not None and not isinstance(row.get("payload"), dict) for row in audit):
        k._fail("sync_outcome_unknown")
    base_ids = {row.get("knowledgeBaseId") for row in bases}
    proposal_ids = {row["proposalId"] for row in proposals}
    # A deleted native object can otherwise hide an earlier partial attempt.
    # Existing, unrelated orphan creation records also block conservatively.
    if check_orphan_bases and any(row.get("action") == "knowledge_base.created"
           and (row.get("payload") or {}).get("knowledgeBaseId") not in base_ids for row in audit):
        k._fail("sync_outcome_unknown")
    item_dir = folder / "sync_items" / k._digest(plan["syncId"])
    for iid in ids:
        item = items.get(iid)
        if not item:
            k._fail("sync_outcome_unknown")
        origin = {"sourceScope": plan["sourceScope"], "sourceKnowledgeBaseId": item["knowledgeBaseId"],
                  "sourceKnowledgeItemId": iid}
        key = k._digest(origin)
        paths = (folder / (key + ".json"), folder / "target_baselines" / (key + ".json"),
                 item_dir / (k._digest(iid) + ".intent.json"),
                 item_dir / (k._digest(iid) + ".complete.json"))
        for path in (*paths, *(path.with_name(path.name + ".lock") for path in paths)):
            if path.exists() or path.is_symlink():
                k._fail("sync_outcome_unknown")
        if (any(row.get("description") == "operator-authorized-migration:" + key for row in bases)
                or any((row.get("sourceRef") or {}).get("migrationOriginKey") == key for row in sources)):
            k._fail("sync_outcome_unknown")
        if iid in updates:
            parent = strict_json(read_stable_file(folder / (updates[iid] + ".json"), k._MAX_FILE).raw)
            parent_id = parent.get("mapping", {}).get("knowledgeItemId")
            parent_base = parent.get("mapping", {}).get("knowledgeBaseId")
            if (not parent_id or any(row.get("supersedesKnowledgeItemId") == parent_id for row in targets)
                    or any(row.get("supersedesKnowledgeItemId") == parent_id for row in proposals)
                    or any(row.get("action") == "knowledge.proposal.created"
                           and (row.get("payload") or {}).get("knowledgeBaseId") == parent_base
                           and (row.get("payload") or {}).get("proposalId") not in proposal_ids for row in audit)):
                k._fail("sync_outcome_unknown")
    # Do not persist the contents. The digest binds the one locked observation
    # used for every skipped-item certificate to the terminal decision.
    return k._digest({"bases": bases, "sources": sources, "targets": targets,
                      "proposals": proposals, "audit": audit})


def _execute_plan(lease, s, owner, folder, plan, items, *, source_unchanged, verify, initialize=False):
    """Resume only unstarted operations, confirmed by per-item durable intents."""
    mappings = []
    updates = {row["sourceKnowledgeItemId"]: row["parentKey"] for row in plan["updates"]}
    item_dir = folder / "sync_items" / k._digest(plan["syncId"])
    with pinned_target_directory(item_dir, create=True):
        progress_path = item_dir / "progress.json"
        def persist_progress(index, phase):
            value = {"schemaVersion": 1, "planSha256": k._digest(plan), "nextIndex": index, "phase": phase}
            verify()
            k._write_state(progress_path, value)
            if strict_json(read_stable_file(progress_path, k._MAX_FILE).raw) != value:
                k._fail("sync_outcome_unknown")
            verify()
            return value
        if initialize:
            if progress_path.exists() or progress_path.is_symlink():
                k._fail("sync_operation_conflict")
            progress = persist_progress(0, "ready")
        else:
            if progress_path.is_symlink():
                k._fail("sync_outcome_unknown")
            if not progress_path.exists():
                tree = fingerprint_tree(item_dir, max_file_bytes=k._MAX_FILE,
                                        max_files=k._MAX_FILES, max_total_bytes=k._MAX_BYTES)
                if tree or len(tree.directories) != 1:
                    k._fail("sync_outcome_unknown")
                _assert_unstarted(s, owner, folder, plan, items, plan["sourceKnowledgeItemIds"])
                progress = persist_progress(0, "ready")
            else:
                progress = strict_json(read_stable_file(progress_path, k._MAX_FILE).raw)
        if (not isinstance(progress, dict) or set(progress) != {"schemaVersion", "planSha256", "nextIndex", "phase"}
                or type(progress["schemaVersion"]) is not int or progress["schemaVersion"] != 1
                or progress["planSha256"] != k._digest(plan) or type(progress["nextIndex"]) is not int
                or not 0 <= progress["nextIndex"] <= len(plan["sourceKnowledgeItemIds"])
                or progress["phase"] not in {"ready", "started"}
                or progress["phase"] == "started" and progress["nextIndex"] == len(plan["sourceKnowledgeItemIds"])):
            k._fail("sync_outcome_unknown")
        terminal_path = item_dir / "terminal.json"
        terminal = None
        if terminal_path.exists() or terminal_path.is_symlink():
            terminal = strict_json(read_stable_file(terminal_path, k._MAX_FILE).raw)
            skipped = plan["sourceKnowledgeItemIds"][progress["nextIndex"]:]
            if (not isinstance(terminal, dict) or type(terminal.get("schemaVersion")) is not int
                    or type(terminal.get("completedCount")) is not int
                    or progress["phase"] != "ready" or not skipped):
                k._fail("sync_outcome_unknown")
            _validate_skip_terminal(folder, plan, terminal, skipped, progress["nextIndex"])
            # The certificate proves the original locked observation. Other
            # knowledge may change before the final receipt; recheck only
            # traces that could belong to these skipped actions.
            _assert_unstarted(s, owner, folder, plan, items, skipped, check_orphan_bases=False)
        for index, iid in enumerate(plan["sourceKnowledgeItemIds"]):
            if terminal is not None and index == progress["nextIndex"]:
                return mappings, terminal["skippedSourceKnowledgeItemIds"]
            item = items.get(iid)
            if not item:
                k._fail("sync_outcome_unknown")
            stem = k._digest(iid)
            intent_path, done_path = item_dir / (stem + ".intent.json"), item_dir / (stem + ".complete.json")
            intent = {"schemaVersion": 1, "syncId": plan["syncId"], "planSha256": k._digest(plan),
                      "sourceKnowledgeItemId": iid, "index": index, "parentKey": updates.get(iid)}
            intent_exists = intent_path.exists() or intent_path.is_symlink()
            done_exists = done_path.exists() or done_path.is_symlink()
            if index < progress["nextIndex"] and (not intent_exists or not done_exists):
                k._fail("sync_outcome_unknown")
            if index > progress["nextIndex"]:
                k._fail("sync_outcome_unknown")
            if index == progress["nextIndex"]:
                if progress["phase"] == "ready" and (intent_exists or done_exists):
                    k._fail("sync_outcome_unknown")
                if progress["phase"] == "started" and not intent_exists:
                    k._fail("sync_outcome_unknown")
            if not intent_exists:
                origin = {"sourceScope": plan["sourceScope"], "sourceKnowledgeBaseId": item["knowledgeBaseId"],
                          "sourceKnowledgeItemId": iid}
                existing = folder / (k._digest(origin) + ".json")
                if done_exists or existing.exists() or existing.is_symlink():
                    k._fail("sync_outcome_unknown")
                skipped = plan["sourceKnowledgeItemIds"][index:]
                skip_paths = [item_dir / (k._digest(value) + ".not-started.json") for value in skipped]
                skip_in_progress = any(path.exists() or path.is_symlink()
                    for path in (*skip_paths, *(path.with_name(path.name + ".lock") for path in skip_paths)))
                if not source_unchanged or skip_in_progress:
                    prior_evidence = None
                    missing = False
                    for offset, path in enumerate(skip_paths):
                        if not path.exists() and not path.is_symlink():
                            missing = True
                            continue
                        # A persisted prefix certifies one observation of the
                        # whole skipped suffix; never accept holes or a mixed
                        # observation after an interruption.
                        if missing:
                            k._fail("sync_outcome_unknown")
                        actual = strict_json(read_stable_file(path, k._MAX_FILE).raw)
                        value = skipped[offset]
                        source = items[value]
                        origin = {"sourceScope": plan["sourceScope"], "sourceKnowledgeBaseId": source["knowledgeBaseId"],
                                  "sourceKnowledgeItemId": value}
                        expected = {"schemaVersion": 1, "syncId": plan["syncId"], "planSha256": k._digest(plan),
                            "sourceKnowledgeItemId": value, "index": index + offset, "originKey": k._digest(origin),
                            "targetEvidenceSha256": actual.get("targetEvidenceSha256") if isinstance(actual, dict) else None}
                        digest = expected["targetEvidenceSha256"]
                        if (not isinstance(actual, dict) or type(actual.get("schemaVersion")) is not int
                                or type(actual.get("index")) is not int or actual != expected
                                or not isinstance(digest, str) or not k._SHA256.fullmatch(digest)
                                or prior_evidence is not None and prior_evidence != digest):
                            k._fail("sync_outcome_unknown")
                        prior_evidence = digest
                    observed = _assert_unstarted(s, owner, folder, plan, items, skipped,
                                                 check_orphan_bases=prior_evidence is None)
                    evidence = prior_evidence or observed
                    proofs = []
                    for offset, value in enumerate(skipped):
                        source = items[value]
                        origin = {"sourceScope": plan["sourceScope"], "sourceKnowledgeBaseId": source["knowledgeBaseId"],
                                  "sourceKnowledgeItemId": value}
                        certificate = {"schemaVersion": 1, "syncId": plan["syncId"], "planSha256": k._digest(plan),
                            "sourceKnowledgeItemId": value, "index": index + offset, "originKey": k._digest(origin),
                            "targetEvidenceSha256": evidence}
                        verify()
                        k._immutable(skip_paths[offset], certificate)
                        proofs.append({"sourceKnowledgeItemId": value, "proofSha256": k._digest(certificate)})
                    terminal = {"schemaVersion": 2, "planSha256": k._digest(plan), "completedCount": index,
                                "skippedSourceKnowledgeItemIds": skipped, "targetEvidenceSha256": evidence,
                                "proofs": proofs}
                    verify()
                    k._immutable(terminal_path, terminal)
                    verify()
                    return mappings, skipped
                if iid in updates:
                    parent = strict_json(read_stable_file(folder / (updates[iid] + ".json"), k._MAX_FILE).raw)
                    if not k._target_matches_baseline(lease, s, owner, folder, updates[iid], parent):
                        k._fail("sync_target_conflict")
                progress = persist_progress(index, "started")
                verify()
                k._immutable(intent_path, intent)
                verify()
                if iid in updates:
                    _apply_revision(lease, s, owner, folder, item, plan["sourceScope"],
                                    plan["sourceProofSha256"], plan["syncId"], updates[iid], verify)
                else:
                    _, reused = k._import_one(lease, s, owner, item, plan["sourceScope"],
                                              plan["sourceProofSha256"], folder, verify, plan["syncId"])
                    if reused:
                        k._fail("sync_outcome_unknown")
            else:
                actual = strict_json(read_stable_file(intent_path, k._MAX_FILE).raw)
                if (not isinstance(actual, dict) or type(actual.get("schemaVersion")) is not int
                        or type(actual.get("index")) is not int or actual != intent):
                    k._fail("sync_operation_conflict")
            try:
                mapping, state_hash = _published_item(lease, s, owner, folder, plan, item)
            except (OSError, ValueError, KeyError, TypeError, MigrationIOError):
                k._fail("sync_outcome_unknown")
            done = {"schemaVersion": 1, "intentSha256": k._digest(intent), "mapping": mapping,
                    "stateSha256": state_hash}
            verify()
            k._immutable(done_path, done)
            mappings.append(mapping)
            if index == progress["nextIndex"]:
                progress = persist_progress(index + 1, "ready")
    return mappings, []


def sync_private_knowledge(lease, resolved, *, central, owner_refs, baseline_migration_id,
                           sync_id, authority_verify=None):
    """Import new roots and revise untouched mapped targets; never replay a write.

    A same-ID retry confirms published items and resumes only items proven not
    started under the same source proof. If the source changed, proven-unstarted
    items are terminally skipped so a new operation can plan against fresh proof.
    Unknown started items are never replayed.
    Changed/deleted roots and targets without an untouched baseline are conflicts.
    Callers must preserve the ID and show unresolved/pending counts to users.
    """
    k._lease(lease)
    if (not isinstance(sync_id, str) or not k._TOKEN.fullmatch(sync_id)
            or not isinstance(baseline_migration_id, str) or not k._TOKEN.fullmatch(baseline_migration_id)
            or sync_id == baseline_migration_id
            or authority_verify is not None and not callable(authority_verify)):
        k._fail("sync_request_invalid")
    if authority_verify:
        authority_verify()
    scope, source_root, files, snapshots, source_verify = k._source(resolved, central, owner_refs)
    if Path(lease.root).is_relative_to(source_root) or source_root.is_relative_to(Path(lease.root)):
        k._fail("source_target_overlap")
    from core.web.services import team_knowledge_service as s, agent_directory_service as directory
    from core.web.services.external_management.state_snapshot import ExistingStateSnapshot
    from core.web.services.personal_assistant_project.windows_read import _locked_source
    from core.infrastructure import developer_sandbox
    from . import native
    with ExitStack() as stack:
        for snapshot in snapshots:
            stack.enter_context(_locked_source(Path(snapshot.path.anchor), snapshot.path, directory=False))
        stack.enter_context(_locked_source(Path(directory.CONFIG_PATH).anchor, Path(directory.CONFIG_PATH), directory=False))
        active_path = developer_sandbox._active_state_path(lease.root)
        if active_path.exists():
            stack.enter_context(_locked_source(Path(active_path.anchor), active_path, directory=False))
        workspace = ExistingStateSnapshot(lease.root, directory, pin_workspace=True)
        def verify():
            if authority_verify:
                authority_verify()
            source_verify()
            k._lease(lease)
            workspace.verify_workspace()
            k._promotion_allowed(s)
            k._target(lease, workspace, s)
        verify()
        proof = k._digest({"files": {n: f.sha256 for n, f in files.items()},
                           "central": central.sha256, "ownerRefs": owner_refs.sha256})
        owner = k._target(lease, workspace, s)
        folder = Path(lease.root) / "knowledge_migrations"
        with native._LOCK, s._LOCK, pinned_target_directory(folder), migration_target_lock(folder):
            verify()
            k._pin_target(stack, s, owner)
            history = k.verify_knowledge_completion(Path(lease.root), baseline_migration_id)
            if (history["sourceScope"] != scope or history["targetAgentId"] != lease.agent_id
                    or history["targetWorkspaceSha256"] != k._digest(str(workspace.path()).casefold())):
                k._fail("sync_baseline_invalid")
            sync_dir = folder / "sync_operations"
            stem = k._digest(sync_id)
            intent_path, receipt_path = sync_dir / (stem + ".plan.json"), sync_dir / (stem + ".complete.json")
            if intent_path.exists() or intent_path.is_symlink():
                plan = strict_json(read_stable_file(intent_path, k._MAX_FILE).raw)
                fields = {"schemaVersion", "syncId", "baselineMigrationId", "baselinePlanSha256",
                          "sourceProofSha256", "sourceScope", "targetAgentId", "sourceKnowledgeItemIds", "updates",
                          "conflictKeys", "pendingCount", "excludedCount", "archiveEntries"}
                if (not isinstance(plan, dict) or set(plan) != fields or type(plan["schemaVersion"]) is not int
                        or plan["schemaVersion"] not in {1, 2, 3} or plan["syncId"] != sync_id
                        or plan["baselineMigrationId"] != baseline_migration_id
                        or plan["baselinePlanSha256"] != history["planSha256"]
                        or plan["sourceScope"] != scope
                        or plan["targetAgentId"] != lease.agent_id
                        or not isinstance(plan["sourceKnowledgeItemIds"], list)
                        or any(not isinstance(v, str) or not k._TOKEN.fullmatch(v) for v in plan["sourceKnowledgeItemIds"])
                        or plan["sourceKnowledgeItemIds"] != sorted(set(plan["sourceKnowledgeItemIds"]))
                        or not isinstance(plan["updates"], list)
                        or any(not isinstance(v, dict) or set(v) != {"sourceKnowledgeItemId", "parentKey"}
                               or v["sourceKnowledgeItemId"] not in plan["sourceKnowledgeItemIds"]
                               or not isinstance(v["parentKey"], str) or not k._SHA256.fullmatch(v["parentKey"])
                               for v in plan["updates"])
                        or len({v["sourceKnowledgeItemId"] for v in plan["updates"]}) != len(plan["updates"])
                        or not isinstance(plan["conflictKeys"], list)
                        or any(not isinstance(v, str) or not k._SHA256.fullmatch(v) for v in plan["conflictKeys"])
                        or plan["conflictKeys"] != sorted(set(plan["conflictKeys"]))
                        or type(plan["pendingCount"]) is not int or plan["pendingCount"] < 0
                        or type(plan["excludedCount"]) is not int or plan["excludedCount"] < 0):
                    k._fail("sync_operation_conflict")
                archived = _archived_items(folder, plan)
                if not receipt_path.exists() or receipt_path.is_symlink():
                    # Confirmation may publish only after every original action
                    # has a matching state and untouched target baseline; no
                    # original native write is repeated here.
                    if plan["schemaVersion"] == 3:
                        # If every original action already has an immutable
                        # published state and target baseline, confirmation
                        # does not depend on the mutable progress checkpoint.
                        try:
                            recovered = [_published_item(lease, s, owner, folder, plan, archived[iid])[0]
                                         for iid in plan["sourceKnowledgeItemIds"]]
                            skipped = []
                        except (OSError, ValueError, KeyError, TypeError, MigrationIOError):
                            recovered, skipped = _execute_plan(lease, s, owner, folder, plan, archived,
                                source_unchanged=plan["sourceProofSha256"] == proof, verify=verify)
                    else:
                        recovered = []
                        skipped = []
                        for iid in plan["sourceKnowledgeItemIds"]:
                            source = archived.get(iid)
                            if not source:
                                k._fail("sync_outcome_unknown")
                            try:
                                mapping, _ = _published_item(lease, s, owner, folder, plan, source)
                                recovered.append(mapping)
                            except (OSError, ValueError, KeyError, TypeError, MigrationIOError):
                                k._fail("sync_outcome_unknown")
                    verify()
                    receipt = {"planSha256": k._digest(plan), "mappings": recovered}
                    if skipped:
                        receipt["skippedSourceKnowledgeItemIds"] = skipped
                        terminal_path = folder / "sync_items" / k._digest(sync_id) / "terminal.json"
                        terminal = strict_json(read_stable_file(terminal_path, k._MAX_FILE).raw)
                        if terminal.get("schemaVersion") == 2:
                            receipt["terminalSha256"] = k._digest(terminal)
                    k._immutable(receipt_path, receipt)
                receipt = strict_json(read_stable_file(receipt_path, k._MAX_FILE).raw)
                mappings, skipped = _receipt_mappings(plan, receipt)
                _validate_partial_terminal(folder, plan, mappings, skipped, receipt)
                for expected, mapping in zip(plan["sourceKnowledgeItemIds"], mappings):
                    if not isinstance(mapping, dict) or mapping.get("sourceKnowledgeItemId") != expected:
                        k._fail("sync_receipt_invalid")
                    origin = {name: mapping.get(name) for name in ("sourceScope", "sourceKnowledgeBaseId", "sourceKnowledgeItemId")}
                    state = strict_json(read_stable_file(folder / (k._digest(origin) + ".json"), k._MAX_FILE).raw)
                    k._validate_state(state, state.get("binding"))
                    if (state.get("phase") != "published" or state.get("migrationId") != sync_id
                            or state.get("mapping") != mapping or mapping.get("sourceScope") != scope
                            or state["binding"].get("targetAgentId") != lease.agent_id
                            or state["binding"].get("sourceProofSha256") != plan["sourceProofSha256"]):
                        k._fail("sync_receipt_invalid")
                verify()
                return {"syncId": sync_id, "mappings": mappings, "reused": True,
                        "conflictCount": len(plan["conflictKeys"]), "pendingCount": plan["pendingCount"] + len(skipped),
                        "skippedCount": len(skipped),
                        "excludedCount": plan["excludedCount"], "sourceQuiesced": False, "readyForCutover": False}
            planned, excluded, central_rows, refs = k._plan(scope, files, central, owner_refs)
            old_path = folder / "archives" / history["sourceProofSha256"] / "private/items.jsonl"
            old_items = k._rows(read_stable_file(old_path, k._MAX_FILE).raw, "knowledgeItemId")
            old_by_id = {row["knowledgeItemId"]: row for row in old_items}
            old_roots = {row.get("rootKnowledgeItemId") or row["knowledgeItemId"] for row in old_items}
            current = {row["knowledgeItemId"]: row for row in planned}
            by_id = {row["knowledgeItemId"]: row for row in k._rows(files["items.jsonl"].raw, "knowledgeItemId")}
            def ancestors(item):
                rows, seen = [], set()
                while item:
                    iid = item["knowledgeItemId"]
                    if iid in seen:
                        k._fail("revision_chain_unsupported")
                    seen.add(iid)
                    rows.append(item)
                    item = by_id.get(item.get("supersedesKnowledgeItemId"))
                return rows
            conflicts = []
            updates = {}
            resolved_roots = set()
            for key, mapping in zip(history["originKeys"], history["mappings"]):
                state_path = folder / (key + ".json")
                state = strict_json(read_stable_file(state_path, k._MAX_FILE).raw)
                source = current.get(mapping["sourceKnowledgeItemId"])
                if source is None:
                    descendant = next((item for item in planned if any(
                        row["knowledgeItemId"] == mapping["sourceKnowledgeItemId"] for row in ancestors(item))), None)
                    if (descendant and by_id.get(mapping["sourceKnowledgeItemId"]) == old_by_id.get(mapping["sourceKnowledgeItemId"])
                            and k._target_matches_baseline(lease, s, owner, folder, key, state)):
                        updates[descendant["knowledgeItemId"]] = key
                        resolved_roots.add(descendant.get("rootKnowledgeItemId") or descendant["knowledgeItemId"])
                        continue
                if (source is None or source != old_by_id.get(mapping["sourceKnowledgeItemId"])
                        or not k._target_matches_baseline(lease, s, owner, folder, key, state)):
                    conflicts.append(key)
                else:
                    resolved_roots.add(source.get("rootKnowledgeItemId") or source["knowledgeItemId"])
            candidates = []
            for item in planned:
                root_id = item.get("rootKnowledgeItemId") or item["knowledgeItemId"]
                if root_id in old_roots:
                    if root_id not in resolved_roots:
                        for version in ancestors(item):
                            origin = {"sourceScope": scope, "sourceKnowledgeBaseId": version["knowledgeBaseId"],
                                      "sourceKnowledgeItemId": version["knowledgeItemId"]}
                            key = k._digest(origin)
                            if _prior_addition_unchanged(lease, s, owner, folder, history, scope, key, version):
                                resolved_roots.add(root_id)
                                if version is not item:
                                    updates[item["knowledgeItemId"]] = key
                                for old_key, mapping in zip(history["originKeys"], history["mappings"]):
                                    old = old_by_id.get(mapping["sourceKnowledgeItemId"], {})
                                    if (old.get("rootKnowledgeItemId") or old.get("knowledgeItemId")) == root_id and old_key in conflicts:
                                        conflicts.remove(old_key)
                                break
                    if root_id not in resolved_roots:
                        conflicts.append(k._digest({"sourceScope": scope, "sourceKnowledgeBaseId": item["knowledgeBaseId"],
                                                    "sourceKnowledgeItemId": item["knowledgeItemId"]}))
                    continue
                cursor, seen, already = item, set(), False
                while cursor:
                    iid = cursor["knowledgeItemId"]
                    if iid in seen:
                        k._fail("revision_chain_unsupported")
                    seen.add(iid)
                    origin = {"sourceScope": scope, "sourceKnowledgeBaseId": cursor["knowledgeBaseId"],
                              "sourceKnowledgeItemId": iid}
                    prior = folder / (k._digest(origin) + ".json")
                    if prior.exists() or prior.is_symlink():
                        already = True
                        break
                    cursor = by_id.get(cursor.get("supersedesKnowledgeItemId"))
                if already:
                    key = k._digest(origin)
                    if cursor is not item and _prior_addition_unchanged(lease, s, owner, folder, history, scope, key, cursor):
                        updates[item["knowledgeItemId"]] = key
                        resolved_roots.add(root_id)
                    elif cursor is not item or not _prior_addition_unchanged(lease, s, owner, folder, history, scope, key, item):
                        conflicts.append(key)
                    else:
                        resolved_roots.add(root_id)
                else:
                    candidates.append(item)
            candidates.sort(key=lambda row: row["knowledgeItemId"])
            # Each ID is a one-shot immutable intent. A missing receipt after
            # its creation remains unknown, even if no write can be observed.
            with pinned_target_directory(sync_dir, create=True):
                if receipt_path.exists() or receipt_path.is_symlink():
                    k._fail("sync_operation_conflict")
                # A different ID cannot step around an unresolved intent,
                # even when the partial native outcome is not observable.
                for snapshot in fingerprint_tree(sync_dir, max_file_bytes=k._MAX_FILE,
                                                 max_files=k._MAX_FILES, max_total_bytes=k._MAX_BYTES):
                    if snapshot.path.parent != sync_dir:
                        k._fail("sync_receipt_invalid")
                    if snapshot.path.name.endswith((".plan.json.lock", ".complete.json.lock")):
                        corresponding = snapshot.path.with_name(snapshot.path.name.removesuffix(".lock"))
                        if not corresponding.exists() or corresponding.is_symlink():
                            k._fail("sync_prior_outcome_unknown")
                        continue
                    if snapshot.path.name.endswith(".complete.json"):
                        prior_plan = snapshot.path.with_name(snapshot.path.name.removesuffix(".complete.json") + ".plan.json")
                        if not prior_plan.exists() or prior_plan.is_symlink():
                            k._fail("sync_receipt_invalid")
                        continue
                    if not snapshot.path.name.endswith(".plan.json"):
                        k._fail("sync_receipt_invalid")
                    prior_receipt = snapshot.path.with_name(snapshot.path.name.removesuffix(".plan.json") + ".complete.json")
                    if not prior_receipt.exists() or prior_receipt.is_symlink():
                        k._fail("sync_prior_outcome_unknown")
                    prior = strict_json(snapshot.raw)
                    done = strict_json(read_stable_file(prior_receipt, k._MAX_FILE).raw)
                    if not isinstance(prior, dict):
                        k._fail("sync_receipt_invalid")
                    prior_mappings, skipped = _receipt_mappings(prior, done)
                    _validate_partial_terminal(folder, prior, prior_mappings, skipped, done)
                    if (prior.get("baselinePlanSha256") == history["planSha256"]
                            and prior.get("sourceScope") == scope and prior.get("targetAgentId") == lease.agent_id):
                        for mapping in done["mappings"]:
                            origin = {name: mapping.get(name) for name in ("sourceScope", "sourceKnowledgeBaseId", "sourceKnowledgeItemId")}
                            key = k._digest(origin)
                            item = current.get(mapping.get("sourceKnowledgeItemId"))
                            if key in updates.values():
                                continue
                            version = by_id.get(mapping.get("sourceKnowledgeItemId"))
                            if version and (version.get("rootKnowledgeItemId") or version["knowledgeItemId"]) in resolved_roots:
                                continue
                            if not item or not _prior_addition_unchanged(lease, s, owner, folder, history, scope, key, item):
                                conflicts.append(key)
                archive = folder / "archives" / proof
                k._archive(archive, files, central_rows, refs, scope, central, owner_refs)
                archive_entries = k._archive_entries(archive)
                if {row["path"] for row in archive_entries} != {
                        *("private/" + name for name in files), "selected-central.json", "selected-owner-refs.json", "manifest.json"}:
                    k._fail("archive_conflict")
                plan = {"schemaVersion": 3, "syncId": sync_id, "baselineMigrationId": baseline_migration_id,
                        "baselinePlanSha256": history["planSha256"], "sourceProofSha256": proof,
                        "sourceScope": scope, "targetAgentId": lease.agent_id,
                        "sourceKnowledgeItemIds": sorted([item["knowledgeItemId"] for item in candidates] + list(updates)),
                        "updates": [{"sourceKnowledgeItemId": iid, "parentKey": updates[iid]} for iid in sorted(updates)],
                        "conflictKeys": sorted(set(conflicts)), "pendingCount": 0,
                        "excludedCount": len(excluded), "archiveEntries": archive_entries}
                verify()
                k._immutable(intent_path, plan)
                verify()
                mappings, skipped = _execute_plan(lease, s, owner, folder, plan, current, source_unchanged=True, verify=verify,
                                         initialize=True)
                if skipped:
                    k._fail("sync_outcome_unknown")
                verify()
                k._immutable(receipt_path, {"planSha256": k._digest(plan), "mappings": mappings})
                return {"syncId": sync_id, "mappings": mappings, "reused": False,
                        "conflictCount": len(plan["conflictKeys"]), "pendingCount": plan["pendingCount"],
                        "skippedCount": 0,
                        "excludedCount": plan["excludedCount"], "sourceQuiesced": False, "readyForCutover": False}
