"""Integrate an old-line task through a private, independently validated DAG.

The source checkout is observation-only. All commits, junctions and disposable
worktrees belong to this adapter, beneath the repository's common directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from scripts import local_quality_gate as gate
from scripts import reuse_research_contract as reuse


def _closeout():
    # Avoid an import cycle at the narrow task_closeout entry point.
    from scripts import task_closeout
    return task_closeout


def _git(root: Path, *args: str, input_text: str | None = None,
         env: dict[str, str] | None = None) -> str:
    if env is None:
        env = gate.git_hook_isolated_environment()
        # Even read-only status must not refresh the source index on disk.
        env["GIT_OPTIONAL_LOCKS"] = "0"
    result = gate.run_process(["git", *args], root, input_text=input_text, env=env)
    if result.returncode:
        raise _closeout().ManagedCloseoutError(
            "history_git_failed", (result.stderr or result.stdout).splitlines()[0][:300]
        )
    return result.stdout.strip()


def _home(root: Path) -> Path:
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common.resolve() / "vibelution-cache" / "history-bridge"


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(context) -> dict[str, str]:
    root = context.task_root
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise _closeout().ManagedCloseoutError("history_source_dirty")
    branch = _git(root, "symbolic-ref", "--short", "HEAD")
    if branch != context.branch:
        raise _closeout().ManagedCloseoutError("history_source_changed")
    return {
        "sourceRoot": str(root.resolve()), "sourceBranch": branch,
        "sourceHead": _git(root, "rev-parse", "HEAD"),
        "sourceTree": _git(root, "rev-parse", "HEAD^{tree}"),
    }


def _assert_snapshot(context, source: dict[str, str], main_sha: str, map_digest: str) -> None:
    from scripts import git_history_bridge as bridge
    if _source(context) != source:
        raise _closeout().ManagedCloseoutError("history_source_changed")
    if gate.git_lines(context.main_root, "status", "--porcelain"):
        raise _closeout().dirty_main_error(context)
    if gate.rev_parse(context.main_root, "HEAD") != main_sha:
        raise _closeout().ManagedCloseoutError("history_main_changed")
    current = bridge.load_active_mapping(context.task_root)
    if current is None or current.digest != map_digest:
        raise _closeout().ManagedCloseoutError("history_mapping_changed")


def _validate_owner(context, claim_id: str, agent_id: str) -> None:
    closeout = _closeout()
    closeout.validate_development_claim(context, claim_id=claim_id, agent_id=agent_id)
    status = closeout._coordination_call(context, "status")
    agents = status.get("agents") or []
    owner = next((item for item in agents if isinstance(item, dict) and item.get("id") == agent_id), None)
    if (owner is None or owner.get("state") not in {"active", "paused"}
            or owner.get("branch") != context.branch
            or os.path.normcase(str(Path(str(owner.get("worktree") or "")).resolve()))
            != os.path.normcase(str(context.task_root.resolve()))):
        raise closeout.ManagedCloseoutError("history_source_owner_mismatch")


def _copy_reuse(source, candidate, files: list[str]) -> dict[str, str] | None:
    if not reuse.reuse_research_required(files):
        return None
    original_id = source.branch.removeprefix("codex/")
    original_path = reuse.evidence_path(source.task_root, original_id)
    initial_digest = _digest(original_path) if original_path.is_file() else ""
    payload = _read_source_reuse(source)
    if payload is None:
        raise _closeout().ManagedCloseoutError("reuse_research_missing")
    original_digest = _digest(original_path)
    if original_digest != initial_digest:
        raise _closeout().ManagedCloseoutError("history_reuse_evidence_changed")
    candidate_id = candidate.branch.removeprefix("codex/")
    copied = dict(payload, taskId=candidate_id, branch=candidate.branch)
    # Keep the exact decision and candidate/source provenance. This is a new
    # task binding of a validated assessment, never a fabricated assessment.
    copied["historyBridgeSource"] = {"path": str(original_path), "sha256": original_digest}
    reuse.validate_evidence_payload(copied, candidate.task_root, task_id=candidate_id, branch=candidate.branch)
    _atomic(reuse.evidence_path(candidate.task_root, candidate_id), copied)
    return {"path": str(original_path), "sha256": original_digest}


def _read_source_reuse(source):
    try:
        return reuse.load_and_validate_evidence(
            source.task_root, task_id=source.branch.removeprefix("codex/"),
            branch=source.branch, project_root=source.main_root,
        )
    except reuse.ReuseResearchEvidenceError as error:
        raise _closeout().ManagedCloseoutError("reuse_research_invalid") from error


def _assert_reuse(source, evidence: dict[str, str] | None) -> None:
    if evidence is not None:
        if _read_source_reuse(source) is None or _digest(Path(evidence["path"])) != evidence["sha256"]:
            raise _closeout().ManagedCloseoutError("history_reuse_evidence_changed")


def _candidate_head(root: Path, main_sha: str, translated: str) -> str:
    if gate.is_ancestor(root, main_sha, translated):
        return translated
    merged = gate.run_process(["git", "merge-tree", "--write-tree", main_sha, translated], root)
    if merged.returncode:
        # merge-tree writes only objects; it never changes source index/files.
        raise _closeout().ManagedCloseoutError("history_merge_conflict")
    tree = merged.stdout.splitlines()[0].strip()
    # commit-tree must use the configured human identity, not inherited hook
    # author overrides. The normal main permit still checks raw identities.
    env = gate.git_hook_isolated_environment()
    for key in tuple(env):
        if key.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_")):
            env.pop(key)
    name = _git(root, "config", "user.name")
    email = _git(root, "config", "user.email")
    if not name or not email:
        raise _closeout().ManagedCloseoutError("history_human_identity_required")
    return _git(root, "-c", f"user.name={name}", "-c", f"user.email={email}",
                "commit-tree", tree, "-p", main_sha, "-p", translated,
                input_text="Merge translated task with current main\n", env=env)


def _manifest_binding(path: Path, candidate, head: str, main_sha: str, claim_id: str) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (payload.get("headSha") != head or payload.get("branch") != candidate.branch
            or Path(payload.get("worktree", "")).resolve() != candidate.task_root.resolve()
            or payload.get("validatedMainSha") != main_sha or payload.get("claimId") != claim_id):
        raise _closeout().ManagedCloseoutError("history_manifest_candidate_mismatch")
    return _digest(path)


def _cleanup_candidate(context, candidate_root: Path, candidate_branch: str, head: str) -> None:
    """Remove only our clean merged candidate, without force or traversal."""
    closeout = _closeout()
    candidates = (_home(context.task_root) / "candidates").resolve()
    if (candidate_root.resolve().parent != candidates
            or not candidate_branch.startswith("codex/history-")
            or candidate_root.name != candidate_branch.removeprefix("codex/history-")):
        raise closeout.ManagedCloseoutError("history_unsafe_candidate_cleanup")
    if not gate.is_ancestor(context.main_root, head, "HEAD"):
        raise closeout.ManagedCloseoutError("history_candidate_not_merged")
    if candidate_root.exists():
        if _git(candidate_root, "symbolic-ref", "--short", "HEAD") != candidate_branch:
            raise closeout.ManagedCloseoutError("history_candidate_changed")
        if _git(candidate_root, "rev-parse", "HEAD") != head or _git(candidate_root, "status", "--porcelain"):
            raise closeout.ManagedCloseoutError("history_candidate_changed")
        for relative in closeout.TASK_OWNED_EPHEMERAL_PATHS:
            path = candidate_root / relative
            if closeout._is_link_or_junction(path):
                closeout._remove_link_or_junction(path)
        _git(context.main_root, "worktree", "remove", str(candidate_root))
    exists = gate.run_process(["git", "show-ref", "--verify", f"refs/heads/{candidate_branch}"], context.main_root)
    if exists.returncode == 0:
        if _git(context.main_root, "rev-parse", candidate_branch) != head:
            raise closeout.ManagedCloseoutError("history_candidate_changed")
        _git(context.main_root, "branch", "-d", candidate_branch)


def _merged_result(receipt: dict[str, Any], *, errors: list[str] | None = None):
    return _closeout().ManagedCloseoutResult(
        status="merged_cleanup_pending", exit_code=0, merged=True,
        merge_sha=receipt["candidateHead"], manifest_path=receipt["manifest"],
        retryable=bool(errors),
        next_action=("retry_history_closeout_preserving_original_worktree_and_branch"
                     if errors else "retain_original_worktree_and_branch"), errors=errors or [],
    )


def _status(context) -> dict:
    return _closeout()._coordination_call(context, "status", "--include-completed")


def _release_recorded(context, path: Path, receipt: dict[str, Any], *, integration: bool) -> None:
    flag = "integrationReleased" if integration else "developmentReleased"
    if receipt.get(flag):
        return
    claim_id = receipt["integrationClaimId" if integration else "claimId"]
    claim = next((item for item in _status(context).get("claims", [])
                  if isinstance(item, dict) and item.get("id") == claim_id), None)
    if claim is None or claim.get("agentId") != receipt["agentId"]:
        raise _closeout().ManagedCloseoutError("history_receipt_claim_owner_mismatch")
    if integration and "integration/main" not in (claim.get("scopes") or []):
        raise _closeout().ManagedCloseoutError("history_receipt_integration_mismatch")
    if claim.get("status") != "completed":
        if claim.get("status") not in {"active", "ready"}:
            raise _closeout().ManagedCloseoutError("history_receipt_claim_not_active")
        _closeout().release_claim(context, claim_id, status="completed",
                                 reason=f"history-compatible merge at {receipt['candidateHead']}")
    # Read-back on the next retry recognizes a successful release even if this
    # write fails after the external mutation. Flags alone are never authority.
    receipt[flag] = True
    _atomic(path, receipt)


def _owner_after_merge(context, receipt):
    expected = {key: receipt[key] for key in ("sourceRoot", "sourceBranch", "sourceHead", "sourceTree")}
    try:
        actual = _source(context)
    except (OSError, RuntimeError, ValueError) as error:
        raise _closeout().ManagedCloseoutError("history_source_changed_after_merge") from error
    if actual != expected:
        raise _closeout().ManagedCloseoutError("history_source_changed_after_merge")
    owner = next((item for item in _status(context).get("agents", [])
                  if isinstance(item, dict) and item.get("id") == receipt["agentId"]), None)
    if (owner is None or owner.get("branch") != context.branch
            or owner.get("state") not in {"active", "paused", "completed"}
            or Path(str(owner.get("worktree") or "")).resolve() != context.task_root.resolve()):
        raise _closeout().ManagedCloseoutError("history_source_owner_changed_after_merge")
    return owner


def _finish(context, path: Path, receipt: dict[str, Any]):
    """Read back authority when recovering release/complete acknowledgement gaps."""
    closeout = _closeout()
    errors = []
    owner_safe = True
    if not receipt.get("ownerCompleted"):
        try:
            _owner_after_merge(context, receipt)
        except (OSError, RuntimeError, ValueError) as error:
            owner_safe = False
            receipt["ownerPending"] = True
            _atomic(path, receipt)
            errors.append(str(getattr(error, "code", "")) or closeout._bounded_error(error))
    if owner_safe:
        try:
            _release_recorded(context, path, receipt, integration=False)
        except (OSError, RuntimeError, ValueError) as error:
            owner_safe = False
            errors.append(closeout._bounded_error(error))
    # A source owner that continued working must retain its development claim;
    # our integration lease can still be completed independently.
    _release_recorded(context, path, receipt, integration=True)
    if owner_safe and not receipt.get("ownerCompleted"):
        owner = _owner_after_merge(context, receipt)
        if owner.get("state") != "completed":
            closeout.complete_agent(context, agent_id=receipt["agentId"], merge_sha=receipt["candidateHead"])
        receipt["ownerCompleted"] = True
        receipt["ownerPending"] = False
        _atomic(path, receipt)
    try:
        _cleanup_candidate(context, Path(receipt["candidateRoot"]), receipt["candidateBranch"], receipt["candidateHead"])
    except (OSError, RuntimeError, ValueError) as error:
        errors.append(f"history_candidate_cleanup_pending: {closeout._bounded_error(error)}")
    return _merged_result(receipt, errors=errors)


def _retry(context, path: Path, source: dict[str, str], receipt_map, claim_id: str, agent_id: str):
    if not path.is_file():
        return None
    receipt = json.loads(path.read_text(encoding="utf-8"))
    required = {"candidateHead", "candidateTree", "translatedHead", "mainSha", "manifest", "manifestDigest",
                "candidateRoot", "candidateBranch", "integrationClaimId"}
    if (not isinstance(receipt, dict) or receipt.get("schemaVersion") != 1
            or any(not isinstance(receipt.get(key), str) or not receipt[key] for key in required)):
        raise _closeout().ManagedCloseoutError("history_receipt_invalid")
    for key, value in {**source, "mapDigest": receipt_map.digest, "claimId": claim_id, "agentId": agent_id}.items():
        if receipt.get(key) != value:
            raise _closeout().ManagedCloseoutError("history_receipt_mismatch")
    candidate = receipt.get("candidateHead", "")
    if not gate.is_ancestor(context.main_root, candidate, "HEAD"):
        return None
    if (_git(context.main_root, "rev-parse", f"{candidate}^{{tree}}") != receipt.get("candidateTree")
            or not gate.is_ancestor(context.main_root, receipt["mainSha"], candidate)
            or _digest(Path(receipt["manifest"])) != receipt.get("manifestDigest")):
        raise _closeout().ManagedCloseoutError("history_receipt_mismatch")
    private = _closeout().CloseoutContext(context.main_root, Path(receipt["candidateRoot"]), receipt["candidateBranch"])
    _manifest_binding(Path(receipt["manifest"]), private, candidate, receipt["mainSha"], claim_id)
    from scripts import git_history_bridge as bridge
    translated = bridge.translate_task_dag(context.task_root, source["sourceHead"], receipt_map).head
    if translated != receipt.get("translatedHead"):
        raise _closeout().ManagedCloseoutError("history_receipt_translation_mismatch")
    if candidate != translated:
        parents = _git(context.main_root, "rev-list", "--parents", "-n", "1", candidate).split()[1:]
        merged_tree = gate.run_process(
            ["git", "merge-tree", "--write-tree", receipt["mainSha"], translated], context.main_root)
        if (parents != [receipt["mainSha"], translated] or merged_tree.returncode
                or merged_tree.stdout.splitlines()[0].strip() != receipt["candidateTree"]):
            raise _closeout().ManagedCloseoutError("history_receipt_candidate_mismatch")
    # The pre-merge receipt is sufficient to recover a crash after the Git
    # transaction but before writing its merged flag.
    receipt["merged"] = True
    _atomic(path, receipt)
    try:
        return _finish(context, path, receipt)
    except (OSError, RuntimeError, ValueError) as error:
        return _merged_result(receipt, errors=[_closeout()._bounded_error(error)])


def run_if_needed(context, *, claim_id: str, agent_id: str, base: str = "main",
                  integration_wait_seconds: float = 15.0, **_options):
    """Return None for normal histories; otherwise own the full closeout."""
    # Existing unit callers use synthetic contexts. Avoid probing non-repos.
    if not (context.task_root / ".git").exists():
        return None
    from scripts import git_history_bridge as bridge
    closeout = _closeout()
    lease = ""
    merged = False
    candidate_root = None
    candidate_branch = ""
    manifest_path = ""
    receipt = None
    result = None
    try:
        mapping = bridge.load_active_mapping(context.task_root)
        if mapping is None:
            return None
        if _git(context.task_root, "for-each-ref", "--format=%(refname)", "refs/replace"):
            raise closeout.ManagedCloseoutError("history_replace_refs_present")
        source = _source(context)
        main_sha = gate.rev_parse(context.main_root, "HEAD")
        incoming = set(_git(context.task_root, "rev-list", source["sourceHead"], f"^{main_sha}").splitlines())
        old_nodes = {old for old, new in mapping.mapping.items() if old != new}
        if not incoming.intersection(old_nodes):
            return None
        key = hashlib.sha256(json.dumps({**source, "mapDigest": mapping.digest}, sort_keys=True).encode()).hexdigest()
        receipt_path = _home(context.task_root) / "closeouts" / f"{key}.json"
        previous = _retry(context, receipt_path, source, mapping, claim_id, agent_id)
        if previous is not None:
            return previous
        _validate_owner(context, claim_id, agent_id)
        _assert_snapshot(context, source, main_sha, mapping.digest)
        translated = bridge.translate_task_dag(context.task_root, source["sourceHead"], mapping)
        head = _candidate_head(context.task_root, main_sha, translated.head)
        identifier = uuid.uuid4().hex
        candidate_branch = f"codex/history-{identifier}"
        candidate_root = _home(context.task_root) / "candidates" / identifier
        candidate_root.parent.mkdir(parents=True, exist_ok=True)
        _git(context.main_root, "worktree", "add", "-b", candidate_branch, str(candidate_root), head)
        candidate = closeout.CloseoutContext(context.main_root, candidate_root, candidate_branch)
        files = gate.changed_files(candidate_root, base)
        evidence = _copy_reuse(context, candidate, files)
        # Deliberately ignore any source manifest. Both gate and verifier see
        # the private candidate's own branch, root, tree and current main.
        validation = gate.run_closeout(candidate_root, base, claim_id)
        manifest_path = str(validation.manifest_path or "")
        if validation.outcome != "passed" or validation.manifest_path is None:
            result = closeout.ManagedCloseoutResult(
                status="validation_failed", exit_code=1, manifest_path=manifest_path,
                next_action=f"inspect_history_candidate: root={candidate_root}; branch={candidate_branch}",
                errors=[str(validation.outcome)],
                failures=closeout.command_failure_details(validation.outcome, validation.commands))
            return result
        verified = gate.verify_manifest(validation.manifest_path, candidate_root, base)
        if verified.outcome != "passed":
            raise closeout.ManagedCloseoutError(f"history_manifest_{verified.outcome}")
        # Bind the receipt to the exact independently validated candidate, even
        # when the general manifest verifier permits equivalent head content.
        manifest_digest = _manifest_binding(validation.manifest_path, candidate, head, main_sha, claim_id)
        _assert_snapshot(context, source, main_sha, mapping.digest)
        _assert_reuse(context, evidence)
        lease = closeout.acquire_integration_claim_with_retry(
            context, agent_id=agent_id, wait_seconds=integration_wait_seconds)
        _assert_snapshot(context, source, main_sha, mapping.digest)
        _assert_reuse(context, evidence)
        _validate_owner(context, claim_id, agent_id)
        verified = gate.verify_manifest(validation.manifest_path, candidate_root, base)
        if verified.outcome != "passed":
            raise closeout.ManagedCloseoutError(f"history_manifest_{verified.outcome}")
        if _manifest_binding(validation.manifest_path, candidate, head, main_sha, claim_id) != manifest_digest:
            raise closeout.ManagedCloseoutError("history_manifest_changed")
        _assert_snapshot(context, source, main_sha, mapping.digest)
        _assert_reuse(context, evidence)
        receipt = {"schemaVersion": 1, **source, "candidateHead": head,
                   "translatedHead": translated.head,
                   "candidateTree": gate.rev_parse(candidate_root, "HEAD^{tree}"),
                   "candidateRoot": str(candidate_root), "candidateBranch": candidate_branch,
                   "mainSha": main_sha, "mapDigest": mapping.digest,
                   "manifest": manifest_path, "manifestDigest": manifest_digest,
                   "sourceReuseEvidence": evidence, "claimId": claim_id, "agentId": agent_id,
                   "integrationClaimId": lease, "merged": False}
        _atomic(receipt_path, receipt)
        closeout.merge_ff_only(candidate, integration_claim_id=lease, target_sha=head)
        merged = True
        receipt["merged"] = True
        _atomic(receipt_path, receipt)
        result = _finish(context, receipt_path, receipt)
        lease = ""
        return result
    except (OSError, RuntimeError, ValueError) as error:
        if merged and receipt is not None:
            result = _merged_result(receipt, errors=[closeout._bounded_error(error)])
            return result
        code = str(getattr(error, "code", "")) or closeout._bounded_error(error)
        result = closeout.ManagedCloseoutResult(
            status="integration_claim_conflict" if code == "integration_claim_conflict" else "failed",
            exit_code=1, manifest_path=manifest_path, errors=[code],
            next_action=(f"inspect_history_candidate: root={candidate_root}; branch={candidate_branch}"
                         if candidate_root is not None else ""))
        return result
    finally:
        if lease and not merged:
            # No owner completion after failure. Release only our lease.
            try:
                closeout.release_claim(context, lease, status="released",
                                       reason="history compatibility closeout released its lease")
            except (OSError, RuntimeError, ValueError) as error:
                if result is not None:
                    result.errors.append(f"integration_release_pending: {lease}: {closeout._bounded_error(error)}")
        # Failed candidates are retained for evidence and retry; never force
        # remove a dirty/unmerged checkout or any source resource.
