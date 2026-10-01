// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../api/financialAssistant";
import { FinanceRoute } from "./FinanceRoute";

vi.mock("../api/financialAssistant", () => ({ createFinancialAssistant: vi.fn(), listFinancialAssistants: vi.fn() }));
const { openSession } = vi.hoisted(() => ({ openSession: vi.fn() }));
vi.mock("./chat/useChatRouteSelection", () => ({ useChatRouteSelection: () => ({ openSession }) }));
vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement; let root: Root; let client: QueryClient;
const row: FinancialAssistant = {
  agentId: "finance-a", agentCode: "A001", displayName: "炒股智能体", status: "active",
  setupStatus: "ready", directSessionId: "native-session", knowledgeBaseId: "agent:finance-a:reports",
  knowledgeReadable: true, modelStatus: "configured_unverified", reportStatus: "not_configured",
  newsDelegationStatus: "disabled", marketDataStatus: "not_connected", privateLedgerStatus: "not_implemented",
  tradingEnabled: false,
};
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.clearAllMocks(); });
async function render(state?: unknown) {
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: "/finance", state }]}><FinanceRoute /></MemoryRouter>
    </QueryClientProvider>,
  ));
  await settle();
}
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 15))); }
function button(label: string) { return [...container.querySelectorAll("button")].find((item) => item.textContent?.includes(label)); }

describe("financial assistant entry", () => {
  it("opens a ready chat without creating another assistant", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([row]);
    await render();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(openSession).toHaveBeenCalledWith("native-session", expect.objectContaining({ replace: true, telemetrySource: "financial_assistant_entry" }));
    expect(container.textContent).not.toContain("当前能力");
  });

  it("creates the assistant on first open and then enters its chat", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([]);
    vi.mocked(createFinancialAssistant).mockResolvedValue({ created: true, assistant: row });
    await render();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(openSession).toHaveBeenCalledWith("native-session", expect.objectContaining({ replace: true }));
  });

  it("does not open a chat after the page has gone", async () => {
    let resolve!: (value: FinancialAssistant[]) => void;
    vi.mocked(listFinancialAssistants).mockReturnValue(new Promise((done) => { resolve = done; }));
    await render();
    await act(async () => root.render(<div>another route</div>));
    await act(async () => resolve([row]));
    await settle();
    expect(openSession).not.toHaveBeenCalled();
    expect(container.textContent).toBe("another route");
  });

  it("stops on an archived assistant instead of creating another", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, status: "archived", directSessionId: "", setupStatus: "ready" }]);
    await render();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(openSession).not.toHaveBeenCalled();
    expect(container.textContent).toContain("已归档");
  });

  it("shows a menu failure and retries into the chat", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([row]);
    await render({ financialEntryError: "打开失败" });
    expect(listFinancialAssistants).not.toHaveBeenCalled();
    expect(container.textContent).toContain("打开失败");
    await act(async () => button("重试")!.click());
    await settle();
    expect(openSession).toHaveBeenCalledWith("native-session", expect.objectContaining({ replace: true }));
  });
});
