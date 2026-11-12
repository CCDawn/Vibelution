"""agent.auto_restart_threshold is retired, not wiring debt.

The field is described as an error-count trigger, but no error-count
restart path exists: restarts come from tools/rebirth_tools.py (agent
request) and the Launcher control plane only. Wiring the field would mean
inventing a new restart mechanism, so the contract is an explicit
retirement marker in both the model and the config panel.
"""

from __future__ import annotations

import pathlib

from config.models import AgentConfig


def test_field_description_says_retired():
    description = AgentConfig.model_fields["auto_restart_threshold"].description or ""
    assert "已退役" in description


def test_config_panel_stops_promising_auto_restart():
    panel = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "config_panel.py"
    text = panel.read_text(encoding="utf-8")
    assert "已退役：本版不按错误次数自动重启。" in text
    assert "Retired: this version never restarts on an error-count threshold." in text
    assert "达到阈值后触发热重启。" not in text
    assert "Threshold that triggers hot restart." not in text
