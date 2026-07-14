from core.chat.chat_task_types import trim_lines
from core.web.services.session_service import _trim_tool_detail_text


def test_trim_lines_keeps_only_first_nonempty_lines() -> None:
    assert trim_lines("  first  \n\n second \n third ", max_lines=2) == "first\nsecond"


def test_trim_lines_preserves_short_single_line() -> None:
    assert trim_lines("  already compact  ", max_lines=4) == "already compact"


def test_trim_tool_detail_text_bounds_lines_before_cleaning() -> None:
    assert _trim_tool_detail_text(" first  \nsecond   \nthird", max_lines=2) == "first\nsecond"


def test_trim_tool_detail_text_truncates_single_line() -> None:
    assert _trim_tool_detail_text("abcdefgh", max_chars=5) == "abcd…"
