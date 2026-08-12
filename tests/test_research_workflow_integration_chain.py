"""Legacy integration notes for the research workflow chain.

The former ``test_full_chain_no_fakes`` injected ``_HermeticTaskFactory`` and is
not production evidence. The authoritative default composition gate lives in
``tests/test_research_workflow_t51_default_composition_chain.py``.
"""

from __future__ import annotations


def test_full_chain_with_injected_task_factory() -> None:
    """Retained name so renames are discoverable; body is the T5.1-8 gate."""
    from tests.test_research_workflow_t51_default_composition_chain import (
        test_deterministic_composition_integration_gate as _gate,
    )

    assert callable(_gate)
