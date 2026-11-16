"""Dead log/network config fields must announce their retirement.

The audit found these fields were reachable from the config panel but had no
runtime reader. Retiring them in place keeps old config.toml files valid while
making the real owner explicit, so nobody tunes a switch that does nothing.
"""

from __future__ import annotations

import pytest

from config.models import LogConfig, NetworkConfig


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (LogConfig, "date_format"),
        (LogConfig, "backup_count"),
        (LogConfig, "detailed_traceback"),
        (NetworkConfig, "retry_delay"),
    ],
)
def test_dead_field_is_marked_retired(model, field):
    description = model.model_fields[field].description or ""
    assert "已退役" in description
    assert "不参与运行时决策" in description


def test_descriptions_name_the_real_owner():
    owners = {
        (LogConfig, "backup_count"): "log_rotation",
        (LogConfig, "date_format"): "日志记录器",
    }
    for (model, field), needle in owners.items():
        description = model.model_fields[field].description or ""
        assert needle in description


def test_defaults_stay_for_config_compatibility():
    config = LogConfig()
    assert config.backup_count == 5
    assert config.date_format == "%Y-%m-%d %H:%M:%S"
    assert NetworkConfig().retry_delay == 1.0
