import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread";
import {
  agentMessageContextSections,
  agentMessageContentSections,
  agentMessageProcessSections,
  buildAgentMessageSectionState,
} from "./agentMessageSections";
import agentMessageSectionsSource from "./agentMessageSections.ts?raw";

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "msg",
    role: "user",
    content: "",
    timestamp: "2026-05-20T14:12:39",
    ...overrides,
  };
}

function sectionState(message: ConversationMessage) {
  return buildAgentMessageSectionState(conversationMessageToAgentMessage(message));
}

describe("agentMessageSections", () => {
  it("does not export retired ConversationMessage content or block helpers", () => {
    expect(agentMessageSectionsSource).not.toMatch(/export function (?:hasUserContent|has(?:Response|Thought|Mental|Tool)Block)\b/);
  });

  it("builds AgentMessage section state from legacy assistant fields", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "我会整理下一步。",
      thought: "先确认 section selector",
      mentalSnapshot: {
        mood: "focused",
        feeling: "",
        whisper: "",
        summary: "",
        cognitiveState: "productive",
        confidence: 0.8,
        sampleSize: 1,
        interventionCount: 0,
        updatedAt: "2026-07-02T10:20:00Z",
        source: "test",
      },
      toolCalls: [{ name: "read_file_tool", status: "done", summary: "读取 agentMessageSections" }],
    });

    const state = buildAgentMessageSectionState(conversationMessageToAgentMessage(assistantMessage));

    expect(state).toMatchObject({
      answerText: "我会整理下一步。",
      hasResponseBlock: true,
      hasThoughtBlock: true,
      hasMentalBlock: true,
      hasToolBlock: true,
      hasFeedbackTimeline: false,
      hasUserContent: false,
    });
  });

  it("derives AgentMessage section state from process, content, and context sections", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "我会整理下一步。",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "done",
          name: "read_file_tool",
          summary: "读取 ConversationView",
        },
      ],
      references: [
        {
          kind: "session",
          sessionId: "session-ref",
          title: "历史会话",
        },
      ],
    });

    const state = buildAgentMessageSectionState(conversationMessageToAgentMessage(assistantMessage));

    expect(state).toMatchObject({
      sectionCount: 3,
      sectionKinds: ["process", "content", "context"],
      hasProcessSection: true,
      hasContentSection: true,
      hasContextSection: true,
      hasResponseBlock: true,
      hasFeedbackTimeline: true,
      hasToolBlock: true,
    });
  });

  it("selects AgentMessage context sections without flattening attachments or references", () => {
    const userMessage = message({
      id: "user-context",
      role: "user",
      content: "继续看这个上下文",
      attachments: [
        {
          artifactId: "context-image.png",
          filename: "context.png",
          imageUrl: "/api/sessions/session-1/artifacts/context-image.png",
          contentType: "image/png",
          kind: "user_image",
          status: "ready",
        },
      ],
      references: [
        {
          kind: "session",
          referenceId: "session:context-ref",
          sessionId: "context-ref",
          title: "旧会话摘录",
        },
      ],
    });

    const sections = agentMessageContextSections(conversationMessageToAgentMessage(userMessage));

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      id: "user-context-section-context-1",
      kind: "context",
    });
    expect(sections[0].parts.map((part) => part.type)).toEqual(["attachment", "reference"]);
  });

  it("selects AgentMessage content sections without mixing in context parts", () => {
    const userMessage = message({
      id: "user-content",
      role: "user",
      content: "继续看这个正文",
      attachments: [
        {
          artifactId: "content-image.png",
          filename: "content.png",
          imageUrl: "/api/sessions/session-1/artifacts/content-image.png",
          contentType: "image/png",
          kind: "user_image",
          status: "ready",
        },
      ],
    });

    const sections = agentMessageContentSections(conversationMessageToAgentMessage(userMessage));

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      id: "user-content-section-content-0",
      kind: "content",
    });
    expect(sections[0].parts.map((part) => part.type)).toEqual(["text"]);
    expect(sections[0].parts.map((part) => part.channel)).toEqual(["user"]);
  });

  it("selects AgentMessage process sections without mixing in content or context parts", () => {
    const assistantMessage = message({
      id: "assistant-process",
      role: "assistant",
      content: "最终回答",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "done",
          summary: "先检查 process section",
          resultPreview: "先检查 process section",
        },
        {
          sequence: 2,
          kind: "tool",
          status: "done",
          name: "read_file_tool",
          summary: "读取 ConversationView",
        },
      ],
      references: [
        {
          kind: "session",
          referenceId: "session:process-ref",
          sessionId: "process-ref",
          title: "过程引用",
        },
      ],
    });

    const sections = agentMessageProcessSections(conversationMessageToAgentMessage(assistantMessage));

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      id: "assistant-process-section-process-0",
      kind: "process",
    });
    expect(sections[0].parts.map((part) => part.type)).toEqual(["thought", "tool-call"]);
  });

  it("builds AgentMessage section state without exposing runtime status placeholders as answers", () => {
    const statusMessage = message({
      role: "assistant",
      content: "正在思考，已收到思考片段...\n模型已经开始返回 reasoning，正文可能稍后出现。",
      streaming: true,
      streamStage: "model_thinking",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status",
          status: "running",
          name: "model_request",
          summary: "正在请求模型",
        },
      ],
    });

    const state = buildAgentMessageSectionState(conversationMessageToAgentMessage(statusMessage));

    expect(state).toMatchObject({
      hasResponseBlock: false,
      hasFeedbackTimeline: false,
      hasThoughtBlock: false,
      hasToolBlock: false,
    });
  });

  it("builds AgentMessage section state for feedback tool timelines with answers", () => {
    const feedbackMessage = message({
      role: "assistant",
      content: "已完成搜索。",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "done",
          name: "grep_search_tool",
          summary: "搜索 selector",
        },
      ],
    });

    const state = buildAgentMessageSectionState(conversationMessageToAgentMessage(feedbackMessage));

    expect(state).toMatchObject({
      answerText: "已完成搜索。",
      hasResponseBlock: true,
      hasFeedbackTimeline: true,
      hasToolBlock: true,
    });
  });

  it("shows operator text as direct message content", () => {
    const userMessage = message({
      role: "user",
      content: "你知道你上文说了什么吗",
    });
    const state = sectionState(userMessage);

    expect(state.hasUserContent).toBe(true);
    expect(state.hasResponseBlock).toBe(false);
  });

  it("keeps assistant content in the response block", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "我会先检查日志。",
    });
    const state = sectionState(assistantMessage);

    expect(state.hasUserContent).toBe(false);
    expect(state.hasResponseBlock).toBe(true);
  });

  it.each([
    "上一轮运行已被中断，当前会话已恢复为可继续状态。",
    "The previous turn was interrupted. This session is ready to continue.",
  ])("keeps runtime notice out of assistant response blocks: %s", (content) => {
    const noticeMessage = message({
      role: "assistant",
      content,
    });

    expect(sectionState(noticeMessage).hasResponseBlock).toBe(false);
  });

  it("keeps transient reasoning placeholders out of assistant response blocks", () => {
    const statusMessage = message({
      role: "assistant",
      content: "正在思考，已收到思考片段...\n模型已经开始返回 reasoning，正文可能稍后出现。",
      streaming: true,
      streamStage: "model_thinking",
    });

    expect(sectionState(statusMessage).hasResponseBlock).toBe(false);
  });

  it("keeps normal assistant replies that mention thinking visible", () => {
    const assistantMessage = message({
      role: "assistant",
      content: "我正在思考这个排版问题，结论是需要把状态移到过程区。",
      streaming: true,
      streamStage: "responding",
    });

    expect(sectionState(assistantMessage).hasResponseBlock).toBe(true);
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

    expect(sectionState({ ...errorMessage, thought: "hidden" }).hasThoughtBlock).toBe(true);
    expect(sectionState({ ...errorMessage, toolCalls: [{ name: "tool", status: "done" }] }).hasToolBlock).toBe(true);
    expect(sectionState(errorMessage).hasResponseBlock).toBe(false);
  });

  it("keeps legacy provider failure summary replies out of assistant response blocks", () => {
    const errorMessage = message({
      role: "assistant",
      content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
      thought: "The generation failed with a 502 upstream error.",
      toolCalls: [{ name: "image2_generate_tool", status: "done" }],
    });

    const state = sectionState(errorMessage);
    expect(state.hasThoughtBlock).toBe(true);
    expect(state.hasToolBlock).toBe(true);
    expect(state.hasResponseBlock).toBe(false);
  });

  it("keeps failed image-generation artifact messages out of assistant response blocks", () => {
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

    const state = sectionState(errorMessage);
    expect(state.hasToolBlock).toBe(true);
    expect(state.hasResponseBlock).toBe(false);
  });

  it("keeps group room transcript sync out of assistant response blocks", () => {
    const transcript = message({
      role: "assistant",
      content: "[群聊同步]\n群聊: 科研团队 团队群聊\n\n你的发言:\n- 已完成。",
      metadata: { kind: "group_room_transcript" },
    });

    expect(sectionState(transcript).hasResponseBlock).toBe(false);
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

    const state = sectionState(userMessage);
    expect(state.hasThoughtBlock).toBe(false);
    expect(state.hasMentalBlock).toBe(false);
    expect(state.hasToolBlock).toBe(false);
  });

});
