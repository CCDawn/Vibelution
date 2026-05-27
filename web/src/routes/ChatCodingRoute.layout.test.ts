import { describe, expect, it } from "vitest";

import conversationStyles from "../components/conversation/ConversationView.module.css";
import routeSource from "./ChatCodingRoute.tsx?raw";
import routeStyles from "./ChatCodingRoute.module.css";

describe("ChatCodingRoute layout contract", () => {
  it("keeps the center conversation readable and the composer as a stable bottom layer", () => {
    expect(conversationStyles.timeline).toBeTypeOf("string");
    expect(conversationStyles.markdownBody).toBeTypeOf("string");
    expect(conversationStyles.operationSummary).toBeTypeOf("string");
    expect(conversationStyles.composer).toBeTypeOf("string");
    expect(conversationStyles.sendButton).toBeTypeOf("string");
    expect(conversationStyles.assistantTurn).toBeTypeOf("string");
    expect(conversationStyles.turnContent).toBeTypeOf("string");
    expect(conversationStyles.responseSegment_status).toBeTypeOf("string");
    expect(conversationStyles.userMessageBody).toBeTypeOf("string");
    expect(conversationStyles.messageBody).toBeTypeOf("string");
  });

  it("keeps side panes collapsible while allowing narrow screens to prioritize the center pane", () => {
    expect(routeSource).toContain("CHAT_CENTER_FIRST_MEDIA_QUERY");
    expect(routeSource).toContain("centerFirstLayout");
    expect(routeSource).toContain("centerFirstAutoCollapseRef");
    expect(routeSource).toContain("window.matchMedia(CHAT_CENTER_FIRST_MEDIA_QUERY)");
    expect(routeSource).toContain("styles.layoutCenterFirst");
    expect(routeStyles.layout).toBeTypeOf("string");
    expect(routeStyles.layoutCenterFirst).toBeTypeOf("string");
    expect(routeStyles.leftRail).toBeTypeOf("string");
    expect(routeStyles.rightPane).toBeTypeOf("string");
    expect(routeStyles.resizeHandle).toBeTypeOf("string");
    expect(routeStyles.centerPane).toBeTypeOf("string");
  });

  it("compresses the left rail into primary controls plus auxiliary status groups", () => {
    expect(routeSource).toContain("styles.resourceBlock");
    expect(routeSource).toContain("styles.resourceSplit");
    expect(routeSource).toContain("styles.companionBlock");
    expect(routeSource).toContain("styles.companionCompact");
    expect(routeSource).toContain("styles.petMiniAvatar");
    expect(routeSource).toContain("styles.featurePrimarySlot");
    expect(routeSource).toContain("styles.featureChipRow");
    expect(routeSource).toContain("styles.featureChip");
    expect(routeSource).not.toContain("<section className={styles.petShowcase}");
    expect(routeSource).not.toContain("styles.featurePresetGrid");

    expect(routeStyles.resourceBlock).toBeTypeOf("string");
    expect(routeStyles.resourceSplit).toBeTypeOf("string");
    expect(routeStyles.companionBlock).toBeTypeOf("string");
    expect(routeStyles.companionCompact).toBeTypeOf("string");
    expect(routeStyles.petMiniAvatar).toBeTypeOf("string");
    expect(routeStyles.featurePrimarySlot).toBeTypeOf("string");
    expect(routeStyles.featureChipRow).toBeTypeOf("string");
    expect(routeStyles.featureChip).toBeTypeOf("string");
  });

  it("keeps prompt cache observation visible in the current session status strip", () => {
    expect(routeSource).toContain("const sessionCacheUsage = detail?.cacheUsage");
    expect(routeSource).toContain("label: t(\"promptCache\")");
    expect(routeSource).toContain("turnCachedInputTokens");
    expect(routeSource).toContain("turnInputTokens");
    expect(routeSource).toContain("turnCacheHitRate");
    expect(routeSource).toContain("lastCachedInputTokens");
    expect(routeSource).toContain("lastInputTokens");
    expect(routeSource).toContain("totalCachedInputTokens");
    expect(routeSource).toContain("totalInputTokens");
    expect(routeSource).toContain("cacheObservationPending");
  });

  it("exposes dynamic group creation from the unified conversation list", () => {
    expect(routeSource).toContain("handleToggleGroupComposer");
    expect(routeSource).toContain("handleCreateGroupRoom");
    expect(routeSource).toContain("fetchJson<AgentInstance[]>(\"/api/agents\")");
    expect(routeSource).toContain("body: JSON.stringify({ title, agentIds, mode })");
    expect(routeSource).toContain("styles.groupComposerPanel");
    expect(routeSource).toContain("styles.groupAgentPicker");
    expect(routeSource).toContain("styles.createGroupButton");

    expect(routeStyles.sessionActionRow).toBeTypeOf("string");
    expect(routeStyles.newGroupButton).toBeTypeOf("string");
    expect(routeStyles.groupComposerPanel).toBeTypeOf("string");
    expect(routeStyles.groupAgentOption).toBeTypeOf("string");
    expect(routeStyles.createGroupButton).toBeTypeOf("string");
  });

  it("opens group conversations inside the chat page instead of navigating away", () => {
    expect(routeSource).toContain("activeGroupRoomId");
    expect(routeSource).toContain("handleOpenGroupRoom");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${activeGroupRoomId}`)");
    expect(routeSource).toContain("handleStartGroupRound");
    expect(routeSource).toContain("updateGroupRoomMutation");
    expect(routeSource).toContain("deleteGroupRoomMutation");
    expect(routeSource).toContain("participantSessionIds: sessionIds");
    expect(routeSource).toContain("styles.groupManagementPanel");
    expect(routeSource).toContain("styles.groupConversationFrame");
    expect(routeSource).not.toContain("navigate(`/chat-rooms");

    expect(routeStyles.groupConversationFrame).toBeTypeOf("string");
    expect(routeStyles.groupManagementPanel).toBeTypeOf("string");
    expect(routeStyles.groupMemberPicker).toBeTypeOf("string");
    expect(routeStyles.groupMemberChip).toBeTypeOf("string");
    expect(routeStyles.groupMessageTimeline).toBeTypeOf("string");
    expect(routeStyles.groupRoundBlock).toBeTypeOf("string");
    expect(routeStyles.groupMessageCard).toBeTypeOf("string");
    expect(routeStyles.groupComposerBar).toBeTypeOf("string");
  });
});
