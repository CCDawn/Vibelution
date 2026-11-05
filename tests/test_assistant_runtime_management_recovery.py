"""Local management references recover original receipts without replay."""
import hashlib
import json

import pytest

from core.assistant_runtime.dispatch import DispatchError
from core.assistant_runtime.management import ManagementAdapter


class Probe:
    def __init__(self):
        self.writes, self.reads = [], []
        self.fail = False

    async def call(self, project_id, operation):
        probe = self
        class Client:
            async def management_action(self, **values):
                probe.writes.append((project_id, values))
                if probe.fail:
                    raise DispatchError("Lost acknowledgement", code="BACKEND_UNAVAILABLE")
                return {"action": values["action"], "requestId": values["request_id"], "status": "unknown"}

            async def management_receipt(self, **values):
                probe.reads.append((project_id, values))
                return {"action": values["action"], "requestId": values["request_id"], "status": "unknown"}
        return await operation(Client())


@pytest.mark.anyio
async def test_restart_discovers_lost_acknowledgement_and_reads_original_receipt(tmp_path):
    probe = Probe()
    adapter = ManagementAdapter(tmp_path, {"p": tmp_path / "project"}, probe.call)
    parameters = {"name": "private name", "goal": "private body", "credential": "private credential"}
    probe.fail = True
    with pytest.raises(DispatchError):
        await adapter.invoke("p", action="team_run", request_id="original", parameters=parameters)
    restarted = ManagementAdapter(tmp_path, {"p": tmp_path / "project"}, probe.call)
    page = restarted.list_requests(action="team_run")
    assert page["requests"] == [{"projectId": "p", "action": "team_run", "requestId": "original"}]
    assert page["total"] == 1 and page["nextOffset"] is None
    assert page["coverage"]["legacyUnrecoverable"] == page["coverage"]["invalidRecords"] == 0
    assert probe.reads == [] and len(probe.writes) == 1
    stored = next((tmp_path / "assistant_management").glob("*.json")).read_text(encoding="utf-8")
    assert all(secret not in stored for secret in parameters.values())
    assert "parameters" not in stored and "status" not in stored
    ref = page["requests"][0]
    result = await restarted.receipt(ref["projectId"], action=ref["action"], request_id=ref["requestId"])
    assert result["status"] == "unknown"
    result = await restarted.invoke("p", action="team_run", request_id="original", parameters=parameters)
    assert result["status"] == "unknown" and len(probe.writes) == 1
    assert probe.reads == [("p", {"action": "team_run", "request_id": "original"})] * 2


@pytest.mark.anyio
@pytest.mark.parametrize("initial_error", ["BACKEND_TIMEOUT", "SCOPE_DENIED"])
async def test_archive_missing_receipt_never_replays_an_ambiguous_write(tmp_path, initial_error):
    writes, reads = [], []

    class Client:
        async def management_action(self, **values):
            writes.append(values)
            if len(writes) == 1:
                raise DispatchError("First request did not return a receipt.", code=initial_error)
            return {"status": "unknown", "action": values["action"], "requestId": values["request_id"]}

        async def management_receipt(self, **values):
            reads.append(values)
            raise DispatchError("Original target receipt is unavailable.", code="REQUEST_UNAVAILABLE")

    async def call(_project_id, operation):
        return await operation(Client())

    projects = {"p": tmp_path / "project"}
    adapter = ManagementAdapter(tmp_path, projects, call)
    arguments = {"action": "agent_archive", "request_id": "original",
        "parameters": {"agent_id": "agent-a", "expected_config_revision": 3}}
    with pytest.raises(DispatchError) as initial:
        await adapter.invoke("p", **arguments)
    assert initial.value.code == initial_error
    restarted = ManagementAdapter(tmp_path, projects, call)
    if initial_error == "SCOPE_DENIED":
        # Only the persisted, authenticated pre-admission denial permits the
        # original envelope after authorization is explicitly supplied.
        assert (await restarted.invoke("p", **arguments))["status"] == "unknown"
        assert len(writes) == 2 and writes[1]["require_existing_subject"] is True
    with pytest.raises(DispatchError) as ambiguous:
        await restarted.invoke("p", **arguments)
    assert ambiguous.value.code == "OPERATION_UNCONFIRMED"
    assert len(writes) == (2 if initial_error == "SCOPE_DENIED" else 1)
    assert all(row == {"action": "agent_archive", "request_id": "original"} for row in reads)


@pytest.mark.anyio
async def test_legacy_fingerprint_stays_readable_but_directory_exposes_gap(tmp_path):
    probe = Probe()
    adapter = ManagementAdapter(tmp_path, {"p": tmp_path / "project"}, probe.call)
    key = adapter._key("p", "agent_archive", "known-old-id")
    path = tmp_path / "assistant_management" / (key + ".json")
    path.parent.mkdir()
    original = json.dumps({"schemaVersion": 1, "fingerprint": "a" * 64})
    path.write_text(original, encoding="utf-8")
    page = adapter.list_requests(action="team_run")
    assert page["requests"] == [] and page["total"] == 0
    assert page["coverage"]["legacyUnrecoverable"] == 1
    assert page["coverage"]["historyComplete"] is False
    assert page["status"] == "partial"
    assert path.read_text(encoding="utf-8") == original
    result = await adapter.receipt("p", action="agent_archive", request_id="known-old-id")
    assert result["status"] == "unknown" and probe.writes == []
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.anyio
async def test_request_directory_checks_binding_authorization_and_closed_metadata(tmp_path):
    probe = Probe()
    projects = {"p": tmp_path / "project", "removed": tmp_path / "other"}
    adapter = ManagementAdapter(tmp_path, lambda: projects, probe.call)
    await adapter.invoke("p", action="team_run", request_id="healthy", parameters={"goal": "x"})
    await adapter.invoke("removed", action="team_run", request_id="hidden", parameters={"goal": "x"})
    projects.pop("removed")
    root = tmp_path / "assistant_management"
    valid = json.loads((root / (adapter._key("p", "team_run", "healthy") + ".json")).read_text(encoding="utf-8"))
    (root / ("0" * 64 + ".json")).write_text(json.dumps(valid), encoding="utf-8")
    invalid = {**valid, "reference": {**valid["reference"], "private": "must not escape"}}
    (root / ("1" * 64 + ".json")).write_text(json.dumps(invalid), encoding="utf-8")
    (root / ("2" * 64 + ".json")).write_text("not json", encoding="utf-8")
    page = adapter.list_requests()
    assert page["requests"] == [{"projectId": "p", "action": "team_run", "requestId": "healthy"}]
    assert page["coverage"]["invalidRecords"] == 3 and page["status"] == "partial"
    assert "hidden" not in str(page) and "must not escape" not in str(page)
    with pytest.raises(DispatchError) as denied:
        adapter.list_requests(project_id="removed")
    assert denied.value.code == "PROJECT_NOT_AUTHORIZED"
    projects["p"] = tmp_path / "different-root"
    page = adapter.list_requests()
    assert page["requests"] == [] and page["coverage"]["invalidRecords"] == 4


def test_request_directory_paginates_past_4096_with_model_safe_references(tmp_path):
    from tests.test_assistant_runtime_actions import _through_native_model_budget

    adapter = ManagementAdapter(tmp_path, {"p": tmp_path / "project"}, Probe().call)
    root = tmp_path / "assistant_management"
    root.mkdir()
    expected = []
    for index in range(4120):
        request_id = f"request-{index:04d}"
        reference = {"projectId": "p", "action": "team_run", "requestId": request_id}
        key = adapter._key("p", "team_run", request_id)
        record = {"schemaVersion": 1, "fingerprint": hashlib.sha256(b"private").hexdigest(), "reference": reference}
        (root / (key + ".json")).write_text(json.dumps(record), encoding="utf-8")
        expected.append(reference)
    # Start at the old ceiling; a fresh query can reach the final page.
    page = adapter.list_requests(action="team_run", offset=4096, limit=20)
    assert len(page["requests"]) <= 20 and page["nextOffset"] == 4116
    tail = adapter.list_requests(action="team_run", offset=page["nextOffset"], limit=20)
    assert tail["total"] == 4120 and tail["nextOffset"] is None and len(tail["requests"]) == 4
    recovered = page["requests"] + tail["requests"]
    assert recovered == expected[4096:]
    raw, outcome, facts, rendered = _through_native_model_budget(page)
    assert outcome is None and not facts.truncated
    assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)


def test_request_directory_rejects_revocation_during_scan(tmp_path, monkeypatch):
    projects = {"p": tmp_path / "project"}
    adapter = ManagementAdapter(tmp_path, lambda: projects, Probe().call)
    root = tmp_path / "assistant_management"
    root.mkdir()
    path = root / (adapter._key("p", "team_run", "original") + ".json")
    path.write_text(json.dumps({"schemaVersion": 1, "fingerprint": "a" * 64,
        "reference": {"projectId": "p", "action": "team_run", "requestId": "original"}}), encoding="utf-8")
    read = adapter._read
    def revoke(path):
        record = read(path)
        projects.clear()
        return record
    monkeypatch.setattr(adapter, "_read", revoke)
    with pytest.raises(DispatchError) as changed:
        adapter.list_requests()
    assert changed.value.code == "PROJECT_REGISTRY_RECONCILE_REQUIRED"
