from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain_auto_advance as auto_advance,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain_store as store,
)


def test_chain_facade_reexports_store() -> None:
    assert chain._records is store._records
    assert chain._append_jsonl is store._append_jsonl
    assert chain.HypothesisFirstChainError is store.HypothesisFirstChainError
    assert chain.hypothesis_first_scope_lock is store.hypothesis_first_scope_lock


def test_auto_advance_binds_to_chain_globals() -> None:
    assert chain.sweep_auto_advance_closure is auto_advance.sweep_auto_advance_closure
    assert chain.auto_adjudicate_exhausted_round is (
        auto_advance.auto_adjudicate_exhausted_round
    )
    assert chain.sweep_auto_advance_closure.__globals__ is chain.__dict__
    assert chain.sweep_auto_advance_closure.__module__.endswith(
        "hypothesis_first_chain_auto_advance"
    )
    assert chain._auto_start_created_formal_run.__globals__ is chain.__dict__


def test_command_and_meeting_owners_stay_on_chain() -> None:
    assert chain.execute_v2_command.__module__.endswith("hypothesis_first_chain")
    assert chain.open_review_meeting_for_selection.__module__.endswith(
        "hypothesis_first_chain"
    )
    assert chain.open_candidate_generation_meeting.__module__.endswith(
        "hypothesis_first_chain"
    )
    assert chain.chain_state.__module__.endswith("hypothesis_first_chain")
