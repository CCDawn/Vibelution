from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain_store as store,
)


def test_chain_facade_reexports_store() -> None:
    assert chain._records is store._records
    assert chain._append_jsonl is store._append_jsonl
    assert chain.HypothesisFirstChainError is store.HypothesisFirstChainError
    assert chain.hypothesis_first_scope_lock is store.hypothesis_first_scope_lock


def test_command_and_meeting_owners_stay_on_chain() -> None:
    assert chain.execute_v2_command.__module__.endswith("hypothesis_first_chain")
    assert chain.open_review_meeting_for_selection.__module__.endswith(
        "hypothesis_first_chain"
    )
    assert chain.open_candidate_generation_meeting.__module__.endswith(
        "hypothesis_first_chain"
    )
    assert chain.chain_state.__module__.endswith("hypothesis_first_chain")
