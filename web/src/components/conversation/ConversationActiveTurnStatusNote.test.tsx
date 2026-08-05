import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationActiveTurnStatusNote } from "./ConversationActiveTurnStatusNote";
import styles from "./ConversationActiveTurnStatusNote.styles";

describe("ConversationActiveTurnStatusNote", () => {
  it("renders thinking heartbeat with compact stage dots instead of a full label bar", () => {
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
    expect(html).toContain('data-stage-phase="thinking"');
    expect(html).toContain('data-stage-current="true"');
    expect(html).toContain('data-stage-phase="sent"');
    // Visible chrome no longer dumps the whole pipeline as text.
    expect(html).not.toContain("发送 →");
    expect(html).not.toContain(">发送<");
    expect(html).not.toContain(">准备<");
    expect(html).not.toContain(">请求<");
    expect(html).toContain("aria-label=");
    expect(html).toMatch(/aria-label="[^"]*状态[^"]*思考中/);
    expect(styles.stageDotCurrent).toContain("accent-cool");
    expect(styles.note).toContain("inline-flex");
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
    expect(html).toContain('data-stage-current="true"');
  });

  it("can hide the stage track when only heartbeat is needed", () => {
    const html = renderToStaticMarkup(
      <ConversationActiveTurnStatusNote
        message={{ streamStage: "model_thinking", timestamp: "2026-08-02T12:00:00.000Z" }}
        lang="zh"
        showStageBar={false}
      />,
    );
    expect(html).toMatch(/思考中 · \d+s/);
    expect(html).not.toContain("data-stage-phase");
  });
});
