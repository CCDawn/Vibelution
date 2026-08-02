import { describe, expect, it } from "vitest";

import type { ChatNextStateSignalSummary } from "../../api/types";
import chatCodingRouteSource from "../../routes/ChatCodingRoute.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import { shouldShowNextStateSignalInConversation } from "./conversationNextStateSignal";

function nextStateSignal(kind: ChatNextStateSignalSummary["kind"]): ChatNextStateSignalSummary {
  return {
    signalId: `signal-${kind}`,
    sessionId: "session-1",
    turnId: "turn-1",
    source: "user",
    kind,
    polarity: "neutral",
    mode: "directive",
    relatedEventCode: `conversation.${kind}`,
    createdAt: "2026-05-25T00:19:12Z",
    summary: kind,
  };
}

describe("shouldShowNextStateSignalInConversation", () => {
  it("shows user continue signals only while the conversation phase is busy", () => {
    const signal = nextStateSignal("user_continues");

    expect(shouldShowNextStateSignalInConversation(signal, "ready")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(signal, "completed")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(signal, "queued")).toBe(true);
    expect(shouldShowNextStateSignalInConversation(signal, " running ")).toBe(true);
    expect(shouldShowNextStateSignalInConversation(signal, "STOPPING")).toBe(true);
  });

  it("keeps non-continue signals visible after the turn finishes", () => {
    expect(shouldShowNextStateSignalInConversation(nextStateSignal("user_stops"), "ready")).toBe(true);
    expect(shouldShowNextStateSignalInConversation(nextStateSignal("tool_error"), "completed")).toBe(true);
  });

  it("hides a terminal tool error after the same tool succeeds later in the latest turn", () => {
    const signal = {
      ...nextStateSignal("tool_error"),
      summary: "Tool failed: challenge_cup_iteration_writeback_tool",
    };
    const messages = [
      {
        id: "user-1",
        role: "user" as const,
        content: "继续迭代",
        timestamp: "2026-08-02T01:55:00Z",
      },
      {
        id: "tool-failed",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:57:27Z",
        toolCalls: [{
          name: "challenge_cup_iteration_writeback_tool",
          status: "failed",
          semanticStatus: "failed",
        }],
      },
      {
        id: "tool-recovered",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:58:07Z",
        toolCalls: [{
          name: "challenge_cup_iteration_writeback_tool",
          status: "done",
          semanticStatus: "succeeded",
        }],
      },
      {
        id: "assistant-final",
        role: "assistant" as const,
        content: "已完成正式写回。",
        timestamp: "2026-08-02T01:58:28Z",
      },
    ];

    expect(shouldShowNextStateSignalInConversation(signal, "ready", messages)).toBe(false);
    expect(shouldShowNextStateSignalInConversation(signal, "running", messages)).toBe(true);
  });

  it("uses the canonical raw tool name returned by session detail", () => {
    const toolName = "challenge_cup_iteration_writeback_tool";
    const signal = {
      ...nextStateSignal("tool_error"),
      summary: `Tool failed: ${toolName}`,
    };
    const messages = [
      {
        id: "user-1",
        role: "user" as const,
        content: "继续迭代",
        timestamp: "2026-08-02T01:55:00Z",
      },
      {
        id: "assistant-canonical-tools",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:58:07Z",
        toolCalls: [
          {
            name: "",
            rawToolName: toolName,
            title: toolName,
            status: "failed",
            semanticStatus: "failed",
          },
          {
            name: "",
            rawToolName: toolName,
            title: toolName,
            status: "completed",
          },
        ],
      },
    ];

    expect(shouldShowNextStateSignalInConversation(signal, "ready", messages)).toBe(false);
  });

  it("keeps an unrecovered or differently recovered tool error visible", () => {
    const signal = {
      ...nextStateSignal("tool_error"),
      summary: "Tool failed: challenge_cup_iteration_writeback_tool",
    };
    const messages = [
      {
        id: "user-1",
        role: "user" as const,
        content: "继续迭代",
        timestamp: "2026-08-02T01:55:00Z",
      },
      {
        id: "tool-failed",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:57:27Z",
        toolCalls: [{
          name: "challenge_cup_iteration_writeback_tool",
          status: "failed",
          semanticStatus: "failed",
        }],
      },
      {
        id: "other-tool",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:58:07Z",
        toolCalls: [{
          name: "challenge_cup_iteration_context_tool",
          status: "done",
          semanticStatus: "succeeded",
        }],
      },
    ];

    expect(shouldShowNextStateSignalInConversation(signal, "ready", messages)).toBe(true);
  });

  it("keeps the signal visible when the newest same-tool terminal state failed again", () => {
    const signal = {
      ...nextStateSignal("tool_error"),
      summary: "Tool failed: challenge_cup_iteration_writeback_tool",
    };
    const messages = [
      {
        id: "user-1",
        role: "user" as const,
        content: "继续迭代",
        timestamp: "2026-08-02T01:55:00Z",
      },
      {
        id: "tool-failed",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:57:27Z",
        toolCalls: [{
          name: "challenge_cup_iteration_writeback_tool",
          status: "failed",
          semanticStatus: "failed",
        }],
      },
      {
        id: "tool-recovered",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:58:07Z",
        toolCalls: [{
          name: "challenge_cup_iteration_writeback_tool",
          status: "done",
          semanticStatus: "succeeded",
        }],
      },
      {
        id: "tool-failed-again",
        role: "assistant" as const,
        content: "",
        timestamp: "2026-08-02T01:58:20Z",
        toolCalls: [{
          name: "challenge_cup_iteration_writeback_tool",
          status: "failed",
          semanticStatus: "failed",
        }],
      },
    ];

    expect(shouldShowNextStateSignalInConversation(signal, "ready", messages)).toBe(true);
  });

  it("keeps next-state signal filtering out of ConversationView and route imports", () => {
    const routeConversationViewImportEnd = chatCodingRouteSource.indexOf(
      'from "../components/conversation/ConversationView";',
    );
    const routeConversationViewImportStart = routeConversationViewImportEnd >= 0
      ? chatCodingRouteSource.lastIndexOf("import {", routeConversationViewImportEnd)
      : -1;
    const routeConversationViewImport = routeConversationViewImportStart >= 0
      ? chatCodingRouteSource.slice(routeConversationViewImportStart, routeConversationViewImportEnd)
      : "";

    expect(conversationViewSource).toContain('from "./conversationNextStateSignal"');
    expect(conversationViewSource).not.toMatch(
      /function isBusyConversationPhase|export function shouldShowNextStateSignalInConversation/,
    );
    expect(chatCodingRouteSource).toContain('from "../components/conversation/conversationNextStateSignal"');
    expect(routeConversationViewImport).not.toContain("shouldShowNextStateSignalInConversation");
  });
});
