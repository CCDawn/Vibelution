"""Per-route「不支持参数」负缓存的失效机制。

背景（2026-11-09）：负缓存原本是进程级、无 TTL 的永久事实。一次聚合池节点的
400 让 reasoning_effort 被剥了整整一个进程生命周期，通道恢复后也没有任何请求
去验证它，用户的思考强度设置静默失效（日志里 616 次 cache hit）。实测该端点
当前接受该参数且思考量随强度单调变化，说明缓存必须能过期。
"""

from __future__ import annotations

import pytest

from core.llm import client as client_mod


@pytest.fixture(autouse=True)
def _isolated_cache():
    """模块级缓存逐用例隔离，避免用例间状态泄漏。"""
    client_mod._reset_llm_route_unsupported_params_cache()
    yield
    client_mod._reset_llm_route_unsupported_params_cache()


@pytest.fixture
def clock(monkeypatch):
    """可推进的单调时钟，替换负缓存自己的时钟读取。"""
    now = [1000.0]
    monkeypatch.setattr(
        client_mod, "_llm_route_unsupported_params_now", lambda: now[0]
    )
    return now


@pytest.fixture
def events(monkeypatch):
    """捕获场景事件，避免真实落盘。"""
    captured: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        client_mod,
        "_record_llm_scene_event",
        lambda phase, code, **kwargs: captured.append(
            (phase, code, kwargs.get("fields") or {})
        ),
    )
    return captured


def test_fresh_record_is_still_used(clock):
    """刚记下的能力事实立刻生效：TTL 内继续预剥。"""
    client_mod._remember_route_unsupported_params("route-a", ("reasoning_effort",))
    clock[0] += client_mod._LLM_ROUTE_UNSUPPORTED_PARAMS_TTL_SECONDS - 1
    assert client_mod._cached_route_unsupported_params("route-a") == ("reasoning_effort",)


def test_expired_record_is_dropped_and_reprobed(clock):
    """超过 TTL 即淘汰：读空，并且下一次发送会重新带上参数。"""
    client_mod._remember_route_unsupported_params("route-a", ("reasoning_effort",))
    clock[0] += client_mod._LLM_ROUTE_UNSUPPORTED_PARAMS_TTL_SECONDS

    assert client_mod._cached_route_unsupported_params("route-a") == ()
    payload = {"model": "m", "reasoning_effort": "high"}
    stripped, params = client_mod._pre_strip_cached_unsupported_params(payload, "route-a")
    assert params == ()
    assert stripped == payload
    # 淘汰是就地发生的，不是只对本次读返回空。
    assert "route-a" not in client_mod._LLM_ROUTE_UNSUPPORTED_PARAMS


def test_ttl_boundary_is_exclusive(clock):
    """恰好到达 TTL 视为过期，避免边界上继续沿用旧事实。"""
    client_mod._remember_route_unsupported_params("route-a", ("reasoning_effort",))
    clock[0] += client_mod._LLM_ROUTE_UNSUPPORTED_PARAMS_TTL_SECONDS - 0.001
    assert client_mod._cached_route_unsupported_params("route-a") == ("reasoning_effort",)
    clock[0] += 0.001
    assert client_mod._cached_route_unsupported_params("route-a") == ()


def test_remembering_again_restarts_the_ttl(clock):
    """通道再次 400 时刷新时间戳：新的观测从当下重新计时。"""
    client_mod._remember_route_unsupported_params("route-a", ("reasoning_effort",))
    clock[0] += 400
    client_mod._remember_route_unsupported_params("route-a", ("reasoning_effort",))
    clock[0] += 400
    # 距第一次记录已 800s，但距第二次只有 400s，仍应有效。
    assert client_mod._cached_route_unsupported_params("route-a") == ("reasoning_effort",)


def test_expiry_emits_a_scene_event(clock, events):
    """过期必须可观测：静默失效正是这次事故的根因。"""
    client_mod._remember_route_unsupported_params("route-a", ("reasoning_effort",))
    clock[0] += client_mod._LLM_ROUTE_UNSUPPORTED_PARAMS_TTL_SECONDS

    assert client_mod._cached_route_unsupported_params("route-a") == ()
    expired = [item for item in events if item[1] == "llm.route_unsupported_params.expired"]
    assert len(expired) == 1
    phase, _code, fields = expired[0]
    assert phase == "llm"
    assert fields["routeKey"] == "route-a"
    assert fields["params"] == ["reasoning_effort"]


def test_routes_expire_independently(clock):
    """TTL 按 route 独立计算，一条 route 过期不影响另一条。"""
    client_mod._remember_route_unsupported_params("route-a", ("reasoning_effort",))
    clock[0] += 500
    client_mod._remember_route_unsupported_params("route-b", ("reasoning_effort",))
    clock[0] += 200

    assert client_mod._cached_route_unsupported_params("route-a") == ()
    assert client_mod._cached_route_unsupported_params("route-b") == ("reasoning_effort",)
