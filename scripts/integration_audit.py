from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


CONFIG_SENSITIVE_BASENAMES = {
    "config.toml",
    "config.example.toml",
    "VERSION",
    "CHANGELOG.md",
}

CONFIG_SENSITIVE_REPO_PATHS = {
    "web/package-lock.json",
}

CONFIG_SENSITIVE_FRAGMENTS = {
    "config/",
    "config\\",
    "config_paths",
    "config_service",
    "model_reference",
    "runtime_capabilities",
    "web/src/routes/config",
    "web\\src\\routes\\config",
}

FRONTEND_TEST_RECOMMENDATIONS = (
    ("web/src/routes/agentsroute", "npm --prefix web run test -- AgentsRoute.layout.test.ts"),
    (
        "web/src/routes/configroute",
        "npm --prefix web run test -- ConfigRoute.layout.test.ts configRouteLogic.test.ts",
    ),
    (
        "web/src/routes/configroutelogic",
        "npm --prefix web run test -- ConfigRoute.layout.test.ts configRouteLogic.test.ts",
    ),
    ("web/src/routes/teamsroute", "npm --prefix web run test -- TeamsRoute.layout.test.ts"),
    (
        "web/src/routes/launcherroute",
        "npm --prefix web run test -- AppShellNavigationTelemetry.test.ts LauncherRoute.layout.test.ts",
    ),
    (
        "web/src/app/appshell",
        "npm --prefix web run test -- AppShellNavigationTelemetry.test.ts LauncherRoute.layout.test.ts",
    ),
)

PYTEST_RECOMMENDATIONS = (
    (
        "tests/test_agent_config_workspace_service.py",
        "python -m pytest tests/test_agent_config_workspace_service.py -q",
    ),
    (
        "tests/test_launcher_scripts.py",
        "python -m pytest tests/test_launcher_scripts.py tests/test_runtime_manager.py tests/test_launcher_service.py -q",
    ),
    (
        "tests/test_runtime_manager.py",
        "python -m pytest tests/test_launcher_scripts.py tests/test_runtime_manager.py tests/test_launcher_service.py -q",
    ),
    ("tests/test_launcher_service.py", "python -m pytest tests/test_launcher_service.py -q"),
    ("tests/test_integration_audit.py", "python -m pytest tests/test_integration_audit.py -q"),
)

LAUNCHER_RUNTIME_FRAGMENTS = (
    "core/launcher/",
    "core/runtime_manager/",
    "scripts/vibelution_launcher",
    "scripts/vibelution_desktop_entry",
)

CHALLENGE_CUP_FRAGMENT = "\u6311\u6218\u676f/"

ACTIVE_STATUSES = {
    "active",
    "claimed",
    "in_progress",
    "running",
}

READY_STATUSES = {
    "ready",
    "ready_for_merge",
}

MERGED_STATUSES = {
    "merged",
    "merged_to_main",
    "closed",
    "done",
}

HOT_FILE_FRAGMENTS = (
    "AGENTS.md",
    "DEVELOPMENT_STANDARD.md",
    ".docs/project-memory/",
    ".docs/project-memory\\",
    "PROJECT_MEMORY.html",
    "tests/test_web_app.py",
)


@dataclass
class GitResult:
    code: int
    stdout: str
    stderr: str


@dataclass
class ClaimRef:
    claim_id: str
    status: str
    branch: str = ""
    worktree: str = ""
    changed_files: list[str] = field(default_factory=list)


@dataclass
class WorktreeAuditItem:
    worktree: str
    branch: str
    head: str
    is_main: bool
    exists: bool
    clean: bool
    dirty_paths: list[str]
    touched_paths: list[str]
    claim_ids: list[str]
    claim_statuses: list[str]
    ready_claim_ids: list[str]
    queued_claim_ids: list[str]
    plus_commits: int
    minus_commits: int
    head_ancestor_of_main: bool
    main_ancestor_of_head: bool
    touches_config_sensitive: bool
    decision: str
    suggested_action: str
    reasons: list[str]
    risk_level: str
    risk_score: int
    risk_reasons: list[str]
    merge_method: str
    recommended_validations: list[str]


@dataclass
class DuplicateReadyGroup:
    head: str
    worktree: str
    branch: str
    claim_ids: list[str]


@dataclass
class IntegrationAuditReport:
    root: str
    main_branch: str
    main_head: str
    operator_config: str
    merge_queue_claim_ids: list[str]
    duplicate_ready_groups: list[DuplicateReadyGroup]
    items: list[WorktreeAuditItem]
    summary: dict[str, int]


@dataclass
class StashAuditItem:
    ref: str
    summary: str
    file_count: int
    touched_paths: list[str]
    sample_paths: list[str]
    touches_protected: bool
    touches_hot: bool
    kind: str
    suggested_action: str
    reasons: list[str]


@dataclass
class StashAuditReport:
    root: str
    items: list[StashAuditItem]
    summary: dict[str, int]


def run_git(root: Path, *args: str, check: bool = False) -> GitResult:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with {completed.returncode}: {completed.stderr.strip()}"
        )
    return GitResult(completed.returncode, completed.stdout, completed.stderr)


def normalize_branch(ref: str) -> str:
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        return ref[len(prefix) :]
    return ref


def norm_path_key(path: str | Path) -> str:
    return str(Path(path).resolve(strict=False)).replace("\\", "/").casefold()


def load_registry(registry_path: Path) -> tuple[dict[str, ClaimRef], list[str]]:
    if not registry_path.exists():
        return {}, []
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    raw_claims = data.get("workClaims") or data.get("claims") or {}
    claims: dict[str, ClaimRef] = {}
    for claim_id, raw in raw_claims.items():
        if not isinstance(raw, dict):
            continue
        changed_files = raw.get("changedFiles") or raw.get("changed_files") or []
        if not isinstance(changed_files, list):
            changed_files = []
        claims[claim_id] = ClaimRef(
            claim_id=claim_id,
            status=str(raw.get("status") or ""),
            branch=str(raw.get("branch") or ""),
            worktree=str(raw.get("worktree") or raw.get("worktreePath") or ""),
            changed_files=[str(item) for item in changed_files],
        )
    queue = data.get("mergeQueue") or data.get("merge_queue") or []
    queue_ids: list[str] = []
    if isinstance(queue, list):
        for item in queue:
            if isinstance(item, str):
                queue_ids.append(item)
            elif isinstance(item, dict) and item.get("claimId"):
                queue_ids.append(str(item["claimId"]))
    return claims, queue_ids


def parse_worktrees(root: Path) -> list[dict[str, str]]:
    result = run_git(root, "worktree", "list", "--porcelain", check=True)
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        worktrees.append(current)
    return worktrees


def parse_dirty_paths(status_output: str) -> list[str]:
    paths: list[str] = []
    for line in status_output.splitlines():
        if not line:
            continue
        value = line[3:] if len(line) > 3 else line
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        paths.append(value.strip().strip('"'))
    return sorted(set(paths))


def count_cherry(root: Path, main_branch: str, branch: str) -> tuple[int, int, list[str]]:
    if not branch or branch == main_branch:
        return 0, 0, []
    result = run_git(root, "cherry", "-v", main_branch, branch)
    if result.code != 0:
        return 0, 0, [f"git_cherry_failed:{result.stderr.strip()}"]
    plus = 0
    minus = 0
    for line in result.stdout.splitlines():
        if line.startswith("+"):
            plus += 1
        elif line.startswith("-"):
            minus += 1
    return plus, minus, []


def diff_paths(root: Path, main_branch: str, branch: str) -> list[str]:
    if not branch or branch == main_branch:
        return []
    result = run_git(root, "diff", "--name-only", f"{main_branch}...{branch}")
    if result.code != 0:
        result = run_git(root, "diff", "--name-only", f"{main_branch}..{branch}")
    if result.code != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    if not ancestor or not descendant:
        return False
    result = run_git(root, "merge-base", "--is-ancestor", ancestor, descendant)
    return result.code == 0


def path_is_config_sensitive(path: str, operator_config: Path) -> bool:
    normalized = path.replace("\\", "/").casefold()
    basename = Path(path).name.casefold()
    if basename in {item.casefold() for item in CONFIG_SENSITIVE_BASENAMES}:
        return True
    if normalized in {item.casefold() for item in CONFIG_SENSITIVE_REPO_PATHS}:
        return True
    if norm_path_key(path) == norm_path_key(operator_config):
        return True
    return any(fragment.casefold() in normalized for fragment in CONFIG_SENSITIVE_FRAGMENTS)


def normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").casefold()


def any_path_matches(paths: Iterable[str], fragments: Iterable[str]) -> bool:
    normalized = [normalize_repo_path(path) for path in paths]
    return any(fragment.casefold() in path for path in normalized for fragment in fragments)


def unique_ordered(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def list_stashes(root: Path) -> list[tuple[str, str]]:
    result = run_git(root, "stash", "list", "--format=%gd|%gs", check=True)
    stashes: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        ref, _, summary = line.partition("|")
        stashes.append((ref.strip(), summary.strip()))
    return stashes


def stash_paths(root: Path, ref: str) -> list[str]:
    result = run_git(root, "stash", "show", "--name-only", "--format=", ref)
    if result.code != 0:
        return []
    return unique_ordered(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    )


def path_is_hot_file(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return any(fragment.casefold() in normalized for fragment in HOT_FILE_FRAGMENTS)


def classify_stash_item(paths: list[str]) -> tuple[str, str, list[str], bool, bool]:
    file_count = len(paths)
    touches_protected = any(path_is_config_sensitive(path, Path("__operator_config_unused__")) for path in paths)
    touches_hot = any(path_is_hot_file(path) for path in paths)
    tests_only = file_count > 0 and all(normalize_repo_path(path).startswith("tests/") for path in paths)
    reasons: list[str] = []
    if file_count == 0:
        reasons.append("no_tracked_paths_reported")
        return "empty_or_untracked_only", "manual_check_before_drop", reasons, touches_protected, touches_hot
    if touches_protected:
        reasons.append("protected_files")
        return "protected_risk", "retain_until_manual_diff_review", reasons, touches_protected, touches_hot
    if touches_hot:
        reasons.append("hot_files")
        return "hot_snapshot", "manual_scope_review", reasons, touches_protected, touches_hot
    if tests_only:
        reasons.append("tests_only")
        return "test_only", "compare_with_main_then_drop_if_absorbed", reasons, touches_protected, touches_hot
    if file_count <= 5:
        reasons.append("narrow_snapshot")
        return "small_snapshot", "targeted_review_for_salvage", reasons, touches_protected, touches_hot
    reasons.append("broad_snapshot")
    return "broad_snapshot", "retain_as_history_do_not_reapply_blindly", reasons, touches_protected, touches_hot


def recommend_validations(
    *,
    touched_paths: list[str],
    decision: str,
    touches_config_sensitive: bool,
) -> list[str]:
    commands: list[str] = []
    normalized = [normalize_repo_path(path) for path in touched_paths]
    if decision == "cleanup_ready":
        if touches_config_sensitive:
            commands.append(
                "manual: confirm cleanup only; do not edit or restore operator config"
            )
        commands.append(
            "manual: confirm worktree has no unique commits and no active claim before cleanup"
        )
        return unique_ordered(commands)
    if touches_config_sensitive:
        commands.append(
            "manual: review config boundary and preserve "
            "C:\\Users\\17533\\Documents\\Vibelution\\config\\config.toml"
        )
        commands.append("python -m pytest tests/test_web_app.py -q -k config_workspace")
        commands.append(
            "npm --prefix web run test -- ConfigRoute.layout.test.ts configRouteLogic.test.ts"
        )
    for fragment, command in FRONTEND_TEST_RECOMMENDATIONS:
        if any(fragment in path for path in normalized):
            commands.append(command)
    if any(path.startswith("web/") for path in normalized):
        commands.append("npm --prefix web run build")
    for fragment, command in PYTEST_RECOMMENDATIONS:
        if any(fragment in path for path in normalized):
            commands.append(command)
    if any_path_matches(touched_paths, LAUNCHER_RUNTIME_FRAGMENTS):
        commands.append(
            "python -m pytest tests/test_launcher_scripts.py tests/test_runtime_manager.py tests/test_launcher_service.py -q"
        )
    if any(CHALLENGE_CUP_FRAGMENT in path for path in normalized):
        commands.append("node \u6311\u6218\u676f/build_research_flow_site.mjs")
    py_paths = [
        path.replace("\\", "/")
        for path in touched_paths
        if normalize_repo_path(path).endswith(".py")
    ]
    if any(
        path in {"scripts/integration_audit.py", "tests/test_integration_audit.py"}
        for path in py_paths
    ):
        commands.append("python -m py_compile scripts/integration_audit.py tests/test_integration_audit.py")
    elif py_paths:
        commands.append(f"python -m py_compile {' '.join(py_paths[:10])}")
    if decision in {"merge_ready", "review_required"}:
        commands.append("git diff --check")
    return unique_ordered(commands)


def score_risk(
    *,
    decision: str,
    clean: bool,
    plus_commits: int,
    touches_config_sensitive: bool,
    touched_paths: list[str],
    reasons: list[str],
) -> tuple[str, int, list[str]]:
    if decision == "main":
        return "info", 0, []
    risk_reasons: list[str] = list(reasons)
    score = 10
    if decision == "blocked_active":
        score = 100
    elif decision == "review_required":
        score += 30
    elif decision == "merge_ready":
        score += 15
    elif decision == "cleanup_ready":
        score += 5
    if not clean:
        score += 35
        risk_reasons.append("dirty_worktree")
    if touches_config_sensitive:
        score += 15 if decision == "cleanup_ready" else 35
        risk_reasons.append("config_sensitive_paths")
    if plus_commits > 1:
        score += min(20, plus_commits * 4)
        risk_reasons.append("multi_commit_branch")
    if any_path_matches(touched_paths, LAUNCHER_RUNTIME_FRAGMENTS):
        score += 20
        risk_reasons.append("launcher_runtime_surface")
    if any(normalize_repo_path(path).startswith("web/") for path in touched_paths):
        score += 10
        risk_reasons.append("frontend_surface")
    if any(CHALLENGE_CUP_FRAGMENT in normalize_repo_path(path) for path in touched_paths):
        score += 8
        risk_reasons.append("generated_research_site_surface")
    score = min(score, 100)
    if score >= 90:
        level = "blocked" if decision == "blocked_active" else "high"
    elif score >= 60:
        level = "high"
    elif score >= 30:
        level = "medium"
    else:
        level = "low"
    return level, score, unique_ordered(risk_reasons)


def choose_merge_method(
    *,
    decision: str,
    clean: bool,
    plus_commits: int,
    main_ancestor_of_head: bool,
) -> str:
    if decision == "main":
        return "not_applicable"
    if decision == "cleanup_ready":
        return "not_applicable_cleanup_only"
    if decision == "blocked_active":
        return "blocked_active_claim"
    if decision != "merge_ready" or not clean:
        return "manual_review"
    if main_ancestor_of_head:
        return "fast_forward"
    if plus_commits == 1:
        return "cherry_pick"
    return "merge_commit_or_rebase_then_ff"


def claim_maps(claims: dict[str, ClaimRef]) -> tuple[dict[str, list[ClaimRef]], dict[str, list[ClaimRef]]]:
    by_worktree: dict[str, list[ClaimRef]] = {}
    by_branch: dict[str, list[ClaimRef]] = {}
    for claim in claims.values():
        if claim.worktree:
            by_worktree.setdefault(norm_path_key(claim.worktree), []).append(claim)
        if claim.branch:
            by_branch.setdefault(claim.branch, []).append(claim)
    return by_worktree, by_branch


def matching_claims(
    worktree: Path,
    branch: str,
    claims_by_worktree: dict[str, list[ClaimRef]],
    claims_by_branch: dict[str, list[ClaimRef]],
) -> list[ClaimRef]:
    seen: set[str] = set()
    matched: list[ClaimRef] = []
    for claim in claims_by_worktree.get(norm_path_key(worktree), []):
        matched.append(claim)
        seen.add(claim.claim_id)
    for claim in claims_by_branch.get(branch, []):
        if claim.claim_id not in seen:
            matched.append(claim)
            seen.add(claim.claim_id)
    return sorted(matched, key=lambda item: item.claim_id)


def classify_item(
    *,
    is_main_worktree: bool,
    clean: bool,
    statuses: set[str],
    queued_claims: list[str],
    plus_commits: int,
    minus_commits: int,
    head_ancestor_of_main: bool,
    touches_config_sensitive: bool,
    reasons: list[str],
) -> tuple[str, str, list[str]]:
    if is_main_worktree:
        return "main", "observe_only", reasons
    if statuses & ACTIVE_STATUSES:
        reasons.append("active_claim")
        return "blocked_active", "do_not_touch", reasons
    if touches_config_sensitive:
        reasons.append("config_sensitive_paths")
    if not clean:
        reasons.append("dirty_worktree")
        return "review_required", "inspect_before_action", reasons
    if queued_claims or statuses & READY_STATUSES:
        if touches_config_sensitive:
            return "review_required", "manual_config_review", reasons
        if plus_commits > 0:
            reasons.append("ready_claim_with_unique_commits")
            return "merge_ready", "merge_after_final_review", reasons
        if minus_commits > 0 or head_ancestor_of_main:
            reasons.append("ready_claim_already_in_main")
            return "cleanup_ready", "close_claim_and_remove_worktree", reasons
        reasons.append("ready_claim_without_unique_diff")
        return "review_required", "inspect_claim_state", reasons
    if plus_commits > 0:
        reasons.append("unique_commits_without_ready_claim")
        return "review_required", "decide_claim_or_merge_path", reasons
    if minus_commits > 0 or head_ancestor_of_main:
        reasons.append("no_unique_commits")
        return "cleanup_ready", "remove_worktree_if_no_claim_needed", reasons
    reasons.append("unclassified_clean_worktree")
    return "review_required", "inspect_manually", reasons


def build_report(
    root: Path,
    registry_path: Path | None = None,
    main_branch: str = "main",
    operator_config: Path | None = None,
) -> IntegrationAuditReport:
    root = root.resolve()
    operator_config = operator_config or Path.home() / "Documents" / "Vibelution" / "config" / "config.toml"
    main_head = run_git(root, "rev-parse", main_branch, check=True).stdout.strip()
    worktrees = parse_worktrees(root)
    main_worktree = next(
        (
            Path(raw["worktree"])
            for raw in worktrees
            if normalize_branch(raw.get("branch", "")) == main_branch and raw.get("worktree")
        ),
        root,
    ).resolve()
    registry_path = registry_path or main_worktree / ".docs" / "project-memory" / "agent-registry.json"
    claims, queue_claim_ids = load_registry(registry_path)
    claims_by_worktree, claims_by_branch = claim_maps(claims)
    items: list[WorktreeAuditItem] = []

    for raw in worktrees:
        wt_path = Path(raw.get("worktree", ""))
        branch = normalize_branch(raw.get("branch", ""))
        head = raw.get("HEAD", "")
        is_main_worktree = branch == main_branch and norm_path_key(wt_path) == norm_path_key(main_worktree)
        exists = wt_path.exists()
        status_result = run_git(wt_path, "status", "--porcelain=v1") if exists else GitResult(1, "", "")
        dirty_paths = parse_dirty_paths(status_result.stdout)
        clean = exists and status_result.code == 0 and not dirty_paths
        matched_claims = matching_claims(wt_path, branch, claims_by_worktree, claims_by_branch)
        claim_ids = [claim.claim_id for claim in matched_claims]
        statuses = {claim.status for claim in matched_claims if claim.status}
        ready_claim_ids = [
            claim.claim_id for claim in matched_claims if claim.status in READY_STATUSES
        ]
        queued_for_item = [claim_id for claim_id in claim_ids if claim_id in queue_claim_ids]
        plus_commits, minus_commits, cherry_reasons = count_cherry(root, main_branch, branch)
        branch_paths = diff_paths(root, main_branch, branch)
        claim_paths = [path for claim in matched_claims for path in claim.changed_files]
        touched_paths = sorted(set(branch_paths + dirty_paths + claim_paths))
        touches_config_sensitive = any(
            path_is_config_sensitive(path, operator_config) for path in touched_paths
        )
        head_ancestor_of_main = False
        main_ancestor_of_head = False
        if not is_main_worktree and head:
            head_ancestor_of_main = is_ancestor(root, head, main_branch)
            main_ancestor_of_head = is_ancestor(root, main_branch, head)
        reasons = list(cherry_reasons)
        decision, suggested_action, reasons = classify_item(
            is_main_worktree=is_main_worktree,
            clean=clean,
            statuses=statuses,
            queued_claims=queued_for_item,
            plus_commits=plus_commits,
            minus_commits=minus_commits,
            head_ancestor_of_main=head_ancestor_of_main,
            touches_config_sensitive=touches_config_sensitive,
            reasons=reasons,
        )
        risk_level, risk_score, risk_reasons = score_risk(
            decision=decision,
            clean=clean,
            plus_commits=plus_commits,
            touches_config_sensitive=touches_config_sensitive,
            touched_paths=touched_paths,
            reasons=reasons,
        )
        merge_method = choose_merge_method(
            decision=decision,
            clean=clean,
            plus_commits=plus_commits,
            main_ancestor_of_head=main_ancestor_of_head,
        )
        recommended_validations = recommend_validations(
            touched_paths=touched_paths,
            decision=decision,
            touches_config_sensitive=touches_config_sensitive,
        )
        items.append(
            WorktreeAuditItem(
                worktree=str(wt_path),
                branch=branch,
                head=head,
                is_main=is_main_worktree,
                exists=exists,
                clean=clean,
                dirty_paths=dirty_paths,
                touched_paths=touched_paths,
                claim_ids=claim_ids,
                claim_statuses=sorted(statuses),
                ready_claim_ids=ready_claim_ids,
                queued_claim_ids=queued_for_item,
                plus_commits=plus_commits,
                minus_commits=minus_commits,
                head_ancestor_of_main=head_ancestor_of_main,
                main_ancestor_of_head=main_ancestor_of_head,
                touches_config_sensitive=touches_config_sensitive,
                decision=decision,
                suggested_action=suggested_action,
                reasons=reasons,
                risk_level=risk_level,
                risk_score=risk_score,
                risk_reasons=risk_reasons,
                merge_method=merge_method,
                recommended_validations=recommended_validations,
            )
        )

    duplicate_ready_groups = build_duplicate_ready_groups(items, queue_claim_ids)
    summary: dict[str, int] = {}
    for item in items:
        summary[item.decision] = summary.get(item.decision, 0) + 1
    return IntegrationAuditReport(
        root=str(main_worktree),
        main_branch=main_branch,
        main_head=main_head,
        operator_config=str(operator_config),
        merge_queue_claim_ids=queue_claim_ids,
        duplicate_ready_groups=duplicate_ready_groups,
        items=sorted(items, key=lambda item: (item.decision, item.branch, item.worktree)),
        summary=dict(sorted(summary.items())),
    )


def build_duplicate_ready_groups(
    items: Iterable[WorktreeAuditItem], queue_claim_ids: list[str]
) -> list[DuplicateReadyGroup]:
    queued = set(queue_claim_ids)
    groups: dict[tuple[str, str, str], set[str]] = {}
    for item in items:
        ready_claims = [claim_id for claim_id in item.claim_ids if claim_id in queued]
        ready_claims.extend(claim_id for claim_id in item.ready_claim_ids if claim_id not in ready_claims)
        if len(ready_claims) < 2:
            continue
        key = (item.head, item.worktree, item.branch)
        groups.setdefault(key, set()).update(ready_claims)
    return [
        DuplicateReadyGroup(head=head, worktree=worktree, branch=branch, claim_ids=sorted(ids))
        for (head, worktree, branch), ids in sorted(groups.items())
        if len(ids) > 1
    ]


def build_stash_report(root: Path, limit: int | None = None) -> StashAuditReport:
    root = root.resolve()
    stashes = list_stashes(root)
    if limit is not None and limit >= 0:
        stashes = stashes[:limit]
    items: list[StashAuditItem] = []
    summary: dict[str, int] = {}
    for ref, message in stashes:
        paths = stash_paths(root, ref)
        kind, suggested_action, reasons, touches_protected, touches_hot = classify_stash_item(paths)
        summary[kind] = summary.get(kind, 0) + 1
        items.append(
            StashAuditItem(
                ref=ref,
                summary=message,
                file_count=len(paths),
                touched_paths=paths,
                sample_paths=paths[:5],
                touches_protected=touches_protected,
                touches_hot=touches_hot,
                kind=kind,
                suggested_action=suggested_action,
                reasons=reasons,
            )
        )
    return StashAuditReport(
        root=str(root),
        items=items,
        summary=dict(sorted(summary.items())),
    )


def report_to_json(report: IntegrationAuditReport | StashAuditReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True)


def format_report(report: IntegrationAuditReport) -> str:
    lines = [
        f"Integration audit for {report.root}",
        f"main: {report.main_branch} @ {report.main_head[:12]}",
        f"operator config: {report.operator_config}",
        "",
        "Summary:",
    ]
    for decision, count in report.summary.items():
        lines.append(f"  {decision}: {count}")
    lines.append(f"  merge_queue_claims: {len(report.merge_queue_claim_ids)}")
    lines.append(f"  duplicate_ready_groups: {len(report.duplicate_ready_groups)}")
    if report.duplicate_ready_groups:
        lines.append("")
        lines.append("Duplicate ready groups:")
        for group in report.duplicate_ready_groups:
            lines.append(
                f"  {group.branch} {group.head[:12]} claims={','.join(group.claim_ids)}"
            )
    for decision in sorted(report.summary):
        selected = [item for item in report.items if item.decision == decision]
        if not selected:
            continue
        lines.append("")
        lines.append(f"{decision}:")
        for item in selected:
            flag = " config" if item.touches_config_sensitive else ""
            claims = ",".join(item.claim_ids) if item.claim_ids else "-"
            reasons = ",".join(item.reasons) if item.reasons else "-"
            lines.append(
                f"  {item.branch or '(detached)'} @ {item.head[:12]} clean={item.clean}"
                f" plus={item.plus_commits} minus={item.minus_commits}{flag}"
            )
            lines.append(f"    worktree: {item.worktree}")
            lines.append(f"    claims: {claims}")
            lines.append(f"    action: {item.suggested_action}; reasons: {reasons}")
            lines.append(
                f"    risk: {item.risk_level} score={item.risk_score}; "
                f"merge_method: {item.merge_method}"
            )
            if item.recommended_validations:
                lines.append(
                    f"    validations: {' | '.join(item.recommended_validations)}"
                )
    return "\n".join(lines)


def format_merge_plan(report: IntegrationAuditReport) -> str:
    lines = [
        "READ-ONLY merge plan",
        f"root: {report.root}",
        f"main: {report.main_branch} @ {report.main_head[:12]}",
        f"operator config source of truth: {report.operator_config}",
        "",
        "This plan does not merge, delete, or edit config files.",
    ]
    if report.duplicate_ready_groups:
        lines.append("")
        lines.append("Duplicate ready claims:")
        for group in report.duplicate_ready_groups:
            lines.append(
                f"  {group.branch} @ {group.head[:12]} claims={','.join(group.claim_ids)}"
            )
    merge_ready = sorted(
        [item for item in report.items if item.decision == "merge_ready"],
        key=lambda item: (item.risk_score, item.branch, item.worktree),
    )
    lines.append("")
    lines.append("Merge candidates:")
    if not merge_ready:
        lines.append("  none")
    for index, item in enumerate(merge_ready, start=1):
        claims = ",".join(item.claim_ids) if item.claim_ids else "-"
        reasons = ",".join(item.risk_reasons or item.reasons) if (item.risk_reasons or item.reasons) else "-"
        validations = item.recommended_validations or ["git diff --check"]
        lines.append(
            f"  {index}. {item.branch} @ {item.head[:12]} "
            f"risk={item.risk_level}/{item.risk_score} method={item.merge_method}"
        )
        lines.append(f"     worktree: {item.worktree}")
        lines.append(f"     claims: {claims}")
        lines.append(f"     reasons: {reasons}")
        lines.append(f"     validations: {' | '.join(validations)}")
    review_required = sorted(
        [item for item in report.items if item.decision == "review_required"],
        key=lambda item: (-item.risk_score, item.branch, item.worktree),
    )
    lines.append("")
    lines.append("Manual review queue:")
    if not review_required:
        lines.append("  none")
    for item in review_required:
        claims = ",".join(item.claim_ids) if item.claim_ids else "-"
        reasons = ",".join(item.risk_reasons or item.reasons) if (item.risk_reasons or item.reasons) else "-"
        lines.append(
            f"  {item.branch} @ {item.head[:12]} "
            f"risk={item.risk_level}/{item.risk_score} action={item.suggested_action}"
        )
        lines.append(f"     claims: {claims}; reasons: {reasons}")
        if item.recommended_validations:
            lines.append(f"     validations: {' | '.join(item.recommended_validations)}")
    blocked = [item for item in report.items if item.decision == "blocked_active"]
    cleanup_ready = [item for item in report.items if item.decision == "cleanup_ready"]
    lines.append("")
    lines.append(f"Blocked active worktrees: {len(blocked)}")
    for item in sorted(blocked, key=lambda item: (item.branch, item.worktree)):
        claims = ",".join(item.claim_ids) if item.claim_ids else "-"
        lines.append(f"  {item.branch} @ {item.head[:12]} claims={claims}")
    lines.append("")
    lines.append(f"Cleanup-ready worktrees: {len(cleanup_ready)}")
    for item in sorted(cleanup_ready, key=lambda item: (item.branch, item.worktree))[:10]:
        lines.append(f"  {item.branch} @ {item.head[:12]} method={item.merge_method}")
    if len(cleanup_ready) > 10:
        lines.append(f"  ... {len(cleanup_ready) - 10} more")
    return "\n".join(lines)


def format_stash_plan(report: StashAuditReport) -> str:
    lines = [
        "READ-ONLY stash governance plan",
        f"root: {report.root}",
        "",
        "This plan does not apply, drop, or mutate stashes.",
        "Use it to decide which snapshots are absorbed, risky, or worth salvaging in a separate round.",
        "",
        "Summary:",
    ]
    if not report.summary:
        lines.append("  none")
    for kind, count in report.summary.items():
        lines.append(f"  {kind}: {count}")
    if report.items:
        lines.append("")
        lines.append("Recent stashes:")
    for item in report.items:
        flags: list[str] = []
        if item.touches_protected:
            flags.append("protected")
        if item.touches_hot:
            flags.append("hot")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        lines.append(
            f"  {item.ref} kind={item.kind} files={item.file_count}{flag_text}"
        )
        lines.append(f"    summary: {item.summary}")
        if item.sample_paths:
            lines.append(f"    sample: {', '.join(item.sample_paths)}")
        lines.append(f"    action: {item.suggested_action}")
        if item.reasons:
            lines.append(f"    reasons: {', '.join(item.reasons)}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit for Vibelution worktree integration decisions."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--main-branch", default="main")
    parser.add_argument(
        "--operator-config",
        type=Path,
        default=Path.home() / "Documents" / "Vibelution" / "config" / "config.toml",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--merge-plan",
        action="store_true",
        help="Emit a read-only prioritized merge plan.",
    )
    parser.add_argument(
        "--stash-plan",
        action="store_true",
        help="Emit a read-only stash governance plan.",
    )
    parser.add_argument(
        "--stash-limit",
        type=int,
        default=24,
        help="Maximum number of most-recent stashes to inspect for --stash-plan.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.stash_plan:
        report = build_stash_report(root=args.root, limit=args.stash_limit)
        if args.json:
            output = report_to_json(report)
        else:
            output = format_stash_plan(report)
    else:
        report = build_report(
            root=args.root,
            registry_path=args.registry,
            main_branch=args.main_branch,
            operator_config=args.operator_config,
        )
        if args.json:
            output = report_to_json(report)
        elif args.merge_plan:
            output = format_merge_plan(report)
        else:
            output = format_report(report)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
