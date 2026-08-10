from core.web.services.team_workflow.research_runtime.node_operational_projection import (
    project_node_operations,
)


def test_project_node_operations_selects_latest_attempt_records() -> None:
    record = {
        "nodeRuns": [
            {"nodeRunId": "nr-1", "nodeId": "source_finding", "attempt": 1},
            {"nodeRunId": "nr-2", "nodeId": "source_finding", "attempt": 2},
        ],
        "executionEnvelopes": [
            {"nodeRunId": "nr-1", "nodeId": "source_finding", "attempt": 1},
            {"nodeRunId": "nr-2", "nodeId": "source_finding", "attempt": 2, "status": "running"},
        ],
        "taskLeases": [
            {"nodeRunId": "nr-2", "attempt": 2, "leaseOwner": "worker-2", "status": "running"},
        ],
        "qualityGateEvaluations": [
            {"qualityGateId": "quality-2", "nodeId": "source_finding", "status": "passed"},
        ],
        "artifactManifests": [
            {"artifactId": "artifact-produced", "producerNodeRunId": "nr-1", "cacheDisposition": "produced"},
            {
                "artifactId": "artifact-reused",
                "producerNodeRunId": "nr-2",
                "cacheDisposition": "reused",
                "sourceArtifactIds": ["artifact-produced"],
            },
        ],
    }

    projected = project_node_operations(record, "source_finding")

    assert projected["executionEnvelope"]["nodeRunId"] == "nr-2"
    assert projected["taskLease"]["leaseOwner"] == "worker-2"
    assert projected["qualityGateEvaluation"]["qualityGateId"] == "quality-2"
    assert projected["artifactManifests"] == [record["artifactManifests"][1]]
    assert projected["artifactReuseCount"] == 1
