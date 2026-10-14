"""会话标签 × 关闭时延探针（runtime-scene 取证，隔离实例）。

用户场景：双击顶栏标签 × 后标签应立即消失、后续标签补齐；确认删除一次后
进入急速连关窗口（2 秒内其它标签单击直删）。本探针在隔离分支实例上量化：

- 第二次点击 → 标签 DOM 移除 的页面时钟时延；
- DELETE /api/sessions/{id} 请求/响应时间；
- 会话列表轮询（/api/sessions/query、/api/sessions?agentId=…）响应到达时间；
- 删除当前会话时，路由切到下一会话（URL 变化）的时间；
- 急速连关：首张两段式确认后，第二张单击直删的时延。

数据形态对齐用户实况：标签条展示的是「选中 agent 的会话」，因此用
create_agent + agent 会话造数，并保持一个活跃会话打开。
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.instance_registry import control_token
from tests.e2e.helpers.page_anchors import wait_route_ready

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]

TAB_CONTAINER = "[data-agent-session-tab-container]"
CLOSE_BUTTON = "button.agentSessionTabCloseButton"
PRESENT_POLL_INTERVAL_MS = 60
TAB_WAIT_TIMEOUT_MS = 30000

_INSTRUMENT_SOURCE = """
(domId) => {
    const probe = {
        click1At: null,
        click2At: null,
        removedAt: null,
        removalSeen: false,
        reappearedAt: null,
    };
    window.__tabProbe = probe;
    window.__navLog = [];
    const recordNav = (kind, detail) => {
        const stack = String(new Error().stack || "").split("\\n").slice(2, 6).join(" | ");
        window.__navLog.push({ at: performance.now(), kind, detail: String(detail).slice(0, 160), stack });
    };
    const rawPush = history.pushState.bind(history);
    const rawReplace = history.replaceState.bind(history);
    history.pushState = (...args) => { recordNav("pushState", args[2]); return rawPush(...args); };
    history.replaceState = (...args) => { recordNav("replaceState", args[2]); return rawReplace(...args); };
    window.addEventListener("popstate", () => recordNav("popstate", location.search));
    document.addEventListener(
        "click",
        (event) => {
            const target = event.target;
            if (!(target && target.closest && target.closest("button.agentSessionTabCloseButton"))) return;
            if (probe.click1At === null) {
                probe.click1At = performance.now();
                return;
            }
            if (probe.click2At === null) probe.click2At = performance.now();
        },
        { capture: true },
    );
    const tabEl = document.getElementById(domId);
    const container = tabEl && tabEl.closest("[data-agent-session-tab-container]");
    const strip = container && container.parentElement;
    if (!strip) return;
    const markRemoval = () => {
        if (document.getElementById(domId)) {
            if (probe.removalSeen && probe.reappearedAt === null) probe.reappearedAt = performance.now();
            return;
        }
        if (!probe.removalSeen) {
            probe.removalSeen = true;
            probe.removedAt = performance.now();
        }
    };
    new MutationObserver(markRemoval).observe(strip, { childList: true, subtree: true });
}
"""


def _tab_dom_id(session_id: str) -> str:
    return f"agent-session-tab-session-{session_id}"


def _delete_session_api(port: int, session_id: str) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/sessions/{session_id}",
        method="DELETE",
        headers={"X-Vibelution-Control-Token": control_token(port)},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except urllib.error.HTTPError:
        pass  # 404 = 已经不存在；探针清理不因已删而失败。


def _dump_strip_diagnostics(page, port: int, seeded: list[str]) -> None:
    counts = page.evaluate(
        """() => ({
            groups: document.querySelectorAll(".agentSessionTabGroup").length,
            containers: document.querySelectorAll("[data-agent-session-tab-container]").length,
            closeButtons: document.querySelectorAll("button.agentSessionTabCloseButton").length,
            path: location.pathname + location.search,
        })"""
    )
    print(f"[diag] page={counts}")
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/sessions?limit=100",
            headers={"X-Vibelution-Control-Token": control_token(port)},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            import json as _json

            payload = _json.loads(response.read().decode("utf-8"))
        items = payload if isinstance(payload, list) else payload.get("items", [])
        print(f"[diag] api sessions={len(items)}: {[s.get('id') for s in items][:6]}")
    except Exception as exc:  # noqa: BLE001 - 诊断输出不因 API 失败中断
        print(f"[diag] api sessions fetch failed: {exc}")
    import os
    import tempfile

    shot = os.path.join(tempfile.gettempdir(), "vibe_tabprobe_diag.png")
    try:
        page.screenshot(path=shot)
        print(f"[diag] screenshot: {shot}")
    except Exception as exc:  # noqa: BLE001
        print(f"[diag] screenshot failed: {exc}")


class _NetworkLog:
    """按 Python 单调钟记录 DELETE 与会话列表响应到达时间。"""

    def __init__(self, page, target_session_id: str) -> None:
        self.entries: list[tuple[float, str, str]] = []
        self.delete_responses: list = []
        self._target = target_session_id
        page.on("response", self._on_response)

    def _on_response(self, response) -> None:
        try:
            method = response.request.method
            url = response.url
        except Exception:
            return
        tag = ""
        if method == "DELETE" and f"/api/sessions/{self._target}" in url:
            tag = f"DELETE->{response.status}"
            self.delete_responses.append(response)
        elif method == "GET" and f"/api/sessions/{self._target}" in url and url.rstrip("/").endswith(self._target):
            tag = f"detail-get->{response.status}"
        elif method == "GET" and ("/api/sessions/query" in url or url.rstrip("/").endswith("/api/sessions")):
            tag = "sessions-list"
        if tag:
            import time as _time

            self.entries.append((_time.monotonic(), tag, url[:110]))

    def close(self, page) -> None:
        try:
            page.remove_listener("response", self._on_response)
        except Exception:
            pass


def _wait_close_button(page, session_id: str, port: int, seeded: list[str]):
    dom_id = _tab_dom_id(session_id)
    try:
        page.wait_for_selector(f"#{dom_id}", state="visible", timeout=TAB_WAIT_TIMEOUT_MS)
    except Exception:
        _dump_strip_diagnostics(page, port, seeded)
        raise
    return page.locator(f'{TAB_CONTAINER}:has(#{dom_id}) {CLOSE_BUTTON}').first


def _double_click_and_measure(page, close_button, dom_id: str) -> dict[str, Any]:
    close_button.click()  # 第一次：进入红色确认态。
    armed = close_button.get_attribute("data-session-tab-close-armed")
    close_button.click()  # 第二次：执行删除。
    deadline_sweep = 40.0
    import time as _time

    start = _time.monotonic()
    timeline: list[tuple[float, dict[str, Any]]] = []
    result: dict[str, Any] = {"armed_after_first_click": armed}
    while _time.monotonic() - start < deadline_sweep:
        snap = page.evaluate(
            """(domId) => ({
                probe: window.__tabProbe || null,
                present: Boolean(document.getElementById(domId)),
                search: location.search,
                thread: (document.querySelector("[data-agent-thread-id]") || {}).getAttribute
                    ? document.querySelector("[data-agent-thread-id]").getAttribute("data-agent-thread-id")
                    : null,
                now: performance.now(),
            })""",
            dom_id,
        )
        timeline.append((round(snap["now"], 1), {
            "present": snap["present"],
            "search": snap["search"],
            "thread": snap["thread"],
        }))
        probe = snap["probe"] or {}
        if probe.get("removedAt") is not None:
            # 移除后继续观察 4 秒，捕捉失败回滚（标签回弹）与路由弹回。
            if _time.monotonic() - start > 4.0:
                result.update(probe=probe, timeline=timeline)
                return result
        page.wait_for_timeout(PRESENT_POLL_INTERVAL_MS)
    result.update(probe=(page.evaluate("window.__tabProbe || null")) or {}, timeline=timeline)
    return result


def _report(label: str, result: dict[str, Any], network: _NetworkLog, nav_log: list | None = None) -> None:
    probe = result.get("probe") or {}
    click2 = probe.get("click2At")
    removed = probe.get("removedAt")
    print(f"\n=== {label} ===")
    print(f"baseline_search: {result.get('baseline_search', '')[:90]}")
    print(f"armed_after_first_click: {result.get('armed_after_first_click')}")
    if click2 is not None and removed is not None:
        print(f"click2 -> tab removed: {removed - click2:.0f} ms (page clock)")
    else:
        print(f"click2At={click2} removedAt={removed} (未捕获完整移除)")
    reappeared = probe.get("reappearedAt")
    if reappeared is not None and removed is not None:
        print(f"rollback/reappear: +{reappeared - removed:.0f} ms after removal")
    timeline = result.get("timeline") or []
    if timeline:
        t0 = timeline[0][0]
        deduped: list[tuple[float, dict[str, Any]]] = []
        for at, state in timeline:
            if not deduped or deduped[-1][1] != state:
                deduped.append((at - t0, state))
        if deduped and deduped[-1][0] != timeline[-1][0] - t0:
            deduped.append((timeline[-1][0] - t0, timeline[-1][1]))
        print("route/thread timeline (deduped, ms since first sample):")
        for at, state in deduped[:24]:
            print(f"  +{at:7.0f}ms present={int(bool(state['present']))} search={state['search'][:70]} thread={str(state['thread'])[:40]}")
    if nav_log:
        click1 = probe.get("click1At") or 0.0
        print(f"nav log ({len(nav_log)} entries, ms relative to click1):")
        for entry in nav_log:
            rel = entry.get("at", 0.0) - click1
            print(f"  {rel:+9.0f}ms {entry.get('kind')} -> {str(entry.get('detail'))[:90]}")
            print(f"            stack: {str(entry.get('stack'))[:220]}")
    print("network responses (python monotonic clock, first entry为原点):")
    base = network.entries[0][0] if network.entries else 0.0
    for at, tag, url in network.entries:
        print(f"  +{at - base:8.3f}s {tag} {url}")
    for response in network.delete_responses[:2]:
        try:
            print(f"  DELETE body: {response.text()[:220]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  DELETE body 读取失败: {exc}")


def _seed_agent_sessions(port: int, prefix: str) -> tuple[str, list[str]]:
    from tests.e2e.helpers.api_write import post_json
    from tests.e2e.helpers.instance_registry import fetch_json

    templates = fetch_json(port, "/api/prompt-templates").get("templates") or []
    template_id = next(
        (str((item or {}).get("templateId") or "").strip() for item in templates
         if str((item or {}).get("templateId") or "").strip()),
        "",
    )
    assert template_id, f"实例无可用提示词模板: {str(templates)[:200]}"
    # 创建校验只查非空（agent_operation_service._assert_creation_fields），
    # 伪模型引用即可，不注册 provider、不写共享 operator config。
    agent = post_json(port, "/api/agents", {
        "displayName": f"{prefix}-agent",
        "primaryMode": "chat",
        "promptTemplateId": template_id,
        "llmBindings": {"dialogue": {"modelId": "e2e-tabprobe/probe-chat"}},
    })
    agent_id = str(agent.get("agentId") or agent.get("id") or "")
    assert agent_id, f"create_agent 未返回 agentId: {str(agent)[:200]}"
    sessions = [create_session(port, title=f"{prefix}-{i}", agent_id=agent_id) for i in range(3)]
    return agent_id, sessions


def _run_scenario(e2e_instance, page, *, label: str, active_session: str, target_session: str, seeded: list[str]) -> None:
    page.goto(
        f"{e2e_instance.base_url}/chat?session={urllib.parse.quote(active_session)}",
        wait_until="domcontentloaded",
    )
    wait_route_ready(page)
    close_button = _wait_close_button(page, target_session, e2e_instance.port, seeded)
    assert close_button.is_enabled(), "ready 会话的 × 不应被 busy 禁用"
    dom_id = _tab_dom_id(target_session)
    page.evaluate(_INSTRUMENT_SOURCE, dom_id)
    network = _NetworkLog(page, target_session)
    try:
        baseline_search = str(page.evaluate("location.search"))
        result = _double_click_and_measure(page, close_button, dom_id)
        result["baseline_search"] = baseline_search
        nav_log = page.evaluate("window.__navLog || []")
    finally:
        network.close(page)
    _report(label, result, network, nav_log)
    probe = result.get("probe") or {}
    assert probe.get("removedAt") is not None, "标签最终应消失（否则删除链路整体失效）"
    delete_entries = [e for e in network.entries if e[1].startswith("DELETE")]
    assert delete_entries, "第二次点击应发出 DELETE 请求（否则被 busy/守卫静默拦截）"


def test_double_click_close_inactive_tab_latency(e2e_instance, page):
    agent_id, seeded = _seed_agent_sessions(e2e_instance.port, "zz-tabprobe-a")
    try:
        _run_scenario(
            e2e_instance,
            page,
            label="场景A：打开会话2，双击会话1（非当前）标签 ×",
            active_session=seeded[1],
            target_session=seeded[0],
            seeded=seeded,
        )
    finally:
        for session_id in seeded:
            _delete_session_api(e2e_instance.port, session_id)


def test_double_click_close_active_tab_latency(e2e_instance, page):
    agent_id, seeded = _seed_agent_sessions(e2e_instance.port, "zz-tabprobe-b")
    try:
        _run_scenario(
            e2e_instance,
            page,
            label="场景B：双击当前活跃标签 ×（含路由接棒）",
            active_session=seeded[0],
            target_session=seeded[0],
            seeded=seeded,
        )
    finally:
        for session_id in seeded:
            _delete_session_api(e2e_instance.port, session_id)


def test_burst_close_single_click_after_first_confirm(e2e_instance, page):
    """急速连关：确认删除第一张标签后，2 秒内单击其它标签 × 直接删除。"""
    import time as _time

    port = e2e_instance.port
    agent_id, seeded = _seed_agent_sessions(port, "zz-tabprobe-burst")
    try:
        page.goto(
            f"{e2e_instance.base_url}/chat?session={urllib.parse.quote(seeded[0])}",
            wait_until="domcontentloaded",
        )
        wait_route_ready(page)
        network = _NetworkLog(page, "")
        try:
            # 第一张：冷启动两段式（arm + confirm），开启急速连关窗口。
            first = _wait_close_button(page, seeded[1], port, seeded)
            first.click()
            assert first.get_attribute("data-session-tab-close-armed") == "true", "第一击应进入确认态"
            first.click()
            deadline = _time.monotonic() + 15.0
            while _time.monotonic() < deadline:
                if page.evaluate("(id) => !document.getElementById(id)", _tab_dom_id(seeded[1])):
                    break
                page.wait_for_timeout(40)
            else:
                pytest.fail("确认删除后第一张标签 15s 未消失")

            # 第二张：连关窗口内单击直删，不应先进入 armed 态。
            second = _wait_close_button(page, seeded[2], port, seeded)
            t_click = _time.monotonic()
            second.click()
            # 单次同步读态：burst 生效时标签可能已被乐观移除（REMOVED），
            # 旧行为则会先 ARMED——不能用会自动等待的 locator.get_attribute。
            state = page.evaluate(
                """(domId) => {
                    const el = document.getElementById(domId);
                    if (!el) return "REMOVED";
                    const btn = el.closest("[data-agent-session-tab-container]").querySelector("button.agentSessionTabCloseButton");
                    return btn?.getAttribute("data-session-tab-close-armed") === "true" ? "ARMED" : "PLAIN";
                }""",
                _tab_dom_id(seeded[2]),
            )
            assert state != "ARMED", "急速连关窗口内单击不应进入 armed 态"
            deadline = _time.monotonic() + 15.0
            while _time.monotonic() < deadline:
                if page.evaluate("(id) => !document.getElementById(id)", _tab_dom_id(seeded[2])):
                    break
                page.wait_for_timeout(40)
            else:
                pytest.fail("急速连关单击后第二张标签 15s 未消失")
            delta_ms = (_time.monotonic() - t_click) * 1000.0
            print(f"\n=== 场景D：急速连关（单击直删第二张） ===\n  单击 -> 标签消失: {delta_ms:.0f}ms")
            # 乐观移除先于 DELETE 响应到达；轮询等两个响应落地再断言。
            deadline = _time.monotonic() + 10.0
            deletes: list = []
            while _time.monotonic() < deadline:
                deletes = [e for e in network.entries if e[1].startswith("DELETE")]
                if len(deletes) >= 2:
                    break
                page.wait_for_timeout(100)
            assert len(deletes) == 2, f"应恰好发出 2 个 DELETE: {deletes}"
            # 活跃标签仍在条带（未误删）。
            assert page.evaluate("(id) => Boolean(document.getElementById(id))", _tab_dom_id(seeded[0]))
        finally:
            network.close(page)
    finally:
        for session_id in seeded:
            _delete_session_api(port, session_id)


def test_user_scale_rapid_tab_deletes(e2e_instance, page):
    """用户规模复刻：1 个 agent + 130 条会话，首张双击确认后一路单击连删 5 个标签。

    观察三件事：每个标签的移除时延（首张=确认击，后续=连关单击）、DELETE 在
    大存储下的耗时、以及删除后条带是否回填（「后边的会话补齐」）。
    """
    import time as _time

    port = e2e_instance.port
    from tests.e2e.helpers.api_write import post_json
    from tests.e2e.helpers.instance_registry import fetch_json

    templates = fetch_json(port, "/api/prompt-templates").get("templates") or []
    template_id = next(
        (str((item or {}).get("templateId") or "").strip() for item in templates
         if str((item or {}).get("templateId") or "").strip()),
        "",
    )
    agent = post_json(port, "/api/agents", {
        "displayName": "zz-userscale-agent",
        "primaryMode": "chat",
        "promptTemplateId": template_id,
        "llmBindings": {"dialogue": {"modelId": "e2e-tabprobe/probe-chat"}},
    })
    agent_id = str(agent.get("agentId") or "")
    seeded = [create_session(port, title=f"zz-userscale-{i:03d}", agent_id=agent_id) for i in range(130)]
    active = seeded[0]
    try:
        page.goto(
            f"{e2e_instance.base_url}/chat?session={urllib.parse.quote(active)}",
            wait_until="domcontentloaded",
        )
        wait_route_ready(page)
        # 条带有 5 标签上限：目标从 DOM 实际在条的标签里取（去掉当前活跃），
        # 而不是按建序猜——建序在 130 会话的 updatedAt 排序下不可见。
        page.wait_for_selector(TAB_CONTAINER, state="visible", timeout=TAB_WAIT_TIMEOUT_MS)
        import time as _settle

        _settle.sleep(3.0)  # 等轮询把条带稳定到最终 5 标签。
        present_ids = page.evaluate(
            """() => Array.from(document.querySelectorAll("[data-agent-session-tab-container] button[id^='agent-session-tab-session-']"))
                .map((el) => decodeURIComponent(el.id.replace('agent-session-tab-session-', '')))
                .filter((id) => id && !id.startsWith('agent-'))"""
        )
        print(f"[scale] 条带在页标签: {len(present_ids)} -> {present_ids}")
        targets = [sid for sid in present_ids if sid != active][:5]
        assert len(targets) >= 3, f"条带可删目标不足: {targets}"
        page.evaluate(
            """() => {
                window.__stripProbe = {counts: []};
                const strip = document.querySelector(".agentSessionTabGroup");
                if (!strip) return;
                const current = () => document.querySelectorAll("[data-agent-session-tab-container]").length;
                window.__stripProbe.counts.push({at: performance.now(), n: current()});
                new MutationObserver(() => {
                    window.__stripProbe.counts.push({at: performance.now(), n: current()});
                }).observe(strip, {childList: true, subtree: true});
            }"""
        )
        network = _NetworkLog(page, "")
        per_target_timing: list[str] = []
        for index, target in enumerate(targets):
            close_button = _wait_close_button(page, target, port, seeded)
            t_click = _time.monotonic()
            close_button.click()
            if index == 0:
                armed = close_button.get_attribute("data-session-tab-close-armed")
                assert armed, "首张第一击应进入确认态"
                close_button.click()  # 确认删除，开启急速连关窗口。
            # 后续目标：急速连关窗口内单击即删（用户要的「一路点过去」）。
            deadline = _time.monotonic() + 15.0
            dom_id = _tab_dom_id(target)
            while _time.monotonic() < deadline:
                gone = page.evaluate(
                    "(domId) => !document.getElementById(domId)", dom_id,
                )
                if gone:
                    break
                page.wait_for_timeout(40)
            else:
                per_target_timing.append(f"目标{index}: 15s 未消失!")
                continue
            delta_ms = (_time.monotonic() - t_click) * 1000.0
            gesture = "双击" if index == 0 else "连关单击"
            per_target_timing.append(f"目标{index}: {gesture}后 {delta_ms:.0f}ms 消失")
            page.wait_for_timeout(220)  # 模拟用户移动到下一个标签的节奏。
        _time.sleep(2.0)
        counts = page.evaluate("window.__stripProbe || {counts: []}").get("counts") or []
        print("\n=== 场景C：130 会话规模连删 5 标签（首张双击+后续单击） ===")
        for line in per_target_timing:
            print(f"  {line}")
        if counts:
            t0 = counts[0]["at"]
            deduped = []
            for entry in counts:
                if not deduped or deduped[-1][1] != entry["n"]:
                    deduped.append((entry["at"] - t0, entry["n"]))
            print("  条带标签数时间线 (ms, count):")
            for at, n in deduped[:20]:
                print(f"    +{at:7.0f}ms n={n}")
        delete_times = [(at, tag) for at, tag, _ in network.entries if tag.startswith("DELETE")]
        base = network.entries[0][0] if network.entries else 0.0
        print(f"  DELETE 响应: {len(delete_times)} 个")
        for at, tag in delete_times:
            print(f"    +{at - base:8.3f}s {tag}")
        network.close(page)
        assert len(delete_times) == len(targets), "每个目标都应发出恰好一个 DELETE"
    finally:
        for session_id in seeded:
            _delete_session_api(port, session_id)
