"""Bounded checks of explicit budget statements, never a verdict on advice quality."""

from __future__ import annotations

import re
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


def _amounts(text: str) -> set[Decimal]:
    # Quotes, fenced examples and conditional/correction sentences are not facts.
    text = re.sub(r"```[^\n]*\n.*?(?:```|\Z)", "", text[:50_000], flags=re.S)
    text = re.sub(r"(?m)^\s*>[^\n]*", "", text)
    text = re.sub(r"[“\"][^”\"\n]*[”\"]", "", text)
    found = set()
    for sentence in re.split(r"[。！？\n;；]", text):
        conditional = False
        for clause in re.split(r"，|(?<!\d),(?!\d)", sentence):
            conditional |= bool(_CONDITIONAL.search(clause))
            if conditional or _NON_ASSERTION.search(clause):
                continue
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
    return {"budgetCny": float(budget) if budget is not None else None, "budgetSource": source, "issues": issues}
