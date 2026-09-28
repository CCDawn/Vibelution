"""确保 worktree 的 ``web/dist`` 前端产物存在：junction node_modules + 一次性 npm build。

worktree 只检出被追踪文件，``web/node_modules`` 与 ``web/dist`` 都不存在。
本模块：
1. 用 junction 把根 checkout 的 ``web/node_modules`` 映射进 worktree（不复制、不改动根）；
2. ``npm run build`` 一次，成功后写 stamp（HEAD + 时间戳）；
3. stamp 存在、HEAD 未变且 ``dist/index.html`` 在场时跳过重建。

根 checkout 定位用 ``git rev-parse --git-common-dir``，不假设固定盘符/用户名。
所有子进程 ``CREATE_NO_WINDOW``。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tests.e2e.helpers.instance_registry import InstanceRegistryError, normalize_path

BUILD_TIMEOUT_SECONDS = 900.0


def stamp_path_for(worktree_root: Path) -> Path:
    """stamp 落在 %LOCALAPPDATA%\\Vibelution\\e2e\\build-stamps\\（按 worktree 哈希），
    不写 checkout 根，避免污染 git status。"""
    import hashlib

    digest = hashlib.sha1(str(worktree_root).lower().encode("utf-8")).hexdigest()[:16]
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Vibelution" / "e2e" / "build-stamps"
    return base / f"{digest}.json"

_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass(frozen=True)
class WebBuildResult:
    worktree_web: Path
    dist_dir: Path
    stamp_path: Path
    rebuilt: bool
    head: str


def _run_capture(argv: list[str], cwd: Path, *, timeout_seconds: float, what: str) -> str:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=_CREATION_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstanceRegistryError(f"{what} 超时（{timeout_seconds:.0f}s）: cwd={cwd}") from exc
    except OSError as exc:
        raise InstanceRegistryError(f"{what} 无法启动: {argv!r} ({exc})") from exc
    if completed.returncode != 0:
        raise InstanceRegistryError(
            f"{what} 失败（exit={completed.returncode}）: cwd={cwd}\n"
            f"stdout tail: {(completed.stdout or '')[-600:]!r}\n"
            f"stderr tail: {(completed.stderr or '')[-600:]!r}"
        )
    return (completed.stdout or "").strip()


def resolve_root_checkout(worktree_root: Path) -> Path:
    git_common_dir = _run_capture(
        ["git", "rev-parse", "--git-common-dir"], worktree_root, timeout_seconds=30, what="git rev-parse --git-common-dir"
    )
    common = Path(git_common_dir)
    if not common.is_absolute():
        common = (worktree_root / common).resolve()
    return common.parent


def current_head(worktree_root: Path) -> str:
    return _run_capture(["git", "rev-parse", "HEAD"], worktree_root, timeout_seconds=30, what="git rev-parse HEAD")


def ensure_node_modules_junction(worktree_root: Path) -> Path:
    """把根 checkout 的 web/node_modules junction 到 worktree；已是 junction 或真实目录则原样返回。"""
    worktree_web = worktree_root / "web"
    destination = worktree_web / "node_modules"
    if destination.exists() or destination.is_symlink():
        return destination
    root_checkout = resolve_root_checkout(worktree_root)
    source = root_checkout / "web" / "node_modules"
    if not source.is_dir():
        raise InstanceRegistryError(
            f"根 checkout 缺少 web/node_modules，无法 junction：{source}（先在根 checkout 安装依赖）"
        )
    if os.name != "nt":
        os.symlink(source, destination, target_is_directory=True)
        return destination
    import _winapi

    _winapi.CreateJunction(str(source), str(destination))
    return destination


def _stamp_valid(stamp_path: Path, dist_dir: Path, head: str) -> bool:
    if not (dist_dir / "index.html").is_file() or not stamp_path.is_file():
        return False
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return normalize_path(stamp.get("head", "")) == normalize_path(head)


def ensure_web_build(worktree_root: Path, *, force: bool = False) -> WebBuildResult:
    """保证 worktree 前端产物可用；默认 stamp 命中即跳过，``force`` 强制重建。"""
    worktree_root = Path(worktree_root).resolve()
    worktree_web = worktree_root / "web"
    dist_dir = worktree_web / "dist"
    stamp_path = stamp_path_for(worktree_root)
    head = current_head(worktree_root)

    if not force and _stamp_valid(stamp_path, dist_dir, head):
        return WebBuildResult(worktree_web, dist_dir, stamp_path, rebuilt=False, head=head)

    ensure_node_modules_junction(worktree_root)
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise InstanceRegistryError("PATH 上找不到 npm（npm.cmd），无法构建 web 前端")
    started = time.monotonic()
    _run_capture(
        [npm, "run", "build"], worktree_web, timeout_seconds=BUILD_TIMEOUT_SECONDS, what="npm run build（web 前端）"
    )
    if not (dist_dir / "index.html").is_file():
        raise InstanceRegistryError(f"npm run build 返回 0 但缺 {dist_dir / 'index.html'}，构建产物不完整")

    stamp = {"head": head, "builtAtUnix": time.time(), "buildSeconds": round(time.monotonic() - started, 1),
             "worktreeRoot": str(worktree_root)}
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8")
    return WebBuildResult(worktree_web, dist_dir, stamp_path, rebuilt=True, head=head)
