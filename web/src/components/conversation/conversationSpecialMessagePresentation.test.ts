import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  agentInboxSourceLabel,
  agentInboxSummary,
  cliAgentLifecycleDetail,
  cliAgentLifecycleLabel,
  groupRoomTranscriptLabel,
} from "./conversationSpecialMessagePresentation";

const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");
const timelineProcessProjectionSource = readFileSync(
  new URL("./timelineMessageProcessProjection.ts", import.meta.url),
  "utf8",
);

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "msg",
    role: "assistant",
    content: "",
    timestamp: "2026-07-03T22:52:00Z",
    ...overrides,
  };
}

describe("conversation special message presentation", () => {
  it("keeps special-message helpers outside ConversationView", () => {
    expect(conversationViewSource).toContain("./conversationSpecialMessagePresentation");
    expect(conversationViewSource).not.toContain("function cliAgentLifecycleLabel");
    expect(conversationViewSource).not.toContain("function cliAgentLifecycleDetail");
    expect(conversationViewSource).not.toContain("function agentInboxSourceLabel");
    expect(conversationViewSource).not.toContain("function agentInboxSummary");
    expect(conversationViewSource).not.toContain("function groupRoomTranscriptLabel");
    expect(conversationViewSource).not.toContain("function metadataText");
    expect(timelineProcessProjectionSource).not.toContain("function isCliAgentLifecycleMessage");
  });

  it("builds localized CLI lifecycle labels and details", () => {
    const closed = message({
      content: "fallback detail",
      metadata: {
        kind: "cli_agent_lifecycle",
        event: "closed",
        label: "Codex CLI",
        cliRunId: "cli-run-001",
      },
    });
    const running = message({
      content: "terminal session fallback",
      metadata: {
        kind: "cli_agent_lifecycle",
        status: "running",
        adapterId: "claude",
        terminalSessionId: 42,
      },
    });

    expect(cliAgentLifecycleLabel(closed, "zh")).toBe("终端已关闭 · Codex CLI");
    expect(cliAgentLifecycleLabel(closed, "en")).toBe("Terminal closed · Codex CLI");
    expect(cliAgentLifecycleDetail(closed)).toBe("cli-run-001");
    expect(cliAgentLifecycleLabel(running, "zh")).toBe("终端状态 · claude");
    expect(cliAgentLifecycleDetail(running)).toBe("42");
  });

  it("builds Agent inbox labels and summaries from metadata or content", () => {
    const metadataMessage = message({
      role: "user",
      content: "[Agent 私信]\n来源 Agent: A011 · 夏予安\n\n消息内容:\n请从组织设计角度回复。",
      metadata: {
        kind: "agent_inbox_message",
        sourceAgentCode: "A014",
        sourceAgentName: "能力管家",
        summary: "权限审查已完成。",
      },
    });
    const contentMessage = message({
      role: "user",
      content: "[Agent 私信]\n来源 Agent: A011 · 夏予安\n\n摘要:\n需要你接手组织设计。\n\n消息内容:\n请从组织设计角度回复。",
    });
    const bodyMessage = message({
      role: "user",
      content: "[Agent 私信]\n来源 Agent: A011 · 夏予安\n\n消息内容:\n权限审查已完成。",
    });

    expect(agentInboxSourceLabel(metadataMessage)).toBe("Agent 私信 · A014 · 能力管家");
    expect(agentInboxSummary(metadataMessage)).toBe("权限审查已完成。");
    expect(agentInboxSourceLabel(contentMessage)).toBe("Agent 私信 · A011 · 夏予安");
    expect(agentInboxSummary(contentMessage)).toBe("需要你接手组织设计。");
    expect(agentInboxSummary(bodyMessage)).toBe("权限审查已完成。");
  });

  it("builds group room transcript labels from source room metadata", () => {
    expect(groupRoomTranscriptLabel(message({
      content: "[群聊同步]",
      metadata: {
        kind: "group_room_transcript",
        sourceRoomTitle: "科研团队 团队群聊",
      },
    }))).toBe("群聊同步记录 · 科研团队 团队群聊");
    expect(groupRoomTranscriptLabel(message({
      content: "[群聊同步]",
      metadata: { kind: "group_room_transcript" },
    }))).toBe("群聊同步记录");
  });
});
