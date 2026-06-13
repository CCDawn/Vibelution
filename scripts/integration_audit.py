from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


CONFIG_SENSITIVE_EXACT = {
    "config.toml",
    "config.example.toml",
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
    touches_config_sensitive: bool
    decision: str
    suggested_action: str
    reasons: list[str]


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
    if basename in CONFIG_SENSITIVE_EXACT:
        return True
    if norm_path_key(path) == norm_path_key(operator_config):
        return True
    return any(fragment.casefold() in normalized for fragment in CONFIG_SENSITIVE_FRAGMENTS)


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
        if not is_main_worktree and head:
            head_ancestor_of_main = is_ancestor(root, head, main_branch)
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
                touches_config_sensitive=touches_config_sensitive,
                decision=decision,
                suggested_action=suggested_action,
                reasons=reasons,
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


def report_to_json(report: IntegrationAuditReport) -> str:
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        root=args.root,
        registry_path=args.registry,
        main_branch=args.main_branch,
        operator_config=args.operator_config,
    )
    output = report_to_json(report) if args.json else format_report(report)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
