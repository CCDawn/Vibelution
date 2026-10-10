"""Deterministic A-share walk-forward plan validation and fold construction."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from core.web.services.financial_backtest.data import BacktestInputError

_CANDIDATE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")
_ALLOWED_FIELDS = frozenset(
    {"trainSessions", "testSessions", "stepSessions", "candidates", "maxTokens"}
)


def normalize_walk_forward_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the bounded, user-visible A-share workflow request."""
    if not isinstance(payload, Mapping):
        raise BacktestInputError("滚动验证请求必须是对象")
    unknown = set(payload) - _ALLOWED_FIELDS
    if unknown:
        raise BacktestInputError("滚动验证请求包含不支持的字段")

    train_sessions = _integer(payload.get("trainSessions", 126), "trainSessions", 2, 2500)
    test_sessions = _integer(payload.get("testSessions", 63), "testSessions", 2, 1250)
    step_sessions = _integer(payload.get("stepSessions", 63), "stepSessions", 2, 1250)
    if step_sessions < test_sessions:
        raise BacktestInputError("stepSessions不能小于testSessions，滚动测试窗口不能重叠")
    max_tokens = _integer(payload.get("maxTokens", 2_000_000), "maxTokens", 512, 2_000_000)

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes)):
        raise BacktestInputError("candidates必须是候选策略列表")
    if not 2 <= len(raw_candidates) <= 4:
        raise BacktestInputError("候选策略数量必须为2到4个")
    candidates: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    position_pcts: set[int] = set()
    for item in raw_candidates:
        if not isinstance(item, Mapping) or set(item) != {"candidateId", "maxPositionPct"}:
            raise BacktestInputError("每个候选策略只能包含candidateId和maxPositionPct")
        candidate_id = item.get("candidateId")
        position_pct = item.get("maxPositionPct")
        if not isinstance(candidate_id, str) or not _CANDIDATE_ID.fullmatch(candidate_id):
            raise BacktestInputError("candidateId只能包含字母、数字、下划线或连字符，长度1到40")
        if candidate_id in candidate_ids:
            raise BacktestInputError("candidateId不能重复")
        if isinstance(position_pct, bool) or not isinstance(position_pct, int):
            raise BacktestInputError("maxPositionPct必须是整数")
        if not 0 <= position_pct <= 100:
            raise BacktestInputError("maxPositionPct必须是0到100之间的整数")
        if position_pct in position_pcts:
            raise BacktestInputError("候选策略的maxPositionPct不能重复")
        candidate_ids.add(candidate_id)
        position_pcts.add(position_pct)
        candidates.append({"candidateId": candidate_id, "maxPositionPct": position_pct})

    candidates.sort(key=lambda row: row["candidateId"])
    return {
        "trainSessions": train_sessions,
        "testSessions": test_sessions,
        "stepSessions": step_sessions,
        "maxTokens": max_tokens,
        "candidates": candidates,
    }


def build_folds(
    session_dates: Sequence[str], request: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    """Build fixed-length rolling train/test folds and report the dropped tail.

    Training windows roll forward by ``stepSessions`` and remain fixed length.
    Test windows are complete, ordered, and non-overlapping. When the step is
    larger than the test window, intervening sessions are not scored as test
    data. An incomplete trailing window is omitted and its size is returned.
    """
    dates = tuple(str(value) for value in session_dates)
    if not dates:
        raise BacktestInputError("冻结A股快照没有交易日")
    try:
        parsed = tuple(date.fromisoformat(value) for value in dates)
    except ValueError as exc:
        raise BacktestInputError("冻结A股快照包含无效交易日") from exc
    if any(day.isoformat() != value for day, value in zip(parsed, dates, strict=True)):
        raise BacktestInputError("冻结A股快照交易日格式无效")
    if tuple(sorted(set(dates))) != dates:
        raise BacktestInputError("冻结A股快照交易日重复或乱序")

    train_sessions = int(request["trainSessions"])
    test_sessions = int(request["testSessions"])
    step_sessions = int(request["stepSessions"])
    folds: list[dict[str, Any]] = []
    offset = 0
    while offset + train_sessions + test_sessions <= len(dates):
        train_start_index = offset
        train_end_index = offset + train_sessions - 1
        test_start_index = train_end_index + 1
        test_end_index = test_start_index + test_sessions - 1
        folds.append(
            {
                "foldId": f"fold-{len(folds) + 1:03d}",
                "trainStart": dates[train_start_index],
                "trainEnd": dates[train_end_index],
                "testStart": dates[test_start_index],
                "testEnd": dates[test_end_index],
                "trainStartIndex": train_start_index,
                "trainEndIndex": train_end_index,
                "testStartIndex": test_start_index,
                "testEndIndex": test_end_index,
            }
        )
        offset += step_sessions

    if not folds:
        raise BacktestInputError("冻结行情不足一个完整的训练加测试窗口")
    dropped = len(dates) - int(folds[-1]["testEndIndex"]) - 1
    return folds, dropped


def select_candidate(
    candidates: Sequence[Mapping[str, Any]],
    train_metrics: Mapping[str, Mapping[str, Any]],
) -> str:
    """Choose only from training excess return; candidateId breaks exact ties."""
    scored: list[tuple[float, str]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidateId") or "")
        metrics = train_metrics.get(candidate_id)
        if not isinstance(metrics, Mapping):
            raise BacktestInputError("训练结果缺少候选策略评分")
        score = metrics.get("excessReturnPct")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise BacktestInputError("训练结果缺少有效的超额收益")
        value = float(score)
        if value != value or value in (float("inf"), float("-inf")):
            raise BacktestInputError("训练结果超额收益不是有限数值")
        scored.append((value, candidate_id))
    if not scored:
        raise BacktestInputError("训练结果没有可选择的候选策略")
    # Sort in a fully specified order so behavior is stable across platforms.
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数")
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数") from exc
    if normalized != value or not minimum <= normalized <= maximum:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数")
    return normalized


__all__ = ["build_folds", "normalize_walk_forward_request", "select_candidate"]
