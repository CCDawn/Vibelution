from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import local_quality_gate as gate
from tests import select_tests


def test_pre_commit_is_thin_adapter() -> None:
    hook = (gate.PROJECT_ROOT / ".githooks" / "pre-commit").read_text(
        encoding="utf-8"
    )
    assert '"$repo_root/scripts/local_quality_gate.py" commit' in hook
    assert "pytest" not in hook
    assert "ruff" not in hook


def test_pre_commit_self_test_environment_removes_repository_local_git_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "shared/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "shared")
    monkeypatch.setenv("GIT_INDEX_FILE", "shared/.git/index")
    monkeypatch.setenv("UNRELATED_SETTING", "preserved")

    env = gate.git_hook_isolated_environment()

    assert "GIT_DIR" not in env
    assert "GIT_WORK_TREE" not in env
    assert "GIT_INDEX_FILE" not in env
    assert env["UNRELATED_SETTING"] == "preserved"


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_sh_exe() -> Path:
    git_exe = shutil.which("git")
    if not git_exe:
        pytest.skip("Git is required for pre-commit hook tests")
    git_root = Path(git_exe).resolve().parent.parent
    for candidate in (
        git_root / "usr" / "bin" / "sh.exe",
        git_root / "bin" / "sh.exe",
    ):
        if candidate.is_file():
            return candidate
    pytest.skip("Git for Windows sh.exe is required for pre-commit hook tests")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "quality-gate@example.invalid")
    git(tmp_path, "config", "user.name", "Quality Gate Test")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(tmp_path, "add", "seed.txt")
    git(tmp_path, "commit", "-m", "seed")
    return tmp_path


def test_pre_commit_missing_project_python_fails_with_repair_command(
    git_repo: Path,
) -> None:
    hook_dir = git_repo / ".githooks"
    hook_dir.mkdir()
    shutil.copyfile(
        gate.PROJECT_ROOT / ".githooks" / "pre-commit",
        hook_dir / "pre-commit",
    )

    result = subprocess.run(
        [str(_git_sh_exe()), ".githooks/pre-commit"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert (
        "[pre-commit] repair: powershell -ExecutionPolicy Bypass -File "
        "scripts/vibelution_launcher.ps1 -Action repair-deps"
        in result.stderr.splitlines()
    )


def commit_file(root: Path, path: str, content: str, message: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(root, "add", path)
    git(root, "commit", "-m", message)


def active_claim(claim_id: str, scopes: list[str]) -> dict[str, object]:
    return {
        "claims": [
            {
                "id": claim_id,
                "status": "active",
                "scopes": scopes,
            }
        ]
    }


def create_passed_manifest(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    git(git_repo, "branch", "-M", "main")
    commit_file(git_repo, ".gitignore", ".runtime/\n", "ignore gate runtime")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "docs/note.md", "changed\n", "docs change")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["docs/note.md"]),
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed"
    assert result.manifest_path is not None
    return result.manifest_path


def create_recorded_contract_manifest(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    git(git_repo, "branch", "-M", "main")
    commit_file(git_repo, ".gitignore", ".runtime/\n", "ignore gate runtime")
    validated_main_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "scripts/local_quality_gate.py", "VALUE = 1\n", "gate change")
    head_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    files = ["scripts/local_quality_gate.py"]
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", files),
    )
    selection = gate.selected_validation(files)
    raw_commands = list(selection["commands"])
    if gate.GATE_SELF_TEST_COMMAND not in raw_commands:
        raw_commands.append(gate.GATE_SELF_TEST_COMMAND)
    commands = [
        gate.ProcessResult(
            kind="changed-python-ruff",
            argv=[
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                gate.FATAL_RUFF_RULES,
                *files,
            ],
            cwd=str(git_repo.resolve()),
            exit_code=0,
            duration_ms=1,
            status="passed",
        )
    ]
    for raw_command in raw_commands:
        spec = gate.parse_allowed_command(raw_command, git_repo.resolve())
        argv = list(spec.argv)
        if Path(argv[0]) == gate.PROJECT_PYTHON_NAME:
            argv[0] = str((spec.cwd / gate.PROJECT_PYTHON_NAME).resolve())
        commands.append(
            gate.ProcessResult(
                kind=spec.kind,
                argv=argv,
                cwd=str(spec.cwd),
                exit_code=0,
                duration_ms=1,
                status="passed",
            )
        )
    payload = gate.manifest_payload(
        task_id="test-task",
        branch="codex/test-task",
        root=git_repo.resolve(),
        claim_id="claim-test",
        validated_main_sha=validated_main_sha,
        head_sha=head_sha,
        files=files,
        commands=commands,
        checks={
            "worktreeClean": True,
            "claimValid": True,
            "mergePreflight": True,
            "commandsAllowlisted": True,
        },
        outcome="passed",
    )
    return gate.write_manifest(git_repo, "test-task", payload)


def test_commit_mode_lints_staged_blob_instead_of_worktree(git_repo: Path) -> None:
    target = git_repo / "broken.py"
    target.write_text("def broken(:\n", encoding="utf-8")
    git(git_repo, "add", "broken.py")
    target.write_text("def fixed() -> int:\n    return 1\n", encoding="utf-8")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "failed"
    assert result.exit_code == 1
    assert result.commands[0].kind == "diff-check"
    assert result.commands[1].kind == "ruff-staged"
    assert "broken.py" in result.commands[1].failure_summary


def test_commit_mode_lints_non_ascii_staged_python_path(git_repo: Path) -> None:
    target = git_repo / "挑战杯" / "broken.py"
    target.parent.mkdir()
    target.write_text("def broken(:\n", encoding="utf-8")
    git(git_repo, "add", "挑战杯/broken.py")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "failed"
    assert any(command.kind == "ruff-staged" for command in result.commands)


def test_commit_mode_ignores_deleted_python(git_repo: Path) -> None:
    target = git_repo / "removed.py"
    target.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    git(git_repo, "add", "removed.py")
    git(git_repo, "commit", "-m", "add python")
    target.unlink()
    git(git_repo, "add", "removed.py")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "passed"
    assert all(command.kind != "ruff-staged" for command in result.commands)


def test_commit_mode_rejects_partially_staged_gate_definition(git_repo: Path) -> None:
    hook = git_repo / ".githooks" / "pre-commit"
    hook.parent.mkdir()
    hook.write_text("first\n", encoding="utf-8")
    git(git_repo, "add", ".githooks/pre-commit")
    hook.write_text("first\nsecond\n", encoding="utf-8")

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "gate_definition_dirty"
    assert result.exit_code == 1


def test_commit_mode_rejects_staged_gate_definition_deleted_from_worktree(
    git_repo: Path,
) -> None:
    hook = git_repo / ".githooks" / "pre-commit"
    hook.parent.mkdir()
    hook.write_text("first\n", encoding="utf-8")
    git(git_repo, "add", ".githooks/pre-commit")
    hook.unlink()

    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "gate_definition_dirty"
    assert result.exit_code == 1


def test_commit_mode_without_relevant_staged_files_passes(git_repo: Path) -> None:
    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "passed"
    assert result.commands == []


@pytest.mark.parametrize(
    ("command", "kind", "argv_prefix"),
    [
        ("git diff --check", "diff-check", ["git", "diff", "--check"]),
        (
            ".\\.venv\\Scripts\\python.exe -m pytest tests/test_select_tests.py -q",
            "pytest",
            [str(gate.PROJECT_PYTHON_NAME), "-m", "pytest"],
        ),
        (
            ".\\.venv\\Scripts\\python.exe tests/select_tests.py "
            "--changed-file README.md --json",
            "selector",
            [str(gate.PROJECT_PYTHON_NAME), "tests/select_tests.py"],
        ),
        (
            ".\\.venv\\Scripts\\python.exe tests/prompt_debugger.py --suite",
            "prompt-debugger",
            [str(gate.PROJECT_PYTHON_NAME), "tests/prompt_debugger.py"],
        ),
        (
            "node web/node_modules/vitest/vitest.mjs run",
            "web-test",
            ["node", "web/node_modules/vitest/vitest.mjs", "run"],
        ),
        (
            "npm --prefix web run build",
            "web-build",
            ["npm", "--prefix", "web", "run", "build"],
        ),
        (
            "npm --prefix web run check:bundle",
            "bundle-check",
            ["npm", "--prefix", "web", "run", "check:bundle"],
        ),
        (
            "node 挑战杯/build_research_flow_site.mjs",
            "challenge-cup-build",
            ["node", "挑战杯/build_research_flow_site.mjs"],
        ),
    ],
)
def test_parse_allowed_command(
    git_repo: Path,
    command: str,
    kind: str,
    argv_prefix: list[str],
) -> None:
    spec = gate.parse_allowed_command(command, git_repo)

    assert spec.kind == kind
    assert spec.argv[: len(argv_prefix)] == argv_prefix
    assert spec.cwd == git_repo


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher resolution")
def test_materialize_command_resolves_windows_npm_launcher(git_repo: Path) -> None:
    spec = gate.parse_allowed_command("npm --prefix web run build", git_repo)

    materialized = gate.materialize_command(spec)

    assert Path(materialized.argv[0]).name.lower() == "npm.cmd"
    assert materialized.argv[1:] == ["--prefix", "web", "run", "build"]
    assert materialized.cwd == git_repo


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher resolution")
def test_materialize_command_resolves_windowless_vitest_launcher(git_repo: Path) -> None:
    spec = gate.parse_allowed_command(
        "node web/node_modules/vitest/vitest.mjs run src/example.test.ts",
        git_repo,
    )

    materialized = gate.materialize_command(spec)

    assert Path(materialized.argv[0]).name.lower() == "node.exe"
    assert materialized.argv[1:] == [
        "web/node_modules/vitest/vitest.mjs",
        "run",
        "src/example.test.ts",
    ]
    assert all(not argument.lower().endswith((".cmd", ".bat")) for argument in materialized.argv)
    assert materialized.cwd == git_repo


def test_local_quality_gate_matrix_command_matches_self_test_and_allowlist(
    git_repo: Path,
) -> None:
    matrix = select_tests.load_matrix()
    rule = next(rule for rule in matrix["rules"] if rule["id"] == "local-quality-gate")

    assert rule["commands"] == [gate.GATE_SELF_TEST_COMMAND]
    spec = gate.parse_allowed_command(rule["commands"][0], git_repo)
    assert spec.kind == "pytest"
    assert spec.argv == [
        str(gate.PROJECT_PYTHON_NAME),
        "-m",
        "pytest",
        "tests/test_local_quality_gate.py",
        "tests/test_ci_workflow_contract.py",
        "tests/test_environment_doctor.py",
        "tests/test_select_tests.py",
        "-q",
    ]
    assert spec.cwd == git_repo


def test_selected_validation_loads_from_isolated_script_execution(
    git_repo: Path,
) -> None:
    project_python = gate.PROJECT_ROOT / gate.PROJECT_PYTHON_NAME
    script = gate.PROJECT_ROOT / "scripts" / "local_quality_gate.py"
    probe = (
        "import runpy; "
        f"namespace = runpy.run_path({str(script)!r}); "
        "namespace['selected_validation'](['README.md'])"
    )

    result = subprocess.run(
        [str(project_python), "-I", "-c", probe],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "python -c print(1)",
        "git status",
        "npm install",
        "pytest tests",
        "git diff --check; git status",
        "npm --prefix web run test | more",
        "node -e process.exit(0)",
        "pwsh -Command Get-ChildItem",
    ],
)
def test_parse_allowed_command_rejects_arbitrary_or_shell_commands(
    git_repo: Path,
    command: str,
) -> None:
    with pytest.raises(gate.UnsupportedValidationCommand):
        gate.parse_allowed_command(command, git_repo)


def test_execute_command_runs_allowed_argv_without_a_shell(git_repo: Path) -> None:
    spec = gate.parse_allowed_command("git diff --check", git_repo)

    result = gate.execute_command(spec)

    assert result.kind == "diff-check"
    assert result.argv == ["git", "diff", "--check"]
    assert result.cwd == str(git_repo)
    assert result.status == "passed"


def test_main_worktree_falls_back_to_single_repository(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")

    assert gate.main_worktree(git_repo, "main") == git_repo.resolve()


def test_main_worktree_finds_linked_main_worktree(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    git(git_repo, "branch", "-M", "main")
    task_worktree = tmp_path / "task-worktree"
    git(git_repo, "worktree", "add", str(task_worktree), "-b", "codex/test-task")

    assert gate.main_worktree(task_worktree, "main") == git_repo.resolve()


def test_closeout_writes_bounded_passed_manifest(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["README.md"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed"
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == 1
    assert manifest["taskId"] == "test-task"
    assert manifest["branch"] == "codex/test-task"
    assert manifest["claimId"] == "claim-test"
    assert manifest["changedFiles"] == ["README.md"]
    assert manifest["checks"]["worktreeClean"] is True
    assert manifest["checks"]["claimValid"] is True
    assert manifest["checks"]["mergePreflight"] is True
    assert manifest["checks"]["commandsAllowlisted"] is True
    assert manifest["outcome"] == "passed"
    ancestry = git(
        git_repo,
        "merge-base",
        "--is-ancestor",
        manifest["validatedMainSha"],
        manifest["headSha"],
        check=False,
    )
    assert ancestry.returncode == 0
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "environment" not in serialized.lower()
    assert "prompt" not in serialized.lower()
    assert "stdout" not in serialized.lower()
    assert "stderr" not in serialized.lower()


def test_closeout_keeps_deleted_python_in_ownership_without_linting_it(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    commit_file(git_repo, ".gitignore", ".runtime/\n", "ignore gate runtime")
    commit_file(
        git_repo,
        "removed.py",
        "def removed() -> int:\n    return 1\n",
        "add removable Python",
    )
    git(git_repo, "switch", "-c", "codex/test-task")
    git(git_repo, "rm", "removed.py")
    git(git_repo, "commit", "-m", "remove Python")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["removed.py"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed", result.commands
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["changedFiles"] == ["removed.py"]
    assert all(
        command["kind"] != "changed-python-ruff"
        or "removed.py" not in command["argv"]
        for command in manifest["commands"]
    )
    assert gate.verify_manifest(result.manifest_path, git_repo, "main").outcome == (
        "passed"
    )


def test_closeout_checks_committed_diff_range_for_trailing_whitespace(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    commit_file(git_repo, ".gitignore", ".runtime/\n", "ignore gate runtime")
    validated_main_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "docs/note.md", "trailing whitespace  \n", "bad diff")
    head_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["docs/note.md"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "failed"
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    diff_check = next(
        command for command in manifest["commands"] if command["kind"] == "diff-check"
    )
    assert diff_check["argv"] == [
        "git",
        "diff",
        "--check",
        f"{validated_main_sha}...{head_sha}",
    ]
    assert manifest["outcome"] == "failed"


def test_closeout_records_exact_committed_diff_range_for_valid_diff(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    commit_file(git_repo, ".gitignore", ".runtime/\n", "ignore gate runtime")
    validated_main_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "docs/note.md", "valid diff\n", "valid diff")
    head_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["docs/note.md"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed"
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    diff_check = next(
        command for command in manifest["commands"] if command["kind"] == "diff-check"
    )
    assert diff_check["argv"] == [
        "git",
        "diff",
        "--check",
        f"{validated_main_sha}...{head_sha}",
    ]


def test_verify_manifest_rejects_bare_diff_check_argv(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_passed_manifest(git_repo, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    diff_check = next(
        command for command in payload["commands"] if command["kind"] == "diff-check"
    )
    diff_check["argv"] = ["git", "diff", "--check"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "failed"


def test_closeout_rejects_main_branch(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "failed"


def test_closeout_reports_dirty_worktree(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "dirty_worktree"


def test_closeout_reports_claim_conflict(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(gate, "read_guard_status", lambda root: {"claims": []})

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "claim_conflict"


def test_validate_claim_matches_central_guard_scope_semantics(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", [" readme.md ", "scripts"]),
    )

    assert gate.validate_claim(
        git_repo,
        "claim-test",
        ["README.md", "scripts/local_quality_gate.py"],
    )


def test_scope_covers_rejects_unrelated_path_prefix() -> None:
    assert not gate.scope_covers("scripts", "scripts-archive/local_quality_gate.py")


def test_closeout_reports_unsupported_validation_command(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["README.md"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["pwsh -Command Get-ChildItem"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "unsupported_validation_command"


def test_verify_manifest_detects_stale_main(git_repo: Path) -> None:
    git(git_repo, "branch", "-M", "main")
    manifest = git_repo / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "outcome": "passed",
                "validatedMainSha": "0" * 40,
                "headSha": git(git_repo, "rev-parse", "HEAD").stdout.strip(),
            }
        ),
        encoding="utf-8",
    )

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "stale_main"


def test_verify_manifest_accepts_current_authorization(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_passed_manifest(git_repo, monkeypatch)

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "passed"


def test_verify_manifest_rejects_inactive_claim(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_passed_manifest(git_repo, monkeypatch)
    monkeypatch.setattr(gate, "read_guard_status", lambda root: {"claims": []})

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "claim_conflict"


def test_verify_manifest_rejects_dirty_worktree(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_passed_manifest(git_repo, monkeypatch)
    (git_repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "dirty_worktree"


def test_verify_manifest_rejects_current_branch_mismatch(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_passed_manifest(git_repo, monkeypatch)
    git(git_repo, "switch", "-c", "codex/other-task")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "failed"


@pytest.mark.parametrize(
    "tamper",
    [
        "payload-branch",
        "schema-version-type",
        "worktree",
        "changed-files",
        "check-worktree-clean",
        "check-claim-valid",
        "check-merge-preflight",
        "check-commands-allowlisted",
        "command-status",
        "command-exit-code",
        "command-argv",
        "command-cwd",
        "command-kind",
        "command-kind-type",
    ],
)
def test_verify_manifest_rejects_tampered_authorization(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    manifest = create_passed_manifest(git_repo, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if tamper == "payload-branch":
        payload["branch"] = "codex/other-task"
    elif tamper == "schema-version-type":
        payload["schemaVersion"] = True
    elif tamper == "worktree":
        payload["worktree"] = str(git_repo / "other-worktree")
    elif tamper == "changed-files":
        payload["changedFiles"] = ["other.md"]
    elif tamper.startswith("check-"):
        check_name = {
            "check-worktree-clean": "worktreeClean",
            "check-claim-valid": "claimValid",
            "check-merge-preflight": "mergePreflight",
            "check-commands-allowlisted": "commandsAllowlisted",
        }[tamper]
        payload["checks"][check_name] = False
    elif tamper == "command-status":
        payload["commands"][0]["status"] = "failed"
    elif tamper == "command-exit-code":
        payload["commands"][0]["exitCode"] = 1
    elif tamper == "command-argv":
        payload["commands"][0]["argv"] = "git diff --check"
    elif tamper == "command-cwd":
        payload["commands"][0]["cwd"] = 7
    elif tamper == "command-kind":
        payload["commands"][0]["kind"] = "unsupported"
    elif tamper == "command-kind-type":
        payload["commands"][0]["kind"] = ["diff-check"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "failed"


def test_verify_manifest_rejects_empty_commands(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_recorded_contract_manifest(git_repo, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["commands"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "failed"


def test_verify_manifest_rejects_missing_expected_command(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_recorded_contract_manifest(git_repo, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(payload["commands"]) > 1
    del payload["commands"][1]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "failed"


@pytest.mark.parametrize("field", ["argv", "cwd"])
def test_verify_manifest_rejects_changed_command_contract(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    manifest = create_recorded_contract_manifest(git_repo, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if field == "argv":
        payload["commands"][0]["argv"][-1] = "other.py"
    else:
        payload["commands"][0]["cwd"] = str(git_repo / "other")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "failed"


def test_verify_manifest_rejects_task_id_that_does_not_match_branch(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = create_recorded_contract_manifest(git_repo, monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["taskId"] = "other-task"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "failed"


def test_verify_manifest_rejects_non_ancestor_validated_main(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    commit_file(git_repo, ".gitignore", ".runtime/\n", "ignore gate runtime")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "task\n", "task change")
    head_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "switch", "main")
    commit_file(git_repo, "main.txt", "main\n", "main change")
    validated_main_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "switch", "codex/test-task")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["README.md"]),
    )
    payload = gate.manifest_payload(
        task_id="test-task",
        branch="codex/test-task",
        root=git_repo.resolve(),
        claim_id="claim-test",
        validated_main_sha=validated_main_sha,
        head_sha=head_sha,
        files=["README.md"],
        commands=[
            gate.ProcessResult(
                kind="diff-check",
                argv=["git", "diff", "--check"],
                cwd=str(git_repo.resolve()),
                exit_code=0,
                duration_ms=1,
                status="passed",
            )
        ],
        checks={
            "worktreeClean": True,
            "claimValid": True,
            "mergePreflight": True,
            "commandsAllowlisted": True,
        },
        outcome="passed",
    )
    manifest = gate.write_manifest(git_repo, "test-task", payload)

    result = gate.verify_manifest(manifest, git_repo, "main")

    assert result.outcome == "stale_main"


def test_closeout_detects_main_moving_during_commands(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "README.md", "changed\n", "docs change")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["README.md"]),
    )
    original_execute = gate.execute_command

    def execute_and_move_main(spec: gate.CommandSpec) -> gate.ProcessResult:
        result = original_execute(spec)
        git(git_repo, "update-ref", "refs/heads/main", "HEAD")
        return result

    monkeypatch.setattr(gate, "execute_command", execute_and_move_main)

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.outcome == "stale_main"
    assert manifest["outcome"] == "stale_main"


def test_closeout_prioritizes_stale_main_over_merge_conflict(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflict = git_repo / "conflict.txt"
    conflict.write_text("base\n", encoding="utf-8")
    git(git_repo, "add", "conflict.txt")
    git(git_repo, "commit", "-m", "add conflict base")
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "conflict.txt", "task\n", "task side")
    git(git_repo, "switch", "main")
    commit_file(git_repo, "conflict.txt", "main\n", "main side")
    git(git_repo, "switch", "codex/test-task")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["conflict.txt"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.outcome == "stale_main"
    assert manifest["outcome"] == "stale_main"


def test_closeout_rejects_clean_diverged_history_even_when_merge_tree_passes(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "task.txt", "task\n", "task change")
    git(git_repo, "switch", "main")
    commit_file(git_repo, "main.txt", "main\n", "main change")
    git(git_repo, "switch", "codex/test-task")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["task.txt"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )
    merge_tree = git(
        git_repo,
        "merge-tree",
        "--write-tree",
        "main",
        "HEAD",
        check=False,
    )
    assert merge_tree.returncode == 0

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "stale_main"
    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["outcome"] == "stale_main"
    assert manifest["checks"]["mergePreflight"] is False


def test_closeout_reports_stale_main_when_main_moves_during_merge_tree_preflight(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "task.txt", "task\n", "task side")
    validated_main_sha = git(git_repo, "rev-parse", "main").stdout.strip()
    git(git_repo, "switch", "main")
    git(git_repo, "switch", "-c", "future-main")
    commit_file(git_repo, "main.txt", "future main\n", "move main")
    future_main_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "switch", "codex/test-task")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["task.txt"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )
    original_run_process = gate.run_process
    merge_bases: list[str] = []

    def run_process_and_move_main(
        argv: list[str],
        cwd: Path,
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["git", "merge-tree", "--write-tree"]:
            merge_bases.append(argv[3])
            git(git_repo, "update-ref", "refs/heads/main", future_main_sha)
        return original_run_process(argv, cwd, input_text=input_text)

    monkeypatch.setattr(gate, "run_process", run_process_and_move_main)

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert merge_bases == [validated_main_sha]
    assert result.outcome == "stale_main"
    assert manifest["outcome"] == "stale_main"


def test_closeout_reports_stale_main_when_main_moves_during_ancestry_preflight(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(git_repo, "task.txt", "task\n", "task side")
    validated_main_sha = git(git_repo, "rev-parse", "main").stdout.strip()
    git(git_repo, "switch", "main")
    git(git_repo, "switch", "-c", "future-main")
    commit_file(git_repo, "main.txt", "future main\n", "move main")
    future_main_sha = git(git_repo, "rev-parse", "HEAD").stdout.strip()
    git(git_repo, "switch", "codex/test-task")
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["task.txt"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )
    original_run_process = gate.run_process
    ancestry_bases: list[str] = []

    def run_process_and_move_main(
        argv: list[str],
        cwd: Path,
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["git", "merge-base", "--is-ancestor"]:
            ancestry_bases.append(argv[3])
            git(git_repo, "update-ref", "refs/heads/main", future_main_sha)
        return original_run_process(argv, cwd, input_text=input_text)

    monkeypatch.setattr(gate, "run_process", run_process_and_move_main)

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert ancestry_bases == [validated_main_sha]
    assert result.outcome == "stale_main"
    assert manifest["outcome"] == "stale_main"


def test_closeout_reads_claim_from_linked_main_worktree(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    task_worktree = tmp_path / "linked-task"
    git(git_repo, "worktree", "add", str(task_worktree), "-b", "codex/test-task")
    commit_file(task_worktree, "README.md", "changed\n", "docs change")
    guard_roots: list[Path] = []

    def guard_status(root: Path) -> dict[str, object]:
        guard_roots.append(root)
        return active_claim("claim-test", ["README.md"])

    monkeypatch.setattr(gate, "read_guard_status", guard_status)
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )

    result = gate.run_closeout(task_worktree, "main", "claim-test")

    assert result.outcome == "passed"
    assert guard_roots == [git_repo.resolve(), git_repo.resolve()]


def test_closeout_appends_gate_self_tests_when_gate_definition_changes(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(git_repo, "branch", "-M", "main")
    git(git_repo, "switch", "-c", "codex/test-task")
    commit_file(
        git_repo,
        "scripts/local_quality_gate.py",
        "VALUE = 1\n",
        "change gate",
    )
    monkeypatch.setattr(
        gate,
        "read_guard_status",
        lambda root: active_claim("claim-test", ["scripts/local_quality_gate.py"]),
    )
    monkeypatch.setattr(
        gate,
        "selected_validation",
        lambda changed: {"commands": ["git diff --check"]},
    )
    monkeypatch.setattr(
        gate,
        "measured",
        lambda kind, argv, cwd, **kwargs: gate.ProcessResult(
            kind=kind,
            argv=list(argv),
            cwd=str(cwd),
            exit_code=0,
            duration_ms=1,
            status="passed",
        ),
    )
    monkeypatch.setattr(
        gate,
        "execute_command",
        lambda spec: gate.ProcessResult(
            kind=spec.kind,
            argv=spec.argv,
            cwd=str(spec.cwd),
            exit_code=0,
            duration_ms=1,
            status="passed",
        ),
    )

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed"
    assert [command.kind for command in result.commands] == [
        "changed-python-ruff",
        "diff-check",
        "pytest",
    ]


def test_manifest_payload_redacts_and_bounds_failure_summary_before_persistence(
    git_repo: Path,
) -> None:
    fake_secrets = [
        "bearer-secret-value",
        "fake-api-key-value",
        "url-password-value",
        "sk-test-abcdefghijklmnopqrstuvwxyz012345",
    ]
    failure_summary = (
        "pytest: Authorization: Bearer bearer-secret-value; "
        "api_key=fake-api-key-value; "
        "https://user:url-password-value@example.com; "
        "sk-test-abcdefghijklmnopqrstuvwxyz012345; "
        + "x" * 400
        + "\nsecret second line"
    )
    payload = gate.manifest_payload(
        task_id="test-task",
        branch="codex/test-task",
        root=git_repo,
        claim_id="claim-test",
        validated_main_sha="a" * 40,
        head_sha="b" * 40,
        files=["README.md"],
        commands=[
            gate.ProcessResult(
                kind="pytest",
                argv=["python", "-m", "pytest"],
                cwd=str(git_repo),
                exit_code=1,
                duration_ms=1,
                status="failed",
                failure_summary=failure_summary,
            )
        ],
        checks={
            "worktreeClean": True,
            "claimValid": True,
            "mergePreflight": False,
            "commandsAllowlisted": True,
        },
        outcome="failed",
    )
    manifest_path = gate.write_manifest(git_repo, "test-task", payload)
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    persisted_summary = persisted["commands"][0]["failureSummary"]

    assert persisted_summary.startswith("pytest:")
    assert "[REDACTED]" in persisted_summary
    assert all(secret not in persisted_summary for secret in fake_secrets)
    assert "\n" not in persisted_summary
    assert len(persisted_summary) <= 300
