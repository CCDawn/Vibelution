"""Dispatch immutable research kinds without changing legacy announcement hashes."""
from collections.abc import Mapping
from typing import Any

from .data import BacktestInputError

RESEARCH_MODES = ("announcements", "financial_reports")


def research_kind(snapshot: Mapping[str, Any]) -> str:
    if not isinstance(snapshot, Mapping):
        raise BacktestInputError("历史研究快照必须是对象")
    kind = snapshot.get("researchKind", "announcements")
    if kind not in RESEARCH_MODES:
        raise BacktestInputError("历史研究快照类型无效")
    return kind


def _adapter(kind: str):
    if kind == "announcements":
        from . import research_snapshot
        return research_snapshot
    if kind == "financial_reports":
        from . import frozen_financial_reports
        return frozen_financial_reports
    raise BacktestInputError("历史研究输入类型无效")


def freeze_research_snapshot(mode: str, symbols, decision_dates):
    adapter = _adapter(mode)
    freeze = adapter.freeze_announcement_research_snapshot if mode == "announcements" else adapter.freeze_financial_report_snapshot
    return freeze(symbols, decision_dates)


def validate_research_snapshot(payload, *, expected_hash=None, symbols=None, decision_dates=None, expected_kind=None):
    kind = research_kind(payload)
    if expected_kind is not None and kind != expected_kind:
        raise BacktestInputError("冻结研究快照与请求类型不匹配")
    return _adapter(kind).validate_research_snapshot(payload, expected_hash=expected_hash, symbols=symbols, decision_dates=decision_dates)


def research_coverage_summary(snapshot):
    return _adapter(research_kind(snapshot)).research_coverage_summary(snapshot)


def decision_research_material(snapshot, *, symbols, decision_date):
    return _adapter(research_kind(snapshot)).decision_research_material(snapshot, symbols=symbols, decision_date=decision_date)
