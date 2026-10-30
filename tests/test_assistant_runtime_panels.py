from fastapi.testclient import TestClient

from core.assistant_runtime.host import create_app


class Native:
    assistant = {"agentId": "resident", "directSessionId": "session"}

    def identity(self):
        return {"assistant": dict(self.assistant)}


def test_panel_operations_are_private_closed_and_resident_scoped(monkeypatch):
    from core.web.services import personal_affairs_service, virtual_human_life_service

    calls = []
    class Affairs:
        def list_items(self, agent, *, kind, status):
            calls.append((agent, kind, status))
            return {"agentId": agent, "items": []}
        def add_item(self, agent, **kwargs):
            calls.append((agent, kwargs))
            return {"itemId": "item"}
    monkeypatch.setattr(personal_affairs_service, "get_personal_affairs_service", lambda: Affairs())
    monkeypatch.setattr(virtual_human_life_service, "virtual_human_preference_proposals", lambda agent: {"agentId": agent, "proposals": []})
    native = Native()
    client = TestClient(create_app(native=native, token="private-test-token"), base_url="http://127.0.0.1")
    path = "/api/assistant/panels"
    auth = {"Authorization": "Bearer private-test-token"}
    body = {"operation": "panelAffairs", "kind": "todo", "status": "open"}
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers={**auth, "Origin": "https://evil.invalid"}).status_code == 403
    assert client.post(path, json={**body, "agentId": "other"}, headers=auth).status_code == 422
    assert client.post(path, json={"operation": "anything", "url": "http://localhost"}, headers=auth).status_code == 422
    assert client.post(path, json={"operation": "panelAffairAdd", "payload": {"title": "x", "sourceTurnId": "foreign"}}, headers=auth).status_code == 422
    assert client.post(path, json=body, headers=auth).json()["agentId"] == "resident"
    assert client.post(path, json={"operation": "panelAffairAdd", "payload": {"title": "x"}}, headers=auth).json()["agentId"] == "resident"
    assert client.post(path, json={"operation": "panelProposals"}, headers=auth).json()["agentId"] == "resident"
    assert calls == [("resident", "todo", "open"), ("resident", {"kind": "todo", "title": "x", "note": "", "due_at": ""})]
    native.identity = lambda: {"assistant": {"agentId": "other", "directSessionId": "session"}}
    assert client.post(path, json=body, headers=auth).status_code == 503
    assert len(calls) == 2


def test_dialogue_update_uses_atomic_native_partial_patch(monkeypatch):
    from core.web.services import virtual_human_life_service
    from tools import pa_assistant_actions
    seen = []
    monkeypatch.setattr(pa_assistant_actions, "execute", lambda action, payload, runtime: seen.append((action, payload, runtime)))
    monkeypatch.setattr(virtual_human_life_service, "virtual_human_dialogue_settings", lambda agent: {"agentId": agent, "speakingInitiative": "natural"})
    client = TestClient(create_app(native=Native(), token="private-test-token"), base_url="http://127.0.0.1")
    auth = {"Authorization": "Bearer private-test-token"}
    response = client.post("/api/assistant/panels", json={"operation": "panelDialogueUpdate", "payload": {"speakingInitiative": "natural"}}, headers=auth)
    assert response.status_code == 200
    assert seen == [("dialogue_settings_update", {"speakingInitiative": "natural"}, {"agentId": "resident"})]


def test_panel_transport_uses_real_resident_services(tmp_path):
    from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run
    _run(tmp_path, """
        import os
        from pathlib import Path
        from fastapi.testclient import TestClient
        from core.assistant_runtime.host import NativeFacade, create_app
        native = NativeFacade(Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']))
        try:
            identity = native.bootstrap()['assistant']
            client = TestClient(create_app(native=native, token='private-test-token'), base_url='http://127.0.0.1')
            headers = {'Authorization': 'Bearer private-test-token'}
            def invoke(operation, **fields):
                response = client.post('/api/assistant/panels', json={'operation': operation, **fields}, headers=headers)
                assert response.status_code == 200, (operation, response.status_code, response.text)
                return response.json()
            assert invoke('panelSettings')['settings']['displayName']
            assert invoke('panelSettingsUpdate', payload={'displayName': 'Resident Test'})['settings']['displayName'] == 'Resident Test'
            assert invoke('panelDialogue')['agentId'] == identity['agentId']
            assert invoke('panelDialogueUpdate', payload={'speakingInitiative': 'natural'})['speakingInitiative'] == 'natural'
            assert invoke('panelProposals')['agentId'] == identity['agentId']
            item = invoke('panelAffairAdd', payload={'kind': 'todo', 'title': 'Resident task'})['item']
            rows = invoke('panelAffairs', kind='', status='')['items']
            assert [row['itemId'] for row in rows] == [item['itemId']]
            assert invoke('panelAffairComplete', itemId=item['itemId'])['item']['status'] == 'done'
        finally:
            assert native.shutdown()['closed']
    """, config_text=TEST_MODEL_CONFIG)
