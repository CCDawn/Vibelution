import { describe, expect, it } from "vitest";

import type { CodexTranscriptProjection, ConversationMessage } from "../api/types";
import {
  activeTurnProtocolTextLength,
  hasCommittedAssistantProtocolAnswer,
  hasVisibleActiveTurnProtocolContent,
  resolveAssistantTurnRenderProtocol,
  visibleNativeAssistantMarkdownText,
} from "./chatTurnProtocol";

function nativeTranscript(cells: CodexTranscriptProjection["cells"]): CodexTranscriptProjection {
  return {
    version: 1,
    source: "native",
    messageId: "message-native",
    cells,
  };
}

describe("chat turn protocol", () => {
  it("treats native assistant markdown as the answer protocol when legacy text is empty", () => {
    const transcript = nativeTranscript([
      {
        id: "native-answer",
        kind: "assistant_markdown",
        messageId: "message-native",
        status: "completed",
        tone: "neutral",
        text: "native 协议里的最终回答",
      },
    ]);

    expect(resolveAssistantTurnRenderProtocol({ answerContent: "", thoughtContent: "", codexTranscript: transcript }))
      .toBe("native_codex_transcript");
    expect(visibleNativeAssistantMarkdownText(transcript)).toBe("native 协议里的最终回答");
    expect(activeTurnProtocolTextLength({ answerContent: "", thoughtContent: "", codexTranscript: transcript }))
      .toBe("native 协议里的最终回答".length);
    expect(hasVisibleActiveTurnProtocolContent({
      answerContent: "",
      thoughtContent: "",
      feedbackEventCount: 0,
      codexTranscript: transcript,
    })).toBe(true);
  });

  it("filters internal native status markdown out of answer visibility", () => {
    const transcript = nativeTranscript([
      {
        id: "native-status",
        kind: "assistant_markdown",
        messageId: "message-native",
        status: "completed",
        tone: "neutral",
        text: "正在请求模型，等待首个响应片段...",
      },
    ]);

    expect(visibleNativeAssistantMarkdownText(transcript)).toBe("");
    expect(activeTurnProtocolTextLength({ answerContent: "", thoughtContent: "", codexTranscript: transcript }))
      .toBe(0);
    expect(hasVisibleActiveTurnProtocolContent({
      answerContent: "",
      thoughtContent: "",
      feedbackEventCount: 0,
      codexTranscript: transcript,
    })).toBe(false);
  });

  it("recognizes committed native assistant markdown as an assistant answer", () => {
    const message = {
      id: "assistant-final",
      role: "assistant",
      content: "",
      timestamp: "2026-07-09T08:00:00Z",
      codexTranscript: nativeTranscript([
        {
          id: "native-answer",
          kind: "assistant_markdown",
          messageId: "assistant-final",
          status: "completed",
          tone: "neutral",
          text: "正式 native 回答",
        },
      ]),
    } satisfies ConversationMessage;

    expect(hasCommittedAssistantProtocolAnswer(message)).toBe(true);
  });

  it("does not treat process-only native transcript cells as a committed answer", () => {
    const message = {
      id: "assistant-process",
      role: "assistant",
      content: "",
      timestamp: "2026-07-09T08:00:00Z",
      codexTranscript: nativeTranscript([
        {
          id: "native-tool",
          kind: "tool_call",
          messageId: "assistant-process",
          status: "completed",
          tone: "neutral",
          title: "npm build",
          summary: "构建完成",
        },
      ]),
    } satisfies ConversationMessage;

    expect(resolveAssistantTurnRenderProtocol({ answerContent: "", thoughtContent: "", codexTranscript: message.codexTranscript }))
      .toBe("native_codex_transcript");
    expect(hasCommittedAssistantProtocolAnswer(message)).toBe(false);
  });
});
import * as canonicalTurnProtocol from "./chatTurnProtocol";

describe("canonical SessionTurnItem v2 rendering", () => {
  const baseItem = {
    version: 2,
    sessionId: "session-v2",
    turnId: "turn-v2",
    invocationId: "invocation-v2",
    iteration: 0,
    status: "completed",
    sequence: 1,
    protocol: "responses",
  } as const;

  it("replaces a provisional item with the highest revision for the same canonical identity", () => {
    const items = canonicalTurnProtocol.consolidateSessionTurnItemsV2([
      {
        ...baseItem,
        id: "legacy-revision-0",
        itemId: "assistant-answer",
        revision: 0,
        kind: "assistant_message",
        channel: "answer",
        phase: "final_answer",
        provisional: true,
        terminal: false,
        type: "assistant_message",
        text: "draft answer",
      },
      {
        ...baseItem,
        id: "legacy-revision-1",
        itemId: "assistant-answer",
        revision: 1,
        sequence: 2,
        kind: "assistant_message",
        channel: "answer",
        phase: "final_answer",
        provisional: false,
        terminal: true,
        type: "assistant_message",
        text: "final answer",
      },
    ]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ revision: 1, text: "final answer", terminal: true });
  });

  it("keeps a provisional interrupted draft visible without treating it as committed", () => {
    const draft = {
      id: "draft-r0",
      role: "assistant",
      content: "legacy duplicate",
      timestamp: "2026-07-11T00:00:00.000Z",
      turnItems: [{
        ...baseItem,
        id: "draft-item-r0",
        itemId: "draft-item",
        revision: 0,
        kind: "assistant_message",
        channel: "answer",
        phase: "final_answer",
        type: "assistant_message",
        status: "running",
        provisional: true,
        terminal: false,
        text: "interrupted draft",
      }],
    } as never;

    expect(canonicalTurnProtocol.projectConversationMessageFromTurnItemsV2(draft).content).toBe("interrupted draft");
    expect(canonicalTurnProtocol.hasCommittedAssistantProtocolAnswer(draft)).toBe(false);
  });

  it("makes canonical v2 items authoritative over conflicting legacy projections", () => {
    const surface = canonicalTurnProtocol.resolveAssistantTurnRenderSurface({
      answerProjectionContent: "legacy duplicated answer",
      thoughtContent: "legacy thought",
      feedbackEvents: [],
      codexTranscript: {
        version: 1,
        source: "native",
        cells: [{ id: "legacy-cell", kind: "assistant_markdown", markdown: "legacy transcript answer" }],
      },
      turnItems: [
        {
          ...baseItem,
          id: "canonical-answer-r1",
          itemId: "canonical-answer",
          revision: 1,
          kind: "assistant_message",
          channel: "answer",
          phase: "final_answer",
          provisional: false,
          terminal: true,
          type: "assistant_message",
          text: "canonical final answer",
        },
      ],
    });

    expect(surface.protocol).toBe("canonical_turn_items_v2");
    expect(surface.answerContent).toBe("canonical final answer");
    expect(surface.codexTranscript?.cells).toHaveLength(1);
    expect(surface.codexTranscript?.cells[0]).toMatchObject({
      kind: "assistant_markdown",
      text: "canonical final answer",
    });
  });

  it("keeps reasoning, commentary, tool calls, and the final answer in separate cells", () => {
    const projected = canonicalTurnProtocol.projectConversationMessageFromTurnItemsV2({
      id: "message-v2",
      role: "assistant",
      content: "legacy answer",
      timestamp: "2026-07-11T00:00:00.000Z",
      turnItems: [
        {
          ...baseItem,
          id: "reasoning-r0",
          itemId: "reasoning",
          revision: 0,
          sequence: 1,
          kind: "reasoning",
          channel: "analysis",
          phase: "reasoning",
          type: "reasoning",
          text: "private reasoning summary",
        },
        {
          ...baseItem,
          id: "commentary-r0",
          itemId: "commentary",
          revision: 0,
          sequence: 2,
          kind: "assistant_message",
          channel: "commentary",
          phase: "commentary",
          type: "assistant_message",
          text: "I will inspect the file.",
        },
        {
          ...baseItem,
          id: "tool-r0",
          itemId: "tool-call",
          revision: 0,
          sequence: 3,
          kind: "tool_call",
          channel: "tool",
          phase: "tool_call",
          type: "tool_call",
          callId: "call-1",
          toolName: "read_file",
          text: "VERSION",
        },
        {
          ...baseItem,
          id: "answer-r0",
          itemId: "answer",
          revision: 0,
          sequence: 4,
          kind: "assistant_message",
          channel: "answer",
          phase: "final_answer",
          type: "assistant_message",
          terminal: true,
          text: "1.2.3",
        },
      ],
    } as never);

    expect(projected.content).toBe("1.2.3");
    expect(projected.codexTranscript?.cells.map((cell) => cell.kind)).toEqual([
      "reasoning_summary",
      "assistant_markdown",
      "tool_call",
      "assistant_markdown",
    ]);
    expect(projected.codexTranscript?.cells[1]).toMatchObject({
      kind: "assistant_markdown",
      channel: "commentary",
      phase: "commentary",
      text: "I will inspect the file.",
    });
    expect(projected.codexTranscript?.cells[2]).toMatchObject({
      kind: "tool_call",
      channel: "tool",
      phase: "tool_call",
      text: "VERSION",
    });
    expect(projected.codexTranscript?.cells[3]).toMatchObject({
      kind: "assistant_markdown",
      channel: "answer",
      phase: "final_answer",
      terminal: true,
      text: "1.2.3",
    });
    expect(JSON.stringify(projected.codexTranscript)).not.toContain('"markdown"');
  });

  it("keeps terminal errors visible without promoting them to final answer content", () => {
    const projected = canonicalTurnProtocol.projectConversationMessageFromTurnItemsV2({
      id: "message-error-v2",
      role: "assistant",
      content: "legacy fallback must not survive",
      timestamp: "2026-07-13T00:00:00.000Z",
      turnItems: [{
        ...baseItem,
        id: "error-r0",
        itemId: "error",
        revision: 0,
        kind: "error",
        channel: "answer",
        phase: "final_answer",
        type: "error",
        status: "failed",
        provisional: false,
        terminal: true,
        text: "Provider request failed",
        diagnosticSummary: { code: "provider_error" },
      }],
    } as never);

    expect(projected.content).toBe("");
    expect(projected.codexTranscript?.cells).toEqual([
      expect.objectContaining({
        kind: "error_notice",
        text: "Provider request failed",
        tone: "error",
        terminal: true,
        provisional: false,
        diagnosticSummary: { code: "provider_error" },
      }),
    ]);
    expect(canonicalTurnProtocol.hasTerminalCanonicalTurnOutcome(projected)).toBe(true);
  });
});
