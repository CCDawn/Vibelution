import asyncio
import pytest
from core.assistant_runtime.main_control import MainControlBroker
from core.assistant_runtime.appearance_protocol import validate_request, validate_result


def test_closed_appearance_contracts():
    assert validate_request("launcher_theme_get", {"operation": "read"}) == {"operation": "read"}
    assert validate_request("launcher_theme_set", {"operation": "set", "theme": "dark"})["theme"] == "dark"
    for body in ({"operation": "set", "theme": "DARK"}, {"operation": "set", "theme": "dark", "projectId": "x"}, {"operation": "set", "theme": True}):
        with pytest.raises(ValueError): validate_request("launcher_theme_set", body)
    with pytest.raises(ValueError): validate_request("operator_image_upload", {"operation":"import", "kind":"avatar", "path":"C:/secret.png"})


def test_theme_results_are_observed_and_closed():
    req = {"operation": "set", "theme": "dark"}
    assert validate_result("launcher_theme_set", req, {"schemaVersion":1,"operation":"set","code":"applied","theme":"dark"})["theme"] == "dark"
    for state in ("applied", "conflict", "unavailable", "unknown"):
        assert validate_result("launcher_theme_set", req, {"schemaVersion":1,"operation":"set","code":"applied","theme":"dark","workbenchSync":state})["workbenchSync"] == state
    with pytest.raises(ValueError):
        validate_result("launcher_theme_set", req, {"schemaVersion":1,"operation":"set","code":"applied","theme":"dark","workbenchSync":[]})
    for row in ({"schemaVersion":1,"operation":"set","code":"applied","theme":"light"}, {"schemaVersion":1,"operation":"set","code":"applied"}, {"schemaVersion":1,"operation":"set","code":"applied","theme":"dark","path":"secret"}):
        with pytest.raises(ValueError): validate_result("launcher_theme_set", req, row)


def test_image_results_expose_only_matching_logical_selection():
    req={"operation":"import","kind":"avatar"}
    valid={"schemaVersion":1,**req,"code":"applied","verified":True,"selection":"workspace/user_avatars/a.png"}
    assert validate_result("operator_image_upload",req,valid)==valid
    for patch in ({"selection":"C:/a.png"},{"selection":"theme_backgrounds/a.png"},{"selection":"workspace/user_avatars/../a.png"},{"verified":False},{"code":"cancelled"},{"extra":"secret"}):
        with pytest.raises(ValueError): validate_result("operator_image_upload",req,{**valid,**patch})


def test_appearance_capability_is_explicit_and_separate_from_project_permissions():
    async def run():
        old=MainControlBroker(lambda:())
        with pytest.raises(ValueError): await old.invoke("launcher_theme_get", {"operation":"read"})
        broker=MainControlBroker(lambda:(), appearance_enabled=True)
        flight=asyncio.create_task(broker.invoke("launcher_theme_get", {"operation":"read"}))
        claim=(await broker.claim())["request"]
        assert claim["action"]=="launcher_theme_get" and "projectId" not in claim
        assert broker.settle(claim["deliveryId"],{"schemaVersion":1,"operation":"read","code":"read","theme":"light"})
        assert (await flight)["theme"]=="light"
        broker.close();old.close()
    asyncio.run(run())


def test_image_claim_has_bounded_remaining_budget_and_expired_delivery_cannot_settle():
    async def run():
        broker=MainControlBroker(lambda:(), appearance_enabled=True, image_timeout_seconds=.02)
        flight=asyncio.create_task(broker.invoke("operator_image_upload", {"operation":"import","kind":"avatar"}))
        claim=(await broker.claim())["request"]
        assert 1<=claim["timeoutMs"]<=120000
        assert (await flight)["code"]=="unavailable"
        assert not broker.settle(claim["deliveryId"],{"schemaVersion":1,"operation":"import","kind":"avatar","code":"cancelled","verified":False})
        broker.close()
    asyncio.run(run())


def test_image_write_admission_is_live_single_use_and_bound_to_kind():
    async def run():
        broker=MainControlBroker(lambda:(), appearance_enabled=True)
        flight=asyncio.create_task(broker.invoke("operator_image_upload",{"operation":"import","kind":"avatar"}))
        claim=(await broker.claim())["request"]
        key=claim["deliveryId"]
        assert not broker.admit_image_import(key,"background")
        assert broker.admit_image_import(key,"avatar")
        assert not broker.admit_image_import(key,"avatar")
        broker.close()
        assert (await flight)["code"]=="unavailable"
        assert not broker.admit_image_import(key,"avatar")
    asyncio.run(run())


def test_appearance_actions_keep_native_governance_and_model_result_budget():
    import json
    from core.assistant_runtime.actions import bind_actions, unbind_actions, execute_action
    from tests.test_assistant_runtime_actions import Dispatch, _through_native_model_budget
    async def run():
        broker=MainControlBroker(lambda:(),appearance_enabled=True)
        dispatch=Dispatch();bind_actions(dispatch,asyncio.get_running_loop(),main_control=broker)
        try:
            for action in ("launcher_theme_get","launcher_theme_set","operator_image_upload","operator_image_options","operator_image_select"):
                contract=await asyncio.to_thread(execute_action,"describe",{"action":action})
                raw,outcome,facts,rendered=_through_native_model_budget(contract)
                assert outcome is None and not facts.truncated
                assert json.loads(rendered.split("\nResult:\n",1)[1])==json.loads(raw)
                assert contract.get("governed",False) is (action=="operator_image_upload")
            result=await asyncio.to_thread(execute_action,"operator_image_upload",{"kind":"avatar"},runtime={"agentId":"a","sessionId":"s"})
            assert result["status"]=="approval_required"
            with pytest.raises(ValueError):
                await asyncio.to_thread(execute_action,"operator_image_upload",{"kind":"avatar","path":"C:/private.png"},runtime={"agentId":"a","sessionId":"s"},governed=True)
            for payload in ({"ok":True,"kind":"avatar","options":["workspace/user_avatars/"+"a"*180+".png"]*12,"total":12,"nextOffset":None},
                            {"schemaVersion":1,"operation":"import","kind":"avatar","code":"applied","verified":True,"selection":"workspace/user_avatars/a.png"}):
                raw,outcome,facts,rendered=_through_native_model_budget(payload)
                assert outcome is None and not facts.truncated
                assert json.loads(rendered.split("\nResult:\n",1)[1])==json.loads(raw)
        finally:broker.close();unbind_actions(dispatch)
    asyncio.run(run())


def test_native_stop_cancels_only_its_unadmitted_image_and_prevents_late_write():
    async def run():
        broker=MainControlBroker(lambda:(),appearance_enabled=True)
        pending=asyncio.create_task(broker.invoke("operator_image_upload",{"operation":"import","kind":"avatar"},turn_id="turn-current"))
        claim=(await broker.claim())["request"]
        broker.cancel_image_imports("turn-stale")
        assert not pending.done()
        broker.cancel_image_imports("turn-current")
        assert (await pending)["code"]=="cancelled"
        assert not broker.admit_image_import(claim["deliveryId"],"avatar")
        draining=asyncio.create_task(broker.invoke("operator_image_upload",{"operation":"import","kind":"avatar"},turn_id="turn-admitted"))
        admitted=(await broker.claim())["request"]
        assert broker.admit_image_import(admitted["deliveryId"],"avatar")
        broker.cancel_image_imports("turn-admitted")
        assert not draining.done()
        broker.close();await draining
    asyncio.run(run())


def test_launcher_theme_help_describes_best_effort_primary_workbench_sync():
    from core.assistant_runtime.actions import _APPEARANCE_HELP

    help_text = _APPEARANCE_HELP["launcher_theme_set"]
    assert "authorityStatus" in help_text and "assistantSync" in help_text and "workbenchSync" in help_text
    assert "离线或不可达时不保证同步" in help_text
    assert "其他项目不变" in help_text
