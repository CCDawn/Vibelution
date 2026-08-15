from pathlib import Path

from core.orchestration.turn_outcome import TurnOutcomeController
from core.orchestration.tool_lifecycle import ToolLifecycleBridge
from core.orchestration.turn_runner import run_agent_single_turn
from agent import SelfEvolvingAgent


def test_gate_2_4_does_not_create_internal_turn_pipeline():
    orchestration_root = Path(__file__).resolve().parents[1] / "core" / "orchestration"
    assert not (orchestration_root / "turn_pipeline.py").exists()
    assert hasattr(SelfEvolvingAgent, "_run_orchestrated_turn")
    assert callable(TurnOutcomeController.decide_llm_iteration)
    assert callable(TurnOutcomeController.finalize_round)
    assert callable(ToolLifecycleBridge.execute_tools)
    assert callable(run_agent_single_turn)
