import { describe, expect, it } from "vitest";

import lobbySource from "../CompanionsRoute.tsx?raw";
import chatSource from "../chat/ChatCodingRouteWorkbench.tsx?raw";
import streamSource from "../chat/useSessionDetailStream.ts?raw";
import lifeRailSource from "./CompanionLifeRail.tsx?raw";
import personRailSource from "./CompanionPersonRail.tsx?raw";
import portraitSource from "./CompanionPortrait.tsx?raw";
import portraitStyles from "./companions.styles.ts";

describe("virtual-human native Chat reuse", () => {
  it("uses the sole Chat route writer to select a native direct Session with companion identity", () => {
    expect(lobbySource).toContain("openCompanionSession(");
    expect(lobbySource).not.toContain("/chat?session=");
    expect(chatSource).toContain("requestedSessionId");
    expect(chatSource).toContain('get("companion")');
    expect(chatSource).toContain("companion.directSessionId === requestedSessionId");
    expect(chatSource).toContain("companionMode,");
    expect(chatSource).toContain("<ChatCenterSessionSurface");
    expect(chatSource).toContain("<CompanionPersonRail");
    expect(chatSource).toContain("<CompanionLifeRail");
    expect(personRailSource).toContain("agentCenterConfigRoute({");
    expect(personRailSource).toContain("returnTo: companionReturnTarget(companion)");
    expect(personRailSource).not.toContain("/companions/${");
  });

  it("keeps one SSE owner and removes person/session pickers in companion mode", () => {
    expect(streamSource).toContain("new EventSource");
    expect(lobbySource).not.toContain("EventSource");
    expect(lifeRailSource).not.toContain("EventSource");
    expect(personRailSource).not.toContain("EventSource");
    expect(chatSource).toContain("showSessionTabs={!companionMode");
    expect(chatSource).toContain("showAgentFallbackTab={!companionMode}");
  });

  it("keeps route-layer JSON transport in web/src/api", () => {
    expect(lobbySource).not.toContain("fetchJson");
    expect(lifeRailSource).not.toContain("fetchJson");
    expect(personRailSource).not.toContain("fetchJson");
  });

  it("uses the Agent avatar as one shared full portrait in the lobby card and chat person rail", () => {
    expect(lobbySource).toContain("<CompanionPortrait");
    expect(personRailSource).toContain("<CompanionPortrait");
    expect(portraitSource).toContain("companion.avatarImageUrl");
    expect(portraitStyles.portraitImage).toContain("object-contain");
    expect(portraitStyles.portraitImage).toContain("object-bottom");
  });
});
