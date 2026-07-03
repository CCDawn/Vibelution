import { describe, expect, it } from "vitest";

import chatCodingRouteSource from "../../routes/ChatCodingRoute.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";

describe("conversation view public type boundary", () => {
  it("keeps route-level types out of the heavy ConversationView module", () => {
    expect(chatCodingRouteSource).not.toContain('from "../components/conversation/ConversationView"');
    expect(chatCodingRouteSource).toContain('from "../components/conversation/conversationStreamingMetrics"');
    expect(chatCodingRouteSource).toContain('from "../components/conversation/conversationTurnAvatar"');
  });

  it("keeps streaming frame metrics in a public helper module", () => {
    expect(conversationViewSource).toContain('from "./conversationStreamingMetrics"');
    expect(conversationViewSource).not.toContain("export type ConversationStreamingFramePaintMetrics =");
  });
});
