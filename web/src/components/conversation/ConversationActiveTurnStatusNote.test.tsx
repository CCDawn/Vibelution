import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationActiveTurnStatusNote } from "./ConversationActiveTurnStatusNote";

describe("ConversationActiveTurnStatusNote", () => {
  it("renders thinking heartbeat and stage bar from stream stage", () => {
    const html = renderToStaticMarkup(
      <ConversationActiveTurnStatusNote
        message={{
          streamStage: "model_thinking",
          timestamp: "2026-08-02T12:00:00.000Z",
        }}
        lang="zh"
      />,
    );

    expect(html).toContain('data-active-turn-stage="model_thinking"');
    expect(html).toMatch(/思考中 · \d+s/);
    expect(html).toContain("发送");
    expect(html).toContain("准备");
    expect(html).toContain("请求");
    expect(html).toContain("思考");
    expect(html).toContain('data-stage-phase="thinking"');
    expect(html).toContain('data-stage-current="true"');
  });

  it("renders optimistic submit stage before server progress arrives", () => {
    const html = renderToStaticMarkup(
      <ConversationActiveTurnStatusNote
        message={{
          streamStage: "user_submit",
          timestamp: "2026-08-02T12:00:00.000Z",
          feedbackEvents: [
            { kind: "status", name: "user_submit", status: "running" },
          ],
        }}
        lang="zh"
      />,
    );

    expect(html).toContain('data-active-turn-stage="user_submit"');
    expect(html).toMatch(/已发送 · \d+s/);
    expect(html).toContain('data-stage-phase="sent"');
  });
});
