# 本地质量门闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立以本地 `main` 为事实源的轻量 commit 门、强任务收口门和可验证 manifest，使任务分支能独立开发、低冲突合并，并在完成后只清理自己的 worktree 与分支。

**Architecture:** 新增一个依赖标准库的 `scripts/local_quality_gate.py` 作为唯一执行策略层；tracked hook 只调用 commit mode，closeout mode 复用现有 `tests/select_tests.py` 与 `tests/test_matrix.yaml`，并把命令转成白名单 argv 后执行。门禁只验证和记录，不执行 merge、branch/worktree 删除、claim release、Launcher 刷新或应用状态写入；本地 `main` SHA 变化会使既有结果失效为 `stale_main`。

**Tech Stack:** Python 3.11+ 标准库、pytest、Ruff、Git CLI、PowerShell、GitHub Actions YAML、现有 Vibelution test selector 与 agent work guard。

## Global Constraints

- 根目录 `C:\Users\17533\Desktop\Vibelution` 必须持续位于 `main`；实现只在 `C:\Users\17533\Desktop\Vibelution-worktrees\local-quality-gate-closure` 的 `codex/local-quality-gate-closure` 上进行。
- 中间 commit 只检查 staged 内容，不运行行为测试、前端 build、bundle budget、Launcher 检查或全仓 lint；只有 gate-definition 变更会额外运行 `tests/test_local_quality_gate.py` 的 commit/hook 子集。
- Ruff 只启用 fatal rules：`E9,F63,F7,F82`；`F401`、`F841` 与当前 217 项全仓 lint debt 不进入本任务。
- closeout 只接受现有矩阵产生且属于允许命令族的命令；不得使用 shell、任意命令、`eval` 或 shell metacharacters。
- GitHub Actions 保持 `workflow_dispatch` 手动触发，不恢复 push 或 pull-request 自动触发。
- gate 只验证和写 `.runtime/quality_gates/*.json`；不得 merge、删除 branch/worktree、release claim、刷新 Launcher 或修改应用运行态。
- gate-definition 文件必须整文件 staged；同一文件同时有 staged 与 unstaged 改动时返回 `gate_definition_dirty`。
- 每次 closeout 绑定 `validatedMainSha` 与 `headSha`；执行中或执行后 `main` 变化必须返回 `stale_main`。
- 任务合并后由任务所有者做最小 main 验证，然后只释放本任务 claim、删除本任务 worktree 和本任务 branch；不清理其他任务资源。
- 不修改 `.gitignore`、应用源码、前端源码、operator config、`VERSION`、`CHANGELOG.md` 或依赖锁文件。
- 版本影响：`none`；Launcher refresh：`not needed`，因为本任务只改变开发治理、测试和手动 CI。

---

## 文件责任图

| 文件 | 责任 | 变化 |
| --- | --- | --- |
| `scripts/local_quality_gate.py` | commit/closeout/verify-manifest 唯一策略层、命令白名单、manifest | Create |
| `tests/test_local_quality_gate.py` | staged blob、命令解析、临时 Git 仓、outcome 与 manifest 回归 | Create |
| `.githooks/pre-commit` | 定位 repo 与项目 Python，薄调用 commit mode | Modify |
| `scripts/doctor.ps1` | 只读报告 `core.hooksPath`、hook 与 gate 脚本状态及修复命令 | Modify |
| `tests/test_environment_doctor.py` | doctor JSON/文本契约 | Modify |
| `tests/test_matrix.yaml` | gate-definition 影响面到聚焦验证命令的唯一映射 | Modify |
| `tests/test_select_tests.py` | gate rule 与高频路径映射契约 | Modify |
| `.github/workflows/ci.yml` | 手动 CI 无条件 fatal Ruff 检查 | Modify |
| `tests/test_ci_workflow_contract.py` | 手动触发与 lint 步骤可达性契约 | Create |
| `README.md` | 本地开发入口和首次 hook 配置 | Modify |
| `tests/README.md` | commit/closeout/manifest 操作说明 | Modify |
| `DEVELOPMENT_STANDARD.md` | 本地闭环、stale-main、冲突与清理治理规范 | Modify |

`tests/select_tests.py` 保持只负责“选择和解释”，本轮不修改；gate 通过导入 `load_matrix()` 与 `select_tests()` 复用它，不复制第二份 registry。

---

### Task 1: 建立实现 claim 并让 Commit mode 检查 Git index 内容

**Files:**
- Create: `scripts/local_quality_gate.py`
- Create: `tests/test_local_quality_gate.py`

**Interfaces:**
- Consumes: Git CLI、当前 Python 的 `python -m ruff`。
- Produces: `Outcome`、`ProcessResult`、`GateResult`；`repository_root(start: Path) -> Path`；`staged_paths(root: Path) -> list[str]`；`staged_blob(root: Path, path: str) -> str`；`run_commit_gate(root: Path) -> GateResult`；`main(argv: Sequence[str] | None = None) -> int`。

- [ ] **Step 1: 在任何实现编辑前建立完整 claim 与 `.venv` junction**

在 task worktree 的 PowerShell 会话执行；任一 scope 冲突即停止，不使用 `--force`：

```powershell
$root = 'C:\Users\17533\Desktop\Vibelution'
$worktree = 'C:\Users\17533\Desktop\Vibelution-worktrees\local-quality-gate-closure'
$python = Join-Path $root '.venv\Scripts\python.exe'
$guard = 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py'
$scopes = @(
  'docs/superpowers/specs/2026-07-10-local-quality-gate-closure-design.md',
  'docs/superpowers/plans/2026-07-10-local-quality-gate-closure.md',
  'scripts/local_quality_gate.py',
  'tests/test_local_quality_gate.py',
  '.githooks/pre-commit',
  'scripts/doctor.ps1',
  'tests/test_environment_doctor.py',
  'tests/test_matrix.yaml',
  'tests/test_select_tests.py',
  '.github/workflows/ci.yml',
  'tests/test_ci_workflow_contract.py',
  'README.md',
  'tests/README.md',
  'DEVELOPMENT_STANDARD.md'
)
$scopeArgs = foreach ($scope in $scopes) { '--scope'; $scope }
$check = & $python $guard $root check --lane quality-and-operations @scopeArgs --json | ConvertFrom-Json
if (-not $check.ok) { throw ($check.conflicts | ConvertTo-Json -Depth 8) }
$claim = & $python $guard $root claim --lane quality-and-operations @scopeArgs --agent codex-local-quality-gate --task 'Implement local quality gate closure' --status active --ttl-minutes 360 --json | ConvertFrom-Json
if (-not $claim.ok) { throw ($claim.conflicts | ConvertTo-Json -Depth 8) }
$env:VIBELUTION_CLAIM_ID = $claim.claim.id

$venvLink = Join-Path $worktree '.venv'
if (-not (Test-Path -LiteralPath $venvLink)) {
  New-Item -ItemType Junction -Path $venvLink -Target (Join-Path $root '.venv') | Out-Null
}
```

Expected: `$env:VIBELUTION_CLAIM_ID` 以 `claim-` 开头且后缀非空；`.venv` 是指向 root `.venv` 的 junction；tracked worktree 仍 clean。

- [ ] **Step 2: 写 staged-content 与 gate-definition 的失败测试**

在 `tests/test_local_quality_gate.py` 创建临时仓库 helper，并加入下列测试；测试通过 import 调用行为，不断言 mock 被调用次数：

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import local_quality_gate as gate


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "quality-gate@example.invalid")
    git(tmp_path, "config", "user.name", "Quality Gate Test")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(tmp_path, "add", "seed.txt")
    git(tmp_path, "commit", "-m", "seed")
    return tmp_path


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


def test_commit_mode_without_relevant_staged_files_passes(git_repo: Path) -> None:
    result = gate.run_commit_gate(git_repo)

    assert result.outcome == "passed"
    assert result.commands == []
```

- [ ] **Step 3: 运行测试并确认因模块不存在而失败**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py -q`

Expected: collection FAIL，错误包含 `cannot import name 'local_quality_gate' from 'scripts'` 或 `ModuleNotFoundError`。

- [ ] **Step 4: 实现 commit mode 的最小完整骨架**

创建 `scripts/local_quality_gate.py`。使用以下稳定类型和常量，后续任务只能扩展，不得改名：

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Sequence

Outcome = Literal[
    "passed",
    "failed",
    "stale_main",
    "claim_conflict",
    "dirty_worktree",
    "merge_conflict",
    "unsupported_validation_command",
    "gate_definition_dirty",
]

FATAL_RUFF_RULES = "E9,F63,F7,F82"
GATE_DEFINITION_FILES = frozenset(
    {
        ".githooks/pre-commit",
        ".github/workflows/ci.yml",
        "scripts/doctor.ps1",
        "scripts/local_quality_gate.py",
        "tests/select_tests.py",
        "tests/test_matrix.yaml",
    }
)


@dataclass(frozen=True)
class ProcessResult:
    kind: str
    argv: list[str]
    cwd: str
    exit_code: int
    duration_ms: int
    status: Literal["passed", "failed"]
    failure_summary: str = ""


@dataclass
class GateResult:
    outcome: Outcome
    exit_code: int
    commands: list[ProcessResult] = field(default_factory=list)
    manifest_path: Path | None = None


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def run_process(
    argv: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def repository_root(start: Path) -> Path:
    completed = run_process(["git", "rev-parse", "--show-toplevel"], start)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "not a Git repository")
    return Path(completed.stdout.strip()).resolve()


def git_lines(root: Path, *args: str) -> list[str]:
    completed = run_process(["git", *args], root)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return [line for line in completed.stdout.splitlines() if line]


def staged_paths(root: Path) -> list[str]:
    return [
        normalize_path(path)
        for path in git_lines(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    ]


def staged_blob(root: Path, path: str) -> str:
    completed = run_process(["git", "show", f":{path}"], root)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"cannot read staged blob: {path}")
    return completed.stdout


def summarize_failure(completed: subprocess.CompletedProcess[str], subject: str) -> str:
    raw = completed.stderr.strip() or completed.stdout.strip() or "command failed"
    first_line = raw.splitlines()[0][:300]
    return f"{subject}: {first_line}"


def measured(
    kind: str,
    argv: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    subject: str,
) -> ProcessResult:
    started = time.monotonic()
    completed = run_process(argv, cwd, input_text=input_text)
    duration_ms = round((time.monotonic() - started) * 1000)
    return ProcessResult(
        kind=kind,
        argv=list(argv),
        cwd=str(cwd),
        exit_code=completed.returncode,
        duration_ms=duration_ms,
        status="passed" if completed.returncode == 0 else "failed",
        failure_summary="" if completed.returncode == 0 else summarize_failure(completed, subject),
    )
```

同一文件继续加入 `gate_definition_is_dirty()`、`run_commit_gate()` 与 CLI；Ruff 的 stdin 文件名必须是 index 路径：

```python
def gate_definition_is_dirty(root: Path, staged: Sequence[str]) -> bool:
    unstaged = {
        normalize_path(path)
        for path in git_lines(root, "diff", "--name-only", "--diff-filter=ACMR")
    }
    return bool(GATE_DEFINITION_FILES.intersection(staged).intersection(unstaged))


def run_commit_gate(root: Path) -> GateResult:
    root = repository_root(root)
    staged = staged_paths(root)
    if not staged:
        return GateResult(outcome="passed", exit_code=0)
    if gate_definition_is_dirty(root, staged):
        return GateResult(outcome="gate_definition_dirty", exit_code=1)

    commands: list[ProcessResult] = []
    diff_check = measured(
        "diff-check",
        ["git", "diff", "--cached", "--check"],
        root,
        subject="staged diff",
    )
    commands.append(diff_check)
    if diff_check.status == "failed":
        return GateResult(outcome="failed", exit_code=1, commands=commands)

    for path in staged:
        if not path.endswith(".py"):
            continue
        lint = measured(
            "ruff-staged",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                FATAL_RUFF_RULES,
                "--stdin-filename",
                path,
                "-",
            ],
            root,
            input_text=staged_blob(root, path),
            subject=path,
        )
        commands.append(lint)
        if lint.status == "failed":
            return GateResult(outcome="failed", exit_code=1, commands=commands)
    if GATE_DEFINITION_FILES.intersection(staged):
        self_test = measured(
            "gate-self-test",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_local_quality_gate.py",
                "-q",
                "-k",
                "commit_mode or pre_commit",
            ],
            root,
            subject="gate self-test",
        )
        commands.append(self_test)
        if self_test.status == "failed":
            return GateResult(outcome="failed", exit_code=1, commands=commands)
    return GateResult(outcome="passed", exit_code=0, commands=commands)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vibelution local quality gate")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("commit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "commit":
        result = run_commit_gate(Path.cwd())
        print(json.dumps(asdict(result), ensure_ascii=False, default=str))
        return result.exit_code
    raise AssertionError(f"unhandled mode: {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 运行 commit-mode tests 与真实 Ruff smoke**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py -q`

Expected: `4 passed`。

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 scripts/local_quality_gate.py tests/test_local_quality_gate.py`

Expected: exit 0，输出 `All checks passed!`。

- [ ] **Step 6: scoped commit**

```powershell
git add -- scripts/local_quality_gate.py tests/test_local_quality_gate.py
git commit -m "feat: validate staged content locally"
```

Expected: commit 成功；`git status --short` 为空。

---

### Task 2: 将 selector 命令转换成无 shell 的允许 argv

**Files:**
- Modify: `scripts/local_quality_gate.py`
- Modify: `tests/test_local_quality_gate.py`

**Interfaces:**
- Consumes: `ProcessResult`、`normalize_path()`。
- Produces: `CommandSpec`；`parse_allowed_command(command: str, root: Path) -> CommandSpec`；`execute_command(spec: CommandSpec) -> ProcessResult`；异常 `UnsupportedValidationCommand`。

- [ ] **Step 1: 写允许族与拒绝族参数化测试**

追加：

```python
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
            ".\\.venv\\Scripts\\python.exe tests/select_tests.py --changed-file README.md --json",
            "selector",
            [str(gate.PROJECT_PYTHON_NAME), "tests/select_tests.py"],
        ),
        (
            ".\\.venv\\Scripts\\python.exe tests/prompt_debugger.py --suite",
            "prompt-debugger",
            [str(gate.PROJECT_PYTHON_NAME), "tests/prompt_debugger.py"],
        ),
        ("npm --prefix web run test", "web-test", ["npm", "--prefix", "web", "run", "test"]),
        ("npm --prefix web run build", "web-build", ["npm", "--prefix", "web", "run", "build"]),
        ("npm --prefix web run check:bundle", "bundle-check", ["npm", "--prefix", "web", "run", "check:bundle"]),
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
```

- [ ] **Step 2: 运行定向测试并确认接口缺失**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py -q`

Expected: FAIL，首个错误指向 `PROJECT_PYTHON_NAME` 或 `parse_allowed_command` 未定义。

- [ ] **Step 3: 实现跨平台、无 shell 的解析器**

在 `scripts/local_quality_gate.py` 加入 `re`、`shlex` import，并加入：

```python
PROJECT_PYTHON_NAME = Path(".venv") / "Scripts" / "python.exe"
SHELL_META = re.compile(r"[|&;<>\r\n]|\$\(|`")


class UnsupportedValidationCommand(ValueError):
    pass


@dataclass(frozen=True)
class CommandSpec:
    kind: str
    argv: list[str]
    cwd: Path


def split_command(command: str) -> list[str]:
    if SHELL_META.search(command):
        raise UnsupportedValidationCommand(command)
    tokens = shlex.split(command, posix=False)
    return [
        token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"} else token
        for token in tokens
    ]


def parse_allowed_command(command: str, root: Path) -> CommandSpec:
    argv = split_command(command)
    normalized = [normalize_path(token) for token in argv]
    python_tokens = {normalize_path(str(PROJECT_PYTHON_NAME)), ".venv/Scripts/python.exe"}
    if normalized == ["git", "diff", "--check"]:
        return CommandSpec("diff-check", argv, root)
    if normalized and normalized[0] in python_tokens:
        canonical = [str(PROJECT_PYTHON_NAME), *argv[1:]]
        if argv[1:3] == ["-m", "pytest"]:
            return CommandSpec("pytest", canonical, root)
        if len(argv) >= 2 and normalized[1] == "tests/select_tests.py":
            return CommandSpec("selector", canonical, root)
        if len(argv) >= 2 and normalized[1] == "tests/prompt_debugger.py":
            return CommandSpec("prompt-debugger", canonical, root)
    if normalized[:4] == ["npm", "--prefix", "web", "run"] and len(argv) >= 5:
        npm_kinds = {
            "test": "web-test",
            "build": "web-build",
            "check:bundle": "bundle-check",
        }
        if argv[4] in npm_kinds:
            return CommandSpec(npm_kinds[argv[4]], argv, root)
    if normalized == ["node", "挑战杯/build_research_flow_site.mjs"]:
        return CommandSpec("challenge-cup-build", argv, root)
    raise UnsupportedValidationCommand(command)


def execute_command(spec: CommandSpec) -> ProcessResult:
    argv = list(spec.argv)
    if Path(argv[0]) == PROJECT_PYTHON_NAME:
        argv[0] = str((spec.cwd / PROJECT_PYTHON_NAME).resolve())
    return measured(spec.kind, argv, spec.cwd, subject=spec.kind)
```

- [ ] **Step 4: 运行 parser 测试与 fatal Ruff**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py -q`

Expected: 全部 PASS。

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 scripts/local_quality_gate.py tests/test_local_quality_gate.py`

Expected: exit 0。

- [ ] **Step 5: scoped commit**

```powershell
git add -- scripts/local_quality_gate.py tests/test_local_quality_gate.py
git commit -m "feat: allowlist closeout commands"
```

---

### Task 3: Closeout、claim、stale-main、merge preflight 与 manifest

**Files:**
- Modify: `scripts/local_quality_gate.py`
- Modify: `tests/test_local_quality_gate.py`

**Interfaces:**
- Consumes: `tests.select_tests.load_matrix()`、`tests.select_tests.select_tests()`、Task 2 的 `parse_allowed_command()` 与 `execute_command()`、外部 guard 的 `status --json`。
- Produces: `main_worktree(root: Path, base: str) -> Path`；`validate_claim(project_root: Path, claim_id: str, changed_files: Sequence[str]) -> bool`；`merge_preflight(root: Path, base: str, head: str) -> bool`；`run_closeout(root: Path, base: str, claim_id: str) -> GateResult`；`verify_manifest(path: Path, root: Path, base: str) -> GateResult`。

- [ ] **Step 1: 写临时仓库 closeout 的关键 outcome tests**

在 fixture 中创建 `main` 与 `codex/test-task`，并将 guard 路径作为可替换常量。加入以下测试组；每个测试实际创建 commit 和读取 manifest：

```python
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

    result = gate.run_closeout(git_repo, "main", "claim-test")

    assert result.outcome == "passed"
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
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "environment" not in serialized.lower()
    assert "prompt" not in serialized.lower()


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


def test_verify_manifest_detects_stale_main(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
```

同一步追加两项行为测试，断言最终 manifest outcome，而不是只断言 Git 命令调用：

```python
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
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.outcome == "stale_main"
    assert manifest["outcome"] == "stale_main"


def test_closeout_reports_merge_conflict(
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
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.outcome == "merge_conflict"
    assert manifest["outcome"] == "merge_conflict"
```

- [ ] **Step 2: 运行 closeout tests 并确认接口缺失**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py -q`

Expected: FAIL，错误指向 `run_closeout`、`read_guard_status` 或 `verify_manifest` 未定义。

- [ ] **Step 3: 实现 claim 与 selector adapters**

加入以下常量和函数；guard 使用根项目 memory registry，不复制 claim 文件解析逻辑：

```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUARD_SCRIPT = Path.home() / ".codex" / "skills" / "ccdawn-dawn-agent-html-memory" / "scripts" / "agent_work_guard.py"
MANIFEST_SCHEMA_VERSION = 1
GATE_SELF_TEST_COMMAND = (
    ".\\.venv\\Scripts\\python.exe -m pytest "
    "tests/test_local_quality_gate.py tests/test_ci_workflow_contract.py "
    "tests/test_environment_doctor.py tests/test_select_tests.py -q"
)


def current_branch(root: Path) -> str:
    return git_lines(root, "branch", "--show-current")[0]


def rev_parse(root: Path, revision: str) -> str:
    return git_lines(root, "rev-parse", revision)[0]


def changed_files(root: Path, base: str) -> list[str]:
    return [normalize_path(path) for path in git_lines(root, "diff", "--name-only", f"{base}...HEAD")]


def main_worktree(root: Path, base: str) -> Path:
    completed = run_process(["git", "worktree", "list", "--porcelain"], root)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "cannot list worktrees")
    blocks = completed.stdout.strip().split("\n\n")
    expected_branch = f"branch refs/heads/{base}"
    for block in blocks:
        lines = block.splitlines()
        if expected_branch in lines:
            path_line = next(line for line in lines if line.startswith("worktree "))
            return Path(path_line.removeprefix("worktree ")).resolve()
    return root.resolve()


def read_guard_status(project_root: Path) -> dict[str, object]:
    completed = run_process(
        [sys.executable, str(GUARD_SCRIPT), str(project_root), "status", "--json"],
        project_root,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "guard status failed")
    loaded = json.loads(completed.stdout)
    if not isinstance(loaded, dict):
        raise RuntimeError("guard status must be an object")
    return loaded


def scope_covers(scope: str, changed_path: str) -> bool:
    normalized_scope = normalize_path(scope)
    normalized_path = normalize_path(changed_path)
    if normalized_scope == "repo":
        return True
    if normalized_scope.endswith("/**"):
        prefix = normalized_scope[:-3]
        return normalized_path == prefix or normalized_path.startswith(prefix + "/")
    return normalized_scope == normalized_path


def validate_claim(project_root: Path, claim_id: str, files: Sequence[str]) -> bool:
    status = read_guard_status(project_root)
    claims = status.get("claims", [])
    if not isinstance(claims, list):
        return False
    claim = next(
        (
            item
            for item in claims
            if isinstance(item, dict)
            and item.get("id") == claim_id
            and item.get("status") == "active"
        ),
        None,
    )
    if claim is None:
        return False
    scopes = claim.get("scopes", [])
    return isinstance(scopes, list) and all(
        any(scope_covers(str(scope), path) for scope in scopes) for path in files
    )


def selected_validation(files: Sequence[str]) -> dict[str, object]:
    from tests.select_tests import load_matrix, select_tests

    return select_tests(list(files), load_matrix())
```

- [ ] **Step 4: 实现 closeout state machine 与 bounded manifest**

加入 `utc_now()`、`write_manifest()`、`merge_preflight()` 和 `run_closeout()`。实现必须按此顺序短路：branch/clean → 定位 main worktree 与 SHA snapshot → changed files → claim → allowlist → changed-Python Ruff → focused commands → merge preflight → SHA recheck → manifest。manifest 只写以下 schema：

```python
def manifest_payload(
    *,
    task_id: str,
    branch: str,
    root: Path,
    claim_id: str,
    validated_main_sha: str,
    head_sha: str,
    files: Sequence[str],
    commands: Sequence[ProcessResult],
    checks: dict[str, bool],
    outcome: Outcome,
) -> dict[str, object]:
    return {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "taskId": task_id,
        "branch": branch,
        "worktree": str(root),
        "claimId": claim_id,
        "validatedMainSha": validated_main_sha,
        "headSha": head_sha,
        "changedFiles": list(files),
        "commands": [
            {
                "kind": command.kind,
                "argv": command.argv,
                "cwd": command.cwd,
                "exitCode": command.exit_code,
                "durationMs": command.duration_ms,
                "status": command.status,
                "failureSummary": command.failure_summary,
            }
            for command in commands
        ],
        "checks": checks,
        "outcome": outcome,
        "generatedAt": utc_now(),
    }
```

关键实现约束：

- clean 检查使用 `git status --porcelain`，任何输出都返回 `dirty_worktree`。
- branch 必须非空、非 `main` 且以 `codex/` 开头；否则 `failed`。
- `validatedMainSha` 从 `main_worktree(root, base)` 的 `HEAD` 读取，guard 也以该 main worktree 为 project root；不得从任务 worktree 的 `.docs/project-memory` 副本读取 claim。
- changed Python 非空时先执行 `[sys.executable, "-m", "ruff", "check", "--select", FATAL_RUFF_RULES, *python_files]` 并记录为 `changed-python-ruff`。
- `merge_preflight()` 在 focused commands 之后使用 `git merge-tree --write-tree main HEAD`，不得 checkout、merge、reset 或更新 ref。
- `GATE_DEFINITION_FILES` 与 changed files 相交时，即使 matrix 被本分支修改并删除了规则，也要追加 `GATE_SELF_TEST_COMMAND`。
- 每条 Ruff/focused command 前后均比较 `rev_parse(main_root, "HEAD")` 与 `validatedMainSha`；不同立即写 `stale_main` manifest 并停止。
- 第一个命令失败即写 `failed`，但保留已执行命令的 bounded result。
- `failureSummary` 仅保留首行 300 字符；不写 stdout、stderr、prompt、diff、环境变量或 secret。
- manifest 目录固定为 `root / ".runtime" / "quality_gates"`，例如本任务写入清洗后的 `local-quality-gate-closure.json`。

`run_closeout()` 采用以下完整控制流；实现时补充 `from datetime import datetime, timezone` 与 `import re`：

```python
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_manifest(root: Path, task_id: str, payload: dict[str, object]) -> Path:
    directory = root / ".runtime" / "quality_gates"
    directory.mkdir(parents=True, exist_ok=True)
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip("-") or "task"
    path = directory / f"{safe_task_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def merge_preflight(root: Path, base: str, head: str) -> bool:
    completed = run_process(["git", "merge-tree", "--write-tree", base, head], root)
    return completed.returncode == 0


def run_closeout(root: Path, base: str, claim_id: str) -> GateResult:
    root = repository_root(root)
    branch = current_branch(root)
    task_id = branch.removeprefix("codex/") if branch else "unknown-task"
    commands: list[ProcessResult] = []
    files: list[str] = []
    validated_main_sha = ""
    head_sha = rev_parse(root, "HEAD")
    checks = {
        "worktreeClean": False,
        "claimValid": False,
        "mergePreflight": False,
        "commandsAllowlisted": False,
    }

    def finish(outcome: Outcome) -> GateResult:
        payload = manifest_payload(
            task_id=task_id,
            branch=branch,
            root=root,
            claim_id=claim_id,
            validated_main_sha=validated_main_sha,
            head_sha=head_sha,
            files=files,
            commands=commands,
            checks=checks,
            outcome=outcome,
        )
        path = write_manifest(root, task_id, payload)
        return GateResult(
            outcome=outcome,
            exit_code=0 if outcome == "passed" else 1,
            commands=commands,
            manifest_path=path,
        )

    if not branch or branch == base or not branch.startswith("codex/"):
        return finish("failed")
    if git_lines(root, "status", "--porcelain"):
        return finish("dirty_worktree")
    checks["worktreeClean"] = True

    main_root = main_worktree(root, base)
    main_revision = "HEAD" if current_branch(main_root) == base else base
    validated_main_sha = rev_parse(main_root, main_revision)
    files = changed_files(root, base)
    checks["claimValid"] = validate_claim(main_root, claim_id, files)
    if not checks["claimValid"]:
        return finish("claim_conflict")

    selection = selected_validation(files)
    raw_commands = selection.get("commands", [])
    if not isinstance(raw_commands, list):
        return finish("unsupported_validation_command")
    if GATE_DEFINITION_FILES.intersection(files) and GATE_SELF_TEST_COMMAND not in raw_commands:
        raw_commands.append(GATE_SELF_TEST_COMMAND)
    try:
        specs = [parse_allowed_command(str(command), root) for command in raw_commands]
    except UnsupportedValidationCommand:
        return finish("unsupported_validation_command")
    checks["commandsAllowlisted"] = True

    def main_is_fresh() -> bool:
        return rev_parse(main_root, main_revision) == validated_main_sha

    python_files = [path for path in files if path.endswith(".py")]
    if python_files:
        if not main_is_fresh():
            return finish("stale_main")
        lint = measured(
            "changed-python-ruff",
            [sys.executable, "-m", "ruff", "check", "--select", FATAL_RUFF_RULES, *python_files],
            root,
            subject="changed Python",
        )
        commands.append(lint)
        if lint.status == "failed":
            return finish("failed")
        if not main_is_fresh():
            return finish("stale_main")

    for spec in specs:
        if not main_is_fresh():
            return finish("stale_main")
        result = execute_command(spec)
        commands.append(result)
        if result.status == "failed":
            return finish("failed")
        if not main_is_fresh():
            return finish("stale_main")

    checks["mergePreflight"] = merge_preflight(root, base, "HEAD")
    if not checks["mergePreflight"]:
        return finish("merge_conflict")
    if not main_is_fresh():
        return finish("stale_main")
    if rev_parse(root, "HEAD") != head_sha:
        return finish("failed")
    if not validate_claim(main_root, claim_id, files):
        checks["claimValid"] = False
        return finish("claim_conflict")
    return finish("passed")
```

- [ ] **Step 5: 实现 verify-manifest CLI 契约**

扩展 parser：

```python
closeout = subparsers.add_parser("closeout")
closeout.add_argument("--base", default="main")
closeout.add_argument("--claim-id", required=True)
verify = subparsers.add_parser("verify-manifest")
verify.add_argument("--manifest", type=Path, required=True)
verify.add_argument("--base", default="main")
```

`verify_manifest()` 必须验证：JSON object、`schemaVersion == 1`、`outcome == "passed"`、当前 `main` SHA 等于 `validatedMainSha`、当前 `HEAD` 等于 `headSha`；schema/HEAD 不符返回 `failed`，base SHA 不符返回 `stale_main`。`main()` 分派三种 mode，non-passed 一律 exit 1。

实现采用以下完整函数与分派，不对 manifest 做重写：

```python
def verify_manifest(path: Path, root: Path, base: str) -> GateResult:
    root = repository_root(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if not isinstance(payload, dict):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if payload.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    if payload.get("outcome") != "passed":
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    main_root = main_worktree(root, base)
    main_revision = "HEAD" if current_branch(main_root) == base else base
    if payload.get("validatedMainSha") != rev_parse(main_root, main_revision):
        return GateResult(outcome="stale_main", exit_code=1, manifest_path=path)
    if payload.get("headSha") != rev_parse(root, "HEAD"):
        return GateResult(outcome="failed", exit_code=1, manifest_path=path)
    return GateResult(outcome="passed", exit_code=0, manifest_path=path)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "commit":
        result = run_commit_gate(Path.cwd())
    elif args.mode == "closeout":
        result = run_closeout(Path.cwd(), args.base, args.claim_id)
    elif args.mode == "verify-manifest":
        result = verify_manifest(args.manifest, Path.cwd(), args.base)
    else:
        raise AssertionError(f"unhandled mode: {args.mode}")
    print(json.dumps(asdict(result), ensure_ascii=False, default=str))
    return result.exit_code
```

- [ ] **Step 6: 运行全部 gate tests、CLI help 与 fatal Ruff**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py -q`

Expected: 全部 PASS，至少覆盖八种 outcome 与两个临时 Git integration 分支。

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' scripts/local_quality_gate.py --help`

Expected: 输出包含 `commit`、`closeout`、`verify-manifest`。

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 scripts/local_quality_gate.py tests/test_local_quality_gate.py`

Expected: exit 0。

- [ ] **Step 7: scoped commit**

```powershell
git add -- scripts/local_quality_gate.py tests/test_local_quality_gate.py
git commit -m "feat: record local closeout evidence"
```

---

### Task 4: Hook 薄适配器与 doctor 只读诊断

**Files:**
- Modify: `.githooks/pre-commit`
- Modify: `scripts/doctor.ps1`
- Modify: `tests/test_environment_doctor.py`
- Test: `tests/test_local_quality_gate.py`

**Interfaces:**
- Consumes: `scripts/local_quality_gate.py commit`。
- Produces: doctor JSON 的 `checks.git_hooks_path`、`checks.pre_commit_hook`、`checks.local_quality_gate`；修复命令固定为 `git config core.hooksPath .githooks`。

- [ ] **Step 1: 先写 hook 与 doctor contract tests**

在 `tests/test_local_quality_gate.py` 追加静态 hook 契约：

```python
def test_pre_commit_is_thin_adapter() -> None:
    hook = (gate.PROJECT_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "scripts/local_quality_gate.py commit" in hook
    assert "pytest" not in hook
    assert "ruff" not in hook
```

在 `tests/test_environment_doctor.py` 的现有 `run_doctor()` 结果上追加：

```python
def test_doctor_reports_local_quality_gate_and_hook_configuration():
    report = run_doctor()

    assert report["checks"]["git_hooks_path"]["expected"] == ".githooks"
    assert report["checks"]["git_hooks_path"]["repair"] == "git config core.hooksPath .githooks"
    assert report["checks"]["pre_commit_hook"]["ok"] is True
    assert report["checks"]["local_quality_gate"]["ok"] is True
```

- [ ] **Step 2: 运行 tests 并确认新契约失败**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py tests/test_environment_doctor.py -q`

Expected: FAIL；hook 仍含 `pytest`，doctor 缺少 `git_hooks_path`。

- [ ] **Step 3: 把 tracked hook 改成无策略薄适配器**

`.githooks/pre-commit` 完整内容改为：

```bash
#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
project_python="$repo_root/.venv/Scripts/python.exe"

if [ ! -x "$project_python" ]; then
  echo "[pre-commit] missing project Python: $project_python" >&2
  exit 1
fi

exec "$project_python" "$repo_root/scripts/local_quality_gate.py" commit
```

- [ ] **Step 4: 扩展 doctor，不静默修改 Git config**

在 `scripts/doctor.ps1` 解析 root 后加入：

```powershell
$expectedHooksPath = ".githooks"
$configuredHooksPath = (& git -C $resolvedRoot config --get core.hooksPath 2>$null)
$hooksPathOk = ($LASTEXITCODE -eq 0) -and (($configuredHooksPath -join "").Trim() -eq $expectedHooksPath)
$preCommitHook = Join-Path $resolvedRoot ".githooks\pre-commit"
$qualityGateScript = Join-Path $resolvedRoot "scripts\local_quality_gate.py"
```

在 `$report.checks` 中加入：

```powershell
git_hooks_path = [PSCustomObject]@{
    ok = $hooksPathOk
    expected = $expectedHooksPath
    configured = (($configuredHooksPath -join "").Trim())
    repair = "git config core.hooksPath .githooks"
}
pre_commit_hook = [PSCustomObject]@{
    ok = (Test-Path $preCommitHook)
    path = $preCommitHook
}
local_quality_gate = [PSCustomObject]@{
    ok = (Test-Path $qualityGateScript)
    path = $qualityGateScript
}
```

将 `$allChecksOk` 纳入这三项；非 JSON 输出打印 configured/expected 与 repair，但不得调用 `git config` 写操作。

- [ ] **Step 5: 运行 doctor tests、静态写操作扫描与 diff hygiene**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py tests/test_environment_doctor.py -q`

Expected: 全部 PASS。

Run: `rg -n "git\s+config\s+core\.hooksPath" scripts/doctor.ps1`

Expected: 只命中 `repair` 字符串；不存在以 `& git ... config ... core.hooksPath` 执行写入的语句。

Run: `git diff --check`

Expected: exit 0。

- [ ] **Step 6: scoped commit**

```powershell
git add -- .githooks/pre-commit scripts/doctor.ps1 tests/test_environment_doctor.py tests/test_local_quality_gate.py
git commit -m "fix: wire local commit gate diagnostics"
```

---

### Task 5: Selector matrix 覆盖 gate-definition 与高频治理路径

**Files:**
- Modify: `tests/test_matrix.yaml`
- Modify: `tests/test_select_tests.py`
- Test: `tests/test_local_quality_gate.py`

**Interfaces:**
- Consumes: 现有 `select_tests(changed_files, matrix)` 返回结构。
- Produces: rule id `local-quality-gate`，只覆盖本任务 gate-definition 与对应 docs/tests，不引入 catch-all。

- [ ] **Step 1: 写精确 mapping 失败测试**

在 `tests/test_select_tests.py` 追加：

```python
def test_selector_matches_local_quality_gate_surfaces():
    result = select_tests.select_tests(
        [
            ".githooks/pre-commit",
            ".github/workflows/ci.yml",
            "scripts/doctor.ps1",
            "scripts/local_quality_gate.py",
            "tests/test_matrix.yaml",
        ],
        select_tests.load_matrix(),
    )

    rule = next(rule for rule in result["matchedRules"] if rule["id"] == "local-quality-gate")
    assert set(rule["matchedFiles"]) == {
        ".githooks/pre-commit",
        ".github/workflows/ci.yml",
        "scripts/doctor.ps1",
        "scripts/local_quality_gate.py",
        "tests/test_matrix.yaml",
    }
    assert any("tests/test_local_quality_gate.py" in command for command in result["commands"])
    assert any("tests/test_ci_workflow_contract.py" in command for command in result["commands"])
    assert any("tests/test_environment_doctor.py" in command for command in result["commands"])
    assert any("tests/test_select_tests.py" in command for command in result["commands"])
    assert "local-serial" in result["validationLayers"]
```

- [ ] **Step 2: 运行 selector test 并确认 rule 缺失**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_select_tests.py::test_selector_matches_local_quality_gate_surfaces -q`

Expected: FAIL，`StopIteration` 或 matched rule 中无 `local-quality-gate`。

- [ ] **Step 3: 添加窄范围 matrix rule**

在 `tests/test_matrix.yaml` 的 `rules:` 下加入：

```yaml
  - id: local-quality-gate
    description: "Local commit hook, closeout manifest, doctor, selector, and manual CI contracts."
    executionLayers:
      - "focused"
      - "local-serial"
    paths:
      - ".githooks/pre-commit"
      - ".github/workflows/ci.yml"
      - "scripts/doctor.ps1"
      - "scripts/local_quality_gate.py"
      - "tests/select_tests.py"
      - "tests/test_matrix.yaml"
      - "tests/test_local_quality_gate.py"
      - "tests/test_ci_workflow_contract.py"
      - "tests/test_environment_doctor.py"
      - "tests/test_select_tests.py"
      - "README.md"
      - "tests/README.md"
      - "DEVELOPMENT_STANDARD.md"
    commands:
      - ".\\.venv\\Scripts\\python.exe -m pytest tests/test_local_quality_gate.py tests/test_ci_workflow_contract.py tests/test_environment_doctor.py tests/test_select_tests.py -q"
    notes:
      - "Gate-definition changes must validate the gate itself even when the matrix changes in the same branch."
```

保留 `docs-only` rule；命令 dedupe 由现有 selector 处理。

- [ ] **Step 4: 运行 selector、matrix existence 与 gate parser tests**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_select_tests.py tests/test_local_quality_gate.py -q`

Expected: 全部 PASS；matrix 新命令可被 Task 2 allowlist 接受。

- [ ] **Step 5: scoped commit**

```powershell
git add -- tests/test_matrix.yaml tests/test_select_tests.py tests/test_local_quality_gate.py
git commit -m "test: map local quality gate validation"
```

---

### Task 6: 修复 manual CI 中不可达的 Ruff 门

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `tests/test_ci_workflow_contract.py`

**Interfaces:**
- Consumes: GitHub Actions `workflow_dispatch`、Ruff CLI。
- Produces: manual-only workflow contract；无 event-specific changed-files 分支。

- [ ] **Step 1: 写 workflow 文本契约失败测试**

创建 `tests/test_ci_workflow_contract.py`：

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_ci_remains_manual_only() -> None:
    text = workflow_text()
    trigger_block = text.split("concurrency:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "pull_request:" not in trigger_block
    assert "push:" not in trigger_block


def test_manual_ci_runs_reachable_fatal_ruff() -> None:
    text = workflow_text()
    assert "tj-actions/changed-files" not in text
    assert "github.event_name == 'pull_request'" not in text
    assert "python -m ruff check --select E9,F63,F7,F82 agent.py config core scripts tools" in text
```

- [ ] **Step 2: 运行 contract 并确认不可达 lint 失败**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_ci_workflow_contract.py -q`

Expected: `test_manual_ci_runs_reachable_fatal_ruff` FAIL，现有 workflow 包含 `tj-actions/changed-files` 与 PR-only 条件。

- [ ] **Step 3: 将 python-lint job 收敛成无条件 fatal Ruff**

保留 checkout、Python 3.11 与 Ruff install；删除 changed-files 与三条 skip step，替换为：

```yaml
      - name: Run fatal Ruff checks
        run: python -m ruff check --select E9,F63,F7,F82 agent.py config core scripts tools
```

不得修改 `on.workflow_dispatch`、Python test matrix 或 web job。

- [ ] **Step 4: 运行 workflow contract 与本地同命令**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_ci_workflow_contract.py -q`

Expected: `2 passed`。

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 agent.py config core scripts tools`

Expected: exit 0；如果发现既有 fatal error，仅修复该 fatal error 并把对应文件加入当前 claim，不扩大到 F401/F841。

- [ ] **Step 5: scoped commit**

```powershell
git add -- .github/workflows/ci.yml tests/test_ci_workflow_contract.py
git commit -m "fix: make manual fatal lint reachable"
```

---

### Task 7: 文档化本地独立开发、收口、合并与自清理

**Files:**
- Modify: `README.md` 的“快速开始”后新增“本地任务闭环”
- Modify: `tests/README.md` 的“使用影响面测试选择器”后新增“本地质量门”
- Modify: `DEVELOPMENT_STANDARD.md` sections 6、13、16

**Interfaces:**
- Consumes: 三个 CLI mode、manifest outcomes、现有 guard、worktree protocol。
- Produces: 用户与 Agent 共享的单一操作顺序；不新增脚本接口。

- [ ] **Step 1: 在 README 写首次配置与日常入口**

加入可直接复制的 PowerShell 示例：

```powershell
git config core.hooksPath .githooks
$claimId = $env:VIBELUTION_CLAIM_ID
if ([string]::IsNullOrWhiteSpace($claimId)) { throw "Set VIBELUTION_CLAIM_ID first." }
powershell -ExecutionPolicy Bypass -File scripts/doctor.ps1 -Json
& .\.venv\Scripts\python.exe scripts/local_quality_gate.py closeout --base main --claim-id $claimId
$taskId = (git branch --show-current).Replace("codex/", "")
& .\.venv\Scripts\python.exe scripts/local_quality_gate.py verify-manifest --manifest ".runtime/quality_gates/$taskId.json" --base main
```

正文明确：commit hook 快速且只看 staged；closeout 在 task worktree 运行；manifest passed 不等于已经 merge；remote push 不属于默认本地闭环。

- [ ] **Step 2: 在 tests README 写命令选择与 outcome 恢复表**

记录八个 outcome 与唯一下一步：

| Outcome | 操作 |
| --- | --- |
| `passed` | 复核 manifest 后进入本地 main fast-forward gate |
| `failed` | 修复首个失败命令并重跑 closeout |
| `stale_main` | 在任务 worktree 合并最新本地 main，解决冲突并重跑 |
| `claim_conflict` | 修正/续期本任务 claim，不使用其他任务 claim |
| `dirty_worktree` | 提交或撤回本任务未提交内容 |
| `merge_conflict` | 仅在任务 worktree 解决冲突 |
| `unsupported_validation_command` | 修正 matrix 为允许命令族，不放宽到 shell |
| `gate_definition_dirty` | 整文件 stage gate-definition 或拆成独立 commit |

- [ ] **Step 3: 更新 DEVELOPMENT_STANDARD 的强制闭环**

在 sections 6/13/16 明确以下顺序：

1. task branch 从当前本地 `main` 建立，普通开发不在 root main 进行；
2. 每次 commit 走 staged-content 轻门；
3. closeout 绑定 claim、`main` SHA、HEAD SHA、selector 命令与 merge preflight；
4. `main` 变化使 manifest 失效，冲突回 task worktree；
5. root main clean 且 SHA 未变化时执行 `git merge --ff-only $taskBranch`；
6. main 上做最小 post-merge verification；
7. release 本任务 claim，移除本任务 junction（存在时）、worktree 与 branch；
8. 不删除未完成任务的分支/worktree，所有任务完成后自然只剩 `main`。

同时写明 gate 不执行步骤 5-7，只提供验证证据。

- [ ] **Step 4: 运行文档契约扫描与 diff check**

Run: `rg -n "local_quality_gate.py|stale_main|ff-only|只清理本任务|workflow_dispatch" README.md tests/README.md DEVELOPMENT_STANDARD.md`

Expected: 三份文档均命中本地质量门；`DEVELOPMENT_STANDARD.md` 同时命中 `stale_main`、`ff-only` 与本任务自清理边界。

Run: `git diff --check`

Expected: exit 0。

- [ ] **Step 5: scoped commit**

```powershell
git add -- README.md tests/README.md DEVELOPMENT_STANDARD.md
git commit -m "docs: define local task closeout flow"
```

---

### Task 8: 集成验证、真实 smoke 与本地 main 收口

**Files:**
- Test: `tests/test_local_quality_gate.py`
- Test: `tests/test_ci_workflow_contract.py`
- Test: `tests/test_environment_doctor.py`
- Test: `tests/test_select_tests.py`
- Verify: `.runtime/quality_gates/local-quality-gate-closure.json`（ignored evidence，不提交）

**Interfaces:**
- Consumes: 全部已提交实现与本任务有效 claim。
- Produces: fresh passed manifest、fast-forward-ready commit range；merge 与清理由任务所有者在 gate 外执行。

- [ ] **Step 1: 复核实现 claim、main 与 worktree 前置状态**

```powershell
$status = & $python $guard $root status --json | ConvertFrom-Json
$implementationClaim = $status.claims | Where-Object {
  $_.id -eq $env:VIBELUTION_CLAIM_ID -and $_.status -eq 'active'
} | Select-Object -First 1
if ($null -eq $implementationClaim) { throw 'Implementation claim is missing, expired, or inactive.' }
if ((git branch --show-current) -ne 'codex/local-quality-gate-closure') { throw 'Wrong task branch.' }
if ((git -C $root branch --show-current) -ne 'main') { throw 'Root integration checkout is not on main.' }
```

Expected: claim active，当前 worktree branch 正确，root checkout 仍在 `main`。

- [ ] **Step 2: 运行聚焦 gate suite**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py tests/test_ci_workflow_contract.py tests/test_environment_doctor.py tests/test_select_tests.py -q`

Expected: 全部 PASS，无 skip；PowerShell doctor tests 在 Windows 本地执行。

- [ ] **Step 3: 运行 fatal Ruff 与 diff hygiene**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 agent.py config core scripts tools`

Expected: exit 0。

Run: `git diff --check main...HEAD`

Expected: exit 0。

- [ ] **Step 4: 运行真实 commit-mode smoke**

在临时 Git repository 中复制 `.githooks/pre-commit` 与 `scripts/local_quality_gate.py`，设置 `core.hooksPath=.githooks`，分别提交合法 Python 和 staged syntax error：

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py::test_commit_mode_lints_staged_blob_instead_of_worktree -q
```

Expected: test PASS；合法提交 exit 0，syntax error 提交 exit non-zero 且不生成 commit。

- [ ] **Step 5: 运行本任务 closeout 并验证 manifest**

Run: `& .\.venv\Scripts\python.exe scripts/local_quality_gate.py closeout --base main --claim-id $env:VIBELUTION_CLAIM_ID`

Expected: exit 0，`.runtime/quality_gates/local-quality-gate-closure.json` 的 `outcome` 为 `passed`，`validatedMainSha` 等于当时 root local main SHA，`headSha` 等于当前 branch HEAD。

Run: `& .\.venv\Scripts\python.exe scripts/local_quality_gate.py verify-manifest --manifest .runtime/quality_gates/local-quality-gate-closure.json --base main`

Expected: exit 0；若为 `stale_main`，先在 task worktree 收敛最新 main 并从 Step 2 重新验证。

- [ ] **Step 6: 自审 commit range**

Run: `git diff --stat main...HEAD`

Expected: 只包含文件责任图列出的 12 个实现文件，加上已批准的 design spec 与本 implementation plan，共 14 个 tracked 文件；无 `.runtime`、版本文件、依赖文件、应用源码或前端源码。

Run: `git diff main...HEAD -- docs/superpowers/specs/2026-07-10-local-quality-gate-closure-design.md docs/superpowers/plans/2026-07-10-local-quality-gate-closure.md .githooks/pre-commit .github/workflows/ci.yml scripts/local_quality_gate.py scripts/doctor.ps1 tests/test_local_quality_gate.py tests/test_ci_workflow_contract.py tests/test_environment_doctor.py tests/test_matrix.yaml tests/test_select_tests.py README.md tests/README.md DEVELOPMENT_STANDARD.md`

Expected: 无 shell 执行、无 merge/delete/release 行为、无 secret/full-output 持久化、无自动 CI trigger。

- [ ] **Step 7: 在 root local main 执行 fast-forward merge**

仅当 manifest 仍有效、root main clean、claim 无冲突时，在 `C:\Users\17533\Desktop\Vibelution` 执行：

```powershell
git merge --ff-only codex/local-quality-gate-closure
```

Expected: fast-forward 成功；若失败，不在 root main 解冲突，返回 task worktree 同步 main 并重跑 Step 2-6。

- [ ] **Step 8: main 上做最小 post-merge verification**

Run: `& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests/test_local_quality_gate.py tests/test_ci_workflow_contract.py tests/test_environment_doctor.py tests/test_select_tests.py -q`

Expected: 全部 PASS。

Run: `git status --short --branch`

Expected: branch 为 `main`；当前任务影响文件无 dirty change。若 root 原本存在无关 dirty change，保持原状并明确记录，不覆盖或清理。

- [ ] **Step 9: 完成 implementation claim，并序列化项目记忆**

main 上的 Step 8 通过后，先完成 implementation claim，再为 memory 单写入建立独立 claim：

```powershell
& $python $guard $root release --claim-id $env:VIBELUTION_CLAIM_ID --status completed --reason 'Merged local quality gate and passed post-merge focused verification.'
$memoryScopes = @('.docs/project-memory/**', 'PROJECT_MEMORY.html')
$memoryScopeArgs = foreach ($scope in $memoryScopes) { '--scope'; $scope }
$memoryCheck = & $python $guard $root check --lane project-memory-governance @memoryScopeArgs --json | ConvertFrom-Json
if (-not $memoryCheck.ok) { throw ($memoryCheck.conflicts | ConvertTo-Json -Depth 8) }
if (git -C $root status --short -- .docs/project-memory PROJECT_MEMORY.html) { throw 'Project memory has unrelated dirty changes.' }
$memoryClaim = & $python $guard $root claim --lane project-memory-governance @memoryScopeArgs --agent codex-local-quality-gate --task 'Record local quality gate closure' --status active --ttl-minutes 60 --json | ConvertFrom-Json
if (-not $memoryClaim.ok) { throw ($memoryClaim.conflicts | ConvertTo-Json -Depth 8) }
$memoryClaimId = $memoryClaim.claim.id

& $python 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py' $root --lane quality-and-operations --lane-title 'Quality and Operations' --owner codex-local-quality-gate --focus 'Local commit and closeout quality gates' --phase completed --health green --update 'Added staged-content commit gate, claim-bound closeout manifest, stale-main detection, manual fatal Ruff, and task-owned cleanup protocol.'
git -C $root diff --check -- .docs/project-memory PROJECT_MEMORY.html
git -C $root add -- .docs/project-memory PROJECT_MEMORY.html
git -C $root commit -m 'docs: record local quality gate closure'
& $python $guard $root release --claim-id $memoryClaimId --status completed --reason 'Synced quality-and-operations memory after main verification.'
```

Expected: memory sync commit 成功，两个本任务 claim 都 completed，其他 claims 不变。

- [ ] **Step 10: 安全移除 junction、worktree 与本任务 branch**

确认 task worktree tracked clean 后，先验证并删除 junction 本身，再从 root 移除 worktree：

```powershell
$venvLink = 'C:\Users\17533\Desktop\Vibelution-worktrees\local-quality-gate-closure\.venv'
$worktree = 'C:\Users\17533\Desktop\Vibelution-worktrees\local-quality-gate-closure'
if (git -C $worktree status --short) { throw 'Task worktree is not clean.' }
$item = Get-Item -LiteralPath $venvLink -Force
if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) { throw '.venv is not a junction.' }
if (-not $item.FullName.StartsWith('C:\Users\17533\Desktop\Vibelution-worktrees\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Junction is outside worktree root.' }
[System.IO.Directory]::Delete($item.FullName)
Set-Location -LiteralPath $root
git worktree remove 'C:\Users\17533\Desktop\Vibelution-worktrees\local-quality-gate-closure'
git branch -d codex/local-quality-gate-closure
```

Expected: 只移除本任务 worktree/branch；`git worktree list --porcelain` 与 `git branch --list` 仍保留所有未完成任务，所有任务各自完成后最终只剩 `main`。

---

## 规格覆盖自检

| 规格要求 | 实现任务 |
| --- | --- |
| staged blob、fatal Ruff、gate-definition 完整 staging | Task 1 |
| 命令族白名单、argv/cwd、拒绝 shell | Task 2 |
| clean/claim/SHA/selector/preflight/manifest/outcomes | Task 3 |
| hook 无策略、doctor 只读修复提示 | Task 4 |
| 单一 matrix 与 gate 自测强制注入 | Task 5 |
| manual-only CI 与可达 fatal Ruff | Task 6 |
| 本地 main、stale-main、冲突回 worktree、自清理 | Task 7 |
| fresh evidence、ff-only merge、post-merge、memory/claim/cleanup | Task 8 |

实现期间每个 task 都必须先看到测试失败，再做最小实现并运行通过；不得把多个 task 累积到一个大 commit。
