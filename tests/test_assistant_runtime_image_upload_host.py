"""Private upload admission and canonical config application, exclusively in Temp."""
import base64
from fastapi.testclient import TestClient
from core.assistant_runtime.host import create_app
from core.assistant_runtime.appearance_protocol import validate_result
from tests.test_assistant_runtime_operator_image_actions import operator, PNG, read

TOKEN="private-operator-import-test-token"
KEY="a"*32
class Native:
    def bootstrap(self): return {"assistant":{"agentId":"synthetic","directSessionId":"synthetic"}}
    def shutdown(self): pass
class Control:
    appearance_enabled=True
    def __init__(self): self.used=False
    def admit_image_import(self,key,kind):
        if key!=KEY or kind!="avatar" or self.used:return False
        self.used=True;return True
    def close(self):pass

def client(control=None):
    return TestClient(create_app(native=Native(),token=TOKEN,main_control=control),base_url="http://127.0.0.1",headers={"Authorization":"Bearer "+TOKEN})
def payload():return {"deliveryId":KEY,"filename":"chosen.png","contentType":"image/png","dataBase64":base64.b64encode(PNG).decode()}

def test_image_import_requires_explicit_capability_private_auth_and_live_admission(operator):
    route="/api/assistant/operator-assets/avatar"
    with client() as c:assert c.post(route,json=payload()).status_code==405
    gate=Control()
    with client(gate) as c:
        assert c.get("/health").json()["appearanceControlVersion"]==1
        assert c.post(route,json=payload(),headers={"Authorization":"Bearer invalid"}).status_code==401
        assert c.post(route,json=payload(),headers={"Origin":"https://foreign.invalid"}).status_code==403
        for body in ({k:v for k,v in payload().items() if k!="deliveryId"},{**payload(),"path":"C:/secret.png"},{**payload(),"filename":3}):
            r=c.post(route,json=body);assert r.status_code==422 and "secret" not in r.text
        assert c.post(route+"?path=secret",json=payload()).status_code==422
        assert c.post(route,json={**payload(),"deliveryId":"b"*32}).status_code==409
        assert c.post("/api/assistant/operator-assets/background",json=payload()).status_code==409
        assert not gate.used
    assert not (operator.parent/"avatars").exists()

def test_real_canonical_upload_applies_and_same_delivery_cannot_create_another_resource(operator,monkeypatch):
    from core.assistant_runtime import operator_assets
    monkeypatch.setattr(operator_assets.avatars,"_legacy_user_avatar_dir",lambda:operator.parent/"unused-legacy")
    gate=Control()
    with client(gate) as c:
        result=c.post("/api/assistant/operator-assets/avatar",json=payload())
        assert result.status_code==200
        applied=result.json()
        assert applied["ok"] and applied["verified"] and applied["selection"].startswith("workspace/user_avatars/")
        projected={"schemaVersion":1,"operation":"import","kind":"avatar","code":"applied","verified":True,"selection":applied["selection"]}
        assert validate_result("operator_image_upload",{"operation":"import","kind":"avatar"},projected)==projected
        assert read(operator)["user_profile"]["avatar_image_path"]==applied["selection"]
        current=c.get("/api/assistant/operator-assets/avatar").json()
        assert current["image"]["dataBase64"]==base64.b64encode(PNG).decode()
        assert c.post("/api/assistant/operator-assets/avatar",json=payload()).status_code==409
        assert len(list((operator.parent/"avatars").iterdir()))==1

def test_duplicate_or_oversized_upload_json_never_reaches_writer(operator):
    with client(Control()) as c:
        path="/api/assistant/operator-assets/avatar"
        assert c.post(path,content=b'{"deliveryId":"a","deliveryId":"b"}').status_code==422
        assert c.post(path,content=b"x"*(14*1024*1024+1)).status_code==413
    assert not (operator.parent/"avatars").exists()


def test_native_stop_ack_precedes_image_cancellation_and_rejected_stop_does_not_cancel():
    from fastapi import HTTPException
    calls=[]
    class StopNative(Native):
        def stop(self,turn_id):
            calls.append(("native",turn_id))
            if turn_id=="stale":raise HTTPException(409,detail="stale turn")
            return {"id":"synthetic","stopRequested":True}
    class StopControl(Control):
        def cancel_image_imports(self,turn_id):calls.append(("cancel",turn_id))
    with TestClient(create_app(native=StopNative(),token=TOKEN,main_control=StopControl()),base_url="http://127.0.0.1",headers={"Authorization":"Bearer "+TOKEN}) as c:
        assert c.post("/api/assistant/stop",json={"turnId":" current "}).status_code==202
        assert calls==[("native"," current "),("cancel","current")]
        assert c.post("/api/assistant/stop",json={"turnId":"stale"}).status_code==409
        assert calls[-1]==("native","stale")
