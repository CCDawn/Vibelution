"""Financial composer copy follows live UI language without changing identity."""

from copy import deepcopy

import pytest

from core.web.services import financial_assistant_service as service
from core.web.services import i18n


def test_financial_starters_follow_live_language_and_preserve_agent(monkeypatch):
    agent = {
        "displayName": "我的研究员",
        "metadata": {"financialAssistantProfile": service.PROFILE},
        "personaProfile": {"identityNotes": "保留我的人物设定。"},
        "taskProfile": {"mission": "保留我的研究目标。"},
    }
    original = deepcopy(agent)
    monkeypatch.setattr(service.directory, "get_agent", lambda _agent_id: agent)
    config = {"ui": {"language": "zh"}}
    monkeypatch.setattr(i18n, "get_public_config_snapshot", lambda: config)

    chinese = service.composer_starters_for_agent("finance")
    assert chinese == list(service.COMPOSER_STARTERS)
    config["ui"]["language"] = "en"
    english = service.composer_starters_for_agent("finance")
    assert [item["heading"] for item in english] == [
        "News reference",
        "Financial report evidence",
        "Risk boundaries",
    ]
    assert all(item["command"].isascii() for item in english)
    assert "insufficient evidence" in english[1]["command"]
    assert "Do not suggest placing orders" in english[2]["command"]
    english[0]["heading"] = "Edited card"
    assert service.composer_starters_for_agent("finance")[0]["heading"] == "News reference"
    config["ui"]["language"] = "zh"
    assert service.composer_starters_for_agent("finance") == chinese
    assert agent == original


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("agent", [None, {"metadata": {}}, {"metadata": {"financialAssistantProfile": "other"}}])
def test_non_financial_agents_keep_shared_starter_fallback(monkeypatch, language, agent):
    monkeypatch.setattr(service.directory, "get_agent", lambda _agent_id: agent)
    monkeypatch.setattr(
        i18n, "get_public_config_snapshot", lambda: {"ui": {"language": language}}
    )
    assert service.composer_starters_for_agent("ordinary") is None
    assert service.composer_starters_for_agent("") is None
