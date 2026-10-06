"""Financial paper ledger isolation, accounting, concurrency, and HTTP contracts."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes import financial_paper as paper_routes
from core.web.routes.financial_paper import router
from core.web.services import agent_directory_service as directory
from core.web.services import financial_paper_service as paper
from core.web.services import financial_research_service as research
from core.web.services.financial_assistant_service import PROFILE, ROLE
from core.web.services.financial_paper import ledger
from tests.test_financial_knowledge_service import finance_env as _finance_env

finance_env = _finance_env


def _agent(label: str = "Paper account") -> dict:
    return directory.create_agent_instance(
        display_name=label,
        primary_mode="general",
        role_key=ROLE,
        prompt_template_id="prompt-chat-default",
        metadata={
            "financialAssistantProfile": PROFILE,
            "financialAssistantSetup": "ready",
        },
    )


def _snapshot(symbol: str = "sh600519", price: float = 10.0) -> dict:
    ticker = symbol[2:]
    return {
        "stock": {
            "symbol": symbol,
            "ticker": ticker,
            "name": "贵州茅台",
            "market": "上交所",
            "price": price,
            "timestamp": "2026-10-05T15:00:00+08:00",
        },
        "source": "腾讯财经",
        "sourceUrl": f"https://gu.qq.com/{symbol}/gp",
        "fetchedAt": "2026-10-05T07:00:02+00:00",
    }


def _batch(symbols: list[str], price: float = 10.0) -> dict:
    return {
        "source": "腾讯财经",
        "sourceUrl": "https://gu.qq.com/",
        "fetchedAt": "2026-10-05T07:00:02+00:00",
        "items": [
            {
                "symbol": symbol,
                "quote": _snapshot(symbol, price)["stock"],
                "error": None,
            }
            for symbol in symbols
        ],
    }


@pytest.fixture
def paper_env(finance_env, monkeypatch):
    agent = _agent()
    quote = {"price": 10.0}
    monkeypatch.setattr(
        research,
        "batch_quotes",
        lambda symbols: _batch(symbols, quote["price"]),
    )
    return {**finance_env, "agent": agent, "quote": quote}


def test_get_is_read_only_and_account_open_is_idempotent(paper_env):
    agent_id = paper_env["agent"]["agentId"]
    path = ledger._ledger_path(directory.get_agent(agent_id))
    assert not path.exists()
    with pytest.raises(paper.AccountNotOpenedError):
        paper.get_account_snapshot(agent_id)
    assert not path.exists()
    assert not path.parent.exists()

    first = paper.open_account(agent_id)
    second = paper.open_account(agent_id)
    assert first["accountId"] == second["accountId"]
    assert first["initialCashYuan"] == "1000000.00"
    assert first["cashYuan"] == "1000000.00"
    assert first["positions"] == []
    assert path.exists()


def test_concurrent_account_open_creates_one_account(paper_env):
    from concurrent.futures import ThreadPoolExecutor

    agent_id = paper_env["agent"]["agentId"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda _: paper.open_account(agent_id), range(12)))
    assert len({row["accountId"] for row in rows}) == 1
    assert all(row["initialCashYuan"] == "1000000.00" for row in rows)


def test_concurrent_identical_order_is_recorded_once(paper_env):
    from concurrent.futures import ThreadPoolExecutor

    agent_id = paper_env["agent"]["agentId"]
    paper.open_account(agent_id)
    request = {
        "client_order_id": str(uuid4()),
        "symbol": "sh600519",
        "side": "buy",
        "quantity": 100,
        "reason": "并发重试必须只记一笔",
    }
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(
            pool.map(lambda _: paper.submit_order(agent_id, **request), range(8))
        )
    assert all(row["ordersTotal"] == 1 for row in rows)
    account = paper.get_account_snapshot(agent_id)
    assert account["ordersTotal"] == 1
    assert account["cashYuan"] == "998995.00"


def test_insufficient_cash_does_not_mutate_the_ledger(paper_env):
    agent_id = paper_env["agent"]["agentId"]
    paper.open_account(agent_id)
    paper_env["quote"]["price"] = 10001.0
    with pytest.raises(paper.InsufficientCashError):
        paper.submit_order(
            agent_id,
            client_order_id=str(uuid4()),
            symbol="sh600519",
            side="buy",
            quantity=100,
            reason="总成本超过虚拟余额",
        )
    account = paper.get_account_snapshot(agent_id)
    assert account["cashYuan"] == "1000000.00"
    assert account["ordersTotal"] == 0 and account["positions"] == []


def test_decimal_fees_t_plus_one_idempotency_and_full_ledger_review(
    paper_env, monkeypatch
):
    agent_id = paper_env["agent"]["agentId"]
    paper.open_account(agent_id)
    now = {"value": datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)}
    day = {"value": datetime(2026, 10, 5, tzinfo=timezone.utc).date()}
    monkeypatch.setattr(ledger, "_utc_now", lambda: now["value"])
    monkeypatch.setattr(ledger, "_beijing_date", lambda _value=None: day["value"])
    key = str(uuid4())
    bought = paper.submit_order(
        agent_id,
        client_order_id=key,
        symbol="600519",
        side="buy",
        quantity=200,
        reason="核对公开行情后的模拟买入",
    )
    assert bought["cashYuan"] == "997995.00"
    assert bought["positions"][0]["quantity"] == 200
    assert bought["positions"][0]["availableQuantity"] == 0
    assert bought["orders"][0]["priceYuan"] == "10.00"
    assert bought["orders"][0]["quoteDate"] == "2026-10-05"
    assert bought["orders"][0]["commissionYuan"] == "5.00"
    assert bought["orders"][0]["stampDutyYuan"] == "0.00"

    paper_env["quote"]["price"] = 11.0
    with pytest.raises(paper.InsufficientSharesError, match=r"T\+1"):
        paper.submit_order(
            agent_id,
            client_order_id=str(uuid4()),
            symbol="sh600519",
            side="sell",
            quantity=100,
            reason="尝试当日卖出",
        )

    day["value"] = datetime(2026, 10, 6, tzinfo=timezone.utc).date()
    now["value"] += timedelta(days=1)
    sell_key = str(uuid4())
    sold = paper.submit_order(
        agent_id,
        client_order_id=sell_key,
        symbol="sh600519",
        side="sell",
        quantity=100,
        reason="次日按北京时间自然日模拟卖出",
    )
    sale = sold["orders"][0]
    assert sale["grossAmountYuan"] == "1100.00"
    assert sale["commissionYuan"] == "5.00"
    assert sale["stampDutyYuan"] == "0.55"
    assert sale["realizedPnlYuan"] == "91.95"
    assert sold["positions"][0]["quantity"] == 100
    assert sold["positions"][0]["availableQuantity"] == 100

    replayed = paper.submit_order(
        agent_id,
        client_order_id=sell_key,
        symbol="sh600519",
        side="sell",
        quantity=100,
        reason="次日按北京时间自然日模拟卖出",
    )
    assert replayed["ordersTotal"] == 2
    with pytest.raises(paper.IdempotencyConflictError):
        paper.submit_order(
            agent_id,
            client_order_id=sell_key,
            symbol="sh600519",
            side="sell",
            quantity=200,
            reason="不同订单复用同一个幂等键",
        )

    review = paper.get_review_snapshot(agent_id, month="2026-10")
    assert review["summary"]["totalTradeCount"] == 2
    assert review["summary"]["allTimeRealizedPnlYuan"] == "91.95"
    assert review["summary"]["allTimeFeesYuan"] == "10.55"
    assert review["summary"]["monthTradeCount"] == 2
    assert review["summary"]["monthRealizedPnlYuan"] == "91.95"
    assert len(review["days"]) == 2
    assert [order["side"] for order in review["account"]["orders"]] == [
        "sell",
        "buy",
    ]
    assert review["account"]["orders"][0]["reason"] == "次日按北京时间自然日模拟卖出"
    assert review["account"]["ordersLimit"] == 20
    assert review["account"]["ordersTruncated"] is False
    assert "requestFingerprint" not in review["account"]["orders"][0]


def test_agents_cannot_read_or_spend_each_others_virtual_balance(paper_env):
    first_id = paper_env["agent"]["agentId"]
    second = _agent("Separate paper account")
    second_id = second["agentId"]
    paper.open_account(first_id)
    paper.open_account(second_id)
    paper.submit_order(
        first_id,
        client_order_id=str(uuid4()),
        symbol="sh600519",
        side="buy",
        quantity=100,
        reason="只记入第一个金融 Agent 的模拟账本",
    )
    first = paper.get_account_snapshot(first_id)
    other = paper.get_account_snapshot(second_id)
    assert first["cashYuan"] == "998995.00"
    assert other["cashYuan"] == "1000000.00"
    assert other["positions"] == [] and other["ordersTotal"] == 0
    assert first["accountId"] != other["accountId"]


def test_holdings_use_one_quote_batch_and_preserve_partial_quote_failures(
    paper_env, monkeypatch
):
    agent_id = paper_env["agent"]["agentId"]
    paper.open_account(agent_id)
    for symbol in ("sh600519", "sz000001"):
        paper.submit_order(
            agent_id,
            client_order_id=str(uuid4()),
            symbol=symbol,
            side="buy",
            quantity=100,
            reason="核对持仓批量估值与逐股失败",
        )
    calls = []

    def quote_batch(symbols):
        calls.append(symbols)
        result = _batch(symbols, 12.0)
        result["items"] = [
            row
            if row["symbol"] == "sh600519"
            else {"symbol": row["symbol"], "quote": None, "error": "行情缺失"}
            for row in result["items"]
        ]
        return result

    monkeypatch.setattr(research, "batch_quotes", quote_batch)
    snapshot = paper.get_account_snapshot(agent_id)
    assert len(calls) == 1 and set(calls[0]) == {"sh600519", "sz000001"}
    positions = {row["symbol"]: row for row in snapshot["positions"]}
    assert positions["sh600519"]["markPriceYuan"] == "12.00"
    assert positions["sh600519"]["valuationStatus"] == "fresh"
    assert positions["sz000001"]["markPriceYuan"] == "10.00"
    assert positions["sz000001"]["valuationStatus"] == "stale"
    assert snapshot["marketValueYuan"] == "2200.00"
    assert snapshot["valuationStatus"] == "partial"


def test_paper_orders_reject_hk_us_before_requesting_quotes(paper_env, monkeypatch):
    agent_id = paper_env["agent"]["agentId"]
    paper.open_account(agent_id)
    calls = []
    monkeypatch.setattr(research, "batch_quotes", lambda symbols: calls.append(symbols) or _batch(symbols))
    for symbol in ("hk00700", "usAAPL"):
        with pytest.raises(paper.InvalidPaperOrderError, match="仅支持 A 股"):
            paper.submit_order(
                agent_id,
                client_order_id=str(uuid4()),
                symbol=symbol,
                side="buy",
                quantity=100,
                reason="多市场研究不能进入人民币A股模拟账本",
            )
    assert calls == []
    account = paper.get_account_snapshot(agent_id)
    assert account["ordersTotal"] == 0 and account["positions"] == []


def test_legacy_foreign_holding_is_never_valued_as_yuan(paper_env, monkeypatch):
    calls = []
    monkeypatch.setattr(research, "batch_quotes", lambda symbols: calls.append(symbols) or _batch(symbols))
    source_ledger = {
        "agentId": paper_env["agent"]["agentId"],
        "account": {
            "accountId": "legacy-account",
            "openedAt": "2026-01-01T00:00:00+00:00",
            "initialCashYuan": "1000000.00",
            "cashYuan": "900000.00",
        },
        "positions": {
            "hk00700": {
                "ticker": "00700",
                "name": "腾讯控股",
                "market": "港交所",
                "lots": [
                    {
                        "remainingQuantity": 100,
                        "remainingCostYuan": "10000.00",
                        "acquiredBeijingDate": "2026-01-01",
                    }
                ],
                "lastQuote": {
                    "priceYuan": "427.40",
                    "timestamp": "2026-10-06T13:39:52+08:00",
                    "source": "腾讯财经",
                    "sourceUrl": "https://gu.qq.com/hk00700/gp",
                },
            }
        },
        "orders": [],
    }

    snapshot = ledger._account_snapshot_from_ledger(source_ledger, order_limit=50)
    position = snapshot["positions"][0]
    assert calls == []
    assert position["valuationStatus"] == "unavailable"
    assert position["markPriceYuan"] is None
    assert position["marketValueYuan"] is None
    assert position["unrealizedPnlYuan"] is None
    assert position["quoteTimestamp"] == "" and position["sourceUrl"] == ""
    assert snapshot["marketValueYuan"] == "0.00"
    assert snapshot["valuationStatus"] == "partial"


def test_financial_paper_routes_are_typed_read_only_until_explicit_open(
    paper_env, monkeypatch
):
    events = []
    record = lambda *args, **kwargs: events.append((args, kwargs))
    monkeypatch.setattr(ledger, "record_runtime_scene_event_quietly", record)
    monkeypatch.setattr(paper_routes, "record_runtime_scene_event_quietly", record)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    agent_id = paper_env["agent"]["agentId"]
    path = ledger._ledger_path(directory.get_agent(agent_id))

    assert client.get(f"/api/financial-paper/{agent_id}").status_code == 404
    assert not path.exists() and not path.parent.exists()
    opened = client.post(f"/api/financial-paper/{agent_id}/account")
    assert opened.status_code == 200, opened.text
    assert opened.json()["simulationOnly"] is True
    assert opened.json()["initialCashYuan"] == "1000000.00"
    assert (
        client.post(
            f"/api/financial-paper/{agent_id}/account",
            json={"initialCashYuan": "999999999"},
        ).status_code
        == 422
    )

    market_calls = []
    monkeypatch.setattr(
        research,
        "batch_quotes",
        lambda symbols: market_calls.append(symbols) or _batch(symbols),
    )
    malformed = client.post(
        f"/api/financial-paper/{agent_id}/orders",
        json={
            "clientOrderId": str(uuid4()),
            "symbol": "sh600519",
            "side": "buy",
            "quantity": 100,
            "reason": "test order",
            "priceYuan": "1.00",
        },
    )
    assert malformed.status_code == 422
    assert market_calls == []

    placed = client.post(
        f"/api/financial-paper/{agent_id}/orders",
        json={
            "clientOrderId": str(uuid4()),
            "symbol": "sh600519",
            "side": "buy",
            "quantity": 100,
            "reason": "review quote provenance",
        },
    )
    assert placed.status_code == 200, placed.text
    body = placed.json()
    assert body["positions"][0]["source"] == "腾讯财经"
    assert body["positions"][0]["quoteTimestamp"] == "2026-10-05T15:00:00+08:00"
    assert body["orders"][0]["quoteFetchedAt"] == "2026-10-05T07:00:02+00:00"
    assert "requestFingerprint" not in body["orders"][0]

    rejected = client.post(
        f"/api/financial-paper/{agent_id}/orders",
        json={
            "clientOrderId": str(uuid4()),
            "symbol": "sh600519",
            "side": "sell",
            "quantity": 100,
            "reason": "same-day test sale",
        },
    )
    assert rejected.status_code == 422
    assert "T+1" in rejected.json()["detail"]
    assert [event[0][2] for event in events] == [
        "finance.paper_account.opened",
        "finance.paper_order.recorded",
        "finance.paper_order.rejected",
    ]
    assert all(event[1]["fields"]["agentId"] == agent_id for event in events)
    assert all(event[1]["fields"]["simulationOnly"] is True for event in events)
    assert events[-1][1]["fields"]["reason"] == "InsufficientSharesError"
    assert "same-day test sale" not in str(events)

    review = client.get(f"/api/financial-paper/{agent_id}/review?month=2026-10")
    assert review.status_code == 200, review.text
    assert review.json()["summary"]["totalTradeCount"] == 1
    assert review.json()["account"]["orders"] == body["orders"]
    assert review.json()["account"]["ordersLimit"] == 20
    assert (
        client.get(f"/api/financial-paper/{agent_id}/review?month=2026-13").status_code
        == 422
    )
    assert all(
        method == "GET"
        for path, methods in app.openapi()["paths"].items()
        if "financial-market" in path
        for method in methods
    )
