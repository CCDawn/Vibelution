/** @vitest-environment happy-dom */
import React, { act, createRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentMessageCenter } from "./AgentMessageCenter";
import { AgentMessageDetail } from "./AgentMessageDetail";
import { AgentMessageSidebar, type AgentMessageSidebarHandle } from "./AgentMessageSidebar";
import { messageMatches, messageSummary } from "./agentMessagePresentation";
import type { AgentMessageRecord } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function record(id: string, patch: Partial<AgentMessageRecord> = {}): AgentMessageRecord {
  return {
    id, sender: { agentId: "sender", name: "发送方" }, type: "request", createdAt: "2026-11-01T10:00:00Z",
    title: "相同标题", body: `正文 ${id}`,
    recipients: [{ agentId: "receiver", name: "接收方", delivery: "delivered", handling: "received" }],
    ...patch,
  };
}

describe("Agent message presentation", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;
  const scrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
  afterEach(async () => {
    if (root) await act(async () => { root?.unmount(); });
    container?.remove();
    root = null;
    vi.restoreAllMocks();
    if (scrollIntoViewDescriptor) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", scrollIntoViewDescriptor);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  });
  async function render(element: React.ReactNode) {
    if (!root) {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
    }
    await act(async () => { root?.render(element); });
  }
  function button(label: string, scope: ParentNode = container): HTMLButtonElement {
    const found = [...scope.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === label);
    expect(found, `Button ${label}`).toBeDefined();
    return found!;
  }
  async function click(element: HTMLElement) { await act(async () => { element.click(); }); }

  it("retains separate rows and exact reply linkage for identical titles", async () => {
    const records = [record("first"), record("second"), record("reply-first", { type: "reply", replyToId: "first", body: "只关联第一条" }), record("reply-second", { type: "reply", replyToId: "second", body: "只关联第二条" })];
    const onSelect = vi.fn();
    await render(<AgentMessageCenter records={records} selectedId="first" onSelect={onSelect} lang="zh" scope="all" onScopeChange={vi.fn()} />);
    expect(container.querySelectorAll("[data-message-id]")).toHaveLength(4);
    const detail = container.querySelector('[data-testid="agent-message-detail"]')!;
    expect(detail.querySelector('[data-reply-id="reply-first"]')).not.toBeNull();
    expect(detail.querySelector('[data-reply-id="reply-second"]')).toBeNull();
    await click(button("在左栏定位这条回复", detail));
    expect(onSelect).toHaveBeenLastCalledWith("reply-first");
    // The caller owns selection: clicking never overwrites controlled detail.
    expect(detail.getAttribute("data-selected-message-id")).toBe("first");
    await render(<AgentMessageDetail records={records} selectedId="reply-second" onSelect={onSelect} lang="zh" />);
    await click(button("查看原消息"));
    expect(onSelect).toHaveBeenLastCalledWith("second");
  });

  it("clears filters and scrolls to an explicitly selected hidden reply", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    const records = [record("request"), record("reply", { type: "reply", replyToId: "request", body: "回复内容" })];
    function Harness() {
      const [selectedId, setSelectedId] = useState("request");
      return <AgentMessageCenter records={records} selectedId={selectedId} onSelect={setSelectedId} lang="zh" scope="all" onScopeChange={vi.fn()} />;
    }
    await render(<Harness />);
    await click(button("待处理"));
    expect(container.querySelector('[data-message-id="reply"]')).toBeNull();
    await click(button("在左栏定位这条回复"));
    expect(container.querySelector('[data-message-id="reply"]')?.getAttribute("aria-pressed")).toBe("true");
    expect(button("全部").getAttribute("aria-pressed")).toBe("true");
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    expect(container.querySelector('[data-testid="agent-message-detail"]')?.getAttribute("data-selected-message-id")).toBe("reply");
  });

  it("reveals the current selection on explicit locate even when its id is unchanged", async () => {
    const ref = createRef<AgentMessageSidebarHandle>();
    await render(<AgentMessageSidebar ref={ref} records={[record("request")]} selectedId="request" onSelect={vi.fn()} lang="zh" scope="current" onScopeChange={vi.fn()} />);
    await click(button("已回复"));
    expect(container.querySelector('[data-message-id="request"]')).toBeNull();
    await act(async () => { ref.current?.locate("request"); });
    expect(container.querySelector('[data-message-id="request"]')).not.toBeNull();
    expect(button("全部").getAttribute("aria-pressed")).toBe("true");
  });

  it("searches sender and message text, then clears search on explicit navigation", async () => {
    const ref = createRef<AgentMessageSidebarHandle>();
    await render(<AgentMessageSidebar ref={ref} records={[record("one", { body: "检索目标" }), record("two", { sender: { agentId: "other", name: "另一个Agent" } })]} selectedId="one" onSelect={vi.fn()} lang="zh" scope="all" onScopeChange={vi.fn()} />);
    const input = container.querySelector<HTMLInputElement>('input[type="search"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "另一个Agent");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.querySelector('[data-message-id="one"]')).toBeNull();
    expect(container.querySelector('[data-message-id="two"]')).not.toBeNull();
    await act(async () => { ref.current?.locate("one"); });
    expect(input.value).toBe("");
    expect(container.querySelectorAll("[data-message-id]")).toHaveLength(2);
  });

  it("keeps selected identity, detail scroll and filters when new messages arrive", async () => {
    const onSelect = vi.fn();
    const first = record("reading");
    const renderCenter = (records: AgentMessageRecord[]) => <AgentMessageCenter records={records} selectedId="reading" onSelect={onSelect} lang="zh" scope="all" onScopeChange={vi.fn()} />;
    await render(renderCenter([first]));
    const detail = container.querySelector<HTMLElement>('[data-testid="agent-message-detail"]')!;
    detail.scrollTop = 240;
    await click(button("待处理"));
    await render(renderCenter([record("newest"), first]));
    expect(onSelect).not.toHaveBeenCalled();
    expect(detail.scrollTop).toBe(240);
    expect(detail.getAttribute("data-selected-message-id")).toBe("reading");
    expect(container.querySelector('[data-message-id="reading"]')?.getAttribute("aria-pressed")).toBe("true");
    expect(button("待处理").getAttribute("aria-pressed")).toBe("true");
  });

  it("preserves the first visible row offset when records prepend", async () => {
    const first = record("reading");
    const renderSidebar = (records: AgentMessageRecord[]) => <AgentMessageSidebar records={records} selectedId={null} onSelect={vi.fn()} lang="zh" scope="all" onScopeChange={vi.fn()} />;
    await render(renderSidebar([first]));
    const list = container.querySelector<HTMLElement>('[data-testid="agent-message-list"]')!;
    const row = container.querySelector<HTMLElement>('[data-message-id="reading"]')!;
    let rowTop = 20;
    vi.spyOn(list, "getBoundingClientRect").mockImplementation(() => ({ top: 10 } as DOMRect));
    vi.spyOn(row, "getBoundingClientRect").mockImplementation(() => ({ top: rowTop, bottom: rowTop + 100 } as DOMRect));
    list.scrollTop = 300;
    await act(async () => { list.dispatchEvent(new Event("scroll")); });
    rowTop = 140;
    await render(renderSidebar([record("new"), first]));
    expect(list.scrollTop).toBe(420);
  });

  it("shows explicit delivery errors and neutral unknown receipts without invented actions", async () => {
    const failed = record("failed", { recipients: [{ agentId: "r", name: "异常方", delivery: "failed", handling: "unknown", error: "目标会话不可用" }] });
    const unknown = record("unknown", { recipients: [{ agentId: "u", name: "待确认方", delivery: "unknown", handling: "unknown" }] });
    await render(<AgentMessageDetail records={[failed, unknown]} selectedId="failed" onSelect={vi.fn()} lang="zh" />);
    expect(container.textContent).toContain("投递失败");
    expect(container.textContent).toContain("目标会话不可用");
    expect(container.textContent).not.toContain("重试");
    await render(<AgentMessageDetail records={[failed, unknown]} selectedId="unknown" onSelect={vi.fn()} lang="zh" />);
    expect(container.textContent).toContain("待确认");
    expect(container.textContent).not.toContain("处理中");
    expect(container.querySelector('[data-tone="danger"]')).toBeNull();
    expect(messageMatches(unknown, "", "exception")).toBe(false);
    expect(messageMatches(failed, "", "exception")).toBe(true);
  });

  it("ends collected notifications while collected requests still require replies", () => {
    const request = record("request");
    const notification = record("notification", { type: "notification" });
    expect(messageMatches(request, "", "pending")).toBe(true);
    expect(messageMatches(notification, "", "pending")).toBe(false);
    expect(messageSummary(request, "zh")).toContain("已收取 · 待回复");
    expect(messageSummary(notification, "zh")).toBe("已送达 · 已收取");
    expect(messageSummary(notification, "zh")).not.toContain("处理中");
  });

  it("keeps group sends in one row and exposes every recipient independently", async () => {
    const group = record("group", { recipients: [
      { agentId: "a", name: "甲", delivery: "delivered", handling: "replied" },
      { agentId: "b", name: "乙", delivery: "failed", handling: "waiting", error: "乙投递失败" },
    ] });
    await render(<AgentMessageCenter records={[group]} selectedId="group" onSelect={vi.fn()} lang="zh" scope="all" onScopeChange={vi.fn()} />);
    expect(container.querySelectorAll("[data-message-id]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-recipient-id]")).toHaveLength(2);
    expect(container.textContent).toContain("1/2 已送达 · 1/2 已回复");
    expect(container.querySelector('[data-recipient-id="b"]')?.textContent).toContain("乙投递失败");
  });

  it("does not substitute another message when selection is missing", async () => {
    await render(<AgentMessageDetail records={[record("available")]} selectedId="missing" onSelect={vi.fn()} lang="zh" />);
    expect(container.textContent).toContain("该消息尚未加载或已不可用");
    expect(container.textContent).not.toContain("正文 available");
  });

  it("exposes loading failures and only calls the supplied reload action", async () => {
    const refresh = vi.fn();
    const changeScope = vi.fn();
    await render(<AgentMessageSidebar records={[]} selectedId={null} onSelect={vi.fn()} lang="zh" scope="all" onScopeChange={changeScope} currentScopeAvailable={false} error="连接失败" onRefresh={refresh} />);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("连接失败");
    expect(container.textContent).not.toContain("暂无跨 Agent 消息");
    expect(button("当前对话").disabled).toBe(true);
    await click(button("当前对话"));
    expect(changeScope).not.toHaveBeenCalled();
    await click(button("重新加载"));
    expect(refresh).toHaveBeenCalledOnce();
    await render(<AgentMessageSidebar records={[]} selectedId={null} onSelect={vi.fn()} lang="en" scope="all" onScopeChange={changeScope} loading />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(container.textContent).toContain("Loading…");
    expect(container.textContent).not.toContain("No agent messages yet");
  });
});
