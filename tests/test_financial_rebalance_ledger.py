"""Atomic batch execution against the simulation-only paper ledger."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event
from time import sleep
from uuid import UUID, uuid4, uuid5

import pytest

from core.web.services import agent_directory_service as directory
from core.web.services import financial_paper_service as paper
from core.web.services import financial_research_service as research
from core.web.services.financial_assistant_service import PROFILE, ROLE
from core.web.services.financial_paper import ledger, rebalance
from tests.test_financial_knowledge_service import finance_env as _finance_env

finance_env = _finance_env


def _agent() -> dict:
    return directory.create_agent_instance(
        display_name="Paper rebalance account",
        primary_mode="general",
        role_key=ROLE,
        prompt_template_id="prompt-chat-default",
        metadata={
            "financialAssistantProfile": PROFILE,
            "financialAssistantSetup": "ready",
        },
    )


def _quote(symbol: str, price: str = "10.00") -> dict:
    return {
        "symbol": symbol,
        "ticker": symbol[2:],
        "name": "贵州茅台" if symbol == "sh600519" else "平安银行",
        "market": "上交所" if symbol.startswith("sh") else "深交所",
        "priceYuan": price,
        "timestamp": "2026-10-06T15:00:00+08:00",
        "fetchedAt": "2026-10-06T07:00:02+00:00",
        "source": "腾讯财经",
        "sourceUrl": f"https://gu.qq.com/{symbol}/gp",
    }


def _quote_batch(symbols: list[str]) -> dict:
    return {
        "source": "腾讯财经",
        "sourceUrl": "https://gu.qq.com/",
        "fetchedAt": "2026-10-06T07:00:02+00:00",
        "items": [
            {
                "symbol": symbol,
                "quote": {
                    "symbol": symbol,
                    "ticker": symbol[2:],
                    "name": "贵州茅台" if symbol == "sh600519" else "平安银行",
                    "market": "上交所" if symbol.startswith("sh") else "深交所",
                    "price": 10.0,
                    "timestamp": "2026-10-06T15:00:00+08:00",
                },
                "error": None,
            }
            for symbol in symbols
        ],
    }


@pytest.fixture
def rebalance_env(finance_env, monkeypatch):
    agent = _agent()
    monkeypatch.setattr(research, "batch_quotes", _quote_batch)
    paper.open_account(agent["agentId"])
    return {**finance_env, "agent": agent}


def _metadata() -> dict:
    return {
        "proposalId": "proposal-1",
        "planHash": "b" * 64,
        "reportRefs": [
            {
                "sessionId": "session-1",
                "turnId": "turn-1",
                "contentHash": "c" * 64,
            }
        ],
    }


def _orders() -> list[dict]:
    # Deliberately put the buy first; the ledger applies sells before buys.
    return [
        {
            "symbol": "sz000001",
            "side": "buy",
            "quantity": 100,
            "reason": "按已批准组合补足目标权重",
        },
        {
            "symbol": "sh600519",
            "side": "sell",
            "quantity": 100,
            "reason": "按已批准组合降低目标权重",
        },
    ]


def _quotes() -> dict:
    return {
        "sh600519": _quote("sh600519", "11.00"),
        "sz000001": _quote("sz000001", "10.00"),
    }


def _execute(agent_id: str, context: dict, *, batch_id: str | None = None, **changes):
    args = {
        "batch_id": batch_id or str(uuid4()),
        "request_hash": "a" * 64,
        "expected_ledger_fingerprint": context["ledgerFingerprint"],
        "orders": _orders(),
        "quotes": _quotes(),
        "metadata": _metadata(),
    }
    args.update(changes)
    return rebalance.execute_rebalance(agent_id, **args)


def _buy_old_holding(agent_id: str, monkeypatch):
    monkeypatch.setattr(
        ledger,
        "_utc_now",
        lambda: datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc),
    )
    paper.submit_order(
        agent_id,
        client_order_id=str(uuid4()),
        symbol="sh600519",
        side="buy",
        quantity=200,
        reason="准备次日可卖的持仓",
    )
    monkeypatch.setattr(
        ledger,
        "_utc_now",
        lambda: datetime(2026, 10, 6, 3, 0, tzinfo=timezone.utc),
    )


def test_read_context_returns_stable_fingerprint_and_sellable_quantities(
    rebalance_env, monkeypatch
):
    agent_id = rebalance_env["agent"]["agentId"]
    _buy_old_holding(agent_id, monkeypatch)

    first = rebalance.read_rebalance_context(agent_id)
    second = rebalance.read_rebalance_context(agent_id)

    assert first == second
    assert first["accountId"] == paper.get_account_snapshot(agent_id)["accountId"]
    assert first["cashYuan"] == "997995.00"
    assert first["positions"] == [
        {
            "symbol": "sh600519",
            "quantity": 200,
            "sellableQuantity": 200,
            "name": "贵州茅台",
        }
    ]
    assert len(first["ledgerFingerprint"]) == 64


def test_rebalance_applies_sells_before_buys_and_writes_once(rebalance_env, monkeypatch):
    agent_id = rebalance_env["agent"]["agentId"]
    _buy_old_holding(agent_id, monkeypatch)
    context = rebalance.read_rebalance_context(agent_id)
    path = ledger._ledger_path(directory.get_agent(agent_id))
    original_write = ledger._write_ledger
    writes = []

    def counted_write(*args, **kwargs):
        writes.append(args[0])
        return original_write(*args, **kwargs)

    monkeypatch.setattr(ledger, "_write_ledger", counted_write)

    batch = _execute(agent_id, context)
    account = paper.get_account_snapshot(agent_id)
    persisted = ledger._load_ledger(path, agent_id)

    assert len(writes) == 1
    assert [order["side"] for order in batch["orders"]] == ["sell", "buy"]
    assert [order["side"] for order in account["orders"][:2]] == ["buy", "sell"]
    assert batch["beforeCashYuan"] == "997995.00"
    assert batch["afterCashYuan"] == "998084.45"
    assert account["cashYuan"] == "998084.45"
    assert account["totalFeesYuan"] == "15.55"
    assert batch["accountId"] == account["accountId"]
    assert batch["ledgerFingerprint"] == context["ledgerFingerprint"]
    assert batch["metadata"] == _metadata()
    assert len(batch["resultingLedgerFingerprint"]) == 64
    assert persisted["rebalanceBatches"][-1]["batchId"] == batch["batchId"]
    assert [order["clientOrderId"] for order in batch["orders"]] == [
        str(uuid5(UUID(batch["batchId"]), f"{order['symbol']}:{order['side']}"))
        for order in batch["orders"]
    ]


def test_later_leg_failure_leaves_ledger_bytes_unchanged(rebalance_env, monkeypatch):
    agent_id = rebalance_env["agent"]["agentId"]
    _buy_old_holding(agent_id, monkeypatch)
    context = rebalance.read_rebalance_context(agent_id)
    path = ledger._ledger_path(directory.get_agent(agent_id))
    before = path.read_bytes()
    orders = [
        {
            "symbol": "sh600519",
            "side": "sell",
            "quantity": 100,
            "reason": "先执行的卖出腿",
        },
        {
            "symbol": "sz000001",
            "side": "buy",
            "quantity": 100_000,
            "reason": "故意超过可用余额的买入腿",
        },
    ]

    with pytest.raises(paper.InsufficientCashError):
        rebalance.execute_rebalance(
            agent_id,
            batch_id=str(uuid4()),
            request_hash="c" * 64,
            expected_ledger_fingerprint=context["ledgerFingerprint"],
            orders=orders,
            quotes=_quotes(),
            metadata=_metadata(),
        )

    assert path.read_bytes() == before
    assert ledger._load_ledger(path, agent_id).get("rebalanceBatches", []) == []


def test_batch_retry_is_idempotent_without_quotes_and_hash_conflicts(
    rebalance_env, monkeypatch
):
    agent_id = rebalance_env["agent"]["agentId"]
    _buy_old_holding(agent_id, monkeypatch)
    context = rebalance.read_rebalance_context(agent_id)
    batch_id = str(uuid4())
    committed = _execute(agent_id, context, batch_id=batch_id)

    replayed = _execute(
        agent_id,
        context,
        batch_id=batch_id,
        orders=[],
        quotes={},
        expected_ledger_fingerprint="0" * 64,
    )

    assert replayed == committed
    with pytest.raises(paper.IdempotencyConflictError):
        _execute(
            agent_id,
            context,
            batch_id=batch_id,
            request_hash="d" * 64,
            orders=[],
            quotes={},
        )


def test_concurrent_identical_rebalance_is_recorded_once(rebalance_env, monkeypatch):
    agent_id = rebalance_env["agent"]["agentId"]
    _buy_old_holding(agent_id, monkeypatch)
    context = rebalance.read_rebalance_context(agent_id)
    batch_id = str(uuid4())

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda _: _execute(agent_id, context, batch_id=batch_id), range(8)
            )
        )

    assert all(result == results[0] for result in results)
    account = paper.get_account_snapshot(agent_id)
    path = ledger._ledger_path(directory.get_agent(agent_id))
    persisted = ledger._load_ledger(path, agent_id)
    assert account["ordersTotal"] == 3
    assert len(persisted["rebalanceBatches"]) == 1
    assert len(results[0]["orders"]) == 2


def test_concurrent_distinct_rebalances_reject_the_stale_fingerprint(
    rebalance_env, monkeypatch
):
    agent_id = rebalance_env["agent"]["agentId"]
    _buy_old_holding(agent_id, monkeypatch)
    context = rebalance.read_rebalance_context(agent_id)

    def execute(batch_id: str):
        try:
            return _execute(agent_id, context, batch_id=batch_id)
        except paper.PaperAccountConflictError:
            return None

    batch_ids = [str(uuid4()), str(uuid4())]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, batch_ids))

    assert sum(result is not None for result in results) == 1
    path = ledger._ledger_path(directory.get_agent(agent_id))
    persisted = ledger._load_ledger(path, agent_id)
    assert len(persisted["rebalanceBatches"]) == 1
    assert paper.get_account_snapshot(agent_id)["ordersTotal"] == 3


def test_quote_expiry_is_checked_after_waiting_for_ledger_lock(
    rebalance_env, monkeypatch
):
    agent_id = rebalance_env["agent"]["agentId"]
    _buy_old_holding(agent_id, monkeypatch)
    monkeypatch.setattr(ledger, "_utc_now", lambda: datetime.now(timezone.utc))
    context = rebalance.read_rebalance_context(agent_id)
    path = ledger._ledger_path(directory.get_agent(agent_id))
    original_transaction_lock = ledger._transaction_lock
    waiting_for_lock = Event()

    @contextmanager
    def observed_transaction_lock(lock_path):
        waiting_for_lock.set()
        with original_transaction_lock(lock_path):
            yield

    monkeypatch.setattr(ledger, "_transaction_lock", observed_transaction_lock)
    expires_at = datetime.now(timezone.utc) + timedelta(milliseconds=500)
    before = path.read_bytes()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with original_transaction_lock(path):
            future = pool.submit(
                _execute,
                agent_id,
                context,
                expires_at=expires_at.isoformat(),
            )
            assert waiting_for_lock.wait(timeout=5)
            remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                sleep(remaining + 0.05)

        with pytest.raises(paper.PaperAccountConflictError, match="过期"):
            future.result(timeout=5)

    assert path.read_bytes() == before
    assert ledger._load_ledger(path, agent_id).get("rebalanceBatches", []) == []


def test_stale_ledger_fingerprint_rejects_without_mutation(rebalance_env, monkeypatch):
    agent_id = rebalance_env["agent"]["agentId"]
    stale_context = rebalance.read_rebalance_context(agent_id)
    paper.submit_order(
        agent_id,
        client_order_id=str(uuid4()),
        symbol="sh600519",
        side="buy",
        quantity=100,
        reason="制造已变化的账本版本",
    )
    path = ledger._ledger_path(directory.get_agent(agent_id))
    before = path.read_bytes()

    with pytest.raises(paper.PaperAccountConflictError):
        _execute(agent_id, stale_context)

    assert path.read_bytes() == before
