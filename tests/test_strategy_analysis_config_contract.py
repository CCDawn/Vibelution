"""strategy.* and analysis.* are retired as whole groups.

Nothing in core/, tools/ or agent.py reads cfg.strategy / cfg.analysis:
the fields only ever surfaced on the config panel. Instead of inventing
consumers, both groups are marked retired while staying loadable so old
config.toml files keep parsing.
"""

from __future__ import annotations

from config.models import AnalysisConfig, StrategyConfig

STRATEGY_FIELDS = (
    "data_dir",
    "exploration_rate",
    "learning_enabled",
    "learning_data_path",
)
ANALYSIS_FIELDS = (
    "data_dir",
    "feedback_dir",
    "knowledge_graph_path",
    "pattern_library_path",
)


def test_strategy_fields_are_marked_retired():
    for name in STRATEGY_FIELDS:
        description = StrategyConfig.model_fields[name].description or ""
        assert "已退役" in description, name


def test_analysis_fields_are_marked_retired():
    for name in ANALYSIS_FIELDS:
        description = AnalysisConfig.model_fields[name].description or ""
        assert "已退役" in description, name


def test_group_docstrings_explain_the_retirement():
    assert "已退役整组" in (StrategyConfig.__doc__ or "")
    assert "已退役整组" in (AnalysisConfig.__doc__ or "")
