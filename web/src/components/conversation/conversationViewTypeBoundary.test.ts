import { describe, expect, it } from "vitest";

import chatCodingRouteSource from "../../routes/ChatCodingRoute.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import conversationViewTypesSource from "./conversationViewTypes.ts?raw";
import lazyConversationViewSource from "./LazyConversationView.tsx?raw";

describe("conversation view public type boundary", () => {
  it("keeps route-level types out of the heavy ConversationView module", () => {
    expect(chatCodingRouteSource).not.toContain('from "../components/conversation/ConversationView"');
    expect(chatCodingRouteSource).toContain('from "../components/conversation/conversationStreamingMetrics"');
    expect(chatCodingRouteSource).toContain('from "../components/conversation/conversationTurnAvatar"');
  });

  it("keeps streaming frame metrics in a public helper module", () => {
    expect(conversationViewTypesSource).toContain('from "./conversationStreamingMetrics"');
    expect(conversationViewSource).not.toContain("export type ConversationStreamingFramePaintMetrics =");
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
