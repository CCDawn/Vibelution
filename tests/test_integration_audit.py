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
