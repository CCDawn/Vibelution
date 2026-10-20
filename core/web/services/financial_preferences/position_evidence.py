"""Exclude explicitly labelled acceptance/simulation samples from actual assets."""

import re

_REFERENCE = re.compile(
    r"(?:^|[\s:：【\[(])(?:(?:仅供|仅用于|仅作|用于|这是|历史)\s*)?(?:\d{8})?(?:功能)?(?:验收|测试|模拟盘|模拟|示例|fixture|paper[ -]?trade)"
    r"(?=$|[\s\d:：\]】/-]|持仓|数据|记录|交易|用途|用)", re.I,
)


def is_reference_position(row: dict) -> bool:
    note = str(row.get("note") or "")
    return bool(_REFERENCE.search(note))


def actual_positions(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not is_reference_position(row)]
