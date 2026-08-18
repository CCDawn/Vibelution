"""R0/R1 source-boundary tests for Challenge Cup tracked resources."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from core.research.competition import source_boundary
from core.research.competition.source_boundary import (
    SourceBoundaryError,
    SourceBoundaryPolicy,
    build_source_manifest,
    evaluate_clean_clone,
    evaluate_source_integrity,
    git_show_bytes,
    verify_manifest_on_tree,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "challenge_cup_submission_source_manifest.schema.json"


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init")
    git(root, "config", "user.email", "source-boundary@example.invalid")
    git(root, "config", "user.name", "Source Boundary Test")
    return root


def _commit_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        git(root, "add", rel)
    git(root, "commit", "-m", "source-boundary fixture")


def _policy(*required: str) -> SourceBoundaryPolicy:
    return SourceBoundaryPolicy(
        include_globs=required + ("experiments/challenge_cup_gpu_operator/**",),
        required_paths=required,
        r1_pytest_targets=(),
    )


def test_verify_manifest_fails_on_missing_file_and_hash_drift(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tracked = tree / "core" / "research" / "competition" / "resources.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("ok\n", encoding="utf-8")
    manifest = {
        "entries": [
            {
                "path": "core/research/competition/resources.py",
                "sha256": "A" * 64,
                "sizeBytes": 3,
            }
        ]
    }
    assert any("hash mismatch" in item for item in verify_manifest_on_tree(tree, manifest))
    assert any(
        "clone missing" in item
        for item in verify_manifest_on_tree(tree, {"entries": [{"path": "missing.py"}]})
    )


def test_build_manifest_from_git_ls_files_and_real_hashes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    _commit_tree(
        repo,
        {
            "schemas/challenge_cup_submission_source_manifest.schema.json": schema,
            "core/research/competition/resources.py": "tracked = True\n",
            "experiments/challenge_cup_gpu_operator/NOTICE.md": "# fixture\n",
        },
    )
    policy = _policy(
        "core/research/competition/resources.py",
        "experiments/challenge_cup_gpu_operator/NOTICE.md",
    )
    manifest = build_source_manifest(repo, policy=policy, require_clean=True)
    assert [error.message for error in Draft202012Validator(json.loads(schema)).iter_errors(manifest)] == []
    paths = {item["path"] for item in manifest["entries"]}
    assert "core/research/competition/resources.py" in paths
    assert "experiments/challenge_cup_gpu_operator/NOTICE.md" in paths
    resources = next(
        item
        for item in manifest["entries"]
        if item["path"] == "core/research/competition/resources.py"
    )
    payload = git_show_bytes(repo, "core/research/competition/resources.py")
    assert resources["sha256"] == hashlib.sha256(payload).hexdigest().upper()


def test_missing_required_path_fails(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit_tree(repo, {"core/research/competition/resources.py": "tracked = True\n"})
    policy = _policy(
        "core/research/competition/resources.py",
        "experiments/challenge_cup_gpu_operator/NOTICE.md",
    )
    with pytest.raises(SourceBoundaryError, match="required path is not tracked"):
        build_source_manifest(repo, policy=policy)


def test_machine_local_path_fails_source_integrity(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit_tree(
        repo,
        {
            "core/research/competition/resources.py": "root = '/Users/administrator/data'\n",
        },
    )
    policy = _policy("core/research/competition/resources.py")
    with pytest.raises(SourceBoundaryError, match="machine-local path"):
        build_source_manifest(repo, policy=policy)


def test_unmanifested_tracked_experiment_file_fails(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit_tree(
        repo,
        {
            "core/research/competition/resources.py": "tracked = True\n",
            "experiments/challenge_cup_gpu_operator/NOTICE.md": "# ok\n",
            "experiments/challenge_cup_gpu_operator/secret.nwb": "nwb",
        },
    )
    policy = SourceBoundaryPolicy(
        include_globs=("core/research/competition/resources.py",),
        required_paths=("core/research/competition/resources.py",),
        r1_pytest_targets=(),
    )
    with pytest.raises(SourceBoundaryError, match="unmanifested tracked experiment file"):
        build_source_manifest(repo, policy=policy)


def test_require_clean_rejects_dirty_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit_tree(repo, {"core/research/competition/resources.py": "tracked = True\n"})
    (repo / "core/research/competition/resources.py").write_text("dirty\n", encoding="utf-8")
    policy = _policy("core/research/competition/resources.py")
    with pytest.raises(SourceBoundaryError, match="working tree is dirty"):
        build_source_manifest(repo, policy=policy, require_clean=True)


def test_evaluate_source_integrity_fails_on_dirty_tree_for_r0(tmp_path: Path) -> None:
    """R0 never reports PASS on a dirty tree, so READY cannot regress."""
    repo = _init_repo(tmp_path / "repo")
    _commit_tree(repo, {"core/research/competition/resources.py": "tracked = True\n"})
    (repo / "core/research/competition/resources.py").write_text("dirty\n", encoding="utf-8")
    report = evaluate_source_integrity(repo, require_clean=True)
    assert report["source_integrity"] == "FAIL"
    assert any("working tree is dirty" in item for item in report["failures"])


def test_manifest_hashes_head_blob_not_dirty_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    _commit_tree(
        repo,
        {
            "schemas/challenge_cup_submission_source_manifest.schema.json": schema,
            "core/research/competition/resources.py": "tracked = True\n",
        },
    )
    policy = _policy("core/research/competition/resources.py")
    committed = hashlib.sha256(b"tracked = True\n").hexdigest().upper()
    (repo / "core/research/competition/resources.py").write_text("dirty worktree\n", encoding="utf-8")
    manifest = build_source_manifest(repo, policy=policy, require_clean=False)
    resources = next(
        item
        for item in manifest["entries"]
        if item["path"] == "core/research/competition/resources.py"
    )
    assert resources["sha256"] == committed
    dest = tmp_path / "clone"
    report = evaluate_clean_clone(
        repo, dest, policy=policy, require_clean=False, run_pytest=False
    )
    assert report["source_integrity"] == "PASS"
    assert report["clean_clone_reproduction"] == "PASS"


def test_clean_clone_passes_then_fails_on_hash_change(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    _commit_tree(
        repo,
        {
            "schemas/challenge_cup_submission_source_manifest.schema.json": schema,
            "core/research/competition/resources.py": "tracked = True\n",
            "experiments/challenge_cup_gpu_operator/NOTICE.md": "# fixture\n",
        },
    )
    policy = _policy(
        "core/research/competition/resources.py",
        "experiments/challenge_cup_gpu_operator/NOTICE.md",
    )
    dest = tmp_path / "clone"
    report = evaluate_clean_clone(
        repo, dest, policy=policy, require_clean=True, run_pytest=False
    )
    assert report["source_integrity"] == "PASS"
    assert report["clean_clone_reproduction"] == "PASS"
    mutated = dest / "core" / "research" / "competition" / "resources.py"
    mutated.write_text("changed\n", encoding="utf-8")
    failures = verify_manifest_on_tree(dest, report["manifest"])
    assert any("hash mismatch" in item for item in failures)


def test_current_repo_source_integrity_uses_git_ls_files() -> None:
    git_marker = ROOT / ".git"
    if not git_marker.exists():
        pytest.skip("R1 archive clone has no git metadata")
    report = evaluate_source_integrity(ROOT, require_clean=False)
    assert report["failures"] == [], report["failures"]
    assert report["source_integrity"] == "PASS"
    manifest = report["manifest"]
    assert manifest is not None
    paths = {item["path"] for item in manifest["entries"]}
    assert "experiments/challenge_cup_spike_coding/sci096_dandi_probe.py" in paths
    assert "core/research/experiment_adapters/gpu_operator.py" in paths
    assert "core/research/experiment_adapters/neural_spike.py" in paths
    for required in (
        "core/web/services/team_workflow/challenge_cup_dev_controls.py",
        "core/web/routes/team_workflows/challenge_cup_dev_controls.py",
        "core/web/routes/team_workflows/challenge_cup_dev_controls_models.py",
        "web/src/api/teamExperiment.ts",
        "web/src/api/types/challengeCup.ts",
        "web/src/routes/teams/research-workflow/ChallengeMvpProgressPanel.tsx",
    ):
        assert required in paths, required
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert [error.message for error in Draft202012Validator(schema).iter_errors(manifest)] == []


def test_source_boundary_uses_only_core_no_console_helpers() -> None:
    """R1 must never import from scripts/ and must route waitable subprocesses
    through the core no-console helper (no visible console windows)."""
    source = Path(source_boundary.__file__).read_text(encoding="utf-8")
    assert "from scripts" not in source
    assert "import scripts" not in source
    assert "no_window_subprocess_kwargs" not in source
    assert "no_console_subprocess_kwargs" in source
    run_r1_source = source.split("def run_r1_pytest")[1]
    assert "**no_console_subprocess_kwargs()" in run_r1_source
    assert "timeout=R1_PYTEST_TIMEOUT_SECONDS" in run_r1_source


def test_r1_pytest_uses_bounded_timeout_constant() -> None:
    """R1 pytest must run under an explicit, bounded timeout so a hung clone
    never blocks the report indefinitely."""
    timeout = source_boundary.R1_PYTEST_TIMEOUT_SECONDS
    assert isinstance(timeout, (int, float))
    assert 0 < timeout <= 3600


def test_extract_head_archive_converts_git_timeout_to_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0] if args else [], timeout=kwargs.get("timeout", 0)
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SourceBoundaryError, match="git archive timed out"):
        source_boundary.extract_head_archive(tmp_path, tmp_path / "clone")
    assert not list(tmp_path.glob(".challenge-cup-r1-*.tar"))


def test_git_show_bytes_converts_timeout_to_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0] if args else [], timeout=kwargs.get("timeout", 0)
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SourceBoundaryError, match="git show timed out"):
        source_boundary.git_show_bytes(tmp_path, "core/example.py")


def test_r1_archive_extraction_has_member_size_and_time_bounds() -> None:
    assert 0 < source_boundary.R1_ARCHIVE_MAX_MEMBERS <= 100_000
    assert 0 < source_boundary.R1_ARCHIVE_MAX_MEMBER_BYTES <= 50_000_000
    assert 0 < source_boundary.R1_ARCHIVE_MAX_TOTAL_BYTES <= 1_000_000_000
    assert 0 < source_boundary.R1_ARCHIVE_EXTRACT_TIMEOUT_SECONDS <= 300


def test_r1_nested_pytest_excludes_clean_clone_meta_tests() -> None:
    """The R1 clone already proves archive extraction before pytest starts.

    Re-running clean-clone meta tests inside that pytest would create another
    archive pipeline and can deadlock the bounded R1 subprocess on Windows.
    The product/backend contract tests remain in ``R1_PYTEST_TARGETS``.
    """
    excluded = set(source_boundary.R1_NESTED_PYTEST_EXCLUDES)
    assert excluded == {
        "test_manifest_hashes_head_blob_not_dirty_worktree",
        "test_clean_clone_passes_then_fails_on_hash_change",
        "test_current_repo_source_integrity_uses_git_ls_files",
    }
    assert "tests/test_challenge_cup_platform_controls.py" in (
        source_boundary.R1_PYTEST_TARGETS
    )


def test_run_r1_pytest_converts_timeout_to_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = tmp_path / "clone"
    target = "tests/test_dummy.py"
    path = tree / target
    path.parent.mkdir(parents=True)
    path.write_text("def test_ok(): pass\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0] if args else [], timeout=kwargs.get("timeout", 0)
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    failures = source_boundary.run_r1_pytest(tree, python="python", targets=(target,))
    assert failures != []
    assert any("timed out" in item for item in failures)
