// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchVirtualHumanEvents } from "../../api/virtualHumanLife";
import type { VirtualHumanEpisodicMemory, VirtualHumanLifeEvent } from "../../api/types";
import { CompanionMemoryRecords } from "./CompanionMemoryRecords";

vi.mock("../../api/virtualHumanLife", () => ({ fetchVirtualHumanEvents: vi.fn() }));
vi.mock("../../app/pollingPolicy", () => ({ usePageVisibility: () => false }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;
const memory: VirtualHumanEpisodicMemory = {
  episodeId: "episode-1", text: "已有的记忆正文", occurredAt: "2026-10-12T10:00:00Z", sourceEventIds: ["event-1"],
};
const simulatedEvent: VirtualHumanLifeEvent = {
  eventId: "event-1", agentId: "companion-1", kind: "activity_completed", title: "散步",
  outcome: { kind: "deterministic_simulation", status: "succeeded", summary: "完成了散步。" }, simulatedAfterRestart: false,
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(fetchVirtualHumanEvents).mockResolvedValue([]);
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  container.remove();
  vi.clearAllMocks();
});

async function renderRecords(memories = [memory], agentId = "companion-1") {
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <CompanionMemoryRecords key={agentId} agentId={agentId} memories={memories} lang="zh" />
    </QueryClientProvider>,
  ));
}

async function flushQuery() {
  await act(async () => new Promise((resolve) => setTimeout(resolve, 15)));
}

async function openMemory() {
  const button = container.querySelector<HTMLButtonElement>('button[aria-label="阅读记忆正文与来源"]');
  expect(button).toBeTruthy();
  await act(async () => button!.click());
  return document.querySelector<HTMLElement>('[role="dialog"]')!;
}

describe("CompanionMemoryRecords", () => {
  it("opens the entire supplied body as text without fabricating an extended record", async () => {
    const body = "现存正文\n" + "一段很长的记忆。".repeat(90) + "\n<em>保留原文</em>";
    await renderRecords([{ ...memory, text: body, sourceEventIds: [] }]);
    const dialog = await openMemory();
    expect(dialog.textContent).toContain(body);
    expect(dialog.querySelector("em")).toBeNull();
    expect(dialog.textContent).toContain("未提供更长内容");
    expect(dialog.textContent).toContain("来源未核实");
    expect(fetchVirtualHumanEvents).not.toHaveBeenCalled();
  });

  it("labels old simulated completions even when they were not simulated after restart", async () => {
    vi.mocked(fetchVirtualHumanEvents).mockResolvedValue([simulatedEvent]);
    await renderRecords();
    const dialog = await openMemory();
    await flushQuery();
    expect(container.textContent).toContain("含日程模拟记录");
    expect(dialog.textContent).toContain("日程模拟");
    expect(dialog.textContent).toContain("不能据此确认真实行动或共同经历");
    expect(dialog.textContent).toContain("完成了散步。");
    expect(fetchVirtualHumanEvents).toHaveBeenCalledTimes(3);
    expect(fetchVirtualHumanEvents).toHaveBeenCalledWith("companion-1", expect.objectContaining({ localDate: "2026-10-12", limit: 500, signal: expect.any(AbortSignal) }));
  });

  it("does not join another Agent's matching event ID, and treats missing history as unknown", async () => {
    vi.mocked(fetchVirtualHumanEvents).mockResolvedValue([{ ...simulatedEvent, agentId: "companion-other" }]);
    await renderRecords();
    const dialog = await openMemory();
    await flushQuery();
    expect(container.textContent).toContain("来源未完全确认");
    expect(dialog.textContent).toContain("event-1");
    expect(dialog.textContent).toContain("未找到此事件，仍待核实");
    expect(dialog.textContent).not.toContain("完成了散步。");
    await renderRecords([{ ...memory, episodeId: "episode-other", text: "另一个人物的记忆" }], "companion-other");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("keeps source loading, failure, retry and the saved body visible", async () => {
    const rejectEvents: Array<(reason: Error) => void> = [];
    vi.mocked(fetchVirtualHumanEvents).mockImplementation(() => new Promise((_resolve, reject) => { rejectEvents.push(reject); }));
    await renderRecords();
    const dialog = await openMemory();
    expect(dialog.textContent).toContain("正在读取来源事件");
    await act(async () => rejectEvents.forEach((reject) => reject(new Error("unavailable"))));
    await flushQuery();
    expect(dialog.textContent).toContain(memory.text);
    expect(dialog.textContent).toContain("来源暂不可用");
    vi.mocked(fetchVirtualHumanEvents).mockResolvedValue([simulatedEvent]);
    const retry = [...dialog.querySelectorAll("button")].find((button) => button.textContent === "重试来源");
    await act(async () => retry!.click());
    await flushQuery();
    expect(dialog.textContent).toContain("日程模拟");
    expect(dialog.textContent).not.toContain("来源暂不可用");
  });

  it("preserves legacy source values without claiming their text proves an event", async () => {
    const legacy = { ...memory, text: "", sourceEventIds: [], source: "legacy-scheduler" };
    await renderRecords([legacy]);
    const dialog = await openMemory();
    expect(dialog.textContent).toContain("这条记忆没有正文。");
    expect(dialog.textContent).toContain("source: legacy-scheduler");
    expect(dialog.textContent).toContain("来源未核实");
  });

  it("labels provenance and keeps excluded memories available in history", async () => {
    const memories: VirtualHumanEpisodicMemory[] = [
      {
        ...memory,
        episodeId: "excluded-simulation",
        text: "模拟经历仍留在历史中",
        occurredAt: "2026-10-14T10:00:00Z",
        sourceEventIds: [],
        sourceKind: "simulation",
        excludedFromRecall: true,
        sourceRefs: [{ type: "episode", id: "simulated-episode-1" }],
      },
      { ...memory, episodeId: "verified-action", text: "有回执的行动", sourceEventIds: [], sourceKind: "verified_action" },
      { ...memory, episodeId: "character-report", text: "人物自述", sourceEventIds: [], sourceKind: "character_report" },
      { ...memory, episodeId: "unknown-source", text: "未核实来源", sourceEventIds: [], sourceKind: "unknown" },
    ];
    await renderRecords(memories);

    expect(container.querySelectorAll('button[aria-label="阅读记忆正文与来源"]')).toHaveLength(4);
    expect(container.textContent).toContain("日程模拟（已隔离）");
    expect(container.textContent).toContain("工具行动（有回执）");
    expect(container.textContent).toContain("人物自述");
    expect(container.textContent).toContain("来源未核实");
    expect(container.textContent).toContain("模拟经历仍留在历史中");
    expect(container.textContent).toContain("已排除出回忆检索，历史记录仍保留");

    const dialog = await openMemory();
    expect(dialog.textContent).toContain("日程模拟（已隔离）");
    expect(dialog.textContent).toContain("episode: simulated-episode-1");
    expect(dialog.textContent).toContain("已排除出回忆检索，历史记录仍保留");
  });

  it("does not claim an unconfirmed simulation was excluded from recall", async () => {
    await renderRecords([{
      ...memory,
      sourceEventIds: [],
      sourceKind: "simulation",
      excludedFromRecall: false,
    }]);

    expect(container.textContent).toContain("日程模拟");
    expect(container.textContent).not.toContain("已隔离");

    const dialog = await openMemory();
    expect(dialog.textContent).toContain("此模拟来源尚未确认已排除出回忆检索。");
    expect(dialog.textContent).not.toContain("日程模拟（已隔离）");
  });

  it("does not guess a source date from promotion time or fetch today's events when the record date is missing", async () => {
    await renderRecords([{ ...memory, occurredAt: null, promotedAt: "2026-10-12T12:00:00Z" }]);
    const dialog = await openMemory();
    expect(dialog.textContent).toContain("记录时间缺失");
    expect(dialog.textContent).toContain("event-1");
    expect(fetchVirtualHumanEvents).not.toHaveBeenCalled();
  });

  it("returns focus to the Read button after the dialog closes", async () => {
    await renderRecords([{ ...memory, sourceEventIds: [] }]);
    const dialog = await openMemory();
    await act(async () => dialog.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!.click());
    await flushQuery();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(container.querySelector('button[aria-label="阅读记忆正文与来源"]'));
  });

  it("reveals memories six at a time and resets the page at data and Agent boundaries", async () => {
    const makeMemories = (prefix: string, count: number) => Array.from({ length: count }, (_, index) => ({
      ...memory,
      episodeId: `${prefix}-${index + 1}`,
      text: `${prefix} 记忆正文 ${index + 1}`,
      occurredAt: new Date(Date.UTC(2026, 9, 12, index)).toISOString(),
      sourceEventIds: [],
    }));
    const originalMemories = makeMemories("agent-one", 13);
    const readButtons = () => container.querySelectorAll<HTMLButtonElement>('button[aria-label="阅读记忆正文与来源"]');
    const moreButton = () => [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.includes("查看更多记忆"));

    await renderRecords(originalMemories);
    expect(readButtons()).toHaveLength(6);
    expect(moreButton()?.textContent).toContain("还有 7 条");

    await act(async () => moreButton()!.click());
    expect(readButtons()).toHaveLength(12);
    expect(moreButton()?.textContent).toContain("还有 1 条");

    await act(async () => moreButton()!.click());
    expect(readButtons()).toHaveLength(13);
    expect(moreButton()).toBeUndefined();

    const changedMemories = makeMemories("agent-one-updated", 12);
    await renderRecords(changedMemories);
    expect(readButtons()).toHaveLength(6);
    expect(moreButton()?.textContent).toContain("还有 6 条");
    expect(container.textContent).toContain("agent-one-updated 记忆正文 12");
    expect(container.textContent).not.toContain("agent-one 记忆正文 1");
    await act(async () => moreButton()!.click());
    expect(readButtons()).toHaveLength(12);

    const otherAgentMemories = makeMemories("agent-two", 12);
    await renderRecords(otherAgentMemories, "companion-two");
    expect(readButtons()).toHaveLength(6);
    expect(moreButton()?.textContent).toContain("还有 6 条");
    expect(container.textContent).toContain("agent-two 记忆正文 12");
    expect(container.textContent).not.toContain("agent-one-updated 记忆正文 1");
  });
});
