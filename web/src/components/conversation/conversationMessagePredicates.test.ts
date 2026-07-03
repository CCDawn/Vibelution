import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  imageArtifactForMessage,
  isAgentInboxMessage,
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

describe("conversationMessagePredicates", () => {
  it.each([
    "上一轮运行已被中断，当前会话已恢复为可继续状态。",
    "The previous turn was interrupted. This session is ready to continue.",
  ])("classifies assistant runtime notices: %s", (content) => {
    expect(isRuntimeNoticeMessage(message({ role: "assistant", content }))).toBe(true);
    expect(isRuntimeNoticeMessage(message({ role: "user", content }))).toBe(false);
  });

  it("classifies transient reasoning placeholders without hiding normal replies", () => {
    expect(isRuntimeStatusContent(message({
      role: "assistant",
      content: "正在思考，已收到思考片段...\n模型已经开始返回 reasoning，正文可能稍后出现。",
      streaming: true,
      streamStage: "model_thinking",
    }))).toBe(true);
    expect(isRuntimeStatusContent(message({
      role: "assistant",
      content: "我正在思考这个排版问题，结论是需要把状态移到过程区。",
      streaming: true,
      streamStage: "responding",
    }))).toBe(false);
  });

  it("classifies provider failure and failed image generation messages as turn errors", () => {
    const providerError = message({
      role: "assistant",
      content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
    });
    const imageError = message({
      role: "assistant",
      content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
      metadata: {
        kind: "image2_generation",
        status: "failed",
        errorType: "RuntimeError",
      },
    });

    expect(isProviderFailureSummaryText(providerError.content)).toBe(true);
    expect(isTurnErrorMessage(providerError)).toBe(true);
    expect(isTurnErrorMessage(imageError)).toBe(true);
  });

  it("classifies Agent inbox and group transcript messages", () => {
    expect(isAgentInboxMessage(message({
      role: "user",
      content: "普通用户输入",
    }))).toBe(false);
    expect(isAgentInboxMessage(message({
      role: "user",
      content: "普通内容",
      metadata: { kind: "agent_inbox_message" },
    }))).toBe(true);
    expect(isAgentInboxMessage(message({
      role: "user",
      content: "[Agent 私信]\n来源 Agent: A011 · 夏予安",
    }))).toBe(true);
    expect(isGroupRoomTranscriptMessage(message({
      role: "assistant",
      content: "[群聊同步]\n群聊: 科研团队 团队群聊",
    }))).toBe(true);
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
