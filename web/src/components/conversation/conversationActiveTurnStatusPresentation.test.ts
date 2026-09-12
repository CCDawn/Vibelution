import { describe, expect, it } from "vitest";

import {
  activeTurnElapsedSeconds,
  activeTurnOptimisticStageSummary,
  activeTurnStageBarPhase,
  activeTurnStageLabel,
  buildActiveTurnStageBarItems,
  formatActiveTurnHeartbeatText,
  planActiveTurnStageSwitch,
  resolveActiveTurnProgressStage,
  resolveActiveTurnRetryProgress,
} from "./conversationActiveTurnStatusPresentation";

describe("conversationActiveTurnStatusPresentation", () => {
  it("maps stage labels and optimistic summaries", () => {
    expect(activeTurnStageLabel("user_submit", "zh")).toBe("已发送");
    expect(activeTurnStageLabel("model_thinking", "zh")).toBe("思考中");
    expect(activeTurnStageLabel("server_thinking", "en")).toBe("Thinking");
    expect(activeTurnStageLabel("model_request", "zh")).toBe("请求模型");
    expect(activeTurnStageLabel("working", "zh")).toBe("处理中");
    expect(activeTurnStageLabel("thinking", "en")).toBe("Thinking");
    expect(activeTurnStageLabel("queued", "zh")).toBe("排队中");
    expect(activeTurnOptimisticStageSummary("user_submit", "zh")).toBe("已发送，正在连接");
    expect(activeTurnOptimisticStageSummary("model_thinking", "zh")).toBe("思考中，等待模型输出");
  });

  it("builds heartbeat text with elapsed seconds", () => {
    expect(formatActiveTurnHeartbeatText("model_thinking", 12, "zh")).toBe("思考中 · 12s");
    expect(formatActiveTurnHeartbeatText("agent_prepare", null, "en")).toBe("Preparing agent");
    expect(activeTurnElapsedSeconds("2026-08-02T10:00:00.000Z", Date.parse("2026-08-02T10:00:08.400Z"))).toBe(8);
    expect(activeTurnElapsedSeconds("bad", Date.now())).toBeNull();
  });

  it("maps prepare→thinking stage bar progression", () => {
    expect(activeTurnStageBarPhase("user_submit")).toBe("sent");
    expect(activeTurnStageBarPhase("agent_prepare")).toBe("prepare");
    expect(activeTurnStageBarPhase("model_request")).toBe("request");
    expect(activeTurnStageBarPhase("model_thinking")).toBe("thinking");
    const bar = buildActiveTurnStageBarItems("model_thinking", "zh");
    expect(bar.map((item) => item.label)).toEqual(["发送", "准备", "请求", "思考"]);
    expect(bar.find((item) => item.phase === "thinking")?.current).toBe(true);
    expect(bar.filter((item) => item.reached)).toHaveLength(4);
  });

  it("falls back to metadata.processStage then pending/running defaults", () => {
    expect(resolveActiveTurnProgressStage({
      turnItems: [],
      metadata: { processStage: "user_submit" },
    })).toBe("user_submit");
    expect(resolveActiveTurnProgressStage({
      turnItems: [],
      status: "pending",
    })).toBe("user_submit");
    expect(resolveActiveTurnProgressStage({
      turnItems: [],
      status: "running",
    })).toBe("running");
  });

  it("holds a fresh stage for the minimum dwell before switching", () => {
    expect(planActiveTurnStageSwitch("working", "working", 0)).toEqual({ stage: "working", delayMs: 0 });
    expect(planActiveTurnStageSwitch("working", "thinking", 120)).toEqual({ stage: "working", delayMs: 580 });
    expect(planActiveTurnStageSwitch("working", "thinking", 700)).toEqual({ stage: "thinking", delayMs: 0 });
    expect(planActiveTurnStageSwitch("working", "thinking", 5000)).toEqual({ stage: "thinking", delayMs: 0 });
  });

  it("resolves retry attempt progress from structured fields then text", () => {
    expect(resolveActiveTurnRetryProgress({
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
    })).toEqual({ attempt: 2, maxAttempts: 5 });
    expect(resolveActiveTurnRetryProgress({
      turnItems: [{
        id: "status-1-r1",
        itemId: "status-1",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-1",
        type: "status",
        status: "running",
        revision: 1,
        sequence: 2,
        code: "model_retry",
        text: "模型连接正在重试...\n第 3/5 次；原因：server_error。",
      }],
    })).toEqual({ attempt: 3, maxAttempts: 5 });
    expect(resolveActiveTurnRetryProgress({
      turnItems: [{
        id: "status-2-r1",
        itemId: "status-2",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-1",
        type: "status",
        status: "running",
        revision: 1,
        sequence: 3,
        code: "model_request",
        text: "等待模型响应...",
      }],
    })).toBeNull();
  });

  it("formats retry heartbeat with attempt counts", () => {
    expect(formatActiveTurnHeartbeatText("model_retry", 12, "zh", { attempt: 2, maxAttempts: 5 }))
      .toBe("请求重试 2/5 · 12s");
    expect(formatActiveTurnHeartbeatText("model_retry", null, "en", { attempt: 3, maxAttempts: 5 }))
      .toBe("Retrying request 3/5");
    expect(formatActiveTurnHeartbeatText("model_retry", 8, "zh"))
      .toBe("请求重试 · 8s");
  });
});
