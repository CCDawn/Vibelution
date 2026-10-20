"""Bounded budget and stock-fee checks, never a verdict on advice quality."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from core.chat.turn_journal import EVENT_USER_MESSAGE

_MONEY = r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>万|千)?\s*(?:元|块)(?!美元)"
_BUDGET_PATTERNS = [
    re.compile(r"(?:投资预算|总预算|预算|本金)\s*(?:为|是|约|大约|大概|有|改为|调整为|[:：=])*\s*" + _MONEY),
    re.compile(_MONEY + r"\s*(?:的)?\s*(?:投资预算|总预算|预算|本金)"),
    re.compile(r"(?:我(?:现在|目前)?有|以)\s*(?:约|大约)?\s*" + _MONEY + r"\s*(?:的)?\s*(?:闲置资金|闲钱|起步)"),
]
_NON_ASSERTION = re.compile(r"假设|假如|如果|例如|比如|上一轮|之前|原来|错误|写错|误写|作废|不是|不等于|不代表|若")
_CONDITIONAL = re.compile(r"假设|假如|如果|例如|比如|若")


def _assertions(text: str):
    # Quotes, fenced examples and conditional/correction sentences are not facts.
    text = re.sub(r"```[^\n]*\n.*?(?:```|\Z)", "", text[:50_000], flags=re.S)
    text = re.sub(r"(?m)^\s*>[^\n]*", "", text)
    text = re.sub(r"[“\"][^”\"\n]*[”\"]", "", text)
    for sentence in re.split(r"[。！？\n;；]", text):
        conditional = False
        for clause in re.split(r"，|(?<!\d),(?!\d)", sentence):
            conditional |= bool(_CONDITIONAL.search(clause))
            if conditional or _NON_ASSERTION.search(clause):
                continue
            yield clause


def _amounts(text: str) -> set[Decimal]:
    found = set()
    for clause in _assertions(text):
        for pattern in _BUDGET_PATTERNS:
            for match in pattern.finditer(clause):
                try:
                    amount = Decimal(match["amount"].replace(",", ""))
                    amount *= {None: 1, "千": 1000, "万": 10_000}[match["unit"]]
                    if 0 < amount <= 100_000_000:
                        found.add(amount)
                except InvalidOperation:
                    continue
    return found


def _stock_fee_issues(answer: str) -> list[str]:
    from core.web.services.financial_backtest.fees import stamp_duty_rate

    today = datetime.now(timezone(timedelta(hours=8))).date()
    expected = stamp_duty_rate(today.isoformat(), "sell")
    number = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+(?:点[零〇一二三四五六七八九]+)?)"
    expression = re.compile(
        r"印花税(?:率)?(?:[约为是按收取均:：\s]|成交(?:额|金额)的)*"
        r"(\d+(?:\.\d+)?\s*[%‰]|[万千百]分之" + number + r")(?![\d.零〇一二两三四五六七八九十百千万点])"
    )
    for clause in _assertions(answer):
        # Only self-contained stock sell assertions: a comma must not lose a
        # preceding ETF/foreign-market/historical scope and turn it into A shares.
        if not re.search(r"(?:股票|A\s*股).*卖出", clause, re.I):
            continue
        if re.search(r"ETF|基金|港股|美股|香港|美国|境外|海外|历史|回测", clause, re.I):
            continue
        if any(int(year) != today.year for year in re.findall(r"(20\d{2})年", clause)):
            continue
        for match in expression.finditer(clause):
            value = match[1].replace(" ", "")
            try:
                if "分之" in value:
                    unit, number = value.split("分之")
                    rate = _fee_number(number) / {"万": 10000, "千": 1000, "百": 100}[unit]
                else:
                    rate = Decimal(value[:-1]) / (100 if value[-1] == "%" else 1000)
                if rate != expected:
                    return [f"股票卖出印花税 {value} 与共享费用模型的 {expected * 100:g}% 不一致，请重新核对；实际费用以适用规则和券商为准。"]
            except InvalidOperation:
                continue
    return []


def _fee_number(value: str) -> Decimal:
    if value[0].isdigit():
        return Decimal(value)
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    integer, _, fraction = value.partition("点")
    total = section = number = 0
    for char in integer:
        if char in digits:
            number = number * 10 + digits[char]
        elif char == "万":
            total += (section + number) * 10000
            section = number = 0
        else:
            section += (number or 1) * {"十": 10, "百": 100, "千": 1000}[char]
            number = 0
    decimal = "".join(str(digits[char]) for char in fraction)
    return Decimal(str(total + section + number) + ("." + decimal if decimal else ""))


def _user_budget(events: list, turn_id: str) -> tuple[Decimal | None, bool, bool]:
    from core.web.services.financial_report_service import _initial_user_request

    # Native branch order is authoritative; never inspect later Turns or model/tool text.
    turns = {}
    reached_target = False
    for event in events:
        if reached_target and event.turn_id != turn_id:
            break
        reached_target |= event.turn_id == turn_id
        if event.event_type == EVENT_USER_MESSAGE:
            turns.setdefault(event.turn_id, []).append(event)
    for request_turn, requests in reversed(list(turns.items())[-20:]):
        values = _amounts(_initial_user_request(requests))
        if values:
            return (next(iter(values)), False, request_turn == turn_id) if len(values) == 1 else (None, True, request_turn == turn_id)
    return None, False, False


def assess_budget(answer: str, events: list, turn_id: str, profile: dict | None, proposal: dict | None) -> dict:
    budget, ambiguous, current_request = _user_budget(events, turn_id)
    source = "conversation" if budget is not None else "unknown"
    issues = []
    if not current_request and profile and profile.get("budgetCny") is not None:
        budget = Decimal(str(profile["budgetCny"]))
        source = "saved_profile"
        ambiguous = False
    if ambiguous:
        issues.append("用户条件中出现多个预算，尚不能唯一确认，请先澄清后重新分析。")
    if budget is not None:
        stated = _amounts(answer)
        conflicting = sorted(value for value in stated if value != budget)
        if conflicting:
            amounts = "、".join(f"{value:g}" for value in conflicting[:5])
            issues.append(f"回答中的预算 {amounts} 元与核对依据 {budget:g} 元不一致，请重新分析。")
        if proposal and proposal["kind"] == "profile":
            proposed = proposal["profile"].get("budgetCny")
            if proposed is not None and Decimal(str(proposed)) != budget:
                issues.append("投资配置提案的预算与用户条件不一致，暂不能确认保存。")
    terms = proposal["profile"] if proposal and proposal["kind"] == "profile" else profile
    if terms and terms.get("market") == "CN":
        issues.extend(_stock_fee_issues(answer))
    return {"budgetCny": float(budget) if budget is not None else None, "budgetSource": source, "issues": issues}
