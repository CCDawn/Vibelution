"""Bounded, revision-checked desktop settings in the financial Agent territory."""

from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services import financial_market_service as market
from core.web.services.financial_preferences_service import FinancialPreferenceError, _agent
from core.web.services.financial_team import runs

_LOCK = threading.RLock()
_SECTIONS = {"selectedStock", "watchlist", "profiles", "manualPositions", "reviewCases"}
_PERSISTED_FIELDS = {"schemaVersion", "agentId", "revision", "updatedAt", *_SECTIONS}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


def _text(value: Any, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise FinancialPreferenceError("设置内容必须为文本")
    result = value.strip()
    if (not result and not empty) or len(result) > limit or any(ord(c) < 32 and c not in "\n\t" for c in result):
        raise FinancialPreferenceError("设置内容为空或超过长度限制")
    return result


def _identifier(value: Any) -> str:
    result = _text(value, 160)
    if not _ID.fullmatch(result) or ".." in result:
        raise FinancialPreferenceError("设置标识无效")
    return result


def _tags(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 10:
        raise FinancialPreferenceError("每条记录最多 10 个标签")
    return list(dict.fromkeys(_text(tag, 30) for tag in value))


def _stock(value: Any) -> dict:
    if not isinstance(value, dict):
        raise FinancialPreferenceError("股票设置无效")
    try:
        symbol = market.normalize_symbol(_text(value.get("symbol"), 24))
    except market.MarketDataError as exc:
        raise FinancialPreferenceError("股票代码无效") from exc
    ticker = symbol[2:]
    raw_ticker = _text(value.get("ticker"), 24)
    if market.market_code_for_symbol(symbol) == "US":
        try:
            ticker_symbol = market.normalize_symbol("us" + raw_ticker)
        except market.MarketDataError as exc:
            raise FinancialPreferenceError("股票代码与标识不匹配") from exc
        if ticker_symbol != symbol:
            raise FinancialPreferenceError("股票代码与标识不匹配")
    elif raw_ticker != ticker:
        raise FinancialPreferenceError("股票代码与标识不匹配")
    return {"symbol": symbol, "ticker": ticker, "name": _text(value.get("name"), 60), "market": _text(value.get("market"), 30)}


def _number(value: Any, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 or value > maximum:
        raise FinancialPreferenceError("持仓数量与成本必须为有效正数")
    return float(value)


def _rows(value: Any, limit: int, transform, key: str) -> list[dict]:
    if not isinstance(value, list) or len(value) > limit:
        raise FinancialPreferenceError(f"设置条目最多 {limit} 条")
    result = [transform(row) for row in value]
    if len({row[key] for row in result}) != len(result):
        raise FinancialPreferenceError("设置条目标识不能重复")
    return result


def _watch(row: Any) -> dict:
    stock = _stock(row)
    return {**stock, "tags": _tags(row.get("tags", [])), "note": _text(row.get("note", ""), 500, empty=True)}


def _profile(row: Any) -> dict:
    if not isinstance(row, dict) or row.get("scope") not in {"financial", "events", "risk", "comprehensive"} or row.get("depth") not in {"brief", "basic", "standard", "detailed", "exhaustive"}:
        raise FinancialPreferenceError("研究档案的范围或深度无效")
    return {"id": _identifier(row.get("id")), "name": _text(row.get("name"), 60), "scope": row["scope"], "depth": row["depth"], "period": _text(row.get("period", ""), 100, empty=True), "instructions": _text(row.get("instructions", ""), 1000, empty=True), "isDefault": row.get("isDefault") is True}


def _position(row: Any) -> dict:
    if not isinstance(row, dict):
        raise FinancialPreferenceError("持仓设置无效")
    stock = _stock(row.get("stock"))
    expected = "HKD" if stock["symbol"].startswith("hk") else "USD" if stock["symbol"].startswith("us") else "CNY"
    if row.get("currency", expected) != expected:
        raise FinancialPreferenceError("持仓币种与市场不匹配")
    return {"id": _identifier(row.get("id")), "stock": stock, "quantity": _number(row.get("quantity"), 1e12), "costPrice": _number(row.get("costPrice"), 1e8), "currency": expected, "note": _text(row.get("note", ""), 500, empty=True)}


def _case(row: Any) -> dict:
    if not isinstance(row, dict):
        raise FinancialPreferenceError("复盘书签无效")
    return {"id": _identifier(row.get("id")), "sessionId": _identifier(row.get("sessionId")), "turnId": _identifier(row.get("turnId")), "title": _text(row.get("title"), 120), "tags": _tags(row.get("tags", [])), "note": _text(row.get("note", ""), 500, empty=True)}


def _section(key: str, value: Any) -> Any:
    if key == "selectedStock":
        return None if value is None else _stock(value)
    limits = {"watchlist": (50, _watch, "symbol"), "profiles": (20, _profile, "id"), "manualPositions": (50, _position, "id"), "reviewCases": (100, _case, "id")}
    limit, transform, identity = limits[key]
    result = _rows(value, limit, transform, identity)
    if key == "profiles" and sum(row["isDefault"] for row in result) > 1:
        raise FinancialPreferenceError("只能设置一个默认研究档案")
    return result


def _path(agent_id: str) -> Path:
    try:
        return runs._run_root(agent_id).parent / "financial-workspace.json"
    except (ValueError, OSError, RuntimeError) as exc:
        raise FinancialPreferenceError("金融助手私有设置目录不可用", 409) from exc


def _empty(agent_id: str) -> dict:
    return {"schemaVersion": 1, "agentId": agent_id, "revision": 0, "updatedAt": "", "selectedStock": None, "watchlist": [], "profiles": [], "manualPositions": [], "reviewCases": []}


def _load(path: Path, agent_id: str) -> dict:
    if not path.exists():
        return _empty(agent_id)
    try:
        if path.stat().st_size > 250_000:
            raise ValueError("oversize")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or type(raw.get("schemaVersion")) is not int
            or raw["schemaVersion"] != 1
            or raw.get("agentId") != agent_id
            or type(raw.get("revision")) is not int
            or raw["revision"] < 0
            or set(raw) - _PERSISTED_FIELDS
        ):
            raise ValueError("identity")
        return {**_empty(agent_id), "revision": raw["revision"], "updatedAt": _text(raw.get("updatedAt", ""), 80, empty=True), **{key: _section(key, raw.get(key, None if key == "selectedStock" else [])) for key in _SECTIONS}}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise FinancialPreferenceError("设置文件无法安全读取，未覆盖现有数据", 409) from exc


def get_workspace(agent_id: str) -> dict:
    _agent(agent_id)
    return _load(_path(agent_id), agent_id)


def update_workspace(agent_id: str, expected_revision: int, patch: dict) -> dict:
    _agent(agent_id)
    if type(expected_revision) is not int or expected_revision < 0 or not isinstance(patch, dict) or not patch or set(patch) - _SECTIONS:
        raise FinancialPreferenceError("设置更新无效")
    sections = {key: _section(key, value) for key, value in patch.items()}
    path = _path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, cross_process_file_lock(path, lock_path=path.with_name(path.name + ".transaction.lock"), timeout=10):
        state = _load(path, agent_id)
        if state["revision"] != expected_revision:
            raise FinancialPreferenceError("设置已在其他页面更新，请刷新后重试", 409)
        # Validate new native identities only; stale bookmarks remain removable.
        if "reviewCases" in sections:
            from core.web.services import financial_report_service as reports

            existing = {(row["sessionId"], row["turnId"]) for row in state["reviewCases"]}
            for item in sections["reviewCases"]:
                if (item["sessionId"], item["turnId"]) in existing:
                    continue
                try:
                    reports._completed_report(agent_id, item["sessionId"], item["turnId"])
                except reports.FinancialReportExportError as exc:
                    raise FinancialPreferenceError("复盘书签必须来自此助手的已完成研究", 409) from exc
        state.update(sections)
        state.update(revision=state["revision"] + 1, updatedAt=datetime.now(timezone.utc).isoformat())
        atomic_write_json(path, state, ensure_ascii=False, indent=2, strict_replace=True)
        return state
