"""Playwright e2e 手动车道（真实分支实例）的 pytest 挂载。

关键约束（见 docs/guides/e2e-playwright.md 与 pytest.ini 注释）：
- ``e2e`` marker 已被刻意删除，**禁止重新注册**；本目录所有模块用现有
  ``serial`` marker + ``skipif`` 环境门（``VIBELUTION_E2E != "1"`` 时逐条 skip，
  退出码 0）。默认/serial 收集到也只会 skip。注意不能用模块级
  ``pytest.skip(allow_module_level=True)``——那会零收集，closeout 选择器
  直跑本目录文件时 pytest 退出码 5 判失败。
- 生命周期用官方 Launcher：start → registry steady/open → health 就绪口径 →
  测试 → stop → registry closed/closed。不用 taskkill，不弹可见控制台。
- playwright 在 fixture 内导入，保证其他车道 import 本 conftest 不依赖 playwright。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent
WORKTREE_ROOT = E2E_DIR.parent.parent

READY_TIMEOUT_SECONDS = 200.0
CLOSED_TIMEOUT_SECONDS = 120.0


def e2e_enabled() -> bool:
    return os.environ.get("VIBELUTION_E2E") == "1"


@dataclass
class E2EInstance:
    """一次会话级分支实例的运行事实。"""

    port: int
    base_url: str
    instance_id: str
    project_root: Path
    data_home: str
    health: dict = field(default_factory=dict)

    def api_get(self, path: str) -> dict:
        """对实例后端做只读 GET 并解析 JSON（测试里用于守卫判定等）。"""
        from tests.e2e.helpers.instance_registry import fetch_json

        return fetch_json(self.port, path)


def _resolve_data_home(entry: dict) -> str:
    """实例数据目录：优先产品自己的解析函数，registry 条目兜底。"""
    try:
        # tests/conftest.py 已把 worktree 根插入 sys.path；该函数即产品 launcher
        # 给实例分配 dataHome 的同一实现（core/launcher/slot_identity.py）。
        from core.launcher.slot_identity import data_home_for_project

        return str(data_home_for_project(WORKTREE_ROOT))
    except Exception as exc:  # noqa: BLE001 - 解析失败退回 registry 值
        print(f"[e2e] data_home_for_project 解析失败，退回 registry 值: {exc}")
        return str(entry.get("dataHome") or "")


def _teardown_instance(instance: E2EInstance | None, *, started: bool = True) -> None:
    """优雅停机并核对 registry 关闭口径；KEEP_DATA=1 时保留数据目录。

    ``started=True`` 且 ``instance=None``（起实例后、就绪口径核对前就失败）时
    尽力补一次 stop；补停失败只打印，不掩盖 setup 的原始错误。
    """
    from tests.e2e.helpers import instance_registry, launcher

    if instance is None:
        if not started:
            return
        try:
            launcher.stop_instance(WORKTREE_ROOT)
            instance_registry.wait_for_entry(
                WORKTREE_ROOT,
                instance_registry.entry_is_closed,
                timeout_seconds=CLOSED_TIMEOUT_SECONDS,
                what="实例关闭（closed/closed）",
            )
            print("[e2e] 就绪前失败，已尽力停掉刚启动的实例")
        except Exception as exc:  # noqa: BLE001 - 保现场输出，不掩盖 setup 错误
            print(f"[e2e] 就绪前失败的补停未闭环（现场保留待排查）: {exc}")
        return
    # stop 走优雅 POST /api/runtime/shutdown；被在飞工作挡住时这里会失败，
    # 按约定报告并保留现场，不 force-stop。
    launcher.stop_instance(instance.project_root)
    entry = instance_registry.wait_for_entry(
        instance.project_root,
        instance_registry.entry_is_closed,
        timeout_seconds=CLOSED_TIMEOUT_SECONDS,
        what="实例关闭（closed/closed, spawnPid 归零）",
    )
    data_home = _resolve_data_home(entry) or instance.data_home
    if os.environ.get("VIBELUTION_E2E_KEEP_DATA") == "1":
        print(f"[e2e] VIBELUTION_E2E_KEEP_DATA=1：保留实例数据目录 {data_home}")
        return
    _remove_instance_data(Path(data_home))


def _remove_instance_data(data_home: Path) -> None:
    """清理本任务实例数据目录（带边界守卫：必须在 %LOCALAPPDATA%\\Vibelution 下）。"""
    if not str(data_home).strip():
        # 新实例条目可能暂无 dataHome（registry 演进中）：无路径即无事可清理。
        print("[e2e] registry 条目无 dataHome，跳过数据目录清理")
        return
    allowed_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Vibelution"
    try:
        data_home.resolve().relative_to(allowed_root.resolve())
    except ValueError:
        print(f"[e2e] 跳过数据目录清理（不在 {allowed_root} 下）: {data_home}")
        return
    try:
        shutil.rmtree(data_home)
        print(f"[e2e] 已清理实例数据目录 {data_home}")
    except OSError as exc:
        # 清理失败不影响已验证事实：留警告，不判 teardown 失败。
        print(f"[e2e] 实例数据目录清理失败（可手动删除）: {data_home} ({exc})")


@pytest.fixture(scope="session")
def e2e_instance() -> E2EInstance:
    """起一个本 worktree 的分支实例并核对就绪口径；会话结束优雅停机并断言关闭。"""
    from tests.e2e.helpers import ensure_web_build, instance_registry, launcher

    build = ensure_web_build.ensure_web_build(WORKTREE_ROOT)
    print(
        f"[e2e] web/dist 就绪：{'重新构建' if build.rebuilt else 'stamp 命中复用'}"
        f"（head={build.head[:12]}，dist={build.dist_dir}）"
    )

    launcher.start_instance(WORKTREE_ROOT)
    instance: E2EInstance | None = None
    try:
        entry = instance_registry.wait_for_entry(
            WORKTREE_ROOT,
            instance_registry.entry_is_ready,
            timeout_seconds=READY_TIMEOUT_SECONDS,
            what="实例就绪（steady/open + 端口租约 held）",
        )
        port = int(entry["port"])
        health = instance_registry.fetch_health(port)
        instance_registry.assert_health_serves_worktree(health, WORKTREE_ROOT)
        instance = E2EInstance(
            port=port,
            base_url=f"http://127.0.0.1:{port}",
            instance_id=str(entry.get("instanceId") or entry.get("slotId") or ""),
            project_root=WORKTREE_ROOT,
            data_home=str(entry.get("dataHome") or ""),
            health=health,
        )
        print(
            f"[e2e] 分支实例就绪: {instance.base_url} instanceId={instance.instance_id}"
            f" builtFromCommit={(health.get('serving') or {}).get('frontend', {}).get('builtFromCommit', '')[:12]}"
        )
        yield instance
    finally:
        # setup 中途失败（start 成功但就绪/health 未过）也要尽量把实例停干净；
        # stop 失败会原样抛出，保留现场供排查。
        _teardown_instance(instance)


@pytest.fixture
def page(e2e_instance: E2EInstance):
    """headless chromium 指向分支实例 URL，等首屏加载完成信号后交给测试。

    ``VIBELUTION_E2E_MODE=cdp`` 时改为连接共享桌面壳、复用分支工作台真实窗口
    （只读连接，退出仅断开客户端）。
    """
    from playwright.sync_api import sync_playwright

    from tests.e2e.helpers import desktop_cdp
    from tests.e2e.helpers.page_anchors import wait_route_ready

    mode = os.environ.get("VIBELUTION_E2E_MODE", "headless").strip().lower()
    if mode == "cdp":
        with desktop_cdp.cdp_branch_page(WORKTREE_ROOT, e2e_instance.port, e2e_instance.instance_id) as attached:
            yield attached["page"]
        return

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            context.set_default_timeout(30_000)
            page = context.new_page()
            page.goto(e2e_instance.base_url, wait_until="domcontentloaded")
            wait_route_ready(page)
            yield page
        finally:
            browser.close()
