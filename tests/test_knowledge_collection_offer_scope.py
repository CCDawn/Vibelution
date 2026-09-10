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


def test_unavailable_ensure_offer_serializes_reason_into_the_snapshot() -> None:
    """快照投影必须带出 reasonCode/blockerIds（前端理由渲染的依据）。

    死 turn 死局（2026-09-10 run-f9bf7be5985e）里 ensure offer 被标
    knowledge_collection_in_flight 不可用；快照序列化走 CommandOffer.to_dict，
    reasonCode/blockerIds 缺一都会让前端 commandOfferUnavailableReason 无从
    渲染。这里锁定不可用 offer 的序列化契约。
    """

    class _Invocation:
        invocation_id = "kinv-live"
        status = "running"

    run = build_run_record()
    offers = build_knowledge_collection_offers(
        run=run, invocations=[_Invocation()],
    )
    serialized = {
        item["command"]: item
        for item in (offer.to_dict() for offer in offers)
    }
    ensure = serialized["ensure_knowledge_collection"]
    assert ensure["available"] is False
    assert ensure["reasonCode"] == "knowledge_collection_in_flight"
    assert ensure["blockerIds"] == ["knowledge_collection_in_flight"]
    assert ensure["payload"]["invocationId"] == "kinv-live"
