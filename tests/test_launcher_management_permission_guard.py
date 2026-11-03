"""Only the native settings command may change the Launcher management mode."""
import pytest

from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as personal
from core.web.services.local_assistant import management_permissions as permissions
from tests.test_launcher_management_permission_api import _private_operator_config
from tests.test_personal_assistant_service import finance_env, personal_env


def test_generic_update_and_tool_catalog_cannot_self_elevate(personal_env):
    from core.web.services.agent_operation_service import update_agent_from_catalog_request

    aid = personal.create_personal_assistant()["assistant"]["agentId"]
    payload = {permissions.METADATA_KEY: {"preset": "full_access", "revision": 1}}
    with pytest.raises(directory.AgentDirectoryError):
        directory.update_agent_instance(aid, metadata=payload)
    with pytest.raises(directory.AgentDirectoryError):
        update_agent_from_catalog_request(aid, updates={"metadata": payload})
    with pytest.raises(directory.AgentDirectoryError):
        directory.update_agent_instance(aid, metadata=list(payload.items()))
    assert permissions.read(aid) == {"preset": "request_approval", "revision": 0}
    assert permissions.update("auto_review", 0) == {"preset": "auto_review", "revision": 1}
    with pytest.raises(directory.AgentDirectoryError):
        directory.update_agent_instance(aid, metadata={permissions.METADATA_KEY: None})
    assert permissions.read(aid) == {"preset": "auto_review", "revision": 1}


def test_generic_creation_cannot_seed_a_management_grant(personal_env):
    with pytest.raises(directory.AgentDirectoryError):
        directory.create_agent_instance(display_name="forged assistant", metadata={
            permissions.METADATA_KEY: {"preset": "full_access", "revision": 1}})


def test_other_metadata_still_updates_and_preserves_the_user_selected_mode(personal_env):
    aid = personal.create_personal_assistant()["assistant"]["agentId"]
    permissions.update("auto_review", 0)
    directory.update_agent_instance(aid, metadata={"ordinaryMetadata": "kept"})
    assert permissions.read(aid) == {"preset": "auto_review", "revision": 1}
    assert directory.get_agent(aid)["metadata"]["ordinaryMetadata"] == "kept"
