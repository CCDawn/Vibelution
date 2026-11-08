"""Workflow discussion opens the selected team's room after navigation and reload."""
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import e2e_enabled
from tests.e2e.helpers.instance_registry import fetch_json

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated browser acceptance"),
]


def test_workflow_discussion_tracks_the_selected_team_and_room(page, e2e_instance):
    for team_id in ("knowledge-expansion-team", "ai-search-team", "knowledge-expansion-team"):
        team = fetch_json(e2e_instance.port, f"/api/teams/{team_id}?detail=full")
        room_id = team["linkedChatRoomId"]
        room = fetch_json(e2e_instance.port, f"/api/chat-rooms/{room_id}")
        assert room["roomId"] == room_id
        page.goto(f"{e2e_instance.base_url}/teams?team={team_id}&teamWorkspace=flows", wait_until="domcontentloaded")
        page.get_by_role("button", name="团队讨论", exact=True).click(timeout=30_000)
        expect(page.locator('[data-testid="team-native-conversation"]')).to_be_visible(timeout=30_000)
        with page.expect_response(
            lambda response: response.request.method == "GET"
            and urlsplit(response.url).path == f"/api/chat-rooms/{room_id}", timeout=30_000,
        ) as room_response:
            page.reload(wait_until="domcontentloaded")
        assert room_response.value.ok
        expect(page.locator('[data-testid="team-native-conversation"]')).to_be_visible(timeout=30_000)
        expect(page.get_by_text(team["name"], exact=True).first).to_be_visible(timeout=30_000)
        for member in team["members"]:
            if member.get("agentName"):
                expect(page.get_by_text(member["agentName"], exact=True).first).to_be_visible(timeout=30_000)
        params = parse_qs(urlsplit(page.url).query)
        assert (params.get("team") or params.get("teamId")) == [team_id]
        assert params.get("teamConversationTeamId") == [team_id]
        assert params.get("teamConversation") == ["group"]
        assert params.get("room") == [room_id]
