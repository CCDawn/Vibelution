import { describe, expect, it } from "vitest";

import chatApiTypesSource from "../../api/types/chat.ts?raw";
import chatCodingRouteSource from "../../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import conversationStreamingMetricsSource from "./conversationStreamingMetrics.ts?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import conversationViewTypesSource from "./conversationViewTypes.ts?raw";
import lazyConversationViewSource from "./LazyConversationView.tsx?raw";

describe("conversation view public type boundary", () => {
  it("keeps assistant messages on the canonical turnItems envelope", () => {
    const assistantTurn = chatApiTypesSource.match(
      /export type AssistantConversationTurn = ConversationMessageBase & \{([\s\S]*?)\n\};/,
    )?.[1];

    expect(assistantTurn).toBeTruthy();
    expect(assistantTurn).toContain('role: "assistant";');
    expect(assistantTurn).toContain("turnId: string;");
    expect(assistantTurn).toContain("status: SessionTurnItemStatus;");
    expect(assistantTurn).toContain("turnItems: SessionTurnItem[];");
    for (const retiredField of [
      "content:",
      "thought:",
      "streaming:",
      "streamStage:",
      "toolCalls:",
      "feedbackEvents:",
      "timelineItems:",
      "codexTranscript:",
    ]) {
      expect(assistantTurn).not.toContain(retiredField);
    }
  });

  it("keeps streaming frame metrics in a public helper module", () => {
    expect(conversationViewTypesSource).toContain('from "./conversationStreamingMetrics"');
    expect(conversationViewSource).not.toContain("export type ConversationStreamingFramePaintMetrics =");
    expect(conversationStreamingMetricsSource).toContain("paintedAtMs: number;");
    expect(conversationStreamingMetricsSource).toContain("renderedTextLength: number;");
    expect(conversationStreamingMetricsSource).toContain("streamingMessageCount: number;");
  });

  it("keeps the lazy wrapper on the lightweight public prop boundary", () => {
    expect(lazyConversationViewSource).toContain('from "./conversationViewTypes"');
    expect(lazyConversationViewSource).not.toContain('from "./ConversationView"');
  });

  it("keeps public view prop and mode types out of the heavy component module", () => {
    expect(conversationViewSource).toContain('from "./conversationViewTypes"');
    expect(conversationViewSource).not.toContain("export type ConversationProcessDisplayMode");
    expect(conversationViewSource).not.toContain("export type ConversationViewProps");
  });
});
