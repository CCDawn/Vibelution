"""Agent 生命周期 e2e：三步向导建 Agent + 记忆设置关闭与持久化复核。

口径（锚点实测见 docs/guides/e2e-playwright.md；组件源：
web/src/routes/agent-create/AgentCreateWizardDialog.tsx、
web/src/routes/AgentMemoryPolicyPanel.tsx）：
- 创建入口 ``#agents-create-trigger``；三步 = 基本信息 → 服务商与模型 → 提示词与工具；
  默认 primaryMode=chat（工作会话态）时只需填「功能名」；模型需点「探测当前模型」
  真实连通后「下一步」才可用（产品契约：探测即轻量真实连通测试）；
- 成功后对话框标题变为「Agent 已创建」；点「完成」收尾；
- ``/agents?agent=<id>&pane=config`` → 配置分组 nav（aria-label「配置分组」）点
  「能力绑定」→ 记忆设置面板：checkbox（``data-vui="checkbox"``）关掉「启用个人记忆」
  → 面板 pill「未保存」→ 点「保存记忆」→ pill「已同步」；
- 刷新后复查开关仍为关；API GET /api/agents/{id} 复核 memoryPolicy.enabled==false。

注意：向导的模型探测依赖实例模型库中已配密钥的模型（探测即真实连通检查）；
本机 operator config 有可用密钥时用例可走通，若探测全部失败用例会以明确信息失败。

缺陷⑥固化（修复 949a33cf4）：test_wizard_keystroke_before_catalog_backfills_defaults_
and_enables_create 用 ``page.route`` 把向导目录 API（``/api/agents/config-workspace``、
``/api/tools``，见 AgentCreateWizardDialog 的两个 useQuery）握住到击键之后才放行，
固化「击键先于异步目录返回」竞态：修复前整草稿 draftDirty 门冻结 normalize，
模型/工具包停在空值、创建按钮永久禁用；修复后字段级补齐——功能名保值、模型补默认、
工具包补默认勾选、创建按钮可用（规格：字段级保护，archive plan 2026-07-19:81）。
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

import pytest

from tests.e2e.helpers.agent_factory import (
    find_agent_by_display_name,
    find_working_providers,
    wait_for_agent_memory_enabled,
)
from tests.e2e.helpers.instance_registry import fetch_json

pytestmark = [
    pytest.mark.serial,
    pytest.mark.timeout(0),
    # skipif 而非模块级 skip：模块级 skip 会「零收集」，closeout 选择器直跑
    # 本文件时 pytest 退出码 5（NO_TESTS_COLLECTED）判失败；skipif 逐条跳过退出码 0。
    pytest.mark.skipif(
        os.environ.get("VIBELUTION_E2E") != "1",
        reason="e2e 手动车道：设 VIBELUTION_E2E=1 后运行（见 docs/guides/e2e-playwright.md）",
    ),
]

CREATE_TRIGGER = "#agents-create-trigger"
SUCCESS_TITLE = "Agent 已创建"
CONFIG_SECTION_NAV = 'nav[aria-label="配置分组"]'
# VCheckbox = label[data-vui="checkbox"][data-selected]（ShadcnCheckbox 契约）；
# 用记忆提示文案唯一锁定，避免误点同面板其他勾选框。
MEMORY_CHECKBOX = (
    'label[data-vui="checkbox"]:has-text("关闭后该 Agent 不再挂载个人记忆写入工具")'
)


def _wizard_step_reachable(page: Any, label: str) -> Any:
    return page.locator(f'ol[aria-label="新建 Agent 步骤"] button:has-text("{label}")').first


def _click_in_dialog(button: Any) -> None:
    """点击对话框内可能藏在滚动区折叠线以下的按钮。

    VDialog body 是 overflow-auto 滚动容器，按钮在折叠线以下时 Playwright
    常规 click 会因 "element is outside of the viewport" 拒点；先显式把元素
    滚到视口中心再点，仍失败用元素自身 JS click 兜底（同样走真实事件 handler）。
    """
    try:
        button.click(timeout=5_000)
        return
    except Exception:  # noqa: BLE001 - 滚动到中心后重试一次
        button.evaluate("el => el.scrollIntoView({block: 'center', inline: 'center'})")
        button.wait_for(state="visible", timeout=10_000)
        button.page.wait_for_timeout(300)
        try:
            button.click(timeout=10_000, force=True)
            return
        except Exception:  # noqa: BLE001 - 最终 JS click 兜底
            button.evaluate("el => el.click()")


def _pick_provider_by_id(page: Any, provider_id: str) -> bool:
    """在「服务商」下拉里选 label 含指定 provider_id 的可用项（精确命中）。"""
    trigger = page.locator('button[aria-label="服务商"]').first
    if not trigger.count() or trigger.is_disabled():
        return False
    trigger.click()
    options = page.locator(
        'ul[role="listbox"][aria-label="服务商"] button[role="option"]:not([disabled])'
    )
    options.first.wait_for(state="visible", timeout=15_000)
    total = options.count()
    for index in range(total):
        option = options.nth(index)
        text = (option.inner_text() or "").strip()
        if provider_id in text and "已配密钥" in text:
            option.click()
            return True
    page.keyboard.press("Escape")
    return False


def _pick_model_by_id(page: Any, model_id: str) -> bool:
    """在「模型」下拉里选 label 含指定 model_id（裸名，去 provider 前缀）的可用项。

    服务商 onChange 自动带出的是该服务商排序后的第一个可用模型，可能与 API
    预验证通过的模型不同（实测 09-26 共享配置 58 个已配密钥模型时，
    dashscope_main 首个是 qwen3.6-plus，其探测必因「达到 max output token
    上限被 provider 截断」失败）；因此显式选中预验证的那个模型再探测。
    """
    bare = model_id.split("/")[-1]
    trigger = page.locator('button[aria-label="模型"]').first
    if not trigger.count() or trigger.is_disabled():
        return False
    trigger.click()
    options = page.locator(
        'ul[role="listbox"][aria-label="模型"] button[role="option"]:not([disabled])'
    )
    options.first.wait_for(state="visible", timeout=15_000)
    total = options.count()
    for index in range(total):
        option = options.nth(index)
        text = (option.inner_text() or "").strip()
        if bare in text or model_id in text:
            _click_in_dialog(option)
            return True
    page.keyboard.press("Escape")
    return False


def _pick_keyed_provider(page: Any, pick_index: int = 0) -> bool:
    """在「服务商」下拉里选第 pick_index+1 个「已配密钥且非 local/lan」的可用项。

    local/lan 服务商的端点常不可达（探测 30s 超时），探测失败后由调用方递增
    pick_index 换下一个；label 形如 "compatible · openai · openai_main · N 已配密钥"。
    返回是否成功点了某个服务商选项。
    """
    trigger = page.locator('button[aria-label="服务商"]').first
    if not trigger.count() or trigger.is_disabled():
        return False
    trigger.click()
    options = page.locator(
        'ul[role="listbox"][aria-label="服务商"] button[role="option"]:not([disabled])'
    )
    options.first.wait_for(state="visible", timeout=15_000)
    matches = []
    total = options.count()
    for index in range(total):
        text = (options.nth(index).inner_text() or "").strip()
        if "已配密钥" in text and "local" not in text.lower() and "lan" not in text.lower():
            matches.append((index, text))
    if not matches:
        return False
    # 常主流公网 API 优先（实测 command_code/dashscope_main/relay_openai 可达），
    # 其余仍按 DOM 顺序轮询兜底。
    preferred = ("command_code", "dashscope", "relay_openai", "openai_main", "deepseek", "siliconflow")
    matches.sort(
        key=lambda item: (
            0 if any(key in item[1].lower() for key in preferred) else 1,
            item[0],
        )
    )
    target = matches[min(pick_index, len(matches) - 1)][0]
    options.nth(target).click()
    return True


def _create_agent_via_wizard(
    page: Any,
    base_url: str,
    display_name: str,
    verified_providers: list[tuple[str, str]],
) -> None:
    """跑完三步向导直至「Agent 已创建」+「完成」。

    高负载机上向导的 workspace/tools 查询偶发一次性失败（「部分创建选项加载
    失败」，模型清单为空），无法在对话框内恢复，因此由调用方整流程重试一次。
    模型步骤优先选 API 预探测通过的 verified_providers（与 UI 探测同一后端实现）。
    """
    page.goto(f"{base_url}/agents", wait_until="domcontentloaded")
    trigger = page.locator(CREATE_TRIGGER).first
    trigger.wait_for(state="visible", timeout=20_000)
    trigger.click()

    # VDialog = Radix：content[data-vui="dialog-content"] + title[data-slot="dialog-title"]。
    dialog = page.locator('[data-vui="dialog-content"]').first
    dialog.wait_for(state="visible", timeout=15_000)

    # 第 1 步 基本信息：primaryMode 默认 chat（工作会话态）只需功能名。
    name_input = page.get_by_label("功能名").first
    name_input.wait_for(state="visible", timeout=15_000)
    name_input.fill(display_name)
    next_button = page.get_by_role("button", name="下一步").first
    _click_in_dialog(next_button)

    # 第 2 步 服务商与模型：等待「探测当前模型」就绪。模型清单异步加载，且草稿
    # 一旦被编辑（填名）就不再自动套用工作区默认模型，因此持续轮询并按
    # verified_providers（API 预探测通过的服务商）驱动「服务商」下拉；单次探测
    # 失败（远端不可达会 30s 超时）则换下一个已验证服务商重试。
    probe_button = page.get_by_role("button", name="探测当前模型").first
    probe_button.wait_for(state="visible", timeout=15_000)
    deadline = time.monotonic() + 420
    drove_select = False
    verified_index = 0
    probe_attempts = 0
    probe_passed = False
    while True:
        if time.monotonic() >= deadline:
            try:
                page.screenshot(path="C:/vtmp/e2e-wizard-stuck.png")
                summaries = page.locator('p[aria-live="polite"]').all_inner_texts()
                print(
                    "[wizard-stuck] availability summaries="
                    f"{[t[:80] for t in summaries]}; probe_disabled={probe_button.is_disabled()}"
                )
            except Exception:  # noqa: BLE001 - 诊断尽力而为
                pass
            raise AssertionError(
                "向导模型探测未完成：清单未加载、全部未配密钥或多次探测失败"
            )
        if not drove_select:
            # 先把服务商与模型驱动到 API 预验证对，再点探测。顺序不能反：
            # 默认回填模型本身可用时「探测当前模型」从不禁用，禁用驱动的旧
            # 顺序会一直探测默认模型（实测 qwen3.6-plus 探测必因 max output
            # token 截断失败）；且 onChange 自动带出的首个可用模型可能与预
            # 验证模型不同，故显式选中预验证模型。没有 verified 信息时退回
            # 挑「已配密钥且非 local/lan」。
            picked = False
            if verified_index < len(verified_providers):
                picked = _pick_provider_by_id(page, verified_providers[verified_index][0])
                if picked:
                    # 预验证模型选不中也不阻塞：仍用 onChange 带出的模型探测。
                    _pick_model_by_id(page, verified_providers[verified_index][1])
            if not picked:
                picked = _pick_keyed_provider(page, verified_index)
            drove_select = picked or drove_select
        if not probe_button.is_disabled():
            _click_in_dialog(probe_button)
            probe_attempts += 1
            probe_passed = False
            result_deadline = time.monotonic() + 45
            while time.monotonic() < result_deadline:
                if page.get_by_text("探测通过，可以使用该模型创建会话。").count():
                    probe_passed = True
                    break
                if page.get_by_text("探测失败").count():
                    break
                page.wait_for_timeout(1_000)
            if probe_passed and not next_button.is_disabled():
                break
            verified_index += 1
            drove_select = False
            if verified_index >= max(len(verified_providers), 1):
                raise AssertionError(
                    f"模型探测 {probe_attempts} 次均未通过（检查实例模型库密钥/网络）"
                )
            page.wait_for_timeout(1_000)
            continue
        page.wait_for_timeout(1_000)
    deadline = time.monotonic() + 10
    while next_button.is_disabled():
        assert time.monotonic() < deadline, "探测通过后「下一步」仍未解锁"
        page.wait_for_timeout(500)
    _click_in_dialog(next_button)

    # 第 3 步 提示词与工具：默认提示词已就绪。工具包清单异步加载，且草稿被编辑过
    # （填名）后 normalize 不再自动勾选默认工具包，创建按钮会因「未选工具包」
    # 保持禁用——就绪超时则勾选第一个工具包再等。
    create_button = page.get_by_role("button", name="创建 Agent").first
    create_button.wait_for(state="visible", timeout=15_000)
    deadline = time.monotonic() + 10
    ticked_bundle = False
    while create_button.is_disabled():
        if time.monotonic() >= deadline:
            if not ticked_bundle:
                # 对话框可能横向溢出视口（实例截图见 C:/vtmp/e2e-wizard-attempt*.png），
                # 先把勾选框滚到视口中心，再用元素自身 JS click 触发真实 change。
                first_bundle = dialog.locator('input[type="checkbox"]').first
                first_bundle.wait_for(state="attached", timeout=20_000)
                first_bundle.evaluate(
                    "el => { el.scrollIntoView({block: 'center', inline: 'center'}); el.click(); }"
                )
                ticked_bundle = True
                deadline = time.monotonic() + 10
                continue
            raise AssertionError("创建按钮未就绪（提示词/工具包未加载）")
        page.wait_for_timeout(500)
    _click_in_dialog(create_button)

    dialog_title = dialog.locator('[data-slot="dialog-title"]').first
    page.get_by_text(SUCCESS_TITLE).first.wait_for(state="visible", timeout=60_000)
    assert SUCCESS_TITLE in (dialog_title.inner_text() or ""), (
        f"对话框标题不是「{SUCCESS_TITLE}」: {dialog_title.inner_text()!r}"
    )
    done_button = dialog.get_by_role("button", name="完成").first
    _click_in_dialog(done_button)


def test_create_agent_via_wizard_then_disable_memory(page: Any, e2e_instance: Any) -> None:
    """三步向导建 Agent（成功标题「Agent 已创建」）→ config pane 关记忆 → 持久。"""
    display_name = f"e2e 向导 Agent {uuid.uuid4().hex[:6]}"

    # arrange：用后端探测接口（与 UI「探测」同一实现）预先筛出当前真实可用的
    # 服务商，避免在 UI 里逐个试错；一个可用都没有则本环境无法完成向导。
    verified = find_working_providers(e2e_instance.port)
    assert verified, (
        "实例模型库中没有任何当前可连通的已配密钥模型，向导无法完成探测步骤"
    )
    print(f"[wizard] verified providers: {verified}")

    # --- 三步向导（workspace 查询偶发一次性失败，整流程重试一次）---
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            _create_agent_via_wizard(
                page, e2e_instance.base_url, display_name,
                verified[attempt - 1:] or verified,
            )
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001 - 整流程重试一次
            last_error = exc
            print(f"[wizard] 第 {attempt} 次向导失败: {exc}")
            try:
                page.screenshot(path=f"C:/vtmp/e2e-wizard-attempt{attempt}.png")
            except Exception:  # noqa: BLE001 - 截图尽力而为
                pass
            # 重试前确认后端还活着（探测超时不该拖垮实例，但保险起见先查再试）。
            alive = False
            try:
                alive = fetch_json(e2e_instance.port, "/api/health").get("routesReady") is True
            except Exception:  # noqa: BLE001 - 不可达即视为不活着
                alive = False
            if not alive:
                raise AssertionError(
                    "实例后端在向导流程中失联（/api/health 不可达），不再重试"
                ) from exc
            page.goto("about:blank")
    if last_error is not None:
        raise AssertionError(f"向导两次均未完成（见 C:/vtmp/e2e-wizard-attempt*.png）: {last_error}")

    # --- 记忆设置关闭与持久化 ---
    agent = find_agent_by_display_name(e2e_instance.port, display_name)
    agent_id = str(agent["agentId"])

    page.goto(
        f"{e2e_instance.base_url}/agents?agent={agent_id}&pane=config",
        wait_until="domcontentloaded",
    )
    nav = page.locator(CONFIG_SECTION_NAV).first
    nav.wait_for(state="visible", timeout=20_000)
    nav.get_by_role("button", name="能力绑定").click()

    # 记忆设置面板：勾选框当前为开（data-selected="true"）→ 点关。
    panel_title = page.get_by_text("记忆设置", exact=True).first
    panel_title.wait_for(state="visible", timeout=20_000)
    checkbox = page.locator(MEMORY_CHECKBOX).first
    checkbox.wait_for(state="visible", timeout=10_000)
    assert checkbox.get_attribute("data-selected") == "true", "前置：记忆开关初始应为开"
    checkbox.click()
    page.wait_for_timeout(300)
    assert checkbox.get_attribute("data-selected") == "false", "点击后记忆开关未关闭"

    unsaved_pill = page.locator("span", has_text="未保存").first
    unsaved_pill.wait_for(state="visible", timeout=10_000)
    save_button = page.get_by_role("button", name="保存记忆").first

    # 网络层证据：记录保存 PATCH 是否真的发出及结果（截屏见 C:/vtmp）。
    patch_log: list[str] = []
    page.on(
        "response",
        lambda response: patch_log.append(f"{response.status} {response.url}")
        if "/api/agents/" in response.url and response.request.method == "PATCH"
        else None,
    )

    # 保存点击偶发不触发（重渲染竞态），PATCH 未发出前最多重试 3 次。
    deadline = time.monotonic() + 90
    save_tries = 0
    while time.monotonic() < deadline:
        if page.locator("span", has_text="已同步").count():
            break
        save_tries += 1
        patch_log.clear()
        _click_in_dialog(save_button)
        # 等这次点击要么发出 PATCH、要么 pill 翻转；都没有就再点一次。
        click_deadline = time.monotonic() + 15
        while time.monotonic() < click_deadline:
            if page.locator("span", has_text="已同步").count() or patch_log:
                break
            page.wait_for_timeout(500)
        if save_tries >= 3 and not patch_log:
            break
        page.wait_for_timeout(500)

    synced_pill = page.locator("span", has_text="已同步").first
    try:
        synced_pill.wait_for(state="visible", timeout=45_000)
    except Exception:  # noqa: BLE001 - 失败留现场再抛
        try:
            page.screenshot(path="C:/vtmp/e2e-memory-save-stuck.png")
            print(
                "[memory-save-stuck] pills=",
                [t for t in page.locator("span").all_inner_texts() if "保存" in t or "同步" in t][:6],
                "; patch_log=", patch_log,
                "; errors=",
                [t for t in page.locator("p").all_inner_texts() if "失败" in t or "错误" in t][:4],
            )
        except Exception:  # noqa: BLE001 - 诊断尽力而为
            pass
        raise
    assert synced_pill.is_visible(), "保存后面板未回到「已同步」"

    # API 复核 enabled=false（权威持久化口径，短轮询等落盘刷新）。
    final_enabled = wait_for_agent_memory_enabled(e2e_instance.port, agent_id, expected=False)
    assert final_enabled is False, "API 复核 memoryPolicy.enabled != false"

    # 刷新页面复查开关持久（仍为关）。重载后面板会先渲染默认草稿再被 agent
    # 数据纠正，因此轮询等待其收敛到 false，而不是读首帧。
    page.reload(wait_until="domcontentloaded")
    nav = page.locator(CONFIG_SECTION_NAV).first
    nav.wait_for(state="visible", timeout=20_000)
    nav.get_by_role("button", name="能力绑定").click()
    panel_title.wait_for(state="visible", timeout=20_000)
    checkbox = page.locator(MEMORY_CHECKBOX).first
    checkbox.wait_for(state="visible", timeout=10_000)
    ui_deadline = time.monotonic() + 20
    ui_reflects_saved = False
    while time.monotonic() < ui_deadline:
        if checkbox.get_attribute("data-selected") == "false":
            ui_reflects_saved = True
            break
        page.wait_for_timeout(1_000)
    assert ui_reflects_saved, "刷新后记忆开关未反映已保存的关闭状态"


def test_wizard_keystroke_before_catalog_backfills_defaults_and_enables_create(
    page: Any, e2e_instance: Any
) -> None:
    """缺陷⑥（修复 949a33cf4）：击键先于目录到达时字段级补齐、创建按钮可用。

    受控竞态：page.route 握住向导目录 API 不放行 → 在「功能名」击键（置脏）→
    至少 2.5s 后才放行目录 → 断言功能名保值、模型补默认值、工具包补默认勾选、
    创建按钮可用。修复前整草稿 draftDirty 门冻结 normalize：模型/工具包停在
    空值，创建按钮永久禁用（本用例会红）；修复后 normalizeCreateDraftForWorkspace
    逐字段保值（规格：字段级保护，archive plan 2026-07-19:81）。

    断到「创建按钮可用」为止，不点击创建（避免实例状态污染；创建成功路径由
    test_create_agent_via_wizard_then_disable_memory 覆盖）。
    """
    display_name = f"e2e 竞态 Agent {uuid.uuid4().hex[:6]}"

    # arrange：后端预探测（与 UI 探测同一实现）筛出真实可用服务商，供第 2 步换选。
    verified = find_working_providers(e2e_instance.port)
    assert verified, (
        "实例模型库中没有任何当前可连通的已配密钥模型，向导无法完成探测步骤"
    )

    # 受控竞态的机关：goto 前安装路由，把目录请求握住不放行（比固定延迟更确定，
    # 击键完成前目录结构上不可能到达）。/agents 页自身会预取 /api/tools，同样
    # 被握住；向导打开后 react-query 对同 key 去重，共用这条在途请求。
    # /api/agents/config-workspace 在纯 /agents 页不预取（fullWorkspaceNeeded=false），
    # 只有向导打开才发，同样落入握持。
    held_routes: list[Any] = []
    catalog_released = {"value": False}

    def _hold_catalog_route(route: Any) -> None:
        if catalog_released["value"]:
            route.continue_()
        else:
            held_routes.append(route)

    page.route(re.compile(r"/api/agents/config-workspace"), _hold_catalog_route)
    page.route(re.compile(r"/api/tools"), _hold_catalog_route)

    page.goto(f"{e2e_instance.base_url}/agents", wait_until="domcontentloaded")
    trigger = page.locator(CREATE_TRIGGER).first
    trigger.wait_for(state="visible", timeout=20_000)
    trigger.click()
    dialog = page.locator('[data-vui="dialog-content"]').first
    dialog.wait_for(state="visible", timeout=15_000)

    # 目录未到时立即击键（缺陷触发前提：draftDirty 在目录返回前置位）。
    name_input = page.get_by_label("功能名").first
    name_input.wait_for(state="visible", timeout=15_000)
    name_input.fill(display_name)
    assert name_input.input_value() == display_name, "击键后功能名应立即生效"

    # 第 1 步只要求功能名，目录未到也可前进；竞态前提坐实：目录仍被握住，
    # 模型清单未加载（触发器禁用、占位符）。
    next_button = page.get_by_role("button", name="下一步").first
    _click_in_dialog(next_button)
    model_trigger = page.locator('button[aria-label="模型"]').first
    model_trigger.wait_for(state="visible", timeout=15_000)
    deadline = time.monotonic() + 10
    while not model_trigger.is_disabled():
        assert time.monotonic() < deadline, "目录握住期间模型清单不应加载"
        page.wait_for_timeout(500)
    page.wait_for_timeout(2_500)  # 击键后目录仍扣留 ≥2.5s：复现缺陷⑥时序

    catalog_released["value"] = True
    for held in held_routes:
        held.continue_()
    held_routes.clear()

    # 断言一（缺陷核心）：模型补上默认值（触发器离开占位符）。旧实现在此
    # 永久停留「选择模型」。
    deadline = time.monotonic() + 30
    model_value = ""
    while time.monotonic() < deadline:
        model_value = (model_trigger.inner_text() or "").strip()
        if model_value and model_value != "选择模型":
            break
        page.wait_for_timeout(500)
    assert model_value and model_value != "选择模型", (
        f"目录放行后模型未补默认值（触发器文本={model_value!r}）"
    )

    # 第 2 步：把模型换成 API 预验证过的 (服务商, 模型) 精确对并真实探测
    # （与既有向导用例同口径；探测失败则换下一个预验证对）。
    probe_button = page.get_by_role("button", name="探测当前模型").first
    probe_button.wait_for(state="visible", timeout=15_000)
    probe_passed = False
    for provider_id, model_id in verified[:3]:
        if not _pick_provider_by_id(page, provider_id):
            continue
        if not _pick_model_by_id(page, model_id):
            continue
        _click_in_dialog(probe_button)
        result_deadline = time.monotonic() + 45
        while time.monotonic() < result_deadline:
            if page.get_by_text("探测通过，可以使用该模型创建会话。").count():
                probe_passed = True
                break
            if page.get_by_text("探测失败").count():
                break
            page.wait_for_timeout(1_000)
        if probe_passed:
            break
        page.wait_for_timeout(1_000)
    assert probe_passed, "预验证服务商的模型探测未通过（检查实例模型库密钥/网络）"
    deadline = time.monotonic() + 10
    while next_button.is_disabled():
        assert time.monotonic() < deadline, "探测通过后「下一步」仍未解锁"
        page.wait_for_timeout(500)
    _click_in_dialog(next_button)

    # 第 3 步：断言二（功能名保值，创建前确认首行=名称）。
    create_button = page.get_by_role("button", name="创建 Agent").first
    create_button.wait_for(state="visible", timeout=15_000)
    summary_name = dialog.locator('section[aria-label="创建前确认"] dd').first
    summary_name.wait_for(state="visible", timeout=15_000)
    assert (summary_name.inner_text() or "").strip() == display_name, (
        "目录补齐后功能名被覆盖（规格要求字段级保护）"
    )

    # 断言三：工具包有可选项且默认勾选非空（旧实现停留 0 勾选）。
    bundle_checks = dialog.locator('input[type="checkbox"]')
    deadline = time.monotonic() + 15
    checked_count = 0
    while time.monotonic() < deadline:
        checked_count = bundle_checks.evaluate_all(
            "els => els.filter(el => el.checked).length"
        )
        if bundle_checks.count() > 0 and checked_count > 0:
            break
        page.wait_for_timeout(500)
    assert bundle_checks.count() > 0, "工具包清单未加载"
    assert checked_count > 0, "工具包未自动勾选默认包"

    # 断言四（缺陷终态）：创建按钮可用。旧实现在此永久禁用。
    deadline = time.monotonic() + 15
    while create_button.is_disabled():
        assert time.monotonic() < deadline, "创建按钮未就绪（缺陷⑥症状：永久禁用）"
        page.wait_for_timeout(500)
    assert create_button.is_enabled(), "创建按钮应可用"
