"""Read-only recovery disposition evidence; never an authority or execution owner.

The trusted caller must validate the supplied source PA against its registry.
Only ``report`` is public. Snapshots/proofs stay private and must not be copied
into the assistant's runtime, prompt, approval queue, or executable plugin data.
No claim about in-memory grants or source quiescence follows from disk evidence.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .migration_io import (FileSnapshot, MigrationIOError, check_path, path_identity,
    read_stable_file, strict_json, validate_path, verify_snapshot)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
_CAPS = {"max_files": 10000, "max_file_bytes": 4 * 1024 * 1024,
         "max_total_bytes": 32 * 1024 * 1024, "max_grant_records": 10000}
_STATUSES = ("applied", "pending_review", "rejected")
_DISPOSITION = {"disposition": "retained_in_source", "requires_native_reauthorization": True}
# Native Run.model_dump() is extended by the generic workflow store. These
# fields remain private and are not interpreted as migration authority.
_RUN_STRINGS = frozenset({"_createFingerprint", "_recoveryChildMode", "_recoveryQueuedAt", "_recoveryScene",
    "_recoveryDeploymentRef", "_recoveryReplayAfter", "_retryDisposition", "_sourceReason"})
_RUN_BOOLS = frozenset({"_repeat", "_sourceRetryExhausted", "_sourceEligible", "_sourceReplayPending"})
_RUN_INTS = frozenset({"_taskRosterVersion", "_recoveryVerification"})
_GRANT_STRINGS = frozenset({"eventId", "requestId", "kind", "status", "grantScope", "sourceSessionId",
    "sourceTurnId", "targetAgentId", "targetAgentCode", "targetAgentName", "proposedByAgentId",
    "proposedByAgentCode", "proposedByAgentName", "reason", "riskLevel", "approvalReason", "createdAt",
    "resolvedAt", "resolvedBy", "resolutionNote", "appliedToolPolicyId"})
_GRANT_DICTS = {"policyDelta": {"grantTools", "revokeTools", "blockTools", "unblockTools"},
    "temporaryGrant": {"scope", "sessionId", "turnId", "grantTools", "appliedAt"},
    "after": {"policyId", "allowedTools", "blockedTools", "writeScopes"},
    "authority": {"actorKind", "role", "canApplyLowRisk", "reason"}}


@dataclass
class RecoveryBindingInventory:
    report: dict
    snapshots: tuple[FileSnapshot, ...] = field(repr=False)
    directoryproofs: tuple[tuple[Path, tuple], ...] = field(repr=False)
    _missingproofs: tuple[Path, ...] = field(default=(), repr=False)


def _require(condition, code="recovery_source_schema_invalid"):
    if not condition:
        raise MigrationIOError(code)


def _token(value, *, limit=160, empty=False):
    _require(type(value) is str and ((empty and value == "") or
        (len(value) <= limit and _TOKEN.fullmatch(value) is not None)), "recovery_identity_invalid")
    return value


def _closed(value, keys):
    _require(type(value) is dict and not (value.keys() - keys))
    return value


def _native(model, value):
    try:
        return model.model_validate(value, strict=True).model_dump()
    except (ValueError, TypeError, RecursionError):
        raise MigrationIOError("recovery_source_schema_invalid") from None


def _local_authority(value):
    required = {"authorizationId", "operatorId", "runId", "issuedAt", "expiresAt", "revoked",
        "allowedFiles", "teamId", "principals", "requestDigest"}
    _closed(value, required | {"roleBindingSource"})
    _require(required.issubset(value))
    for key in required - {"revoked", "allowedFiles", "principals"}:
        _require(type(value[key]) is str and bool(value[key]))
    _require(type(value["revoked"]) is bool)
    _require(type(value["allowedFiles"]) is list and 1 <= len(value["allowedFiles"]) <= 8
        and all(type(v) is str for v in value["allowedFiles"]))
    _require(re.fullmatch(r"[0-9a-f]{64}", value["requestDigest"]) is not None)
    if "roleBindingSource" in value:
        _require(value["roleBindingSource"] == "recovery_binding_v1")
    principals = _closed(value["principals"], {"observer", "executor", "reviewer"})
    _require(set(principals) == {"observer", "executor", "reviewer"})
    for item in principals.values():
        _closed(item, {"agentId", "fingerprint"})
        _token(item.get("agentId"), limit=128)
        _require(type(item.get("fingerprint")) is str and re.fullmatch(r"[0-9a-f]{64}", item["fingerprint"]) is not None)
    for key in ("issuedAt", "expiresAt"):
        try:
            _require(datetime.fromisoformat(value[key]).tzinfo is not None)
        except (ValueError, TypeError):
            raise MigrationIOError("recovery_source_schema_invalid") from None


def _run_extensions(value, models):
    for key in value.keys() - models.Run.model_fields.keys():
        item = value[key]
        if key in _RUN_STRINGS:
            _require(type(item) is str)
        elif key in _RUN_BOOLS:
            _require(type(item) is bool)
        elif key in _RUN_INTS:
            _require(type(item) is int and item >= 0)
        elif key == "_recoveryTemplate":
            _native(models.Flow, item)
        elif key == "_recoveryHistory":
            _require(type(item) is list and len(item) <= 60)
            for state in item:
                _native(models.RecoveryState, state)
        elif key == "_recoveryParent":
            _closed(item, {"runId", "issueId", "mode"})
            _require(all(type(v) is str for v in item.values()))
        elif key == "_sourceIdentity":
            _closed(item, {"kind", "sessionId", "turnId", "agentId", "researchSource"})
            _require(item.get("kind") in {"session", "research"})
            if item.get("kind") == "research":
                _native(models.ResearchSource, item.get("researchSource"))
            else:
                _require(all(type(v) is str for v in item.values()))
        elif key == "_codeRepairRequest":
            _native(models.LocalIntegrationRequest, item)
        elif key == "_codeRepairAuthorization":
            _local_authority(item)
        elif key == "_codeRepairSource":
            _closed(item, {"teamId", "runId", "flowId", "bindingId", "issueId", "repairRunId", "sourceAttemptKey"})
            _require(all(type(v) is str for v in item.values()))
        else:
            raise MigrationIOError("recovery_source_unknown_field")


def _binding_row(flow, *, team_id, kind, source_agent_id, run=None):
    policy = flow.get("failureRecovery")
    if policy is None:
        return None
    _token(flow["id"], limit=80)
    _require(type(flow["revision"]) is int and flow["revision"] >= 1)
    for key in ("assistantAgentId", "directorAgentId", "developerAgentId", "reviewerAgentId"):
        _token(policy[key], limit=128, empty=key in {"assistantAgentId", "developerAgentId"})
    references = {policy[key] for key in ("assistantAgentId", "directorAgentId", "developerAgentId", "reviewerAgentId")}
    references.update(policy.get("agentPolicyFingerprints", {}))
    references.update(step.get("owner") for step in flow.get("steps", []) if isinstance(step, dict))
    if source_agent_id in references:
        relationship = "references_source_assistant"
    elif not policy.get("assistantAgentId"):
        # Historical unbound policies can still execute through their frozen
        # compatibility path. Their assistant identity cannot be inferred.
        relationship = "legacy_unresolved"
    else:
        return None
    _token(policy["repairFlowId"], limit=80)
    _token(policy["bindingId"], limit=80, empty=True)
    if policy["expiresAt"]:
        try:
            expiry = datetime.fromisoformat(policy["expiresAt"])
            _require(expiry.tzinfo is not None)
        except (ValueError, TypeError):
            raise MigrationIOError("recovery_expiry_invalid") from None
    row = {"type": kind, "teamId": team_id, "flowId": flow["id"], "flowRevision": flow["revision"],
        "status": "bound" if policy["bindingId"] else "legacy", "bindingId": policy["bindingId"],
        "expiresAt": policy["expiresAt"], "sourceRelationship": relationship, "proofStatus": "unresolved", **_DISPOSITION}
    if run is not None:
        row.update(runId=run["id"], runRevision=run["revision"], runStatus=run["status"])
    return row


def _grant_record(value, agent_id):
    _closed(value, _GRANT_STRINGS | _GRANT_DICTS.keys() | {"riskTags", "requiresApproval"})
    _require(all(type(value[key]) is str for key in value.keys() & _GRANT_STRINGS))
    _require(value.get("kind") == "tool_governance_request" and value.get("targetAgentId") == agent_id)
    _token(value.get("requestId"))
    _token(value.get("eventId"))
    _require(value["requestId"] == value["eventId"])
    scope, status = value.get("grantScope", "persistent"), value.get("status")
    _require(scope in {"persistent", "session", "turn"} and status in _STATUSES)
    for key, keys in _GRANT_DICTS.items():
        nested = _closed(value.get(key, {}), keys)
        for name, item in nested.items():
            if name == "canApplyLowRisk":
                _require(type(item) is bool)
            elif name in {"grantTools", "revokeTools", "blockTools", "unblockTools", "allowedTools", "blockedTools", "writeScopes"}:
                _require(type(item) is list and all(type(v) is str for v in item))
            else:
                _require(type(item) is str)
    if "riskTags" in value:
        _require(type(value["riskTags"]) is list and all(type(v) is str for v in value["riskTags"]))
    if "requiresApproval" in value:
        _require(type(value["requiresApproval"]) is bool)
    if scope != "persistent":
        _token(value.get("sourceSessionId"))
        _token(value.get("sourceTurnId", ""), empty=scope == "session")
        temporary = value.get("temporaryGrant", {})
        if temporary:
            _require(temporary.get("scope") == scope and temporary.get("sessionId") == value["sourceSessionId"]
                and temporary.get("turnId", "") == value.get("sourceTurnId", ""))
        if status == "applied":
            _require(bool(temporary.get("grantTools")))
    return scope, status


def verify_recovery_inventory(result: RecoveryBindingInventory) -> None:
    """Revalidate private proof immediately before a caller consumes the report."""
    for snapshot in result.snapshots:
        verify_snapshot(snapshot)
    for path, identity in result.directoryproofs:
        try:
            check_path(path)
            _require(path_identity(path) == identity, "source_changed")
        except OSError:
            raise MigrationIOError("source_unavailable_or_changed") from None
    for path in result._missingproofs:
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise MigrationIOError("source_unavailable_or_changed") from None
        raise MigrationIOError("source_changed")


def _governance_source(*, workspace, agent_id, agent_row, project_root, authorized_governance_path):
    """Resolve registry authority lexically before probing either candidate log.

    Native _request_path uses workspacePath, and _ensure_agent_workspace has no
    valid canonical default for an absent workspacePath. Never call that helper:
    it creates directories. A nonstandard declared path needs exact caller
    authorization even when a stale canonical log happens to remain on disk.
    """
    if agent_row is None:
        return None, "agent_workspace_unproven"
    _require(type(agent_row) is dict and agent_row.get("agentId") == agent_id,
        "governance_agent_authority_mismatch")
    raw = agent_row.get("workspacePath")
    if raw is None or raw == "":
        return None, "agent_workspace_unproven"
    _require(type(raw) is str and bool(raw.strip()), "governance_workspace_invalid")
    from .migration_paths import _path
    lexical = Path(raw.strip())
    if (project_root is None and not lexical.is_absolute()
            and (not lexical.parts or lexical.parts[0].lower() != "workspace")):
        return None, "agent_workspace_resolution_required"
    source_root = validate_path(project_root) if project_root is not None else workspace
    declared = _path(raw, project_root=source_root, workspace=workspace)
    target = declared / "events/tool_governance_requests.jsonl"
    if authorized_governance_path is not None:
        approved = _path(authorized_governance_path, project_root=source_root, workspace=workspace, absolute=True)
        _require(approved == target, "governance_path_authority_mismatch")
    elif declared != workspace / "agents" / agent_id:
        return None, "explicit_governance_path_authorization_required"
    return target, ""


def inventory_recovery_bindings(*, workspace: Path, agent_id: str, project_id: str, instance_id: str,
        agent_row: dict | None = None, project_root: Path | None = None,
        authorized_governance_path: Path | None = None,
        max_files: int = 10000, max_file_bytes: int = 4 * 1024 * 1024,
        max_total_bytes: int = 32 * 1024 * 1024, max_grant_records: int = 10000) -> RecoveryBindingInventory:
    """Inventory all team recovery policies and this PA's grant-log counts.

    Uses explicit source identity and the selected raw registry ``agent_row``
    supplied by an authority-validating caller. Relative workspacePath follows
    native project/workspace semantics using ``project_root``. A custom workspace
    is not read unless ``authorized_governance_path`` supplies its exact absolute
    log path, already approved by the caller for this same source identity. The
    caller must revalidate registry/authorization snapshots before handoff.
    Missing row/path/approval stays unresolved; canonical leftovers are not read.
    ``max_files`` bounds every visited directory entry, including ignored native
    metadata/lock sidecars. Exceeding any budget, unsupported schema, or changed
    source raises a fixed diagnostic, never a truncated successful inventory.
    Missing sources produce unresolved evidence and never create directories.
    """
    for name, cap in _CAPS.items():
        value = locals()[name]
        _require(type(value) is int and 1 <= value <= cap, "invalid_source_budget")
    _token(agent_id, limit=128)
    for value in (project_id, instance_id):
        _token(value)
    workspace = check_path(validate_path(workspace))
    _require(workspace.is_dir(), "source_type_mismatch")
    grants, grant_reason = _governance_source(workspace=workspace, agent_id=agent_id, agent_row=agent_row,
        project_root=project_root, authorized_governance_path=authorized_governance_path)
    snapshots, proofs, missing, issues, rows = [], {}, [], [], []
    visited = total = 0

    def pin(path):
        path = check_path(path)
        identity = path_identity(path)
        _require(stat.S_ISDIR(identity[5]), "source_type_mismatch")
        if path in proofs:
            _require(proofs[path] == identity, "source_changed")
        proofs[path] = identity

    def present(path):
        # No resolver or native store helper may seed an absent namespace.
        current = workspace if path.is_relative_to(workspace) else Path(path.anchor)
        pin(current)
        for part in path.relative_to(current).parts:
            candidate = current / part
            try:
                candidate.lstat()
            except FileNotFoundError:
                missing.append(candidate)
                return False
            except OSError:
                raise MigrationIOError("source_unavailable_or_changed") from None
            check_path(candidate)
            if candidate != path:
                pin(candidate)
            current = candidate
        return True

    def children(path):
        nonlocal visited
        pin(path)
        result = []
        try:
            with os.scandir(path) as iterator:
                for child in iterator:
                    visited += 1
                    _require(visited <= max_files, "file_limit")
                    result.append(check_path(Path(child.path)))
        except OSError:
            raise MigrationIOError("source_unavailable_or_changed") from None
        _require(path_identity(path) == proofs[path], "source_changed")
        return sorted(result, key=lambda item: item.name)

    def read(path):
        nonlocal total
        snapshot = read_stable_file(path, min(max_file_bytes, max_total_bytes - total))
        total += len(snapshot.raw)
        snapshots.append(snapshot)
        return snapshot

    pin(workspace)
    teams = workspace / "teams"
    if not present(teams):
        issues.append({"type": "team_recovery", "status": "unresolved"})
    else:
        # Models are validation-only; never import generic store/service (which
        # can seed namespaces, reconcile native work, or dispatch recovery).
        from core.web.services.team_workflow.generic import models
        for team in children(teams):
            if not team.is_dir():
                _require(team.is_file(), "source_type_mismatch")
                continue  # Native team index/metadata, bounded but not read.
            team_id = _token(team.name, limit=96)
            generic = team / "generic-workflows"
            for kind in ("flows", "runs"):
                folder = generic / kind
                if not present(folder):
                    issues.append({"type": kind, "teamId": team_id, "status": "unresolved"})
                    continue
                for path in children(folder):
                    _require(path.is_file(), "source_type_mismatch")
                    if path.name.endswith(".json.lock"):
                        _token(path.name[:-10], limit=96)
                        continue
                    _require(path.suffix == ".json", "recovery_source_unknown_file")
                    _token(path.stem, limit=96)
                    value = strict_json(read(path).raw)
                    _require(type(value) is dict)
                    if kind == "flows":
                        parsed = _native(models.Flow, value)
                        _require(parsed["id"] == path.stem)
                        flow, run = parsed, None
                    else:
                        _run_extensions(value, models)
                        parsed = _native(models.Run, {k: v for k, v in value.items() if k in models.Run.model_fields})
                        _require(parsed["id"] == path.stem and parsed["teamId"] == team_id
                            and type(parsed["revision"]) is int and parsed["revision"] >= 1)
                        _token(parsed["id"], limit=96)
                        flow, run = parsed["flow"], parsed
                    row = _binding_row(flow, team_id=team_id, kind="saved_flow" if run is None else "frozen_run",
                        source_agent_id=agent_id, run=run)
                    if row is not None:
                        rows.append(row)

    counts = {scope: {status: 0 for status in _STATUSES} for scope in ("session", "turn")}
    available = grants is not None and present(grants)
    if available:
        raw = read(grants).raw
        records = 0
        for line in raw.splitlines():
            if not line.strip():
                continue
            records += 1
            _require(records <= max_grant_records, "grant_record_limit")
            scope, status = _grant_record(strict_json(line), agent_id)
            if scope in counts:
                counts[scope][status] += 1
    else:
        grant_reason = grant_reason or "governance_log_missing"
        issues.append({"type": "temporary_grants", "status": "unresolved", "reason": grant_reason})
    result = RecoveryBindingInventory(report={"schemaVersion": 1,
        "sourceScope": {"projectId": project_id, "instanceId": instance_id, "agentId": agent_id},
        "inventoryComplete": not issues, "bindings": rows, "issues": issues,
        "temporaryGrants": {"status": "observed" if available else "unresolved", "reason": grant_reason, "counts": counts,
            "processGrantsAbsentProven": False, **_DISPOSITION},
        "sourceQuiesced": False, "readyForCutover": False, **_DISPOSITION}, snapshots=tuple(snapshots),
        directoryproofs=tuple(proofs.items()), _missingproofs=tuple(missing))
    verify_recovery_inventory(result)
    return result
