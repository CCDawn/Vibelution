from __future__ import annotations

import pytest

from core.web.services import runtime_scene_service


@pytest.mark.parametrize(
    ("lifecycle", "level", "reconciliation_closed", "expected"),
    [
        (False, "info", False, False),
        (True, "info", False, True),
        (False, "info", True, True),
        (False, "warning", False, True),
        (False, "error", False, True),
        (False, "critical", False, True),
        (False, "fatal", False, True),
    ],
)
def test_runtime_scene_event_projection_refresh_policy(
    lifecycle: bool,
    level: str,
    reconciliation_closed: bool,
    expected: bool,
) -> None:
    assert (
        runtime_scene_service._runtime_scene_event_requires_full_projection_refresh(
            lifecycle=lifecycle,
            level=level,
            reconciliation_closed=reconciliation_closed,
        )
        is expected
    )
