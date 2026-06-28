import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import {
  hasMentalBlock,
  hasResponseBlock,
  hasThoughtBlock,
  hasToolBlock,
  hasUserContent,
  imageArtifactForMessage,
  isAgentInboxMessage,
  isGroupRoomTranscriptMessage,
  isProviderFailureSummaryText,
  isRuntimeNoticeMessage,
  isRuntimeStatusContent,
  isTurnErrorMessage,
  researchOrgMessageChips,
} from "./messageSections";

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "msg",
    role: "user",
    content: "",
    timestamp: "2026-05-20T14:12:39",
    ...overrides,
  };
}

describe("messageSections", () => {
  it("shows operator text as direct message content", () => {
    const userMessage = message({
      role: "user",
      content: "你知道你上文说了什么吗",
    });

    expect(hasUserContent(userMessage)).toBe(true);
    expect(hasResponseBlock(userMessage)).toBe(false);
  });

  it("keeps assistant content in the response block", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "我会先检查日志。",
    });

    expect(hasUserContent(assistantMessage)).toBe(false);
    expect(hasResponseBlock(assistantMessage)).toBe(true);
  });

  it.each([
    "上一轮运行已被中断，当前会话已恢复为可继续状态。",
    "The previous turn was interrupted. This session is ready to continue.",
  ])("keeps runtime notice out of assistant response blocks: %s", (content) => {
    const noticeMessage = message({
      role: "assistant",
      content,
    });

    expect(isRuntimeNoticeMessage(noticeMessage)).toBe(true);
    expect(hasResponseBlock(noticeMessage)).toBe(false);
  });

  it("keeps transient reasoning placeholders out of assistant response blocks", () => {
    const statusMessage = message({
      role: "assistant",
      content: "正在思考，已收到思考片段...\n模型已经开始返回 reasoning，正文可能稍后出现。",
      streaming: true,
      streamStage: "model_thinking",
    });

    expect(isRuntimeStatusContent(statusMessage)).toBe(true);
    expect(hasResponseBlock(statusMessage)).toBe(false);
  });

  it("keeps normal assistant replies that mention thinking visible", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "我正在思考这个排版问题，结论是需要把状态移到过程区。",
      streaming: true,
      streamStage: "responding",
    });

    expect(isRuntimeStatusContent(assistantMessage)).toBe(false);
    expect(hasResponseBlock(assistantMessage)).toBe(true);
  });

  it.each([
    "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
    "The model provider failed upstream, so this turn did not complete. The full provider error was written to runtime logs.",
  ])("keeps provider failure summaries out of assistant response blocks: %s", (content) => {
    const errorMessage = message({
      role: "assistant",
      content,
      metadata: { kind: "turn_error", providerFailure: true },
    });

    expect(isRuntimeNoticeMessage(errorMessage)).toBe(false);
    expect(isTurnErrorMessage(errorMessage)).toBe(true);
    expect(hasThoughtBlock({ ...errorMessage, thought: "hidden" })).toBe(true);
    expect(hasToolBlock({ ...errorMessage, toolCalls: [{ name: "tool", status: "done" }] })).toBe(true);
    expect(hasResponseBlock(errorMessage)).toBe(false);
  });

  it("treats legacy provider failure summary replies as turn-error notices", () => {
    const errorMessage = message({
      role: "assistant",
      content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
      thought: "The generation failed with a 502 upstream error.",
      toolCalls: [{ name: "image2_generate_tool", status: "done" }],
    });

    expect(isProviderFailureSummaryText(errorMessage.content)).toBe(true);
    expect(isTurnErrorMessage(errorMessage)).toBe(true);
    expect(hasThoughtBlock(errorMessage)).toBe(true);
    expect(hasToolBlock(errorMessage)).toBe(true);
    expect(hasResponseBlock(errorMessage)).toBe(false);
  });

  it("treats failed image-generation artifact messages as turn-error notices", () => {
    const errorMessage = message({
      role: "assistant",
      content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
      metadata: {
        kind: "image2_generation",
        status: "failed",
        errorType: "RuntimeError",
      },
      toolCalls: [{ name: "image2_generate_tool", status: "done" }],
    });

    expect(isTurnErrorMessage(errorMessage)).toBe(true);
    expect(hasToolBlock(errorMessage)).toBe(true);
    expect(hasResponseBlock(errorMessage)).toBe(false);
  });

  it("does not classify user text as a runtime notice", () => {
    const userMessage = message({
      role: "user",
      content: "上一轮运行已被中断，当前会话已恢复为可继续状态。",
    });

    expect(isRuntimeNoticeMessage(userMessage)).toBe(false);
  });

  it("classifies Agent inbox wake prompts separately from operator-authored user text", () => {
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
  });

  it("does not add research organization chips to ordinary private messages", () => {
    expect(researchOrgMessageChips(message({
      role: "user",
      content: "[Agent 私信]",
      metadata: {
        kind: "agent_inbox_message",
        inboxKind: "agent_direct_message",
      },
    }))).toEqual([]);
  });

  it("keeps group room transcript sync out of assistant response blocks", () => {
    const transcript = message({
      role: "assistant",
      content: "[群聊同步]\n群聊: 科研团队 团队群聊\n\n你的发言:\n- 已完成。",
      metadata: { kind: "group_room_transcript" },
    });

    expect(isGroupRoomTranscriptMessage(transcript)).toBe(true);
    expect(hasResponseBlock(transcript)).toBe(false);
  });

  it("keeps assistant-only diagnostic sections scoped away from operator messages", () => {
    const userMessage = message({
      role: "user",
      content: "继续",
      thought: "hidden",
      mentalSnapshot: {
        mood: "open",
        feeling: "",
        whisper: "",
        summary: "",
        cognitiveState: "",
        confidence: 0,
        sampleSize: 0,
        interventionCount: 0,
        updatedAt: "",
        source: "",
      },
      toolCalls: [{ name: "rg", status: "completed" }],
    });

    expect(hasThoughtBlock(userMessage)).toBe(false);
    expect(hasMentalBlock(userMessage)).toBe(false);
    expect(hasToolBlock(userMessage)).toBe(false);
  });

  it("extracts image artifact metadata into a typed section contract", () => {
    const assistantMessage = message({
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
    });

    expect(imageArtifactForMessage(assistantMessage)).toEqual({
      imageUrl: "/api/sessions/session-a/artifacts/image.png",
      downloadUrl: "/api/sessions/session-a/artifacts/image.png?download=1",
      prompt: "AI poster",
      artifactId: "image.png",
      size: "1024x1536",
      quality: "high",
      model: "gpt-image-1.5",
    });
  });

  it("ignores unfinished image artifact metadata", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "生成中",
      metadata: {
        kind: "image2_generation",
        status: "running",
        imageUrl: "/api/sessions/session-a/artifacts/image.png",
      },
    });

    expect(imageArtifactForMessage(assistantMessage)).toBeNull();
  });
});
