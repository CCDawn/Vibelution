"""Transactional Git integration for supervised evolution candidates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from core.infrastructure import git_process
from scripts import git_claim_guard, local_quality_gate, task_closeout


class CandidateIntegrationError(RuntimeError):
    """Raised when a candidate cannot be integrated without losing evidence."""


def prepare_candidate(*, project_root: Path, candidate_root: Path, changed_files: list[dict[str, Any]],
                      expected_head: str, expected_variant_id: str, run_id: str) -> dict[str, Any]:
    """Freeze and validate before independent review, without promoting main."""
    from .self_evolution_candidate_workspace import inspect_candidate_workspace

    root, candidate = Path(project_root).resolve(), Path(candidate_root).resolve()
    if (_git_text(root, "branch", "--show-current") != "main" or _status_entries(root)
            or _git_text(root, "rev-parse", "HEAD") != expected_head):
        raise CandidateIntegrationError("stale_main: 无法在变化的主线上冻结待审候选。")
    workspace = {"worktreePath": str(candidate), "branch": _git_text(candidate, "branch", "--show-current"),
                 "baseCommit": expected_head}
    inspected = inspect_candidate_workspace(root, workspace)
    if (not expected_variant_id or inspected["variantId"] != expected_variant_id
            or _normalized_changed_paths(inspected["changedFiles"]) != _normalized_changed_paths(changed_files)):
        raise CandidateIntegrationError("candidate_changed: 实际候选与已提交的候选记录不符。")
    _freeze_candidate_head(candidate, changed_files=changed_files, run_id=run_id)
    frozen = inspect_candidate_workspace(root, workspace)
    if frozen["variantId"] != expected_variant_id or _status_entries(candidate):
        raise CandidateIntegrationError("candidate_changed: 冻结后候选内容发生变化。")
    _, verified = _validate_managed_candidate(root, candidate)
    if (_git_text(candidate, "rev-parse", "HEAD") != frozen["headCommit"]
            or _status_entries(candidate)):
        raise CandidateIntegrationError("candidate_changed: 验证期间候选提交发生变化。")
    if (_git_text(root, "rev-parse", "HEAD") != expected_head or _status_entries(root)):
        raise CandidateIntegrationError("stale_main: 验证期间主线发生变化。")
    return {**workspace, **frozen, "validationManifestPath": str(verified.manifest_path)}


def recover_candidate_integration(
    *, project_root: Path, candidate_root: Path, changed_files: list[dict[str, Any]],
    expected_head: str, expected_variant_id: str, run_id: str, manifest_root: Path,
    expected_candidate_commit: str = "",
) -> dict[str, Any] | None:
    """Recover an admitted, completed main transition without validation or merge.

    Git and claims are read-only here; only the rollback manifest is persisted.
    Missing proof returns None so callers can preserve the original failure.
    """
    root, candidate = Path(project_root).resolve(), Path(candidate_root).resolve()
    request = _integration_request(root, candidate, changed_files, expected_head,
                                   expected_variant_id, run_id)
    if not all(request[key] for key in ("runId", "baseCommit", "candidateVariantId")):
        return None
    intent = _read_integration_intent(_integration_intent_path(root, request["runId"]),
                                      request, expected_candidate_commit)
    if intent and _has_completed_integration(root, intent):
        return _integration_result(root, intent, Path(manifest_root),
                                   _recovered_governance(intent))
    return None


def finish_candidate_integration_governance(
    *, project_root: Path, candidate_root: Path, changed_files: list[dict[str, Any]],
    expected_head: str, expected_variant_id: str, run_id: str, manifest_root: Path,
    expected_candidate_commit: str = "",
) -> dict[str, Any]:
    """Finish only the recorded claims and agent after a proven main advance."""
    root, candidate = Path(project_root).resolve(), Path(candidate_root).resolve()
    request = _integration_request(root, candidate, changed_files, expected_head,
                                   expected_variant_id, run_id)
    path = _integration_intent_path(root, request["runId"])
    intent = _read_integration_intent(path, request, expected_candidate_commit)
    if intent is None or not _has_completed_integration(root, intent):
        raise CandidateIntegrationError("integration_not_proven: 缺少已完成合入证据，禁止释放治理归属。")
    cleanup = intent.get("governanceCleanup")
    if isinstance(cleanup, dict) and cleanup.get("status") == "completed":
        return dict(cleanup)
    try:
        binding = intent.get("developmentBinding")
        lease = intent.get("integrationClaimId")
        if (not isinstance(binding, dict)
                or not all(isinstance(binding.get(key), str) and binding[key].strip()
                           for key in ("claimId", "agentId", "branch"))
                or not binding["branch"].startswith("codex/")
                or not isinstance(lease, str) or not lease or lease == binding["claimId"]):
            raise CandidateIntegrationError("governance_binding_missing: 缺少可信的预写治理身份。")
        context = task_closeout.CloseoutContext(root, candidate, binding["branch"])
        snapshot = task_closeout._coordination_call(context, "status")
        claims, agents = snapshot.get("claims"), snapshot.get("agents")
        if not isinstance(claims, list) or not isinstance(agents, list):
            raise CandidateIntegrationError("governance_status_invalid: 治理记录不完整。")
        agent = next((item for item in agents if isinstance(item, dict)
                      and item.get("id") == binding["agentId"]), None)
        if agent and ((agent.get("branch") and agent["branch"] != binding["branch"])
                      or (agent.get("worktree") and Path(str(agent["worktree"])).resolve() != candidate)):
            raise CandidateIntegrationError("governance_binding_changed: 原 Agent 已转移到其他任务。")
        recorded = []
        for claim_id in (lease, binding["claimId"]):
            claim = next((item for item in claims if isinstance(item, dict)
                          and item.get("id") == claim_id), None)
            if claim is None:  # Completed claims can already have been pruned.
                continue
            if (claim.get("agentId") != binding["agentId"]
                    or (claim_id == lease and (claim.get("laneId") != "integration"
                                               or claim.get("scopes") != ["integration/main"]))):
                raise CandidateIntegrationError("governance_binding_changed: 预写 claim 的归属或范围已变化。")
            if claim.get("status") in {"active", "ready", "yielded", "blocked"}:
                recorded.append(claim_id)
            elif claim.get("status") not in {"completed", "released", "expired"}:
                raise CandidateIntegrationError("governance_status_invalid: 预写 claim 状态不可识别。")
        for claim_id in recorded:
            task_closeout.release_claim(context, claim_id, status="completed", reason="Supervised integration recovered")
        if agent and agent.get("state") != "completed":
            # The shared seam refuses completion while any other live claim remains.
            task_closeout.complete_agent(context, agent_id=binding["agentId"], merge_sha=intent["candidateCommit"])
        cleanup = {"status": "completed", "errors": []}
        intent["governanceCleanup"] = cleanup
        _write_json_atomic(path, intent)
        return cleanup
    except (OSError, RuntimeError, ValueError) as error:
        cleanup = {"status": "pending", "errors": [str(error)[:300]]}
        intent["governanceCleanup"] = cleanup
        try:
            _write_json_atomic(path, intent)
        except (OSError, RuntimeError, ValueError):
            pass  # Retain the original cleanup failure; no completed receipt was written.
        raise CandidateIntegrationError(f"governance_cleanup_pending: {error}") from error


def _recovered_governance(intent: dict[str, Any]) -> dict[str, Any]:
    cleanup = intent.get("governanceCleanup")
    if not isinstance(cleanup, dict):
        cleanup = {"status": "pending", "errors": []}
    return {**cleanup, "recovered": True}


def integrate_candidate(
    *,
    project_root: Path,
    candidate_root: Path,
    changed_files: list[dict[str, Any]],
    expected_head: str,
    expected_variant_id: str,
    run_id: str,
    manifest_root: Path,
    expected_candidate_commit: str = "",
    admission_guard=None,
) -> dict[str, Any]:
    """Promote a frozen candidate only while local main still matches its base."""

    root = Path(project_root).resolve()
    candidate = Path(candidate_root).resolve()
    branch = _git_text(root, "branch", "--show-current")
    if branch != "main":
        raise CandidateIntegrationError(f"受控合入只允许写入 main；当前分支为 {branch or 'detached'}。")
    variant_id = str(expected_variant_id or "").strip()
    if not variant_id:
        raise CandidateIntegrationError("候选版本未绑定，禁止创建合入提交。")

    frozen_head = str(expected_head or "").strip()
    if not frozen_head:
        raise CandidateIntegrationError(
            "missing_frozen_main: 候选未绑定冻结的 main 提交，禁止自动晋升。"
        )
    run_label = str(run_id or "").strip()
    if not run_label:
        raise CandidateIntegrationError("缺少 runId，禁止创建无法恢复归属的合入记录。")
    request = _integration_request(root, candidate, changed_files, frozen_head, variant_id, run_label)
    intent_path = _integration_intent_path(root, run_label)
    intent = _read_integration_intent(intent_path, request, expected_candidate_commit)
    if intent and _has_completed_integration(root, intent):
        return _integration_result(root, intent, Path(manifest_root),
                                   _recovered_governance(intent))

    dirty = _status_entries(root)
    if dirty:
        raise CandidateIntegrationError(
            f"主工作区必须完全干净后才能自动合入；当前存在 {len(dirty)} 项改动。"
        )
    current_head = _git_text(root, "rev-parse", "HEAD")
    if current_head != frozen_head:
        raise CandidateIntegrationError(
            "stale_main: main 已从候选冻结基线前进；"
            f"expected={frozen_head[:12]} current={current_head[:12]}。"
            "请基于最新 main 重新生成、评估并审批候选。"
        )

    if not candidate.is_dir():
        raise CandidateIntegrationError("候选工作树不可用，禁止创建合入提交。")

    if expected_candidate_commit and (_status_entries(candidate)
            or _git_text(candidate, "rev-parse", "HEAD") != expected_candidate_commit):
        raise CandidateIntegrationError("reviewed_candidate_changed: 候选已偏离独立审查的固定提交。")
    _freeze_candidate_head(candidate, changed_files=changed_files, run_id=run_id)
    candidate_head = _fetch_candidate_head(root, candidate)
    if not candidate_head:
        raise CandidateIntegrationError("无法解析候选 HEAD，禁止晋升。")
    if candidate_head == current_head:
        raise CandidateIntegrationError("候选与 main 指向同一提交，禁止空晋升。")
    if not _is_ancestor(root, current_head, candidate_head):
        raise CandidateIntegrationError(
            "candidate_not_descendant: 候选提交不是冻结 main 的后代，禁止自动晋升。"
        )

    current_tree = _git_text(root, "rev-parse", f"{current_head}^{{tree}}")
    candidate_tree = _git_text(root, "rev-parse", f"{candidate_head}^{{tree}}")
    if current_tree == candidate_tree:
        raise CandidateIntegrationError("候选与 main 工作树相同，禁止空晋升。")

    if expected_candidate_commit and candidate_head != expected_candidate_commit:
        raise CandidateIntegrationError("reviewed_candidate_changed: 候选提交与审查证据不符。")
    if intent and intent["candidateCommit"] != candidate_head:
        raise CandidateIntegrationError("integration_intent_mismatch: runId 已绑定另一候选提交。")
    intent = {**request, "schemaVersion": 1, "candidateCommit": candidate_head,
              "createdAt": _now_iso()}
    governance_cleanup = _merge_validated_candidate(root, candidate, expected_head=frozen_head,
        candidate_head=candidate_head, integration_intent=(intent_path, intent),
        **({"admission_guard": admission_guard} if admission_guard else {}))

    commit_sha = _git_text(root, "rev-parse", "HEAD")
    if commit_sha != candidate_head:
        raise CandidateIntegrationError("Git 晋升未推进 HEAD，已中止自动合入。")
    result_tree = _git_text(root, "rev-parse", f"{commit_sha}^{{tree}}")
    if result_tree != candidate_tree:
        raise CandidateIntegrationError("晋升后 main 工作树与候选不一致，已中止。")
    if _status_entries(root):
        raise CandidateIntegrationError(
            f"候选提交后主工作区仍有 {len(_status_entries(root))} 项改动，不能声明合入完成。"
        )

    return _integration_result(root, intent, Path(manifest_root), governance_cleanup)


def _integration_result(root: Path, intent: dict[str, Any], manifest_root: Path,
                        governance_cleanup: dict[str, Any]) -> dict[str, Any]:
    """Persist the result independently of the irreversible main ref advance."""
    changed_paths = _nul_paths(_git_bytes(
        root, "diff", "--name-only", "-z", intent["baseCommit"], intent["candidateCommit"],
    ))
    manifest = {
        "schemaVersion": 3,
        "mechanism": "git_merge_ff",
        "runId": intent["runId"],
        "createdAt": intent["createdAt"],
        "baseCommit": intent["baseCommit"],
        "candidateCommit": intent["candidateCommit"],
        "frozenMain": intent["baseCommit"],
        "candidateVariantId": intent["candidateVariantId"],
        "commitSha": intent["candidateCommit"],
        "changedFiles": changed_paths,
    }
    manifest_path = _write_manifest(Path(manifest_root), manifest)

    return {
        "status": "committed",
        "mechanism": "git_merge_ff",
        "baseCommit": intent["baseCommit"],
        "commitSha": intent["candidateCommit"],
        "candidateCommit": intent["candidateCommit"],
        "candidateVariantId": intent["candidateVariantId"],
        "changedFiles": changed_paths,
        "rollbackManifestPath": str(manifest_path),
        "committedAt": intent["createdAt"],
        "governanceCleanup": governance_cleanup,
    }


def revert_candidate_commit(
    *,
    project_root: Path,
    integration_commit: str,
    run_id: str,
) -> dict[str, Any]:
    """Create an auditable revert commit for a previously integrated candidate."""

    root = Path(project_root).resolve()
    commit_sha = str(integration_commit or "").strip()
    if not commit_sha:
        raise CandidateIntegrationError("缺少候选合入提交，不能执行回退。")
    if _status_entries(root):
        raise CandidateIntegrationError("主工作区必须完全干净后才能回退候选提交。")
    current_head = _git_text(root, "rev-parse", "HEAD")
    if current_head != commit_sha:
        raise CandidateIntegrationError(
            "自动回退仅允许在候选合入提交仍为当前 HEAD 时执行，避免覆盖后续提交。"
        )
    parents = _git_text(root, "rev-list", "--parents", "-n", "1", commit_sha).split()
    revert_args = ["revert", "--no-edit"]
    if len(parents) >= 3:
        revert_args.extend(["-m", "1"])
    revert_args.append(commit_sha)
    result = git_process.run_git(
        revert_args,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        raise CandidateIntegrationError(f"Git revert 失败：{detail or 'unknown error'}")
    revert_sha = _git_text(root, "rev-parse", "HEAD")
    if not revert_sha or revert_sha == commit_sha or _status_entries(root):
        raise CandidateIntegrationError("Git revert 未形成干净、可审计的新提交。")
    return {
        "status": "reverted",
        "runId": str(run_id or "").strip(),
        "revertedCommit": commit_sha,
        "revertCommit": revert_sha,
        "revertedAt": _now_iso(),
    }


def _merge_validated_candidate(root: Path, candidate: Path, *, expected_head: str, candidate_head: str,
                               admission_guard=None, integration_intent=None) -> dict[str, Any]:
    """Use the same validation, lease and exact-ref permit as task integration."""
    binding, verified = _validate_managed_candidate(root, candidate)
    context = task_closeout.CloseoutContext(root, candidate, binding.branch)
    merged_sha = ""
    cleanup_errors: list[str] = []
    try:
        lease = task_closeout.acquire_integration_claim_with_retry(context, agent_id=binding.agent_id)
        try:
            verified = local_quality_gate.verify_manifest(verified.manifest_path, candidate, "main")
            if (
                verified.outcome != "passed"
                or _git_text(root, "rev-parse", "HEAD") != expected_head
                or _git_text(candidate, "rev-parse", "HEAD") != candidate_head
            ):
                raise CandidateIntegrationError("stale_main: 主线或候选验证证据已变化，请重新评估候选。")
            with admission_guard() if admission_guard else nullcontext():
                if integration_intent is not None:
                    if (_git_text(root, "rev-parse", "HEAD") != expected_head
                            or _git_text(candidate, "rev-parse", "HEAD") != candidate_head
                            or _status_entries(root) or _status_entries(candidate)):
                        raise CandidateIntegrationError("stale_main: 准入期间主线或候选发生变化。")
                    path, intent = integration_intent
                    reflog = _main_reflog_path(root).read_bytes()
                    intent["mainReflogOffset"] = len(reflog)
                    intent["mainReflogPrefixDigest"] = hashlib.sha256(reflog).hexdigest()
                    intent["developmentBinding"] = {"claimId": binding.claim_id,
                                                     "agentId": binding.agent_id, "branch": binding.branch}
                    intent["integrationClaimId"] = lease
                    _write_json_atomic(path, intent)
                merged_sha = task_closeout.merge_ff_only(context, integration_claim_id=lease, target_sha=candidate_head)
        finally:
            try:
                task_closeout.release_claim(context, lease, status="released", reason="Supervised integration finished")
            except (OSError, RuntimeError, ValueError) as error:
                if not merged_sha:
                    raise
                cleanup_errors.append(str(error)[:300])
        try:
            task_closeout.release_claim(context, binding.claim_id, status="completed", reason="Supervised candidate integrated")
            task_closeout.complete_agent(context, agent_id=binding.agent_id, merge_sha=merged_sha)
        except (OSError, RuntimeError, ValueError) as error:
            cleanup_errors.append(str(error)[:300])
        cleanup = {"status": "pending" if cleanup_errors else "completed", "errors": cleanup_errors}
        if integration_intent is not None:
            path, intent = integration_intent
            intent["governanceCleanup"] = cleanup
            _write_json_atomic(path, intent)
        return cleanup
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, CandidateIntegrationError):
            raise
        raise CandidateIntegrationError(f"受控集成未完成：{error}") from error


def _validate_managed_candidate(root: Path, candidate: Path):
    binding = git_claim_guard.read_claim_binding(candidate)
    if binding is None:
        raise CandidateIntegrationError("候选缺少开发归属记录，请在受管 codex 分支完成候选验证后重试。")
    if (
        not binding.branch.startswith("codex/")
        or Path(binding.worktree).resolve() != candidate.resolve()
        or binding.branch != _git_text(candidate, "branch", "--show-current")
    ):
        raise CandidateIntegrationError("候选分支与开发归属记录不匹配，禁止集成。")
    context = task_closeout.CloseoutContext(root, candidate, binding.branch)
    try:
        task_closeout.validate_development_claim(
            context, claim_id=binding.claim_id, agent_id=binding.agent_id,
        )
        manifest = task_closeout.discover_manifest(context)
        verified = local_quality_gate.verify_manifest(manifest, candidate, "main") if manifest else None
        if verified is None or verified.outcome != "passed":
            verified = local_quality_gate.run_closeout(candidate, "main", binding.claim_id)
        if verified.outcome != "passed" or verified.manifest_path is None:
            raise CandidateIntegrationError(f"候选集成验证未通过：{verified.outcome}。候选已保留，请查看验证记录。")
        return binding, verified
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, CandidateIntegrationError):
            raise
        raise CandidateIntegrationError(f"受控集成未完成：{error}") from error


def _freeze_candidate_head(
    candidate: Path,
    *,
    changed_files: list[dict[str, Any]],
    run_id: str,
) -> None:
    """Commit pending judged changes so promote only reads a Git tree."""

    tracked_dirty = _nul_paths(
        _git_bytes(candidate, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    )
    judged_paths = set(_normalized_changed_paths(changed_files))
    untracked = _nul_paths(
        _git_bytes(candidate, "ls-files", "--others", "--exclude-standard", "-z")
    )
    judged_untracked = [path for path in untracked if path in judged_paths]
    if not tracked_dirty and not judged_untracked:
        return
    if tracked_dirty:
        _run_git_checked(candidate, "add", "-u", "--")
    if judged_untracked:
        _run_git_checked(candidate, "add", "--", *judged_untracked)
    if not _nul_paths(_git_bytes(candidate, "diff", "--cached", "--name-only", "-z")):
        raise CandidateIntegrationError("候选工作区有未提交改动，不在 Git 管辖内，禁止晋升。")
    label = str(run_id or "").strip() or "candidate"
    _run_git_checked(
        candidate,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        f"evolve(supervised): freeze {label}",
    )
    leftover_tracked = _nul_paths(
        _git_bytes(candidate, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    )
    leftover_judged = [
        path
        for path in _nul_paths(
            _git_bytes(candidate, "ls-files", "--others", "--exclude-standard", "-z")
        )
        if path in judged_paths
    ]
    if leftover_tracked or leftover_judged:
        raise CandidateIntegrationError("候选冻结提交后仍有未纳入 Git 的改动，禁止晋升。")


def _fetch_candidate_head(root: Path, candidate: Path) -> str:
    fetch = git_process.run_git(
        [
            "fetch",
            "--no-tags",
            str(candidate),
            "+HEAD:refs/vibelution/supervised-promote",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if fetch.returncode != 0:
        detail = str(fetch.stderr or fetch.stdout or "").strip()
        raise CandidateIntegrationError(f"无法把候选提交取入 main 仓库：{detail or 'fetch failed'}")
    return _git_text(root, "rev-parse", "refs/vibelution/supervised-promote")


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = git_process.run_git(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _normalized_changed_paths(changed_files: list[dict[str, Any]]) -> list[str]:
    paths: set[str] = set()
    for item in changed_files:
        raw = str(item.get("path") or "").strip().replace("\\", "/")
        path = PurePosixPath(raw)
        if (
            not raw
            or path.is_absolute()
            or raw.startswith("/")
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise CandidateIntegrationError(f"候选路径不安全：{raw or '<empty>'}")
        paths.add(path.as_posix())
    return sorted(paths)


def _integration_intent_path(root: Path, run_id: str) -> Path:
    common = Path(_git_text(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common / "vibelution" / "supervised-integrations" / f"{hashlib.sha256(run_id.encode()).hexdigest()}.json"


def _integration_request(root: Path, candidate: Path, changed_files: list[dict[str, Any]],
                         expected_head: str, variant_id: str, run_id: str) -> dict[str, Any]:
    return {
        "runId": str(run_id or "").strip(), "projectRoot": str(root), "candidateRoot": str(candidate),
        "baseCommit": str(expected_head or "").strip(), "candidateVariantId": str(variant_id or "").strip(),
        "changedFiles": _normalized_changed_paths(changed_files),
    }


def _main_reflog_path(root: Path) -> Path:
    return Path(_git_text(root, "rev-parse", "--path-format=absolute", "--git-path", "logs/refs/heads/main"))


def _read_integration_intent(path: Path, request: dict[str, Any], expected_commit: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        intent = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(intent, dict) or intent.get("schemaVersion") != 1
                or any(intent.get(key) != value for key, value in request.items())
                or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(intent.get("candidateCommit") or ""))
                or (expected_commit and intent["candidateCommit"] != expected_commit)
                or not isinstance(intent.get("mainReflogOffset"), int)
                or intent["mainReflogOffset"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(intent.get("mainReflogPrefixDigest") or ""))
                or not intent.get("createdAt")):
            raise ValueError("integration binding differs")
        return intent
    except (OSError, ValueError, TypeError) as error:
        raise CandidateIntegrationError("integration_intent_mismatch: 合入意图无法绑定当前 run/base/SHA/variant/path。") from error


def _has_completed_integration(root: Path, intent: dict[str, Any]) -> bool:
    """Prove a *new* exact main transition after the durable admission intent.

    An ancestor alone (or a merge that predates this run's intent) is insufficient.
    Another owner merging the same fixed SHA after admission has the same result.
    """
    try:
        reflog = _main_reflog_path(root).read_bytes()
    except OSError:
        return False
    offset = intent["mainReflogOffset"]
    if len(reflog) <= offset or hashlib.sha256(reflog[:offset]).hexdigest() != intent["mainReflogPrefixDigest"]:
        return False
    base, candidate = intent["baseCommit"], intent["candidateCommit"]
    message = f"merge {candidate}: Fast-forward".encode("ascii")
    for entry in reflog[offset:].splitlines():
        identity, separator, action = entry.partition(b"\t")
        fields = identity.split(b" ", 2)
        if (separator and len(fields) == 3 and fields[:2] == [base.encode("ascii"), candidate.encode("ascii")]
                and action == message):
            return (_is_ancestor(root, base, candidate)
                    and _is_ancestor(root, candidate, _git_text(root, "rev-parse", "refs/heads/main")))
    return False


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_manifest(manifest_root: Path, manifest: dict[str, Any]) -> Path:
    root = Path(manifest_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    label = f"{manifest['runId']}-{manifest['candidateVariantId']}"
    safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:48]
    path = root / f"{safe_label}-{hashlib.sha256(label.encode()).hexdigest()[:12]}.json"
    _write_json_atomic(path, manifest)
    return path


def _status_entries(root: Path) -> list[str]:
    return _nul_paths(
        _git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    )


def _git_text(root: Path, *args: str) -> str:
    result = _run_git_checked(
        root,
        *args,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return str(result.stdout or "").strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = _run_git_checked(root, *args, text=False)
    value = result.stdout or b""
    return value if isinstance(value, bytes) else str(value).encode("utf-8")


def _run_git_checked(root: Path, *args: str, **kwargs: Any):
    result = git_process.run_git(
        list(args),
        cwd=root,
        capture_output=True,
        check=False,
        **kwargs,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
        stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout or "")
        raise CandidateIntegrationError((stderr or stdout or "Git command failed").strip())
    return result


def _nul_paths(value: bytes) -> list[str]:
    return sorted(
        item.decode("utf-8", errors="replace")
        for item in value.split(b"\0")
        if item
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
