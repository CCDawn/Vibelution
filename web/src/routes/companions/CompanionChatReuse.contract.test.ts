import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import lobbySource from "../CompanionsRoute.tsx?raw";
import chatSource from "../chat/ChatCodingRouteWorkbench.tsx?raw";
import statusRailSource from "../chat/ChatCodingStatusRail.tsx?raw";
import chatConversationSurfaceModelSource from "../chat/useChatConversationSurfaceModel.tsx?raw";
import centerTabsSource from "../chat/ChatCenterTabStrip.tsx?raw";
import codingCenterTabsSource from "../chat/ChatCodingCenterTabs.tsx?raw";
import streamSource from "../chat/useSessionDetailStream.ts?raw";
import sessionEventStreamSource from "../chat/sessionEventStream.ts?raw";
import conversationHeaderSource from "./CompanionConversationHeader.tsx?raw";
import lifeRailSource from "./CompanionLifeRail.tsx?raw";
import personRailSource from "./CompanionPersonRail.tsx?raw";
import portraitSource from "./CompanionPortrait.tsx?raw";
import attentionSource from "./CompanionDesktopAttention.tsx?raw";
import portraitStyles from "./companions.styles.ts";
import appShellSource from "../../app/AppShell.tsx?raw";

const portraitMotionSource = readFileSync(
  new URL("../../design/route-css/companions.tailwind.css", import.meta.url),
  "utf8",
);

describe("virtual-human native Chat reuse", () => {
  it("uses the sole Chat route writer to select a native direct Session with companion identity", () => {
    expect(lobbySource).toContain("openCompanionSession(");
    expect(lobbySource).not.toContain("/chat?session=");
    expect(chatSource).toContain("requestedSessionId");
    expect(chatSource).toContain('get("companion")');
    expect(chatSource).toContain("companion.directSessionId === requestedSessionId");
    expect(chatSource).toContain("sessionsForChatRoute({");
    expect(chatSource).toContain("listVirtualHumanCompanionActivity");
    expect(chatSource).toContain("companionRouteUpgradeLookupEnabled");
    expect(chatSource).toContain(
      "companionAgentIdForDirectSession(companionRouteUpgradeQuery.data, requestedSessionId)",
    );
    expect(chatSource).toContain('telemetrySource: "companion_route_upgrade"');
    expect(chatSource).toContain("const verifiedCompanionMode = Boolean(activeCompanion);");
    expect(chatSource).toContain("const companionTransportAgentId = activeCompanion?.agentId;");
    expect(chatSource).toContain("const companionComposerDisabled = composerDisabled || (companionMode && !companionTransportAgentId);");
    expect(chatSource).toContain("companionAgentId: companionTransportAgentId");
    expect(chatSource).toContain("composerDisabled: composerDisabledDuringModelParametersSave");
    expect(chatSource).toContain("const composerDisabledDuringModelParametersSave = companionComposerDisabled || modelParametersSavePending;");
    expect(chatSource).toContain("if (financeSurface || verifiedCompanionMode) return false;");
    expect(chatSource).toContain('actionMode: "send" as const');
    expect(chatSource).toContain("attachmentInputDisabled: companionComposerDisabled");
    expect(chatSource).not.toContain("companionAgentId: companionMode ? requestedCompanionId : undefined");
    expect(chatSource).toContain("companionMode,");
    expect(chatSource).toContain("<ChatCenterSessionSurface");
    expect(chatSource).toContain("<CompanionPersonRail");
    expect(chatSource).toContain("<ChatCodingStatusRail");
    expect(statusRailSource).toContain("<CompanionLifeRail");
    expect(codingCenterTabsSource).toContain("<CompanionConversationHeader");
    expect(chatSource).toContain("<ChatCodingCenterTabs");
    expect(centerTabsSource).toContain("companionHeader ?? (");
    expect(conversationHeaderSource).toContain("<CompanionPortrait");
    expect(conversationHeaderSource).toContain("<CompanionProactiveSettingsPopover");
    expect(personRailSource).toContain("agentCenterConfigRoute({");
    expect(personRailSource).toContain("returnTo: companionReturnTarget(companion)");
    expect(personRailSource).not.toContain("/companions/${");
  });

  it("keeps one guarded session-stream owner and removes person/session pickers in companion mode", () => {
    expect(streamSource).toContain("createSessionEventStream = createDefaultSessionEventStream");
    expect(streamSource).toContain("const acquired = acquireSessionStream(streamSessionId, createSessionEventStream);");
    expect(sessionEventStreamSource).toContain("consumeGuardedEventStream(");
    expect(sessionEventStreamSource).not.toContain("new EventSource");
    expect(lobbySource).not.toContain("EventSource");
    expect(lifeRailSource).not.toContain("EventSource");
    expect(personRailSource).not.toContain("EventSource");
    expect(codingCenterTabsSource).toContain("showSessionTabs={!financeSurface && !verifiedCompanionMode");
    expect(codingCenterTabsSource).toContain("showAgentFallbackTab={!financeSurface && !verifiedCompanionMode}");
    expect(chatSource).toContain("<ChatCodingCenterTabs");
  });

  it("opens life management as an exact hidden native Session", () => {
    const lifeStart = statusRailSource.indexOf("onOpenLifeSteward={(stewardSessionId) => {");
    const lifeSteward = statusRailSource.slice(lifeStart, statusRailSource.indexOf("/>", lifeStart));
    expect(lifeStart).toBeGreaterThanOrEqual(0);
    expect(lifeSteward).toContain("openSession(stewardSessionId,");
    expect(lifeSteward).toContain('telemetrySource: "virtual_human_life_steward"');
    expect(lifeSteward).not.toContain("/chat?session=");
  });

  it("removes technical composer chrome only from the verified companion presentation", () => {
    expect(chatConversationSurfaceModelSource).toContain("companionMode: verifiedCompanionMode");
    expect(chatConversationSurfaceModelSource).toContain("showMentalSnapshots: !verifiedCompanionMode");
    expect(chatConversationSurfaceModelSource).toContain("composerLeadingControl: verifiedCompanionMode ? undefined");
    expect(chatConversationSurfaceModelSource).toContain("permissionControl: !financeSurface && !verifiedCompanionMode && activeSessionAgent");
    expect(chatConversationSurfaceModelSource).toContain("llmControl: undefined");
    expect(chatConversationSurfaceModelSource).toContain("turnModelControl: financeSurface || verifiedCompanionMode ? undefined : turnModelControl");
    expect(chatConversationSurfaceModelSource).toContain("composerContextRing: financeSurface || verifiedCompanionMode ? null : composerContextRing");
    expect(chatConversationSurfaceModelSource).toContain("slashCommandSuggestions: verifiedCompanionMode ? [] : slashCommandSuggestions");
    expect(statusRailSource).toContain("if (verifiedCompanionMode)");
    expect(chatSource).toContain("statusRail={(");
    expect(chatSource).toContain("conversationIndex={financeSurface ? null : verifiedCompanionMode ? (");
  });

  it("keeps route-layer JSON transport in web/src/api", () => {
    expect(lobbySource).not.toContain("fetchJson");
    expect(lifeRailSource).not.toContain("fetchJson");
    expect(personRailSource).not.toContain("fetchJson");
  });

  it("keeps hidden Companion unread and notifications in a Companion-only adapter", () => {
    expect(appShellSource).toContain("<CompanionDesktopAttention");
    expect(attentionSource).toContain("listVirtualHumanCompanionActivity");
    expect(attentionSource).toContain("companionAgentId: companion.agentId");
    expect(attentionSource).toContain('completionIdentity: String(activity.activityStamp || "").trim()');
    expect(attentionSource).toContain("resolveCompanionActivityRefetchInterval");
    expect(attentionSource).toContain("refetchIntervalInBackground: false");
    expect(attentionSource).toContain("openCompanionSession(");
    expect(lobbySource).toContain("isSessionActivitySeen(");
    expect(lobbySource).toContain("markSessionActivitySeen(");
    expect(lobbySource).toContain("styles.unreadBadge");
    expect(chatSource).not.toContain("CompanionDesktopAttention");
    expect(streamSource).not.toContain("companionAgentId");
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

  it("projects Companion-only expression, scene, breath, and blink without replacing native typing", () => {
    expect(portraitSource).toContain("companion.snapshot.causal?.embodiment");
    expect(portraitSource).toContain("data-expression-id");
    expect(portraitSource).toContain("data-motion-preset");
    expect(portraitSource).toContain("data-scene-key");
    expect(portraitSource).toContain("data-companion-blink");
    expect(portraitSource).toContain("blinkProfile?.minIntervalMs");
    expect(portraitSource).toContain("--companion-blink-duration");
    expect(portraitSource).toContain("embodiment?.assetRefs?.expression");
    expect(portraitSource).toContain("setFailedAssetRef");
    expect(portraitStyles.portrait).toContain("data-[scene-key=campus-day]");
    expect(portraitMotionSource).toContain("@keyframes companion-portrait-breathe");
    expect(portraitMotionSource).toContain("@keyframes companion-portrait-blink");
    expect(portraitMotionSource).toContain("@media (prefers-reduced-motion: reduce)");
    expect(chatConversationSurfaceModelSource).toContain("companionMode: verifiedCompanionMode");
    expect(chatSource).not.toContain("EmbodimentState");
  });
});
