"""HTTP regression for governed ingestion, full-body search and cited context."""

from tests.test_knowledge_routes import _setup, _source_artifact


def test_http_search_and_rag_use_matching_formal_body_and_preserve_acl(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    client, team, lead, member, outsider = _setup(tmp_path, monkeypatch)
    response = client.post(
        f"/api/teams/{team['teamId']}/knowledge-bases",
        json={"name": "Query quality", "actorAgentId": lead["agentId"]},
    )
    assert response.status_code == 201
    base_id = response.json()["knowledgeBaseId"]
    base = response.json()

    def approve(title, body):
        source = _source_artifact(client, base, team, lead, member, title=title)
        proposal = client.post(
            f"/api/knowledge-bases/{base_id}/refinement-proposals",
            json={
                "sourceArtifactIds": [source["sourceArtifactId"]],
                "proposedByAgentId": member["agentId"],
                "title": title,
                "content": body,
            },
        )
        assert proposal.status_code == 201, proposal.text
        reviewed = client.patch(
            f"/api/knowledge-bases/{base_id}/refinement-proposals/{proposal.json()['proposalId']}/review",
            json={"status": "approved", "reviewedByAgentId": lead["agentId"]},
        )
        assert reviewed.status_code == 200, reviewed.text
        return reviewed.json()["item"], source

    approve("Dark matter observations", "This report describes galaxy rotation measurements.")
    body = "\n".join(f"General introductory paragraph {index}." for index in range(55))
    body += "\nCUDA Event timing requires synchronization; proposalPayload preserves provenance."
    target, source = approve("CUDA Event timing", body)
    common = {"agentId": member["agentId"], "knowledgeBaseId": base_id}
    exact = client.get("/api/knowledge/search", params={**common, "query": "CUDA Event", "searchMode": "exact"})
    assert exact.status_code == 200
    assert [row["knowledgeItemId"] for row in exact.json()["results"]] == [target["knowledgeItemId"]]

    for mode in ("exact", "bm25", "semantic", "hybrid"):
        result = client.get(
            "/api/knowledge/rag/retrieve",
            params={**common, "query": "proposalPayload", "retrievalMode": mode, "topK": 1, "maxContextChars": 500},
        )
        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload["summary"]["contextCount"] == 1
        assert "proposalPayload" in payload["contexts"][0]["text"]
        assert payload["citations"][0]["knowledgeItemId"] == target["knowledgeItemId"]
        assert payload["citations"][0]["sourceArtifactIds"] == [source["sourceArtifactId"]]
    denied = client.get(
        "/api/knowledge/search",
        params={**common, "agentId": outsider["agentId"], "query": "proposalPayload", "searchMode": "bm25"},
    )
    assert denied.status_code == 200
    assert denied.json()["results"] == []
