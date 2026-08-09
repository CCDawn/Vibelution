import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  imageArtifactForMessage,
  isAgentInboxMessage,
  isCliAgentLifecycleMessage,
  isGroupRoomTranscriptMessage,
  isProviderFailureSummaryText,
  isRuntimeNoticeMessage,
  isRuntimeStatusContent,
  isTurnErrorMessage,
  researchOrgMessageChips,
} from "./conversationMessagePredicates";

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "msg",
    role: "user",
    content: "",
    timestamp: "2026-05-20T14:12:39",
    ...overrides,
  };
}

describe("conversationMessagePredicates", () => {it("classifies CLI Agent lifecycle messages from metadata", () => {
    expect(isCliAgentLifecycleMessage(message({
      role: "assistant",
      content: "terminal closed",
      metadata: { kind: "cli_agent_lifecycle" },
    }))).toBe(true);
    expect(isCliAgentLifecycleMessage(message({
      role: "assistant",
      content: "ordinary assistant output",
      metadata: { kind: "session_live_overlay" },
    }))).toBe(false);
  });

  it("extracts research organization communication chips from Agent inbox metadata", () => {
    const chips = researchOrgMessageChips(message({
      role: "user",
      content: "[Agent 私信]",
      metadata: {
        kind: "agent_inbox_message",
        inboxKind: "research_org_report",
        researchOrgIntent: "status_report",
        researchOrgMessageType: "report",
        researchOrgDeliveryMode: "private",
        wakeStatus: "not_requested",
      },
    }));

    expect(chips).toEqual([
      { key: "intent", label: "intent: status report", tone: "intent" },
      { key: "type", label: "type: report", tone: "meta" },
      { key: "delivery", label: "delivery: private", tone: "meta" },
      { key: "wake", label: "wake: not requested", tone: "wake" },
    ]);
    expect(researchOrgMessageChips(message({
      role: "user",
      content: "[Agent 私信]",
      metadata: {
        kind: "agent_inbox_message",
        inboxKind: "agent_direct_message",
      },
    }))).toEqual([]);
  });

  it("extracts completed image artifact metadata only", () => {
    expect(imageArtifactForMessage(message({
      role: "assistant",
      content: "海报生成完成",
      metadata: {
        kind: "image2_generation",
        status: "succeeded",
        imageUrl: "/api/sessions/session-a/artifacts/image.png",
        downloadUrl: "/api/sessions/session-a/artifacts/image.png?download=1",
        prompt: "AI poster",
        artifactId: "image.png",
        size: "1024x1536",
        quality: "high",
        model: "gpt-image-1.5",
      },
    }))).toEqual({
      imageUrl: "/api/sessions/session-a/artifacts/image.png",
      downloadUrl: "/api/sessions/session-a/artifacts/image.png?download=1",
      prompt: "AI poster",
      artifactId: "image.png",
      size: "1024x1536",
      quality: "high",
      model: "gpt-image-1.5",
    });
    expect(imageArtifactForMessage(message({
      role: "assistant",
      content: "生成中",
      metadata: {
        kind: "image2_generation",
        status: "running",
        imageUrl: "/api/sessions/session-a/artifacts/image.png",
      },
    }))).toBeNull();
  });
});
