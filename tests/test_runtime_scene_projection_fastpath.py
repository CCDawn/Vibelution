from __future__ import annotations

import pytest

from core.web.services import runtime_scene_service


@pytest.mark.parametrize(
    ("level", "reconciliation_closed", "expected"),
    [
        ("info", False, False),
        ("info", True, True),
        ("warning", False, True),
        ("error", False, True),
        ("critical", False, True),
        ("fatal", False, True),
    ],
)
def test_runtime_scene_event_projection_refresh_policy(
    level: str,
    reconciliation_closed: bool,
    expected: bool,
) -> None:
    assert (
        runtime_scene_service._runtime_scene_event_requires_full_projection_refresh(
            level=level,
            reconciliation_closed=reconciliation_closed,
        )
        is expected
    )
