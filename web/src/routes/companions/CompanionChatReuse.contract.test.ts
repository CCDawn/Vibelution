import { describe, expect, it } from "vitest";

import lobbySource from "../CompanionsRoute.tsx?raw";
import chatSource from "../chat/ChatCodingRouteWorkbench.tsx?raw";
import streamSource from "../chat/useSessionDetailStream.ts?raw";
import lifeRailSource from "./CompanionLifeRail.tsx?raw";
import personRailSource from "./CompanionPersonRail.tsx?raw";

describe("virtual-human native Chat reuse", () => {
  it("uses the companion route only to select a native direct Session", () => {
    expect(lobbySource).toContain("companionSessionRoute(companion, lang)");
    expect(chatSource).toContain("requestedSessionId");
    expect(chatSource).toContain("companion.directSessionId === requestedSessionId");
    expect(chatSource).toContain("<ChatCenterSessionSurface");
    expect(chatSource).toContain("<CompanionPersonRail");
    expect(chatSource).toContain("<CompanionLifeRail");
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
});
