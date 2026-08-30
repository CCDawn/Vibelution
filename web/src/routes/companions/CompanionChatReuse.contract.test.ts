import { describe, expect, it } from "vitest";

import lobbySource from "../CompanionsRoute.tsx?raw";
import chatSource from "../chat/ChatCodingRouteWorkbench.tsx?raw";
import centerTabsSource from "../chat/ChatCenterTabStrip.tsx?raw";
import streamSource from "../chat/useSessionDetailStream.ts?raw";
import conversationHeaderSource from "./CompanionConversationHeader.tsx?raw";
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
    expect(chatSource).toContain("const verifiedCompanionMode = Boolean(activeCompanion);");
    expect(chatSource).toContain("const companionTransportAgentId = activeCompanion?.agentId;");
    expect(chatSource).toContain("const companionComposerDisabled = composerDisabled || (companionMode && !companionTransportAgentId);");
    expect(chatSource).toContain("companionAgentId: companionTransportAgentId");
    expect(chatSource).toContain("composerDisabled: companionComposerDisabled");
    expect(chatSource).toContain('actionMode: "send" as const');
    expect(chatSource).toContain("attachmentInputDisabled: companionComposerDisabled");
    expect(chatSource).not.toContain("companionAgentId: companionMode ? requestedCompanionId : undefined");
    expect(chatSource).toContain("companionMode,");
    expect(chatSource).toContain("<ChatCenterSessionSurface");
    expect(chatSource).toContain("<CompanionPersonRail");
    expect(chatSource).toContain("<CompanionLifeRail");
    expect(chatSource).toContain("<CompanionConversationHeader");
    expect(centerTabsSource).toContain("companionHeader ?? (");
    expect(conversationHeaderSource).toContain("<CompanionPortrait");
    expect(conversationHeaderSource).toContain("<CompanionProactiveSettingsPopover");
    expect(personRailSource).toContain("agentCenterConfigRoute({");
    expect(personRailSource).toContain("returnTo: companionReturnTarget(companion)");
    expect(personRailSource).not.toContain("/companions/${");
  });

  it("keeps one SSE owner and removes person/session pickers in companion mode", () => {
    expect(streamSource).toContain("new EventSource");
    expect(lobbySource).not.toContain("EventSource");
    expect(lifeRailSource).not.toContain("EventSource");
    expect(personRailSource).not.toContain("EventSource");
    expect(chatSource).toContain("showSessionTabs={!verifiedCompanionMode");
    expect(chatSource).toContain("showAgentFallbackTab={!verifiedCompanionMode}");
  });

  it("opens life management as an exact hidden native Session", () => {
    expect(chatSource).toContain("onOpenLifeSteward");
    expect(chatSource).toContain('telemetrySource: "virtual_human_life_steward"');
    expect(chatSource).not.toContain("/chat?session=${");
  });

  it("removes technical composer chrome only from the verified companion presentation", () => {
    expect(chatSource).toContain("companionMode: verifiedCompanionMode");
    expect(chatSource).toContain("showMentalSnapshots: !verifiedCompanionMode");
    expect(chatSource).toContain("composerLeadingControl: verifiedCompanionMode ? undefined");
    expect(chatSource).toContain("permissionControl: !verifiedCompanionMode && activeSessionAgent");
    expect(chatSource).toContain("llmControl: verifiedCompanionMode ? undefined : sessionLlmControl");
    expect(chatSource).toContain("composerContextRing: verifiedCompanionMode ? null : composerContextRing");
    expect(chatSource).toContain("slashCommandSuggestions: verifiedCompanionMode ? [] : slashCommandSuggestions");
    expect(chatSource).toContain("statusRail={verifiedCompanionMode ? (");
    expect(chatSource).toContain("conversationIndex={verifiedCompanionMode ? (");
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
    expect(personRailSource).toContain("styles.personSummary");
    expect(personRailSource).toContain("styles.personFacts");
    expect(personRailSource).not.toContain("companionAbout(");
    expect(personRailSource).not.toContain("companionIdentity(");
    expect(personRailSource).not.toContain("打开她的完整档案");
  });
});
