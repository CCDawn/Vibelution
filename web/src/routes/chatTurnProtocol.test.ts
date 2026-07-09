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
