"""停止链路分段耗时视图的行为锁定。

阶段登记本来就在记「什么时候到了哪一步」。这里锁定的是复盘真正需要的
那一层：相邻阶段的耗时差，以及日志落到时机——登记一清，数据就没了。
"""

import logging

import pytest

from core.web.services.session import control


@pytest.fixture(autouse=True)
def _clean_stop_stages():
    """阶段登记是模块级状态：测试前后清空，防跨测试污染。"""
    with control._STOP_STAGE_LOCK:
        control._SESSION_STOP_STAGES.clear()
    yield
    with control._STOP_STAGE_LOCK:
        control._SESSION_STOP_STAGES.clear()


def _seed(session_id: str, turn_id: str, stages: list[tuple[str, str]]) -> None:
    with control._STOP_STAGE_LOCK:
        control._SESSION_STOP_STAGES[(session_id, turn_id)] = [
            {"stage": stage, "at": at} for stage, at in stages
        ]


def test_returns_empty_when_no_stage_was_recorded():
    assert control.build_session_stop_breakdown("session-none", "turn-none") == {}


def test_measures_each_hop_between_recorded_stages():
    _seed(
        "session-a",
        "turn-a",
        [
            ("requested", "2026-11-12T05:00:00.000000+00:00"),
            ("provider_aborted", "2026-11-12T05:00:00.450000+00:00"),
            ("tools_cancelled", "2026-11-12T05:00:02.450000+00:00"),
        ],
    )

    breakdown = control.build_session_stop_breakdown("session-a", "turn-a")

    assert breakdown["stageCount"] == 3
    assert breakdown["totalMs"] == 2450
    assert breakdown["segments"] == [
        {"from": "requested", "to": "provider_aborted", "ms": 450},
        {"from": "provider_aborted", "to": "tools_cancelled", "ms": 2000},
    ]
    assert [stage["stage"] for stage in breakdown["stages"]] == [
        "requested",
        "provider_aborted",
        "tools_cancelled",
    ]


def test_keeps_extra_stage_fields_next_to_the_stage_name():
    with control._STOP_STAGE_LOCK:
        control._SESSION_STOP_STAGES[("session-b", "turn-b")] = [
            {"stage": "requested", "at": "2026-11-12T05:00:00.000000+00:00"},
            {
                "stage": "tools_cancelled",
                "at": "2026-11-12T05:00:01.000000+00:00",
                "outcome": "quiescent",
            },
        ]

    breakdown = control.build_session_stop_breakdown("session-b", "turn-b")

    assert breakdown["stages"][1]["outcome"] == "quiescent"
    assert breakdown["stages"][1]["stage"] == "tools_cancelled"


def test_skips_entries_without_a_parsable_timestamp():
    _seed(
        "session-c",
        "turn-c",
        [
            ("requested", "2026-11-12T05:00:00.000000+00:00"),
            ("provider_aborted", ""),
            ("tools_cancelled", "2026-11-12T05:00:03.000000+00:00"),
        ],
    )

    breakdown = control.build_session_stop_breakdown("session-c", "turn-c")

    assert breakdown["stageCount"] == 2
    assert breakdown["segments"] == [
        {"from": "requested", "to": "tools_cancelled", "ms": 3000},
    ]


def test_logs_one_line_before_the_stages_are_cleared(caplog):
    _seed(
        "session-d",
        "turn-d",
        [
            ("requested", "2026-11-12T05:00:00.000000+00:00"),
            ("snapshot_persisted", "2026-11-12T05:00:00.120000+00:00"),
        ],
    )

    with caplog.at_level(logging.INFO, logger=control.__name__):
        control.log_session_stop_breakdown("session-d", "turn-d")
        control._clear_session_stop_stages("session-d", "turn-d")

    messages = [record.getMessage() for record in caplog.records]
    assert any("session_stop_breakdown" in message for message in messages)
    assert control.build_session_stop_breakdown("session-d", "turn-d") == {}


def test_logging_without_stages_is_a_no_op(caplog):
    with caplog.at_level(logging.INFO, logger=control.__name__):
        control.log_session_stop_breakdown("session-empty", "turn-empty")

    assert not [record for record in caplog.records if "session_stop_breakdown" in record.getMessage()]
