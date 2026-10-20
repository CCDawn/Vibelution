from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

from tests.test_self_evolution_local_integration import harness, SHA
from tests.test_self_evolution_autonomous_loop_service import _build_service
from core.web.services.self_evolution_campaign_service import SelfEvolutionCampaignService
from core.web.services import self_evolution_local_integration as local


def test_real_workrun_and_authority_complete_two_independently_reviewed_rounds(harness, tmp_path, monkeypatch):
    """Compose the actual owners, retaining native Session evidence validation."""
    harness.now[0] = datetime.now(timezone.utc)
    adapter = harness.adapter
    child, calls = _build_service(tmp_path)
    child._store = harness.store
    original = child._hooks
    issued = []

    def authorize(context):
        issued.append(context["runId"])
        return adapter.authorize(context)

    def plan(context):
        value = original.plan(context)
        value["targetFiles"] = ["src/example.py"]
        return value

    def evolve(context):
        value = original.evolve(context)
        value["baseCommit"] = "b" * 40
        value["changedFiles"] = [{"path": "src/example.py", "changeType": "modified"}]
        return value

    def review(context):
        run_id = context["runId"]
        harness.native.metadata["externalTaskId"] = run_id
        harness.native.events[0].correlation_id = f"{local.REVIEW_SOURCE}:{run_id}:{SHA}"
        return adapter.review(context)

    def integrate(context):
        with adapter.guard(context):
            value = original.integrate(context)
            value["commitSha"] = context["candidate"]["headCommit"]
            return value

    child._hooks = replace(original, plan=plan, evolve=evolve, authorize=adapter.authorize,
                           review=review, check_authorization=adapter.check, integrate=integrate)
    campaign = SelfEvolutionCampaignService(store=harness.store, child=child, authorize=authorize,
                                           now=lambda: harness.now[0])
    queued = campaign.queue({"goal": "bounded improvement", "rounds": 2,
                             "idempotencyKey": "real-owner-integration",
                             "localIntegration": harness.snapshot["request"]["localIntegration"]})
    # Background rounds cannot inherit the HTTP principal. Delegation must work
    # from the durable root grant alone.
    monkeypatch.setattr(local, "current_server_operator", lambda: None)
    result = campaign.run(queued["runId"])
    assert result["status"] == "completed", [
        child.get_campaign(ref["runId"], source=ref["source"]).get("error") for ref in result["rounds"]
    ]
    assert len(issued) == 1
    assert len(harness.native.submitted) == 2
    assert [name for name, _ in calls].count("integrate") == 2
    for ref in result["rounds"]:
        snapshot = child.get_campaign(ref["runId"], source=ref["source"])
        grant = snapshot["localIntegrationAuthorization"]
        assert snapshot["_campaignExecutionSettled"] is True
        assert grant["expiresAt"] == queued["deadline"]
        assert grant["allowedFiles"] == queued["request"]["localIntegration"]["allowedFiles"]
        assert ref["commitSha"] == SHA
