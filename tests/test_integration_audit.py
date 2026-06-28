import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import integration_audit as audit  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def init_repo(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test Agent")
    git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-m", "base")
    return path


def write_registry(root: Path, claims: dict, merge_queue: list) -> Path:
    registry = root / "registry.json"
    registry.write_text(
        json.dumps({"workClaims": claims, "mergeQueue": merge_queue}, ensure_ascii=False),
        encoding="utf-8",
    )
    return registry


def add_worktree(root: Path, name: str, branch: str) -> Path:
    worktree = root.parent / name
    git(root, "worktree", "add", "-b", branch, str(worktree))
    git(worktree, "config", "user.name", "Test Agent")
    git(worktree, "config", "user.email", "test@example.com")
    return worktree


def commit_file(worktree: Path, file_name: str, content: str, message: str) -> str:
    path = worktree / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(worktree, "add", file_name)
    git(worktree, "commit", "-m", message)
    return git(worktree, "rev-parse", "HEAD")


def commit_files(worktree: Path, files: dict[str, str], message: str) -> str:
    for file_name, content in files.items():
        path = worktree / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(worktree, "add", ".")
    git(worktree, "commit", "-m", message)
    return git(worktree, "rev-parse", "HEAD")


def create_stash(
    worktree: Path,
    *,
    message: str,
    tracked_changes: dict[str, str] | None = None,
    untracked_changes: dict[str, str] | None = None,
) -> None:
    for file_name, content in (tracked_changes or {}).items():
        path = worktree / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for file_name, content in (untracked_changes or {}).items():
        path = worktree / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    args = ["stash", "push", "-m", message]
    if untracked_changes:
        args.insert(2, "--include-untracked")
    git(worktree, *args)


def item_by_branch(report: audit.IntegrationAuditReport, branch: str) -> audit.WorktreeAuditItem:
    matches = [item for item in report.items if item.branch == branch]
    assert len(matches) == 1
    return matches[0]


def test_ready_claim_with_unique_commit_is_merge_ready(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "ready-wt", "codex/ready")
    head = commit_file(worktree, "feature.txt", "feature\n", "feature")
    registry = write_registry(
        root,
        {
            "claim-a": {
                "status": "ready_for_merge",
                "branch": "codex/ready",
                "worktree": str(worktree),
                "changedFiles": ["feature.txt"],
            },
            "claim-b": {
                "status": "ready_for_merge",
                "branch": "codex/ready",
                "worktree": str(worktree),
                "changedFiles": ["feature.txt"],
            },
        },
        ["claim-a", "claim-b"],
    )

    report = audit.build_report(root, registry_path=registry)
    item = item_by_branch(report, "codex/ready")

    assert item.head == head
    assert item.decision == "merge_ready"
    assert item.suggested_action == "merge_after_final_review"
    assert item.plus_commits == 1
    assert item.main_ancestor_of_head is True
    assert item.merge_method == "fast_forward"
    assert item.risk_level in {"low", "medium"}
    assert len(report.duplicate_ready_groups) == 1
    assert report.duplicate_ready_groups[0].claim_ids == ["claim-a", "claim-b"]


def test_already_merged_clean_worktree_is_cleanup_ready(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "merged-wt", "codex/merged")
    commit_file(worktree, "merged.txt", "merged\n", "merged")
    git(root, "merge", "--ff-only", "codex/merged")
    registry = write_registry(
        root,
        {
            "claim-merged": {
                "status": "merged_to_main",
                "branch": "codex/merged",
                "worktree": str(worktree),
                "changedFiles": ["merged.txt"],
            }
        },
        [],
    )

    report = audit.build_report(root, registry_path=registry)
    item = item_by_branch(report, "codex/merged")

    assert item.decision == "cleanup_ready"
    assert item.plus_commits == 0
    assert item.head_ancestor_of_main is True
    assert item.merge_method == "not_applicable_cleanup_only"


def test_active_claim_blocks_worktree_even_when_dirty(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "active-wt", "codex/active")
    (worktree / "scratch.txt").write_text("dirty\n", encoding="utf-8")
    registry = write_registry(
        root,
        {
            "claim-active": {
                "status": "claimed",
                "branch": "codex/active",
                "worktree": str(worktree),
                "changedFiles": ["scratch.txt"],
            }
        },
        [],
    )

    report = audit.build_report(root, registry_path=registry)
    item = item_by_branch(report, "codex/active")

    assert item.decision == "blocked_active"
    assert item.suggested_action == "do_not_touch"
    assert item.clean is False
    assert "active_claim" in item.reasons
    assert item.risk_level == "blocked"
    assert item.merge_method == "blocked_active_claim"


def test_config_sensitive_unique_commit_requires_manual_review(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "config-wt", "codex/config")
    commit_file(worktree, "config.toml", "model = 'x'\n", "touch config")
    registry = write_registry(root, {}, [])

    report = audit.build_report(root, registry_path=registry)
    item = item_by_branch(report, "codex/config")

    assert item.decision == "review_required"
    assert item.touches_config_sensitive is True
    assert "config_sensitive_paths" in item.reasons
    assert item.risk_level == "high"
    assert any("config.toml" in command for command in item.recommended_validations)


def test_external_operator_config_claim_path_is_config_sensitive(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "external-config-wt", "codex/external-config")
    operator_config = tmp_path / "Documents" / "Vibelution" / "config" / "config.toml"
    registry = write_registry(
        root,
        {
            "claim-config": {
                "status": "ready_for_merge",
                "branch": "codex/external-config",
                "worktree": str(worktree),
                "changedFiles": [str(operator_config)],
            }
        },
        ["claim-config"],
    )

    report = audit.build_report(root, registry_path=registry, operator_config=operator_config)
    item = item_by_branch(report, "codex/external-config")

    assert item.touches_config_sensitive is True
    assert item.decision == "review_required"
    assert item.suggested_action == "manual_config_review"
    assert item.merge_method == "manual_review"


def test_report_uses_main_worktree_registry_when_started_from_task_worktree(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "task-wt", "codex/task")
    commit_file(worktree, "task.txt", "task\n", "task")
    registry = root / ".docs" / "project-memory" / "agent-registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "workClaims": {
                    "claim-task": {
                        "status": "ready_for_merge",
                        "branch": "codex/task",
                        "worktree": str(worktree),
                        "changedFiles": ["task.txt"],
                    }
                },
                "mergeQueue": ["claim-task"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = audit.build_report(worktree)
    main_item = item_by_branch(report, "main")
    task_item = item_by_branch(report, "codex/task")

    assert report.root == str(root.resolve())
    assert main_item.decision == "main"
    assert task_item.claim_ids == ["claim-task"]
    assert task_item.decision == "merge_ready"


def test_ready_branch_recommends_cherry_pick_when_main_advanced(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "feature-wt", "codex/feature")
    commit_file(worktree, "feature.txt", "feature\n", "feature")
    commit_file(root, "main.txt", "main advanced\n", "advance main")
    registry = write_registry(
        root,
        {
            "claim-feature": {
                "status": "ready_for_merge",
                "branch": "codex/feature",
                "worktree": str(worktree),
                "changedFiles": ["feature.txt"],
            }
        },
        ["claim-feature"],
    )

    report = audit.build_report(root, registry_path=registry)
    item = item_by_branch(report, "codex/feature")

    assert item.decision == "merge_ready"
    assert item.main_ancestor_of_head is False
    assert item.merge_method == "cherry_pick"


def test_frontend_route_paths_recommend_targeted_validation(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    worktree = add_worktree(root, "teams-wt", "codex/teams")
    commit_file(
        worktree,
        "web/src/routes/TeamsRoute.tsx",
        "export const TeamsRoute = null\n",
        "teams route",
    )
    registry = write_registry(
        root,
        {
            "claim-teams": {
                "status": "ready_for_merge",
                "branch": "codex/teams",
                "worktree": str(worktree),
                "changedFiles": ["web/src/routes/TeamsRoute.tsx"],
            }
        },
        ["claim-teams"],
    )

    report = audit.build_report(root, registry_path=registry)
    item = item_by_branch(report, "codex/teams")

    assert item.decision == "merge_ready"
    assert "npm --prefix web run test -- TeamsRoute.layout.test.ts" in item.recommended_validations
    assert "npm --prefix web run build" in item.recommended_validations
    assert "frontend_surface" in item.risk_reasons


def test_merge_plan_is_read_only_and_prioritized(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    ready_worktree = add_worktree(root, "ready-wt", "codex/ready")
    commit_file(ready_worktree, "feature.txt", "feature\n", "feature")
    config_worktree = add_worktree(root, "config-wt", "codex/config")
    commit_file(config_worktree, "config.toml", "model = 'x'\n", "config")
    registry = write_registry(
        root,
        {
            "claim-ready": {
                "status": "ready_for_merge",
                "branch": "codex/ready",
                "worktree": str(ready_worktree),
                "changedFiles": ["feature.txt"],
            },
            "claim-config": {
                "status": "ready_for_merge",
                "branch": "codex/config",
                "worktree": str(config_worktree),
                "changedFiles": ["config.toml"],
            },
        },
        ["claim-ready", "claim-config"],
    )

    report = audit.build_report(root, registry_path=registry)
    plan = audit.format_merge_plan(report)

    assert "READ-ONLY merge plan" in plan
    assert "does not merge, delete, or edit config files" in plan
    assert "codex/ready" in plan
    assert "method=fast_forward" in plan
    assert "codex/config" in plan
    assert "manual: review config boundary" in plan


def test_build_stash_report_classifies_protected_test_only_and_untracked_entries(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(
        root,
        {
            "tests/test_sample.py": "def test_sample():\n    assert True\n",
            "config.toml": "model = 'base'\n",
            "notes.txt": "base\n",
        },
        "seed files",
    )
    create_stash(
        root,
        message="test-only stash",
        tracked_changes={"tests/test_sample.py": "def test_sample():\n    assert False\n"},
    )
    create_stash(
        root,
        message="config stash",
        tracked_changes={"config.toml": "model = 'changed'\n"},
    )
    create_stash(
        root,
        message="untracked stash",
        untracked_changes={"scratch/untracked.txt": "temp\n"},
    )

    report = audit.build_stash_report(root, limit=3)

    assert report.summary == {
        "empty_or_untracked_only": 1,
        "protected_risk": 1,
        "test_only": 1,
    }
    assert report.items[0].summary == "On main: untracked stash"
    assert report.items[0].kind == "empty_or_untracked_only"
    assert report.items[0].suggested_action == "inspect_untracked_payload_before_drop"
    assert report.items[1].kind == "protected_risk"
    assert report.items[1].touches_protected is True
    assert report.items[1].suggested_action == "retain_until_manual_diff_review"
    assert report.items[2].kind == "test_only"
    assert report.items[2].suggested_action == "compare_with_main_then_drop_if_absorbed"


def test_build_stash_report_marks_hot_and_broad_snapshots(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(
        root,
        {
            "DEVELOPMENT_STANDARD.md": "base\n",
            "core/a.py": "A = 1\n",
            "core/b.py": "B = 1\n",
            "core/c.py": "C = 1\n",
            "core/d.py": "D = 1\n",
            "core/e.py": "E = 1\n",
            "core/f.py": "F = 1\n",
        },
        "seed governance files",
    )
    create_stash(
        root,
        message="hot stash",
        tracked_changes={"DEVELOPMENT_STANDARD.md": "changed\n"},
    )
    create_stash(
        root,
        message="broad stash",
        tracked_changes={
            "core/a.py": "A = 2\n",
            "core/b.py": "B = 2\n",
            "core/c.py": "C = 2\n",
            "core/d.py": "D = 2\n",
            "core/e.py": "E = 2\n",
            "core/f.py": "F = 2\n",
        },
    )

    report = audit.build_stash_report(root, limit=2)

    assert report.summary == {"broad_snapshot": 1, "hot_snapshot": 1}
    assert report.items[0].kind == "broad_snapshot"
    assert report.items[0].suggested_action == "retain_as_history_do_not_reapply_blindly"
    assert report.items[1].kind == "hot_snapshot"
    assert report.items[1].touches_hot is True
    assert report.items[1].suggested_action == "manual_scope_review"


def test_format_stash_plan_is_read_only_and_grouped(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(
        root,
        {
            "tests/test_sample.py": "def test_sample():\n    assert True\n",
            "config.toml": "model = 'base'\n",
        },
        "seed files",
    )
    create_stash(
        root,
        message="test-only stash",
        tracked_changes={"tests/test_sample.py": "def test_sample():\n    assert False\n"},
    )
    create_stash(
        root,
        message="config stash",
        tracked_changes={"config.toml": "model = 'changed'\n"},
    )

    report = audit.build_stash_report(root, limit=2)
    plan = audit.format_stash_plan(report)

    assert "READ-ONLY stash governance plan" in plan
    assert "does not apply, drop, or mutate stashes" in plan
    assert "protected_risk: 1" in plan
    assert "test_only: 1" in plan
    assert "retain_until_manual_diff_review" in plan
    assert "compare_with_main_then_drop_if_absorbed" in plan


def test_build_stash_report_treats_package_lock_as_protected(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(
        root,
        {
            "web/package-lock.json": "{\n  \"name\": \"repo\"\n}\n",
        },
        "seed package lock",
    )
    create_stash(
        root,
        message="package lock stash",
        tracked_changes={"web/package-lock.json": "{\n  \"name\": \"repo\",\n  \"lockfileVersion\": 3\n}\n"},
    )

    report = audit.build_stash_report(root, limit=1)

    assert report.items[0].kind == "protected_risk"
    assert report.items[0].touches_protected is True


def test_build_stash_report_marks_absorbed_test_only_stash(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(
        root,
        {
            "tests/test_sample.py": "def test_sample():\n    assert True\n",
        },
        "seed test file",
    )
    create_stash(
        root,
        message="absorbed test stash",
        tracked_changes={"tests/test_sample.py": "def test_sample():\n    assert False\n"},
    )
    (root / "tests" / "test_sample.py").write_text(
        "def test_sample():\n    assert False\n",
        encoding="utf-8",
    )

    report = audit.build_stash_report(root, limit=1)

    assert report.items[0].kind == "test_only"
    assert report.items[0].absorption_state == "absorbed_by_main"
    assert report.items[0].suggested_action == "drop_after_spot_check"


def test_build_stash_report_exposes_untracked_payload_for_empty_stash(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    create_stash(
        root,
        message="untracked payload stash",
        untracked_changes={"scratch/note.txt": "payload\n"},
    )

    report = audit.build_stash_report(root, limit=1)

    assert report.items[0].kind == "empty_or_untracked_only"
    assert report.items[0].untracked_paths == ["scratch/note.txt"]
    assert report.items[0].suggested_action == "inspect_untracked_payload_before_drop"


def test_build_stash_report_marks_expected_disposable_untracked_probe(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    create_stash(
        root,
        message="safe modify probe stash",
        untracked_changes={
            "tests/harness_safe_modify_probe.py": (
                'HARNESS_SAFE_MODIFY_MARKER = "HARNESS_SAFE_MODIFY_MARKER"\n\n'
                "\n"
                "def probe_marker() -> str:\n"
                "    return HARNESS_SAFE_MODIFY_MARKER\n"
            )
        },
    )

    report = audit.build_stash_report(root, limit=1)
    item = report.items[0]

    assert item.kind == "empty_or_untracked_only"
    assert item.absorption_state == "expected_disposable_artifact"
    assert item.untracked_file_states == {
        "tests/harness_safe_modify_probe.py": "expected_artifact_missing_in_main",
    }
    assert item.suggested_action == "drop_expected_disposable_artifact"
    assert "expected_disposable_artifact" in item.reasons


def test_format_stash_plan_shows_absorption_and_untracked_paths(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(
        root,
        {
            "tests/test_sample.py": "def test_sample():\n    assert True\n",
        },
        "seed test file",
    )
    create_stash(
        root,
        message="absorbed test stash",
        tracked_changes={"tests/test_sample.py": "def test_sample():\n    assert False\n"},
    )
    commit_files(
        root,
        {
            "tests/test_sample.py": "def test_sample():\n    assert False\n",
        },
        "absorb stashed test change into main",
    )
    create_stash(
        root,
        message="untracked payload stash",
        untracked_changes={"scratch/note.txt": "payload\n"},
    )

    report = audit.build_stash_report(root, limit=2)
    plan = audit.format_stash_plan(report)

    assert "absorbed_by_main" in plan
    assert "untracked: scratch/note.txt" in plan


def test_build_stash_report_classifies_untracked_payload_file_states(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    create_stash(
        root,
        message="mixed untracked payload",
        untracked_changes={
            "scratch/absorbed.txt": "same\n",
            "scratch/diverged.txt": "stash-version\n",
            "scratch/missing.txt": "only-in-stash\n",
        },
    )
    commit_files(
        root,
        {
            "scratch/absorbed.txt": "same\n",
            "scratch/diverged.txt": "main-version\n",
        },
        "add absorbed and diverged files",
    )

    report = audit.build_stash_report(root, limit=1)
    item = report.items[0]

    assert item.kind == "empty_or_untracked_only"
    assert item.absorption_state == "partially_absorbed"
    assert item.untracked_file_states == {
        "scratch/absorbed.txt": "absorbed_by_main",
        "scratch/diverged.txt": "diverged_in_main",
        "scratch/missing.txt": "missing_in_main",
    }


def test_format_stash_plan_shows_untracked_file_states(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    create_stash(
        root,
        message="mixed untracked payload",
        untracked_changes={
            "scratch/absorbed.txt": "same\n",
            "scratch/diverged.txt": "stash-version\n",
            "scratch/missing.txt": "only-in-stash\n",
        },
    )
    commit_files(
        root,
        {
            "scratch/absorbed.txt": "same\n",
            "scratch/diverged.txt": "main-version\n",
        },
        "add absorbed and diverged files",
    )

    report = audit.build_stash_report(root, limit=1)
    plan = audit.format_stash_plan(report)

    assert "untracked-state: scratch/absorbed.txt=absorbed_by_main" in plan
    assert "scratch/diverged.txt=diverged_in_main" in plan
    assert "scratch/missing.txt=missing_in_main" in plan


def test_format_stash_plan_shows_expected_disposable_untracked_probe(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    create_stash(
        root,
        message="safe modify probe stash",
        untracked_changes={
            "tests/harness_safe_modify_probe.py": (
                'HARNESS_SAFE_MODIFY_MARKER = "HARNESS_SAFE_MODIFY_MARKER"\n\n'
                "\n"
                "def probe_marker() -> str:\n"
                "    return HARNESS_SAFE_MODIFY_MARKER\n"
            )
        },
    )

    report = audit.build_stash_report(root, limit=1)
    plan = audit.format_stash_plan(report)

    assert "expected_disposable_artifact" in plan
    assert "tests/harness_safe_modify_probe.py=expected_artifact_missing_in_main" in plan
    assert "drop_expected_disposable_artifact" in plan
