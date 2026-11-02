"""Regression for real assistant replies that format exit codes as Markdown."""

import pytest

from scripts.acceptance_local_assistant_development import reports_exit_zero


@pytest.mark.parametrize("answer", [
    "退出码：`0`（Ran 3 tests OK）",
    "- **退出码**：**0**",
    "exitCode=0",
    "exitCode: `0`",
])
def test_exit_zero_accepts_plain_and_formatted_reports(answer):
    assert reports_exit_zero(answer)


@pytest.mark.parametrize("answer", [
    "退出码：1，预期 0",
    "exitCode=10",
    "exitCode=0.1",
    "exitCode=00",
    "exitCode=0x1",
    "退出码：-0",
    "Ran 3 tests OK",
])
def test_exit_zero_requires_an_explicit_exact_zero_report(answer):
    assert not reports_exit_zero(answer)
