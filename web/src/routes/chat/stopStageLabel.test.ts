import { describe, expect, it } from "vitest";
import { resolveStopStageLabel } from "./stopStageLabel";

const stage = (name: string) => ({ stage: name, at: "2026-01-01T00:00:00Z" });

describe("resolveStopStageLabel", () => {
  it("stays silent without stage evidence", () => {
    expect(resolveStopStageLabel(undefined, "zh")).toBe("");
    expect(resolveStopStageLabel(null, "zh")).toBe("");
    expect(resolveStopStageLabel([], "en")).toBe("");
  });

  it("names the newest hop rather than the first", () => {
    expect(resolveStopStageLabel([stage("requested"), stage("tools_cancelled")], "zh"))
      .toBe("正在停止 · 已取消工具");
  });

  it("translates each known hop", () => {
    expect(resolveStopStageLabel([stage("requested")], "zh")).toBe("正在停止 · 已受理");
    expect(resolveStopStageLabel([stage("provider_aborted")], "zh")).toBe("正在停止 · 已中断模型");
    expect(resolveStopStageLabel([stage("snapshot_persisted")], "en")).toBe("Stopping · saving snapshot");
    expect(resolveStopStageLabel([stage("forced")], "en")).toBe("Stopping · forcing settle");
  });

  it("ignores hops it cannot name instead of inventing progress", () => {
    expect(resolveStopStageLabel([stage("unknown_hop")], "zh")).toBe("");
  });
});
