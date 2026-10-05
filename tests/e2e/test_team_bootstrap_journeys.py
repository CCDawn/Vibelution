"""Real Team catalog navigation and initialization, without starting model work."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

from core.web.services.team.team_constants import (
    AI_SEARCH_TEAM_ID,
    EVOLUTION_SYSTEM_TEAM_IDS,
    KNOWLEDGE_EXPANSION_TEAM_ID,
)
from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.page_anchors import domain_recipe_selector, primary_nav_link

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


def test_team_catalog_initializes_and_survives_repeated_navigation(page, e2e_instance):
    from playwright.sync_api import expect

    snapshots = []
    catalogs = []

    def capture(response):
        if urlparse(response.url).path == "/api/teams" and response.request.method == "GET" and response.status == 200:
            payload = response.json()
            snapshots.append(payload.get("systemTeamBootstrap", {}))
            catalogs.append(payload)

    page.on("response", capture)
    try:
        page.locator(primary_nav_link("/teams")).click()
        expect(page.locator(domain_recipe_selector("teams-organization-workbench"))).to_be_visible()
        # Observe normal frontend polling; diagnostics must not trigger extra repairs.
        for _ in range(120):
            if snapshots and snapshots[-1].get("status") in {"ready", "failed"}:
                break
            page.wait_for_timeout(500)
        assert snapshots, "Team navigation made no successful catalog request"
        state = snapshots[-1]
        print(f"[team-journey] instance={e2e_instance.instance_id} bootstrap={state}")
        # A fresh instance may lack the six preconfigured Challenge Cup Agents.
        # This refusal must not prevent independent system Teams from appearing.
        if state.get("status") == "failed":
            assert "Challenge Cup AgentDirectory asset is missing:" in state.get("lastError", ""), state
            assert state.get("requiredSteps") == ["challenge_cup_research_team"], state
        else:
            assert state.get("status") == "ready", state
        expected = {AI_SEARCH_TEAM_ID, KNOWLEDGE_EXPANSION_TEAM_ID, *EVOLUTION_SYSTEM_TEAM_IDS}
        attempt = state.get("attempt")
        for _ in range(3):
            page.locator(primary_nav_link("/chat")).click()
            expect(page).to_have_url(re.compile(re.escape(e2e_instance.base_url) + r"/chat(?:\?|$)"))
            page.locator(primary_nav_link("/teams")).click()
            expect(page.locator(domain_recipe_selector("teams-organization-workbench"))).to_be_visible()
        with page.expect_response(lambda response: urlparse(response.url).path == "/api/teams" and response.status == 200):
            page.reload(wait_until="domcontentloaded")
        expect(page.locator(domain_recipe_selector("teams-organization-workbench"))).to_be_visible()
        assert expected <= {team["teamId"] for team in catalogs[-1].get("teams", [])}
        assert snapshots[-1].get("attempt") == attempt, "Navigation restarted initialization during the retry window"
    finally:
        page.remove_listener("response", capture)
