"""Real Team catalog navigation and initialization, without starting model work."""
from __future__ import annotations

import re

import pytest

from core.web.services.team.team_constants import (
    AI_SEARCH_TEAM_ID,
    CHALLENGE_CUP_RESEARCH_TEAM_ID,
    EVOLUTION_SYSTEM_TEAM_IDS,
    KNOWLEDGE_EXPANSION_TEAM_ID,
)
from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.instance_registry import fetch_json
from tests.e2e.helpers.page_anchors import domain_recipe_selector, primary_nav_link

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


def test_team_catalog_initializes_and_survives_repeated_navigation(request, e2e_instance):
    from playwright.sync_api import expect

    # Read the deployed registry and native Sessions, not an in-process seed.
    # Every bundled identity must be selectable before visiting a feature page.
    # The existing route provisions configured evolution roles on its first
    # cold read. Allow that startup work; subsequent reads keep the normal
    # fixture timeout. This does not impose a new product latency contract.
    agents = fetch_json(e2e_instance.port, "/api/agents?detail=summary", timeout_seconds=60)
    bundled = [agent for agent in agents if (agent.get("metadata") or {}).get("builtinPreset")]
    starter = [agent for agent in bundled if agent["metadata"]["builtinPreset"] == "general_assistant_v1"]
    research = [agent for agent in bundled if agent["metadata"]["builtinPreset"].startswith("research_role_v1:")]
    assert len(starter) == 1, starter
    assert starter[0]["primaryMode"] == "chat"
    assert len(research) == 6, research
    assert len({agent["agentId"] for agent in bundled}) == 7
    for agent in bundled:
        assert agent["status"] == "active"
        session = e2e_instance.api_get(f"/api/sessions/{agent['directSessionId']}")
        assert session["id"] == agent["directSessionId"]
        assert session["agentId"] == agent["agentId"]
    public_presets = [agent for agent in agents if (agent.get("metadata") or {}).get("publicPresetKey")]
    assert len(public_presets) == 11
    assert all(agent["metadata"].get("publicPresetSeedComplete") for agent in public_presets)
    for agent in public_presets:
        session = e2e_instance.api_get(f"/api/sessions/{agent['directSessionId']}")
        assert session["agentId"] == agent["agentId"]
        assert not session.get("messages"), "Public presets must start without developer transcripts"
    companions = e2e_instance.api_get("/api/agent-plugins/virtual-human-life/companions")
    companion = next(row for row in companions if row["displayName"] == "洛天依")
    assert companion["snapshot"]["state"]["lifePaused"] is True
    owner_id = companion["agentId"]
    helpers = [agent for agent in agents if (agent.get("metadata") or {}).get("lifeStewardForAgentId") == owner_id
               or (agent.get("metadata") or {}).get("selfWakeForAgentId") == owner_id]
    assert len(helpers) == 2
    for agent in helpers:
        session = e2e_instance.api_get(f"/api/sessions/{agent['directSessionId']}")
        assert session["agentId"] == agent["agentId"]
        assert not session.get("messages")

    # Complete the deployment API assertions before the browser starts its
    # unrelated first-page hydration and selection requests.
    page = request.getfixturevalue("page")
    page.locator(primary_nav_link("/teams")).click()
    expect(page.locator(domain_recipe_selector("generic-team-workspace"))).to_be_visible()
    expect(page.get_by_text("6 位成员可用", exact=True)).to_be_visible()
    # A warm frontend can reuse its catalog cache. Inspect the deployed owner
    # through its normal read endpoint instead of requiring another UI request.
    for _ in range(120):
        catalog = e2e_instance.api_get("/api/teams")
        state = catalog.get("systemTeamBootstrap", {})
        if state.get("status") in {"ready", "failed"}:
            break
        page.wait_for_timeout(500)
    print(f"[team-journey] instance={e2e_instance.instance_id} bootstrap={state}")
    assert state.get("status") == "ready", state
    expected = {CHALLENGE_CUP_RESEARCH_TEAM_ID, AI_SEARCH_TEAM_ID, KNOWLEDGE_EXPANSION_TEAM_ID, *EVOLUTION_SYSTEM_TEAM_IDS}
    assert expected <= {team["teamId"] for team in catalog.get("teams", [])}
    attempt = state.get("attempt")
    for _ in range(3):
        page.locator(primary_nav_link("/chat")).click()
        expect(page).to_have_url(re.compile(re.escape(e2e_instance.base_url) + r"/chat(?:\?|$)"))
        page.locator(primary_nav_link("/teams")).click()
        expect(page.locator(domain_recipe_selector("generic-team-workspace"))).to_be_visible()
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(domain_recipe_selector("generic-team-workspace"))).to_be_visible()
    final_catalog = e2e_instance.api_get("/api/teams")
    final_state = final_catalog.get("systemTeamBootstrap", {})
    assert final_state.get("status") == "ready", final_state
    assert expected <= {team["teamId"] for team in final_catalog.get("teams", [])}
    assert final_state.get("attempt") == attempt, "Navigation restarted initialization during the retry window"
    page.goto(f"{e2e_instance.base_url}/companions", wait_until="domcontentloaded")
    expect(page.locator(domain_recipe_selector("virtual-human-companion-lobby"))).to_be_visible()
    expect(page.get_by_text("洛天依", exact=True)).to_be_visible()
    final_agents = e2e_instance.api_get("/api/agents?detail=summary")
    assert {agent["agentId"] for agent in final_agents} == {agent["agentId"] for agent in agents}, (
        "Feature navigation duplicated the deployed Agent catalog"
    )
