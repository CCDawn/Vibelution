import { describe, expect, it } from "vitest";

import {
  activeTurnElapsedSeconds,
  activeTurnOptimisticStageSummary,
  activeTurnStageBarPhase,
  activeTurnStageLabel,
  buildActiveTurnStageBarItems,
  formatActiveTurnHeartbeatText,
  resolveActiveTurnProgressStage,
} from "./conversationActiveTurnStatusPresentation";

describe("conversationActiveTurnStatusPresentation", () => {
  it("resolves stage from streamStage then latest status feedback", () => {
    expect(resolveActiveTurnProgressStage({ streamStage: "model_thinking" })).toBe("model_thinking");
    expect(resolveActiveTurnProgressStage({
      feedbackEvents: [
        { kind: "status", name: "agent_prepare", status: "running" },
        { kind: "status", name: "model_request", status: "running" },
      ],
    })).toBe("model_request");
    expect(resolveActiveTurnProgressStage({})).toBe("running");
  });

  it("maps stage labels and optimistic summaries", () => {
    expect(activeTurnStageLabel("user_submit", "zh")).toBe("已发送");
    expect(activeTurnStageLabel("model_thinking", "zh")).toBe("思考中");
    expect(activeTurnStageLabel("server_thinking", "en")).toBe("Thinking");
    expect(activeTurnStageLabel("model_request", "zh")).toBe("请求模型");
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
});
