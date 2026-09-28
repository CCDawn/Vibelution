import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  imageArtifactForMessage,
  isAgentInboxMessage,
  isCliAgentLifecycleMessage,
  isGroupRoomTranscriptMessage,
  isHotRestartResumeMessage,
  isProviderFailureSummaryText,
  isRecoverySupersededPartial,
  isRuntimeNoticeMessage,
  isRuntimeStatusContent,
  isSessionRecoveryResumedMessage,
  isSteerGuidanceMessage,
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

describe("conversationMessagePredicates", () => {
  it("classifies running-turn steer records from metadata", () => {
    expect(isSteerGuidanceMessage(message({
      role: "user",
      content: "先不要改代码",
      metadata: { kind: "user_guidance" },
    }))).toBe(true);
    expect(isSteerGuidanceMessage(message({
      role: "user",
      content: "普通用户消息",
      metadata: { kind: "journal_user_message" },
    }))).toBe(false);
  });

  it("classifies CLI Agent lifecycle messages from metadata", () => {
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

  it("classifies session recovery resumed rows from metadata", () => {
    const resumed = message({
      role: "assistant",
      content: "",
      metadata: {
        kind: "session_recovery_resumed",
        attempt: 2,
        turnLabel: "重构导出脚本",
      },
    });
    expect(isSessionRecoveryResumedMessage(resumed)).toBe(true);
    // The recovery row is a lifecycle-style status line, not a runtime notice:
    // it must survive the runtime-notice filter.
    expect(isRuntimeNoticeMessage(resumed)).toBe(false);
    expect(isSessionRecoveryResumedMessage(message({
      role: "assistant",
      content: "ordinary assistant output",
      metadata: { kind: "cli_agent_lifecycle" },
    }))).toBe(false);
    expect(isSessionRecoveryResumedMessage(message({
      role: "user",
      content: "not an assistant row",
      metadata: { kind: "session_recovery_resumed" },
    }))).toBe(false);
  });

  it("flags system-authored hot-restart resume user rows from metadata", () => {
    expect(isHotRestartResumeMessage(message({
      role: "user",
      content: "E2E-MOCK-SLOW-V1 重启自动恢复",
      metadata: { kind: "hot_restart_resume", recoveredTurnId: "turn-1" },
    }))).toBe(true);
    // The original (human-authored) row keeps the same text but no resume kind.
    expect(isHotRestartResumeMessage(message({
      role: "user",
      content: "E2E-MOCK-SLOW-V1 重启自动恢复",
      metadata: { kind: "journal_user_message" },
    }))).toBe(false);
    expect(isHotRestartResumeMessage(message({
      role: "assistant",
      content: "not a user row",
      metadata: { kind: "hot_restart_resume" },
    }))).toBe(false);
  });

  it("flags only interrupted partials that recovery superseded", () => {
    expect(isRecoverySupersededPartial(message({
      role: "assistant",
      content: "half-streamed answer",
      metadata: { interrupted: true, recoverySuperseded: true },
    }))).toBe(true);
    // Interrupted without supersession (recovery disabled or capped) stays visible.
    expect(isRecoverySupersededPartial(message({
      role: "assistant",
      content: "half-streamed answer",
      metadata: { interrupted: true },
    }))).toBe(false);
    expect(isRecoverySupersededPartial(message({
      role: "assistant",
      content: "half-streamed answer",
      metadata: { recoverySuperseded: true },
    }))).toBe(false);
    expect(isRecoverySupersededPartial(message({
      role: "user",
      content: "never a partial",
      metadata: { interrupted: true, recoverySuperseded: true },
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

  it("tolerates non-string research organization metadata without crashing", () => {
    const chips = researchOrgMessageChips(message({
      role: "user",
      content: "[Agent 私信]",
      metadata: {
        kind: "agent_inbox_message",
        inboxKind: "research_org_report",
        researchOrgIntent: undefined,
        researchOrgMessageType: 123,
        researchOrgDeliveryMode: null,
        wakeStatus: { unexpected: true },
      },
    }));
    expect(chips).toEqual([]);
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
