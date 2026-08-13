import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationActiveTurnStatusNote } from "./ConversationActiveTurnStatusNote";

describe("ConversationActiveTurnStatusNote canonical turn items", () => {
  it("derives the visible retry heartbeat from a retry item", () => {
    const html = renderToStaticMarkup(
      <ConversationActiveTurnStatusNote
        lang="zh"
        message={{
          timestamp: new Date().toISOString(),
          turnItems: [{
            id: "retry-1-r1",
            itemId: "retry-1",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-1",
            type: "retry",
            status: "running",
            revision: 1,
            sequence: 1,
            attempt: 2,
            targetItemId: "request-1",
            reason: "network_error",
          }],
        }}
      />,
    );

    expect(html).toContain("data-active-turn-stage=\"model_retry\"");
    expect(html).toContain("请求");
    expect(html).not.toContain("data-stage-phase");
    expect(html).not.toContain("stageDot");
  });
});
