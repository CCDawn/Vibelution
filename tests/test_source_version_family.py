from __future__ import annotations

from core.web.services.team_workflow.source_collection_common import (
    project_source_version_families,
    source_version_family_identity,
)
from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
    team_workflow_orchestration_service,
)
from tests._support.team_workflow.helpers import (
    _use_fake_local_research_config,
    _use_tmp_project_root,
)


def _source_candidate(candidate_id: str, doi: str, *, updated_at: str) -> dict[str, object]:
    return {
        "candidateId": candidate_id,
        "candidateType": "source_manifest",
        "title": f"Source {candidate_id}",
        "updatedAt": updated_at,
        "metadata": {
            "doi": doi,
            "sourceIdentityKey": f"doi:{doi}",
        },
    }


def test_research_square_versions_share_one_family_without_losing_record_identity() -> None:
    v1 = source_version_family_identity("doi:10.21203/rs.3.rs-10024823/v1")
    v2 = source_version_family_identity("https://doi.org/10.21203/rs.3.rs-10024823/v2")

    assert v1 == {
        "familyKey": "doi:10.21203/rs.3.rs-10024823",
        "version": 1,
        "versionLabel": "v1",
        "sourceKind": "research_square_preprint",
        "evidencePolicy": "hypothesis_generation_only",
    }
    assert v2 == {
        **v1,
        "version": 2,
        "versionLabel": "v2",
    }


def test_non_versioned_or_unrelated_doi_is_not_rewritten_as_a_version_family() -> None:
    assert source_version_family_identity("10.1016/j.brainresbull.2003.09.004") is None
    assert source_version_family_identity("10.9999/example/v2") is None
    assert source_version_family_identity("https://example.test/paper/v2") is None


def test_projection_keeps_all_records_but_counts_latest_version_once() -> None:
    candidates = [
        _source_candidate(
            "candidate-v1",
            "10.21203/rs.3.rs-10024823/v1",
            updated_at="2026-06-16T00:00:00Z",
        ),
        _source_candidate(
            "candidate-v2",
            "10.21203/rs.3.rs-10024823/v2",
            updated_at="2026-07-15T00:00:00Z",
        ),
        _source_candidate(
            "candidate-journal",
            "10.1016/j.brainresbull.2003.09.004",
            updated_at="2026-07-15T00:00:00Z",
        ),
    ]

    projected, summary = project_source_version_families(candidates)
    by_id = {item["candidateId"]: item for item in projected}

    assert [item["candidateId"] for item in projected] == [
        "candidate-v1",
        "candidate-v2",
        "candidate-journal",
    ]
    assert summary == {
        "sourceRecordCount": 3,
        "independentSourceCount": 2,
        "versionFamilyCount": 1,
        "supersededRecordCount": 1,
    }
    assert by_id["candidate-v1"]["sourceVersionFamily"] == {
        "familyKey": "doi:10.21203/rs.3.rs-10024823",
        "version": 1,
        "versionLabel": "v1",
        "state": "superseded",
        "familySize": 2,
        "currentCandidateId": "candidate-v2",
        "currentVersionLabel": "v2",
        "countsAsIndependentSource": False,
        "sourceKind": "research_square_preprint",
        "evidencePolicy": "hypothesis_generation_only",
    }
    assert by_id["candidate-v2"]["sourceVersionFamily"] == {
        **by_id["candidate-v1"]["sourceVersionFamily"],
        "version": 2,
        "versionLabel": "v2",
        "state": "current",
        "countsAsIndependentSource": True,
    }
    assert "sourceVersionFamily" not in by_id["candidate-journal"]


def test_projection_uses_numeric_version_before_timestamps() -> None:
    candidates = [
        _source_candidate(
            "candidate-v2",
            "10.21203/rs.3.rs-42/v2",
            updated_at="2026-07-20T00:00:00Z",
        ),
        _source_candidate(
            "candidate-v10",
            "10.21203/rs.3.rs-42/v10",
            updated_at="2026-07-01T00:00:00Z",
        ),
    ]

    projected, _summary = project_source_version_families(candidates)
    by_id = {item["candidateId"]: item for item in projected}

    assert by_id["candidate-v10"]["sourceVersionFamily"]["state"] == "current"
    assert by_id["candidate-v2"]["sourceVersionFamily"]["state"] == "superseded"


def test_candidate_list_projects_family_without_rewriting_append_only_records(
    tmp_path,
    monkeypatch,
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Research team")
    registered = []
    for version in (1, 2):
        response = team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Research Square v{version}",
                "sourceUrl": f"https://doi.org/10.21203/rs.3.rs-10024823/v{version}",
                "sourceKind": "paper",
                "summary": "Versioned preprint.",
                "metadata": {"doi": f"10.21203/rs.3.rs-10024823/v{version}"},
                "createdByAgent": "source-extractor",
            },
        )
        registered.append(response["candidate"])

    listed = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"],
        candidate_type="source_manifest",
    )

    assert all("sourceVersionFamily" not in candidate for candidate in registered)
    assert listed["sourceFamilySummary"] == {
        "sourceRecordCount": 2,
        "independentSourceCount": 1,
        "versionFamilyCount": 1,
        "supersededRecordCount": 1,
    }
    assert [item["sourceVersionFamily"]["state"] for item in listed["candidates"]] == [
        "superseded",
        "current",
    ]


def test_candidate_list_keeps_superseded_state_after_quality_filter(
    tmp_path,
    monkeypatch,
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Research team")
    registered = []
    for version in (1, 2):
        response = team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Research Square v{version}",
                "sourceUrl": f"https://doi.org/10.21203/rs.3.rs-10024823/v{version}",
                "sourceKind": "paper",
                "summary": "Versioned preprint.",
                "metadata": {"doi": f"10.21203/rs.3.rs-10024823/v{version}"},
                "createdByAgent": "source-extractor",
            },
        )
        registered.append(response["candidate"])
    team_workflow_orchestration_service.assess_source_candidate_quality(
        team["teamId"],
        registered[0]["candidateId"],
        {
            "decision": "approved",
            "assessedByAgent": "source-extractor",
            "evidenceRefs": [{"type": "doi", "id": "10.21203/rs.3.rs-10024823/v1"}],
        },
    )

    listed = team_workflow_orchestration_service.list_candidate_store(
        team["teamId"],
        candidate_type="source_manifest",
        quality_status="source_quality_approved",
    )

    assert listed["candidateCount"] == 1
    assert listed["candidates"][0]["candidateId"] == registered[0]["candidateId"]
    assert listed["candidates"][0]["sourceVersionFamily"]["state"] == "superseded"
    assert listed["sourceFamilySummary"] == {
        "sourceRecordCount": 1,
        "independentSourceCount": 0,
        "versionFamilyCount": 1,
        "supersededRecordCount": 1,
    }


def test_stage_agent_context_receives_version_chain_and_independent_count(
    tmp_path,
    monkeypatch,
) -> None:
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_fake_local_research_config(monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="资料提炼")
    session_service.ensure_agent_direct_session(agent_id=agent["agentId"], title="资料提炼")
    team = team_service.create_team(
        name="挑战杯科研团队",
        members=[{"agentId": agent["agentId"], "role": "source_extractor", "agentName": "资料提炼"}],
    )
    run_response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "topic": "睡眠功能假说",
            "agentRoles": ["source_extractor"],
            "agentIds": {"source_extractor": agent["agentId"]},
            "querySeeds": ["sleep synaptic homeostasis"],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    run_id = run_response["run"]["runId"]
    for version in (1, 2):
        team_workflow_orchestration_service.register_candidate_source(
            team["teamId"],
            {
                "title": f"Research Square v{version}",
                "sourceUrl": f"https://doi.org/10.21203/rs.3.rs-10024823/v{version}",
                "sourceKind": "paper",
                "summary": "Versioned sleep preprint.",
                "allowedForAnalysis": True,
                "metadata": {
                    "sourceCollectionRunId": run_id,
                    "doi": f"10.21203/rs.3.rs-10024823/v{version}",
                },
                "createdByAgent": agent["agentId"],
            },
        )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda session_id, content, **kwargs: {
            "accepted": True,
            "sessionId": session_id,
            "turnId": "turn-version-family",
            "status": "running",
        },
    )
    task = team_workflow_orchestration_service.start_source_collection_stage_session_task(
        team["teamId"],
        run_id,
        {"stageId": "extraction", "agentId": agent["agentId"], "agentRole": "source_extractor"},
    )

    context = team_workflow_orchestration_service.get_source_collection_stage_task_context(
        team["teamId"],
        task_id=task["taskId"],
        max_records=10,
    )

    assert context["counts"]["candidateCount"] == 2
    assert context["counts"]["independentSourceCount"] == 1
    assert context["counts"]["versionFamilyCount"] == 1
    assert context["counts"]["supersededSourceRecordCount"] == 1
    assert sorted(item["sourceVersionFamily"]["state"] for item in context["candidates"]) == [
        "current",
        "superseded",
    ]
    assert all(
        item["sourceVersionFamily"]["evidencePolicy"] == "hypothesis_generation_only"
        for item in context["candidates"]
    )
