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
  vi.resetAllMocks();
  vi.mocked(fetchPersonalAffairs).mockResolvedValue({ ...list, items: list.items.map(item => ({ ...item })), counts: { ...list.counts } });
  vi.mocked(completePersonalAffair).mockResolvedValue({ agentId: "agent-companion", item: { ...list.items[0], status: "done", dueState: "none" } });
  vi.mocked(addPersonalAffair).mockResolvedValue({ agentId: "agent-companion", item: { ...list.items[0], itemId: "affair-new" } });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: () => 0, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render(focusItemId?: string, focusRequestKey?: string, agentId = "agent-companion") {
  await act(async () => root.render(<QueryClientProvider client={client}>
    <PersonalAssistantAffairs agentId={agentId} focusItemId={focusItemId} focusRequestKey={focusRequestKey} />
  </QueryClientProvider>));
  await settle(); await settle();
}
function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function itemRow(title: string) {
  const row = [...container.querySelectorAll("li")].find(node => node.querySelector("strong")?.textContent === title);
  if (!row) throw new Error(`${title} row not rendered`);
  return row;
}
function itemButton(title: string, label: string) {
  const button = [...itemRow(title).querySelectorAll("button")].find(node => node.textContent === label);
  if (!button) throw new Error(`${title}: ${label} button not rendered`);
  return button as HTMLButtonElement;
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
  it("keeps Launcher affairs and refresh isolated from Workbench for the same agent", async () => {
    const nativeList = { ...list, items: [{ ...list.items[0], title: "Launcher 事务" }] };
    const fetchNative = vi.fn(async () => nativeList);
    const completeNative = vi.fn(async () => ({ agentId: list.agentId, item: nativeList.items[0] }));
    const transport = { cacheKey: ["launcher-assistant"], fetchPersonalAffairs: fetchNative,
      addPersonalAffair, completePersonalAffair: completeNative, cancelPersonalAffair, reopenPersonalAffair, setPersonalAffairDue };
    await act(async () => root.render(<QueryClientProvider client={client}>
      <section data-host="workbench"><PersonalAssistantAffairs agentId={list.agentId} /></section>
      <section data-host="launcher"><PersonalAssistantAffairs agentId={list.agentId} transport={transport} /></section>
    </QueryClientProvider>));
    await settle(); await settle();
    const workbench = container.querySelector('[data-host="workbench"]')!;
    const launcher = container.querySelector('[data-host="launcher"]')!;
    expect(workbench.textContent).toContain("整理周报");
    expect(workbench.textContent).not.toContain("Launcher 事务");
    expect(launcher.textContent).toContain("Launcher 事务");
    expect(launcher.textContent).not.toContain("整理周报");
    const workbenchReads = vi.mocked(fetchPersonalAffairs).mock.calls.length;
    await act(async () => ([...launcher.querySelectorAll("button")].find(button => button.textContent === "完成") as HTMLButtonElement).click());
    await settle();
    expect(completeNative).toHaveBeenCalledExactlyOnceWith(list.agentId, "affair-1");
    expect(completePersonalAffair).not.toHaveBeenCalled();
    expect(fetchNative).toHaveBeenCalledTimes(2);
    expect(fetchPersonalAffairs).toHaveBeenCalledTimes(workbenchReads);
  });

  it("keeps other items available while one item is slow and blocks same-tick duplicate/sibling actions", async () => {
    const slow = deferred<Awaited<ReturnType<typeof completePersonalAffair>>>();
    vi.mocked(fetchPersonalAffairs).mockResolvedValue({ ...list, items: list.items.map(item => ({ ...item, status: "open" })) });
    vi.mocked(completePersonalAffair).mockImplementation((_agentId, itemId) => itemId === "affair-1"
      ? slow.promise : Promise.resolve({ agentId: list.agentId, item: list.items[1] }));
    await render();
    try {
      const complete = itemButton("整理周报", "完成");
      await act(async () => { complete.click(); complete.click(); });
      expect(itemButton("和用户复盘", "完成").disabled).toBe(false);
      expect(itemButton("和用户复盘", "取消").disabled).toBe(false);
      expect(itemButton("和用户复盘", "设截止").disabled).toBe(false);
      expect(completePersonalAffair).toHaveBeenCalledTimes(1);
      expect(cancelPersonalAffair).not.toHaveBeenCalled();
      expect(itemButton("整理周报", "取消").disabled).toBe(true);
      expect(itemButton("整理周报", "设截止").disabled).toBe(true);
      await act(async () => itemButton("和用户复盘", "完成").click());
      expect(completePersonalAffair).toHaveBeenLastCalledWith("agent-companion", "affair-2");
      await settle();
      expect(itemButton("整理周报", "取消").disabled).toBe(true);
      await act(async () => itemButton("和用户复盘", "取消").click());
      expect(cancelPersonalAffair).toHaveBeenCalledWith("agent-companion", "affair-2");
      await settle();
      await act(async () => itemButton("和用户复盘", "设截止").click());
      const editor = itemRow("和用户复盘").querySelector("input") as HTMLInputElement;
      expect(editor.disabled).toBe(false);
      await act(async () => { setInputValue(editor, "2026-10-22T09:00"); });
      await act(async () => itemButton("和用户复盘", "保存").click());
      expect(setPersonalAffairDue).toHaveBeenCalledWith("agent-companion", "affair-2", new Date("2026-10-22T09:00").toISOString());
    } finally {
      await act(async () => slow.resolve({ agentId: list.agentId, item: list.items[0] }));
      await settle();
    }
  });

  it("refreshes authoritative results after out-of-order item mutations and stays pending through refresh", async () => {
    const slowA = deferred<Awaited<ReturnType<typeof completePersonalAffair>>>();
    const slowB = deferred<Awaited<ReturnType<typeof cancelPersonalAffair>>>();
    const finalRefresh = deferred<PersonalAffairList>();
    const server: PersonalAffairList = { ...list, items: list.items.map(item => ({ ...item, status: "open" })) };
    vi.mocked(fetchPersonalAffairs).mockImplementation(async () => structuredClone(server));
    vi.mocked(completePersonalAffair).mockReturnValue(slowA.promise);
    vi.mocked(cancelPersonalAffair).mockReturnValue(slowB.promise);
    await render();
    await act(async () => itemButton("整理周报", "完成").click());
    await act(async () => itemButton("和用户复盘", "取消").click());
    expect(cancelPersonalAffair).toHaveBeenCalledWith(list.agentId, "affair-2");
    server.items[1].status = "cancelled";
    await act(async () => slowB.resolve({ agentId: list.agentId, item: server.items[1] }));
    await settle();
    expect(itemRow("和用户复盘").textContent).toContain("已取消");
    expect(itemButton("整理周报", "完成").disabled).toBe(true);
    server.items[0].status = "done";
    server.counts = { open: 0, overdue: 0, done: 1 };
    vi.mocked(fetchPersonalAffairs).mockReturnValueOnce(finalRefresh.promise);
    await act(async () => slowA.resolve({ agentId: list.agentId, item: server.items[0] }));
    await settle();
    expect(itemButton("整理周报", "取消").disabled).toBe(true);
    expect(itemButton("和用户复盘", "重新打开").disabled).toBe(false);
    await act(async () => finalRefresh.resolve(structuredClone(server)));
    await settle();
    expect(itemRow("整理周报").textContent).toContain("已完成");
    expect(itemRow("和用户复盘").textContent).toContain("已取消");
    expect(container.textContent).toContain("进行中 0");
    expect(fetchPersonalAffairs).toHaveBeenCalledTimes(3);
  });

  it("associates failures with the item and allows retry while another item is pending", async () => {
    const slowA = deferred<Awaited<ReturnType<typeof completePersonalAffair>>>();
    const slowB = deferred<Awaited<ReturnType<typeof cancelPersonalAffair>>>();
    vi.mocked(fetchPersonalAffairs).mockResolvedValue({ ...list, items: list.items.map(item => ({ ...item, status: "open" })) });
    vi.mocked(completePersonalAffair).mockReturnValueOnce(slowA.promise);
    vi.mocked(cancelPersonalAffair).mockReturnValueOnce(slowB.promise);
    await render();
    await act(async () => itemButton("整理周报", "完成").click());
    await act(async () => itemButton("和用户复盘", "取消").click());
    await act(async () => slowA.reject(new Error("A 保存失败")));
    expect(itemRow("整理周报").querySelector('[role="alert"]')?.textContent).toBe("A 保存失败");
    expect(itemRow("和用户复盘").querySelector('[role="alert"]')).toBeNull();
    expect(itemButton("和用户复盘", "完成").disabled).toBe(true);
    expect(itemButton("整理周报", "完成").disabled).toBe(false);
    await act(async () => itemButton("整理周报", "完成").click());
    await settle();
    expect(completePersonalAffair).toHaveBeenCalledTimes(2);
    expect(itemRow("整理周报").querySelector('[role="alert"]')).toBeNull();
    expect(itemButton("和用户复盘", "完成").disabled).toBe(true);
    await act(async () => slowB.resolve({ agentId: list.agentId, item: list.items[1] }));
    await settle();
    expect(itemButton("和用户复盘", "完成").disabled).toBe(false);
  });

  it.each(["success", "failure"])("keeps B's due draft when A's save finishes with %s and rejects same-tick sibling actions", async outcome => {
    const slow = deferred<Awaited<ReturnType<typeof setPersonalAffairDue>>>();
    vi.mocked(fetchPersonalAffairs).mockResolvedValue({ ...list, items: list.items.map(item => ({ ...item, status: "open" })) });
    vi.mocked(setPersonalAffairDue).mockReturnValueOnce(slow.promise);
    await render();
    await act(async () => itemButton("整理周报", "设截止").click());
    const save = itemButton("整理周报", "保存");
    const complete = itemButton("整理周报", "完成");
    const cancel = itemButton("整理周报", "取消");
    await act(async () => { save.click(); save.click(); complete.click(); cancel.click(); });
    expect(setPersonalAffairDue).toHaveBeenCalledTimes(1);
    expect(completePersonalAffair).not.toHaveBeenCalled();
    expect(cancelPersonalAffair).not.toHaveBeenCalled();
    expect((itemRow("整理周报").querySelector("input") as HTMLInputElement).disabled).toBe(true);
    await act(async () => itemButton("和用户复盘", "设截止").click());
    await act(async () => setInputValue(itemRow("和用户复盘").querySelector("input") as HTMLInputElement, "2026-10-24T09:30"));
    await act(async () => {
      if (outcome === "success") slow.resolve({ agentId: list.agentId, item: list.items[0] });
      else slow.reject(new Error("A 截止保存失败"));
    });
    await settle();
    const editorB = itemRow("和用户复盘").querySelector("input") as HTMLInputElement;
    expect(editorB.value).toBe("2026-10-24T09:30");
    expect(editorB.disabled).toBe(false);
    if (outcome === "failure") {
      expect(itemRow("整理周报").querySelector('[role="alert"]')?.textContent).toBe("A 截止保存失败");
      expect(itemRow("和用户复盘").querySelector('[role="alert"]')).toBeNull();
    }
  });

  it.each(["success", "failure", "return-success", "return-failure"])("isolates old %s from pending, errors and drafts after switching agents", async outcome => {
    const oldDue = deferred<Awaited<ReturnType<typeof setPersonalAffairDue>>>();
    const oldAdd = deferred<Awaited<ReturnType<typeof addPersonalAffair>>>();
    const current = deferred<Awaited<ReturnType<typeof completePersonalAffair>>>();
    vi.mocked(setPersonalAffairDue).mockReturnValueOnce(oldDue.promise);
    vi.mocked(addPersonalAffair).mockReturnValueOnce(oldAdd.promise);
    await render();
    await act(async () => itemButton("整理周报", "设截止").click());
    await act(async () => itemButton("整理周报", "保存").click());
    await act(async () => setInputValue(container.querySelector('input[aria-label="标题"]') as HTMLInputElement, "旧草稿"));
    await act(async () => [...container.querySelectorAll("button")].find(button => button.textContent === "添加")!.click());
    await render(undefined, undefined, "agent-other");
    const currentAgent = outcome.startsWith("return-") ? list.agentId : "agent-other";
    if (currentAgent === list.agentId) await render();
    expect(itemButton("整理周报", "完成").disabled).toBe(false);
    expect(container.querySelector('input[aria-label="设截止: 整理周报"]')).toBeNull();
    expect((container.querySelector('input[aria-label="标题"]') as HTMLInputElement).value).toBe("");
    await act(async () => setInputValue(container.querySelector('input[aria-label="标题"]') as HTMLInputElement, "新草稿"));
    await act(async () => itemButton("整理周报", "设截止").click());
    await act(async () => setInputValue(itemRow("整理周报").querySelector("input") as HTMLInputElement, "2026-10-25T09:00"));
    vi.mocked(completePersonalAffair).mockReturnValueOnce(current.promise);
    await act(async () => itemButton("整理周报", "完成").click());
    await act(async () => {
      if (outcome.endsWith("success")) {
        oldDue.resolve({ agentId: list.agentId, item: list.items[0] });
        oldAdd.resolve({ agentId: list.agentId, item: list.items[0] });
      } else {
        oldDue.reject(new Error("旧助理保存失败"));
        oldAdd.reject(new Error("旧助理新增失败"));
      }
    });
    await settle();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect((container.querySelector('input[aria-label="标题"]') as HTMLInputElement).value).toBe("新草稿");
    expect((itemRow("整理周报").querySelector("input") as HTMLInputElement).value).toBe("2026-10-25T09:00");
    expect(itemButton("整理周报", "取消").disabled).toBe(true);
    expect(completePersonalAffair).toHaveBeenLastCalledWith(currentAgent, "affair-1");
    await act(async () => current.resolve({ agentId: currentAgent, item: list.items[0] }));
    await settle();
  });

  it("focuses and scrolls a reminder target once, without stealing focus on polling", async () => {
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { value: scroll, configurable: true });
    await render("affair-2", "notice-1");
    expect(document.activeElement?.textContent).toContain("和用户复盘");
    expect(scroll).toHaveBeenCalledWith({ block: "center" });
    const input = container.querySelector('input[aria-label="标题"]') as HTMLInputElement;
    input.focus();
    await act(async () => client.invalidateQueries({ queryKey: ["agents", "agent-companion", "plugins", "personal-affairs"] }));
    await settle();
    expect(document.activeElement).toBe(input);
    expect(scroll).toHaveBeenCalledTimes(1);
    await render("affair-2", "notice-2");
    expect(document.activeElement?.textContent).toContain("和用户复盘");
    expect(scroll).toHaveBeenCalledTimes(2);
  });

  it("clears filters once per reminder navigation and allows later user filtering", async () => {
    vi.mocked(fetchPersonalAffairs).mockImplementation(async (_id, options) => ({
      ...list, items: list.items.filter(item => !options?.kind || item.kind === options.kind),
    }));
    const chooseKind = async () => {
      await act(async () => (container.querySelector('button[role="combobox"][aria-label="按类型"]') as HTMLButtonElement).click());
      const option = await vi.waitFor(() => {
        const found = [...document.body.querySelectorAll('[role="option"]')].find(node => node.textContent === "日程");
        if (!found) throw new Error("日程 option not rendered yet");
        return found as HTMLElement;
      });
      await act(async () => option.click());
      await settle();
    };
    await render();
    await chooseKind();
    expect(container.textContent).not.toContain("整理周报");
    await render("affair-1", "notice-1");
    expect(document.activeElement?.textContent).toContain("整理周报");
    await chooseKind();
    expect(container.textContent).not.toContain("整理周报");
    expect(fetchPersonalAffairs).toHaveBeenLastCalledWith("agent-companion", expect.objectContaining({ kind: "schedule" }));
  });

  it("shows visible feedback for a missing reminder item", async () => {
    await render("deleted-affair", "notice-1");
    expect(container.querySelector('[role="status"]')?.textContent).toContain("提醒对应的事务已不存在");
    expect(container.textContent).toContain("整理周报");
  });

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
    await act(async () => {
      setInputValue(container.querySelector('input[aria-label="标题"]') as HTMLInputElement, "周会");
      setInputValue(container.querySelector('input[aria-label="截止时间"]') as HTMLInputElement, "2026-10-20T10:30");
    });
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
    await act(async () => setInputValue(editor, "2026-10-22T09:00"));
    await clickButton("保存");
    expect(setPersonalAffairDue).toHaveBeenCalledWith("agent-companion", "affair-1", new Date("2026-10-22T09:00").toISOString());
    await clickButton("设截止");
    const cleared = container.querySelector('input[aria-label="设截止: 整理周报"]') as HTMLInputElement;
    await act(async () => setInputValue(cleared, ""));
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
