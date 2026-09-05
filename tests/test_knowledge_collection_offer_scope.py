from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_offers.knowledge_collection import (
    build_knowledge_collection_offers,
)
from tests._support.workflow_ledger_helpers import build_run_record


def test_knowledge_button_carries_the_runs_question_scope() -> None:
    run = build_run_record()
    offer = next(
        item for item in build_knowledge_collection_offers(run=run)
        if item.command is WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION
    )
    assert offer.available
    assert offer.payload == {"questionId": run.question_id}
    assert offer.expected_run_version == run.run_version
