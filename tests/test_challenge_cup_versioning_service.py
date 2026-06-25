import pytest

from core.web.services import challenge_cup_versioning_service, team_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(challenge_cup_versioning_service, "PROJECT_ROOT", tmp_path)


def _create_research_team():
    return team_service.create_team(
        name="挑战杯ai科研团队",
        purpose="科研协作",
        members=[],
        team_kind="research",
        team_source="test",
    )


def test_candidate_versioning_store_records_versions_relations_and_rejections(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = _create_research_team()

    initial = challenge_cup_versioning_service.get_candidate_versioning_status(team["teamId"])
    assert initial["boundaries"]["autoApply"] is False
    assert initial["boundaries"]["writesFormalKnowledge"] is False
    assert initial["summary"]["versionCount"] == 0

    first = challenge_cup_versioning_service.record_candidate_version_event(
        team["teamId"],
        {
            "operation": "record_version",
            "candidateId": "candidate-a",
            "versionLabel": "v1",
            "summary": "Baseline hypothesis version.",
            "recordedByAgent": "challenge_cup_versioning",
        },
    )
    version_id = first["event"]["versionId"]
    assert first["status"]["summary"]["versionCount"] == 1
    assert first["status"]["versionHistory"][0]["candidateId"] == "candidate-a"

    supersede = challenge_cup_versioning_service.record_candidate_version_event(
        team["teamId"],
        {
            "operation": "supersede",
            "candidateId": "candidate-a",
            "versionLabel": "v2",
            "supersedesVersionId": version_id,
            "summary": "Metric was tightened after smoke evidence.",
            "reason": "smoke result exposed weak metric",
            "recordedByAgent": "challenge_cup_versioning",
        },
    )
    assert supersede["event"]["supersedesVersionId"] == version_id
    assert supersede["status"]["summary"]["relationCount"] == 1

    rejected = challenge_cup_versioning_service.record_candidate_version_event(
        team["teamId"],
        {
            "operation": "reject",
            "candidateId": "candidate-b",
            "summary": "Rejected because evidence is not reproducible.",
            "reason": "missing dataset and metric trace",
            "evidenceRefs": [{"kind": "loop", "id": "loop-evidence-1"}],
            "recordedByAgent": "challenge_cup_versioning",
        },
    )
    assert rejected["status"]["summary"]["rejectionCount"] == 1
    assert rejected["status"]["rejectionArchive"][0]["candidateId"] == "candidate-b"


def test_candidate_versioning_requires_relation_target_version(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = _create_research_team()

    with pytest.raises(challenge_cup_versioning_service.ChallengeCupVersioningError, match="Superseded version id"):
        challenge_cup_versioning_service.record_candidate_version_event(
            team["teamId"],
            {"operation": "supersede", "candidateId": "candidate-a"},
        )

    with pytest.raises(challenge_cup_versioning_service.ChallengeCupVersioningError, match="Derived-from version id"):
        challenge_cup_versioning_service.record_candidate_version_event(
            team["teamId"],
            {"operation": "derive", "candidateId": "candidate-a"},
        )
