import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import {
  ActiveTurnStreamStateContext,
  type ActiveTurnStreamState,
} from "./activeTurnStreamState";
import { ConversationActiveTurnStatusNote } from "./ConversationActiveTurnStatusNote";

function renderNote(options: {
  message?: Record<string, unknown>;
  streamState?: ActiveTurnStreamState;
  companionMode?: boolean;
  lang?: "zh" | "en";
}) {
  const {
    message = { timestamp: new Date(Date.now() - 5_000).toISOString(), status: "running", turnItems: [] },
    streamState,
    companionMode = false,
    lang = "zh",
  } = options;
  const node = streamState ? (
    <ActiveTurnStreamStateContext.Provider value={streamState}>
      <ConversationActiveTurnStatusNote
        lang={lang}
        companionMode={companionMode}
        statusLabel="状态"
        message={message as never}
      />
    </ActiveTurnStreamStateContext.Provider>
  ) : (
    <ConversationActiveTurnStatusNote
      lang={lang}
      companionMode={companionMode}
      statusLabel="状态"
      message={message as never}
    />
  );
  return renderToStaticMarkup(node);
}

describe("ConversationActiveTurnStatusNote canonical turn items", () => {
  it("uses one unlabeled typing affordance for companion mode", () => {
    const html = renderToStaticMarkup(
      <ConversationActiveTurnStatusNote
        lang="zh"
        companionMode
        statusLabel="状态"
        message={{
          timestamp: new Date().toISOString(),
          status: "running",
          turnItems: [],
        }}
      />,
    );

    expect(html).toContain('data-companion-typing-status="true"');
    expect(html.match(/正在输入…/g)).toHaveLength(1);
    expect(html).not.toContain("状态");
    expect(html).not.toContain("aria-label=");
  });

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
            reason: "模型连接正在重试...\n第 2/5 次；原因：server_error。",
            metadata: { maxAttempts: 5 },
          }],
        }}
      />,
    );

    expect(html).toContain("data-active-turn-stage=\"model_retry\"");
    expect(html).toContain("请求重试 2/5");
    expect(html).not.toContain("data-stage-phase");
    expect(html).not.toContain("stageDot");
  });
});

describe("ConversationActiveTurnStatusNote stream advisories", () => {
  it("shows the reconnecting notice with duration while disconnected", () => {
    const html = renderNote({
      streamState: {
        streamConnected: false,
        streamDisconnectedSinceMs: Date.now() - 12_000,
        lastAssistantDeltaAtMs: Date.now() - 1_000,
      },
    });

    expect(html).toContain('data-active-turn-disconnected="true"');
    expect(html).toContain("连接已断开，正在重连…");
    expect(html).toMatch(/· 1[12]s/);
    expect(html).toContain('data-tone="warning"');
    expect(html).not.toContain('data-active-turn-stalled="true"');
  });

  it("shows no connectivity notice while the stream is healthy", () => {
    const html = renderNote({
      streamState: { streamConnected: true, lastAssistantDeltaAtMs: Date.now() - 1_000 },
    });

    expect(html).not.toContain('data-active-turn-disconnected="true"');
    expect(html).not.toContain("连接已断开，正在重连…");
    expect(html).not.toContain('data-active-turn-stalled="true"');
  });

  it("upgrades to the no-output stall hint past the threshold and stacks with disconnect", () => {
    const html = renderNote({
      message: {
        timestamp: new Date(Date.now() - 120_000).toISOString(),
        status: "running",
        turnItems: [],
      },
      streamState: {
        streamConnected: false,
        streamDisconnectedSinceMs: Date.now() - 5_000,
        lastAssistantDeltaAtMs: Date.now() - 95_000,
      },
    });

    // Orthogonal: the reconnecting notice and the stall hint coexist.
    expect(html).toContain('data-active-turn-disconnected="true"');
    expect(html).toContain('data-active-turn-stalled="true"');
    expect(html).toContain(dictionaryChat.zh.chatStreamNoOutputStalled);
    expect(html.match(/长时间无输出，可停止 · 9[45]s/g)).toHaveLength(1);
  });

  it("hides companion-mode advisories", () => {
    const html = renderNote({
      companionMode: true,
      message: {
        timestamp: new Date(Date.now() - 120_000).toISOString(),
        status: "running",
        turnItems: [],
      },
      streamState: {
        streamConnected: false,
        streamDisconnectedSinceMs: Date.now() - 5_000,
        lastAssistantDeltaAtMs: Date.now() - 95_000,
      },
    });

    expect(html).not.toContain('data-active-turn-disconnected="true"');
    expect(html).not.toContain('data-active-turn-stalled="true"');
  });

  it("renders the route fallback notice only when both ends exist", () => {
    const complete = renderNote({
      message: {
        timestamp: new Date().toISOString(),
        status: "running",
        turnItems: [],
        routeFallback: { from: "model-a", to: "model-b" },
      },
    });
    expect(complete).toContain('data-active-turn-route-fallback="true"');
    expect(complete).toContain("已切换备用模型路由（model-a → model-b）继续生成");

    const missingTo = renderNote({
      message: {
        timestamp: new Date().toISOString(),
        status: "running",
        turnItems: [],
        routeFallback: { from: "model-a", to: "" },
      },
    });
    expect(missingTo).not.toContain('data-active-turn-route-fallback="true"');
    expect(missingTo).not.toContain("已切换备用模型路由");

    const absent = renderNote({});
    expect(absent).not.toContain('data-active-turn-route-fallback="true"');
  });

  it("uses English dictionary copy for en", () => {
    const html = renderNote({
      lang: "en",
      streamState: {
        streamConnected: false,
        streamDisconnectedSinceMs: Date.now() - 3_000,
        lastAssistantDeltaAtMs: Date.now() - 1_000,
      },
    });

    expect(html).toContain(dictionaryChat.en.chatStreamDisconnectedReconnecting);
  });
});
