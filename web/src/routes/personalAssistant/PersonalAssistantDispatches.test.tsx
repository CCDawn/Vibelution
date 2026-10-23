// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchPersonalAssistantDispatches,
  type PersonalAssistantDispatchList,
} from "../../api/personalAssistantDispatches";
import { PersonalAssistantDispatches } from "./PersonalAssistantDispatches";

vi.mock("../../api/personalAssistantDispatches", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/personalAssistantDispatches")>()),
  fetchPersonalAssistantDispatches: vi.fn(),
}));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const list: PersonalAssistantDispatchList = {
  assistantAgentId: "assistant-agent",
  dispatches: [
    {
      messageId: "dispatch-1",
      threadId: "thread-1",
      targetAgentId: "agent-writer",
      targetAgentName: "写作助手",
      targetSessionId: "session-writer",
      summary: "把周报整理成摘要",
      deliveryStatus: "pending",
      sentAt: "2026-10-19T02:00:00Z",
      receipts: [
        { messageId: "receipt-1", sourceAgentId: "agent-writer", sourceAgentName: "写作助手", summary: "周报摘要已完成", status: "consumed", receivedAt: "2026-10-19T03:00:00Z" },
        { messageId: "receipt-2", sourceAgentId: "agent-writer", sourceAgentName: "写作助手", summary: "补充了数据核对", status: "pending", receivedAt: "2026-10-19T03:30:00Z" },
      ],
    },
    {
      messageId: "dispatch-2",
      threadId: null,
      targetAgentId: "agent-research",
      targetAgentName: "调研助手",
      targetSessionId: "session-research",
      summary: "收集竞品价格",
      deliveryStatus: "consumed",
      sentAt: "2026-10-18T02:00:00Z",
      receipts: [],
    },
  ],
  unmatchedReceipts: [
    { messageId: "receipt-3", sourceAgentId: "agent-ops", sourceAgentName: "运维助手", summary: "部署完成", status: "pending", receivedAt: "2026-10-19T05:00:00Z" },
  ],
  generatedAt: "2026-10-19T06:00:00Z",
};

let root: Root, container: HTMLDivElement, client: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistantDispatches).mockResolvedValue(list);
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: () => 0, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}>
    <PersonalAssistantDispatches agentId="assistant-agent" />
  </QueryClientProvider>));
  await settle(); await settle();
}

describe("personal assistant dispatches panel", () => {
  it.each([
    ["blocked", "遇到阻塞"], ["failed", "对方报告失败"], ["completed", "对方报告完成"], ["cancelled", "已取消"],
  ] as const)("renders authoritative task state %s separately from delivery", async (taskStatus, label) => {
    vi.mocked(fetchPersonalAssistantDispatches).mockResolvedValue({
      ...list, dispatches: [{ ...list.dispatches[1], taskStatus }], unmatchedReceipts: [],
    });
    await render();
    expect(container.textContent).toContain("对方已接收");
    expect(container.textContent).toContain(label);
    expect(container.textContent).not.toContain("对方已处理");
  });

  it("renders sent dispatches with status, receipt count and an expandable receipt list", async () => {
    await render();
    expect(container.textContent).toContain("写作助手");
    expect(container.textContent).toContain("把周报整理成摘要");
    expect(container.textContent).toContain("待对方接收");
    expect(container.textContent).toContain("对方已接收");
    expect(container.textContent).toContain("收到回复，结果待确认");
    expect(container.textContent).toContain("进行中");
    expect(container.textContent).not.toContain("对方报告完成");
    expect(container.textContent).toContain("2 条回执");
    expect(container.textContent).not.toContain("周报摘要已完成");
    const expand = container.querySelector('button[aria-label="回执: 写作助手"]') as HTMLButtonElement;
    await act(async () => expand.click()); await settle();
    expect(container.textContent).toContain("周报摘要已完成");
    expect(container.textContent).toContain("已读");
    await act(async () => expand.click()); await settle();
    expect(container.textContent).not.toContain("周报摘要已完成");
  });
  it("shows unmatched receipts and hides the section when there are none", async () => {
    await render();
    expect(container.textContent).toContain("收到的回执（未配对）");
    expect(container.textContent).toContain("运维助手");
    expect(container.textContent).toContain("部署完成");
    vi.mocked(fetchPersonalAssistantDispatches).mockResolvedValue({ ...list, unmatchedReceipts: [] });
    await act(async () => client.invalidateQueries()); await settle(); await settle();
    expect(container.textContent).not.toContain("收到的回执（未配对）");
    expect(container.textContent).not.toContain("运维助手");
  });
  it("keeps the panel actionable with an empty ledger instead of a blank rail", async () => {
    vi.mocked(fetchPersonalAssistantDispatches).mockResolvedValue({
      assistantAgentId: "assistant-agent", dispatches: [], unmatchedReceipts: [], generatedAt: "2026-10-19T06:00:00Z",
    });
    await render();
    expect(container.textContent).toContain("还没有派遣记录");
    expect(container.textContent).toContain("把任务派给");
    expect(container.textContent).not.toContain("派出");
  });
});
