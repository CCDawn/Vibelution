// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listFinancialAssistants, type FinancialAssistant } from "../../api/financialAssistant";
import { FinancialAssistantChatNote } from "./FinancialAssistantChatNote";
import { FinancialAssistantStatusNote } from "./FinancialAssistantStatusNote";

vi.mock("../../api/financialAssistant", () => ({ listFinancialAssistants: vi.fn(), createFinancialAssistant: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement; let root: Root; let client: QueryClient;
const row: FinancialAssistant = {
  agentId: "finance-a", agentCode: "A086", displayName: "炒股智能体", status: "active",
  setupStatus: "ready", directSessionId: "native-session", knowledgeBaseId: "agent:finance-a:reports",
  knowledgeReadable: true, modelStatus: "configured_unverified", reportStatus: "not_configured",
  newsDelegationStatus: "disabled", marketDataStatus: "not_connected", privateLedgerStatus: "not_implemented",
  tradingEnabled: false,
};
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(listFinancialAssistants).mockResolvedValue([row]);
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.clearAllMocks(); });
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 15))); }

describe("financial assistant chat note", () => {
  it("shows the boundary and the two existing destinations only for that chat", async () => {
    await act(async () => root.render(
      <QueryClientProvider client={client}><MemoryRouter initialEntries={["/finance?session=native-session"]}>
        <FinancialAssistantChatNote sessionId="native-session" lang="zh" />
      </MemoryRouter></QueryClientProvider>,
    ));
    await settle();
    expect(container.textContent).toContain("新闻仅供参考");
    expect(container.textContent).toContain("日、周、月 K 线已接入");
    expect(container.textContent).toContain("公开行情可能延迟");
    expect(container.textContent).toContain("暂无分钟行情");
    expect(container.textContent).toContain("不会自动下单");
    const hrefs = [...container.querySelectorAll("a")].map((anchor) => anchor.getAttribute("href") || "");
    const decoded = hrefs.map((href) => decodeURIComponent(href));
    expect(decoded.some((href) => href.includes("/agents?") && href.includes("finance-a") && href.includes("/finance?session=native-session"))).toBe(true);
    expect(decoded.some((href) => href.includes("/memory/knowledge") && href.includes("view=knowledge") && href.includes("reports") && href.includes("/finance?session=native-session"))).toBe(true);
  });

  it("stays quiet in an ordinary chat", async () => {
    await act(async () => root.render(
      <QueryClientProvider client={client}><MemoryRouter initialEntries={["/chat?session=ordinary-session"]}>
        <FinancialAssistantChatNote sessionId="ordinary-session" lang="zh" />
      </MemoryRouter></QueryClientProvider>,
    ));
    await settle();
    expect(container.textContent).toBe("");
    expect(listFinancialAssistants).not.toHaveBeenCalled();
  });

  it("puts connection status on the matching agent and skips everyone else", async () => {
    await act(async () => root.render(
      <QueryClientProvider client={client}><MemoryRouter>
        <FinancialAssistantStatusNote agentId="finance-a" lang="zh" />
        <FinancialAssistantStatusNote agentId="other-agent" lang="zh" />
      </MemoryRouter></QueryClientProvider>,
    ));
    await settle();
    expect(container.textContent).toContain("已填写，还没验证能不能连上");
    expect(container.textContent).toContain("还没配好");
    expect(container.textContent).toContain("已绑定，可以读取");
    expect(container.querySelectorAll("[data-financial-assistant-note='status']").length).toBe(1);
  });
});
