import json

import pytest

from core.web.services.session.tool_approvals import _arguments_hash, _assistant_management_summary


def _arguments(values):
    return {"action": "operator_image_upload", "arguments_json": json.dumps(values)}


@pytest.mark.parametrize("kind", ["avatar", "background"])
def test_image_upload_approval_projects_only_validated_kind(monkeypatch, kind):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    assert _assistant_management_summary(_arguments({"kind": kind})) == {
        "assistantAction": "operator_image_upload", "assistantTargets": {"kind": kind},
    }
    other = "background" if kind == "avatar" else "avatar"
    assert _arguments_hash(_arguments({"kind": kind})) != _arguments_hash(_arguments({"kind": other}))


@pytest.mark.parametrize("values", [{}, {"kind": "other"}, {"kind": None},
    {"kind": "avatar", "path": "C:/private.png"}, {"kind": "background", "url": "https://example.com"}])
def test_image_upload_approval_fails_closed(monkeypatch, values):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary(_arguments(values))
    assert result["assistantArgumentsInvalid"] is True
    assert "assistantTargets" not in result
    assert "private.png" not in str(result)


def test_image_upload_approval_rejects_non_launcher_and_malformed_json(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: False)
    assert _assistant_management_summary(_arguments({"kind": "avatar"})) == {"assistantArgumentsInvalid": True}
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    for raw in (None, "{", "[]", " " * 16001):
        assert _assistant_management_summary({"action": "operator_image_upload", "arguments_json": raw})["assistantArgumentsInvalid"] is True
