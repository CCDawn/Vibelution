"""A-share backtest and trading-day schedule browser acceptance."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.agent_factory import create_session
from tests.e2e.helpers.api_write import post_json

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(
        not e2e_enabled(),
        reason="Set VIBELUTION_E2E=1 for isolated browser acceptance",
    ),
]

BLOCKED_PREVIEW = "测试拦截：行情预检条件不满足"


def _finance_url(instance, session_id: str, **navigation: str) -> str:
    """Use the finance workspace's documented query keys and preserve native session selection."""
    query = {"session": session_id, **navigation}
    return f"{instance.base_url}/finance?{urlencode(query)}"


def _assert_no_horizontal_overflow(page, width: int) -> None:
    dimensions = page.evaluate(
        """() => ({
          viewport: window.innerWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
        })"""
    )
    assert dimensions["viewport"] == width
    assert max(dimensions["document"], dimensions["body"]) <= width, dimensions


@pytest.mark.parametrize(
    ("width", "height"),
    [(1280, 800), (1920, 1080)],
    ids=["desktop-1280x800", "desktop-1920x1080"],
)
def test_a_share_backtest_fields_blocking_preview_and_trading_day_schedule(
    page, e2e_instance, tmp_path: Path, width: int, height: int
):
    from playwright.sync_api import expect

    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.set_viewport_size({"width": width, "height": height})
    assistant = post_json(
        e2e_instance.port, "/api/financial-assistants", {"displayName": "炒股智能体"}
    )["assistant"]
    assert assistant["modelStatus"] == "configured_unverified"
    session_id = create_session(
        e2e_instance.port, title="A股回测验收", agent_id=assistant["agentId"]
    )

    # `review` and `backtest` are the actual finance area and reviewTab values;
    # keep the native `session` query independent from finance view navigation.
    page.goto(
        _finance_url(
            e2e_instance,
            session_id,
            finance_area="review",
            finance_reviewTab="backtest",
        ),
        wait_until="domcontentloaded",
    )
    expect(page.locator("div[data-agent-thread-id]").first).to_have_attribute(
        "data-agent-thread-id", session_id, timeout=30_000
    )

    source = page.get_by_role("combobox", name="AI回测历史行情源", exact=True)
    expect(source).to_be_visible(timeout=30_000)
    expect(source).to_contain_text("腾讯财经")
    volume_cap = page.get_by_role("spinbutton", name="日成交量上限 %", exact=True)
    expect(volume_cap).to_have_value("1")
    research_input = page.get_by_role("combobox", name="AI回测研究输入", exact=True)
    expect(research_input).to_contain_text("仅行情")

    source.click()
    page.get_by_role("option", name="东方财富", exact=True).click()
    volume_cap.fill("0.5")
    research_input.click()
    page.get_by_role("option", name="行情 + 历史公告", exact=True).click()
    expect(source).to_contain_text("东方财富")
    expect(volume_cap).to_have_value("0.5")
    expect(research_input).to_contain_text("行情 + 历史公告")

    preview_requests: list[dict] = []
    unexpected_mutations: list[str] = []
    preview_path = "**/api/financial-backtests/*/preview"

    def block_preview(route):
        preview_requests.append(route.request.post_data_json)
        route.fulfill(
            status=422,
            content_type="application/json",
            body=json.dumps({"detail": BLOCKED_PREVIEW}, ensure_ascii=False),
        )

    def record_mutation(request):
        if request.method == "POST" and (
            "/runs" in request.url or "/schedules" in request.url
        ):
            unexpected_mutations.append(request.url)

    page.route(preview_path, block_preview)
    page.on("request", record_mutation)
    try:
        check = page.get_by_role("button", name="检查数据与预算", exact=True)
        try:
            expect(check).to_be_enabled(timeout=15_000)
        except AssertionError:
            print(page.locator("body").aria_snapshot())
            raise
        check.click()
        expect(page.get_by_text(BLOCKED_PREVIEW, exact=True)).to_be_visible(timeout=15_000)
        assert len(preview_requests) == 1
        assert preview_requests[0]["dataSource"] == "eastmoney"
        assert preview_requests[0]["maxParticipationPct"] == 0.5
        assert preview_requests[0]["researchInput"] == "announcements"
        assert page.get_by_role("button", name="开始AI回测", exact=True).count() == 0
        assert not unexpected_mutations
        _assert_no_horizontal_overflow(page, width)
        backtest_screenshot = tmp_path / f"finance-backtest-{width}x{height}.png"
        page.screenshot(path=str(backtest_screenshot), full_page=True)
        print(f"[finance-a-share-e2e] screenshot={backtest_screenshot}")
    finally:
        page.unroute(preview_path, block_preview)

    # The task center's schedule view is `tasks` + `taskTab=schedules`.
    # Verify the A-share trading calendar choice without saving or enabling it.
    page.goto(
        _finance_url(
            e2e_instance,
            session_id,
            finance_area="tasks",
            finance_taskTab="schedules",
        ),
        wait_until="domcontentloaded",
    )
    expect(page.locator("div[data-agent-thread-id]").first).to_have_attribute(
        "data-agent-thread-id", session_id, timeout=30_000
    )
    frequency = page.get_by_role("combobox", name="执行频率", exact=True)
    expect(frequency).to_be_visible(timeout=30_000)
    expect(frequency).to_contain_text("A股交易日")
    frequency.click()
    page.get_by_role("option", name="每天", exact=True).click()
    frequency.click()
    page.get_by_role("option", name="A股交易日", exact=True).click()
    expect(frequency).to_contain_text("A股交易日")
    expect(page.get_by_text("按已核实交易日历；补跑沿用原计划日，未知年份不触发", exact=True)).to_be_visible()
    assert not unexpected_mutations
    _assert_no_horizontal_overflow(page, width)
    schedule_screenshot = tmp_path / f"finance-schedule-{width}x{height}.png"
    page.screenshot(path=str(schedule_screenshot), full_page=True)
    print(f"[finance-a-share-e2e] screenshot={schedule_screenshot}")

    assert not page_errors, f"Uncaught browser errors: {page_errors}"
    page.remove_listener("request", record_mutation)
