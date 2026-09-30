"""读取 `%LOCALAPPDATA%\\Vibelution\\instances.json` 实例注册表并判定就绪/关闭状态。

运行权威与字段语义见 docs/guides/launcher-branch-development.md：
就绪 = ``desiredState=="open"``、``status``/``phase=="steady"``、
``spawnPid != 0``、``portLeaseStatus=="held"``；
关闭 = ``status``/``phase=="closed"``、``spawnPid`` 归零。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

REGISTRY_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "Vibelution" / "instances.json"

READY_DEADLINE_SECONDS = 180.0
CLOSED_DEADLINE_SECONDS = 120.0
POLL_INTERVAL_SECONDS = 2.0


class InstanceRegistryError(RuntimeError):
    """注册表缺失、不可解析或目标条目缺失。"""


def normalize_path(value: str | os.PathLike[str]) -> str:
    """Windows 路径统一为大小写/分隔符无关的可比较形式。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(value))))


def load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        raise InstanceRegistryError(f"实例注册表不存在: {REGISTRY_PATH}")
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstanceRegistryError(f"实例注册表不可解析: {REGISTRY_PATH} ({exc})") from exc
    instances = data.get("instances")
    if not isinstance(instances, dict):
        raise InstanceRegistryError(f"实例注册表缺少 instances map: {REGISTRY_PATH}")
    return data


def find_entry(project_root: str | os.PathLike[str]) -> tuple[str, dict[str, Any]]:
    """按 projectRoot 精确（大小写无关）匹配实例条目。"""
    wanted = normalize_path(project_root)
    registry = load_registry()
    for key, entry in registry["instances"].items():
        if isinstance(entry, dict) and normalize_path(entry.get("projectRoot", "")) == wanted:
            return key, entry
    known = "\n".join(
        f"  {k}: {v.get('status')} {v.get('projectRoot')}"
        for k, v in list(registry["instances"].items())[-8:]
    )
    raise InstanceRegistryError(
        f"注册表中没有 projectRoot=={project_root} 的条目（registry={REGISTRY_PATH}）。\n最近条目:\n{known}"
    )


def entry_is_ready(entry: dict[str, Any]) -> bool:
    return (
        entry.get("desiredState") == "open"
        and entry.get("status") == "steady"
        and entry.get("phase") == "steady"
        and bool(entry.get("spawnPid"))
        and entry.get("portLeaseStatus") == "held"
    )


def entry_is_closed(entry: dict[str, Any]) -> bool:
    """实例已完全停止。

    实测与 core/launcher/service.py 的投影语义一致：stop 完成后
    ``desiredState=="closed"``、``status=="closed"``、``spawnPid==0``、端口租约
    退出 held；``phase`` 停留为 "steady"（表示无在飞迁移），并非 "closed"。
    """
    phase = str(entry.get("phase") or "").strip().lower()
    return (
        entry.get("desiredState") == "closed"
        and entry.get("status") == "closed"
        and phase in {"", "steady", "closed"}
        and not entry.get("spawnPid")
        and entry.get("portLeaseStatus") != "held"
    )


def describe_entry(entry: dict[str, Any]) -> str:
    fields = (
        "desiredState", "status", "phase", "spawnPid", "portLeaseStatus",
        "port", "generation", "failureMessage", "updatedAt",
    )
    return json.dumps({k: entry.get(k) for k in fields if k in entry}, ensure_ascii=False)


def wait_for_entry(
    project_root: str | os.PathLike[str],
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_seconds: float,
    what: str,
) -> dict[str, Any]:
    """轮询注册表直到条目满足谓词；条目暂时缺失（刚 start）也算未就绪，继续轮询。"""
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] | None = None
    missing_error: str = ""
    while time.monotonic() < deadline:
        try:
            _, entry = find_entry(project_root)
        except InstanceRegistryError as exc:
            missing_error = str(exc)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        last = entry
        if predicate(entry):
            return entry
        time.sleep(POLL_INTERVAL_SECONDS)
    evidence = describe_entry(last) if last is not None else (missing_error or "条目从未出现")
    log_dir = launcher_log_dir_hint(project_root)
    raise InstanceRegistryError(
        f"等待{what}超时（{timeout_seconds:.0f}s）。registry={REGISTRY_PATH}\n"
        f"当前条目: {evidence}\nlauncher 日志目录线索: {log_dir}"
    )


def launcher_log_dir_hint(project_root: str | os.PathLike[str]) -> str:
    """从 dataHome 推导该实例的 launcher 运行日志目录（存在与否都只作证据线索）。"""
    try:
        _, entry = find_entry(project_root)
    except InstanceRegistryError:
        return str(Path(os.environ.get("LOCALAPPDATA", "")) / "Vibelution" / "projects" / "*" / "instances" / "*" / "runtime" / "launcher")
    data_home = entry.get("dataHome")
    if not data_home:
        return "(registry entry 无 dataHome)"
    return str(Path(data_home).parent / "runtime" / "launcher")


_CONTROL_TOKEN_PATH = "/api/control-token"
_DEFAULT_CONTROL_TOKEN_HEADER = "X-Vibelution-Control-Token"

# token 按 port 缓存（一次会话一个实例）；403 时清缓存重取一次。
_token_cache: dict[int, str] = {}


def _http_get_json(port: int, path: str, headers: dict[str, str] | None = None, timeout_seconds: float = 15.0) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise InstanceRegistryError(f"GET {path} 返回 HTTP {exc.code}: {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise InstanceRegistryError(f"GET {path} 不可达: {url} ({exc})") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise InstanceRegistryError(f"GET {path} 响应非 JSON: body[:200]={body[:200]!r}") from exc


def control_token(port: int, *, refresh: bool = False) -> str:
    """经免鉴权引导端点 /api/control-token 取控制令牌（后端 guard 的官方口径）。

    前端（web/src/api/client.ts）同样从该端点 bootstrap 后在 API 头携带。
    """
    if not refresh:
        cached = _token_cache.get(port)
        if cached:
            return cached
    payload = _http_get_json(port, _CONTROL_TOKEN_PATH)
    token = str(payload.get("controlToken") or "").strip()
    if not token:
        raise InstanceRegistryError(f"{_CONTROL_TOKEN_PATH} 未返回 controlToken: {json.dumps(payload)[:200]}")
    _token_cache[port] = token
    return token


def fetch_json(port: int, path: str, timeout_seconds: float = 15.0) -> dict[str, Any]:
    """GET ``http://127.0.0.1:<port><path>``（携带控制令牌）并解析 JSON。

    令牌失效（后端重启等）导致 403 时自动刷新重试一次。
    """
    try:
        return _http_get_json(
            port,
            path,
            headers={_DEFAULT_CONTROL_TOKEN_HEADER: control_token(port)},
            timeout_seconds=timeout_seconds,
        )
    except InstanceRegistryError as exc:
        if "HTTP 403" not in str(exc):
            raise
    _token_cache.pop(port, None)
    return _http_get_json(
        port,
        path,
        headers={_DEFAULT_CONTROL_TOKEN_HEADER: control_token(port, refresh=True)},
        timeout_seconds=timeout_seconds,
    )


def fetch_health(port: int, timeout_seconds: float = 10.0) -> dict[str, Any]:
    """GET /api/health，返回解析后的 JSON（非 200 或不可达抛错）。"""
    url = f"http://127.0.0.1:{port}/api/health"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise InstanceRegistryError(f"health 返回 HTTP {exc.code}: {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise InstanceRegistryError(f"health 不可达: {url} ({exc})") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise InstanceRegistryError(f"health 响应非 JSON: {url} body[:200]={body[:200]!r}") from exc


def assert_health_serves_worktree(
    health: dict[str, Any],
    project_root: str | os.PathLike[str],
    *,
    data_home: str | os.PathLike[str],
) -> None:
    """就绪二次确认：代码、数据根和前端构建均属于目标实例。"""
    problems: list[str] = []
    if health.get("routesReady") is not True:
        problems.append(f"routesReady={health.get('routesReady')!r}")
    serving = health.get("serving") or {}
    frontend = serving.get("frontend") or {}
    workspace_root = health.get("workspaceRoot")
    if normalize_path(workspace_root or "") != normalize_path(project_root):
        problems.append(f"workspaceRoot={workspace_root!r} != {project_root}")
    from vibelution_storage import ProjectIdentityError, load_project_identity

    try:
        load_project_identity(project_root)
    except ProjectIdentityError as exc:
        problems.append(f"project identity 无效: {exc}")
    if not str(data_home or "").strip():
        problems.append("registry dataHome 为空")
    else:
        expected_storage = Path(data_home) / "workspace"
        storage_root = health.get("storageWorkspaceRoot")
        if normalize_path(storage_root or "") != normalize_path(expected_storage):
            problems.append(f"storageWorkspaceRoot={storage_root!r} != {expected_storage}")
    if not frontend.get("builtFromCommit"):
        problems.append(f"serving.frontend.builtFromCommit 为空: {frontend!r}")
    if problems:
        raise InstanceRegistryError(
            "health 未达到就绪口径: " + "; ".join(problems) + f"\n完整 health: {json.dumps(health, ensure_ascii=False)[:800]}"
        )
