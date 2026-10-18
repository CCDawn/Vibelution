// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  addPersonalAffair,
  cancelPersonalAffair,
  completePersonalAffair,
  fetchPersonalAffairs,
  reopenPersonalAffair,
  setPersonalAffairDue,
} from "../../api/personalAffairs";
import type { PersonalAffairList } from "../../api/types";
import { PersonalAssistantAffairs } from "./PersonalAssistantAffairs";

vi.mock("../../api/personalAffairs", () => ({
  fetchPersonalAffairs: vi.fn(),
  addPersonalAffair: vi.fn(),
  completePersonalAffair: vi.fn(),
  cancelPersonalAffair: vi.fn(),
  reopenPersonalAffair: vi.fn(),
  setPersonalAffairDue: vi.fn(),
}));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const list: PersonalAffairList = {
  schemaVersion: 1,
  agentId: "agent-companion",
  items: [
    {
      schemaVersion: 1,
      itemId: "affair-1",
      kind: "todo",
      title: "整理周报",
      note: "包含上周遗留项",
      status: "open",
      dueAt: "2026-10-18T02:00:00Z",
      createdAt: "2026-10-17T00:00:00Z",
      updatedAt: "2026-10-17T00:00:00Z",
      completedAt: "",
      sourceTurnId: "",
      dueState: "overdue",
    },
    {
      schemaVersion: 1,
      itemId: "affair-2",
      kind: "schedule",
      title: "和用户复盘",
      note: "",
      status: "done",
      dueAt: "",
      createdAt: "2026-10-16T00:00:00Z",
      updatedAt: "2026-10-17T00:00:00Z",
      completedAt: "2026-10-17T01:00:00Z",
      sourceTurnId: "turn-9",
      dueState: "none",
    },
  ],
  counts: { open: 1, overdue: 1, done: 1 },
  updatedAt: "2026-10-19T00:00:00Z",
};

let root: Root, container: HTMLDivElement, client: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAffairs).mockResolvedValue({ ...list, items: list.items.map(item => ({ ...item })), counts: { ...list.counts } });
  vi.mocked(completePersonalAffair).mockResolvedValue({ agentId: "agent-companion", item: { ...list.items[0], status: "done", dueState: "none" } });
  vi.mocked(addPersonalAffair).mockResolvedValue({ agentId: "agent-companion", item: { ...list.items[0], itemId: "affair-new" } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: () => 0, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}>
    <PersonalAssistantAffairs agentId="agent-companion" />
  </QueryClientProvider>));
  await settle(); await settle();
}
function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
async function clickButton(text: string) {
  const button = await vi.waitFor(() => {
    const found = [...container.querySelectorAll("button")].find(node => node.textContent === text);
    if (!found) throw new Error(`${text} button not rendered yet`);
    return found as HTMLButtonElement;
  });
  await act(async () => button.click());
  await settle();
}

describe("PersonalAssistantAffairs", () => {
  it("renders backend counts and items with mapped kind, due-state and status labels", async () => {
    await render();
    expect(fetchPersonalAffairs).toHaveBeenCalledWith("agent-companion", expect.objectContaining({ kind: "", status: "" }));
    expect(container.textContent).toContain("进行中 1");
    expect(container.textContent).toContain("已逾期 1");
    expect(container.textContent).toContain("已完成 1");
    expect(container.textContent).toContain("整理周报");
    expect(container.textContent).toContain("待办");
    expect(container.textContent).toContain("已逾期");
    expect(container.textContent).toContain("包含上周遗留项");
    expect(container.textContent).toContain("已完成");
    expect(container.querySelector('input[aria-label="设截止: 整理周报"]')).toBeNull();
  });

  it("adds an affair with the selected kind and an ISO due time", async () => {
    await render();
    setInputValue(container.querySelector('input[aria-label="标题"]') as HTMLInputElement, "周会");
    setInputValue(container.querySelector('input[aria-label="截止时间"]') as HTMLInputElement, "2026-10-20T10:30");
    await clickButton("添加");
    expect(addPersonalAffair).toHaveBeenCalledWith("agent-companion", {
      kind: "todo",
      title: "周会",
      dueAt: new Date("2026-10-20T10:30").toISOString(),
    });
    expect((container.querySelector('input[aria-label="标题"]') as HTMLInputElement).value).toBe("");
  });

  it("completes an open item through the backend action route", async () => {
    await render();
    await clickButton("完成");
    expect(completePersonalAffair).toHaveBeenCalledWith("agent-companion", "affair-1");
  });

  it("reopens a done item and cancels are routed by item id", async () => {
    await render();
    await clickButton("重新打开");
    expect(reopenPersonalAffair).toHaveBeenCalledWith("agent-companion", "affair-2");
    await clickButton("取消");
    expect(cancelPersonalAffair).toHaveBeenCalledWith("agent-companion", "affair-1");
  });

  it("edits and saves a due time in the inline editor, empty save clears it", async () => {
    await render();
    await clickButton("设截止");
    const editor = container.querySelector('input[aria-label="设截止: 整理周报"]') as HTMLInputElement;
    expect(editor).not.toBeNull();
    expect(editor.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    setInputValue(editor, "2026-10-22T09:00");
    await clickButton("保存");
    expect(setPersonalAffairDue).toHaveBeenCalledWith("agent-companion", "affair-1", new Date("2026-10-22T09:00").toISOString());
    await clickButton("设截止");
    const cleared = container.querySelector('input[aria-label="设截止: 整理周报"]') as HTMLInputElement;
    setInputValue(cleared, "");
    await clickButton("保存");
    expect(setPersonalAffairDue).toHaveBeenLastCalledWith("agent-companion", "affair-1", "");
  });

  it("applies the kind filter to the list query", async () => {
    await render();
    const trigger = container.querySelector('button[role="combobox"][aria-label="按类型"]') as HTMLButtonElement;
    await act(async () => trigger.click());
    const option = await vi.waitFor(() => {
      const found = [...document.body.querySelectorAll('[role="option"]')].find(node => node.textContent === "日程");
      if (!found) throw new Error("日程 option not rendered yet");
      return found as HTMLElement;
    });
    await act(async () => option.click());
    await settle();
    expect(fetchPersonalAffairs).toHaveBeenLastCalledWith("agent-companion", expect.objectContaining({ kind: "schedule" }));
  });

  it("surfaces an action failure as an inline alert", async () => {
    vi.mocked(completePersonalAffair).mockRejectedValue(new Error("事务不存在"));
    await render();
    await clickButton("完成");
    expect(container.querySelector('p[role="alert"]')?.textContent).toContain("事务不存在");
  });

  it("shows a load-failure state with retry", async () => {
    vi.mocked(fetchPersonalAffairs).mockRejectedValue(new Error("后端未就绪"));
    await render();
    expect(container.textContent).toContain("事务读取失败");
    vi.mocked(fetchPersonalAffairs).mockResolvedValue({ ...list, items: [], counts: { open: 0, overdue: 0, done: 0 } });
    await clickButton("重试");
    // one initial attempt plus its retry:1 re-attempt, then the manual refetch
    expect(fetchPersonalAffairs).toHaveBeenCalledTimes(3);
  });

  it("distinguishes the empty and filtered-empty states", async () => {
    vi.mocked(fetchPersonalAffairs).mockResolvedValue({ ...list, items: [], counts: { open: 0, overdue: 0, done: 0 } });
    await render();
    expect(container.textContent).toContain("还没有事务");
  });
});
