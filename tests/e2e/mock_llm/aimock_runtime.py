# -*- coding: utf-8 -*-
"""aimock（@copilotkit/aimock）进程运行时：安装、端口、生命周期、journal/reset。

职责边界（详见 docs/guides/e2e-mock-llm.md）：
- 一次性安装到 ``%LOCALAPPDATA%\\Vibelution\\e2e\\aimock``（固定版本 + stamp 防重装；
  首次安装需要网络，离线时报错并给出预装命令）；
- 空闲端口发现、node 直调 cli.js 启动（绕开 npm cmd shim）、``CREATE_NO_WINDOW``；
- ``GET /health`` 就绪轮询、journal 读取、journal-only reset；
- 会话结束干净拆机：terminate → wait → kill → wait，杀不死要报告（禁 taskkill）。

已实测事实（spike 证据 %LOCALAPPDATA%\\Temp\\aimock-spike，直接采用）：
- 包 ``@copilotkit/aimock@1.43.0``（MIT，node >= 20.15）；
- ``POST /__aimock/reset`` 会清空**全部** fixture（含 --fixtures 文件加载的），
  不能在测试间使用；测试间隔离用 ``POST /__aimock/reset/journal``（只清 journal
  条目，保留 sequence 计数）+ 每条用例独立的 userMessage 标记；
- ``GET /__aimock/journal`` 支持 ``path=`` / ``status=`` 查询参数。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

AIMOCK_PACKAGE = "@copilotkit/aimock"
AIMOCK_VERSION = "1.43.0"
AIMOCK_NODE_MIN = (20, 15)

INSTALL_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Vibelution" / "e2e" / "aimock"
)
INSTALL_STAMP = INSTALL_ROOT / "aimock-install-stamp.json"

INSTALL_TIMEOUT_SECONDS = 300.0
HEALTH_TIMEOUT_SECONDS = 30.0
TERMINATE_GRACE_SECONDS = 15.0
KILL_GRACE_SECONDS = 5.0

# 测试基础设施同样遵守产品无控制台红线：子进程一律隐藏窗口。
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class AimockError(RuntimeError):
    """aimock 安装、启动或控制面访问失败。"""


# ---------------------------------------------------------------------------
# 安装
# ---------------------------------------------------------------------------


def ensure_aimock_installed() -> Path:
    """返回 aimock cli.js 绝对路径；stamp 命中时零网络零安装。"""
    cli = INSTALL_ROOT / "node_modules" / AIMOCK_PACKAGE / "dist" / "cli.js"
    if cli.is_file():
        stamp = _read_stamp()
        if stamp and stamp.get("version") == AIMOCK_VERSION:
            return cli
    _install_aimock()
    if not cli.is_file():
        raise AimockError(
            f"npm install 后仍找不到 {cli}；请检查 npm 输出或手动预装后重跑。\n"
            f"预装命令：npm install --prefix \"{INSTALL_ROOT}\" {AIMOCK_PACKAGE}@{AIMOCK_VERSION}"
        )
    _write_stamp()
    return cli


def _read_stamp() -> dict[str, Any] | None:
    try:
        data = json.loads(INSTALL_STAMP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_stamp() -> None:
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    INSTALL_STAMP.write_text(
        json.dumps(
            {
                "package": AIMOCK_PACKAGE,
                "version": AIMOCK_VERSION,
                "installedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _resolve_node() -> Path:
    found = os.environ.get("VIBELUTION_E2E_NODE") or ""
    node = Path(found) if found else Path()
    if not found:
        which = _which("node")
        if not which:
            raise AimockError(
                "未找到 node（aimock 需要 node >= "
                f"{AIMOCK_NODE_MIN[0]}.{AIMOCK_NODE_MIN[1]}）。请安装 Node.js 或设置 "
                "VIBELUTION_E2E_NODE 指向 node.exe 后重跑。"
            )
        node = Path(which)
    return node


def _which(name: str) -> str:
    path_env = os.environ.get("PATH", "")
    exts = (".exe", ".cmd", ".bat", "") if os.name == "nt" else ("",)
    for directory in path_env.split(os.pathsep):
        if not directory.strip():
            continue
        for ext in exts:
            candidate = Path(directory) / f"{name}{ext}"
            if candidate.is_file():
                return str(candidate)
    return ""


def _install_aimock() -> None:
    node = _resolve_node()
    npm_cli = node.parent.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if npm_cli.is_file():
        argv = [
            str(node),
            str(npm_cli),
            "install",
            "--prefix",
            str(INSTALL_ROOT),
            "--no-audit",
            "--no-fund",
            "--loglevel=error",
            f"{AIMOCK_PACKAGE}@{AIMOCK_VERSION}",
        ]
    else:  # node 布局异常时退回 npm shim（仍隐藏窗口）
        npm = _which("npm")
        if not npm:
            raise AimockError(
                "未找到 npm，无法安装 aimock。请手动预装后重跑：\n"
                f"npm install --prefix \"{INSTALL_ROOT}\" {AIMOCK_PACKAGE}@{AIMOCK_VERSION}"
            )
        argv = [npm, "install", "--prefix", str(INSTALL_ROOT), "--no-audit", "--no-fund", "--loglevel=error",
                f"{AIMOCK_PACKAGE}@{AIMOCK_VERSION}"]
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=INSTALL_TIMEOUT_SECONDS,
            creationflags=_CREATION_FLAGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AimockError(
            f"npm install aimock 超时（{INSTALL_TIMEOUT_SECONDS:.0f}s）。"
            "首次安装需要网络；若本机离线，请先在有网环境预装：\n"
            f"npm install --prefix \"{INSTALL_ROOT}\" {AIMOCK_PACKAGE}@{AIMOCK_VERSION}"
        ) from exc
    except OSError as exc:
        raise AimockError(f"npm install aimock 启动失败: {exc}") from exc
    if completed.returncode != 0:
        raise AimockError(
            "npm install aimock 失败（退出码 "
            f"{completed.returncode}）。首次安装需要网络；若本机离线，请先预装：\n"
            f"npm install --prefix \"{INSTALL_ROOT}\" {AIMOCK_PACKAGE}@{AIMOCK_VERSION}\n"
            f"stderr tail: {(completed.stderr or '')[-400:]!r}"
        )


# ---------------------------------------------------------------------------
# 端口与 HTTP 控制面
# ---------------------------------------------------------------------------


def find_free_port() -> int:
    """向内核申请一个 127.0.0.1 空闲端口（绑定后立即释放，存在理论竞态但足够）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    except (urllib.error.URLError, OSError) as exc:
        raise AimockError(f"{method} {url} 不可达: {exc}") from exc
    if not body:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body


# ---------------------------------------------------------------------------
# 进程生命周期
# ---------------------------------------------------------------------------


class AimockServer:
    """一个 aimock node 子进程；会话内复用，结束后必须 :meth:`stop`。

    两种启动形态：
    - ``fixtures`` 模式：node 直调 ``dist/cli.js --fixtures <目录>``（JSON 剧本，
      ``userMessage`` 匹配末条 user 消息，适合直连 litellm 级验证）；
    - ``runner`` 模式：node 跑 ``scenarios/runner.mjs``（程序化剧本，在完整
      messages 上做标记路由——产品主聊天调用的末条 user 消息是 Turn Status Bar
      遥测尾巴，JSON 剧本路由不到它，产品 UI 车道必须用 runner）。
    """

    def __init__(
        self,
        fixtures_dir: str | os.PathLike[str],
        *,
        host: str = "127.0.0.1",
        log_level: str = "info",
        script: str | os.PathLike[str] | None = None,
    ) -> None:
        self.host = host
        self.fixtures_dir = Path(fixtures_dir).resolve()
        self.script = Path(script).resolve() if script else None
        self.log_level = log_level
        self.port = find_free_port()
        self.base_url = f"http://{host}:{self.port}"
        self.proc: subprocess.Popen[str] | None = None
        self.log_path: Path | None = None

    def start(self) -> None:
        cli = ensure_aimock_installed()
        node = _resolve_node()
        handle, log_name = tempfile.mkstemp(prefix="aimock-e2e-", suffix=".log")
        os.close(handle)
        self.log_path = Path(log_name)
        if self.script is not None:
            # runner 模式：node 直跑剧本脚本（绕开 npm cmd shim），安装根经环境变量
            # 传给脚本做包解析。
            argv = [
                str(node),
                str(self.script),
                "--port",
                str(self.port),
                "--host",
                self.host,
            ]
            env = dict(os.environ)
            env["AIMOCK_INSTALL_ROOT"] = str(cli.parents[2])
        else:
            argv = [
                str(node),
                str(cli),
                "--port",
                str(self.port),
                "--host",
                self.host,
                "--fixtures",
                str(self.fixtures_dir),
                "--log-level",
                self.log_level,
            ]
            env = None
        log_handle = open(self.log_path, "ab")
        try:
            self.proc = subprocess.Popen(
                argv,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=_CREATION_FLAGS,
                env=env,
            )
        finally:
            log_handle.close()
        self._wait_health()

    def _wait_health(self) -> None:
        deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise AimockError(
                    f"aimock 进程提前退出（code={self.proc.returncode}）。日志: {self.log_path}"
                )
            try:
                status, _ = _request_json("GET", f"{self.base_url}/health", timeout_seconds=2.0)
                if status == 200:
                    return
            except AimockError as exc:
                last_error = exc
            time.sleep(0.25)
        raise AimockError(
            f"aimock /health 在 {HEALTH_TIMEOUT_SECONDS:.0f}s 内未就绪（port={self.port}）。"
            f"日志: {self.log_path}；最后错误: {last_error}"
        )

    # -- 控制面 ---------------------------------------------------------------

    def journal(
        self,
        *,
        path: str | None = None,
        status: int | str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """GET /__aimock/journal，返回条目数组（支持 path/status/limit 过滤）。"""
        query: list[str] = []
        if path:
            query.append(f"path={urllib.request.quote(path, safe='')}")
        if status is not None:
            query.append(f"status={status}")
        if limit is not None:
            query.append(f"limit={limit}")
        suffix = f"?{'&'.join(query)}" if query else ""
        _, payload = _request_json("GET", f"{self.base_url}/__aimock/journal{suffix}")
        return payload if isinstance(payload, list) else []

    def reset_journal(self) -> None:
        """POST /__aimock/reset/journal：清空 journal 条目，保留 fixture 与 sequence 计数。

        注意不要用 POST /__aimock/reset：那会把 ``--fixtures`` 加载的剧本一并清空。
        """
        status, _ = _request_json("POST", f"{self.base_url}/__aimock/reset/journal", payload={})
        if status != 200:
            raise AimockError(f"reset/journal 返回 HTTP {status}")

    # -- 拆机 -----------------------------------------------------------------

    def stop(self) -> None:
        """terminate → wait → kill → wait；杀不死要报告（抛错），不使用 taskkill。

        保留 ``self.proc`` 引用，让 :meth:`assert_stopped` 能基于真实退出状态出证据
        （不要先置 None——那会让断言空转）。
        """
        proc = self.proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=KILL_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    raise AimockError(
                        f"aimock 进程 terminate+kill 后仍存活 pid={proc.pid}，需要人工排查"
                    ) from None
        # Windows terminate 后返回码非 0（1/15 等）属正常；已退出即视为收口。
        print(f"[mock_llm] aimock 进程已退出 pid={proc.pid} code={proc.returncode}")

    def assert_stopped(self) -> None:
        """拆机证据：进程对象确认已退出；未启动过则无证据可出，同样报错。"""
        proc = self.proc
        if proc is None:
            raise AimockError("aimock 从未启动，缺少拆机证据")
        code = proc.poll()
        if code is None:
            raise AimockError(f"aimock 进程仍存活 pid={proc.pid}")


def start_aimock(fixtures_dir: str | os.PathLike[str], *, script: str | os.PathLike[str] | None = None) -> AimockServer:
    """便捷封装：创建 + 启动 + 健康轮询。``script`` 给定时走 runner（程序化剧本）。"""
    server = AimockServer(fixtures_dir, script=script)
    server.start()
    mode = "runner" if script else "fixtures"
    print(f"[mock_llm] aimock({mode}) 就绪 {server.base_url}")
    return server
