import { describe, expect, it } from "vitest";

import {
  AUX_TASK_KINDS,
  auxTaskKindLabel,
  auxTaskStatusLabel,
  auxTaskStatusTone,
  formatRelativeTime,
  formatTaskTimeRange,
  isTerminalRuntimeTask,
} from "./auxTaskPresentation";

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const NOW = Date.parse("2026-10-01T12:00:00Z");

describe("auxTaskPresentation", () => {
  it("labels the three known kinds and passes unknown kinds through", () => {
    expect(AUX_TASK_KINDS).toEqual(["child_session", "cli_agent", "research_task"]);
    expect(auxTaskKindLabel("child_session", "zh")).toBe("子会话");
    expect(auxTaskKindLabel("cli_agent", "zh")).toBe("CLI agent");
    expect(auxTaskKindLabel("research_task", "zh")).toBe("研究任务");
    expect(auxTaskKindLabel("child_session", "en")).toBe("Child session");
    expect(auxTaskKindLabel("exotic_kind", "zh")).toBe("exotic_kind");
    expect(auxTaskKindLabel("", "zh")).toBe("-");
  });

  it("labels task statuses generically and passes unknown words through", () => {
    expect(auxTaskStatusLabel("running", "zh")).toBe("运行中");
    expect(auxTaskStatusLabel("waiting", "zh")).toBe("等待中");
    expect(auxTaskStatusLabel("succeeded", "zh")).toBe("已成功");
    expect(auxTaskStatusLabel("failed", "zh")).toBe("失败");
    expect(auxTaskStatusLabel("stopped", "zh")).toBe("已停止");
    expect(auxTaskStatusLabel("weird", "zh")).toBe("weird");
    expect(auxTaskStatusTone("running")).toBe("accent");
    expect(auxTaskStatusTone("succeeded")).toBe("success");
    expect(auxTaskStatusTone("failed")).toBe("danger");
    expect(auxTaskStatusTone("cancelled")).toBe("warning");
    expect(auxTaskStatusTone("stopped")).toBe("warning");
    expect(auxTaskStatusTone("unknown")).toBe("neutral");
  });

  it("marks terminal state from endedAt, never from the status string", () => {
    expect(isTerminalRuntimeTask({ endedAt: "2026-10-01T10:00:00Z" })).toBe(true);
    expect(isTerminalRuntimeTask({ endedAt: "" })).toBe(false);
    expect(isTerminalRuntimeTask({ endedAt: null })).toBe(false);
    expect(isTerminalRuntimeTask({})).toBe(false);
  });

  it("formats compact relative time buckets", () => {
    expect(formatRelativeTime("", "zh")).toBe("-");
    expect(formatRelativeTime("not-a-date", "zh")).toBe("not-a-date");
    expect(formatRelativeTime(new Date(NOW - 30_000).toISOString(), "zh", NOW)).toBe("刚刚");
    expect(formatRelativeTime(new Date(NOW - 5 * MINUTE_MS).toISOString(), "zh", NOW)).toBe("5 分钟前");
    expect(formatRelativeTime(new Date(NOW - 5 * MINUTE_MS).toISOString(), "en", NOW)).toBe("5m ago");
    expect(formatRelativeTime(new Date(NOW - 3 * HOUR_MS).toISOString(), "zh", NOW)).toBe("3 小时前");
    expect(formatRelativeTime(new Date(NOW - 4 * 24 * HOUR_MS).toISOString(), "zh", NOW)).toBe("4 天前");
    expect(formatRelativeTime(new Date(NOW - 30 * 24 * HOUR_MS).toISOString(), "zh", NOW)).toContain("2026");
  });

  it("describes the start-end range with and without an end", () => {
    const startedAt = new Date(NOW - 2 * HOUR_MS).toISOString();
    expect(formatTaskTimeRange(startedAt, null, "zh", NOW)).toBe("2 小时前 起");
    const endedAt = new Date(NOW - MINUTE_MS).toISOString();
    expect(formatTaskTimeRange(startedAt, endedAt, "zh", NOW)).toBe("2 小时前 → 1 分钟前");
  });
});
